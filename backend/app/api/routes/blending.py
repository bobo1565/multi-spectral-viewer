"""
多光谱混合API路由
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import cv2
import numpy as np
import io
from pathlib import Path

from app.api.models import BlendingRequest, SpectralCurveRequest, SpectralCurveResponse
from app.storage.file_manager import file_manager
from app.api.routes.processing import numpy_to_bytes
from app.database import get_db
from app.services.image_db_service import ImageDBService

router = APIRouter()


def get_channel_from_image(db: Session, image_id: str, channel: str) -> np.ndarray:
    """从图像中提取指定通道"""
    # 首先从数据库查找图像路径
    image = ImageDBService.get_image(db, image_id)
    if image and image.filepath:
        filepath = Path(image.filepath)
    else:
        # 回退到file_manager（兼容旧代码）
        filepath = file_manager.get_file_path(image_id, "original")
    
    if not filepath or not filepath.exists():
        raise HTTPException(status_code=404, detail=f"图像不存在: {image_id}")
    
    img = cv2.imread(str(filepath))
    if img is None:
        raise HTTPException(status_code=500, detail=f"无法读取图像: {image_id}")
    
    if channel == "gray":
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    elif channel == "r":
        return img[:, :, 2]
    elif channel == "g":
        return img[:, :, 1]
    elif channel == "b":
        return img[:, :, 0]
    else:
        raise HTTPException(status_code=400, detail=f"不支持的通道: {channel}")


@router.post("/create")
async def create_blended_image(request: BlendingRequest, db: Session = Depends(get_db)):
    """创建混合图像"""
    # 提取所有波段的图像通道
    band_images = {}
    
    for band_name, band_sel in request.bands.items():
        channel_img = get_channel_from_image(db, band_sel.image_id, band_sel.channel)
        band_images[band_name] = channel_img
    
    # 确保所有图像尺寸一致
    first_img = list(band_images.values())[0]
    target_shape = first_img.shape
    
    for band_name, img in band_images.items():
        if img.shape != target_shape:
            band_images[band_name] = cv2.resize(img, (target_shape[1], target_shape[0]))
    
    # 加权混合
    result = np.zeros(target_shape, dtype=np.float32)
    total_weight = sum(request.weights.values())
    
    if total_weight == 0:
        raise HTTPException(status_code=400, detail="总权重不能为0")
    
    for band_name, img in band_images.items():
        weight = request.weights.get(band_name, 0) / total_weight
        result += img.astype(np.float32) * weight
    
    result = np.clip(result, 0, 255).astype(np.uint8)
    
    # 转换为RGB显示(三通道相同)
    result_rgb = cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
    
    img_bytes = numpy_to_bytes(result_rgb)
    return StreamingResponse(io.BytesIO(img_bytes), media_type="image/jpeg")


@router.post("/spectral-curve", response_model=SpectralCurveResponse)
async def get_spectral_curve(request: SpectralCurveRequest, db: Session = Depends(get_db)):
    """获取指定像素位置的光谱曲线"""
    # 波段到波长的映射
    wavelength_map = {
        "570nm": 570,
        "650nm": 650,
        "730nm": 730,
        "850nm": 850
    }
    
    wavelengths = []
    values = []
    
    for band_name, band_sel in request.bands.items():
        # 获取图像
        channel_img = get_channel_from_image(db, band_sel.image_id, band_sel.channel)
        
        # 检查坐标是否在范围内
        h, w = channel_img.shape[:2]
        if request.x < 0 or request.x >= w or request.y < 0 or request.y >= h:
            raise HTTPException(status_code=400, detail="坐标超出图像范围")
        
        # 获取像素值
        pixel_value = float(channel_img[request.y, request.x])
        
        # 记录波长和值
        if band_name in wavelength_map:
            wavelengths.append(wavelength_map[band_name])
            values.append(pixel_value)
    
    # 按波长排序
    sorted_data = sorted(zip(wavelengths, values))
    wavelengths = [w for w, _ in sorted_data]
    values = [v for _, v in sorted_data]
    
    return SpectralCurveResponse(wavelengths=wavelengths, values=values)

