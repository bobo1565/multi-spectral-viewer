"""Rig profile persistence."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from align3d.config import get_calib_dir
from align3d.types import RigProfile


def _profile_path(name: str, upload_root: Optional[str] = None) -> Path:
    safe = name.replace("/", "_").replace("\\", "_")
    if not safe.startswith("rig_"):
        safe = f"rig_{safe}"
    if not safe.endswith(".json"):
        safe = f"{safe}.json"
    return get_calib_dir(upload_root) / safe


def save_profile(profile: RigProfile, upload_root: Optional[str] = None) -> str:
    path = _profile_path(profile.name, upload_root)
    path.write_text(profile.to_json(), encoding="utf-8")
    return str(path)


def load_profile(name: str, upload_root: Optional[str] = None) -> Optional[RigProfile]:
    path = _profile_path(name, upload_root)
    if not path.exists():
        # try without rig_ prefix
        alt = get_calib_dir(upload_root) / f"{name}.json"
        if alt.exists():
            path = alt
        else:
            return None
    return RigProfile.from_json(path.read_text(encoding="utf-8"))


def list_profiles(upload_root: Optional[str] = None) -> List[dict]:
    calib_dir = get_calib_dir(upload_root)
    profiles = []
    for p in sorted(calib_dir.glob("rig_*.json")):
        try:
            prof = RigProfile.from_json(p.read_text(encoding="utf-8"))
            profiles.append(
                {
                    "name": prof.name,
                    "reference_band": prof.reference_band,
                    "calibration_method": prof.calibration_method,
                    "created_at": prof.created_at,
                    "bands": list(prof.intrinsics.keys()),
                    "path": str(p),
                }
            )
        except Exception as exc:
            profiles.append({"name": p.stem, "error": str(exc), "path": str(p)})
    return profiles


def delete_profile(name: str, upload_root: Optional[str] = None) -> bool:
    path = _profile_path(name, upload_root)
    if path.exists():
        path.unlink()
        return True
    return False
