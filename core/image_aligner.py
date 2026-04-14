"""
图像对齐器模块
封装特征匹配对齐算法，提供简洁的API
"""
import os
import cv2
import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal


def get_roi_from_config(img_width, img_height, roi_config):
    """根据配置计算ROI区域"""
    roi_x = int(img_width * roi_config['roi_x_ratio'])
    roi_y = int(img_height * roi_config['roi_y_ratio'])
    roi_w = int(img_width * roi_config['roi_width_ratio'])
    roi_h = int(img_height * roi_config['roi_height_ratio'])
    
    # 确保ROI不超出图像边界
    roi_x = max(0, min(roi_x, img_width - 1))
    roi_y = max(0, min(roi_y, img_height - 1))
    roi_w = max(1, min(roi_w, img_width - roi_x))
    roi_h = max(1, min(roi_h, img_height - roi_y))
    
    return roi_x, roi_y, roi_w, roi_h


def align_images(img1_color, img2_color, roi_config1=None, roi_config2=None,
                 feature_detector_type='SIFT',
                 ratio_test_thresh=0.75, min_match_count=10):
    """
    使用特征点匹配对齐两张图像
    
    Args:
        img1_color: 参考图像 (BGR格式)
        img2_color: 待对齐图像 (BGR格式)
        roi_config1, roi_config2: ROI配置
        feature_detector_type: 'SIFT' 或 'ORB'
        ratio_test_thresh: 匹配阈值
        min_match_count: 最小匹配点数
        
    Returns:
        对齐后的图像，失败返回None
    """
    h1, w1 = img1_color.shape[:2]
    h2, w2 = img2_color.shape[:2]
    
    # 直接使用传入的ROI配置
    if not roi_config1 or not roi_config2:
        raise ValueError("必须提供有效的ROI配置")
    
    # 根据配置计算ROI区域
    roi_x1, roi_y1, roi_w1, roi_h1 = get_roi_from_config(w1, h1, roi_config1)
    roi_x2, roi_y2, roi_w2, roi_h2 = get_roi_from_config(w2, h2, roi_config2)
    
    mask1 = np.zeros((h1, w1), dtype=np.uint8)
    mask1[roi_y1:roi_y1 + roi_h1, roi_x1:roi_x1 + roi_w1] = 255
    mask2 = np.zeros((h2, w2), dtype=np.uint8)
    mask2[roi_y2:roi_y2 + roi_h2, roi_x2:roi_x2 + roi_w2] = 255
    
    img1 = cv2.cvtColor(img1_color, cv2.COLOR_BGR2GRAY)
    img2 = cv2.cvtColor(img2_color, cv2.COLOR_BGR2GRAY)
    
    # 创建特征检测器
    detector = None
    try:
        if feature_detector_type == 'SIFT':
            if hasattr(cv2, 'SIFT_create'):
                detector = cv2.SIFT_create()
            else:
                raise AttributeError('OpenCV未编译SIFT')
        elif feature_detector_type == 'ORB':
            if hasattr(cv2, 'ORB_create'):
                detector = cv2.ORB_create(nfeatures=2000)
            else:
                raise AttributeError('OpenCV未编译ORB')
        else:
            raise ValueError(f"不支持的特征检测器: {feature_detector_type}")
    except Exception as e:
        print(f"特征检测器创建失败: {e}")
        return None
    
    kp1, des1 = detector.detectAndCompute(img1, mask1)
    kp2, des2 = detector.detectAndCompute(img2, mask2)
    
    if des1 is None or des2 is None or len(kp1) < min_match_count or len(kp2) < min_match_count:
        print("特征点不足，无法进行匹配。")
        return None
    
    if feature_detector_type == 'SIFT':
        bf = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
    else:
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    
    matches = bf.knnMatch(des1, des2, k=2)
    good_matches = []
    for m, n in matches:
        if m.distance < ratio_test_thresh * n.distance:
            good_matches.append(m)
    
    if len(good_matches) < min_match_count:
        print(f"好的匹配点不足 ({len(good_matches)}/{min_match_count})，无法计算单应矩阵。")
        return None
    
    src_pts = np.array([kp1[m.queryIdx].pt for m in good_matches], dtype=np.float32).reshape(-1, 1, 2)
    dst_pts = np.array([kp2[m.trainIdx].pt for m in good_matches], dtype=np.float32).reshape(-1, 1, 2)
    H, _ = cv2.findHomography(dst_pts, src_pts, cv2.RANSAC, 2.0)
    
    if H is None:
        print("无法计算单应矩阵。")
        return None
    
    aligned_img2 = cv2.warpPerspective(img2_color, H, (w1, h1))
    return aligned_img2


class ImageAligner(QObject):
    """
    图像对齐器
    以参考图像为基准，将其他图像对齐到参考图像
    """
    
    # 信号
    alignment_progress = pyqtSignal(int, int)  # current, total
    alignment_completed = pyqtSignal(str, bool, str)  # path, success, message
    batch_completed = pyqtSignal(int, int)  # success_count, total_count
    
    # 默认ROI配置（全图）
    DEFAULT_ROI_CONFIG = {
        'roi_x_ratio': 0.0,
        'roi_y_ratio': 0.0,
        'roi_width_ratio': 1.0,
        'roi_height_ratio': 1.0
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._reference_image = None
        self._reference_path = None
        self._roi_config = self.DEFAULT_ROI_CONFIG.copy()
        self._feature_detector = 'SIFT'  # 或 'ORB'
        
        # 对齐结果缓存
        self._aligned_cache = {}  # path -> aligned_image
    
    @property
    def has_reference(self) -> bool:
        return self._reference_image is not None
    
    @property
    def reference_path(self) -> str:
        return self._reference_path
    
    def set_roi_config(self, config: dict):
        """设置ROI配置"""
        required_keys = ['roi_x_ratio', 'roi_y_ratio', 'roi_width_ratio', 'roi_height_ratio']
        if all(k in config for k in required_keys):
            self._roi_config = config.copy()
    
    def set_feature_detector(self, detector_type: str):
        """设置特征检测器类型 ('SIFT' 或 'ORB')"""
        if detector_type in ('SIFT', 'ORB'):
            self._feature_detector = detector_type
    
    def set_reference(self, image_path: str) -> bool:
        """
        设置参考图像
        
        Args:
            image_path: 参考图像路径
            
        Returns:
            是否设置成功
        """
        if not os.path.exists(image_path):
            return False
            
        img = cv2.imread(image_path)
        if img is None:
            return False
            
        self._reference_image = img
        self._reference_path = image_path
        self._aligned_cache.clear()
        
        return True
    
    def set_reference_from_array(self, image: np.ndarray, path: str = None):
        """从numpy数组设置参考图像"""
        self._reference_image = image.copy()
        self._reference_path = path
        self._aligned_cache.clear()
    
    def align_image(self, target_path: str) -> tuple:
        """
        对齐单张图像到参考图像
        
        Args:
            target_path: 目标图像路径
            
        Returns:
            (aligned_image, success, message) 元组
        """
        if not self.has_reference:
            return None, False, "未设置参考图像"
            
        if not os.path.exists(target_path):
            return None, False, f"文件不存在: {target_path}"
        
        # 检查缓存
        if target_path in self._aligned_cache:
            return self._aligned_cache[target_path], True, "从缓存加载"
        
        # 加载目标图像
        target_img = cv2.imread(target_path)
        if target_img is None:
            return None, False, "无法加载图像"
        
        # 如果是参考图像本身，直接返回
        if target_path == self._reference_path:
            return target_img, True, "参考图像无需对齐"
        
        try:
            # 调用对齐算法
            aligned = align_images(
                self._reference_image,
                target_img,
                roi_config1=self._roi_config,
                roi_config2=self._roi_config,
                feature_detector_type=self._feature_detector
            )
            
            if aligned is None:
                return None, False, "特征点匹配失败"
            
            # 缓存结果
            self._aligned_cache[target_path] = aligned
            
            return aligned, True, "对齐成功"
            
        except Exception as e:
            return None, False, f"对齐失败: {str(e)}"
    
    def align_batch(self, image_paths: list, save_results: bool = False, 
                    output_dir: str = None) -> dict:
        """
        批量对齐图像
        
        Args:
            image_paths: 图像路径列表
            save_results: 是否保存对齐结果
            output_dir: 输出目录（如果为None则覆盖原文件）
            
        Returns:
            结果字典 {path: (aligned_image, success, message)}
        """
        results = {}
        total = len(image_paths)
        success_count = 0
        
        for i, path in enumerate(image_paths):
            aligned, success, message = self.align_image(path)
            results[path] = (aligned, success, message)
            
            if success:
                success_count += 1
                
                # 保存结果
                if save_results and aligned is not None:
                    if output_dir:
                        os.makedirs(output_dir, exist_ok=True)
                        output_path = os.path.join(output_dir, os.path.basename(path))
                    else:
                        output_path = path
                    cv2.imwrite(output_path, aligned)
            
            # 发送进度信号
            self.alignment_progress.emit(i + 1, total)
            self.alignment_completed.emit(path, success, message)
        
        self.batch_completed.emit(success_count, total)
        
        return results
    
    def get_aligned_image(self, path: str) -> np.ndarray:
        """获取已缓存的对齐图像"""
        return self._aligned_cache.get(path)
    
    def clear_cache(self):
        """清除对齐缓存"""
        self._aligned_cache.clear()
    
    def align_multi_images(self, reference_path: str, target_paths: list, 
                           save_to_file: bool = False) -> dict:
        """
        多图像对齐：将多个目标图像对齐到参考图像
        
        Args:
            reference_path: 参考图像路径
            target_paths: 目标图像路径列表（最多4个）
            save_to_file: 是否保存对齐结果覆盖原文件
            
        Returns:
            结果字典 {path: (aligned_image, success, message)}
        """
        results = {}
        
        # 设置参考图像
        if not self.set_reference(reference_path):
            for path in target_paths:
                results[path] = (None, False, "无法加载参考图像")
            return results
        
        total = len(target_paths)
        success_count = 0
        
        for i, path in enumerate(target_paths):
            # 跳过参考图像本身
            if path == reference_path:
                results[path] = (self._reference_image, True, "参考图像无需对齐")
                success_count += 1
                self.alignment_progress.emit(i + 1, total)
                self.alignment_completed.emit(path, True, "参考图像")
                continue
            
            # 执行对齐
            aligned, success, message = self.align_image(path)
            results[path] = (aligned, success, message)
            
            if success:
                success_count += 1
                
                # 保存结果（覆盖原文件）
                if save_to_file and aligned is not None:
                    try:
                        cv2.imwrite(path, aligned)
                        results[path] = (aligned, True, "对齐成功并已保存")
                    except Exception as e:
                        results[path] = (aligned, True, f"对齐成功但保存失败: {str(e)}")
            
            # 发送进度信号
            self.alignment_progress.emit(i + 1, total)
            self.alignment_completed.emit(path, success, message)
        
        self.batch_completed.emit(success_count, total)
        
        return results
