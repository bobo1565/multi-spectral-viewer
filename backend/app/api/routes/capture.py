"""
抓拍即建批次：实时视频 → 多光谱分析 的关键桥梁

POST /api/capture/batch
- 输入一组 camera_ids
- 对每台摄像头抓取 JPEG
- 按 band_type 存到一个新批次的 source 目录
- 调用 BatchDBService/ImageDBService 写入数据库
- 前端接着可以直接走原有的对齐/混合/植被指数管线
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.models import (
    CaptureBatchRequest,
    CaptureBatchResponse,
    CaptureImageResult,
    BAND_TYPES,
)
from app.camera import CameraService, get_camera_service
from app.camera.onvif_imaging import get_imaging_client
from app.database import get_db
from app.services.batch_db_service import BatchDBService
from app.services.camera_db_service import CameraDBService
from app.services.image_db_service import ImageDBService


PROJECT_ROOT = Path("/app") if os.getenv("ENV") == "production" else Path(__file__).parent.parent.parent.parent.parent
UPLOAD_DIR = PROJECT_ROOT / "uploads"


router = APIRouter()


def _decode_jpeg_shape(jpeg_bytes: bytes):
    """从 JPEG bytes 解出 (width, height, channels)"""
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
        return 0, 0, 0
    h, w = img.shape[:2]
    c = img.shape[2] if len(img.shape) == 3 else 1
    return w, h, c


def _fetch_imaging_metadata(cam, band: str, w: int, h: int) -> Optional[dict]:
    """抓拍元数据（方案文档 §12）：尽力读取 ONVIF Imaging 参数，失败返回 None。

    多光谱数据必须可追溯曝光/Gain 等参数，否则灰度值跨时间不可比较。
    """
    if not cam.ip:
        return None
    try:
        client = get_imaging_client(
            cam.ip, cam.username or "", cam.password or "", cam.stream_url or "",
        )
        settings = client.get_settings()
    except Exception:
        return None

    band_nm = None
    m = re.match(r"(\d+)", band or "")
    if m:
        band_nm = int(m.group(1))

    auto_exposure = settings.get("exposure_mode") == "AUTO"
    return {
        "camera_id": cam.id,
        "camera_name": cam.name,
        "camera_ip": cam.ip,
        "band": band,
        "band_nm": band_nm,
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
        "exposure_mode": settings.get("exposure_mode"),
        "exposure_us": settings.get("exposure_time_us"),
        "gain": settings.get("gain"),
        "gamma": settings.get("gamma"),
        # 这类摄像头 AUTO 曝光模式下 Gain 也随动，一并标记
        "auto_exposure": auto_exposure,
        "auto_gain": auto_exposure,
        "wb_mode": settings.get("wb_mode"),
        "wdr_mode": settings.get("wdr_mode"),
        "width": w,
        "height": h,
    }


@router.post("/batch", response_model=CaptureBatchResponse)
async def capture_to_batch(
    payload: CaptureBatchRequest,
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """同步抓拍若干摄像头并写入一个新批次"""
    if not payload.camera_ids:
        raise HTTPException(status_code=400, detail="camera_ids 不能为空")

    # 创建批次
    batch_name = payload.batch_name or time.strftime("Capture_%Y%m%d_%H%M%S")
    batch = BatchDBService.create_batch(db, batch_name)

    # 目录：uploads/{batch_id}/source (或 aligned)
    sub = "source" if payload.image_type == "source" else "aligned"
    target_dir = UPLOAD_DIR / batch.id / sub
    target_dir.mkdir(parents=True, exist_ok=True)

    # 结果按输入 camera_ids 顺序输出
    result_map = {}

    # 第一阶段（顺序）：确定每台摄像头的波段分配，避免多相机抢占同一波段
    assignments = []  # [(cam, band)]
    used_bands = set()
    # 可用波段池（用于未绑定波段的摄像头自动分配）
    available_bands = [b for b in BAND_TYPES]

    for cam_id in payload.camera_ids:
        cam = CameraDBService.get_camera(db, cam_id)
        if not cam:
            result_map[cam_id] = CaptureImageResult(
                camera_id=cam_id, image_id="", band_type="", filename="",
                success=False, message="摄像头不存在",
            )
            continue

        # 决定波段：优先用 overrides，再用 DB 绑定
        band = payload.band_overrides.get(cam_id) or cam.band_type

        if band:
            # 显式绑定的摄像头：使用指定波段
            if band not in BAND_TYPES:
                band = "rgb"
            if band in used_bands:
                result_map[cam_id] = CaptureImageResult(
                    camera_id=cam_id, image_id="", band_type=band, filename="",
                    success=False,
                    message=f"波段 {band} 已被其他摄像头占用",
                )
                continue
        else:
            # 未绑定波段的摄像头：从可用波段池自动分配
            band = None
            for i, b in enumerate(available_bands):
                if b not in used_bands:
                    band = available_bands.pop(i)
                    break
            if not band:
                result_map[cam_id] = CaptureImageResult(
                    camera_id=cam_id, image_id="", band_type="", filename="",
                    success=False, message="所有波段已分配完毕",
                )
                continue

        used_bands.add(band)
        assignments.append((cam, band))

    # 第二阶段（并行）：各摄像头同时抓帧，缩短多路同步抓拍的时间差（文档 §17），
    # 并顺带读取 ONVIF Imaging 参数作为元数据（文档 §12）
    def _grab_frame(cam, band):
        stream = service.stream_manager.get_stream(cam.id)
        if not stream and cam.stream_url:
            if service.stream_manager.add_camera(cam.id, cam.stream_url):
                stream = service.stream_manager.get_stream(cam.id)
        if not stream:
            return cam, band, None, None, "无法打开 RTSP 流"

        # 等一小会儿确保有帧
        jpeg_bytes = None
        deadline = time.time() + 3.0
        while time.time() < deadline:
            jpeg_bytes = stream.get_jpeg_bytes(quality=payload.jpeg_quality)
            if jpeg_bytes:
                break
            time.sleep(0.1)

        if not jpeg_bytes:
            return cam, band, None, None, "未能抓到帧（超时）"

        w, h, c = _decode_jpeg_shape(jpeg_bytes)
        metadata = _fetch_imaging_metadata(cam, band, w, h)
        return cam, band, jpeg_bytes, (w, h, c, metadata), None

    grabbed = []
    if assignments:
        with ThreadPoolExecutor(max_workers=len(assignments)) as pool:
            grabbed = list(pool.map(lambda t: _grab_frame(*t), assignments))

    # 第三阶段（顺序）：落盘 + 元数据 sidecar + 写数据库（Session 非线程安全）
    for cam, band, jpeg_bytes, extra, error in grabbed:
        cam_id = cam.id
        if error:
            result_map[cam_id] = CaptureImageResult(
                camera_id=cam_id, image_id="", band_type=band, filename="",
                success=False, message=error,
            )
            continue

        # 落盘 {file_id}_{cam_id}_{band}.jpg
        file_id = str(uuid.uuid4())
        filename = f"{file_id}_{cam_id}_{band}.jpg"
        filepath = target_dir / filename
        try:
            with open(filepath, "wb") as f:
                f.write(jpeg_bytes)
        except Exception as e:
            result_map[cam_id] = CaptureImageResult(
                camera_id=cam_id, image_id="", band_type=band, filename="",
                success=False, message=f"写盘失败: {e}",
            )
            continue

        w, h, c, metadata = extra

        # 元数据 sidecar：{同名}.json（文档 §12，失败不影响抓拍主流程）
        if metadata:
            try:
                sidecar = filepath.with_suffix(".json")
                sidecar.write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                print(f"[Capture] 元数据写入失败 {cam_id}: {e}")

        try:
            ImageDBService.create_image(db, {
                "id": file_id,
                "batch_id": batch.id,
                "band_type": band,
                "image_type": payload.image_type,
                "filename": filename,
                "filepath": str(filepath),
                "size": len(jpeg_bytes),
                "width": w,
                "height": h,
                "channels": c,
                "upload_time": datetime.utcnow(),
            })
        except Exception as e:
            # DB 写失败则回滚文件
            try:
                filepath.unlink()
                filepath.with_suffix(".json").unlink(missing_ok=True)
            except Exception:
                pass
            result_map[cam_id] = CaptureImageResult(
                camera_id=cam_id, image_id="", band_type=band, filename="",
                success=False, message=f"写数据库失败: {e}",
            )
            continue

        result_map[cam_id] = CaptureImageResult(
            camera_id=cam_id,
            image_id=file_id,
            band_type=band,
            filename=filename,
            success=True,
        )

    results: List[CaptureImageResult] = [result_map[cid] for cid in payload.camera_ids]

    succeeded = sum(1 for r in results if r.success)
    failed = len(results) - succeeded

    # 若全部失败，回滚批次
    if succeeded == 0:
        BatchDBService.delete_batch(db, batch.id)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "所有摄像头抓拍失败",
                "results": [r.model_dump() for r in results],
            },
        )

    return CaptureBatchResponse(
        batch_id=batch.id,
        batch_name=batch.name,
        results=results,
        succeeded=succeeded,
        failed=failed,
    )
