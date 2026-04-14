"""
主窗口模块
整合所有UI组件
"""
import os
from PyQt5.QtWidgets import (
    QMainWindow, QDockWidget, QFileDialog, QStatusBar,
    QMenuBar, QAction, QMessageBox, QApplication
)
from PyQt5.QtCore import Qt

from .image_viewer import ImageViewer
from .image_tree import ImageTreeWidget
from .tool_panel import ToolPanel
from .alignment_panel import AlignmentPanel
from .blend_panel import BlendPanel
from .vegetation_panel import VegetationIndexPanel
from core.image_processor import ImageProcessor


class MainWindow(QMainWindow):
    """多光谱图像分析软件主窗口"""
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("多光谱图像分析软件")
        self.setMinimumSize(1200, 800)
        
        # 图像处理器
        self.processor = ImageProcessor()
        
        # 当前状态
        self._current_file = None
        self._current_channel = 'rgb'
        self._current_directory = None
        self._image_files = []
        self._blend_mode = False  # 是否在混合模式
        
        # 初始化UI
        self._init_ui()
        self._init_menu()
        self._connect_signals()
        
    def _init_ui(self):
        """初始化UI组件"""
        # 中央图像显示区
        self.image_viewer = ImageViewer()
        self.setCentralWidget(self.image_viewer)
        
        # 左侧文件树 Dock
        self.tree_dock = QDockWidget("文件浏览", self)
        self.tree_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.image_tree = ImageTreeWidget()
        self.tree_dock.setWidget(self.image_tree)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.tree_dock)
        
        # 右侧工具面板 Dock
        self.tool_dock = QDockWidget("工具", self)
        self.tool_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.tool_panel = ToolPanel()
        self.tool_dock.setWidget(self.tool_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.tool_dock)
        
        # 图像对齐面板 Dock
        self.align_dock = QDockWidget("图像对齐", self)
        self.align_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.alignment_panel = AlignmentPanel()
        self.align_dock.setWidget(self.alignment_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.align_dock)
        
        # 将对齐面板放在工具面板下方
        self.tabifyDockWidget(self.tool_dock, self.align_dock)
        self.tool_dock.raise_()  # 默认显示工具面板
        
        # 图像混合面板 Dock
        self.blend_dock = QDockWidget("图层混合", self)
        self.blend_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.blend_panel = BlendPanel()
        self.blend_dock.setWidget(self.blend_panel)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.blend_dock)
        
        # 植被指数面板 Dock
        self.veg_dock = QDockWidget("植被指数", self)
        self.veg_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.vegetation_panel = VegetationIndexPanel()
        self.veg_dock.setWidget(self.vegetation_panel)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.veg_dock)
        
        # 将混合面板和植被指数面板放在同一位置
        self.tabifyDockWidget(self.blend_dock, self.veg_dock)
        self.blend_dock.raise_()
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")
        
    def _init_menu(self):
        """初始化菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        
        open_action = QAction("打开目录(&O)...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_directory)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        save_action = QAction("保存当前图像(&S)...", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save_image)
        file_menu.addAction(save_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 视图菜单
        view_menu = menubar.addMenu("视图(&V)")
        
        reset_zoom_action = QAction("重置缩放(&R)", self)
        reset_zoom_action.setShortcut("Ctrl+0")
        reset_zoom_action.triggered.connect(self._reset_zoom)
        view_menu.addAction(reset_zoom_action)
        
        view_menu.addSeparator()
        
        # 工具栏显示切换
        toggle_tree_action = self.tree_dock.toggleViewAction()
        toggle_tree_action.setText("文件浏览面板(&T)")
        view_menu.addAction(toggle_tree_action)
        
        toggle_tool_action = self.tool_dock.toggleViewAction()
        toggle_tool_action.setText("工具面板(&P)")
        view_menu.addAction(toggle_tool_action)
        
        toggle_align_action = self.align_dock.toggleViewAction()
        toggle_align_action.setText("对齐面板(&L)")
        view_menu.addAction(toggle_align_action)
        
        toggle_blend_action = self.blend_dock.toggleViewAction()
        toggle_blend_action.setText("图层混合(&B)")
        view_menu.addAction(toggle_blend_action)
        
        toggle_veg_action = self.veg_dock.toggleViewAction()
        toggle_veg_action.setText("植被指数(&V)")
        view_menu.addAction(toggle_veg_action)
        
        # 工具菜单
        tool_menu = menubar.addMenu("工具(&T)")
        
        auto_wb_action = QAction("自动白平衡(&A)", self)
        auto_wb_action.triggered.connect(self._auto_white_balance)
        tool_menu.addAction(auto_wb_action)
        
        reset_all_action = QAction("重置所有调整(&R)", self)
        reset_all_action.triggered.connect(self._reset_all_adjustments)
        tool_menu.addAction(reset_all_action)
        
    def _connect_signals(self):
        """连接信号"""
        # 文件树选择变化
        self.image_tree.selection_changed.connect(self._on_selection_changed)
        
        # 鼠标移动 -> 更新状态栏
        self.image_viewer.mouse_moved.connect(self._on_mouse_moved)
        self.image_viewer.mouse_left.connect(self._on_mouse_left)
        
        # 工具面板信号
        self.tool_panel.wb_gains_changed.connect(self._on_wb_changed)
        self.tool_panel.auto_wb_requested.connect(self._auto_white_balance)
        self.tool_panel.saturation_changed.connect(self._on_saturation_changed)
        self.tool_panel.channel_gain_changed.connect(self._on_channel_gain_changed)
        self.tool_panel.auto_stretch_requested.connect(self._on_auto_stretch)
        self.tool_panel.channel_gains_reset.connect(self._on_channel_gains_reset)
        
        # 图像处理器信号
        self.processor.histogram_updated.connect(self.tool_panel.update_histogram)
        
        # 对齐面板信号
        self.alignment_panel.alignment_done.connect(self._on_alignment_done)
        
        # 混合面板信号
        self.blend_panel.blend_requested.connect(self._on_blend_requested)
        
        # 植被指数面板信号
        self.vegetation_panel.display_requested.connect(self._on_vegetation_display)
        
    def _open_directory(self):
        """打开目录"""
        directory = QFileDialog.getExistingDirectory(
            self, "选择图像目录", "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        
        if directory:
            files = ImageProcessor.scan_directory(directory)
            if files:
                self._current_directory = directory
                self._image_files = files
                self.image_tree.load_directory(directory, files)
                # 同时更新对齐面板
                self.alignment_panel.load_images(files)
                # 更新植被指数面板
                self.vegetation_panel.load_images(files)
                # 更新多光谱混合面板
                self.blend_panel.load_images(files)
                self.status_bar.showMessage(f"已加载 {len(files)} 个图像文件")
            else:
                QMessageBox.information(
                    self, "提示",
                    "所选目录中没有找到支持的图像文件。\n"
                    "支持的格式：JPG, PNG, TIF, BMP"
                )
    
    def _save_image(self):
        """保存当前处理后的图像"""
        if not self.processor.has_image:
            QMessageBox.warning(self, "警告", "没有可保存的图像")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存图像", "",
            "PNG 图像 (*.png);;JPEG 图像 (*.jpg);;所有文件 (*.*)"
        )
        
        if file_path:
            pixmap = self.processor.get_pixmap(self._current_channel)
            if pixmap and pixmap.save(file_path):
                self.status_bar.showMessage(f"已保存: {file_path}")
            else:
                QMessageBox.warning(self, "错误", "保存图像失败")
    
    def _reset_zoom(self):
        """重置缩放"""
        self.image_viewer.reset_view()
    
    def _on_selection_changed(self, file_path: str, channel: str):
        """处理文件树选择变化"""
        # 记录当前视图状态
        old_center = self.image_viewer.get_current_center()
        old_scale = self.image_viewer.get_current_scale()
        
        # 切换文件时需要重新加载
        if file_path != self._current_file:
            if self.processor.load_image(file_path):
                self._current_file = file_path
                # 重置工具面板
                self.tool_panel.reset_all()
                # 重置视图
                self.image_viewer.set_pixmap(
                    self.processor.get_pixmap(channel),
                    reset_view=True
                )
            else:
                QMessageBox.warning(self, "错误", f"无法加载图像: {file_path}")
                return
        else:
            # 同一文件切换通道，保持视图状态
            self.image_viewer.set_pixmap(
                self.processor.get_pixmap(channel),
                reset_view=False
            )
        
        self._current_channel = channel
        self.status_bar.showMessage(
            f"当前: {os.path.basename(file_path)} - {channel.upper()}"
        )
    
    def _on_mouse_moved(self, x: int, y: int):
        """更新状态栏坐标"""
        w, h = self.processor.image_size
        if 0 <= x < w and 0 <= y < h:
            pixel_info = self.processor.get_channel_value(x, y, self._current_channel)
            self.status_bar.showMessage(f"X: {x}, Y: {y}  |  {pixel_info}")
        else:
            self.status_bar.showMessage("就绪")
    
    def _on_mouse_left(self):
        """鼠标离开图像区域"""
        if self._current_file:
            self.status_bar.showMessage(
                f"当前: {os.path.basename(self._current_file)} - {self._current_channel.upper()}"
            )
        else:
            self.status_bar.showMessage("就绪")
    
    def _on_wb_changed(self, r: float, g: float, b: float):
        """白平衡变化"""
        self.processor.set_white_balance(r, g, b)
        self._refresh_display()
    
    def _on_saturation_changed(self, factor: float):
        """饱和度变化"""
        self.processor.set_saturation(factor)
        self._refresh_display()
    
    def _auto_white_balance(self):
        """自动白平衡"""
        if not self.processor.has_image:
            return
        gains = self.processor.auto_white_balance()
        if gains:
            self.tool_panel.set_wb_gains(*gains)
            self._refresh_display()
            self.status_bar.showMessage(
                f"自动白平衡: R={gains[0]:.2f}, G={gains[1]:.2f}, B={gains[2]:.2f}"
            )
    
    def _reset_all_adjustments(self):
        """重置所有调整"""
        self.tool_panel.reset_all()
        self.processor.set_white_balance(1.0, 1.0, 1.0)
        self.processor.set_saturation(1.0)
        self._refresh_display()
        self.status_bar.showMessage("已重置所有调整")
    
    def _refresh_display(self):
        """刷新显示"""
        if self.processor.has_image:
            self.image_viewer.set_pixmap(
                self.processor.get_pixmap(self._current_channel),
                reset_view=False
            )
    
    def _on_mouse_moved(self, x: int, y: int):
        """鼠标移动回调"""
        # 更新状态栏坐标
        w, h = self.processor.image_size
        if 0 <= x < w and 0 <= y < h:
            # 只有在混合模式下才更新图表
            if self._blend_mode:
                self.blend_panel.update_spectral_chart(x, y)
                
            # 显示像素值
            # ... (这部分由ImageViewer内部处理，这里只做额外操作)
            pass

    def _on_alignment_done(self):
        """对齐完成回调"""
        self.status_bar.showMessage("图像对齐完成")
        # 如果覆盖了原文件，刷新当前显示
        if self._current_file:
            self.processor.load_image(self._current_file)
            self._refresh_display()

    
    def _on_blend_requested(self):
        """混合面板请求更新显示"""
        if self.blend_panel.has_layers():
            self._blend_mode = True
            pixmap = self.blend_panel.get_blended_pixmap()
            if pixmap:
                self.image_viewer.set_pixmap(pixmap, reset_view=False)
                self.status_bar.showMessage("混合预览已更新")
        else:
            self._blend_mode = False
    
    def _on_channel_gain_changed(self, channel: str, gain: float, offset: int):
        """通道增益变化"""
        self.processor.set_channel_gain(channel, gain, offset)
        self._refresh_display()
        self.status_bar.showMessage(
            f"{channel.upper()} 通道: 增益={gain:.2f}, 偏移={offset}"
        )
    
    def _on_auto_stretch(self):
        """自动拉伸直方图"""
        if not self.processor.has_image:
            return
        gains = self.processor.auto_stretch()
        if gains:
            # 更新UI显示
            for ch in ['r', 'g', 'b']:
                gain, offset = gains[ch]
                self.tool_panel.set_channel_gain(ch, gain, offset)
            self._refresh_display()
            self.status_bar.showMessage("已自动拉伸所有通道直方图")
    
    def _on_channel_gains_reset(self):
        """重置通道增益"""
        self.processor.reset_channel_gains()
        self._refresh_display()
        self.status_bar.showMessage("已重置通道增益")

    def _on_vegetation_display(self):
        """植被指数结果显示"""
        if self.vegetation_panel.has_result():
            pixmap = self.vegetation_panel.get_result_pixmap()
            if pixmap:
                self.image_viewer.set_pixmap(pixmap, reset_view=False)
                self.status_bar.showMessage("植被指数计算完成")
