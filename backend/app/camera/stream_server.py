#!/usr/bin/env python3
"""
Low-latency MJPEG Streaming Server
从 ip_camera_viewer 迁入：使用 OpenCV 打开 RTSP，按需编码 MJPEG 输出
"""

import cv2
import threading
import time
from typing import Dict, Optional
from collections import deque
import numpy as np


class CameraStream:
    """单个摄像头的视频流处理"""

    def __init__(self, camera_id: str, rtsp_url: str, config: Dict):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.config = config

        self.cap: Optional[cv2.VideoCapture] = None
        self.cap_lock = threading.Lock()
        self.is_running = False
        self.is_connected = False
        self.frame: Optional[np.ndarray] = None
        self.frame_lock = threading.Lock()

        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()
        self.error_count = 0
        self.last_frame_time = 0

        self.frame_buffer = deque(maxlen=config.get('buffer_size', 2))

        self.capture_thread: Optional[threading.Thread] = None
        self.is_main = False

    def start(self) -> bool:
        """启动视频流"""
        if self.is_running:
            return True

        try:
            with self.cap_lock:
                self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                timeout_ms = self.config.get('connection_timeout', 10) * 1000
                self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout_ms)
                self.cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)

                if not self.cap.isOpened():
                    print(f"[Stream {self.camera_id}] 无法打开RTSP流: {self.rtsp_url}")
                    self.cap.release()
                    self.cap = None
                    return False

            self.is_running = True
            self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.capture_thread.start()

            # 等待第一帧
            wait_start = time.time()
            while time.time() - wait_start < 5:
                with self.frame_lock:
                    if self.frame is not None:
                        self.is_connected = True
                        print(f"[Stream {self.camera_id}] 连接成功")
                        return True
                time.sleep(0.1)

            print(f"[Stream {self.camera_id}] 等待第一帧超时")
            # 超时但线程已启动，保持运行让后台重连
            return True

        except Exception as e:
            print(f"[Stream {self.camera_id}] 启动错误: {e}")
            self.error_count += 1
            self.is_running = False
            if self.capture_thread:
                self.capture_thread.join(timeout=2)
            with self.cap_lock:
                if self.cap:
                    self.cap.release()
                    self.cap = None
            return False

    def _capture_loop(self):
        """视频捕获线程"""
        consecutive_errors = 0
        max_consecutive_errors = 10

        while self.is_running:
            try:
                with self.cap_lock:
                    if self.cap is None or not self.cap.isOpened():
                        cap_ok = False
                    else:
                        ret, frame = self.cap.read()
                        cap_ok = True

                if not cap_ok:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        print(f"[Stream {self.camera_id}] 连接断开，尝试重连...")
                        self._reconnect()
                        consecutive_errors = 0
                    time.sleep(0.5)
                    continue

                if not ret or frame is None:
                    consecutive_errors += 1
                    time.sleep(0.01)
                    continue

                consecutive_errors = 0
                self.error_count = 0

                with self.frame_lock:
                    self.frame = frame
                    self.last_frame_time = time.time()

                self.frame_count += 1

                current_time = time.time()
                if current_time - self.last_fps_time >= 1.0:
                    self.fps = self.frame_count
                    self.frame_count = 0
                    self.last_fps_time = current_time

                # 主力窗口跑满，副窗口降帧（约20FPS）
                if self.is_main:
                    time.sleep(0.001)
                else:
                    time.sleep(0.05)

            except Exception as e:
                print(f"[Stream {self.camera_id}] 捕获错误: {e}")
                consecutive_errors += 1
                time.sleep(0.1)

    def _reconnect(self):
        """重新连接"""
        try:
            with self.cap_lock:
                if self.cap:
                    self.cap.release()
                    self.cap = None

                self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            print(f"[Stream {self.camera_id}] 重连完成")
        except Exception as e:
            print(f"[Stream {self.camera_id}] 重连失败: {e}")

    def get_frame(self) -> Optional[np.ndarray]:
        """获取当前帧"""
        with self.frame_lock:
            if self.frame is not None:
                return self.frame.copy()
        return None

    def get_jpeg_bytes(self, quality: int = None) -> Optional[bytes]:
        """获取JPEG编码的图像字节"""
        frame = self.get_frame()
        if frame is None:
            return None

        if quality is None:
            quality = self.config.get('jpeg_quality', 70)

        encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
        ret, jpeg = cv2.imencode('.jpg', frame, encode_params)

        if ret:
            return jpeg.tobytes()
        return None

    def get_status(self) -> Dict:
        """获取流状态"""
        with self.frame_lock:
            frame_age = time.time() - self.last_frame_time if self.last_frame_time > 0 else -1

        return {
            'camera_id': self.camera_id,
            'is_running': self.is_running,
            'is_connected': self.is_connected and frame_age < 5,
            'fps': self.fps,
            'error_count': self.error_count,
            'frame_age': frame_age,
            'rtsp_url': self.rtsp_url,
        }

    def stop(self):
        """停止视频流"""
        self.is_running = False
        if self.capture_thread:
            self.capture_thread.join(timeout=3)
        with self.cap_lock:
            if self.cap:
                self.cap.release()
                self.cap = None
        print(f"[Stream {self.camera_id}] 已停止")


class StreamManager:
    """管理多个摄像头的视频流"""

    def __init__(self, config: Dict):
        self.config = config
        self.streams: Dict[str, CameraStream] = {}
        self.lock = threading.Lock()

    def add_camera(self, camera_id: str, rtsp_url: str) -> bool:
        """添加摄像头"""
        old_stream: Optional[CameraStream] = None

        with self.lock:
            if camera_id in self.streams:
                if self.streams[camera_id].rtsp_url != rtsp_url:
                    old_stream = self.streams[camera_id]
                    del self.streams[camera_id]
                else:
                    return True

        if old_stream:
            old_stream.stop()

        stream = CameraStream(camera_id, rtsp_url, self.config.get('streaming', {}))
        if not stream.start():
            return False

        with self.lock:
            current = self.streams.get(camera_id)
            if current is not None and current is not old_stream:
                # 其他并发请求已注册了该流，避免覆盖有效实例。
                stream.stop()
                return True

            self.streams[camera_id] = stream
            return True

    def remove_camera(self, camera_id: str):
        """移除摄像头"""
        stream: Optional[CameraStream] = None

        with self.lock:
            if camera_id in self.streams:
                stream = self.streams.pop(camera_id)

        if stream:
            stream.stop()

    def get_stream(self, camera_id: str) -> Optional[CameraStream]:
        """获取视频流"""
        with self.lock:
            return self.streams.get(camera_id)

    def get_all_streams(self) -> Dict[str, CameraStream]:
        """获取所有视频流"""
        with self.lock:
            return dict(self.streams)

    def get_all_status(self) -> Dict:
        """获取所有流状态"""
        with self.lock:
            return {cid: stream.get_status() for cid, stream in self.streams.items()}

    def stop_all(self):
        """停止所有流"""
        with self.lock:
            streams = list(self.streams.values())
            self.streams.clear()

        for stream in streams:
            stream.stop()


def _create_placeholder_jpeg(width: int = 640, height: int = 480, quality: int = 70) -> bytes:
    """创建 '无信号' 占位帧"""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.putText(img, "NO SIGNAL", (width // 2 - 160, height // 2 + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 2.5, (80, 80, 80), 4, cv2.LINE_AA)
    ret, jpeg = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return jpeg.tobytes() if ret else b''


def generate_mjpeg(stream: CameraStream, quality: int = 70):
    """生成 MJPEG 流的生成器，用于 FastAPI StreamingResponse

    - 输出帧率限制在 ~30 FPS，防止浏览器解码/渲染管线被压垮
    - RTSP 断开时持续输出占位帧，防止浏览器因长时间无数据而黑屏
    """
    boundary = b"--frameboundary"
    placeholder = _create_placeholder_jpeg(quality=quality)
    no_frame_count = 0
    # 帧率限制：30 FPS ≈ 33ms 间隔
    target_interval = 1.0 / 30
    last_yield_time = 0.0

    while stream.is_running:
        now = time.time()
        elapsed = now - last_yield_time

        # 帧率限制：未到间隔则等待
        if last_yield_time > 0 and elapsed < target_interval:
            time.sleep(target_interval - elapsed)
            continue

        jpeg_bytes = stream.get_jpeg_bytes(quality)

        if jpeg_bytes:
            no_frame_count = 0
            last_yield_time = time.time()
            yield (boundary + b'\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(jpeg_bytes)).encode() + b'\r\n'
                   b'\r\n' + jpeg_bytes + b'\r\n')
        else:
            no_frame_count += 1
            # 断流时每 ~0.5s 输出一次占位帧
            if no_frame_count % 5 == 0 and placeholder:
                last_yield_time = time.time()
                yield (boundary + b'\r\n'
                       b'Content-Type: image/jpeg\r\n'
                       b'Content-Length: ' + str(len(placeholder)).encode() + b'\r\n'
                       b'\r\n' + placeholder + b'\r\n')
            time.sleep(0.1)
