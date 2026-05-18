"""
摄像头进程级单例服务
- 持有 StreamManager / CameraDiscovery 两个核心组件
- 管理扫描任务后台状态
- FastAPI 在 startup 时创建、shutdown 时关闭所有流
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional

from .stream_server import StreamManager
from .discovery import CameraDiscovery


# 摄像头模块的默认配置（原 ip_camera_viewer/config.json）
DEFAULT_CAMERA_CONFIG: Dict = {
    "discovery": {
        "ip_ranges": [],
        "scan_timeout": 2,
        "onvif_ports": [80, 8080, 2020, 8000],
        "rtsp_ports": [554, 8554],
        "common_credentials": [
            {"username": "admin", "password": ""},
            {"username": "admin", "password": "admin"},
            {"username": "admin", "password": "123456"},
            {"username": "root", "password": "root"},
            {"username": "admin", "password": "12345"},
            {"username": "admin", "password": "password"},
        ],
    },
    "streaming": {
        "jpeg_quality": 70,
        "max_fps": 25,
        "buffer_size": 3,
        "connection_timeout": 10,
    },
}


class CameraService:
    """封装 StreamManager + CameraDiscovery + 扫描状态"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or DEFAULT_CAMERA_CONFIG
        self.stream_manager = StreamManager(self.config)
        self.discovery = CameraDiscovery(self.config)

        # 扫描任务状态
        self.scan_status: Dict = {
            'is_scanning': False,
            'progress': 0,
            'total': 0,
            'found': 0,
            'last_result': [],
            'message': '',
            'scan_logs': [],
        }
        self._scan_lock = threading.Lock()

    def _append_scan_log(self, message: str):
        logs = self.scan_status.setdefault('scan_logs', [])
        logs.append(message)
        if len(logs) > 200:
            del logs[:-200]

    # --------- 扫描 ---------

    def start_scan(self) -> bool:
        """启动后台扫描任务；若已在扫描则返回 False"""
        with self._scan_lock:
            if self.scan_status['is_scanning']:
                return False
            self.scan_status = {
                'is_scanning': True,
                'progress': 0,
                'total': 100,
                'found': 0,
                'last_result': [],
                'message': '扫描启动中...',
                'scan_logs': [],
            }

        thread = threading.Thread(target=self._scan_task, daemon=True)
        thread.start()
        return True

    def _scan_task(self):
        """后台扫描：ONVIF 多播发现 → 依次探测 RTSP 流"""
        try:
            print("[Scan] 开始后台扫描...")
            self.scan_status['message'] = '正在发现ONVIF设备...'
            self._append_scan_log('开始扫描网络中的 ONVIF 设备')

            scan_timeout = int(self.config.get("discovery", {}).get("scan_timeout", 2) or 2)
            rtsp_ports = self.config.get("discovery", {}).get("rtsp_ports", [554, 8554])
            onvif_cameras = self.discovery.onvif_discovery(timeout=scan_timeout)
            print(f"[Scan] ONVIF发现 {len(onvif_cameras)} 个设备")
            self._append_scan_log(f"ONVIF 多播发现 {len(onvif_cameras)} 台设备")

            self.scan_status['message'] = f'发现 {len(onvif_cameras)} 个设备，正在获取视频流...'
            self.scan_status['total'] = max(1, len(onvif_cameras))

            cameras: List[Dict] = []

            for i, cam in enumerate(onvif_cameras):
                ip = cam['ip']
                self.scan_status['progress'] = i + 1
                self.scan_status['message'] = f'正在获取视频流: {ip}'
                self._append_scan_log(f'开始验证 {ip} 的 RTSP 视频流')

                rtsp_info = None
                failure_reasons: List[str] = []
                for port in rtsp_ports:
                    probe = self.discovery.probe_rtsp_stream(ip, port)
                    if probe.get('success'):
                        rtsp_info = probe['info']
                        # 统一 stream_url 字段，供前端和后续同步使用
                        cam['stream_url'] = rtsp_info['rtsp_url']
                        cam['rtsp'] = rtsp_info
                        print(f"[Scan] ✓ {ip} 成功: {rtsp_info.get('path', 'unknown')}")
                        self._append_scan_log(
                            f"{ip} 验证成功: 端口 {rtsp_info.get('port', port)}，"
                            f"路径 {rtsp_info.get('path', 'unknown')}"
                        )
                        break
                    failure_reasons.append(str(probe.get('reason', f'端口 {port} 探测失败')))

                if rtsp_info:
                    cameras.append(cam)
                else:
                    print(f"[Scan] ✗ {ip} 未发现可用 RTSP 流（已尝试端口: {rtsp_ports}）")
                    self._append_scan_log(f"{ip} 验证失败: {'；'.join(failure_reasons) or '未发现可用 RTSP 流'}")

                self.scan_status['found'] = len(cameras)

            # 去重，分配临时 id（= ip）
            seen_ips = set()
            unique: List[Dict] = []
            for cam in cameras:
                ip = cam.get('ip')
                if ip and ip not in seen_ips:
                    seen_ips.add(ip)
                    cam['id'] = ip
                    if 'stream_url' not in cam and 'rtsp' in cam:
                        cam['stream_url'] = cam['rtsp'].get('rtsp_url', '')
                    unique.append(cam)

            self.discovery.discovered_cameras = unique
            self.scan_status['last_result'] = unique
            self.scan_status['message'] = f'扫描完成，发现 {len(unique)} 个摄像头'
            self._append_scan_log(f"扫描完成，最终可用摄像头 {len(unique)} 台")
            print(f"[Scan] 扫描完成，发现 {len(unique)} 个摄像头")
        except Exception as e:
            print(f"[Scan] 扫描出错: {e}")
            import traceback
            traceback.print_exc()
            self.scan_status['message'] = f'扫描出错: {str(e)}'
            self._append_scan_log(f"扫描出错: {str(e)}")
        finally:
            self.scan_status['is_scanning'] = False

    # --------- 生命周期 ---------

    def shutdown(self):
        """关闭所有视频流"""
        print("[CameraService] 关闭所有视频流...")
        self.stream_manager.stop_all()


# ---------- 进程级单例 ----------

_camera_service: Optional[CameraService] = None
_init_lock = threading.Lock()


def get_camera_service() -> CameraService:
    """获取全局 CameraService 单例，供 FastAPI Depends 使用"""
    global _camera_service
    if _camera_service is None:
        with _init_lock:
            if _camera_service is None:
                _camera_service = CameraService()
    return _camera_service
