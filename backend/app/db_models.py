from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class Batch(Base):
    """批次模型 - 每个批次包含一组多光谱图像"""
    __tablename__ = "batches"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)  # 用户命名的批次名称
    created_at = Column(DateTime, default=datetime.utcnow)

    images = relationship("Image", back_populates="batch", cascade="all, delete-orphan")


class Image(Base):
    """图像模型"""
    __tablename__ = "images"

    id = Column(String, primary_key=True, index=True)
    batch_id = Column(String, ForeignKey("batches.id"), nullable=True)
    band_type = Column(String, nullable=True)  # "rgb", "570nm", "650nm", "730nm", "850nm"
    image_type = Column(String, default="source")  # "source" 或 "aligned"
    filename = Column(String, index=True)      # 原始文件名
    filepath = Column(String)                  # 物理路径
    file_size = Column(Integer)
    width = Column(Integer)
    height = Column(Integer)
    channels = Column(Integer)
    upload_time = Column(DateTime, default=datetime.utcnow)

    batch = relationship("Batch", back_populates="images")


class Camera(Base):
    """摄像头模型 - 由 ip_camera_viewer 迁入，支持波段标签用于抓拍"""
    __tablename__ = "cameras"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    ip = Column(String, nullable=True)
    stream_url = Column(String, nullable=False)
    username = Column(String, nullable=True)
    password = Column(String, nullable=True)
    camera_type = Column(String, nullable=True)  # ONVIF / RTSP / Manual
    # 绑定波段类型: rgb / 570nm / 650nm / 730nm / 850nm / None
    band_type = Column(String, nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow)
