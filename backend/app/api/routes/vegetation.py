"""
植被指数计算API路由
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from typing import List, Optional
from sqlalchemy.orm import Session
import io
import os

from app.api.models import (
    VegetationIndexRequest,
    VegetationIndexInfo,
    VegetationIndexResponse,
    BandCorrectionUpdate,
    BandSelection,
)
from app.storage.file_manager import file_manager
from app.core.vegetation_index import VegetationIndexCalculator
from app.core.radiometric import get_band_correction, update_band_correction
from app.api.routes.blending import get_channel_from_image
from app.api.routes.processing import numpy_to_bytes
from app.database import get_db

router = APIRouter()


@router.get("/band-correction")
async def get_band_correction_config():
    """获取各波段的一级相对辐射补偿系数（IMX290C 响应曲线 + FWHM 带宽）"""
    return {"corrections": {str(k): v for k, v in sorted(get_band_correction().items())}}


@router.put("/band-correction")
async def update_band_correction_config(payload: BandCorrectionUpdate):
    """更新波段补偿系数（持久化保存，后续的指数计算立即生效）"""
    try:
        current = update_band_correction(payload.corrections)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"corrections": {str(k): v for k, v in sorted(current.items())}}


@router.get("/indices", response_model=List[VegetationIndexInfo])
async def list_vegetation_indices():
    """获取所有支持的植被指数"""
    calc = VegetationIndexCalculator()
    
    result = []
    for index_name in calc.available_indices:
        info = calc.get_index_info(index_name)
        result.append(VegetationIndexInfo(
            name=index_name,
            full_name=info['name'],
            formula=info['formula'],
            required_bands=info['bands']
        ))
    
    return result


@router.post("/calculate", response_model=VegetationIndexResponse)
async def calculate_vegetation_index(request: VegetationIndexRequest, db: Session = Depends(get_db)):
    """计算植被指数（不自动保存到批次，由前端控制保存时机）"""
    calc = VegetationIndexCalculator()
    
    calc.set_colormap(request.colormap)
    
    for band_name, band_sel in request.bands.items():
        channel_img = get_channel_from_image(db, band_sel.image_id, band_sel.channel)
        calc.set_band_image(band_name, channel_img)
    
    if not calc.can_calculate(request.index_name):
        required_bands = calc.INDICES[request.index_name]['bands']
        raise HTTPException(
            status_code=400,
            detail=f"缺少必要的波段。需要: {', '.join(required_bands)}"
        )
    
    result = calc.calculate(request.index_name)
    if result is None:
        raise HTTPException(status_code=500, detail="计算失败")
    
    colorized = calc.get_colorized_result()
    stats = calc.get_statistics()
    
    result_path = file_manager.save_processed_image("vegetation", colorized, f"{request.index_name}_{request.colormap}")
    result_url = f"/uploads/processed/{os.path.basename(result_path)}"
    
    return VegetationIndexResponse(
        result_url=result_url,
        result_filepath=result_path,
        statistics=stats,
        width=colorized.shape[1],
        height=colorized.shape[0],
        channels=colorized.shape[2] if len(colorized.shape) == 3 else 1,
        file_size=os.path.getsize(result_path) if os.path.exists(result_path) else 0
    )
