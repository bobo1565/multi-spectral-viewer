"""
图像显示组件
基于QGraphicsView实现支持缩放和平移的图像显示区
"""
from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem
)
from PyQt5.QtCore import Qt, pyqtSignal, QPointF
from PyQt5.QtGui import QPixmap, QPainter, QWheelEvent, QMouseEvent


class ImageViewer(QGraphicsView):
    """
    图像查看器
    支持：
    - 鼠标滚轮缩放
    - 左键拖拽平移
    - 坐标跟踪
    """
    
    # 信号：鼠标移动时发出图像坐标
    mouse_moved = pyqtSignal(int, int)  # x, y
    mouse_left = pyqtSignal()  # 鼠标离开
    
    # 缩放范围
    MIN_SCALE = 0.1
    MAX_SCALE = 20.0
    ZOOM_FACTOR = 1.15
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 创建场景
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        
        # 图像项
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        
        # 当前缩放级别
        self._current_scale = 1.0
        
        # 设置渲染选项
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setRenderHint(QPainter.Antialiasing)
        
        # 设置视图选项
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # 背景色
        self.setBackgroundBrush(Qt.darkGray)
        
        # 启用鼠标应用拖拽模式
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        
        # 启用鼠标跟踪
        self.setMouseTracking(True)
        
    def set_pixmap(self, pixmap: QPixmap, reset_view: bool = False):
        """
        设置显示的图像
        
        Args:
            pixmap: 要显示的QPixmap
            reset_view: 是否重置缩放和位置
        """
        if pixmap is None:
            return
            
        self._pixmap_item.setPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        
        if reset_view:
            self.reset_view()
    
    def reset_view(self):
        """重置视图到适应窗口大小"""
        self.resetTransform()
        self._current_scale = 1.0
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        # 更新当前缩放级别
        self._current_scale = self.transform().m11()
    
    def wheelEvent(self, event: QWheelEvent):
        """鼠标滚轮缩放"""
        if event.angleDelta().y() > 0:
            factor = self.ZOOM_FACTOR
        else:
            factor = 1.0 / self.ZOOM_FACTOR
            
        new_scale = self._current_scale * factor
        
        # 限制缩放范围
        if new_scale < self.MIN_SCALE or new_scale > self.MAX_SCALE:
            return
            
        self._current_scale = new_scale
        self.scale(factor, factor)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动事件"""
        # 发送图像坐标
        scene_pos = self.mapToScene(event.pos())
        x, y = int(scene_pos.x()), int(scene_pos.y())
        self.mouse_moved.emit(x, y)
            
        super().mouseMoveEvent(event)
    
    def leaveEvent(self, event):
        """鼠标离开事件"""
        self.mouse_left.emit()
        super().leaveEvent(event)
    

    
    def get_current_center(self) -> QPointF:
        """获取当前视图中心的场景坐标"""
        return self.mapToScene(self.viewport().rect().center())
    
    def set_center(self, center: QPointF):
        """设置视图中心到指定场景坐标"""
        self.centerOn(center)
    
    def get_current_scale(self) -> float:
        """获取当前缩放级别"""
        return self._current_scale
