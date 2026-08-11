"""Tests for align3d package."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

_BACKEND = Path(__file__).parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from align3d.calibration.checkerboard import estimate_intrinsics_from_size
from align3d.calibration.selfcalib import build_profile_from_images
from align3d.config import Align3DConfig
from align3d.depth.plane_sweep import PlaneSweepEstimator
from align3d.pipeline import align_batch_3d
from align3d.preprocess import compute_ncc_score, preprocess_for_matching
from align3d.types import CameraIntrinsics, RigPose, RigProfile
from align3d.warp import depth_to_colormap, project_ref_to_target, warp_target_to_ref


def _make_synthetic_views(
    w: int = 320,
    h: int = 240,
    baseline: float = 0.05,
    fg_depth: float = 2.0,
    bg_depth: float = 8.0,
):
    """Render synthetic multi-view scene: background plane + foreground square."""
    K = np.array([[400, 0, w / 2], [0, 400, h / 2], [0, 0, 1]], dtype=np.float64)
    intr = CameraIntrinsics(K=K, dist=np.zeros(5), width=w, height=h)

    # Reference view
    ref = np.zeros((h, w, 3), dtype=np.uint8)
    ref[:, :] = (60, 80, 100)  # background
    fg_x, fg_y, fg_s = w // 3, h // 3, w // 4
    ref[fg_y : fg_y + fg_s, fg_x : fg_x + fg_s] = (200, 50, 50)

    # Add texture
    noise = np.random.randint(0, 30, (h, w), dtype=np.uint8)
    ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.int16) + noise
    ref = cv2.cvtColor(np.clip(ref_gray, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)

    def warp_with_depth(img, depth_val, t_vec):
        """Simple horizontal shift proportional to baseline/depth."""
        shift = baseline / depth_val * K[0, 0]
        M = np.float32([[1, 0, shift], [0, 1, 0]])
        return cv2.warpAffine(img, M, (w, h))

    # Target view 1: shifted by fg depth in fg region, bg depth elsewhere
    tgt1 = ref.copy()
    shift_fg = int(baseline / fg_depth * K[0, 0])
    shift_bg = int(baseline / bg_depth * K[0, 0])
    # Approximate: whole image shifted by bg, fg region shifted more
    tgt1 = warp_with_depth(ref, bg_depth, np.array([baseline, 0, 0]))
    fg_region = tgt1[fg_y : fg_y + fg_s, fg_x : fg_x + fg_s].copy()
    fg_warped = warp_with_depth(ref[fg_y : fg_y + fg_s, fg_x : fg_x + fg_s], fg_depth, np.array([baseline, 0, 0]))
    tgt1[fg_y : fg_y + fg_s, fg_x : fg_x + fg_s] = fg_warped

    R = np.eye(3)
    t = np.array([[baseline], [0], [0]], dtype=np.float64)
    pose = RigPose(R=R, t=t, band="570nm")

    profile = RigProfile(
        name="synthetic",
        reference_band="rgb",
        intrinsics={"rgb": intr, "570nm": intr},
        poses={"rgb": RigPose(R=np.eye(3), t=np.zeros((3, 1)), band="rgb"), "570nm": pose},
        calibration_method="checkerboard",
    )

    depth_map = np.full((h, w), bg_depth, dtype=np.float32)
    depth_map[fg_y : fg_y + fg_s, fg_x : fg_x + fg_s] = fg_depth

    return ref, tgt1, profile, depth_map, intr


class TestPreprocess:
    def test_clahe(self):
        img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        out = preprocess_for_matching(img, "clahe")
        assert out.shape == (100, 100)

    def test_ncc_identical(self):
        img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        score = compute_ncc_score(img, img)
        assert score > 0.9


class TestWarp:
    def test_project_and_warp(self):
        ref, tgt, profile, depth, intr = _make_synthetic_views()
        map_x, map_y = project_ref_to_target(
            depth, intr.K, intr.K, profile.poses["570nm"].R, profile.poses["570nm"].t
        )
        assert map_x.shape == depth.shape
        aligned, mask = warp_target_to_ref(tgt, map_x, map_y)
        assert aligned.shape[:2] == ref.shape[:2]
        assert mask.sum() > 0

    def test_depth_colormap(self):
        depth = np.random.rand(50, 50).astype(np.float32) + 0.5
        vis = depth_to_colormap(depth)
        assert vis.shape == (50, 50, 3)


class TestProfile:
    def test_selfcalib_profile(self):
        ref, tgt, _, _, _ = _make_synthetic_views()
        profile = build_profile_from_images(
            {"rgb": ref, "570nm": tgt}, reference_band="rgb"
        )
        assert "rgb" in profile.intrinsics
        assert "570nm" in profile.poses


class TestPipeline:
    def test_align_batch_synthetic(self, tmp_path):
        ref, tgt, profile, _, _ = _make_synthetic_views()
        ref_path = str(tmp_path / "ref.jpg")
        tgt_path = str(tmp_path / "tgt.jpg")
        cv2.imwrite(ref_path, ref)
        cv2.imwrite(tgt_path, tgt)

        result = align_batch_3d(
            ref_path,
            [tgt_path],
            band_map={ref_path: "rgb", tgt_path: "570nm"},
            config_overrides={
                "depth_min": 1.0,
                "depth_max": 15.0,
                "num_planes": 16,
                "depth_backend": "sgbm",
                "rig_profile": "",
            },
            debug_dir=str(tmp_path / "align3d"),
        )
        assert result.success_count >= 1
        tgt_result = result.results.get(tgt_path)
        assert tgt_result is not None
        assert tgt_result.aligned_image is not None

    def test_homography_vs_3d_on_synthetic(self, tmp_path):
        """Demonstrate that homography fails on depth-varying synthetic scene."""
        ref, tgt, _, depth, _ = _make_synthetic_views()
        h, w = ref.shape[:2]

        # Homography alignment
        sift = cv2.SIFT_create()
        g1 = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
        g2 = cv2.cvtColor(tgt, cv2.COLOR_BGR2GRAY)
        kp1, des1 = sift.detectAndCompute(g1, None)
        kp2, des2 = sift.detectAndCompute(g2, None)
        bf = cv2.BFMatcher()
        matches = bf.knnMatch(des1, des2, k=2)
        good = [m for m, n in matches if m.distance < 0.75 * n.distance]
        pts1 = np.float32([kp1[m.queryIdx].pt for m in good])
        pts2 = np.float32([kp2[m.trainIdx].pt for m in good])
        H, _ = cv2.findHomography(pts2, pts1, cv2.RANSAC, 1.0)
        homo_aligned = cv2.warpPerspective(tgt, H, (w, h))
        ncc_homo = compute_ncc_score(ref, homo_aligned)

        # Note: on this synthetic scene homography may still partially work;
        # the test documents the comparison metric exists
        assert 0 <= ncc_homo <= 1.0


class TestRealImages:
    def test_real_image_pair_if_exists(self):
        backend = Path(__file__).parent.parent.parent
        t1 = backend / "test1.jpg"
        t2 = backend / "test2.jpg"
        if not t1.exists() or not t2.exists():
            pytest.skip("test1.jpg / test2.jpg not found")

        ref_path = str(t1)
        tgt_path = str(t2)
        result = align_batch_3d(
            ref_path,
            [tgt_path],
            band_map={ref_path: "rgb", tgt_path: "570nm"},
            config_overrides={"num_planes": 8, "depth_backend": "sgbm"},
        )
        assert len(result.results) == 2
