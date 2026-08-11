"""Data types for the align3d package."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple
import json
import numpy as np


@dataclass
class CameraIntrinsics:
    """Camera intrinsic parameters."""

    K: np.ndarray  # 3x3
    dist: np.ndarray  # distortion coefficients
    width: int
    height: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "K": self.K.tolist(),
            "dist": self.dist.tolist(),
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CameraIntrinsics":
        return cls(
            K=np.array(data["K"], dtype=np.float64),
            dist=np.array(data.get("dist", [0, 0, 0, 0, 0]), dtype=np.float64),
            width=int(data["width"]),
            height=int(data["height"]),
        )


@dataclass
class RigPose:
    """Extrinsic pose of a camera relative to the reference camera."""

    R: np.ndarray  # 3x3 rotation
    t: np.ndarray  # 3x1 translation
    band: str = ""
    reprojection_error: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "R": self.R.tolist(),
            "t": self.t.reshape(-1).tolist(),
            "band": self.band,
            "reprojection_error": self.reprojection_error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RigPose":
        return cls(
            R=np.array(data["R"], dtype=np.float64),
            t=np.array(data["t"], dtype=np.float64).reshape(3, 1),
            band=data.get("band", ""),
            reprojection_error=float(data.get("reprojection_error", 0.0)),
        )


@dataclass
class RigProfile:
    """Multi-camera rig calibration profile."""

    name: str
    reference_band: str
    intrinsics: Dict[str, CameraIntrinsics]  # band -> intrinsics
    poses: Dict[str, RigPose]  # band -> pose relative to reference
    calibration_method: str = "checkerboard"  # checkerboard | selfcalib
    created_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "reference_band": self.reference_band,
            "intrinsics": {k: v.to_dict() for k, v in self.intrinsics.items()},
            "poses": {k: v.to_dict() for k, v in self.poses.items()},
            "calibration_method": self.calibration_method,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RigProfile":
        return cls(
            name=data["name"],
            reference_band=data["reference_band"],
            intrinsics={
                k: CameraIntrinsics.from_dict(v)
                for k, v in data.get("intrinsics", {}).items()
            },
            poses={k: RigPose.from_dict(v) for k, v in data.get("poses", {}).items()},
            calibration_method=data.get("calibration_method", "checkerboard"),
            created_at=data.get("created_at", ""),
            metadata=data.get("metadata", {}),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "RigProfile":
        return cls.from_dict(json.loads(text))

    def get_intrinsics(self, band: str) -> Optional[CameraIntrinsics]:
        return self.intrinsics.get(band)

    def get_pose(self, band: str) -> Optional[RigPose]:
        return self.poses.get(band)


@dataclass
class DepthResult:
    """Depth estimation output."""

    depth: np.ndarray  # HxW float32, metric or relative depth
    mask: np.ndarray  # HxW uint8, 255=valid
    method: str = ""
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Align3DResult:
    """Result for a single target image alignment."""

    success: bool
    aligned_image: Optional[np.ndarray] = None
    message: str = ""
    method_used: str = ""
    depth_result: Optional[DepthResult] = None
    valid_ratio: float = 0.0
    ncc_score: float = 0.0
    debug_paths: Dict[str, str] = field(default_factory=dict)


@dataclass
class BatchAlign3DResult:
    """Batch alignment result."""

    results: Dict[str, Align3DResult]  # path -> result
    reference_path: str = ""
    method_used: str = ""
    notes: str = ""
    debug_dir: str = ""

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results.values() if r.success)


BandImageMap = Dict[str, np.ndarray]
PathImageMap = Dict[str, np.ndarray]
RemapPair = Tuple[np.ndarray, np.ndarray]
