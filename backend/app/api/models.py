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


# ---------- 摄像头相关模型 ----------

BandTypeLiteral = Literal["rgb", "570nm", "650nm", "730nm", "850nm"]


class CameraInfo(BaseModel):
    id: str
    name: str
    ip: Optional[str] = None
    stream_url: str
    username: Optional[str] = None
    camera_type: Optional[str] = None
    band_type: Optional[str] = None
    added_at: datetime
    is_running: bool = False      # 流是否在后台运行
    is_connected: bool = False    # 是否能拿到帧
    fps: int = 0


class CameraCreate(BaseModel):
    name: Optional[str] = None
    stream_url: str
    username: Optional[str] = None
    password: Optional[str] = None
    camera_type: Optional[str] = None
    band_type: Optional[str] = None


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    stream_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    band_type: Optional[str] = None


class CameraBandUpdate(BaseModel):
    band_type: Optional[str] = None  # None / "" 表示解绑


class CameraScanStatus(BaseModel):
    is_scanning: bool
    progress: int = 0
    total: int = 0
    found: int = 0
    message: str = ""
    last_result: List[Dict] = Field(default_factory=list)
    scan_logs: List[str] = Field(default_factory=list)


class CameraSyncRequest(BaseModel):
    """用当前扫描结果替换已保存摄像头列表"""
    pass


class StreamsStatusRequest(BaseModel):
    active_ids: List[str] = Field(default_factory=list)
    main_id: Optional[str] = None


class StreamStatus(BaseModel):
    camera_id: str
    name: str
    is_running: bool
    is_connected: bool
    fps: int = 0
    error_count: int = 0
    frame_age: float = -1
    rtsp_url: str = ""
    band_type: Optional[str] = None


# ---------- 抓拍建批次 ----------

class CaptureBatchRequest(BaseModel):
    camera_ids: List[str]
    batch_name: Optional[str] = None
    image_type: Literal["source", "aligned"] = "source"
    # 若相机未绑定波段，可在此处为对应相机指定覆盖值
    band_overrides: Dict[str, str] = Field(default_factory=dict)
    jpeg_quality: int = 95


class AddFromScanRequest(BaseModel):
    """从最近一次扫描结果中添加一台（按 id 或 ip 匹配）"""
    match: str


class CaptureImageResult(BaseModel):
    camera_id: str
    image_id: str
    band_type: str
    filename: str
    success: bool
    message: Optional[str] = None


class CaptureBatchResponse(BaseModel):
    batch_id: str
    batch_name: str
    results: List[CaptureImageResult]
    succeeded: int
    failed: int
