"""
ONVIF Imaging 参数控制 API

对应《Mac_ONVIF_多光谱摄像头监看与参数控制方案》：
- §7  GetImagingSettings / GetOptions / SetImagingSettings
- §8  多光谱模式：关闭自动曝光/增益/白平衡、WDR，固定 ISP 参数
- §9  各波段曝光策略表（per-band profile，可编辑持久化）
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.camera import CameraService, get_camera_service
from app.camera.onvif_imaging import ImagingError, get_imaging_client
from app.database import get_db
from app.services.camera_db_service import CameraDBService

router = APIRouter()


def _sync_black_filter(service: CameraService, cam_id: str, settings: Dict[str, Any]):
    """按最终曝光模式调整该路视频的黑帧判定阈值。

    手动曝光（尤其短曝光）画面本征变暗，默认阈值会把真实暗帧误判为黑帧，
    监控画面冻结在旧帧，看起来像参数没生效；AUTO 模式恢复默认判定。
    """
    mode = settings.get('exposure_mode')
    if mode == 'MANUAL':
        service.stream_manager.set_black_frame_threshold(cam_id, 1.0)
    elif mode == 'AUTO':
        service.stream_manager.set_black_frame_threshold(cam_id, None)

# 波段曝光策略表文件（沿用 matching.json 的配置文件风格，支持热更新）
CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"
BAND_PROFILES_PATH = CONFIG_DIR / "band_imaging_profiles.json"
_profiles_lock = threading.Lock()

# 文档 §9 的推荐默认值：RGB 保持自动，其余波段固定曝光，Gain 取最低
DEFAULT_BAND_PROFILES: Dict[str, Dict[str, Any]] = {
    "rgb": {"auto_exposure": True},
    "560nm": {"exposure_time_us": 8000, "gain": 0},
    "650nm": {"exposure_time_us": 10000, "gain": 0},
    "730nm": {"exposure_time_us": 12000, "gain": 0},
    "850nm": {"exposure_time_us": 15000, "gain": 0},
}


class ImagingStateResponse(BaseModel):
    supported: bool
    settings: Dict[str, Any] = Field(default_factory=dict)
    options: Dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    # 设置后回读校验未生效的字段：[{field, label, requested, actual}]
    rejected: List[Dict[str, Any]] = Field(default_factory=list)


class ImagingUpdateRequest(BaseModel):
    """部分字段更新，键为归一化字段名（见 onvif_imaging 模块）"""
    settings: Dict[str, Any]


class BandProfilesRequest(BaseModel):
    profiles: Dict[str, Dict[str, Any]]


class ImagingActionResult(BaseModel):
    camera_id: str
    name: str
    band_type: Optional[str] = None
    success: bool
    message: str = ""


class ApplyAllRequest(BaseModel):
    settings: Dict[str, Any]
    # 为空时应用到所有监控中的摄像头
    camera_ids: Optional[List[str]] = None


def _load_band_profiles() -> Dict[str, Dict[str, Any]]:
    with _profiles_lock:
        try:
            if BAND_PROFILES_PATH.exists():
                data = json.loads(BAND_PROFILES_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data:
                    return data
        except Exception as e:
            print(f"[Imaging] 读取波段策略表失败，使用默认值: {e}")
        return dict(DEFAULT_BAND_PROFILES)


def _save_band_profiles(profiles: Dict[str, Dict[str, Any]]):
    with _profiles_lock:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        BAND_PROFILES_PATH.write_text(
            json.dumps(profiles, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _get_client_for_camera(cam):
    if not cam.ip:
        raise ImagingError(f"摄像头 {cam.name} 没有 IP 地址，无法使用 ONVIF 控制")
    return get_imaging_client(
        cam.ip,
        cam.username or "",
        cam.password or "",
        cam.stream_url or "",
    )


def _read_state(cam) -> ImagingStateResponse:
    """读取一台摄像头的 settings + options；不支持时返回 supported=False"""
    try:
        client = _get_client_for_camera(cam)
        settings = client.get_settings()
        try:
            options = client.get_options()
        except ImagingError:
            options = {}
        return ImagingStateResponse(supported=True, settings=settings, options=options)
    except ImagingError as e:
        return ImagingStateResponse(supported=False, message=str(e))
    except Exception as e:
        return ImagingStateResponse(supported=False, message=f"读取参数失败: {e}")


# ---------- 单摄像头参数 ----------

@router.get("/{cam_id}/imaging", response_model=ImagingStateResponse)
async def get_imaging_state(cam_id: str, db: Session = Depends(get_db)):
    """读取摄像头当前 Imaging 参数与可设置范围（文档 §7.1 / §7.2）"""
    cam = CameraDBService.get_camera(db, cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="摄像头不存在")
    return await run_in_threadpool(_read_state, cam)


@router.put("/{cam_id}/imaging", response_model=ImagingStateResponse)
async def update_imaging_state(
    cam_id: str,
    payload: ImagingUpdateRequest,
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """修改摄像头 Imaging 参数（文档 §7.3），返回设置后的最新状态"""
    cam = CameraDBService.get_camera(db, cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="摄像头不存在")

    def _apply() -> ImagingStateResponse:
        try:
            client = _get_client_for_camera(cam)
            settings, rejected = client.set_settings(payload.settings)
        except ImagingError as e:
            return ImagingStateResponse(supported=False, message=str(e))
        except Exception as e:
            return ImagingStateResponse(supported=False, message=f"设置参数失败: {e}")
        _sync_black_filter(service, cam_id, settings)
        try:
            options = client.get_options()
        except ImagingError:
            options = {}
        message = ""
        if rejected:
            message = "部分参数未生效：" + "；".join(
                f"{r['label']} 请求 {r['requested']}，实际 {r['actual']}"
                for r in rejected
            )
        return ImagingStateResponse(
            supported=True, settings=settings, options=options,
            message=message, rejected=rejected,
        )

    return await run_in_threadpool(_apply)


# ---------- 波段曝光策略表（文档 §9） ----------

@router.get("/imaging/band-profiles")
async def get_band_profiles():
    """读取各波段曝光策略表"""
    return {"profiles": _load_band_profiles()}


@router.put("/imaging/band-profiles")
async def put_band_profiles(payload: BandProfilesRequest):
    """保存各波段曝光策略表"""
    await run_in_threadpool(_save_band_profiles, payload.profiles)
    return {"success": True, "profiles": payload.profiles}


# ---------- 多光谱模式（文档 §8/§9） ----------

def _apply_multispectral_to_camera(cam, profiles, service: CameraService) -> ImagingActionResult:
    band = cam.band_type
    if not band:
        return ImagingActionResult(
            camera_id=cam.id, name=cam.name, band_type=None,
            success=False, message="未绑定波段，跳过",
        )
    profile = profiles.get(band)
    if profile is None:
        return ImagingActionResult(
            camera_id=cam.id, name=cam.name, band_type=band,
            success=False, message=f"波段 {band} 没有曝光策略，跳过",
        )

    # 文档 §8：固定曝光/增益/白平衡，关闭 AUTO 与 WDR
    if profile.get("auto_exposure"):
        changes: Dict[str, Any] = {"exposure_mode": "AUTO"}
    else:
        changes = {
            "exposure_mode": "MANUAL",
            "exposure_time_us": profile.get("exposure_time_us"),
            "gain": profile.get("gain"),
            "wb_mode": "MANUAL",
            "wdr_mode": "OFF",
        }

    try:
        client = _get_client_for_camera(cam)
        new_settings, rejected = client.set_settings(changes)
        _sync_black_filter(service, cam.id, new_settings)
        exp = "自动曝光" if profile.get("auto_exposure") else f"{profile.get('exposure_time_us')}us / Gain {profile.get('gain')}"
        message = f"已应用：{exp}"
        if rejected:
            message += "；但未生效：" + "、".join(
                f"{r['label']}（实际 {r['actual']}）" for r in rejected
            )
        return ImagingActionResult(
            camera_id=cam.id, name=cam.name, band_type=band,
            success=True, message=message,
        )
    except ImagingError as e:
        return ImagingActionResult(
            camera_id=cam.id, name=cam.name, band_type=band,
            success=False, message=str(e),
        )
    except Exception as e:
        return ImagingActionResult(
            camera_id=cam.id, name=cam.name, band_type=band,
            success=False, message=f"设置失败: {e}",
        )


@router.post("/imaging/multispectral-mode", response_model=List[ImagingActionResult])
async def apply_multispectral_mode(
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """一键多光谱模式：按波段策略表固定每台摄像头的曝光/Gain，关自动白平衡/WDR"""
    cams = [c for c in CameraDBService.list_cameras(db)
            if getattr(c, 'is_monitoring', True)]
    if not cams:
        raise HTTPException(status_code=400, detail="没有监控中的摄像头")
    profiles = _load_band_profiles()

    def _run():
        with ThreadPoolExecutor(max_workers=len(cams)) as pool:
            return list(pool.map(lambda c: _apply_multispectral_to_camera(c, profiles, service), cams))

    return await run_in_threadpool(_run)


# ---------- 应用到全部摄像头（文档 §10） ----------

@router.post("/imaging/apply-all", response_model=List[ImagingActionResult])
async def apply_to_all(
    payload: ApplyAllRequest,
    db: Session = Depends(get_db),
    service: CameraService = Depends(get_camera_service),
):
    """把同一组 Imaging 参数应用到多台摄像头"""
    if not payload.settings:
        raise HTTPException(status_code=400, detail="settings 不能为空")

    all_cams = CameraDBService.list_cameras(db)
    if payload.camera_ids:
        wanted = set(payload.camera_ids)
        cams = [c for c in all_cams if c.id in wanted]
    else:
        cams = [c for c in all_cams if getattr(c, 'is_monitoring', True)]
    if not cams:
        raise HTTPException(status_code=400, detail="没有目标摄像头")

    def _apply_one(cam) -> ImagingActionResult:
        try:
            client = _get_client_for_camera(cam)
            new_settings, rejected = client.set_settings(payload.settings)
            _sync_black_filter(service, cam.id, new_settings)
            message = "已应用"
            if rejected:
                message = "部分未生效：" + "、".join(
                    f"{r['label']}（请求 {r['requested']}，实际 {r['actual']}）"
                    for r in rejected
                )
            return ImagingActionResult(
                camera_id=cam.id, name=cam.name, band_type=cam.band_type,
                success=True, message=message,
            )
        except ImagingError as e:
            return ImagingActionResult(
                camera_id=cam.id, name=cam.name, band_type=cam.band_type,
                success=False, message=str(e),
            )
        except Exception as e:
            return ImagingActionResult(
                camera_id=cam.id, name=cam.name, band_type=cam.band_type,
                success=False, message=f"设置失败: {e}",
            )

    def _run():
        with ThreadPoolExecutor(max_workers=len(cams)) as pool:
            return list(pool.map(_apply_one, cams))

    return await run_in_threadpool(_run)
