"""Self-calibration fallback using feature matching."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from align3d.calibration.checkerboard import estimate_intrinsics_from_size
from align3d.config import Align3DConfig
from align3d.preprocess import preprocess_for_matching
from align3d.types import CameraIntrinsics, RigPose, RigProfile


def _get_sift():
    try:
        return cv2.SIFT_create()
    except AttributeError:
        return cv2.xfeatures2d.SIFT_create()


def match_features(img1: np.ndarray, img2: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Match SIFT features between two preprocessed images."""
    g1 = preprocess_for_matching(img1, "clahe")
    g2 = preprocess_for_matching(img2, "clahe")
    sift = _get_sift()
    kp1, des1 = sift.detectAndCompute(g1, None)
    kp2, des2 = sift.detectAndCompute(g2, None)
    if des1 is None or des2 is None or len(kp1) < 8 or len(kp2) < 8:
        return np.array([]), np.array([])

    bf = cv2.BFMatcher()
    matches = bf.knnMatch(des1, des2, k=2)
    good = []
    for pair in matches:
        if len(pair) == 2:
            m, n = pair
            if m.distance < 0.75 * n.distance:
                good.append(m)

    if len(good) < 8:
        return np.array([]), np.array([])

    pts1 = np.float32([kp1[m.queryIdx].pt for m in good])
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good])
    return pts1, pts2


def estimate_pose_from_images(
    ref_img: np.ndarray,
    tgt_img: np.ndarray,
    K: np.ndarray,
) -> Tuple[Optional[RigPose], int]:
    """Estimate relative pose using F -> E -> recoverPose."""
    pts1, pts2 = match_features(ref_img, tgt_img)
    if len(pts1) < 8:
        return None, 0

    F, mask = cv2.findFundamentalMat(pts1, pts2, cv2.FM_RANSAC, 1.0, 0.99)
    if F is None or mask is None:
        return None, 0

    inliers = int(mask.ravel().sum())
    if inliers < 8:
        return None, inliers

    E = K.T @ F @ K
    _, R, t, pose_mask = cv2.recoverPose(E, pts1, pts2, K)
    inliers_pose = int(pose_mask.ravel().sum()) if pose_mask is not None else inliers

    if inliers_pose < 8:
        return None, inliers_pose

    pose = RigPose(R=R, t=t.reshape(3, 1), reprojection_error=float(inliers_pose))
    return pose, inliers_pose


def build_profile_from_images(
    band_images: Dict[str, np.ndarray],
    reference_band: str = "rgb",
    profile_name: str = "selfcalib",
    config: Optional[Align3DConfig] = None,
) -> RigProfile:
    """
    Build approximate rig profile from a single set of scene images (self-calibration).

    band_images: {band: BGR image ndarray}
    """
    cfg = config or Align3DConfig()
    if reference_band not in band_images:
        raise ValueError(f"Reference band '{reference_band}' not in images")

    ref_img = band_images[reference_band]
    h, w = ref_img.shape[:2]
    ref_intr = estimate_intrinsics_from_size(w, h, cfg.assumed_hfov_deg)

    intrinsics_map: Dict[str, CameraIntrinsics] = {reference_band: ref_intr}
    poses: Dict[str, RigPose] = {
        reference_band: RigPose(
            R=np.eye(3), t=np.zeros((3, 1)), band=reference_band
        )
    }
    inlier_counts: Dict[str, int] = {}

    for band, img in band_images.items():
        if band == reference_band:
            continue
        ih, iw = img.shape[:2]
        intrinsics_map[band] = estimate_intrinsics_from_size(iw, ih, cfg.assumed_hfov_deg)
        pose, inliers = estimate_pose_from_images(ref_img, img, ref_intr.K)
        if pose is not None:
            pose.band = band
            poses[band] = pose
            inlier_counts[band] = inliers

    return RigProfile(
        name=profile_name,
        reference_band=reference_band,
        intrinsics=intrinsics_map,
        poses=poses,
        calibration_method="selfcalib",
        created_at=datetime.utcnow().isoformat(),
        metadata={"inlier_counts": inlier_counts},
    )
