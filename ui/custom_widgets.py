"""
自定义UI组件
"""
import os
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QComboBox
from PyQt5.QtCore import pyqtSignal

# 通道类型映射
CHANNEL_ITEMS = [
    ('RGB 彩图', 'rgb'),
    ('R 通道灰度', 'r'),
    ('G 通道灰度', 'g'),
    ('B 通道灰度', 'b'),
]

class BandSelector(QFrame):
    """波段选择器控件 - 支持图像+通道选择"""
    
    # 信号: band_name, image_path, channel
    selection_changed = pyqtSignal(str, str, str)
    
    def __init__(self, band_name: str, display_name: str, parent=None):
        super().__init__(parent)
        self._band_name = band_name
        self._image_list = []  # 图像路径列表
        
        self.setFrameStyle(QFrame.StyledPanel)
        self.setStyleSheet("QFrame { background-color: #3a3a3a; border-radius: 4px; }")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        
        label = QLabel(f"{display_name}:")
        label.setFixedWidth(70)
        label.setStyleSheet("color: white; font-weight: bold;")
        layout.addWidget(label)
        
        self.combo = QComboBox()
        self.combo.addItem("-- 选择图像/通道 --", (None, None))
        self.combo.setMinimumWidth(200)
        # 强制样式以确保在不同系统上的可见性
        self.combo.setStyleSheet("""
            QComboBox {
                background-color: #505050;
                color: white;
                border: 1px solid #606060;
                border-radius: 3px;
                padding: 4px;
            }
            QComboBox:hover {
                background-color: #606060;
            }
            QComboBox::drop-down {
                border: 0px;
            }
            QComboBox QAbstractItemView {
                background-color: #505050;
                color: white;
                selection-background-color: #0078d7;
            }
        """)
        self.combo.currentIndexChanged.connect(self._on_selection_changed)
        layout.addWidget(self.combo, 1)
    
    @property
    def band_name(self) -> str:
        return self._band_name
    
    def set_images(self, image_list: list):
        """设置可选图像列表，自动添加每个图像的通道选项"""
        self._image_list = image_list
        self.combo.blockSignals(True)
        current = self.combo.currentData()
        self.combo.clear()
        self.combo.addItem("-- 选择图像/通道 --", (None, None))
        
        for img_path in image_list:
            basename = os.path.basename(img_path)
            
            # 添加每个通道选项
            for display_name, channel_type in CHANNEL_ITEMS:
                item_text = f"{basename} → {display_name}"
                self.combo.addItem(item_text, (img_path, channel_type))
        
        # 恢复选择
        if current and current != (None, None):
            for i in range(self.combo.count()):
                if self.combo.itemData(i) == current:
                    self.combo.setCurrentIndex(i)
                    break
        
        self.combo.blockSignals(False)
    
    def get_selected_path(self) -> str:
        """获取选中的图像路径"""
        data = self.combo.currentData()
        return data[0] if data else None
    
    def get_selected_channel(self) -> str:
        """获取选中的通道"""
        data = self.combo.currentData()
        return data[1] if data else None
    
    def _on_selection_changed(self, index: int):
        """选择变化"""
        data = self.combo.currentData()
        if data:
            path, channel = data
            self.selection_changed.emit(self._band_name, path or "", channel or "")
        else:
            self.selection_changed.emit(self._band_name, "", "")
