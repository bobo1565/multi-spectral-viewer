"""
摄像头管理 API 路由
从 ip_camera_viewer 的 Flask 路由翻译为 FastAPI 版本
"""
from __future__ import annotations

import time
import urllib.parse
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session

from app.api.models import (
    CameraInfo,
    CameraCreate,
    CameraUpdate,
    CameraBandUpdate,
    CameraScanStatus,
    StreamsStatusRequest,
    StreamStatus,
    AddFromScanRequest,
)
from app.camera import CameraService, generate_mjpeg, get_camera_service
from app.database import get_db
from app.services.camera_db_service import CameraDBService

router = APIRouter()


def _camera_to_info(cam, stream_manager) -> CameraInfo:
    """DB 模型 → 响应模型，并合并运行中流的状态"""
    stream = stream_manager.get_stream(cam.id)
    is_running = stream is not None
    is_connected = False
    fps = 0
    if stream is not None:
        st = stream.get_status()
        is_connected = bool(st.get("is_connected"))
        fps = int(st.get("fps", 0))

    return CameraInfo(
        id=cam.id,
        name=cam.name,
        ip=cam.ip,
        stream_url=cam.stream_url,
        username=cam.username,
        camera_type=cam.camera_type,
        band_type=cam.band_type,
        added_at=cam.added_at,
        is_running=is_running,
        is_connected=is_connected,
        fps=fps,
    )


# ---------- CRUD ----------

@router.get("/", response_model=List[CameraInfo])
async def list_cameras(
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """列出所有已保存的摄像头"""
    cams = CameraDBService.list_cameras(db)
    return [_camera_to_info(c, service.stream_manager) for c in cams]


@router.post("/", response_model=CameraInfo)
async def create_camera(
    payload: CameraCreate,
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """手动添加摄像头"""
    if not payload.stream_url:
        raise HTTPException(status_code=400, detail="缺少 stream_url")

    parsed = urllib.parse.urlparse(payload.stream_url)
    ip = parsed.hostname or ""

    cam = CameraDBService.create_camera(db, {
        "name": payload.name or f"Camera {ip or payload.stream_url[-8:]}",
        "ip": ip,
        "stream_url": payload.stream_url,
        "username": payload.username,
        "password": payload.password,
        "camera_type": payload.camera_type or "RTSP",
        "band_type": payload.band_type,
    })
    return _camera_to_info(cam, service.stream_manager)


@router.patch("/{cam_id}", response_model=CameraInfo)
async def update_camera(
    cam_id: str,
    payload: CameraUpdate,
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """更新摄像头字段"""
    cam = CameraDBService.update_camera(db, cam_id, payload.model_dump(exclude_unset=True))
    if not cam:
        raise HTTPException(status_code=404, detail="摄像头不存在")
    # URL 改变时强制重启流
    if payload.stream_url:
        service.stream_manager.remove_camera(cam_id)
    return _camera_to_info(cam, service.stream_manager)


@router.put("/{cam_id}/band", response_model=CameraInfo)
async def bind_camera_band(
    cam_id: str,
    payload: CameraBandUpdate,
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """为摄像头绑定/解绑波段标签"""
    cam = CameraDBService.set_band(db, cam_id, payload.band_type)
    if not cam:
        raise HTTPException(status_code=400, detail="摄像头不存在或波段类型非法")
    return _camera_to_info(cam, service.stream_manager)


@router.delete("/{cam_id}")
async def delete_camera(
    cam_id: str,
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """删除摄像头并停止其流"""
    service.stream_manager.remove_camera(cam_id)
    ok = CameraDBService.delete_camera(db, cam_id)
    if not ok:
        raise HTTPException(status_code=404, detail="摄像头不存在")
    return {"success": True}


# ---------- 扫描 ----------

@router.post("/scan", response_model=CameraScanStatus)
async def start_scan(service: CameraService = Depends(get_camera_service)):
    """启动后台 ONVIF 扫描"""
    started = service.start_scan()
    if not started:
        # 并发扫描保护
        return CameraScanStatus(**service.scan_status)
    return CameraScanStatus(**service.scan_status)


@router.get("/scan/status", response_model=CameraScanStatus)
async def get_scan_status(service: CameraService = Depends(get_camera_service)):
    return CameraScanStatus(**service.scan_status)


@router.get("/scan/results")
async def get_scan_results(service: CameraService = Depends(get_camera_service)):
    return service.scan_status.get("last_result", [])


@router.post("/scan/add", response_model=CameraInfo)
async def add_from_scan(
    payload: AddFromScanRequest,
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """从最近一次扫描结果中添加一台摄像头到数据库（按 id 或 ip 匹配）"""
    scan_results = service.scan_status.get("last_result", [])
    cam = None
    for c in scan_results:
        if c.get("id") == payload.match or c.get("ip") == payload.match:
            cam = c
            break
    if not cam:
        raise HTTPException(status_code=404, detail="扫描结果中未找到该设备，请重新扫描")
    if not cam.get("stream_url"):
        raise HTTPException(status_code=400, detail="该设备没有可用的流地址")

    rt = cam.get("rtsp") or {}
    created = CameraDBService.create_camera(db, {
        "name": cam.get("name") or f"Camera {cam.get('ip', '')}",
        "ip": cam.get("ip"),
        "stream_url": cam["stream_url"],
        "username": rt.get("username"),
        "password": rt.get("password"),
        "camera_type": cam.get("type") or "ONVIF",
    })
    return _camera_to_info(created, service.stream_manager)


@router.post("/sync")
async def sync_from_scan(
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """用扫描结果完全替换已保存的摄像头列表，并停掉所有现有流"""
    scan_results = service.scan_status.get("last_result", [])
    if not scan_results:
        raise HTTPException(status_code=400, detail="没有可用的扫描结果，请先扫描网络")

    # 停止现有流
    service.stream_manager.stop_all()

    existing_cameras = CameraDBService.list_cameras(db)
    band_bindings = {
        cam.ip: cam.band_type
        for cam in existing_cameras
        if cam.ip and cam.band_type
    }

    prepared = []
    for cam in scan_results:
        if not cam.get("stream_url"):
            continue
        ip = cam.get("ip")
        default_seed = CameraDBService.default_camera_seed_for_ip(ip)
        band_type = band_bindings.get(ip) or (default_seed or {}).get("band_type")
        username = (cam.get("rtsp") or {}).get("username") or (default_seed or {}).get("username")
        password = (cam.get("rtsp") or {}).get("password") or (default_seed or {}).get("password")
        prepared.append({
            "name": cam.get("name") or (default_seed or {}).get("name") or f"Camera {cam.get('ip', '')}",
            "ip": ip,
            "stream_url": cam["stream_url"],
            "camera_type": cam.get("type") or (default_seed or {}).get("camera_type") or "ONVIF",
            "username": username,
            "password": password,
            "band_type": band_type,
        })

    created = CameraDBService.replace_all(db, prepared)
    print(f"[Sync] 已同步 {len(created)} 个摄像头")
    return {
        "success": True,
        "count": len(created),
        "cameras": [_camera_to_info(c, service.stream_manager).model_dump() for c in created],
    }


# ---------- 流相关 ----------

@router.post("/streams/refresh")
async def refresh_streams(
    payload: StreamsStatusRequest,
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """刷新指定摄像头的视频流：停止并重新连接 RTSP，确保流状态干净"""
    all_cams = CameraDBService.list_cameras(db)
    cam_map = {c.id: c for c in all_cams}

    refreshed = 0
    for cam_id in (payload.active_ids or []):
        cam = cam_map.get(cam_id)
        if not cam or not cam.stream_url:
            continue
        # 先停掉旧流（会触发 MJPEG 生成器退出，浏览器旧连接关闭）
        service.stream_manager.remove_camera(cam_id)
        # 立即重建新流（接下来的 MJPEG 请求会拿到全新 RTSP 连接）
        if service.stream_manager.add_camera(cam_id, cam.stream_url):
            refreshed += 1
            print(f"[Stream] 刷新视频流: {cam_id} ({cam.name})")

    return {"success": True, "refreshed": refreshed}


@router.get("/{cam_id}/stream")
async def stream_video(
    cam_id: str,
    quality: int = Query(70, ge=1, le=100),
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """MJPEG 视频流"""
    stream = service.stream_manager.get_stream(cam_id)
    if not stream:
        cam = CameraDBService.get_camera(db, cam_id)
        if cam and cam.stream_url:
            if service.stream_manager.add_camera(cam_id, cam.stream_url):
                stream = service.stream_manager.get_stream(cam_id)
        if not stream:
            raise HTTPException(status_code=404, detail="Stream not found")

    return StreamingResponse(
        generate_mjpeg(stream, quality),
        media_type="multipart/x-mixed-replace; boundary=frameboundary",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/{cam_id}/snapshot")
async def snapshot(
    cam_id: str,
    quality: int = Query(95, ge=1, le=100),
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """抓取一帧 JPEG（原分辨率，默认质量95）"""
    stream = service.stream_manager.get_stream(cam_id)
    if not stream:
        cam = CameraDBService.get_camera(db, cam_id)
        if cam and cam.stream_url:
            if service.stream_manager.add_camera(cam_id, cam.stream_url):
                stream = service.stream_manager.get_stream(cam_id)
        if not stream:
            raise HTTPException(status_code=404, detail="Stream not found")

    jpeg_bytes = stream.get_jpeg_bytes(quality=quality)
    if not jpeg_bytes:
        raise HTTPException(status_code=500, detail="Failed to capture frame")

    # 文件名
    cam = CameraDBService.get_camera(db, cam_id)
    camera_name = cam.name if cam else cam_id
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{camera_name}_{timestamp}.jpg"

    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@router.post("/streams/status", response_model=List[StreamStatus])
async def streams_status(
    payload: StreamsStatusRequest,
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """
    按需启停流（生命周期管理）：
    - 停掉不在 active_ids 中的流
    - 启动 active_ids 中但未运行的流
    - 返回所有数据库中摄像头的状态
    """
    active_ids = list(payload.active_ids or [])
    main_id = payload.main_id or ""

    all_cams = CameraDBService.list_cameras(db)
    cam_map = {c.id: c for c in all_cams}

    # 停掉不在窗口中的流
    for cid in list(service.stream_manager.get_all_streams().keys()):
        if cid not in active_ids:
            service.stream_manager.remove_camera(cid)
            print(f"[Stream] 停止闲置视频流以降低延迟: {cid}")

    # 启动需要的流
    for cid in active_ids:
        running = service.stream_manager.get_stream(cid) is not None
        cam = cam_map.get(cid)
        if not running and cam and cam.stream_url:
            print(f"[Stream] 按需启动活动视频流: {cid}")
            service.stream_manager.add_camera(cid, cam.stream_url)

    # 标记主窗口
    for cid, stream in service.stream_manager.get_all_streams().items():
        stream.is_main = (cid == main_id)

    # 返回所有已保存摄像头的状态（运行中 → 取真实状态；未运行 → 占位）
    statuses: List[StreamStatus] = []
    for cam in all_cams:
        stream = service.stream_manager.get_stream(cam.id)
        if stream:
            st = stream.get_status()
            statuses.append(StreamStatus(
                camera_id=cam.id,
                name=cam.name,
                is_running=bool(st.get("is_running")),
                is_connected=bool(st.get("is_connected")),
                fps=int(st.get("fps", 0)),
                error_count=int(st.get("error_count", 0)),
                frame_age=float(st.get("frame_age", -1)),
                rtsp_url=st.get("rtsp_url", cam.stream_url or ""),
                band_type=cam.band_type,
            ))
        else:
            statuses.append(StreamStatus(
                camera_id=cam.id,
                name=cam.name,
                is_running=False,
                is_connected=False,
                fps=0,
                error_count=0,
                frame_age=-1,
                rtsp_url=cam.stream_url or "",
                band_type=cam.band_type,
            ))

    return statuses
