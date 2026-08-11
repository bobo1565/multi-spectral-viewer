"""Adapter bridging align3d package to ImageAlignerService."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Ensure backend root is importable
_BACKEND = Path(__file__).parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from align3d import align_batch_3d

import os

PROJECT_ROOT = Path("/app") if os.getenv("ENV") == "production" else Path(__file__).parent.parent.parent.parent
UPLOAD_DIR = str(PROJECT_ROOT / "uploads")


def _extract_band_from_path(path: str, image_band_map: Optional[Dict[str, str]] = None) -> str:
    if image_band_map and path in image_band_map:
        return image_band_map[path]
    name = Path(path).stem.lower()
    for band in ("rgb", "560nm", "650nm", "730nm", "850nm"):
        if band in name:
            return band
    # 兼容旧文件名中的 570 标注（统一视为 560nm 波段）
    if "570" in name:
        return "560nm"
    return name.split("_")[-1] if "_" in name else "unknown"


def align_batch_reconstruction_3d(
    reference_path: str,
    target_paths: List[str],
    align3d_params: Optional[Dict[str, Any]] = None,
    image_band_map: Optional[Dict[str, str]] = None,
    batch_id: Optional[str] = None,
) -> Tuple[Dict[str, np.ndarray], str]:
    """
    Run 3D reconstruction alignment for a batch.

    Returns:
        (aligned_images_map, notes) where aligned_images_map maps path -> aligned ndarray
    """
    align3d_params = align3d_params or {}
    band_map: Dict[str, str] = {}
    band_map[reference_path] = _extract_band_from_path(reference_path, image_band_map)
    for p in target_paths:
        band_map[p] = _extract_band_from_path(p, image_band_map)

    debug_dir = None
    if batch_id:
        debug_dir = str(Path(UPLOAD_DIR) / batch_id / "align3d")

    result = align_batch_3d(
        reference_path,
        target_paths,
        band_map=band_map,
        config_overrides=align3d_params,
        debug_dir=debug_dir,
        upload_root=UPLOAD_DIR,
    )

    aligned_map: Dict[str, np.ndarray] = {}
    for path, res in result.results.items():
        if res.success and res.aligned_image is not None:
            aligned_map[path] = res.aligned_image

    notes = f"{result.notes}; method={result.method_used}"
    return aligned_map, notes
