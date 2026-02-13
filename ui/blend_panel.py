"""
图像混合面板UI (重构版)
提供多光谱波段选择、权重调节和光谱特征曲线显示
"""
import os
import cv2
import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSlider, QLabel, QGroupBox, 
    QScrollArea, QFrame, QSizePolicy, QPushButton
)
from PyQt5.QtCore import Qt, pyqtSignal, QPointF
from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QPolygonF

from core.image_blender import ImageBlender
from .custom_widgets import BandSelector


class SpectralChartWidget(QWidget):
    """光谱指纹图表控件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("background-color: #2a2a2a; border-radius: 4px;")
        
        # 预设波段波长
        self._wavelengths = {
            '450nm': 450,
            '650nm': 650,
            '750nm': 750,
            '850nm': 850
        }
        
        # 当前数据 {layer_name: value}
        self._data = {}
        
        # 坐标轴范围
        self._x_min = 400
        self._x_max = 900
        self._y_min = 0
        self._y_max = 255
        
    def set_data(self, values: dict):
        """设置数据点"""
        self._data = values
        self.update()  # 重绘
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        
        # 边距
        margin_left = 50
        margin_right = 20
        margin_top = 30
        margin_bottom = 40
        
        # 绘图区域尺寸
        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom
        
        # 绘制背景
        painter.fillRect(0, 0, w, h, QColor("#1e1e1e"))
        painter.fillRect(margin_left, margin_top, plot_w, plot_h, QColor("#252525"))
        
        # 绘制坐标轴和网格线
        axis_pen = QPen(QColor("#888888"), 1)
        grid_pen = QPen(QColor("#444444"), 1, Qt.DashLine)
        
        # 绘制Y轴刻度和水平网格线 (0, 64, 128, 192, 255)
        painter.setPen(axis_pen)
        for val in [0, 64, 128, 192, 255]:
            y = h - margin_bottom - (val - self._y_min) / (self._y_max - self._y_min) * plot_h
            # 网格线
            painter.setPen(grid_pen)
            painter.drawLine(margin_left, int(y), w - margin_right, int(y))
            # 刻度
            painter.setPen(axis_pen)
            painter.drawLine(margin_left - 5, int(y), margin_left, int(y))
            painter.drawText(0, int(y) - 10, margin_left - 8, 20, Qt.AlignRight | Qt.AlignVCenter, str(val))
        
        # 绘制X轴刻度和垂直网格线 (400, 500, ..., 900)
        for wl in range(400, 901, 100):
            x = margin_left + (wl - self._x_min) / (self._x_max - self._x_min) * plot_w
            # 网格线
            painter.setPen(grid_pen)
            painter.drawLine(int(x), margin_top, int(x), h - margin_bottom)
            # 刻度
            painter.setPen(axis_pen)
            painter.drawLine(int(x), h - margin_bottom, int(x), h - margin_bottom + 5)
            painter.drawText(int(x) - 25, h - margin_bottom + 5, 50, 20, Qt.AlignCenter, str(wl))

        # 轴标题
        painter.setPen(QPen(QColor("#aaaaaa"), 1))
        painter.drawText(margin_left, 5, plot_w, 20, Qt.AlignCenter, "光谱指纹 (Pixel Intensity)")
        painter.drawText(margin_left, h - 20, plot_w, 20, Qt.AlignCenter, "波长 (nm)")

        # 绘制数据线
        if not self._data:
            painter.setPen(QPen(QColor("#666666"), 1))
            painter.drawText(margin_left, margin_top, plot_w, plot_h, Qt.AlignCenter, "等待像素拾取...")
            return
            
        points = []
        # 按波长排序
        sorted_bands = sorted(self._wavelengths.items(), key=lambda item: item[1])
        
        for name, wl in sorted_bands:
            if name in self._data:
                val = self._data[name]
                x = margin_left + (wl - self._x_min) / (self._x_max - self._x_min) * plot_w
                y = h - margin_bottom - (val - self._y_min) / (self._y_max - self._y_min) * plot_h
                points.append(QPointF(x, y))
        
        if len(points) > 1:
            # 绘制阴影区域 (可选，增强视觉)
            path = QPolygonF(points)
            path.append(QPointF(points[-1].x(), h - margin_bottom))
            path.append(QPointF(points[0].x(), h - margin_bottom))
            painter.setBrush(QColor(0, 255, 170, 40))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(path)

            # 绘制连线
            pen = QPen(QColor("#00ffaa"), 2)
            painter.setPen(pen)
            painter.drawPolyline(QPolygonF(points))
            
            # 绘制标记点
            painter.setBrush(QColor("#00ffaa"))
            painter.setPen(QPen(QColor("white"), 1))
            for i, p in enumerate(points):
                painter.drawEllipse(p, 4, 4)
                # 在点上方显示值
                val = self._data[sorted_bands[i][0]]
                painter.drawText(int(p.x()) - 15, int(p.y()) - 20, 30, 15, Qt.AlignCenter, str(val))
        elif len(points) == 1:
            painter.setBrush(QColor("#00ffaa"))
            painter.setPen(QPen(QColor("white"), 1))
            painter.drawEllipse(points[0], 4, 4)
            val = list(self._data.values())[0]
            painter.drawText(int(points[0].x()) - 15, int(points[0].y()) - 20, 30, 15, Qt.AlignCenter, str(val))



class BlendPanel(QWidget):
    """图像混合控制面板 (多光谱版)"""
    
    # 信号
    blend_requested = pyqtSignal()  # 请求更新混合显示
    
    # 预设波段
    BANDS = ['450nm', '650nm', '750nm', '850nm']
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 混合器
        self.blender = ImageBlender()
        self.blender.set_blend_mode(ImageBlender.BLEND_NORMAL)
        
        # 图像列表（用于下拉框）
        self._image_list = []
        
        # 控件映射
        self._selectors = {}  # name -> BandSelector
        self._sliders = {}    # name -> QSlider
        self._labels = {}     # name -> QLabel (显示百分比)
        
        self._init_ui()
        self._connect_signals()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 混合模式 (保留但默认隐藏或置于顶部)
        # 暂时只用正常混合
        
        # 波段列表
        layers_group = QGroupBox("波段层级 (400~900nm)")
        layers_layout = QVBoxLayout(layers_group)
        layers_layout.setSpacing(10)
        
        for band in self.BANDS:
            # 容器
            container = QFrame()
            container.setStyleSheet("background-color: #2a2a2a; border-radius: 4px;")
            h_layout = QVBoxLayout(container)
            h_layout.setContentsMargins(5, 5, 5, 5)
            
            # 1. 选择器
            selector = BandSelector(band, band)
            selector.setFrameStyle(QFrame.NoFrame)
            selector.setStyleSheet("background: transparent;")
            selector.selection_changed.connect(self._on_band_selection_changed)
            h_layout.addWidget(selector)
            self._selectors[band] = selector
            
            # 2. 权重滑块
            slider_row = QHBoxLayout()
            slider_row.setContentsMargins(10, 0, 10, 0)
            
            w_label = QLabel("权重:")
            w_label.setStyleSheet("color: #aaa;")
            slider_row.addWidget(w_label)
            
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(25)  # 默认均分 (100/4)
            slider.valueChanged.connect(lambda v, b=band: self._on_slider_changed(b, v))
            slider_row.addWidget(slider, 1)
            self._sliders[band] = slider
            
            val_label = QLabel("25%")
            val_label.setFixedWidth(35)
            val_label.setStyleSheet("color: #0af;")
            slider_row.addWidget(val_label)
            self._labels[band] = val_label
            
            h_layout.addLayout(slider_row)
            
            layers_layout.addWidget(container)
            
            # 初始化混合器中的层
            # 初始为空，权重0.25
            # 注意：ImageBlender需要add_layer才能设置权重，这里先不add
        
        layout.addWidget(layers_group)
        
        # 按钮区
        btn_layout = QHBoxLayout()
        self.clear_btn = QPushButton("清除所有")
        self.clear_btn.clicked.connect(self._on_clear)
        btn_layout.addWidget(self.clear_btn)
        
        self.equal_btn = QPushButton("均分权重")
        self.equal_btn.clicked.connect(self._on_equalize)
        btn_layout.addWidget(self.equal_btn)
        
        layout.addLayout(btn_layout)
        
        # 光谱图表
        chart_group = QGroupBox("光谱指纹 (实时)")
        chart_layout = QVBoxLayout(chart_group)
        self.chart = SpectralChartWidget()
        chart_layout.addWidget(self.chart)
        layout.addWidget(chart_group)
        
        layout.addStretch()
        
    def _connect_signals(self):
        """连接信号"""
        self.blender.blend_updated.connect(lambda: self.blend_requested.emit())
    
    def load_images(self, image_list: list):
        """加载图像列表到下拉框"""
        self._image_list = image_list
        for selector in self._selectors.values():
            selector.set_images(image_list)
    
    def _on_band_selection_changed(self, band_name: str, image_path: str, channel: str):
        """处理波段图像选择"""
        if not image_path or not channel:
            # 移除图层
            if self.blender.remove_layer(band_name):
                pass
            return

        # 读取并提取通道
        import cv2
        img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            return
            
        # 提取单通道
        band_data = None
        if len(img.shape) == 3:  # 彩色
            if channel == 'r':
                band_data = img[:, :, 2]
            elif channel == 'g':
                band_data = img[:, :, 1]
            elif channel == 'b':
                band_data = img[:, :, 0]
            else:
                band_data = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:  # 灰度
            band_data = img
            
        # 添加/更新图层
        # 获取当前滑块权重
        weight = self._sliders[band_name].value() / 100.0
        
        # 更新混合器
        # (add_layer 会覆盖同名层)
        self.blender.add_layer(band_name, band_data, weight)
        self.blend_requested.emit()
    
    def _on_slider_changed(self, band_name: str, value: int):
        """滑块值变化"""
        self._labels[band_name].setText(f"{value}%")
        weight = value / 100.0
        # 更新混合器权重
        # 注意：如果图层还没添加（未选图），set_weight可能无效，但ImageBlender会忽略
        self.blender.set_weight(band_name, weight)
    
    def _on_clear(self):
        """清除"""
        self.blender.clear_layers()
        # 重置选择器
        for selector in self._selectors.values():
            selector.set_images(self._image_list) # 重置会清空选择
        self.blend_requested.emit()
        self.chart.set_data({})
    
    def _on_equalize(self):
        """均分权重"""
        for slider in self._sliders.values():
            slider.setValue(25)
    
    def update_spectral_chart(self, x: int, y: int):
        """更新光谱图表"""
        # 从混合器获取原始值
        values = self.blender.get_layer_values(x, y)
        self.chart.set_data(values)
        
    def get_blended_pixmap(self):
        return self.blender.get_blended_pixmap()
    
    def has_layers(self):
        return self.blender.layer_count > 0
