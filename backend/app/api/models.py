"""
Pydantic数据模型
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Literal
from datetime import datetime


# 图像相关模型
class ImageUploadResponse(BaseModel):
    id: str
    filename: str
    filepath: str
    size: int
    width: int
    height: int
    upload_time: datetime


class ImageInfo(BaseModel):
    id: str
    filename: str
    filepath: str
    url: str
    size: int
    width: int
    height: int
    channels: int
    upload_time: datetime


# 图像处理相关模型
class WhiteBalanceRequest(BaseModel):
    image_id: str
    r_gain: float = Field(ge=0.1, le=4.0)
    g_gain: float = Field(ge=0.1, le=4.0)
    b_gain: float = Field(ge=0.1, le=4.0)


class SaturationRequest(BaseModel):
    image_id: str
    factor: float = Field(ge=0.0, le=3.0)


class ChannelGainRequest(BaseModel):
    image_id: str
    channel: Literal["r", "g", "b"]
    gain: float = Field(ge=0.1, le=4.0)
    offset: int = Field(ge=-128, le=128)


class HistogramResponse(BaseModel):
    r: Optional[List[int]] = None
    g: Optional[List[int]] = None
    b: Optional[List[int]] = None
    gray: Optional[List[int]] = None


# 混合相关模型
class BandSelection(BaseModel):
    image_id: str
    channel: Literal["r", "g", "b", "gray"]


class BlendingRequest(BaseModel):
    bands: Dict[str, BandSelection]  # {"450nm": {...}, "650nm": {...}, ...}
    weights: Dict[str, float]  # {"450nm": 0.25, "650nm": 0.25, ...}


class SpectralCurveRequest(BaseModel):
    bands: Dict[str, BandSelection]
    x: int
    y: int


class SpectralCurveResponse(BaseModel):
    wavelengths: List[int]
    values: List[float]


# 植被指数相关模型
class VegetationIndexRequest(BaseModel):
    index_name: Literal["NDVI", "GNDVI", "NDRE", "SAVI", "EVI"]
    bands: Dict[str, BandSelection]  # {"NIR": {...}, "RED": {...}, ...}
    colormap: str = "RdYlGn"


class VegetationIndexInfo(BaseModel):
    name: str
    full_name: str
    formula: str
    required_bands: List[str]


class VegetationIndexResponse(BaseModel):
    result_url: str
    statistics: Dict[str, float]


# 对齐相关模型
class AlignmentRequest(BaseModel):
    reference_image_id: str
    target_image_id: str
    roi_config: Dict[str, float]
    detector: Literal["SIFT", "ORB"] = "SIFT"


class AlignmentResponse(BaseModel):
    aligned_image_url: str
    success: bool
    message: str


# 批次相关模型
BAND_TYPES = ["rgb", "570nm", "650nm", "730nm", "850nm"]


class BatchCreate(BaseModel):
    name: str


class BatchImageInfo(BaseModel):
    """批次中的图像信息"""
    id: str
    band_type: str
    filename: str
    filepath: str
    url: str
    size: int
    width: int
    height: int
    channels: int
    upload_time: datetime


class BatchInfo(BaseModel):
    """批次信息"""
    id: str
    name: str
    created_at: datetime
    images: Dict[str, Optional[BatchImageInfo]]  # Deprecated: usage in frontend to be migrated
    source_images: Dict[str, Optional[BatchImageInfo]] = {}
    aligned_images: Dict[str, Optional[BatchImageInfo]] = {}

