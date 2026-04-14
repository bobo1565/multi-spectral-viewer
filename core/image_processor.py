"""
图像处理器模块
管理图像加载、通道分离、缓存和效果应用
"""
import os
import cv2
import numpy as np
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtCore import QObject, pyqtSignal

from .algorithms import (
    gray_world_white_balance,
    apply_white_balance,
    adjust_saturation,
    calculate_histogram,
    apply_channel_gains,
    auto_stretch_all_channels
)


class ImageProcessor(QObject):
    """图像处理器类，管理当前图像的加载和处理"""
    
    # 信号：当图像处理完成时发出
    image_updated = pyqtSignal()
    histogram_updated = pyqtSignal(dict)
    
    SUPPORTED_FORMATS = ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp')
    
    def __init__(self):
        super().__init__()
        self._original_image = None  # BGR格式原始图像
        self._current_path = None
        
        # 缓存的像素图
        self._cache = {
            'rgb': None,
            'r': None,
            'g': None,
            'b': None
        }
        
        # 当前调整参数
        self._wb_gains = (1.0, 1.0, 1.0)  # R, G, B
        self._saturation = 1.0
        
        # 通道增益调整 {channel: (gain, offset)}
        self._channel_gains = {
            'r': (1.0, 0),
            'g': (1.0, 0),
            'b': (1.0, 0)
        }
        
    @property
    def has_image(self) -> bool:
        return self._original_image is not None
    
    @property
    def image_size(self) -> tuple:
        if self._original_image is None:
            return (0, 0)
        h, w = self._original_image.shape[:2]
        return (w, h)
    
    def load_image(self, path: str) -> bool:
        """
        加载图像文件
        
        Args:
            path: 图像文件路径
            
        Returns:
            加载是否成功
        """
        if not os.path.exists(path):
            return False
            
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            return False
            
        self._original_image = img
        self._current_path = path
        
        # 重置调整参数
        self._wb_gains = (1.0, 1.0, 1.0)
        self._saturation = 1.0
        self._channel_gains = {
            'r': (1.0, 0),
            'g': (1.0, 0),
            'b': (1.0, 0)
        }
        
        # 更新缓存
        self._update_cache()
        
        return True
    
    def _update_cache(self):
        """更新所有通道的缓存"""
        if self._original_image is None:
            return
            
        # 应用当前调整
        processed = self._get_processed_image()
        
        # RGB 彩图
        self._cache['rgb'] = self._numpy_to_pixmap(processed)
        
        # 各通道灰度图
        self._cache['b'] = self._numpy_to_pixmap(processed[:, :, 0], grayscale=True)
        self._cache['g'] = self._numpy_to_pixmap(processed[:, :, 1], grayscale=True)
        self._cache['r'] = self._numpy_to_pixmap(processed[:, :, 2], grayscale=True)
        
        # 发送直方图更新信号
        hist_data = calculate_histogram(processed)
        self.histogram_updated.emit(hist_data)
        self.image_updated.emit()
    
    def _get_processed_image(self) -> np.ndarray:
        """获取应用了所有调整的图像"""
        if self._original_image is None:
            return None
            
        img = self._original_image.copy()
        
        # 应用通道增益调整
        if any(g != (1.0, 0) for g in self._channel_gains.values()):
            img = apply_channel_gains(img, self._channel_gains)
        
        # 应用白平衡
        r, g, b = self._wb_gains
        if r != 1.0 or g != 1.0 or b != 1.0:
            img = apply_white_balance(img, r, g, b)
        
        # 应用饱和度
        if self._saturation != 1.0:
            img = adjust_saturation(img, self._saturation)
            
        return img
    
    def _numpy_to_pixmap(self, img: np.ndarray, grayscale: bool = False) -> QPixmap:
        """将NumPy数组转换为QPixmap"""
        if grayscale or len(img.shape) == 2:
            # 确保数据是连续的并创建副本
            gray = np.ascontiguousarray(img, dtype=np.uint8)
            h, w = gray.shape
            bytes_per_line = w
            # 创建 QImage 并立即复制数据
            q_img = QImage(gray.data, w, h, bytes_per_line, QImage.Format_Grayscale8).copy()
        else:
            # BGR转RGB，确保数据连续
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            # 创建 QImage 并立即复制数据
            q_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()
        
        return QPixmap.fromImage(q_img)
    
    def get_pixmap(self, channel: str = 'rgb') -> QPixmap:
        """
        获取指定通道的QPixmap
        
        Args:
            channel: 'rgb', 'r', 'g', 或 'b'
            
        Returns:
            对应通道的QPixmap
        """
        return self._cache.get(channel.lower())
    
    def get_channel_value(self, x: int, y: int, channel: str = 'rgb') -> str:
        """
        获取指定位置的像素值
        
        Args:
            x, y: 图像坐标
            channel: 通道类型
            
        Returns:
            像素值字符串
        """
        if self._original_image is None:
            return ""
            
        h, w = self._original_image.shape[:2]
        if x < 0 or x >= w or y < 0 or y >= h:
            return ""
            
        processed = self._get_processed_image()
        
        if channel == 'rgb':
            b, g, r = processed[y, x]
            return f"R:{r} G:{g} B:{b}"
        elif channel == 'r':
            return f"R:{processed[y, x, 2]}"
        elif channel == 'g':
            return f"G:{processed[y, x, 1]}"
        elif channel == 'b':
            return f"B:{processed[y, x, 0]}"
        return ""
    
    def set_white_balance(self, r_gain: float, g_gain: float, b_gain: float):
        """设置白平衡增益"""
        self._wb_gains = (r_gain, g_gain, b_gain)
        self._update_cache()
    
    def auto_white_balance(self):
        """自动白平衡（灰度世界算法）"""
        if self._original_image is None:
            return
        gains = gray_world_white_balance(self._original_image)
        self._wb_gains = gains
        self._update_cache()
        return gains
    
    def set_saturation(self, factor: float):
        """设置饱和度因子"""
        self._saturation = factor
        self._update_cache()
    
    def get_current_settings(self) -> dict:
        """获取当前调整参数"""
        return {
            'wb_gains': self._wb_gains,
            'saturation': self._saturation,
            'channel_gains': self._channel_gains.copy()
        }
    
    def set_channel_gain(self, channel: str, gain: float, offset: int = 0):
        """
        设置单个通道的增益和偏移
        
        Args:
            channel: 'r', 'g', 或 'b'
            gain: 增益系数 (例如 0.1-4.0)
            offset: 偏移量 (-128 到 128)
        """
        channel = channel.lower()
        if channel in self._channel_gains:
            self._channel_gains[channel] = (gain, offset)
            self._update_cache()
    
    def set_all_channel_gains(self, r_gain: float, r_offset: int, 
                               g_gain: float, g_offset: int,
                               b_gain: float, b_offset: int):
        """设置所有通道的增益和偏移"""
        self._channel_gains = {
            'r': (r_gain, r_offset),
            'g': (g_gain, g_offset),
            'b': (b_gain, b_offset)
        }
        self._update_cache()
    
    def reset_channel_gains(self):
        """重置所有通道增益为默认值"""
        self._channel_gains = {
            'r': (1.0, 0),
            'g': (1.0, 0),
            'b': (1.0, 0)
        }
        self._update_cache()
    
    def auto_stretch(self):
        """自动拉伸所有通道直方图"""
        if self._original_image is None:
            return
        
        # 重置通道增益
        self._channel_gains = {
            'r': (1.0, 0),
            'g': (1.0, 0),
            'b': (1.0, 0)
        }
        
        # 获取当前处理后的图像
        processed = self._get_processed_image()
        
        # 计算每个通道的拉伸参数
        import numpy as np
        for ch_name, ch_idx in [('b', 0), ('g', 1), ('r', 2)]:
            ch_data = self._original_image[:, :, ch_idx]
            in_min = np.percentile(ch_data, 1)
            in_max = np.percentile(ch_data, 99)
            
            if in_max - in_min > 1:
                # 计算增益和偏移: output = input * gain + offset
                # 将 [in_min, in_max] 映射到 [0, 255]
                gain = 255.0 / (in_max - in_min)
                offset = -in_min * gain
                self._channel_gains[ch_name] = (gain, int(offset))
        
        self._update_cache()
        return self._channel_gains.copy()
    
    @staticmethod
    def scan_directory(directory: str) -> list:
        """
        扫描目录中的图像文件
        
        Args:
            directory: 目录路径
            
        Returns:
            图像文件路径列表
        """
        if not os.path.isdir(directory):
            return []
            
        files = []
        for f in os.listdir(directory):
            if f.lower().endswith(ImageProcessor.SUPPORTED_FORMATS):
                files.append(os.path.join(directory, f))
        
        return sorted(files)
