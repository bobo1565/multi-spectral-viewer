"""
图像对齐服务包装器
严格使用 core/feature_matching_algo.py (即原 core/feature_matching_api.py) 中的算法
"""
import os
import cv2
import json
import numpy as np
import uuid
from pathlib import Path

# 直接从算法文件导入，确保算法一致性
from app.core.feature_matching_algo import (
    align_images, 
    find_valid_region, 
    calculate_common_region, 
    crop_image
)

class ImageAlignerService:
    def __init__(self, upload_dir: str = None):
        if upload_dir is None:
            PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
            upload_dir = str(PROJECT_ROOT / "uploads")
        self._roi_config = self._load_default_roi()
        self._feature_detector = 'SIFT'
        self._upload_dir = Path(upload_dir)
        self._original_dir = self._upload_dir / "original"
        
    def _load_default_roi(self):
        # 优先从 backend/app/core/matching.json 加载 (这是从 root core/ 拷贝过来的)
        path = os.path.join(os.path.dirname(__file__), 'matching.json')
        print(f"[AlignService] Loading ROI config from: {path}")
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    print(f"[AlignService] ROI config loaded: {config}")
                    return config
            except Exception as e:
                print(f"[AlignService] Error loading ROI config: {e}")
        # Fallback
        return {
            "roi_x_ratio": 0.2652,
            "roi_y_ratio": 0,
            "roi_width_ratio": 0.479,
            "roi_height_ratio": 1
        }

    def set_feature_detector(self, detector_type: str):
        print(f"[AlignService] Setting detector to: {detector_type}")
        if detector_type in ('SIFT', 'ORB'):
            self._feature_detector = detector_type

    def _generate_aligned_filename(self, original_path: str) -> tuple:
        """
        根据原始文件路径生成对齐后的新文件名
        返回: (new_file_id, new_filepath)
        """
        original_path = Path(original_path)
        original_name = original_path.name
        
        # 解析原始文件名: UUID_filename.ext
        parts = original_name.split('_', 1)
        if len(parts) >= 2:
            original_filename = parts[1]
        else:
            original_filename = original_name
        
        # 解析文件名和扩展名
        name_without_ext = Path(original_filename).stem
        ext = Path(original_filename).suffix
        
        # 生成新文件名: 原名_aligned.ext
        new_file_id = str(uuid.uuid4())
        aligned_filename = f"{name_without_ext}_aligned{ext}"
        new_full_filename = f"{new_file_id}_{aligned_filename}"
        new_filepath = self._original_dir / new_full_filename
        
        return new_file_id, str(new_filepath), aligned_filename

    def align_batch(self, reference_path: str, target_paths: list, output_dir: str, 
                           overwrite: bool = True, custom_roi: dict = None) -> dict:
        """
        执行批量对齐，并将结果保存到指定目录
        
        Args:
            reference_path: 参考图像路径
            target_paths: 目标图像路径列表
            output_dir: 输出目录 (aligned/)
            overwrite: 是否覆盖输出目录中已存在的文件
            custom_roi: 手动指定的ROI配置，形如 {"roi_x_ratio":...}
            
        Returns:
            dict: {original_path: (success, message, new_file_info)}
        """
        print(f"[AlignService] Starting batch align. Reference: {reference_path}")
        print(f"[AlignService] Targets: {target_paths}, Output: {output_dir}")
        
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
                
                applied_roi = custom_roi if custom_roi else self._roi_config
                
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

        # 3. 检测有效区域 & 4. 计算公共区域
        valid_regions = []
        for path in process_paths:
            img = aligned_images_map[path]
            region = find_valid_region(img)
            valid_regions.append(region)
            
        common_region = calculate_common_region(valid_regions)
        
        # 5. 剪裁并保存
        if common_region:
            for path in process_paths:
                # 即使是参考图，也需要剪裁并保存到 aligned 目录
                img = aligned_images_map[path]
                cropped = crop_image(img, common_region)
                
                # 生成新文件名：原文件名_aligned.jpg
                # 从原文件名中移除UUID前缀（如果存在）
                original_filename = Path(path).name
                
                # 检查文件名是否以UUID开头（格式：UUID_xxx.jpg）
                # 如果是，提取真实的文件名部分
                if '_' in original_filename:
                    parts = original_filename.split('_', 1)
                    # 检查第一部分是否看起来像UUID（长度约36字符，包含-）
                    if len(parts[0]) > 30 and '-' in parts[0]:
                        original_filename = parts[1]  # 使用UUID后面的部分
                
                stem = Path(original_filename).stem
                suffix = Path(original_filename).suffix
                new_filename = f"{stem}_aligned{suffix}"
                
                output_path = Path(output_dir) / new_filename
                
                # 如果文件已存在且不覆盖，添加编号
                if not overwrite and output_path.exists():
                    counter = 1
                    while output_path.exists():
                        new_filename = f"{stem}_aligned_{counter}{suffix}"
                        output_path = Path(output_dir) / new_filename
                        counter += 1

                try:
                    cv2.imwrite(str(output_path), cropped)
                    
                    # 生成文件信息
                    height, width = cropped.shape[:2]
                    channels = cropped.shape[2] if len(cropped.shape) == 3 else 1
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
                        results[path] = (True, "参考图剪裁成功", new_file_info)
                    else:
                        results[path] = (True, "对齐并剪裁成功", new_file_info)

                except Exception as e:
                    results[path] = (False, f"保存失败: {str(e)}", None)
        else:
            for path in process_paths:
                if path != reference_path:
                    results[path] = (False, "无法找到公共有效区域", None)

        # 补全失败的情况
        for path in target_paths:
            if path not in results:
                results[path] = (False, "处理失败", None)

        return results
