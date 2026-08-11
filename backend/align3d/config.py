"""Configuration for align3d with hot-reload from align3d.json."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "align3d.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "depth_min": 0.5,
    "depth_max": 20.0,
    "num_planes": 32,
    "depth_backend": "auto",  # auto | plane_sweep | sgbm | torch_stereo
    "cost_method": "census",  # census | zncc | gradient
    "assumed_hfov_deg": 60.0,
    "fallback_to_homography": True,
    "min_valid_ratio": 0.3,
    "min_ncc_improvement": -0.05,
    "pyramid_levels": 2,
    "sgbm_num_disparities": 128,
    "sgbm_block_size": 7,
    "use_wls_filter": True,
    "rig_profile": "",
    "checkerboard_cols": 9,
    "checkerboard_rows": 6,
    "checkerboard_square_size_mm": 25.0,
    "description": "默认三维重建对齐配置 - 可通过 API 动态修改",
}


@dataclass
class Align3DConfig:
    depth_min: float = 0.5
    depth_max: float = 20.0
    num_planes: int = 32
    depth_backend: str = "auto"
    cost_method: str = "census"
    assumed_hfov_deg: float = 60.0
    fallback_to_homography: bool = True
    min_valid_ratio: float = 0.3
    min_ncc_improvement: float = -0.05
    pyramid_levels: int = 2
    sgbm_num_disparities: int = 128
    sgbm_block_size: int = 7
    use_wls_filter: bool = True
    rig_profile: str = ""
    checkerboard_cols: int = 9
    checkerboard_rows: int = 6
    checkerboard_square_size_mm: float = 25.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Align3DConfig":
        fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**fields)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def merge(self, overrides: Optional[Dict[str, Any]]) -> "Align3DConfig":
        if not overrides:
            return self
        merged = self.to_dict()
        for k, v in overrides.items():
            if k in merged and v is not None:
                merged[k] = v
        return Align3DConfig.from_dict(merged)


def load_config() -> Align3DConfig:
    """Load config from disk (hot reload on every call)."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Align3DConfig.from_dict({**DEFAULT_CONFIG, **data})
        except Exception as exc:
            print(f"[align3d] Error loading config: {exc}")
    return Align3DConfig.from_dict(DEFAULT_CONFIG)


def save_config(config: Align3DConfig) -> None:
    """Persist config to align3d.json."""
    data = {**DEFAULT_CONFIG, **config.to_dict(), "description": DEFAULT_CONFIG["description"]}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[align3d] Config saved to {CONFIG_PATH}")


def get_calib_dir(upload_root: Optional[str] = None) -> Path:
    """Return calibration profiles directory."""
    if upload_root:
        root = Path(upload_root)
    else:
        root = Path(__file__).parent.parent.parent / "uploads"
    calib_dir = root / "calib"
    calib_dir.mkdir(parents=True, exist_ok=True)
    return calib_dir
