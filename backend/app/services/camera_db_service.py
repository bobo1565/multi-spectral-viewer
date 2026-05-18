"""
摄像头数据库服务
- CRUD 封装
- 一次性从 cameras_db.json 迁移到 SQLite Camera 表
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .. import db_models
from ..api.models import BAND_TYPES

DEFAULT_CAMERA_SEEDS = [
    {
        "name": "ONVIF_Camera_111",
        "ip": "192.168.40.111",
        "stream_url": "rtsp://admin:admin@192.168.40.111:554/Streaming/Channels/101",
        "username": "admin",
        "password": "admin",
        "camera_type": "ONVIF",
        "band_type": "rgb",
    },
    {
        "name": "ONVIF_Camera_112",
        "ip": "192.168.40.112",
        "stream_url": "rtsp://admin:admin@192.168.40.112:554/Streaming/Channels/101",
        "username": "admin",
        "password": "admin",
        "camera_type": "ONVIF",
        "band_type": "570nm",
    },
    {
        "name": "ONVIF_Camera_114",
        "ip": "192.168.40.114",
        "stream_url": "rtsp://admin:admin@192.168.40.114:554/Streaming/Channels/101",
        "username": "admin",
        "password": "admin",
        "camera_type": "ONVIF",
        "band_type": "650nm",
    },
    {
        "name": "ONVIF_Camera_113",
        "ip": "192.168.40.113",
        "stream_url": "rtsp://admin:admin@192.168.40.113:554/Streaming/Channels/101",
        "username": "admin",
        "password": "admin",
        "camera_type": "ONVIF",
        "band_type": "730nm",
    },
    {
        "name": "ONVIF_Camera_115",
        "ip": "192.168.40.115",
        "stream_url": "rtsp://admin:admin@192.168.40.115:554/Streaming/Channels/101",
        "username": "admin",
        "password": "admin",
        "camera_type": "ONVIF",
        "band_type": "850nm",
    },
]

DEFAULT_CAMERA_SEEDS_BY_IP = {seed["ip"]: seed for seed in DEFAULT_CAMERA_SEEDS}


class CameraDBService:
    @staticmethod
    def list_cameras(db: Session) -> List[db_models.Camera]:
        return db.query(db_models.Camera).order_by(db_models.Camera.added_at.asc()).all()

    @staticmethod
    def get_camera(db: Session, cam_id: str) -> Optional[db_models.Camera]:
        return db.query(db_models.Camera).filter(db_models.Camera.id == cam_id).first()

    @staticmethod
    def find_camera_by_ip(db: Session, ip: Optional[str]) -> Optional[db_models.Camera]:
        if not ip:
            return None
        return db.query(db_models.Camera).filter(db_models.Camera.ip == ip).first()

    @staticmethod
    def default_camera_seed_for_ip(ip: Optional[str]) -> Optional[Dict]:
        if not ip:
            return None
        seed = DEFAULT_CAMERA_SEEDS_BY_IP.get(ip)
        return dict(seed) if seed else None

    @staticmethod
    def create_camera(db: Session, data: Dict) -> db_models.Camera:
        cam = db_models.Camera(
            id=data.get("id") or str(uuid.uuid4())[:8],
            name=data.get("name") or f"Camera {data.get('ip', '')}",
            ip=data.get("ip"),
            stream_url=data["stream_url"],
            username=data.get("username"),
            password=data.get("password"),
            camera_type=data.get("camera_type") or data.get("type"),
            band_type=data.get("band_type"),
            added_at=datetime.utcnow(),
        )
        db.add(cam)
        db.commit()
        db.refresh(cam)
        return cam

    @staticmethod
    def update_camera(db: Session, cam_id: str, data: Dict) -> Optional[db_models.Camera]:
        cam = CameraDBService.get_camera(db, cam_id)
        if not cam:
            return None
        for field in ("name", "ip", "stream_url", "username", "password", "camera_type", "band_type"):
            if field in data and data[field] is not None:
                setattr(cam, field, data[field])
        db.commit()
        db.refresh(cam)
        return cam

    @staticmethod
    def set_band(db: Session, cam_id: str, band_type: Optional[str]) -> Optional[db_models.Camera]:
        cam = CameraDBService.get_camera(db, cam_id)
        if not cam:
            return None
        # 允许清空 (None / "")
        if band_type in (None, ""):
            cam.band_type = None
        elif band_type in BAND_TYPES:
            cam.band_type = band_type
        else:
            return None
        db.commit()
        db.refresh(cam)
        return cam

    @staticmethod
    def delete_camera(db: Session, cam_id: str) -> bool:
        cam = CameraDBService.get_camera(db, cam_id)
        if not cam:
            return False
        db.delete(cam)
        db.commit()
        return True

    @staticmethod
    def replace_all(db: Session, cameras: List[Dict]) -> List[db_models.Camera]:
        """批量替换（扫描结果同步）"""
        db.execute(delete(db_models.Camera))
        db.commit()
        created = []
        for cam in cameras:
            if not cam.get("stream_url"):
                continue
            created.append(CameraDBService.create_camera(db, cam))
        return created

    @staticmethod
    def ensure_default_cameras(session_factory) -> Dict[str, int]:
        """
        确保默认 5 台摄像头存在于数据库中。
        - 缺失时自动创建
        - 已存在但缺少关键默认字段时补齐
        """
        db = session_factory()
        try:
            created = 0
            updated = 0

            for seed in DEFAULT_CAMERA_SEEDS:
                cam = CameraDBService.find_camera_by_ip(db, seed["ip"])
                if cam is None:
                    CameraDBService.create_camera(db, dict(seed))
                    created += 1
                    continue

                changed = False
                for field in ("name", "stream_url", "username", "password", "camera_type", "band_type"):
                    if not getattr(cam, field, None) and seed.get(field):
                        setattr(cam, field, seed[field])
                        changed = True

                if changed:
                    updated += 1

            if updated:
                db.commit()

            return {"created": created, "updated": updated}
        finally:
            db.close()

    # ---------- JSON → SQLite 一次性迁移 ----------

    @staticmethod
    def _candidate_json_paths() -> List[Path]:
        """找可能存在的 cameras_db.json"""
        here = Path(__file__).resolve()
        # .../image_viewer/backend/app/services/camera_db_service.py
        image_viewer_root = here.parents[3]
        repo_root = here.parents[4] if len(here.parents) > 4 else image_viewer_root
        return [
            Path("/app") / "cameras_db.json",  # docker
            Path.cwd() / "cameras_db.json",
            image_viewer_root / "cameras_db.json",
            repo_root / "ip_camera_viewer" / "cameras_db.json",
            repo_root / "cameras_db.json",
        ]

    @staticmethod
    def migrate_from_json(session_factory) -> int:
        """
        从 cameras_db.json 迁移到 Camera 表。仅在表为空时执行。
        session_factory: SessionLocal 工厂（避免外部 session 复用带来的副作用）
        返回迁移条目数量。
        """
        db = session_factory()
        try:
            # 已有数据则跳过
            if db.query(db_models.Camera).first() is not None:
                return 0

            json_path: Optional[Path] = None
            for p in CameraDBService._candidate_json_paths():
                if p.exists():
                    json_path = p
                    break

            if json_path is None:
                return 0

            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception as e:
                print(f"[CameraMigration] 读取 {json_path} 失败: {e}")
                return 0

            count = 0
            for cam_id, cam_data in (raw or {}).items():
                if not cam_data.get("stream_url"):
                    continue
                cam = db_models.Camera(
                    id=cam_id or str(uuid.uuid4())[:8],
                    name=cam_data.get("name") or f"Camera {cam_data.get('ip', '')}",
                    ip=cam_data.get("ip"),
                    stream_url=cam_data["stream_url"],
                    username=cam_data.get("username"),
                    password=cam_data.get("password"),
                    camera_type=cam_data.get("type"),
                    band_type=cam_data.get("band_type"),
                    added_at=_parse_added_time(cam_data.get("added_time")),
                )
                db.add(cam)
                count += 1

            db.commit()

            # 备份原 JSON（加 .migrated 后缀），避免重复迁移
            try:
                backup = json_path.with_suffix(json_path.suffix + ".migrated")
                if not backup.exists():
                    os.rename(json_path, backup)
            except Exception as e:
                print(f"[CameraMigration] 备份 {json_path} 失败: {e}")

            return count
        finally:
            db.close()


def _parse_added_time(value) -> datetime:
    if not value:
        return datetime.utcnow()
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.utcnow()
