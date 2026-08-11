"""Depth-driven image warping and remapping."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from align3d.types import CameraIntrinsics, DepthResult, RemapPair, RigProfile


def project_ref_to_target(
    depth: np.ndarray,
    K_ref: np.ndarray,
    K_tgt: np.ndarray,
    R: np.ndarray,
    t: np.ndarray,
) -> RemapPair:
    """
    Build remap maps: for each pixel in reference view, sample from target view.

    Returns map_x, map_y suitable for cv2.remap on the TARGET image to align to REF.
    """
    h, w = depth.shape
    u, v = np.meshgrid(np.arange(w), np.arange(h))
    u = u.astype(np.float64)
    v = v.astype(np.float64)
    Z = depth.astype(np.float64)

    valid = Z > 0
    X = (u - K_ref[0, 2]) * Z / K_ref[0, 0]
    Y = (v - K_ref[1, 2]) * Z / K_ref[1, 1]
    P_ref = np.stack([X, Y, Z, np.ones_like(Z)], axis=-1)  # HxWx4

    # Transform to target camera: P_tgt = [R|t] @ P_ref
    R_t = np.hstack([R, t.reshape(3, 1)])
    P_tgt = np.einsum("ij,...j->...i", R_t, P_ref[..., :4])

    X_t = P_tgt[..., 0]
    Y_t = P_tgt[..., 1]
    Z_t = P_tgt[..., 2]

    with np.errstate(divide="ignore", invalid="ignore"):
        u_t = K_tgt[0, 0] * X_t / Z_t + K_tgt[0, 2]
        v_t = K_tgt[1, 1] * Y_t / Z_t + K_tgt[1, 2]

    map_x = u_t.astype(np.float32)
    map_y = v_t.astype(np.float32)

    # Invalidate behind camera or out of bounds
    invalid = (~valid) | (Z_t <= 0) | (map_x < 0) | (map_x >= w) | (map_y < 0) | (map_y >= h)
    map_x[invalid] = -1
    map_y[invalid] = -1

    return map_x, map_y


def warp_target_to_ref(
    target_image: np.ndarray,
    map_x: np.ndarray,
    map_y: np.ndarray,
    ref_shape: Optional[Tuple[int, int]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Warp target image to reference view using inverse mapping.

    Since map_x/map_y map ref->target coords, we invert by building
    a forward warp from target samples.
    """
    h, w = target_image.shape[:2]
    if ref_shape is None:
        ref_h, ref_w = map_x.shape
    else:
        ref_w, ref_h = ref_shape

    # Direct remap: for each ref pixel, sample target at (map_x, map_y)
    valid = (map_x >= 0) & (map_y >= 0) & (map_x < w) & (map_y < h)
    aligned = np.zeros((ref_h, ref_w, 3) if len(target_image.shape) == 3 else (ref_h, ref_w), dtype=target_image.dtype)

    if len(target_image.shape) == 3:
        aligned = cv2.remap(
            target_image,
            map_x,
            map_y,
            interpolation=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        )
    else:
        aligned = cv2.remap(
            target_image,
            map_x,
            map_y,
            interpolation=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )

    mask = valid.astype(np.uint8) * 255
    aligned = fill_holes(aligned, mask)
    return aligned, mask


def fill_holes(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Fill small holes in warped image using inpainting."""
    holes = (mask == 0).astype(np.uint8) * 255
    if holes.sum() == 0:
        return image
    if len(image.shape) == 3:
        return cv2.inpaint(image, holes, 3, cv2.INPAINT_TELEA)
    return cv2.inpaint(image, holes, 3, cv2.INPAINT_TELEA)


def align_target_with_depth(
    ref_image: np.ndarray,
    target_image: np.ndarray,
    depth_result: DepthResult,
    profile: RigProfile,
    target_band: str,
) -> Tuple[np.ndarray, np.ndarray]:
    """Align a single target image to reference using depth map."""
    ref_band = profile.reference_band
    ref_intr = profile.get_intrinsics(ref_band)
    tgt_intr = profile.get_intrinsics(target_band)
    pose = profile.get_pose(target_band)

    if ref_intr is None or tgt_intr is None or pose is None:
        raise ValueError(f"Missing calibration for band {target_band}")

    h, w = ref_image.shape[:2]
    if target_image.shape[:2] != (h, w):
        target_image = cv2.resize(target_image, (w, h))

    depth = depth_result.depth
    if depth.shape[:2] != (h, w):
        depth = cv2.resize(depth, (w, h), interpolation=cv2.INTER_LINEAR)

    map_x, map_y = project_ref_to_target(
        depth, ref_intr.K, tgt_intr.K, pose.R, pose.t
    )
    aligned, mask = warp_target_to_ref(target_image, map_x, map_y, (w, h))
    combined_mask = cv2.bitwise_and(mask, depth_result.mask)
    return aligned, combined_mask


def save_remap_cache(
    path: str,
    map_x: np.ndarray,
    map_y: np.ndarray,
    band: str,
) -> None:
    np.savez_compressed(path, map_x=map_x, map_y=map_y, band=band)


def load_remap_cache(path: str) -> Tuple[np.ndarray, np.ndarray, str]:
    data = np.load(path)
    band = str(data.get("band", ""))
    return data["map_x"], data["map_y"], band


def depth_to_colormap(depth: np.ndarray, mask: Optional[np.ndarray] = None) -> np.ndarray:
    """Convert depth map to color visualization."""
    d = depth.copy()
    if mask is not None:
        d = d.copy()
        d[mask == 0] = 0
    valid = d > 0
    if not valid.any():
        return np.zeros((*d.shape, 3), dtype=np.uint8)
    d_min, d_max = np.percentile(d[valid], [5, 95])
    norm = np.clip((d - d_min) / (d_max - d_min + 1e-6), 0, 1)
    norm = (norm * 255).astype(np.uint8)
    colored = cv2.applyColorMap(norm, cv2.COLORMAP_TURBO)
    colored[~valid] = 0
    return colored
