"""
图像管理API路由
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List

from app.api.models import ImageUploadResponse, ImageInfo
from app.storage.file_manager import file_manager
from app.database import get_db
from app.services.image_db_service import ImageDBService

router = APIRouter()


@router.post("/upload", response_model=ImageUploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """上传图像文件"""
    # 检查文件类型
    allowed_extensions = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
    import os
    ext = os.path.splitext(file.filename)[1].lower()
    
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式。支持的格式: {', '.join(allowed_extensions)}"
        )
    
    try:
        # 读取文件内容
        content = await file.read()
        
        # 保存文件
        file_info = file_manager.save_uploaded_file(content, file.filename)
        
        # 保存到数据库
        ImageDBService.create_image(db, file_info)
        
        return ImageUploadResponse(**file_info)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")


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
            url=f"/uploads/original/{img.filename}", # 注意：这里假设静态文件挂载路径
            size=img.file_size,
            width=img.width,
            height=img.height,
            channels=img.channels,
            upload_time=img.upload_time
        ))
    
    return result


@router.get("/{image_id}")
async def get_image(image_id: str):
    """获取单个图像文件"""
    # 这个接口依然依赖物理文件，逻辑不变
    filepath = file_manager.get_file_path(image_id, "original")
    
    if not filepath or not filepath.exists():
        raise HTTPException(status_code=404, detail="图像不存在")
    
    return FileResponse(str(filepath))
 
 
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
