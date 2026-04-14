"""
图像文件树组件
显示目录中的图像文件及其通道
"""
import os
from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QIcon


class ImageTreeWidget(QTreeWidget):
    """
    图像文件树
    结构：
      图像文件名 (Root)
      ├── RGB 彩图
      ├── R 通道灰度
      ├── G 通道灰度
      └── B 通道灰度
    """
    
    # 信号：选中项变化时发出 (文件路径, 通道类型)
    selection_changed = pyqtSignal(str, str)  # path, channel
    
    # 通道类型映射
    CHANNEL_ITEMS = [
        ('RGB 彩图', 'rgb'),
        ('R 通道灰度', 'r'),
        ('G 通道灰度', 'g'),
        ('B 通道灰度', 'b'),
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 设置列标题
        self.setHeaderLabel("图像文件")
        
        # 设置选择模式
        self.setSelectionMode(QTreeWidget.SingleSelection)
        
        # 连接信号
        self.itemClicked.connect(self._on_item_clicked)
        
        # 当前目录
        self._current_dir = None
        
        # 存储文件路径映射
        self._file_paths = {}  # item -> path
        
    def load_directory(self, directory: str, file_list: list):
        """
        加载目录中的图像文件
        
        Args:
            directory: 目录路径
            file_list: 图像文件路径列表
        """
        self.clear()
        self._file_paths.clear()
        self._current_dir = directory
        
        for file_path in file_list:
            filename = os.path.basename(file_path)
            
            # 创建根项（文件名）
            root_item = QTreeWidgetItem([filename])
            root_item.setData(0, Qt.UserRole, file_path)
            root_item.setData(0, Qt.UserRole + 1, None)  # 无通道
            
            # 创建子项（各通道）
            for display_name, channel_type in self.CHANNEL_ITEMS:
                child_item = QTreeWidgetItem([display_name])
                child_item.setData(0, Qt.UserRole, file_path)
                child_item.setData(0, Qt.UserRole + 1, channel_type)
                root_item.addChild(child_item)
            
            self.addTopLevelItem(root_item)
            self._file_paths[id(root_item)] = file_path
        
        # 展开第一项并选中RGB
        if self.topLevelItemCount() > 0:
            first_item = self.topLevelItem(0)
            first_item.setExpanded(True)
            if first_item.childCount() > 0:
                rgb_item = first_item.child(0)
                self.setCurrentItem(rgb_item)
                self._emit_selection(rgb_item)
    
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """处理项点击事件"""
        self._emit_selection(item)
    
    def _emit_selection(self, item: QTreeWidgetItem):
        """发送选择变化信号"""
        file_path = item.data(0, Qt.UserRole)
        channel = item.data(0, Qt.UserRole + 1)
        
        # 如果点击的是根项（文件名），默认显示RGB
        if channel is None:
            channel = 'rgb'
            # 自动展开并选择RGB子项
            item.setExpanded(True)
            if item.childCount() > 0:
                self.setCurrentItem(item.child(0))
        
        if file_path:
            self.selection_changed.emit(file_path, channel)
    
    def get_current_file(self) -> str:
        """获取当前选中的文件路径"""
        item = self.currentItem()
        if item:
            return item.data(0, Qt.UserRole)
        return None
    
    def get_current_channel(self) -> str:
        """获取当前选中的通道类型"""
        item = self.currentItem()
        if item:
            channel = item.data(0, Qt.UserRole + 1)
            return channel if channel else 'rgb'
        return 'rgb'
