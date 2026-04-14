"""
植被指数计算模块
支持 NDVI, GNDVI, NDRE 等常见遥感植被指数
"""
import numpy as np
import cv2


class VegetationIndexCalculator:
    """
    植被指数计算器
    """
    
    # 预定义的植被指数
    INDICES = {
        'NDVI': {
            'name': '归一化差值植被指数',
            'formula': '(NIR - RED) / (NIR + RED)',
            'bands': ['NIR', 'RED'],
            'description': '最常用的植被指数，反映植被覆盖度和生长状况'
        },
        'GNDVI': {
            'name': '绿色归一化差值植被指数',
            'formula': '(NIR - GREEN) / (NIR + GREEN)',
            'bands': ['NIR', 'GREEN'],
            'description': '对叶绿素含量更敏感，适用于高覆盖度区域'
        },
        'NDRE': {
            'name': '归一化差值红边指数',
            'formula': '(NIR - RED_EDGE) / (NIR + RED_EDGE)',
            'bands': ['NIR', 'RED_EDGE'],
            'description': '对作物氮素状况敏感，适用于精准农业'
        },
        'SAVI': {
            'name': '土壤调节植被指数',
            'formula': '(NIR - RED) * 1.5 / (NIR + RED + 0.5)',
            'bands': ['NIR', 'RED'],
            'description': '减少土壤背景影响，适用于稀疏植被区域'
        },
        'EVI': {
            'name': '增强型植被指数',
            'formula': '2.5 * (NIR - RED) / (NIR + 6*RED - 7.5*BLUE + 1)',
            'bands': ['NIR', 'RED', 'BLUE'],
            'description': '减少大气和土壤影响，适用于高生物量区域'
        }
    }
    
    # 常用色带映射
    COLORMAPS = {
        'RdYlGn': cv2.COLORMAP_JET,  # 红黄绿渐变
        'Viridis': cv2.COLORMAP_VIRIDIS,
        'Plasma': cv2.COLORMAP_PLASMA,
        'Inferno': cv2.COLORMAP_INFERNO,
        'Turbo': cv2.COLORMAP_TURBO,
        'Gray': None,  # 灰度图特殊处理
    }
    
    def __init__(self):
        
        # 波段图像映射
        self._band_images = {}  # band_name -> np.ndarray (grayscale)
        
        # 当前结果
        self._result = None
        self._result_colorized = None
        self._current_index = None
        self._colormap = cv2.COLORMAP_TURBO
    
    @property
    def available_indices(self) -> list:
        """获取可用的植被指数列表"""
        return list(self.INDICES.keys())
    
    def get_index_info(self, index_name: str) -> dict:
        """获取植被指数信息"""
        return self.INDICES.get(index_name, {})
    
    def set_band_image(self, band_name: str, image: np.ndarray):
        """
        设置波段图像
        
        Args:
            band_name: 波段名称 (NIR, RED, GREEN, BLUE, RED_EDGE)
            image: 图像数组（可以是彩色或灰度，8位或16位）
        """
        if image is None:
            return
        
        # 转为灰度
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()
        
        # 将图像转为float32并归一化到0-255范围
        gray = gray.astype(np.float32)
        
        # 如果是16位图像，归一化到0-255
        if gray.max() > 255:
            gray = (gray / gray.max()) * 255
        
        self._band_images[band_name] = gray
        self._result = None  # 清除缓存
    
    def get_band_names(self) -> list:
        """获取已设置的波段名称"""
        return list(self._band_images.keys())
    
    def clear_bands(self):
        """清除所有波段"""
        self._band_images.clear()
        self._result = None
        self._result_colorized = None
    
    def can_calculate(self, index_name: str) -> bool:
        """检查是否可以计算指定的植被指数"""
        if index_name not in self.INDICES:
            return False
        required_bands = self.INDICES[index_name]['bands']
        return all(band in self._band_images for band in required_bands)
    
    def calculate(self, index_name: str) -> np.ndarray:
        """
        计算植被指数
        
        Args:
            index_name: 植被指数名称
            
        Returns:
            归一化后的指数图像 (值范围 -1 到 1)
        """
        if not self.can_calculate(index_name):
            return None
        
        self._current_index = index_name
        
        # 获取波段
        bands = {name: self._band_images[name] for name in self.INDICES[index_name]['bands']}
        
        # 计算指数
        if index_name == 'NDVI':
            result = self._calc_ndvi(bands['NIR'], bands['RED'])
        elif index_name == 'GNDVI':
            result = self._calc_gndvi(bands['NIR'], bands['GREEN'])
        elif index_name == 'NDRE':
            result = self._calc_ndre(bands['NIR'], bands['RED_EDGE'])
        elif index_name == 'SAVI':
            result = self._calc_savi(bands['NIR'], bands['RED'])
        elif index_name == 'EVI':
            result = self._calc_evi(bands['NIR'], bands['RED'], bands['BLUE'])
        else:
            return None
        
        self._result = result
        self._apply_colormap()
        return result
    
    def _calc_ndvi(self, nir: np.ndarray, red: np.ndarray) -> np.ndarray:
        """计算 NDVI"""
        # 确保尺寸一致
        nir, red = self._resize_to_match(nir, red)
        
        with np.errstate(divide='ignore', invalid='ignore'):
            ndvi = (nir - red) / (nir + red + 1e-10)
            ndvi = np.clip(ndvi, -1, 1)
        return ndvi
    
    def _calc_gndvi(self, nir: np.ndarray, green: np.ndarray) -> np.ndarray:
        """计算 GNDVI"""
        nir, green = self._resize_to_match(nir, green)
        
        with np.errstate(divide='ignore', invalid='ignore'):
            gndvi = (nir - green) / (nir + green + 1e-10)
            gndvi = np.clip(gndvi, -1, 1)
        return gndvi
    
    def _calc_ndre(self, nir: np.ndarray, red_edge: np.ndarray) -> np.ndarray:
        """计算 NDRE"""
        nir, red_edge = self._resize_to_match(nir, red_edge)
        
        with np.errstate(divide='ignore', invalid='ignore'):
            ndre = (nir - red_edge) / (nir + red_edge + 1e-10)
            ndre = np.clip(ndre, -1, 1)
        return ndre
    
    def _calc_savi(self, nir: np.ndarray, red: np.ndarray, L: float = 0.5) -> np.ndarray:
        """计算 SAVI"""
        nir, red = self._resize_to_match(nir, red)
        
        with np.errstate(divide='ignore', invalid='ignore'):
            savi = (nir - red) * (1 + L) / (nir + red + L + 1e-10)
            savi = np.clip(savi, -1, 1)
        return savi
    
    def _calc_evi(self, nir: np.ndarray, red: np.ndarray, blue: np.ndarray) -> np.ndarray:
        """计算 EVI"""
        nir, red = self._resize_to_match(nir, red)
        _, blue = self._resize_to_match(nir, blue)
        
        with np.errstate(divide='ignore', invalid='ignore'):
            evi = 2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1 + 1e-10)
            evi = np.clip(evi, -1, 1)
        return evi
    
    def _resize_to_match(self, img1: np.ndarray, img2: np.ndarray) -> tuple:
        """调整两个图像尺寸一致"""
        if img1.shape != img2.shape:
            h, w = img1.shape[:2]
            img2 = cv2.resize(img2, (w, h))
        return img1, img2
    
    def set_colormap(self, colormap_name: str):
        """设置色带"""
        if colormap_name in self.COLORMAPS:
            self._colormap = self.COLORMAPS[colormap_name]
            if self._result is not None:
                self._apply_colormap()
    
    def _apply_colormap(self):
        """应用色带到结果"""
        if self._result is None:
            return
        
        # 将 -1~1 映射到 0~255
        normalized = ((self._result + 1) / 2 * 255).astype(np.uint8)
        
        # 应用色带
        if self._colormap is None:
            self._result_colorized = cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)
        else:
            self._result_colorized = cv2.applyColorMap(normalized, self._colormap)
    
    def get_result(self) -> np.ndarray:
        """获取原始结果（-1 到 1）"""
        return self._result
    
    def get_colorized_result(self) -> np.ndarray:
        """获取着色后的结果"""
        return self._result_colorized
    
    def get_result_colorized_rgb(self) -> np.ndarray:
        """获取着色后的结果(RGB格式用于显示)"""
        if self._result_colorized is None:
            return None
        
        return cv2.cvtColor(self._result_colorized, cv2.COLOR_BGR2RGB)
    
    def get_statistics(self) -> dict:
        """获取结果统计信息"""
        if self._result is None:
            return {}
        
        valid = self._result[~np.isnan(self._result)]
        return {
            'min': float(np.min(valid)),
            'max': float(np.max(valid)),
            'mean': float(np.mean(valid)),
            'std': float(np.std(valid))
        }
