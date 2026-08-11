"""align3d API routes - calibration profiles, config, depth preview."""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

_BACKEND = Path(__file__).parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from align3d import (
    build_profile_from_checkerboard,
    delete_profile,
    list_profiles,
    load_config,
    preview_depth,
    save_config,
    save_profile,
)
from align3d.config import Align3DConfig

import os

PROJECT_ROOT = Path("/app") if os.getenv("ENV") == "production" else Path(__file__).parent.parent.parent.parent
UPLOAD_DIR = str(PROJECT_ROOT / "uploads")

from app.database import get_db
from app.services.batch_db_service import BatchDBService
from app.services.image_db_service import ImageDBService

router = APIRouter()


class Align3DConfigResponse(BaseModel):
    depth_min: float
    depth_max: float
    num_planes: int
    depth_backend: str
    cost_method: str
    assumed_hfov_deg: float
    fallback_to_homography: bool
    min_valid_ratio: float
    min_ncc_improvement: float
    pyramid_levels: int
    sgbm_num_disparities: int
    sgbm_block_size: int
    use_wls_filter: bool
    rig_profile: str
    checkerboard_cols: int
    checkerboard_rows: int
    checkerboard_square_size_mm: float


class Align3DConfigUpdateRequest(BaseModel):
    depth_min: Optional[float] = None
    depth_max: Optional[float] = None
    num_planes: Optional[int] = None
    depth_backend: Optional[str] = None
    cost_method: Optional[str] = None
    assumed_hfov_deg: Optional[float] = None
    fallback_to_homography: Optional[bool] = None
    min_valid_ratio: Optional[float] = None
    min_ncc_improvement: Optional[float] = None
    pyramid_levels: Optional[int] = None
    sgbm_num_disparities: Optional[int] = None
    sgbm_block_size: Optional[int] = None
    use_wls_filter: Optional[bool] = None
    rig_profile: Optional[str] = None
    checkerboard_cols: Optional[int] = None
    checkerboard_rows: Optional[int] = None
    checkerboard_square_size_mm: Optional[float] = None


class ProfileInfo(BaseModel):
    name: str
    reference_band: Optional[str] = None
    calibration_method: Optional[str] = None
    created_at: Optional[str] = None
    bands: Optional[List[str]] = None
    path: Optional[str] = None
    error: Optional[str] = None


class PreviewDepthRequest(BaseModel):
    batch_id: str
    reference_image_id: Optional[str] = None
    align3d_params: Optional[Dict[str, Any]] = None


class PreviewDepthResponse(BaseModel):
    depth_b64: str
    method: str
    confidence: float
    width: int
    height: int


class CheckerboardCalibRequest(BaseModel):
    profile_name: str = "default"
    reference_band: str = "rgb"
    band_image_dirs: Dict[str, List[str]]  # band -> list of image paths on server


@router.get("/config", response_model=Align3DConfigResponse)
async def get_align3d_config():
    cfg = load_config()
    return Align3DConfigResponse(**cfg.to_dict())


@router.put("/config", response_model=Align3DConfigResponse)
async def update_align3d_config(request: Align3DConfigUpdateRequest):
    cfg = load_config()
    overrides = {k: v for k, v in request.model_dump().items() if v is not None}
    merged = cfg.merge(overrides)
    save_config(merged)
    return Align3DConfigResponse(**merged.to_dict())


@router.get("/profiles", response_model=List[ProfileInfo])
async def get_profiles():
    profiles = list_profiles(UPLOAD_DIR)
    return [ProfileInfo(**p) for p in profiles]


@router.delete("/profiles/{name}")
async def remove_profile(name: str):
    ok = delete_profile(name, UPLOAD_DIR)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
    return {"message": f"Profile '{name}' deleted"}


@router.post("/profiles/checkerboard")
async def create_checkerboard_profile(
    profile_name: str = Form("default"),
    reference_band: str = Form("rgb"),
    bands: str = Form(..., description="Comma-separated band names"),
    files: List[UploadFile] = File(...),
    band_labels: str = Form(..., description="Comma-separated band label per file, same order as files"),
):
    """
    Upload checkerboard calibration images and build rig profile.

    Each file should be labeled with its band via band_labels (same order as files).
    """
    band_list = [b.strip() for b in bands.split(",")]
    label_list = [l.strip() for l in band_labels.split(",")]

    if len(files) != len(label_list):
        raise HTTPException(status_code=400, detail="files and band_labels count mismatch")

    calib_tmp = Path(UPLOAD_DIR) / "calib" / "tmp" / profile_name
    calib_tmp.mkdir(parents=True, exist_ok=True)

    band_images: Dict[str, List[str]] = {b: [] for b in band_list}
    for uf, label in zip(files, label_list):
        if label not in band_images:
            band_images[label] = []
        dest = calib_tmp / label / uf.filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = await uf.read()
        dest.write_bytes(content)
        band_images[label].append(str(dest))

    try:
        profile = build_profile_from_checkerboard(
            band_images,
            reference_band=reference_band,
            profile_name=profile_name,
        )
        path = save_profile(profile, UPLOAD_DIR)
        return {
            "message": "标定档案创建成功",
            "profile_name": profile.name,
            "path": path,
            "bands": list(profile.intrinsics.keys()),
            "errors": profile.metadata.get("reprojection_errors", {}),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"标定失败: {str(exc)}")


@router.post("/profiles/selfcalib")
async def create_selfcalib_profile(
    batch_id: str = Form(...),
    profile_name: str = Form("selfcalib"),
    reference_image_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Build self-calibration profile from a batch's source images."""
    from align3d.calibration.selfcalib import build_profile_from_images
    import cv2

    batch_images = BatchDBService.get_batch_images(db, batch_id)
    band_images = {}
    ref_band = "rgb"

    for band, img in batch_images.items():
        if img and getattr(img, "image_type", "source") == "source":
            if img.filepath and Path(img.filepath).exists():
                arr = cv2.imread(img.filepath)
                if arr is not None:
                    band_images[band] = arr

    if not band_images:
        raise HTTPException(status_code=404, detail="批次中没有可用的 source 图像")

    if reference_image_id:
        ref_img = ImageDBService.get_image(db, reference_image_id)
        if ref_img:
            ref_band = ref_img.band_type or "rgb"

    profile = build_profile_from_images(band_images, reference_band=ref_band, profile_name=profile_name)
    path = save_profile(profile, UPLOAD_DIR)
    return {
        "message": "自标定档案创建成功",
        "profile_name": profile.name,
        "path": path,
        "bands": list(profile.intrinsics.keys()),
        "inliers": profile.metadata.get("inlier_counts", {}),
    }


@router.post("/preview-depth", response_model=PreviewDepthResponse)
async def preview_depth_map(request: PreviewDepthRequest, db: Session = Depends(get_db)):
    """Generate depth preview for a batch without full alignment."""
    batch_images = BatchDBService.get_batch_images(db, request.batch_id)
    source_images = []
    for band, img in batch_images.items():
        if img and getattr(img, "image_type", "source") == "source":
            source_images.append(img)

    if not source_images:
        raise HTTPException(status_code=404, detail="批次中没有 source 图像")

    ref_obj = None
    if request.reference_image_id:
        ref_obj = ImageDBService.get_image(db, request.reference_image_id)
    if ref_obj is None:
        ref_obj = batch_images.get("rgb") or source_images[0]

    ref_path = str(Path(ref_obj.filepath).absolute())
    target_paths = [
        str(Path(img.filepath).absolute())
        for img in source_images
        if img.id != ref_obj.id
    ]

    band_map = {}
    for img in source_images:
        band_map[str(Path(img.filepath).absolute())] = img.band_type or "unknown"

    try:
        colormap, depth_result, method = preview_depth(
            ref_path,
            target_paths,
            band_map=band_map,
            config_overrides=request.align3d_params,
            upload_root=UPLOAD_DIR,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"深度预览失败: {str(exc)}")

    _, buf = cv2.imencode(".png", colormap)
    depth_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

    h, w = colormap.shape[:2]
    return PreviewDepthResponse(
        depth_b64=depth_b64,
        method=method,
        confidence=depth_result.confidence,
        width=w,
        height=h,
    )
