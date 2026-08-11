"""
波段辐射补偿配置
一级相对辐射补偿系数（基于 IMX290C 响应曲线 + FWHM 带宽）。
运行时可通过 API 修改，持久化到 uploads/data/band_correction.json。
"""
from __future__ import annotations

import json
import os
import threading
from typing import Dict

from app.database import DATA_DIR

CONFIG_PATH = os.path.join(DATA_DIR, "band_correction.json")

# 默认补偿系数，键为中心波长 nm
DEFAULT_BAND_CORRECTION: Dict[int, float] = {
    560: 1.0173,
    650: 1.0000,
    730: 1.1172,
    850: 0.6215,
}

_lock = threading.Lock()
_cache: Dict[int, float] | None = None


def _load() -> Dict[int, float]:
    """加载补偿系数（带进程内缓存），文件缺失或损坏时回退默认值"""
    global _cache
    if _cache is not None:
        return _cache
    corrections = dict(DEFAULT_BAND_CORRECTION)
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for key, value in saved.items():
                wl = int(key)
                if wl in corrections:
                    corrections[wl] = float(value)
    except Exception as e:
        print(f"[Radiometric] 读取补偿配置失败，使用默认值: {e}")
    _cache = corrections
    return _cache


def get_band_correction() -> Dict[int, float]:
    """获取当前补偿系数 {波长nm: 系数}"""
    with _lock:
        return dict(_load())


def update_band_correction(updates: Dict) -> Dict[int, float]:
    """更新并持久化补偿系数。updates: {波长nm(int或str): 系数}，允许部分更新。"""
    cleaned: Dict[int, float] = {}
    for key, value in (updates or {}).items():
        try:
            wl = int(key)
            coef = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"非法的补偿配置项: {key}={value}")
        if wl not in DEFAULT_BAND_CORRECTION:
            raise ValueError(f"未知波段波长: {wl}nm（支持: {sorted(DEFAULT_BAND_CORRECTION)}）")
        if not (0.0 < coef <= 100.0):
            raise ValueError(f"补偿系数需在 (0, 100] 区间: {wl}nm={coef}")
        cleaned[wl] = coef
    if not cleaned:
        raise ValueError("没有可更新的补偿系数")

    with _lock:
        current = _load()
        current.update(cleaned)
        tmp_path = CONFIG_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({str(k): current[k] for k in sorted(current)}, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CONFIG_PATH)
        print(f"[Radiometric] 波段补偿系数已更新: {cleaned}")
        return dict(current)
