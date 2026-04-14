"""
右侧工具面板
包含直方图、白平衡、饱和度调节工具
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QToolBox, QSlider, QPushButton,
    QLabel, QHBoxLayout, QGroupBox, QDoubleSpinBox, QSpinBox
)
from PyQt5.QtCore import Qt, pyqtSignal

import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class HistogramWidget(QWidget):
    """直方图显示组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 创建matplotlib画布
        self.figure = Figure(figsize=(3, 2), dpi=80)
        self.figure.patch.set_facecolor('#2d2d2d')
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        
        # 设置样式
        self.ax.set_facecolor('#2d2d2d')
        self.ax.tick_params(colors='white', labelsize=7)
        for spine in self.ax.spines.values():
            spine.set_color('white')
        
        layout.addWidget(self.canvas)
        
    def update_histogram(self, hist_data: dict):
        """
        更新直方图显示
        
        Args:
            hist_data: 直方图数据字典，可能包含 'r', 'g', 'b' 或 'gray'
        """
        self.ax.clear()
        self.ax.set_facecolor('#2d2d2d')
        
        x = range(256)
        
        if 'gray' in hist_data:
            # 灰度直方图
            self.ax.fill_between(x, hist_data['gray'], alpha=0.7, color='white')
            self.ax.plot(x, hist_data['gray'], color='white', linewidth=0.8)
        else:
            # RGB直方图
            if 'r' in hist_data:
                self.ax.fill_between(x, hist_data['r'], alpha=0.3, color='red')
                self.ax.plot(x, hist_data['r'], color='red', linewidth=0.8)
            if 'g' in hist_data:
                self.ax.fill_between(x, hist_data['g'], alpha=0.3, color='lime')
                self.ax.plot(x, hist_data['g'], color='lime', linewidth=0.8)
            if 'b' in hist_data:
                self.ax.fill_between(x, hist_data['b'], alpha=0.3, color='dodgerblue')
                self.ax.plot(x, hist_data['b'], color='dodgerblue', linewidth=0.8)
        
        self.ax.set_xlim(0, 255)
        self.ax.tick_params(colors='white', labelsize=7)
        
        self.figure.tight_layout()
        self.canvas.draw()


class WhiteBalanceWidget(QWidget):
    """白平衡调节组件"""
    
    # 信号：增益变化
    gains_changed = pyqtSignal(float, float, float)  # r, g, b
    auto_wb_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # R通道
        self.r_slider, self.r_spin = self._create_channel_control("R 增益", layout)
        # G通道
        self.g_slider, self.g_spin = self._create_channel_control("G 增益", layout)
        # B通道
        self.b_slider, self.b_spin = self._create_channel_control("B 增益", layout)
        
        # 按钮区
        btn_layout = QHBoxLayout()
        
        # 自动校准按钮
        self.auto_btn = QPushButton("自动校准")
        self.auto_btn.clicked.connect(self.auto_wb_requested.emit)
        btn_layout.addWidget(self.auto_btn)
        
        # 重置按钮
        self.reset_btn = QPushButton("重置")
        self.reset_btn.clicked.connect(self.reset_gains)
        btn_layout.addWidget(self.reset_btn)
        
        layout.addLayout(btn_layout)
        layout.addStretch()
        
    def _create_channel_control(self, label: str, parent_layout: QVBoxLayout):
        """创建通道控制滑块和数值框"""
        group = QGroupBox(label)
        h_layout = QHBoxLayout(group)
        
        slider = QSlider(Qt.Horizontal)
        slider.setRange(50, 200)  # 0.5 ~ 2.0
        slider.setValue(100)
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setTickInterval(25)
        
        spin = QDoubleSpinBox()
        spin.setRange(0.5, 2.0)
        spin.setSingleStep(0.05)
        spin.setValue(1.0)
        spin.setDecimals(2)
        
        # 同步滑块和数值框
        slider.valueChanged.connect(lambda v: spin.setValue(v / 100.0))
        spin.valueChanged.connect(lambda v: slider.setValue(int(v * 100)))
        
        # 连接变化信号
        slider.sliderReleased.connect(self._emit_gains)
        spin.editingFinished.connect(self._emit_gains)
        
        h_layout.addWidget(slider, 3)
        h_layout.addWidget(spin, 1)
        
        parent_layout.addWidget(group)
        return slider, spin
    
    def _emit_gains(self):
        """发送增益变化信号"""
        r = self.r_spin.value()
        g = self.g_spin.value()
        b = self.b_spin.value()
        self.gains_changed.emit(r, g, b)
    
    def set_gains(self, r: float, g: float, b: float):
        """设置增益值（不触发信号）"""
        self.r_slider.blockSignals(True)
        self.g_slider.blockSignals(True)
        self.b_slider.blockSignals(True)
        self.r_spin.blockSignals(True)
        self.g_spin.blockSignals(True)
        self.b_spin.blockSignals(True)
        
        self.r_spin.setValue(r)
        self.g_spin.setValue(g)
        self.b_spin.setValue(b)
        self.r_slider.setValue(int(r * 100))
        self.g_slider.setValue(int(g * 100))
        self.b_slider.setValue(int(b * 100))
        
        self.r_slider.blockSignals(False)
        self.g_slider.blockSignals(False)
        self.b_slider.blockSignals(False)
        self.r_spin.blockSignals(False)
        self.g_spin.blockSignals(False)
        self.b_spin.blockSignals(False)
    
    def reset_gains(self):
        """重置所有增益为1.0"""
        self.set_gains(1.0, 1.0, 1.0)
        self.gains_changed.emit(1.0, 1.0, 1.0)


class SaturationWidget(QWidget):
    """饱和度调节组件"""
    
    # 信号：饱和度变化
    saturation_changed = pyqtSignal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 标签
        label = QLabel("饱和度调节")
        layout.addWidget(label)
        
        # 控制区
        ctrl_layout = QHBoxLayout()
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 200)  # 0 ~ 2.0
        self.slider.setValue(100)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(25)
        
        self.spin = QDoubleSpinBox()
        self.spin.setRange(0.0, 2.0)
        self.spin.setSingleStep(0.1)
        self.spin.setValue(1.0)
        self.spin.setDecimals(2)
        
        # 同步
        self.slider.valueChanged.connect(lambda v: self.spin.setValue(v / 100.0))
        self.spin.valueChanged.connect(lambda v: self.slider.setValue(int(v * 100)))
        
        # 连接信号
        self.slider.sliderReleased.connect(self._emit_saturation)
        self.spin.editingFinished.connect(self._emit_saturation)
        
        ctrl_layout.addWidget(self.slider, 3)
        ctrl_layout.addWidget(self.spin, 1)
        layout.addLayout(ctrl_layout)
        
        # 重置按钮
        self.reset_btn = QPushButton("重置")
        self.reset_btn.clicked.connect(self.reset_saturation)
        layout.addWidget(self.reset_btn)
        
        layout.addStretch()
    
    def _emit_saturation(self):
        """发送饱和度变化信号"""
        self.saturation_changed.emit(self.spin.value())
    
    def set_saturation(self, value: float):
        """设置饱和度值"""
        self.slider.blockSignals(True)
        self.spin.blockSignals(True)
        
        self.spin.setValue(value)
        self.slider.setValue(int(value * 100))
        
        self.slider.blockSignals(False)
        self.spin.blockSignals(False)
    
    def reset_saturation(self):
        """重置饱和度为1.0"""
        self.set_saturation(1.0)
        self.saturation_changed.emit(1.0)


class ChannelGainWidget(QWidget):
    """通道增益调节组件"""
    
    # 信号：通道增益变化 (channel, gain, offset)
    channel_gain_changed = pyqtSignal(str, float, int)
    auto_stretch_requested = pyqtSignal()
    reset_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # R通道控制
        self.r_gain, self.r_offset = self._create_channel_control("R 红色通道", "red", layout)
        # G通道控制
        self.g_gain, self.g_offset = self._create_channel_control("G 绿色通道", "green", layout)
        # B通道控制
        self.b_gain, self.b_offset = self._create_channel_control("B 蓝色通道", "blue", layout)
        
        # 按钮区
        btn_layout = QHBoxLayout()
        
        # 自动拉伸按钮
        self.auto_btn = QPushButton("自动拉伸")
        self.auto_btn.setToolTip("自动计算增益使所有通道直方图分布在0-255")
        self.auto_btn.clicked.connect(self.auto_stretch_requested.emit)
        btn_layout.addWidget(self.auto_btn)
        
        # 重置按钮
        self.reset_btn = QPushButton("重置")
        self.reset_btn.clicked.connect(self._reset_all)
        btn_layout.addWidget(self.reset_btn)
        
        layout.addLayout(btn_layout)
        layout.addStretch()
    
    def _create_channel_control(self, label: str, color: str, parent_layout: QVBoxLayout):
        """创建单个通道的增益和偏移控制"""
        group = QGroupBox(label)
        group.setStyleSheet(f"QGroupBox {{ color: {color}; font-weight: bold; }}")
        v_layout = QVBoxLayout(group)
        v_layout.setSpacing(5)
        
        # 增益控制
        gain_layout = QHBoxLayout()
        gain_label = QLabel("增益:")
        gain_label.setFixedWidth(35)
        
        gain_slider = QSlider(Qt.Horizontal)
        gain_slider.setRange(10, 400)  # 0.1 ~ 4.0
        gain_slider.setValue(100)
        gain_slider.setTickPosition(QSlider.TicksBelow)
        gain_slider.setTickInterval(50)
        
        gain_spin = QDoubleSpinBox()
        gain_spin.setRange(0.1, 4.0)
        gain_spin.setSingleStep(0.1)
        gain_spin.setValue(1.0)
        gain_spin.setDecimals(2)
        gain_spin.setFixedWidth(65)
        
        # 同步滑块和数值框
        gain_slider.valueChanged.connect(lambda v: gain_spin.setValue(v / 100.0))
        gain_spin.valueChanged.connect(lambda v: gain_slider.setValue(int(v * 100)))
        
        gain_layout.addWidget(gain_label)
        gain_layout.addWidget(gain_slider, 3)
        gain_layout.addWidget(gain_spin)
        v_layout.addLayout(gain_layout)
        
        # 偏移控制
        offset_layout = QHBoxLayout()
        offset_label = QLabel("偏移:")
        offset_label.setFixedWidth(35)
        
        offset_slider = QSlider(Qt.Horizontal)
        offset_slider.setRange(-128, 128)
        offset_slider.setValue(0)
        offset_slider.setTickPosition(QSlider.TicksBelow)
        offset_slider.setTickInterval(32)
        
        offset_spin = QSpinBox()
        offset_spin.setRange(-128, 128)
        offset_spin.setValue(0)
        offset_spin.setFixedWidth(65)
        
        # 同步
        offset_slider.valueChanged.connect(offset_spin.setValue)
        offset_spin.valueChanged.connect(offset_slider.setValue)
        
        offset_layout.addWidget(offset_label)
        offset_layout.addWidget(offset_slider, 3)
        offset_layout.addWidget(offset_spin)
        v_layout.addLayout(offset_layout)
        
        parent_layout.addWidget(group)
        
        # 连接信号 - 使用 valueChanged 实现实时更新
        channel = label[0].lower()  # 'r', 'g', 或 'b'
        gain_slider.valueChanged.connect(
            lambda v, ch=channel: self._emit_channel_gain(ch))
        offset_slider.valueChanged.connect(
            lambda v, ch=channel: self._emit_channel_gain(ch))
        
        return (gain_slider, gain_spin), (offset_slider, offset_spin)
    
    def _emit_channel_gain(self, channel: str):
        """发送通道增益变化信号"""
        if channel == 'r':
            gain = self.r_gain[1].value()
            offset = self.r_offset[1].value()
        elif channel == 'g':
            gain = self.g_gain[1].value()
            offset = self.g_offset[1].value()
        else:
            gain = self.b_gain[1].value()
            offset = self.b_offset[1].value()
        
        self.channel_gain_changed.emit(channel, gain, offset)
    
    def set_channel_values(self, channel: str, gain: float, offset: int):
        """设置通道值（不触发信号）"""
        if channel == 'r':
            controls = (self.r_gain, self.r_offset)
        elif channel == 'g':
            controls = (self.g_gain, self.g_offset)
        else:
            controls = (self.b_gain, self.b_offset)
        
        gain_slider, gain_spin = controls[0]
        offset_slider, offset_spin = controls[1]
        
        gain_slider.blockSignals(True)
        gain_spin.blockSignals(True)
        offset_slider.blockSignals(True)
        offset_spin.blockSignals(True)
        
        gain_spin.setValue(gain)
        gain_slider.setValue(int(gain * 100))
        offset_spin.setValue(offset)
        offset_slider.setValue(offset)
        
        gain_slider.blockSignals(False)
        gain_spin.blockSignals(False)
        offset_slider.blockSignals(False)
        offset_spin.blockSignals(False)
    
    def _reset_all(self):
        """重置所有通道"""
        self.set_channel_values('r', 1.0, 0)
        self.set_channel_values('g', 1.0, 0)
        self.set_channel_values('b', 1.0, 0)
        self.reset_requested.emit()


class ToolPanel(QToolBox):
    """右侧工具面板"""
    
    # 信号转发
    wb_gains_changed = pyqtSignal(float, float, float)
    auto_wb_requested = pyqtSignal()
    saturation_changed = pyqtSignal(float)
    channel_gain_changed = pyqtSignal(str, float, int)  # channel, gain, offset
    auto_stretch_requested = pyqtSignal()
    channel_gains_reset = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 直方图
        self.histogram = HistogramWidget()
        self.addItem(self.histogram, "📊 直方图")
        
        # 通道增益 - 放在最前面方便用户快速访问
        self.channel_gain = ChannelGainWidget()
        self.channel_gain.channel_gain_changed.connect(self.channel_gain_changed.emit)
        self.channel_gain.auto_stretch_requested.connect(self.auto_stretch_requested.emit)
        self.channel_gain.reset_requested.connect(self.channel_gains_reset.emit)
        self.addItem(self.channel_gain, "📈 通道增益")
        
        # 白平衡
        self.white_balance = WhiteBalanceWidget()
        self.white_balance.gains_changed.connect(self.wb_gains_changed.emit)
        self.white_balance.auto_wb_requested.connect(self.auto_wb_requested.emit)
        self.addItem(self.white_balance, "⚖️ 白平衡")
        
        # 饱和度
        self.saturation = SaturationWidget()
        self.saturation.saturation_changed.connect(self.saturation_changed.emit)
        self.addItem(self.saturation, "🎨 饱和度")
        
        # 设置最小宽度
        self.setMinimumWidth(300)
    
    def update_histogram(self, hist_data: dict):
        """更新直方图"""
        self.histogram.update_histogram(hist_data)
    
    def set_wb_gains(self, r: float, g: float, b: float):
        """设置白平衡增益显示"""
        self.white_balance.set_gains(r, g, b)
    
    def set_saturation(self, value: float):
        """设置饱和度显示"""
        self.saturation.set_saturation(value)
    
    def set_channel_gain(self, channel: str, gain: float, offset: int):
        """设置通道增益显示"""
        self.channel_gain.set_channel_values(channel, gain, offset)
    
    def reset_all(self):
        """重置所有工具"""
        self.white_balance.reset_gains()
        self.saturation.reset_saturation()
        self.channel_gain._reset_all()

