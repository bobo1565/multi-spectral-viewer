"""
图像对齐服务包装器
严格使用 core/feature_matching_algo.py 中的算法

配置文件 matching.json 支持动态热加载：
- 每次 align_batch 调用时从磁盘重新读取
- 前端可通过 API 修改配置后立刻生效，无需重启服务
"""
import os
import cv2
import json
import numpy as np
import uuid
from pathlib import Path

from app.core.feature_matching_algo import (
    align_images, 
    find_valid_region, 
    calculate_common_region, 
    crop_image
)

# 配置文件路径（模块级常量，供 API 层也能访问）
ROI_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'matching.json')

# 默认 ROI（当配置文件不存在时的兜底值）
DEFAULT_ROI = {
    "roi_x_ratio": 0.25,
    "roi_y_ratio": 0.25,
    "roi_width_ratio": 0.5,
    "roi_height_ratio": 0.5
}


def load_roi_config() -> dict:
    """
    从磁盘动态加载 ROI 配置。
    每次调用都重新读取文件，确保前端修改后立即生效。
    """
    if os.path.exists(ROI_CONFIG_PATH):
        try:
            with open(ROI_CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # 只提取需要的 4 个字段
            return {
                "roi_x_ratio": float(config.get("roi_x_ratio", DEFAULT_ROI["roi_x_ratio"])),
                "roi_y_ratio": float(config.get("roi_y_ratio", DEFAULT_ROI["roi_y_ratio"])),
                "roi_width_ratio": float(config.get("roi_width_ratio", DEFAULT_ROI["roi_width_ratio"])),
                "roi_height_ratio": float(config.get("roi_height_ratio", DEFAULT_ROI["roi_height_ratio"])),
            }
        except Exception as e:
            print(f"[AlignService] Error loading ROI config: {e}")
    return DEFAULT_ROI.copy()


def save_roi_config(roi: dict) -> None:
    """
    将 ROI 配置写入磁盘。
    """
    data = {
        "roi_x_ratio": roi["roi_x_ratio"],
        "roi_y_ratio": roi["roi_y_ratio"],
        "roi_width_ratio": roi["roi_width_ratio"],
        "roi_height_ratio": roi["roi_height_ratio"],
        "description": "默认ROI配置 - 可通过前端动态修改"
    }
    with open(ROI_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[AlignService] ROI config saved: {data}")


class ImageAlignerService:
    def __init__(self, upload_dir: str = None):
        if upload_dir is None:
            PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
            upload_dir = str(PROJECT_ROOT / "uploads")
        self._feature_detector = 'SIFT'
        self._upload_dir = Path(upload_dir)
        self._original_dir = self._upload_dir / "original"

    def set_feature_detector(self, detector_type: str):
        print(f"[AlignService] Setting detector to: {detector_type}")
        if detector_type in ('SIFT', 'ORB'):
            self._feature_detector = detector_type

    def align_batch(self, reference_path: str, target_paths: list, output_dir: str, 
                           overwrite: bool = True, custom_roi: dict = None) -> dict:
        """
        执行批量对齐，并将结果保存到指定目录
        
        ROI 优先级：custom_roi（前端手动绘制） > matching.json（默认配置）
        每次调用都重新加载 matching.json，确保配置热更新生效。
        """
        # 动态加载配置（每次调用都读磁盘）
        default_roi = load_roi_config()
        applied_roi = custom_roi if custom_roi else default_roi
        
        print(f"[AlignService] Starting batch align. Reference: {reference_path}")
        print(f"[AlignService] Targets: {target_paths}, Output: {output_dir}")
        print(f"[AlignService] Active ROI: {applied_roi} ({'custom' if custom_roi else 'default from matching.json'})")
        
        results = {}
        
        # 1. 加载参考图像
        try:
            ref_img = cv2.imread(reference_path)
            if ref_img is None:
                return {p: (False, f"无法加载参考图: {reference_path}", None) for p in target_paths}
        except Exception as e:
            return {p: (False, f"加载参考图异常: {str(e)}", None) for p in target_paths}

        aligned_images_map = {reference_path: ref_img}
        process_paths = [reference_path]
        
        # 2. 对齐目标图像
        for path in target_paths:
            if os.path.abspath(path) == os.path.abspath(reference_path):
                continue
                
            try:
                tgt_img = cv2.imread(path)
                if tgt_img is None:
                    results[path] = (False, f"无法加载目标图: {path}", None)
                    continue
                
                aligned = align_images(
                    ref_img, 
                    tgt_img, 
                    roi_config1=applied_roi, 
                    roi_config2=applied_roi,
                    feature_detector_type=self._feature_detector
                )
                
                if aligned is not None:
                    aligned_images_map[path] = aligned
                    process_paths.append(path)
                else:
                    results[path] = (False, "对齐失败：特征匹配不足", None)
            except Exception as e:
                print(f"[AlignService] Exception aligning {path}: {e}")
                results[path] = (False, f"对齐异常: {str(e)}", None)

        if len(aligned_images_map) <= 1:
            return results

        # 3. 保存对齐结果（不裁剪，保持与参考图大小一致）
        for path in process_paths:
            img = aligned_images_map[path]
            
            original_filename = Path(path).name
            if '_' in original_filename:
                parts = original_filename.split('_', 1)
                if len(parts[0]) > 30 and '-' in parts[0]:
                    original_filename = parts[1]
            
            stem = Path(original_filename).stem
            suffix = Path(original_filename).suffix
            new_filename = f"{stem}_aligned{suffix}"
            
            output_path = Path(output_dir) / new_filename
            
            if not overwrite and output_path.exists():
                counter = 1
                while output_path.exists():
                    new_filename = f"{stem}_aligned_{counter}{suffix}"
                    output_path = Path(output_dir) / new_filename
                    counter += 1

            try:
                cv2.imwrite(str(output_path), img)
                
                height, width = img.shape[:2]
                channels = img.shape[2] if len(img.shape) == 3 else 1
                size = os.path.getsize(str(output_path))
                
                new_id = str(uuid.uuid4())
                
                new_file_info = {
                    "id": new_id,
                    "filename": output_path.name,
                    "filepath": str(output_path),
                    "size": size,
                    "width": width,
                    "height": height,
                    "channels": channels
                }
                
                if path == reference_path:
                    results[path] = (True, "参考图直接保存", new_file_info)
                else:
                    results[path] = (True, "对齐保存成功", new_file_info)

            except Exception as e:
                results[path] = (False, f"保存失败: {str(e)}", None)

        # 补全失败的情况
        for path in target_paths:
            if path not in results:
                results[path] = (False, "处理失败", None)

        return results
