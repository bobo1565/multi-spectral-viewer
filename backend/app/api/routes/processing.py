"""
图像处理API路由
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import cv2
import numpy as np
import io
from PIL import Image

from app.api.models import (
    WhiteBalanceRequest,
    SaturationRequest,
    ChannelGainRequest,
    HistogramResponse
)
from app.storage.file_manager import file_manager
from app.core.algorithms import (
    apply_white_balance,
    adjust_saturation,
    apply_channel_gains,
    calculate_histogram,
    auto_stretch_all_channels
)

router = APIRouter()


def numpy_to_bytes(img: np.ndarray) -> bytes:
    """将NumPy数组转换为JPEG字节流"""
    # 转换为RGB (PIL需要)
    if len(img.shape) == 3 and img.shape[2] == 3:
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    else:
        img_rgb = img
    
    # 转换为PIL Image
    pil_img = Image.fromarray(img_rgb)
    
    # 保存到字节流
    byte_io = io.BytesIO()
    pil_img.save(byte_io, format='JPEG', quality=95)
    byte_io.seek(0)
    
    return byte_io.getvalue()


@router.post("/white-balance")
async def apply_white_balance_adjustment(request: WhiteBalanceRequest):
    """应用白平衡调节"""
    filepath = file_manager.get_file_path(request.image_id, "original")
    
    if not filepath or not filepath.exists():
        raise HTTPException(status_code=404, detail="图像不存在")
    
    # 读取图像
    img = cv2.imread(str(filepath))
    if img is None:
        raise HTTPException(status_code=500, detail="无法读取图像")
    
    # 应用白平衡
    result = apply_white_balance(img, request.r_gain, request.g_gain, request.b_gain)
    
    # 转换为字节流返回
    img_bytes = numpy_to_bytes(result)
    
    return StreamingResponse(io.BytesIO(img_bytes), media_type="image/jpeg")


@router.post("/saturation")
async def apply_saturation_adjustment(request: SaturationRequest):
    """应用饱和度调节"""
    filepath = file_manager.get_file_path(request.image_id, "original")
    
    if not filepath or not filepath.exists():
        raise HTTPException(status_code=404, detail="图像不存在")
    
    img = cv2.imread(str(filepath))
    if img is None:
        raise HTTPException(status_code=500, detail="无法读取图像")
    
    # 应用饱和度调节
    result = adjust_saturation(img, request.factor)
    
    img_bytes = numpy_to_bytes(result)
    return StreamingResponse(io.BytesIO(img_bytes), media_type="image/jpeg")


@router.post("/channel-gain")
async def apply_channel_gain_adjustment(request: ChannelGainRequest):
    """应用通道增益调节"""
    filepath = file_manager.get_file_path(request.image_id, "original")
    
    if not filepath or not filepath.exists():
        raise HTTPException(status_code=404, detail="图像不存在")
    
    img = cv2.imread(str(filepath))
    if img is None:
        raise HTTPException(status_code=500, detail="无法读取图像")
    
    # 应用通道增益
    gains = {request.channel: (request.gain, request.offset)}
    result = apply_channel_gains(img, gains)
    
    img_bytes = numpy_to_bytes(result)
    return StreamingResponse(io.BytesIO(img_bytes), media_type="image/jpeg")


@router.get("/histogram/{image_id}", response_model=HistogramResponse)
async def get_histogram(image_id: str, channel: str = "rgb"):
    """获取图像直方图"""
    filepath = file_manager.get_file_path(image_id, "original")
    
    if not filepath or not filepath.exists():
        raise HTTPException(status_code=404, detail="图像不存在")
    
    img = cv2.imread(str(filepath))
    if img is None:
        raise HTTPException(status_code=500, detail="无法读取图像")
    
    # 计算直方图
    is_grayscale = channel == "gray"
    hist_data = calculate_histogram(img, is_grayscale)
    
    # 转换为列表格式
    response_data = {}
    for key, values in hist_data.items():
        response_data[key] = values.tolist()
    
    return HistogramResponse(**response_data)


@router.post("/auto-stretch/{image_id}")
async def apply_auto_stretch(image_id: str):
    """自动拉伸直方图"""
    filepath = file_manager.get_file_path(image_id, "original")
    
    if not filepath or not filepath.exists():
        raise HTTPException(status_code=404, detail="图像不存在")
    
    img = cv2.imread(str(filepath))
    if img is None:
        raise HTTPException(status_code=500, detail="无法读取图像")
    
    # 自动拉伸
    result = auto_stretch_all_channels(img)
    
    img_bytes = numpy_to_bytes(result)
    return StreamingResponse(io.BytesIO(img_bytes), media_type="image/jpeg")
