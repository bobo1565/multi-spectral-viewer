"""Checkerboard-based multi-camera calibration."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from align3d.config import Align3DConfig
from align3d.types import CameraIntrinsics, RigPose, RigProfile


def _get_sift():
    try:
        return cv2.SIFT_create()
    except AttributeError:
        return cv2.xfeatures2d.SIFT_create()


def detect_checkerboard(
    image: np.ndarray,
    cols: int,
    rows: int,
) -> Tuple[bool, Optional[np.ndarray]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    pattern_size = (cols, rows)
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE
    found, corners = cv2.findChessboardCorners(gray, pattern_size, flags)
    if not found:
        return False, None
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    corners = cv2.cornerSubPix(
        gray, corners, (11, 11), (-1, -1), criteria
    )
    return True, corners


def build_object_points(cols: int, rows: int, square_size: float) -> np.ndarray:
    objp = np.zeros((cols * rows, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp *= square_size
    return objp


def calibrate_single_camera(
    image_paths: List[str],
    cols: int,
    rows: int,
    square_size: float,
) -> Tuple[Optional[CameraIntrinsics], float]:
    """Calibrate one camera from multiple checkerboard images."""
    objp = build_object_points(cols, rows, square_size)
    obj_points: List[np.ndarray] = []
    img_points: List[np.ndarray] = []
    img_size = None

    for path in image_paths:
        img = cv2.imread(path)
        if img is None:
            continue
        found, corners = detect_checkerboard(img, cols, rows)
        if found and corners is not None:
            obj_points.append(objp)
            img_points.append(corners)
            img_size = (img.shape[1], img.shape[0])

    if len(obj_points) < 3 or img_size is None:
        return None, 999.0

    ret, K, dist, _rvecs, _tvecs = cv2.calibrateCamera(
        obj_points, img_points, img_size, None, None
    )
    intrinsics = CameraIntrinsics(
        K=K, dist=dist, width=img_size[0], height=img_size[1]
    )
    return intrinsics, float(ret)


def stereo_calibrate_pair(
    ref_intrinsics: CameraIntrinsics,
    tgt_intrinsics: CameraIntrinsics,
    ref_paths: List[str],
    tgt_paths: List[str],
    cols: int,
    rows: int,
    square_size: float,
) -> Tuple[Optional[RigPose], float]:
    """Stereo calibrate target camera relative to reference."""
    objp = build_object_points(cols, rows, square_size)
    obj_points: List[np.ndarray] = []
    ref_img_points: List[np.ndarray] = []
    tgt_img_points: List[np.ndarray] = []

    for ref_path, tgt_path in zip(ref_paths, tgt_paths):
        ref_img = cv2.imread(ref_path)
        tgt_img = cv2.imread(tgt_path)
        if ref_img is None or tgt_img is None:
            continue
        ref_found, ref_corners = detect_checkerboard(ref_img, cols, rows)
        tgt_found, tgt_corners = detect_checkerboard(tgt_img, cols, rows)
        if ref_found and tgt_found:
            obj_points.append(objp)
            ref_img_points.append(ref_corners)
            tgt_img_points.append(tgt_corners)

    if len(obj_points) < 3:
        return None, 999.0

    criteria = (cv2.TERM_CRITERIA_MAX_ITER + cv2.TERM_CRITERIA_EPS, 100, 1e-5)
    flags = cv2.CALIB_FIX_INTRINSIC

    ret, _K1, _D1, _K2, _D2, R, t, _E, _F = cv2.stereoCalibrate(
        obj_points,
        ref_img_points,
        tgt_img_points,
        ref_intrinsics.K,
        ref_intrinsics.dist,
        tgt_intrinsics.K,
        tgt_intrinsics.dist,
        (ref_intrinsics.width, ref_intrinsics.height),
        criteria=criteria,
        flags=flags,
    )
    pose = RigPose(R=R, t=t.reshape(3, 1), reprojection_error=float(ret))
    return pose, float(ret)


def build_profile_from_checkerboard(
    band_images: Dict[str, List[str]],
    reference_band: str = "rgb",
    profile_name: str = "default",
    config: Optional[Align3DConfig] = None,
) -> RigProfile:
    """
    Build rig profile from checkerboard calibration images.

    band_images: {band: [list of image paths]}
    """
    cfg = config or Align3DConfig()
    cols = cfg.checkerboard_cols
    rows = cfg.checkerboard_rows
    square_size = cfg.checkerboard_square_size_mm

    intrinsics_map: Dict[str, CameraIntrinsics] = {}
    errors: Dict[str, float] = {}

    for band, paths in band_images.items():
        intr, err = calibrate_single_camera(paths, cols, rows, square_size)
        if intr is not None:
            intrinsics_map[band] = intr
            errors[band] = err

    if reference_band not in intrinsics_map:
        raise ValueError(f"Reference band '{reference_band}' calibration failed")

    ref_intr = intrinsics_map[reference_band]
    ref_paths = band_images[reference_band]
    poses: Dict[str, RigPose] = {
        reference_band: RigPose(
            R=np.eye(3), t=np.zeros((3, 1)), band=reference_band, reprojection_error=0.0
        )
    }

    for band, intr in intrinsics_map.items():
        if band == reference_band:
            continue
        tgt_paths = band_images.get(band, [])
        if len(tgt_paths) != len(ref_paths):
            min_len = min(len(ref_paths), len(tgt_paths))
            ref_paths_pair = ref_paths[:min_len]
            tgt_paths_pair = tgt_paths[:min_len]
        else:
            ref_paths_pair = ref_paths
            tgt_paths_pair = tgt_paths

        pose, err = stereo_calibrate_pair(
            ref_intr, intr, ref_paths_pair, tgt_paths_pair, cols, rows, square_size
        )
        if pose is not None:
            pose.band = band
            poses[band] = pose
            errors[band] = err

    return RigProfile(
        name=profile_name,
        reference_band=reference_band,
        intrinsics=intrinsics_map,
        poses=poses,
        calibration_method="checkerboard",
        created_at=datetime.utcnow().isoformat(),
        metadata={"reprojection_errors": errors},
    )


def estimate_intrinsics_from_size(
    width: int, height: int, hfov_deg: float = 60.0
) -> CameraIntrinsics:
    """Approximate intrinsics from image size and assumed HFOV."""
    hfov = np.radians(hfov_deg)
    fx = width / (2 * np.tan(hfov / 2))
    fy = fx
    cx, cy = width / 2.0, height / 2.0
    K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)
    dist = np.zeros(5, dtype=np.float64)
    return CameraIntrinsics(K=K, dist=dist, width=width, height=height)
