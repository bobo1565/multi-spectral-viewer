"""Main 3D alignment pipeline with quality gating and fallback chain."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from align3d.calibration.profile_store import load_profile
from align3d.calibration.selfcalib import build_profile_from_images
from align3d.config import Align3DConfig, load_config
from align3d.depth.plane_sweep import PlaneSweepEstimator
from align3d.depth.sgbm import SGBMEstimator
from align3d.depth.torch_stereo import TorchStereoEstimator
from align3d.preprocess import compute_ncc_score
from align3d.types import Align3DResult, BatchAlign3DResult, DepthResult, RigProfile
from align3d.warp import (
    align_target_with_depth,
    depth_to_colormap,
    project_ref_to_target,
    save_remap_cache,
    warp_target_to_ref,
)


def _get_estimator(name: str):
    estimators = {
        "plane_sweep": PlaneSweepEstimator(),
        "sgbm": SGBMEstimator(),
        "torch_stereo": TorchStereoEstimator(),
    }
    return estimators.get(name)


def _homography_fallback(ref_img: np.ndarray, tgt_img: np.ndarray) -> Optional[np.ndarray]:
    """Fallback to homography alignment using SIFT."""
    default_roi = {
        "roi_x_ratio": 0.25,
        "roi_y_ratio": 0.25,
        "roi_width_ratio": 0.5,
        "roi_height_ratio": 0.5,
    }
    try:
        from app.core.feature_matching_algo import align_images
        return align_images(ref_img, tgt_img, roi_config1=default_roi, roi_config2=default_roi)
    except ImportError:
        pass
    except ValueError:
        pass

    # Standalone usage without app
    sift = cv2.SIFT_create()
    g1 = cv2.cvtColor(ref_img, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(tgt_img, cv2.COLOR_BGR2GRAY)
    kp1, des1 = sift.detectAndCompute(g1, None)
    kp2, des2 = sift.detectAndCompute(g2, None)
    if des1 is None or des2 is None:
        return None
    bf = cv2.BFMatcher()
    matches = bf.knnMatch(des1, des2, k=2)
    good = [m for m, n in matches if m.distance < 0.75 * n.distance]
    if len(good) < 8:
        return None
    pts1 = np.float32([kp1[m.queryIdx].pt for m in good])
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good])
    H, _ = cv2.findHomography(pts2, pts1, cv2.RANSAC, 1.0)
    if H is None:
        return None
    h, w = ref_img.shape[:2]
    return cv2.warpPerspective(tgt_img, H, (w, h))


def _resolve_profile(
    ref_image: np.ndarray,
    band_images: Dict[str, np.ndarray],
    reference_band: str,
    config: Align3DConfig,
    upload_root: Optional[str] = None,
) -> Tuple[RigProfile, str]:
    """Load or build rig profile."""
    if config.rig_profile:
        profile = load_profile(config.rig_profile, upload_root)
        if profile is not None:
            return profile, "loaded"

    profile = build_profile_from_images(band_images, reference_band, "selfcalib", config)
    return profile, "selfcalib"


def _estimate_depth(
    ref_image: np.ndarray,
    target_images: Dict[str, np.ndarray],
    profile: RigProfile,
    config: Align3DConfig,
) -> Tuple[DepthResult, str]:
    """Run depth estimation with backend selection."""
    backend = config.depth_backend
    if backend == "auto":
        if profile.calibration_method == "checkerboard":
            backend = "plane_sweep"
        else:
            backend = "sgbm"

    estimator = _get_estimator(backend)
    if estimator is None:
        estimator = SGBMEstimator()
        backend = "sgbm"

    try:
        result = estimator.estimate(ref_image, target_images, profile, config)
        return result, backend
    except Exception as exc:
        print(f"[align3d] Depth estimation failed ({backend}): {exc}")
        if backend != "sgbm":
            fallback = SGBMEstimator()
            result = fallback.estimate(ref_image, target_images, profile, config)
            return result, "sgbm_fallback"
        raise


def _save_debug_artifacts(
    debug_dir: Path,
    depth_result: DepthResult,
    profile: RigProfile,
    method: str,
) -> Dict[str, str]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    depth_vis = depth_to_colormap(depth_result.depth, depth_result.mask)
    depth_path = debug_dir / "depth_colormap.png"
    cv2.imwrite(str(depth_path), depth_vis)
    paths["depth_colormap"] = str(depth_path)

    mask_path = debug_dir / "depth_mask.png"
    cv2.imwrite(str(mask_path), depth_result.mask)
    paths["depth_mask"] = str(mask_path)

    depth_npy = debug_dir / "depth.npy"
    np.save(str(depth_npy), depth_result.depth)
    paths["depth_npy"] = str(depth_npy)

    meta_path = debug_dir / "method.txt"
    meta_path.write_text(f"method={method}\nconfidence={depth_result.confidence}\n")
    paths["method"] = str(meta_path)
    return paths


def align_batch_3d(
    reference_path: str,
    target_paths: List[str],
    band_map: Optional[Dict[str, str]] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
    debug_dir: Optional[str] = None,
    upload_root: Optional[str] = None,
) -> BatchAlign3DResult:
    """
    Align a batch of images using 3D reconstruction.

    Args:
        reference_path: Path to reference image
        target_paths: Paths to target images
        band_map: path -> band name mapping
        config_overrides: Override align3d config parameters
        debug_dir: Directory for debug artifacts
        upload_root: Upload root for calibration profiles
    """
    config = load_config().merge(config_overrides or {})
    band_map = band_map or {}

    ref_img = cv2.imread(reference_path)
    if ref_img is None:
        raise ValueError(f"Cannot load reference image: {reference_path}")

    ref_band = band_map.get(reference_path, "rgb")
    band_images: Dict[str, np.ndarray] = {ref_band: ref_img}
    path_to_band: Dict[str, str] = {reference_path: ref_band}
    target_images: Dict[str, np.ndarray] = {}

    for path in target_paths:
        img = cv2.imread(path)
        if img is None:
            continue
        band = band_map.get(path, Path(path).stem.split("_")[-1].replace(".jpg", ""))
        band_images[band] = img
        path_to_band[path] = band
        target_images[band] = img

    profile, profile_source = _resolve_profile(
        ref_img, band_images, ref_band, config, upload_root
    )

    depth_result, depth_method = _estimate_depth(ref_img, target_images, profile, config)
    valid_ratio = float(depth_result.mask.sum()) / (255.0 * depth_result.mask.size)

    debug_paths = {}
    if debug_dir:
        debug_paths = _save_debug_artifacts(Path(debug_dir), depth_result, profile, depth_method)

    results: Dict[str, Align3DResult] = {}
    method_used = depth_method
    notes_parts = [f"profile={profile_source}", f"depth={depth_method}", f"valid_ratio={valid_ratio:.2f}"]

    # Reference image passthrough
    results[reference_path] = Align3DResult(
        success=True,
        aligned_image=ref_img.copy(),
        message="参考图直接保存",
        method_used=method_used,
        depth_result=depth_result,
        valid_ratio=valid_ratio,
        debug_paths=debug_paths,
    )

    use_fallback = valid_ratio < config.min_valid_ratio

    for path in target_paths:
        band = path_to_band.get(path, "")
        tgt_img = band_images.get(band)
        if tgt_img is None:
            results[path] = Align3DResult(success=False, message=f"无法加载目标图: {path}")
            continue

        aligned = None
        ncc_3d = 0.0
        ncc_homo = 0.0
        msg = ""
        used_method = method_used

        if not use_fallback:
            try:
                aligned, mask = align_target_with_depth(
                    ref_img, tgt_img, depth_result, profile, band
                )
                ncc_3d = compute_ncc_score(ref_img, aligned, mask)
            except Exception as exc:
                print(f"[align3d] 3D warp failed for {band}: {exc}")
                aligned = None

        homo_aligned = _homography_fallback(ref_img, tgt_img)
        if homo_aligned is not None:
            ncc_homo = compute_ncc_score(ref_img, homo_aligned)

        if aligned is None or (
            config.fallback_to_homography
            and ncc_3d < ncc_homo + config.min_ncc_improvement
        ):
            if homo_aligned is not None and config.fallback_to_homography:
                aligned = homo_aligned
                used_method = "homography_fallback"
                msg = f"回退到单应矩阵 (NCC: 3d={ncc_3d:.3f}, homo={ncc_homo:.3f})"
                notes_parts.append(f"{band}:homography_fallback")
            else:
                results[path] = Align3DResult(
                    success=False,
                    message="对齐失败：3D 与单应均失败",
                    method_used=used_method,
                )
                continue
        else:
            msg = f"3D 对齐成功 (NCC={ncc_3d:.3f})"
            # Save remap cache
            if debug_dir and band in profile.poses:
                ref_intr = profile.get_intrinsics(ref_band)
                tgt_intr = profile.get_intrinsics(band)
                pose = profile.get_pose(band)
                if ref_intr and tgt_intr and pose:
                    map_x, map_y = project_ref_to_target(
                        depth_result.depth, ref_intr.K, tgt_intr.K, pose.R, pose.t
                    )
                    cache_path = str(Path(debug_dir) / f"remap_{band}.npz")
                    save_remap_cache(cache_path, map_x, map_y, band)
                    debug_paths[f"remap_{band}"] = cache_path

        results[path] = Align3DResult(
            success=True,
            aligned_image=aligned,
            message=msg,
            method_used=used_method,
            depth_result=depth_result,
            valid_ratio=valid_ratio,
            ncc_score=max(ncc_3d, ncc_homo),
            debug_paths=debug_paths,
        )

    return BatchAlign3DResult(
        results=results,
        reference_path=reference_path,
        method_used=method_used,
        notes="; ".join(notes_parts),
        debug_dir=debug_dir or "",
    )


def preview_depth(
    reference_path: str,
    target_paths: List[str],
    band_map: Optional[Dict[str, str]] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
    upload_root: Optional[str] = None,
) -> Tuple[np.ndarray, DepthResult, str]:
    """Generate depth preview colormap without full alignment."""
    config = load_config().merge(config_overrides or {})
    band_map = band_map or {}

    ref_img = cv2.imread(reference_path)
    if ref_img is None:
        raise ValueError(f"Cannot load reference: {reference_path}")

    ref_band = band_map.get(reference_path, "rgb")
    band_images = {ref_band: ref_img}
    target_images = {}

    for path in target_paths:
        img = cv2.imread(path)
        if img is None:
            continue
        band = band_map.get(path, Path(path).stem)
        band_images[band] = img
        target_images[band] = img

    profile, _ = _resolve_profile(ref_img, band_images, ref_band, config, upload_root)
    depth_result, method = _estimate_depth(ref_img, target_images, profile, config)
    colormap = depth_to_colormap(depth_result.depth, depth_result.mask)
    return colormap, depth_result, method
