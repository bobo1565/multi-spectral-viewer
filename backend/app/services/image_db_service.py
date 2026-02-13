from sqlalchemy.orm import Session
from .. import db_models
from ..api.models import ImageUploadResponse
from typing import List, Optional
from datetime import datetime

class ImageDBService:
    @staticmethod
    def get_image(db: Session, image_id: str):
        return db.query(db_models.Image).filter(db_models.Image.id == image_id).first()

    @staticmethod
    def get_all_images(db: Session):
        return db.query(db_models.Image).order_by(db_models.Image.upload_time.desc()).all()

    @staticmethod
    def create_image(db: Session, image_data: dict) -> db_models.Image:
        db_image = db_models.Image(
            id=image_data["id"],
            batch_id=image_data.get("batch_id"),  # 批次ID
            band_type=image_data.get("band_type"),  # 波段类型
            image_type=image_data.get("image_type", "source"),  # 图像类型：source 或 aligned
            filename=image_data["filename"], # 原始文件名
            filepath=image_data["filepath"],
            file_size=image_data["size"],
            width=image_data["width"],
            height=image_data["height"],
            channels=image_data["channels"],
            upload_time=image_data.get("upload_time", datetime.utcnow())
        )
        db.add(db_image)
        db.commit()
        db.refresh(db_image)
        return db_image

    @staticmethod
    def delete_image(db: Session, image_id: str):
        db_image = db.query(db_models.Image).filter(db_models.Image.id == image_id).first()
        if db_image:
            db.delete(db_image)
            db.commit()
            return True
        return False
        
    @staticmethod
    def exists(db: Session, image_id: str) -> bool:
        return db.query(db_models.Image).filter(db_models.Image.id == image_id).first() is not None
