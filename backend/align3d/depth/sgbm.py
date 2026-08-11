"""Stereo SGBM depth estimation for self-calibration path."""
from __future__ import annotations

from typing import Dict, Tuple

import cv2
import numpy as np

from align3d.config import Align3DConfig
from align3d.preprocess import preprocess_for_matching, to_gray
from align3d.types import DepthResult, RigProfile


def _stereo_match_pair(
    ref_img: np.ndarray,
    tgt_img: np.ndarray,
    K_ref: np.ndarray,
    dist_ref: np.ndarray,
    K_tgt: np.ndarray,
    dist_tgt: np.ndarray,
    R: np.ndarray,
    t: np.ndarray,
    config: Align3DConfig,
) -> Tuple[np.ndarray, np.ndarray]:
    """Rectify and compute disparity using SGBM."""
    h, w = ref_img.shape[:2]
    R1, R2, P1, P2, Q, _, _ = cv2.stereoRectify(
        K_ref, dist_ref, K_tgt, dist_tgt, (w, h), R, t,
        flags=cv2.CALIB_ZERO_DISPARITY, alpha=0.9,
    )
    map1x, map1y = cv2.initUndistortRectifyMap(K_ref, dist_ref, R1, P1, (w, h), cv2.CV_32FC1)
    map2x, map2y = cv2.initUndistortRectifyMap(K_tgt, dist_tgt, R2, P2, (w, h), cv2.CV_32FC1)

    ref_rect = cv2.remap(ref_img, map1x, map1y, cv2.INTER_LINEAR)
    tgt_rect = cv2.remap(tgt_img, map2x, map2y, cv2.INTER_LINEAR)

    ref_gray = preprocess_for_matching(ref_rect, "clahe")
    tgt_gray = preprocess_for_matching(tgt_rect, "clahe")

    num_disp = config.sgbm_num_disparities
    if num_disp % 16 != 0:
        num_disp = (num_disp // 16 + 1) * 16

    sgbm = cv2.StereoSGBM_create(
        minDisparity=0,
        numDisparities=num_disp,
        blockSize=config.sgbm_block_size,
        P1=8 * 3 * config.sgbm_block_size ** 2,
        P2=32 * 3 * config.sgbm_block_size ** 2,
        disp12MaxDiff=1,
        uniquenessRatio=10,
        speckleWindowSize=100,
        speckleRange=32,
        mode=cv2.STEREO_SGBM_MODE_HH,
    )

    disp = sgbm.compute(ref_gray, tgt_gray).astype(np.float32) / 16.0

    if config.use_wls_filter:
        try:
            right_matcher = cv2.ximgproc.createRightMatcher(sgbm)
            disp_right = right_matcher.compute(tgt_gray, ref_gray).astype(np.float32) / 16.0
            wls = cv2.ximgproc.createDisparityWLSFilter(matcher_left=sgbm)
            wls.setLambda(8000)
            wls.setSigmaColor(1.5)
            disp = wls.filter(disp, ref_gray, None, disp_right)
        except Exception:
            pass

    # Convert disparity to pseudo-depth (relative)
    baseline = np.linalg.norm(t)
    fx = P1[0, 0]
    depth = np.zeros_like(disp)
    valid = disp > 0
    depth[valid] = (baseline * fx) / (disp[valid] + 1e-6)

    mask = (disp > 0).astype(np.uint8) * 255
    return depth, mask


class SGBMEstimator:
    """Pairwise SGBM depth estimation aggregated across views."""

    name = "sgbm"

    def estimate(
        self,
        ref_image: np.ndarray,
        target_images: Dict[str, np.ndarray],
        profile: RigProfile,
        config: Align3DConfig,
    ) -> DepthResult:
        ref_band = profile.reference_band
        ref_intr = profile.get_intrinsics(ref_band)
        if ref_intr is None:
            raise ValueError(f"No intrinsics for reference band {ref_band}")

        h, w = ref_image.shape[:2]
        depth_acc = np.zeros((h, w), dtype=np.float32)
        weight_acc = np.zeros((h, w), dtype=np.float32)
        mask_combined = np.zeros((h, w), dtype=np.uint8)
        valid_count = 0

        for band, tgt_img in target_images.items():
            pose = profile.get_pose(band)
            intr = profile.get_intrinsics(band)
            if pose is None or intr is None:
                continue

            if tgt_img.shape[:2] != (h, w):
                tgt_img = cv2.resize(tgt_img, (w, h))

            depth, mask = _stereo_match_pair(
                ref_image,
                tgt_img,
                ref_intr.K,
                ref_intr.dist,
                intr.K,
                intr.dist,
                pose.R,
                pose.t,
                config,
            )
            valid = mask > 0
            depth_acc[valid] += depth[valid]
            weight_acc[valid] += 1.0
            mask_combined = np.maximum(mask_combined, mask)
            valid_count += 1

        if valid_count == 0:
            return DepthResult(
                depth=np.zeros((h, w), dtype=np.float32),
                mask=np.zeros((h, w), dtype=np.uint8),
                method=self.name,
                confidence=0.0,
            )

        valid = weight_acc > 0
        depth_final = np.zeros((h, w), dtype=np.float32)
        depth_final[valid] = depth_acc[valid] / weight_acc[valid]

        confidence = float(mask_combined.sum()) / (255.0 * h * w)
        return DepthResult(
            depth=depth_final,
            mask=mask_combined,
            method=self.name,
            confidence=confidence,
            metadata={"valid_pairs": valid_count},
        )
