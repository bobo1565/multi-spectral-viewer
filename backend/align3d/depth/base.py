"""Depth estimator protocol."""
from __future__ import annotations

from typing import Dict, Protocol, runtime_checkable

import numpy as np

from align3d.config import Align3DConfig
from align3d.types import DepthResult, RigProfile


@runtime_checkable
class DepthEstimator(Protocol):
    """Protocol for depth estimation backends."""

    name: str

    def estimate(
        self,
        ref_image: np.ndarray,
        target_images: Dict[str, np.ndarray],
        profile: RigProfile,
        config: Align3DConfig,
    ) -> DepthResult:
        """Estimate depth map from reference view using target views."""
        ...
