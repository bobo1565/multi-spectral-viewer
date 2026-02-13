"""
图像混合器模块
支持多图层叠加显示，可调节各层权重
"""
import numpy as np
import cv2
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage


class ImageBlender(QObject):
    """
    图像混合器
    管理多个图层并按权重混合输出
    """
    
    # 信号
    blend_updated = pyqtSignal()  # 混合结果更新
    layers_changed = pyqtSignal()  # 图层列表变化
    
    # 混合模式
    BLEND_NORMAL = 'normal'      # 正常（加权平均）
    BLEND_ADD = 'add'            # 相加
    BLEND_DIFFERENCE = 'diff'    # 差值
    BLEND_MULTIPLY = 'multiply'  # 正片叠底
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 图层数据: {name: {'image': np.ndarray, 'weight': float, 'visible': bool}}
        self._layers = {}
        self._layer_order = []  # 图层顺序
        
        # 混合模式
        self._blend_mode = self.BLEND_NORMAL
        
        # 缓存的混合结果
        self._blended_cache = None
        self._cache_valid = False
    
    @property
    def layer_count(self) -> int:
        return len(self._layers)
    
    @property
    def layer_names(self) -> list:
        return self._layer_order.copy()
    
    @property
    def blend_mode(self) -> str:
        return self._blend_mode
    
    def set_blend_mode(self, mode: str):
        """设置混合模式"""
        if mode in (self.BLEND_NORMAL, self.BLEND_ADD, 
                    self.BLEND_DIFFERENCE, self.BLEND_MULTIPLY):
            self._blend_mode = mode
            self._cache_valid = False
            self.blend_updated.emit()
    
    def add_layer(self, name: str, image: np.ndarray, weight: float = 1.0) -> bool:
        """
        添加图层
        
        Args:
            name: 图层名称
            image: BGR格式图像
            weight: 初始权重 (0.0-1.0)
            
        Returns:
            是否添加成功
        """
        if image is None:
            return False
        
        # 确保图像是3通道
        if len(image.shape) == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        
        self._layers[name] = {
            'image': image.copy(),
            'weight': max(0.0, min(1.0, weight)),
            'visible': True
        }
        
        if name not in self._layer_order:
            self._layer_order.append(name)
        
        self._cache_valid = False
        self.layers_changed.emit()
        return True
    
    def remove_layer(self, name: str) -> bool:
        """移除图层"""
        if name in self._layers:
            del self._layers[name]
            self._layer_order.remove(name)
            self._cache_valid = False
            self.layers_changed.emit()
            return True
        return False
    
    def clear_layers(self):
        """清除所有图层"""
        self._layers.clear()
        self._layer_order.clear()
        self._cache_valid = False
        self._blended_cache = None
        self.layers_changed.emit()
    
    def set_weight(self, name: str, weight: float):
        """设置图层权重"""
        if name in self._layers:
            self._layers[name]['weight'] = max(0.0, min(1.0, weight))
            self._cache_valid = False
            self.blend_updated.emit()
    
    def get_weight(self, name: str) -> float:
        """获取图层权重"""
        if name in self._layers:
            return self._layers[name]['weight']
        return 0.0
    
    def set_visible(self, name: str, visible: bool):
        """设置图层可见性"""
        if name in self._layers:
            self._layers[name]['visible'] = visible
            self._cache_valid = False
            self.blend_updated.emit()
    
    def is_visible(self, name: str) -> bool:
        """获取图层可见性"""
        if name in self._layers:
            return self._layers[name]['visible']
        return False
    
    def get_layer_image(self, name: str) -> np.ndarray:
        """获取图层原始图像"""
        if name in self._layers:
            return self._layers[name]['image']
        return None
    
    def blend(self) -> np.ndarray:
        """
        执行图像混合
        
        Returns:
            混合后的BGR图像
        """
        if self._cache_valid and self._blended_cache is not None:
            return self._blended_cache
        
        # 获取可见图层
        visible_layers = [
            (name, self._layers[name])
            for name in self._layer_order
            if name in self._layers and self._layers[name]['visible']
        ]
        
        if not visible_layers:
            return None
        
        # 获取统一尺寸（以第一个图层为准）
        first_img = visible_layers[0][1]['image']
        h, w = first_img.shape[:2]
        
        # 初始化结果
        if self._blend_mode == self.BLEND_NORMAL:
            result = self._blend_normal(visible_layers, h, w)
        elif self._blend_mode == self.BLEND_ADD:
            result = self._blend_add(visible_layers, h, w)
        elif self._blend_mode == self.BLEND_DIFFERENCE:
            result = self._blend_difference(visible_layers, h, w)
        elif self._blend_mode == self.BLEND_MULTIPLY:
            result = self._blend_multiply(visible_layers, h, w)
        else:
            result = self._blend_normal(visible_layers, h, w)
        
        self._blended_cache = result
        self._cache_valid = True
        return result
    
    def _resize_to(self, img: np.ndarray, h: int, w: int) -> np.ndarray:
        """调整图像尺寸"""
        if img.shape[0] != h or img.shape[1] != w:
            return cv2.resize(img, (w, h))
        return img
    
    def _blend_normal(self, layers: list, h: int, w: int) -> np.ndarray:
        """正常混合（加权平均）"""
        result = np.zeros((h, w, 3), dtype=np.float32)
        total_weight = 0.0
        
        for name, layer_data in layers:
            img = self._resize_to(layer_data['image'], h, w)
            weight = layer_data['weight']
            result += img.astype(np.float32) * weight
            total_weight += weight
        
        if total_weight > 0:
            result /= total_weight
        
        return np.clip(result, 0, 255).astype(np.uint8)
    
    def _blend_add(self, layers: list, h: int, w: int) -> np.ndarray:
        """相加混合"""
        result = np.zeros((h, w, 3), dtype=np.float32)
        
        for name, layer_data in layers:
            img = self._resize_to(layer_data['image'], h, w)
            weight = layer_data['weight']
            result += img.astype(np.float32) * weight
        
        return np.clip(result, 0, 255).astype(np.uint8)
    
    def _blend_difference(self, layers: list, h: int, w: int) -> np.ndarray:
        """差值混合"""
        if len(layers) < 2:
            return self._resize_to(layers[0][1]['image'], h, w)
        
        # 以第一层为基准，计算与其他层的差值
        base = self._resize_to(layers[0][1]['image'], h, w).astype(np.float32)
        
        for name, layer_data in layers[1:]:
            img = self._resize_to(layer_data['image'], h, w).astype(np.float32)
            weight = layer_data['weight']
            diff = np.abs(base - img) * weight
            base = diff
        
        return np.clip(base, 0, 255).astype(np.uint8)
    
    def _blend_multiply(self, layers: list, h: int, w: int) -> np.ndarray:
        """正片叠底混合"""
        result = np.ones((h, w, 3), dtype=np.float32) * 255
        
        for name, layer_data in layers:
            img = self._resize_to(layer_data['image'], h, w)
            weight = layer_data['weight']
            # 正片叠底: result = (a * b) / 255
            blended = (result * img.astype(np.float32)) / 255
            # 应用权重
            result = result * (1 - weight) + blended * weight
        
        return np.clip(result, 0, 255).astype(np.uint8)
    
    def get_blended_pixmap(self) -> QPixmap:
        """获取混合结果的QPixmap"""
        blended = self.blend()
        if blended is None:
            return None
        
        # BGR转RGB
        rgb = cv2.cvtColor(blended, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        q_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()
        
        return QPixmap.fromImage(q_img)

    def get_layer_values(self, x: int, y: int) -> dict:
        """
        获取指定坐标下的各图层像素值（灰度/强度）
        会自动处理图层尺寸不一致的情况，将坐标映射到各图层
        
        Args:
            x, y: 混合后图像的坐标
            
        Returns:
            {layer_name: intensity_value} (0-255)
        """
        # 获取参考尺寸（第一个可见图层）
        visible_layers = [
            (name, self._layers[name])
            for name in self._layer_order
            if name in self._layers and self._layers[name]['visible']
        ]
        
        if not visible_layers:
            return {}
        
        # 目标尺寸（混合图像的尺寸）
        first_img = visible_layers[0][1]['image']
        th, tw = first_img.shape[:2]
        
        if not (0 <= x < tw and 0 <= y < th):
            return {}
        
        values = {}
        for name, layer_data in visible_layers:
            img = layer_data['image']
            h, w = img.shape[:2]
            
            # 计算当前图层对应的坐标
            if h == th and w == tw:
                lx, ly = x, y
            else:
                lx = int(x * w / tw)
                ly = int(y * h / th)
            
            # 边界检查
            lx = min(max(0, lx), w - 1)
            ly = min(max(0, ly), h - 1)
            
            # 获取像素值 (BGR)
            pixel = img[ly, lx]
            
            # 转为强度 (如果是灰度图转成的BGR，三个通道相等，取第一个即可)
            # 使用亮度公式: 0.299*R + 0.587*G + 0.114*B 或直接平均
            # 这里简单取平均或最大值代表强度
            intensity = int(np.mean(pixel))
            values[name] = intensity
            
        return values
