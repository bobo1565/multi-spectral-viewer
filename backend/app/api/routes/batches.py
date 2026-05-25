"""
批次管理API路由
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from sqlalchemy.orm import Session
from typing import List, Optional
import os
from pathlib import Path

import os; PROJECT_ROOT = Path("/app") if os.getenv("ENV") == "production" else Path(__file__).parent.parent.parent.parent.parent
UPLOAD_DIR = str(PROJECT_ROOT / "uploads")

from app.api.models import BatchCreate, BatchInfo, BatchImageInfo, BAND_TYPES, ImageRenameRequest, BatchRenameRequest
from app.storage.file_manager import file_manager
from app.database import get_db
from app.services.batch_db_service import BatchDBService
from app.services.image_db_service import ImageDBService

router = APIRouter()


def _image_to_batch_image_info(img) -> Optional[BatchImageInfo]:
    """将数据库图像模型转换为BatchImageInfo"""
    if img is None:
        return None
    
    rel_path = os.path.relpath(img.filepath, UPLOAD_DIR)
    url = f"/uploads/{rel_path}"
    print(f"[BatchImageInfo] filepath={img.filepath}, rel_path={rel_path}, url={url}")
    
    return BatchImageInfo(
        id=img.id,
        band_type=img.band_type or "",
        filename=img.filename,
        filepath=img.filepath,
        url=url,
        size=img.file_size,
        width=img.width,
        height=img.height,
        channels=img.channels,
        upload_time=img.upload_time
    )


def _batch_to_batch_info(batch, db: Session) -> BatchInfo:
    """将数据库批次模型转换为BatchInfo"""
    all_images = BatchDBService.get_all_batch_images_list(db, batch.id)
    
    source_images = {}
    aligned_images = {}
    generated_images = []
    
    for img in all_images:
        info = _image_to_batch_image_info(img)
        if not info:
            continue
        
        img_type = getattr(img, 'image_type', None) or ('aligned' if '/aligned/' in img.filepath else (
            'generated' if '/generated/' in img.filepath else 'source'))
        
        if img_type == 'aligned':
            aligned_images[img.band_type] = info
        elif img_type == 'generated':
            generated_images.append(info)
        else:
            source_images[img.band_type] = info

    return BatchInfo(
        id=batch.id,
        name=batch.name,
        created_at=batch.created_at,
        images=source_images,
        source_images=source_images,
        aligned_images=aligned_images,
        generated_images=generated_images
    )


@router.post("/", response_model=BatchInfo)
async def create_batch(
    batch_data: BatchCreate,
    db: Session = Depends(get_db)
):
    """创建新批次"""
    batch = BatchDBService.create_batch(db, batch_data.name)
    return _batch_to_batch_info(batch, db)


@router.get("/", response_model=List[BatchInfo])
async def list_batches(db: Session = Depends(get_db)):
    """获取所有批次列表"""
    batches = BatchDBService.get_all_batches(db)
    return [_batch_to_batch_info(batch, db) for batch in batches]


@router.get("/{batch_id}", response_model=BatchInfo)
async def get_batch(batch_id: str, db: Session = Depends(get_db)):
    """获取单个批次详情"""
    batch = BatchDBService.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    return _batch_to_batch_info(batch, db)


@router.delete("/{batch_id}")
async def delete_batch(batch_id: str, db: Session = Depends(get_db)):
    """删除批次及其所有图像"""
    batch = BatchDBService.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    
    # 删除批次中所有图像的物理文件
    all_images = BatchDBService.get_all_batch_images_list(db, batch_id)
    for img in all_images:
        try:
            file_manager.delete_file(img.id)
        except Exception as e:
            print(f"[BatchDelete] 物理文件删除失败 {img.id}: {e}")
    
    # 删除批次（会级联删除数据库中的图像记录）
    BatchDBService.delete_batch(db, batch_id)
    
    return {"message": "批次删除成功", "id": batch_id}


@router.delete("/{batch_id}/images/{image_type}")
async def delete_batch_images_by_type(batch_id: str, image_type: str, db: Session = Depends(get_db)):
    """删除批次中指定类型（source 或 aligned）的所有图像"""
    batch = BatchDBService.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
        
    if image_type not in ["source", "aligned", "generated"]:
        raise HTTPException(status_code=400, detail="未知的图像类型，只能是 'source'、'aligned' 或 'generated'")
        
    all_images = BatchDBService.get_all_batch_images_list(db, batch_id)
    deleted_count = 0
    
    for img in all_images:
        current_type = getattr(img, 'image_type', None) or ('aligned' if '/aligned/' in img.filepath else (
            'generated' if '/generated/' in img.filepath else 'source'))
        if current_type == image_type:
            # 物理文件删除
            try:
                file_manager.delete_file(img.id)
            except Exception as e:
                print(f"[BatchDelete] 物理文件删除失败 {img.id}: {e}")
            # 数据库记录删除
            ImageDBService.delete_image(db, img.id)
            deleted_count += 1
            
    return {"message": f"成功删除 {deleted_count} 个 {image_type} 图像"}


@router.post("/{batch_id}/import", response_model=BatchInfo)
async def import_batch_images(
    batch_id: str,
    rgb: Optional[UploadFile] = File(None),
    band_570nm: Optional[UploadFile] = File(None),
    band_650nm: Optional[UploadFile] = File(None),
    band_730nm: Optional[UploadFile] = File(None),
    band_850nm: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """导入图像到批次"""
    batch = BatchDBService.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    
    allowed_extensions = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
    
    # 映射文件到波段
    files_map = {
        "rgb": rgb,
        "570nm": band_570nm,
        "650nm": band_650nm,
        "730nm": band_730nm,
        "850nm": band_850nm
    }
    
    for band_type, file in files_map.items():
        if file is None or file.filename == "":
            continue
            
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"{band_type} 文件格式不支持。支持的格式: {', '.join(allowed_extensions)}"
            )
        
        try:
            content = await file.read()
            file_info = file_manager.save_uploaded_file(content, file.filename)
            
            # 保存到数据库，添加批次和波段信息
            file_info["batch_id"] = batch_id
            file_info["band_type"] = band_type
            ImageDBService.create_image(db, file_info)
            
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"{band_type} 文件上传失败: {str(e)}")
    
    return _batch_to_batch_info(batch, db)


@router.patch("/{batch_id}", response_model=BatchInfo)
async def rename_batch(batch_id: str, body: BatchRenameRequest, db: Session = Depends(get_db)):
    """重命名批次"""
    batch = BatchDBService.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    
    batch.name = body.new_name
    db.commit()
    db.refresh(batch)
    return _batch_to_batch_info(batch, db)


@router.patch("/{batch_id}/images/{image_id}")
async def rename_image(batch_id: str, image_id: str, body: ImageRenameRequest, db: Session = Depends(get_db)):
    """重命名图像文件"""
    batch = BatchDBService.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    
    img = ImageDBService.get_image(db, image_id)
    if not img or img.batch_id != batch_id:
        raise HTTPException(status_code=404, detail="图像不存在")
    
    img.filename = body.new_filename
    db.commit()
    return {"message": "重命名成功", "filename": body.new_filename}


@router.post("/{batch_id}/generated", response_model=BatchImageInfo)
async def add_generated_image(
    batch_id: str,
    filepath: str = Form(...),
    filename: str = Form(...),
    width: int = Form(...),
    height: int = Form(...),
    channels: int = Form(3),
    file_size: int = Form(0),
    db: Session = Depends(get_db)
):
    """将植被指数等临时结果保存为批次的 generated 图像"""
    import shutil
    import uuid as _uuid
    batch = BatchDBService.get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    
    image_id = str(_uuid.uuid4())
    safe_name = os.path.basename(filename).replace(" ", "_")
    dest_filename = f"{image_id}_{safe_name}"
    dest_path = os.path.join(UPLOAD_DIR, "original", dest_filename)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    
    if os.path.exists(filepath):
        shutil.copy2(filepath, dest_path)
        if file_size == 0:
            file_size = os.path.getsize(dest_path)
    else:
        dest_path = filepath
    
    image_data = {
        "id": image_id,
        "batch_id": batch_id,
        "band_type": "generated",
        "image_type": "generated",
        "filename": filename,
        "filepath": dest_path,
        "size": file_size,
        "width": width,
        "height": height,
        "channels": channels,
    }
    db_img = ImageDBService.create_image(db, image_data)
    
    return BatchImageInfo(
        id=db_img.id,
        band_type=db_img.band_type or "generated",
        filename=db_img.filename,
        filepath=db_img.filepath,
        url=f"/uploads/{os.path.relpath(db_img.filepath, UPLOAD_DIR)}",
        size=db_img.file_size,
        width=db_img.width,
        height=db_img.height,
        channels=db_img.channels,
        upload_time=db_img.upload_time
    )
