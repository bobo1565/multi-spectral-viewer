"""
摄像头采集子模块
从 ip_camera_viewer 迁入的实时 RTSP/MJPEG 采集能力
"""
from .stream_server import CameraStream, StreamManager, generate_mjpeg
from .discovery import CameraDiscovery
from .manager import CameraService, get_camera_service

__all__ = [
    "CameraStream",
    "StreamManager",
    "generate_mjpeg",
    "CameraDiscovery",
    "CameraService",
    "get_camera_service",
]
