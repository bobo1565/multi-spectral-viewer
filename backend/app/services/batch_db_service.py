"""
批次数据库服务
"""
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import uuid

from .. import db_models
from ..api.models import BAND_TYPES


class BatchDBService:
    @staticmethod
    def create_batch(db: Session, name: str) -> db_models.Batch:
        """创建新批次"""
        batch = db_models.Batch(
            id=str(uuid.uuid4()),
            name=name,
            created_at=datetime.utcnow()
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)
        return batch

    @staticmethod
    def get_batch(db: Session, batch_id: str) -> Optional[db_models.Batch]:
        """获取单个批次"""
        return db.query(db_models.Batch).filter(db_models.Batch.id == batch_id).first()

    @staticmethod
    def get_all_batches(db: Session) -> List[db_models.Batch]:
        """获取所有批次"""
        return db.query(db_models.Batch).order_by(db_models.Batch.created_at.desc()).all()

    @staticmethod
    def delete_batch(db: Session, batch_id: str) -> bool:
        """删除批次（级联删除关联图像）"""
        batch = db.query(db_models.Batch).filter(db_models.Batch.id == batch_id).first()
        if batch:
            db.delete(batch)
            db.commit()
            return True
        return False

    @staticmethod
    def add_image_to_batch(db: Session, batch_id: str, image_id: str, band_type: str) -> bool:
        """将图像添加到批次"""
        if band_type not in BAND_TYPES:
            return False
        
        image = db.query(db_models.Image).filter(db_models.Image.id == image_id).first()
        if image:
            image.batch_id = batch_id
            image.band_type = band_type
            db.commit()
            return True
        return False

    @staticmethod
    def get_batch_images(db: Session, batch_id: str) -> dict:
        """获取批次中的所有图像，按波段类型组织，优先返回 source 类型"""
        images = db.query(db_models.Image).filter(db_models.Image.batch_id == batch_id).all()
        result = {band: None for band in BAND_TYPES}
        
        # 首先添加 aligned 图像
        for img in images:
            if img.band_type in BAND_TYPES:
                img_type = getattr(img, 'image_type', None) or 'source'
                if img_type == 'aligned':
                    result[img.band_type] = img
        
        # 然后用 source 图像覆盖（优先级高）
        for img in images:
            if img.band_type in BAND_TYPES:
                img_type = getattr(img, 'image_type', None) or 'source'
                if img_type == 'source':
                    result[img.band_type] = img
        
        return result

    @staticmethod
    def get_all_batch_images_list(db: Session, batch_id: str) -> List[db_models.Image]:
        """获取批次中的所有图像列表（不按波段聚合）"""
        return db.query(db_models.Image).filter(db_models.Image.batch_id == batch_id).all()
