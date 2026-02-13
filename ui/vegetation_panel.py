"""
植被指数面板UI
提供指数选择、波段图像选择和结果显示
"""
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QFormLayout, QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal

from core.vegetation_index import VegetationIndexCalculator
from .custom_widgets import BandSelector, CHANNEL_ITEMS


class VegetationIndexPanel(QWidget):
    """植被指数控制面板"""
    
    # 信号
    calculate_requested = pyqtSignal()  # 请求计算
    display_requested = pyqtSignal()    # 请求显示结果
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 计算器
        self.calculator = VegetationIndexCalculator()
        
        # 可用图像列表
        self._image_list = []
        
        # 波段选择器
        self._band_selectors = {}
        
        self._init_ui()
        self._connect_signals()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 指数选择
        index_group = QGroupBox("植被指数")
        index_layout = QVBoxLayout(index_group)
        
        self.index_combo = QComboBox()
        for idx_name in self.calculator.available_indices:
            info = self.calculator.get_index_info(idx_name)
            self.index_combo.addItem(f"{idx_name} - {info['name']}", idx_name)
        self.index_combo.currentIndexChanged.connect(self._on_index_changed)
        index_layout.addWidget(self.index_combo)
        
        # 公式和说明
        self.formula_label = QLabel()
        self.formula_label.setStyleSheet("color: #0af; font-family: monospace;")
        self.formula_label.setWordWrap(True)
        index_layout.addWidget(self.formula_label)
        
        self.desc_label = QLabel()
        self.desc_label.setStyleSheet("color: #aaa; font-size: 11px;")
        self.desc_label.setWordWrap(True)
        index_layout.addWidget(self.desc_label)
        
        layout.addWidget(index_group)
        
        # 波段选择区域
        band_group = QGroupBox("波段图像映射")
        band_layout = QVBoxLayout(band_group)
        
        # 创建所有可能的波段选择器
        band_names = {
            'NIR': '近红外 (NIR)',
            'RED': '红光 (RED)',
            'GREEN': '绿光 (GREEN)',
            'BLUE': '蓝光 (BLUE)',
            'RED_EDGE': '红边 (RE)'
        }
        
        for band_key, band_display in band_names.items():
            selector = BandSelector(band_key, band_display)
            selector.selection_changed.connect(self._on_band_selected)
            band_layout.addWidget(selector)
            self._band_selectors[band_key] = selector
        
        layout.addWidget(band_group)
        
        # 色带选择
        color_group = QGroupBox("色带")
        color_layout = QHBoxLayout(color_group)
        
        self.colormap_combo = QComboBox()
        for name in VegetationIndexCalculator.COLORMAPS.keys():
            self.colormap_combo.addItem(name)
        self.colormap_combo.setCurrentText('Turbo')
        self.colormap_combo.currentTextChanged.connect(self._on_colormap_changed)
        color_layout.addWidget(self.colormap_combo)
        
        layout.addWidget(color_group)
        
        # 计算按钮
        self.calc_btn = QPushButton("计算植被指数")
        self.calc_btn.setStyleSheet("font-size: 14px; padding: 8px;")
        self.calc_btn.clicked.connect(self._on_calculate_clicked)
        layout.addWidget(self.calc_btn)
        
        # 统计信息
        stats_group = QGroupBox("统计信息")
        stats_layout = QFormLayout(stats_group)
        
        self.min_label = QLabel("-")
        self.max_label = QLabel("-")
        self.mean_label = QLabel("-")
        self.std_label = QLabel("-")
        
        stats_layout.addRow("最小值:", self.min_label)
        stats_layout.addRow("最大值:", self.max_label)
        stats_layout.addRow("平均值:", self.mean_label)
        stats_layout.addRow("标准差:", self.std_label)
        
        layout.addWidget(stats_group)
        
        # 状态标签
        self.status_label = QLabel("请选择波段图像")
        self.status_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        # 初始化显示
        self._on_index_changed(0)
        self._update_band_visibility()
    
    def _connect_signals(self):
        """连接信号"""
        self.calculator.result_updated.connect(self._on_result_updated)
    
    def load_images(self, image_list: list):
        """加载图像列表供选择"""
        self._image_list = image_list
        for selector in self._band_selectors.values():
            selector.set_images(image_list)
        self.status_label.setText(f"已加载 {len(image_list)} 张图像")
    
    def _on_index_changed(self, index: int):
        """指数选择变化"""
        idx_name = self.index_combo.currentData()
        if idx_name:
            info = self.calculator.get_index_info(idx_name)
            self.formula_label.setText(f"公式: {info.get('formula', '')}")
            self.desc_label.setText(info.get('description', ''))
            self._update_band_visibility()
    
    def _update_band_visibility(self):
        """根据当前指数更新波段选择器可见性"""
        idx_name = self.index_combo.currentData()
        if not idx_name:
            return
        
        required_bands = self.calculator.get_index_info(idx_name).get('bands', [])
        
        for band_key, selector in self._band_selectors.items():
            if band_key in required_bands:
                selector.show()
            else:
                selector.hide()
    
    def _on_band_selected(self, band_name: str, image_path: str, channel: str):
        """波段图像+通道选择"""
        if image_path and channel:
            import cv2
            # 使用 IMREAD_UNCHANGED 正确读取灰度/单通道图像
            img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
            if img is not None:
                # 根据通道类型提取对应数据
                if len(img.shape) == 3:  # 彩色图像
                    if channel == 'r':
                        band_data = img[:, :, 2]  # BGR -> R
                        channel_name = "R通道"
                    elif channel == 'g':
                        band_data = img[:, :, 1]  # BGR -> G
                        channel_name = "G通道"
                    elif channel == 'b':
                        band_data = img[:, :, 0]  # BGR -> B
                        channel_name = "B通道"
                    else:  # rgb - 取灰度
                        band_data = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                        channel_name = "灰度"
                else:  # 灰度图像
                    band_data = img
                    channel_name = "灰度"
                
                self.calculator.set_band_image(band_name, band_data)
                basename = os.path.basename(image_path)
                self.status_label.setText(
                    f"已设置 {band_name}: {basename} ({channel_name})"
                )
    
    def _on_colormap_changed(self, name: str):
        """色带变化"""
        self.calculator.set_colormap(name)
        if self.calculator.get_result() is not None:
            self.display_requested.emit()
    
    def _on_calculate_clicked(self):
        """计算按钮点击"""
        idx_name = self.index_combo.currentData()
        if not idx_name:
            return
        
        if not self.calculator.can_calculate(idx_name):
            self.status_label.setText("请先选择所需的波段图像")
            return
        
        self.calculator.calculate(idx_name)
        self.calculate_requested.emit()
    
    def _on_result_updated(self):
        """结果更新"""
        stats = self.calculator.get_statistics()
        if stats:
            self.min_label.setText(f"{stats['min']:.4f}")
            self.max_label.setText(f"{stats['max']:.4f}")
            self.mean_label.setText(f"{stats['mean']:.4f}")
            self.std_label.setText(f"{stats['std']:.4f}")
            self.status_label.setText("计算完成")
        
        self.display_requested.emit()
    
    def get_result_pixmap(self):
        """获取结果pixmap"""
        return self.calculator.get_result_pixmap()
    
    def has_result(self) -> bool:
        """是否有计算结果"""
        return self.calculator.get_result() is not None
