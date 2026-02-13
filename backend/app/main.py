"""
FastAPI主应用入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from pathlib import Path

# 获取项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
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

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

from app.api.routes import images, processing, blending, vegetation, alignment, batches
from app.database import engine, Base, SessionLocal
from app.services.image_db_service import ImageDBService
from app.storage.file_manager import file_manager

# 注册路由
app.include_router(images.router, prefix="/api/images", tags=["images"])
app.include_router(processing.router, prefix="/api/processing", tags=["processing"])
app.include_router(blending.router, prefix="/api/blending", tags=["blending"])
app.include_router(vegetation.router, prefix="/api/vegetation", tags=["vegetation"])
app.include_router(alignment.router, prefix="/api/alignment", tags=["alignment"])
app.include_router(batches.router, prefix="/api/batches", tags=["batches"])


@app.on_event("startup")
async def startup_event():
    # 初始化数据库表
    Base.metadata.create_all(bind=engine)
    
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
    """从文件名检测波段类型"""
    lower = filename.lower()
    if 'rgb' in lower:
        return 'rgb'
    elif '570' in lower:
        return '570nm'
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


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

