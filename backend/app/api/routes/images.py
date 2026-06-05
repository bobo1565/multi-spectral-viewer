"""
图像管理API路由
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from typing import List, Optional
import os
import json
import tempfile
import cv2
import numpy as np
from pathlib import Path

from app.api.models import ImageUploadResponse, ImageInfo
from app.storage.file_manager import file_manager
from app.database import get_db
from app.services.image_db_service import ImageDBService

router = APIRouter()


@router.post("/upload", response_model=ImageUploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    raw_params: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """上传图像文件"""
    allowed_extensions = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".raw"}
    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式。支持的格式: {', '.join(allowed_extensions)}"
        )

    try:
        content = await file.read()

        if ext == ".raw":
            if not raw_params:
                raise HTTPException(status_code=400, detail="RAW 文件需要提供 raw_params 参数")
            try:
                params = json.loads(raw_params)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="RAW 参数 JSON 格式无效")

            file_info = file_manager.save_uploaded_raw_file(
                content, file.filename,
                width=params["width"],
                height=params["height"],
                bit_depth=params.get("bit_depth", 8),
                channels=params.get("channels", 1),
                byte_order=params.get("byte_order", "little")
            )
        else:
            file_info = file_manager.save_uploaded_file(content, file.filename)

        ImageDBService.create_image(db, file_info)
        return ImageUploadResponse(**file_info)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")


def _build_image_list_url(img) -> str:
    """根据图像类型构建正确的URL"""
    filepath = Path(img.filepath)
    try:
        if filepath.exists() and filepath.is_file():
            upload_dir = file_manager.upload_dir.resolve()
            resolved = filepath.resolve()
            if os.path.commonpath([str(resolved), str(upload_dir)]) == str(upload_dir):
                return f"/uploads/{resolved.relative_to(upload_dir).as_posix()}"
    except (OSError, ValueError):
        pass

    if img.batch_id:
        # 批次图像: uploads/{batch_id}/{image_type}/{filename}
        img_type = getattr(img, 'image_type', None) or 'source'
        if img_type == 'generated':
            return f"/uploads/original/{img.id}_{img.filename}"
        return f"/uploads/{img.batch_id}/{img_type}/{img.filename}"
    # 独立上传图像: uploads/original/{id}_{filename}
    return f"/uploads/original/{img.id}_{img.filename}"


def _resolve_image_path(image_id: str, db: Session) -> Optional[Path]:
    """按数据库真实路径优先解析图像文件，兼容旧版 original 目录查找。"""
    img = ImageDBService.get_image(db, image_id)
    if img and img.filepath:
        filepath = Path(img.filepath)
        if filepath.exists() and filepath.is_file():
            return filepath

    filepath = file_manager.get_file_path(image_id, "original")
    if filepath and filepath.exists() and filepath.is_file():
        return filepath
    return None


@router.get("/", response_model=List[ImageInfo])
async def list_images(db: Session = Depends(get_db)):
    """获取所有上传的图像列表"""
    # 从数据库获取
    db_images = ImageDBService.get_all_images(db)

    result = []
    for img in db_images:
        result.append(ImageInfo(
            id=img.id,
            filename=img.filename,
            filepath=img.filepath,
            url=_build_image_list_url(img),
            size=img.file_size,
            width=img.width,
            height=img.height,
            channels=img.channels,
            upload_time=img.upload_time
        ))

    return result


@router.get("/{image_id}")
async def get_image(image_id: str, db: Session = Depends(get_db)):
    """获取单个图像文件"""
    filepath = _resolve_image_path(image_id, db)

    if not filepath or not filepath.exists():
        raise HTTPException(status_code=404, detail="图像不存在")

    return FileResponse(str(filepath))


@router.get("/{image_id}/tiff-preview")
async def get_tiff_preview(image_id: str, db: Session = Depends(get_db)):
    """将 TIFF 图像归一化为 8-bit PNG 供浏览器显示"""
    filepath = _resolve_image_path(image_id, db)

    if not filepath or not filepath.exists():
        raise HTTPException(status_code=404, detail="图像不存在")

    if not filepath.suffix.lower() in ('.tif', '.tiff'):
        raise HTTPException(status_code=400, detail="该图像不是 TIFF 格式")

    img = cv2.imread(str(filepath), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise HTTPException(status_code=500, detail="无法读取 TIFF 图像")

    # 归一化到 8-bit
    if img.dtype == np.uint16:
        max_val = img.max()
        if max_val > 0:
            img = (img.astype(np.float32) / max_val * 255).astype(np.uint8)
        else:
            img = img.astype(np.uint8)
    elif img.dtype != np.uint8:
        img = img.astype(np.uint8)

    # 灰度图转 3 通道以便浏览器渲染
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    # 编码为 PNG
    success, buf = cv2.imencode('.png', img)
    if not success:
        raise HTTPException(status_code=500, detail="PNG 编码失败")

    return Response(content=buf.tobytes(), media_type="image/png")


@router.get("/{image_id}/tiff-data")
async def get_tiff_data(image_id: str, db: Session = Depends(get_db)):
    """返回 TIFF 图像的原始像素数据（16-bit），供前端 WebGL 精确渲染"""
    import base64

    filepath = _resolve_image_path(image_id, db)

    if not filepath or not filepath.exists():
        raise HTTPException(status_code=404, detail="图像不存在")

    if not filepath.suffix.lower() in ('.tif', '.tiff'):
        raise HTTPException(status_code=400, detail="该图像不是 TIFF 格式")

    img = cv2.imread(str(filepath), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise HTTPException(status_code=500, detail="无法读取 TIFF 图像")

    # 确保是二维数组（灰度）
    if len(img.shape) == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    height, width = img.shape
    bit_depth = 16 if img.dtype == np.uint16 else 8

    # 转为 Uint16Array（统一按 16-bit 存储）
    if img.dtype == np.uint8:
        data = img.astype(np.uint16)
    else:
        data = img

    data_min = int(data.min())
    data_max = int(data.max())

    # base64 编码
    encoded = base64.b64encode(data.tobytes()).decode('ascii')

    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "data_min": data_min,
        "data_max": data_max,
        "data": encoded,
    }
 
 
@router.get("/processed/{filename}")
async def get_processed_image(filename: str):
    """获取处理后的图像文件（如植被指数图）"""
    filepath = file_manager.processed_dir / filename
    
    if not filepath or not filepath.exists():
        raise HTTPException(status_code=404, detail="处理后的图像不存在")
    
    return FileResponse(str(filepath))


@router.delete("/{image_id}")
async def delete_image(
    image_id: str,
    db: Session = Depends(get_db)
):
    """删除图像"""
    # 先删除数据库记录
    db_deleted = ImageDBService.delete_image(db, image_id)
    
    # 再删除物理文件 (即使数据库没记录，也尝试删除物理文件，保持清理)
    file_deleted = file_manager.delete_file(image_id)
    
    if not db_deleted and not file_deleted:
        raise HTTPException(status_code=404, detail="图像不存在")
    
    return {"message": "删除成功", "id": image_id}
