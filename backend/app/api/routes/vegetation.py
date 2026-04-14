"""
植被指数计算API路由
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from typing import List
from sqlalchemy.orm import Session
import io

from app.api.models import (
    VegetationIndexRequest,
    VegetationIndexInfo,
    VegetationIndexResponse,
    BandSelection
)
from app.storage.file_manager import file_manager
from app.core.vegetation_index import VegetationIndexCalculator
from app.api.routes.blending import get_channel_from_image
from app.api.routes.processing import numpy_to_bytes
from app.database import get_db

router = APIRouter()


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
    """计算植被指数"""
    calc = VegetationIndexCalculator()
    
    # 设置色带
    calc.set_colormap(request.colormap)
    
    # 加载波段图像
    for band_name, band_sel in request.bands.items():
        channel_img = get_channel_from_image(db, band_sel.image_id, band_sel.channel)
        calc.set_band_image(band_name, channel_img)
    
    # 检查是否可以计算
    if not calc.can_calculate(request.index_name):
        required_bands = calc.INDICES[request.index_name]['bands']
        raise HTTPException(
            status_code=400,
            detail=f"缺少必要的波段。需要: {', '.join(required_bands)}"
        )
    
    # 计算
    result = calc.calculate(request.index_name)
    if result is None:
        raise HTTPException(status_code=500, detail="计算失败")
    
    # 获取着色后的结果
    colorized = calc.get_colorized_result()
    
    # 保存结果图像
    result_path = file_manager.save_processed_image(
        "vegetation",
        colorized,
        f"{request.index_name}_{request.colormap}"
    )
    
    # 获取统计信息
    stats = calc.get_statistics()
    
    # 构建公开访问的 URL
    import os
    result_url = f"/api/images/processed/{os.path.basename(result_path)}"
    
    return VegetationIndexResponse(result_url=result_url, statistics=stats)
