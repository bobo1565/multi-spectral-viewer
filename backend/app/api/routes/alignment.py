from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
UPLOAD_DIR = str(PROJECT_ROOT / "uploads")

from app.core.image_aligner_service import ImageAlignerService, load_roi_config, save_roi_config
from app.database import get_db
from app.services.image_db_service import ImageDBService
from app.services.batch_db_service import BatchDBService
from app.api.models import BAND_TYPES

router = APIRouter()

class ROICoords(BaseModel):
    x: float
    y: float
    width: float
    height: float

class ROIConfigResponse(BaseModel):
    roi_x_ratio: float
    roi_y_ratio: float
    roi_width_ratio: float
    roi_height_ratio: float

class ROIConfigUpdateRequest(BaseModel):
    roi_x_ratio: float
    roi_y_ratio: float
    roi_width_ratio: float
    roi_height_ratio: float


@router.get("/roi-config", response_model=ROIConfigResponse)
async def get_roi_config():
    """获取当前默认 ROI 配置"""
    config = load_roi_config()
    return config


@router.put("/roi-config", response_model=ROIConfigResponse)
async def update_roi_config(request: ROIConfigUpdateRequest):
    """更新默认 ROI 配置（写入 matching.json，立即生效）"""
    new_config = {
        "roi_x_ratio": request.roi_x_ratio,
        "roi_y_ratio": request.roi_y_ratio,
        "roi_width_ratio": request.roi_width_ratio,
        "roi_height_ratio": request.roi_height_ratio,
    }
    save_roi_config(new_config)
    return new_config





class AlignmentBatchRequest(BaseModel):
    batch_id: str
    overwrite: bool = True
    reference_image_id: Optional[str] = None
    roi: Optional[ROICoords] = None

class NewFileInfo(BaseModel):
    id: str
    filename: str
    size: int
    width: int
    height: int
    channels: int

class AlignmentResultItem(BaseModel):
    image_id: str
    success: bool
    message: str
    new_file: Optional[NewFileInfo] = None

class AlignmentBatchResponse(BaseModel):
    summary: str
    details: List[AlignmentResultItem]
    new_images: List[NewFileInfo]

@router.post("/batch-align", response_model=AlignmentBatchResponse)
async def batch_align(request: AlignmentBatchRequest, db: Session = Depends(get_db)):
    """
    批量对齐图像 (New Logic)
    
    1. 检查目录结构，将原图移动到 {batch_id}/source/
    2. 使用指定的参考图像（默认为 RGB）
    3. 对齐其他波段，并将结果保存到 {batch_id}/aligned[_n]/
    """
    batch_id = request.batch_id
    
    # 获取批次信息
    batch_images = BatchDBService.get_batch_images(db, batch_id)
    if not any(batch_images.values()):
        raise HTTPException(status_code=404, detail="批次中没有图像")

    # 定义目录
    upload_root = Path(UPLOAD_DIR)
    batch_dir = upload_root / batch_id
    source_dir = batch_dir / "source"
    
    # 确定输出目录 (Versioning)
    # 如果 aligned 存在，则尝试 aligned_1, aligned_2 ...
    base_aligned_name = "aligned"
    aligned_dir_name = base_aligned_name
    counter = 1
    
    while (batch_dir / aligned_dir_name).exists():
        aligned_dir_name = f"{base_aligned_name}_{counter}"
        counter += 1
        
    aligned_dir = batch_dir / aligned_dir_name
    
    # 确保目录存在
    source_dir.mkdir(parents=True, exist_ok=True)
    aligned_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Alignment Output Directory: {aligned_dir}")
    
    # 1. 移动文件到 source 目录 (如果还在 original 或其他地方)
    img_id_map = {} # path -> image_id
    current_paths = [] # list of paths
    
    files_moved = 0
    
    # 重新整理 batch_images 为 list (因为可能不再是简单的 band 映射)
    # BatchDBService.get_batch_images 返回的是 dict {band: image_obj}
    # 但我们需要更灵活的处理，特别是当用户指定了非 RGB 为 reference 时
    
    # 获取所有 Source 类型的图像 (如果 image_type 为 None 或空，默认视为 source)
    source_images = []
    for band, img in batch_images.items():
        if img:
            img_type = getattr(img, 'image_type', None) or 'source'
            print(f"[Alignment Debug] Image {img.id}: band={band}, image_type={img_type}")
            if img_type == 'source':
                source_images.append(img)
                
                current_path = Path(img.filepath)
                
                # 如果文件不在 source_dir 下，移动它
                if source_dir.resolve() not in current_path.resolve().parents:
                    new_path = source_dir / current_path.name
                    try:
                        if current_path.exists():
                            print(f"Moving {current_path} to {new_path}")
                            shutil.move(str(current_path), str(new_path))
                            
                            # 更新数据库
                            img.filepath = str(new_path)
                            db.commit()
                            files_moved += 1
                            current_path = new_path
                        else:
                            print(f"Warning: File not found {current_path}")
                    except Exception as e:
                        print(f"Error moving file {current_path}: {e}")
                
                img_id_map[str(current_path.absolute())] = img.id

    if files_moved > 0:
        print(f"Moved {files_moved} files to source directory")

    # 2. 确定参考图像和目标图像
    ref_image_obj = None
    
    if request.reference_image_id:
        # 查找指定的 image
        for img in source_images:
            if img.id == request.reference_image_id:
                ref_image_obj = img
                break
        if not ref_image_obj:
             raise HTTPException(status_code=400, detail="指定的参考图像不存在或不是 Source 类型")
    else:
        # 默认使用 RGB
        ref_image_obj = batch_images.get('rgb')
        if not ref_image_obj:
             raise HTTPException(status_code=400, detail="未找到RGB图像，请指定参考图像")

    ref_path = str(Path(ref_image_obj.filepath).absolute())
    target_paths = []
    
    for img in source_images:
        path = str(Path(img.filepath).absolute())
        if path != ref_path:
            target_paths.append(path)

    # 处理自定义 ROI
    custom_roi_dict = None
    if request.roi:
        custom_roi_dict = {
            "roi_x_ratio": request.roi.x,
            "roi_y_ratio": request.roi.y,
            "roi_width_ratio": request.roi.width,
            "roi_height_ratio": request.roi.height
        }

    # 2. 调用对齐服务
    service = ImageAlignerService()
    
    try:
        results = service.align_batch(
            ref_path,
            target_paths,
            str(aligned_dir),
            overwrite=request.overwrite,
            custom_roi=custom_roi_dict
        )
        
        # 3. 处理结果
        response_data = []
        new_images = []
        success_count = 0
        
        for path, (success, msg, new_file_info) in results.items():
            img_id = img_id_map.get(path, "unknown")
            
            result_item = {
                "image_id": img_id,
                "success": success,
                "message": msg,
                "new_file": None
            }
            
            if success:
                success_count += 1
                if new_file_info:
                    # 将生成的对齐图像存入数据库
                    original_img = ImageDBService.get_image(db, img_id)
                    band_type = original_img.band_type if original_img else None
                    
                    try:
                        new_img_obj = ImageDBService.create_image(db, {
                            "id": new_file_info["id"],
                            "batch_id": batch_id,     # 同一批次
                            "band_type": band_type,   # 保持波段类型
                            "image_type": "aligned",  # 标记为对齐后的图像
                            "filename": new_file_info["filename"],
                            "filepath": new_file_info["filepath"],
                            "size": new_file_info["size"],
                            "width": new_file_info["width"],
                            "height": new_file_info["height"],
                            "channels": new_file_info["channels"],
                            "upload_time": datetime.utcnow()
                        })
                        print(f"[Alignment] Saved aligned image to DB: {new_file_info['filename']}")
                        
                        new_file_data = {
                            "id": new_file_info["id"],
                            "filename": new_file_info["filename"],
                            "size": new_file_info["size"],
                            "width": new_file_info["width"],
                            "height": new_file_info["height"],
                            "channels": new_file_info["channels"]
                        }
                        result_item["new_file"] = new_file_data
                        new_images.append(new_file_data)
                        
                    except Exception as e:
                        print(f"[Alignment] Error saving to DB: {e}")

            response_data.append(result_item)
            
        return {
            "summary": f"成功对齐 {success_count} 张图像 (输出目录: {aligned_dir_name})",
            "details": response_data,
            "new_images": new_images
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"对齐过程发生错误: {str(e)}")
