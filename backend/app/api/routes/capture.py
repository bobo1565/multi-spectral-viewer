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

import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

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
from app.database import get_db
from app.services.batch_db_service import BatchDBService
from app.services.camera_db_service import CameraDBService
from app.services.image_db_service import ImageDBService


PROJECT_ROOT = Path("/app") if os.getenv("ENV") == "production" else Path(__file__).parent.parent.parent.parent.parent
UPLOAD_DIR = PROJECT_ROOT / "uploads"


router = APIRouter()


def _ensure_stream(service: CameraService, db: Session, cam_id: str):
    """保证摄像头流已启动，未启动则按需启动"""
    stream = service.stream_manager.get_stream(cam_id)
    if stream:
        return stream

    cam = CameraDBService.get_camera(db, cam_id)
    if not cam or not cam.stream_url:
        return None

    if not service.stream_manager.add_camera(cam_id, cam.stream_url):
        return None
    return service.stream_manager.get_stream(cam_id)


def _decode_jpeg_shape(jpeg_bytes: bytes):
    """从 JPEG bytes 解出 (width, height, channels)"""
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
        return 0, 0, 0
    h, w = img.shape[:2]
    c = img.shape[2] if len(img.shape) == 3 else 1
    return w, h, c


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

    results: List[CaptureImageResult] = []
    # 记录已使用波段，避免多个相机绑到同一波段时覆盖
    used_bands = set()

    for cam_id in payload.camera_ids:
        cam = CameraDBService.get_camera(db, cam_id)
        if not cam:
            results.append(CaptureImageResult(
                camera_id=cam_id, image_id="", band_type="", filename="",
                success=False, message="摄像头不存在",
            ))
            continue

        # 决定波段：优先用 overrides，再用 DB 绑定，最后回退 rgb
        band = payload.band_overrides.get(cam_id) or cam.band_type or "rgb"
        if band not in BAND_TYPES:
            band = "rgb"

        # 相同波段冲突：在波段后追加 _2, _3 ... 这里简单处理为记录失败，让用户明确区分
        if band in used_bands:
            results.append(CaptureImageResult(
                camera_id=cam_id, image_id="", band_type=band, filename="",
                success=False,
                message=f"波段 {band} 已被其他摄像头占用，请在 band_overrides 中显式指定",
            ))
            continue

        # 确保流在跑
        stream = _ensure_stream(service, db, cam_id)
        if not stream:
            results.append(CaptureImageResult(
                camera_id=cam_id, image_id="", band_type=band, filename="",
                success=False, message="无法打开 RTSP 流",
            ))
            continue

        # 等一小会儿确保有帧
        jpeg_bytes = None
        deadline = time.time() + 3.0
        while time.time() < deadline:
            jpeg_bytes = stream.get_jpeg_bytes(quality=payload.jpeg_quality)
            if jpeg_bytes:
                break
            time.sleep(0.1)

        if not jpeg_bytes:
            results.append(CaptureImageResult(
                camera_id=cam_id, image_id="", band_type=band, filename="",
                success=False, message="未能抓到帧（超时）",
            ))
            continue

        # 落盘 {file_id}_{cam_id}_{band}.jpg
        file_id = str(uuid.uuid4())
        filename = f"{file_id}_{cam_id}_{band}.jpg"
        filepath = target_dir / filename
        try:
            with open(filepath, "wb") as f:
                f.write(jpeg_bytes)
        except Exception as e:
            results.append(CaptureImageResult(
                camera_id=cam_id, image_id="", band_type=band, filename="",
                success=False, message=f"写盘失败: {e}",
            ))
            continue

        w, h, c = _decode_jpeg_shape(jpeg_bytes)
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
            except Exception:
                pass
            results.append(CaptureImageResult(
                camera_id=cam_id, image_id="", band_type=band, filename="",
                success=False, message=f"写数据库失败: {e}",
            ))
            continue

        used_bands.add(band)
        results.append(CaptureImageResult(
            camera_id=cam_id,
            image_id=file_id,
            band_type=band,
            filename=filename,
            success=True,
        ))

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
