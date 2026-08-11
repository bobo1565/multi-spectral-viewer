"""
FastAPI主应用入口
"""
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
import os
from pathlib import Path


class CacheControlMiddleware(BaseHTTPMiddleware):
    """按路径前缀设置缓存策略。

    - /api/ 数据接口：强制禁用缓存。抓拍后前端立即 listBatches() 刷新，若该 GET
      无 freshness 指令，浏览器会“启发式缓存”复用旧响应，导致新批次找不到、
      主图空白，需手动清缓存。no-store 杜绝该问题。
    - /uploads/ 静态图片：允许浏览器缓存（max-age=3600）。这类文件名含 UUID 且
      写入后不变，缓存安全；切页面后回来可直接用本地缓存，无需重新下载/解码，
      显著加快分析页图像显示（尤其从实时监控切回时不再受连接竞争影响）。
    """

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif path.startswith("/uploads/"):
            response.headers["Cache-Control"] = "public, max-age=3600"
        return response

# 获取项目根目录
import os; PROJECT_ROOT = Path("/app") if os.getenv("ENV") == "production" else Path(__file__).parent.parent.parent
UPLOAD_DIR = str(PROJECT_ROOT / "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(
    title="多光谱图像分析系统",
    description="Multispectral Image Analysis System API",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 注意：中间件按“后注册先执行”的顺序，CacheControlMiddleware 注册在
# CORSMiddleware 之后，会在 CORS 处理完毕后按路径追加缓存头。
app.add_middleware(CacheControlMiddleware)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

from app.api.routes import images, processing, blending, vegetation, alignment, align3d, batches, cameras, capture
from app.database import engine, Base, SessionLocal
from app.services.image_db_service import ImageDBService
from app.storage.file_manager import file_manager
from app.camera import get_camera_service

# 注册路由
app.include_router(images.router, prefix="/api/images", tags=["images"])
app.include_router(processing.router, prefix="/api/processing", tags=["processing"])
app.include_router(blending.router, prefix="/api/blending", tags=["blending"])
app.include_router(vegetation.router, prefix="/api/vegetation", tags=["vegetation"])
app.include_router(alignment.router, prefix="/api/alignment", tags=["alignment"])
app.include_router(align3d.router, prefix="/api/align3d", tags=["align3d"])
app.include_router(batches.router, prefix="/api/batches", tags=["batches"])
app.include_router(cameras.router, prefix="/api/cameras", tags=["cameras"])
app.include_router(capture.router, prefix="/api/capture", tags=["capture"])


@app.on_event("startup")
async def startup_event():
    # 初始化数据库表
    Base.metadata.create_all(bind=engine)

    # 自动迁移：为已有 cameras 表补充 is_monitoring 列
    try:
        from sqlalchemy import text, inspect as sa_inspect
        inspector = sa_inspect(engine)
        columns = [c['name'] for c in inspector.get_columns('cameras')]
        if 'is_monitoring' not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE cameras ADD COLUMN is_monitoring INTEGER DEFAULT 1"))
                conn.commit()
            print("[Startup] 已为 cameras 表添加 is_monitoring 列")
    except Exception as e:
        print(f"[Startup] 添加 is_monitoring 列（表可能尚不存在）: {e}")

    # 自动迁移：波段标签 570nm 统一更名为 560nm（images 与 cameras 两张表）
    try:
        from sqlalchemy import text
        total = 0
        with engine.connect() as conn:
            for table in ("images", "cameras"):
                result = conn.execute(
                    text(f"UPDATE {table} SET band_type='560nm' WHERE band_type='570nm'")
                )
                total += result.rowcount or 0
            conn.commit()
        if total:
            print(f"[Startup] 已将 {total} 条记录的波段标签 570nm 更名为 560nm")
    except Exception as e:
        print(f"[Startup] 波段更名迁移失败: {e}")

    # 初始化摄像头服务（StreamManager + CameraDiscovery 单例）
    camera_service = get_camera_service()

    # 一次性迁移 cameras_db.json → Camera 表
    try:
        from app.services.camera_db_service import CameraDBService
        migrated = CameraDBService.migrate_from_json(SessionLocal)
        if migrated:
            print(f"[Startup] 已从 cameras_db.json 迁移 {migrated} 个摄像头到数据库")
        ensured = CameraDBService.ensure_default_cameras(SessionLocal)
        if ensured["created"] or ensured["updated"]:
            print(
                f"[Startup] 默认摄像头已校准: 新增 {ensured['created']} 台, "
                f"更新 {ensured['updated']} 台"
            )
    except Exception as e:
        print(f"[Startup] 摄像头 JSON 迁移失败: {e}")

    # 导入所需模块
    import cv2
    import uuid
    from pathlib import Path
    from datetime import datetime
    from app.services.batch_db_service import BatchDBService
    
    db = SessionLocal()
    try:
        upload_dir = Path(UPLOAD_DIR)
        
        # 1. 扫描批次目录（UUID格式的目录）
        for item in upload_dir.iterdir():
            if item.is_dir() and len(item.name) == 36 and '-' in item.name:
                # 看起来像 UUID 格式的目录
                batch_id = item.name
                
                # 检查批次是否已存在于数据库
                existing_batch = BatchDBService.get_batch(db, batch_id)
                if not existing_batch:
                    # 创建批次
                    print(f"[Startup] Restoring batch: {batch_id}")
                    try:
                        from app import db_models
                        batch = db_models.Batch(
                            id=batch_id,
                            name=batch_id[:8],  # 使用 ID 前8位作为默认名称
                            created_at=datetime.fromtimestamp(item.stat().st_mtime)
                        )
                        db.add(batch)
                        db.commit()
                    except Exception as e:
                        print(f"[Startup] Failed to create batch {batch_id}: {e}")
                        db.rollback()
                        continue
                
                # 2. 扫描 source 目录
                source_dir = item / "source"
                if source_dir.exists():
                    for img_file in source_dir.iterdir():
                        if img_file.is_file() and img_file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.tif', '.tiff']:
                            _import_image_file(db, img_file, batch_id, "source")
                
                # 3. 扫描 aligned 目录
                aligned_dir = item / "aligned"
                if aligned_dir.exists():
                    for img_file in aligned_dir.iterdir():
                        if img_file.is_file() and img_file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.tif', '.tiff']:
                            _import_image_file(db, img_file, batch_id, "aligned")
        
        # 4. 同步 original 目录中的旧格式文件
        files = file_manager.list_files()
        for file_data in files:
            if not ImageDBService.exists(db, file_data["id"]):
                print(f"[Startup] Importing legacy file: {file_data['filename']}")
                try:
                    img = cv2.imread(file_data["filepath"])
                    if img is not None:
                        height, width = img.shape[:2]
                        channels = img.shape[2] if len(img.shape) == 3 else 1
                        
                        file_data["width"] = width
                        file_data["height"] = height
                        file_data["channels"] = channels
                        file_data["image_type"] = "source"
                        
                        ImageDBService.create_image(db, file_data)
                except Exception as e:
                    print(f"[Startup] Failed to import {file_data['filename']}: {e}")
                    
    finally:
        db.close()


def _import_image_file(db, img_file: 'Path', batch_id: str, image_type: str):
    """导入单个图像文件到数据库"""
    import cv2
    import uuid
    from pathlib import Path
    from datetime import datetime
    
    # 生成或解析文件ID
    # 文件名可能是 UUID_originalname.ext 或 originalname_aligned.ext
    filename = img_file.name
    
    # 尝试从文件名解析UUID
    parts = filename.split('_', 1)
    if len(parts) >= 2 and len(parts[0]) == 36 and '-' in parts[0]:
        file_id = parts[0]
    else:
        # 使用文件路径哈希作为稳定ID
        file_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(img_file)))
    
    # 检查是否已存在
    if ImageDBService.exists(db, file_id):
        return
    
    # 解析波段类型
    band_type = _detect_band_type(filename)
    
    try:
        img = cv2.imread(str(img_file))
        if img is None:
            print(f"[Startup] Cannot read image: {img_file}")
            return
            
        height, width = img.shape[:2]
        channels = img.shape[2] if len(img.shape) == 3 else 1
        
        image_data = {
            "id": file_id,
            "batch_id": batch_id,
            "band_type": band_type,
            "image_type": image_type,
            "filename": filename,
            "filepath": str(img_file),
            "size": img_file.stat().st_size,
            "width": width,
            "height": height,
            "channels": channels,
        }
        
        ImageDBService.create_image(db, image_data)
        print(f"[Startup] Restored image: {filename} ({image_type})")
        
    except Exception as e:
        print(f"[Startup] Failed to import {img_file}: {e}")


def _detect_band_type(filename: str) -> str:
    """从文件名检测波段类型（旧文件中的 570 标注统一视为 560nm 波段）"""
    lower = filename.lower()
    if 'rgb' in lower:
        return 'rgb'
    elif '560' in lower or '570' in lower:
        return '560nm'
    elif '650' in lower:
        return '650nm'
    elif '730' in lower:
        return '730nm'
    elif '850' in lower:
        return '850nm'
    else:
        return 'rgb'  # 默认


@app.get("/")
async def root():
    return {
        "message": "多光谱图像分析系统 API",
        "version": "2.0.0",
        "docs": "/docs",
        "db": "SQLite enabled"
    }


@app.on_event("shutdown")
async def shutdown_event():
    """关闭所有摄像头流，避免子线程泄漏"""
    try:
        get_camera_service().shutdown()
    except Exception as e:
        print(f"[Shutdown] 关闭摄像头流失败: {e}")


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
