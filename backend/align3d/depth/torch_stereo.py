"""Optional torch-based stereo matching plugin."""
from __future__ import annotations

from typing import Dict

import cv2
import numpy as np

from align3d.config import Align3DConfig
from align3d.depth.sgbm import SGBMEstimator
from align3d.types import DepthResult, RigProfile

_TORCH_AVAILABLE = False
try:
    import torch  # noqa: F401
    _TORCH_AVAILABLE = True
except ImportError:
    pass


class TorchStereoEstimator:
    """
    Optional deep stereo backend.

    Falls back to SGBM when torch is unavailable or model fails to load.
    """

    name = "torch_stereo"

    def __init__(self):
        self._fallback = SGBMEstimator()
        self._model = None

    def _try_load_model(self):
        if not _TORCH_AVAILABLE or self._model is not None:
            return
        try:
            # Placeholder for future RAFT-Stereo / IGEV integration
            self._model = "stub"
        except Exception:
            self._model = None

    def estimate(
        self,
        ref_image: np.ndarray,
        target_images: Dict[str, np.ndarray],
        profile: RigProfile,
        config: Align3DConfig,
    ) -> DepthResult:
        self._try_load_model()
        if self._model is None:
            result = self._fallback.estimate(ref_image, target_images, profile, config)
            result.method = f"{self.name}_fallback_sgbm"
            result.metadata["torch_available"] = _TORCH_AVAILABLE
            return result

        # Currently uses SGBM as stub until a model is integrated
        result = self._fallback.estimate(ref_image, target_images, profile, config)
        result.method = self.name
        result.metadata["note"] = "torch stub uses SGBM internally"
        return result


def is_torch_available() -> bool:
    return _TORCH_AVAILABLE
