"""
文件存储管理器
"""
import os
import uuid
import shutil
from pathlib import Path
from typing import Optional
import cv2
import numpy as np
from datetime import datetime


class FileManager:
    
    def __init__(self, upload_dir: str = None):
        if upload_dir is None:
            PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
            upload_dir = str(PROJECT_ROOT / "uploads")
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建子目录
        self.original_dir = self.upload_dir / "original"
        self.processed_dir = self.upload_dir / "processed"
        self.temp_dir = self.upload_dir / "temp"
        
        self.original_dir.mkdir(exist_ok=True)
        self.processed_dir.mkdir(exist_ok=True)
        self.temp_dir.mkdir(exist_ok=True)
    
    def save_uploaded_file(self, file_content: bytes, filename: str) -> dict:
        """
        保存上传的文件
        
        Returns:
            文件信息字典
        """
        # 生成唯一ID
        file_id = str(uuid.uuid4())
        # 简单的文件名清理，防止路径遍历或非法字符
        safe_filename =  os.path.basename(filename).replace(" ", "_")
        
        # 新格式: UUID_原始文件名
        new_filename = f"{file_id}_{safe_filename}"
        
        # 保存到original目录
        filepath = self.original_dir / new_filename
        with open(filepath, "wb") as f:
            f.write(file_content)
        
        # 读取图像信息
        img = cv2.imread(str(filepath))
        if img is None:
            # 如果无法读取，删除文件并抛出异常
            filepath.unlink()
            raise ValueError(f"无法读取图像文件: {filename}")
        
        height, width = img.shape[:2]
        channels = img.shape[2] if len(img.shape) == 3 else 1
        size = filepath.stat().st_size
        
        return {
            "id": file_id,
            "filename": safe_filename, # 返回原始文件名
            "filepath": str(filepath),
            "size": size,
            "width": width,
            "height": height,
            "channels": channels,
            "upload_time": datetime.now()
        }
    
    def get_file_path(self, file_id: str, subdir: str = "original") -> Optional[Path]:
        """获取文件路径"""
        target_dir = self.upload_dir / subdir
        
        # 查找匹配的文件: UUID_*.ext
        for file in target_dir.glob(f"{file_id}_*"):
            return file
            
        # 兼容旧格式: UUID.ext
        for file in target_dir.glob(f"{file_id}.*"):
            return file
            
        return None
    
    def delete_file(self, file_id: str) -> bool:
        """删除文件（包括所有相关文件）"""
        deleted = False
        
        # 删除original
        original_file = self.get_file_path(file_id, "original")
        if original_file and original_file.exists():
            original_file.unlink()
            deleted = True
        
        # 删除processed中的相关文件
        for file in self.processed_dir.glob(f"{file_id}_*"):
            file.unlink()
        
        return deleted
    
    def save_processed_image(self, file_id: str, img: np.ndarray, suffix: str = "processed") -> str:
        """
        保存处理后的图像
        
        Args:
            file_id: 原始文件ID
            img: 处理后的图像数组
            suffix: 文件名后缀
            
        Returns:
            保存后的文件路径
        """
        filename = f"{file_id}_{suffix}_{uuid.uuid4().hex[:8]}.png"
        filepath = self.processed_dir / filename
        
        cv2.imwrite(str(filepath), img)
        return str(filepath)
    
    def list_files(self) -> list:
        """列出所有上传的原始文件"""
        files = []
        for file in self.original_dir.iterdir():
            if file.is_file():
                # 解析文件名 UUID_filename
                try:
                    parts = file.name.split('_', 1)
                    if len(parts) >= 2:
                        file_id = parts[0]
                        original_name = parts[1]
                    else:
                        # 格式不匹配，可能是旧文件或异常文件，跳过或尽力处理
                        file_id = file.stem
                        original_name = file.name
                        
                    stat = file.stat()
                    files.append({
                        "id": file_id,
                        "filename": original_name,
                        "filepath": str(file),
                        "size": stat.st_size,
                        "upload_time": datetime.fromtimestamp(stat.st_mtime)
                    })
                except Exception as e:
                    print(f"Error parsing file {file.name}: {e}")
                    continue
                    
        return files


# 全局实例
file_manager = FileManager()
