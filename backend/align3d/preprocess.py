"""Cross-spectral preprocessing for robust matching."""
from __future__ import annotations

import cv2
import numpy as np


def to_gray(img: np.ndarray) -> np.ndarray:
    if len(img.shape) == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def apply_clahe(gray: np.ndarray, clip_limit: float = 3.0, tile_size: int = 8) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_size, tile_size))
    return clahe.apply(gray)


def gradient_magnitude(gray: np.ndarray) -> np.ndarray:
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    mag = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return mag


def census_transform(gray: np.ndarray, window_size: int = 5) -> np.ndarray:
    """Compute census transform (bit pattern per pixel)."""
    h, w = gray.shape
    half = window_size // 2
    padded = cv2.copyMakeBorder(gray, half, half, half, half, cv2.BORDER_REFLECT)
    census = np.zeros((h, w), dtype=np.uint32)
    center = padded[half : half + h, half : half + w]

    idx = 0
    for dy in range(-half, half + 1):
        for dx in range(-half, half + 1):
            if dy == 0 and dx == 0:
                continue
            neighbor = padded[half + dy : half + dy + h, half + dx : half + dx + w]
            bit = (neighbor >= center).astype(np.uint32)
            census |= bit << idx
            idx += 1
    return census


def preprocess_for_matching(img: np.ndarray, mode: str = "clahe") -> np.ndarray:
    """
    Preprocess image for cross-spectral matching.

    mode: clahe | gradient | census | combined
    """
    gray = to_gray(img)
    if mode == "clahe":
        return apply_clahe(gray)
    if mode == "gradient":
        return gradient_magnitude(apply_clahe(gray))
    if mode == "census":
        return census_transform(apply_clahe(gray)).astype(np.uint8)
    if mode == "combined":
        clahe = apply_clahe(gray)
        grad = gradient_magnitude(clahe)
        return cv2.addWeighted(clahe, 0.5, grad, 0.5, 0)
    return apply_clahe(gray)


def census_hamming_cost(a: np.ndarray, b: np.ndarray, window: int = 5) -> np.ndarray:
    """Hamming distance between two census images."""
    if a.dtype != np.uint32:
        a = census_transform(to_gray(a) if len(a.shape) == 3 else a)
    if b.dtype != np.uint32:
        b = census_transform(to_gray(b) if len(b.shape) == 3 else b)
    xor = np.bitwise_xor(a.astype(np.uint64), b.astype(np.uint64))
    # popcount approximation via lookup for small windows
    bits = np.zeros_like(xor, dtype=np.float32)
    for i in range(32):
        bits += ((xor >> i) & 1).astype(np.float32)
    return bits


def zncc_cost(a: np.ndarray, b: np.ndarray, window: int = 7) -> np.ndarray:
    """Zero-mean normalized cross-correlation cost (1 - NCC)."""
    a_f = a.astype(np.float32)
    b_f = b.astype(np.float32)
    if len(a_f.shape) == 3:
        a_f = to_gray(a).astype(np.float32)
    if len(b_f.shape) == 3:
        b_f = to_gray(b).astype(np.float32)
    mean_a = cv2.boxFilter(a_f, -1, (window, window))
    mean_b = cv2.boxFilter(b_f, -1, (window, window))
    sq_a = cv2.boxFilter(a_f * a_f, -1, (window, window))
    sq_b = cv2.boxFilter(b_f * b_f, -1, (window, window))
    cross = cv2.boxFilter(a_f * b_f, -1, (window, window))
    var_a = sq_a - mean_a * mean_a
    var_b = sq_b - mean_b * mean_b
    cov = cross - mean_a * mean_b
    denom = np.sqrt(np.maximum(var_a * var_b, 1e-6))
    ncc = cov / denom
    return (1.0 - np.clip(ncc, -1, 1)).astype(np.float32)


def compute_ncc_score(img1: np.ndarray, img2: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Mean NCC score between two aligned images (higher is better)."""
    g1 = preprocess_for_matching(img1, "clahe").astype(np.float32)
    g2 = preprocess_for_matching(img2, "clahe").astype(np.float32)
    if g1.shape != g2.shape:
        g2 = cv2.resize(g2, (g1.shape[1], g1.shape[0]))
    if mask is not None:
        valid = mask > 0
        if valid.sum() < 100:
            return 0.0
        g1, g2 = g1[valid], g2[valid]
    else:
        g1, g2 = g1.ravel(), g2.ravel()
    g1 = (g1 - g1.mean()) / (g1.std() + 1e-6)
    g2 = (g2 - g2.mean()) / (g2.std() + 1e-6)
    return float(np.mean(g1 * g2))
