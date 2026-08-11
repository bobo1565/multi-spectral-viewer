"""Multi-view plane sweep stereo depth estimation."""
from __future__ import annotations

from typing import Dict, List, Tuple

import cv2
import numpy as np

from align3d.config import Align3DConfig
from align3d.preprocess import census_transform, preprocess_for_matching, to_gray, zncc_cost
from align3d.types import DepthResult, RigProfile


def _plane_homography(
    K_ref: np.ndarray,
    K_tgt: np.ndarray,
    R: np.ndarray,
    t: np.ndarray,
    depth: float,
    normal: np.ndarray | None = None,
) -> np.ndarray:
    """Compute plane-induced homography for given depth."""
    if normal is None:
        normal = np.array([0, 0, 1.0], dtype=np.float64)
    n = normal.reshape(3, 1)
    H = K_tgt @ (R - (t @ n.T) / depth) @ np.linalg.inv(K_ref)
    return H


def _warp_to_ref(
    tgt_proc: np.ndarray, H: np.ndarray, ref_shape: Tuple[int, int]
) -> np.ndarray:
    h, w = ref_shape
    return cv2.warpPerspective(tgt_proc, H, (w, h), flags=cv2.INTER_LINEAR)


def _compute_cost(ref_proc: np.ndarray, warped: np.ndarray, method: str) -> np.ndarray:
    if method == "census":
        ref_c = census_transform(to_gray(ref_proc) if len(ref_proc.shape) == 3 else ref_proc)
        warped_c = census_transform(to_gray(warped) if len(warped.shape) == 3 else warped)
        xor = np.bitwise_xor(ref_c.astype(np.uint64), warped_c.astype(np.uint64))
        cost = np.zeros(ref_c.shape, dtype=np.float32)
        for i in range(min(32, 64)):
            cost += ((xor >> i) & 1).astype(np.float32)
        return cost
    if method == "zncc":
        return zncc_cost(ref_proc, warped)
    # gradient
    ref_g = preprocess_for_matching(ref_proc, "gradient")
    warped_g = preprocess_for_matching(warped, "gradient")
    diff = cv2.absdiff(ref_g, warped_g).astype(np.float32)
    return diff


def _subpixel_refine(
    cost_volume: np.ndarray, depths: np.ndarray, best_idx: np.ndarray
) -> np.ndarray:
    """Parabolic sub-pixel refinement on cost volume."""
    L, h, w = cost_volume.shape
    refined = depths[best_idx, np.arange(h)[:, None], np.arange(w)[None, :]]
    for y in range(h):
        for x in range(w):
            idx = best_idx[y, x]
            if 0 < idx < L - 1:
                c0 = cost_volume[idx - 1, y, x]
                c1 = cost_volume[idx, y, x]
                c2 = cost_volume[idx + 1, y, x]
                denom = c0 - 2 * c1 + c2
                if abs(denom) > 1e-6:
                    delta = 0.5 * (c0 - c2) / denom
                    d0, d1 = depths[idx - 1], depths[idx + 1]
                    refined[y, x] = depths[idx] + delta * (d1 - d0) * 0.5
    return refined


def _guided_filter_depth(
    depth: np.ndarray, guide: np.ndarray, radius: int = 8, eps: float = 0.01
) -> np.ndarray:
    try:
        gf = cv2.ximgproc.guidedFilter(
            guide.astype(np.float32) / 255.0,
            depth.astype(np.float32),
            radius,
            eps,
        )
        return gf
    except Exception:
        return cv2.bilateralFilter(depth.astype(np.float32), 9, 75, 75)


class PlaneSweepEstimator:
    """Multi-view plane sweep depth estimator."""

    name = "plane_sweep"

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
        scale = 0.5 ** max(0, config.pyramid_levels - 1)
        if scale < 1.0:
            sw, sh = int(w * scale), int(h * scale)
            ref_small = cv2.resize(ref_image, (sw, sh))
            K_ref = ref_intr.K.copy()
            K_ref[0, 0] *= scale
            K_ref[1, 1] *= scale
            K_ref[0, 2] *= scale
            K_ref[1, 2] *= scale
        else:
            ref_small = ref_image
            sh, sw = h, w
            K_ref = ref_intr.K

        ref_proc = preprocess_for_matching(ref_small, config.cost_method)

        # Inverse depth sampling
        inv_d_min = 1.0 / config.depth_max
        inv_d_max = 1.0 / config.depth_min
        inv_depths = np.linspace(inv_d_min, inv_d_max, config.num_planes)
        depths = 1.0 / inv_depths

        cost_volume = np.full(
            (config.num_planes, sh, sw), np.inf, dtype=np.float32
        )

        valid_views = 0
        for band, tgt_img in target_images.items():
            pose = profile.get_pose(band)
            intr = profile.get_intrinsics(band)
            if pose is None or intr is None:
                continue

            if scale < 1.0:
                tgt_small = cv2.resize(tgt_img, (sw, sh))
                K_tgt = intr.K.copy()
                K_tgt[0, 0] *= scale
                K_tgt[1, 1] *= scale
                K_tgt[0, 2] *= scale
                K_tgt[1, 2] *= scale
            else:
                tgt_small = tgt_img
                K_tgt = intr.K

            tgt_proc = preprocess_for_matching(tgt_small, config.cost_method)
            valid_views += 1

            for i, d in enumerate(depths):
                H = _plane_homography(K_ref, K_tgt, pose.R, pose.t, d)
                warped = _warp_to_ref(tgt_proc, H, (sh, sw))
                cost = _compute_cost(ref_proc, warped, config.cost_method)
                cost_volume[i] = np.minimum(cost_volume[i], cost)

        if valid_views == 0:
            mask = np.zeros((sh, sw), dtype=np.uint8)
            return DepthResult(
                depth=np.zeros((sh, sw), dtype=np.float32),
                mask=mask,
                method=self.name,
                confidence=0.0,
            )

        best_idx = np.argmin(cost_volume, axis=0)
        depth_map = _subpixel_refine(cost_volume, depths.reshape(-1, 1, 1), best_idx)

        guide = to_gray(ref_small) if len(ref_small.shape) == 3 else ref_small
        depth_map = _guided_filter_depth(depth_map, guide)

        # Upsample if pyramid was used
        if scale < 1.0:
            depth_map = cv2.resize(depth_map, (w, h), interpolation=cv2.INTER_LINEAR)

        min_cost = np.min(cost_volume, axis=0)
        if scale < 1.0:
            min_cost = cv2.resize(min_cost, (w, h), interpolation=cv2.INTER_LINEAR)
        threshold = np.percentile(min_cost[np.isfinite(min_cost)], 75) if np.any(np.isfinite(min_cost)) else 999
        mask = (min_cost < threshold * 1.5).astype(np.uint8) * 255

        confidence = float(mask.sum()) / (255.0 * h * w)
        return DepthResult(
            depth=depth_map.astype(np.float32),
            mask=mask,
            method=self.name,
            confidence=confidence,
            metadata={"valid_views": valid_views, "num_planes": config.num_planes},
        )
