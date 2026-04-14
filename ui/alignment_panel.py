"""
图像对齐面板UI
提供参考图像选择、批量对齐和结果预览功能
"""
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QListWidget,
    QListWidgetItem, QPushButton, QProgressBar, QLabel, QGroupBox,
    QCheckBox, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor

from core.image_aligner import ImageAligner


class AlignmentPanel(QWidget):
    """图像对齐控制面板"""
    
    # 信号：请求预览对齐结果
    preview_requested = pyqtSignal(str)  # aligned image path
    alignment_done = pyqtSignal()  # 对齐完成
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 对齐器
        self.aligner = ImageAligner()
        
        # 当前目录的图像列表
        self._image_files = []
        
        self._init_ui()
        self._connect_signals()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 参考图像选择
        ref_group = QGroupBox("参考图像")
        ref_layout = QVBoxLayout(ref_group)
        
        self.ref_combo = QComboBox()
        self.ref_combo.setPlaceholderText("选择参考图像...")
        ref_layout.addWidget(self.ref_combo)
        
        self.set_ref_btn = QPushButton("设为参考")
        self.set_ref_btn.setEnabled(False)
        ref_layout.addWidget(self.set_ref_btn)
        
        self.ref_label = QLabel("未设置参考图像")
        self.ref_label.setStyleSheet("color: gray; font-size: 11px;")
        ref_layout.addWidget(self.ref_label)
        
        layout.addWidget(ref_group)
        
        # 快捷操作
        quick_layout = QHBoxLayout()
        self.auto_match_btn = QPushButton("自动匹配五波段")
        self.auto_match_btn.setToolTip("自动识别并选择同组的 D, R, G, RE, NIR 图像")
        quick_layout.addWidget(self.auto_match_btn)
        layout.addLayout(quick_layout)
        
        # 待对齐图像列表
        list_group = QGroupBox("待对齐图像")
        list_layout = QVBoxLayout(list_group)
        
        # 全选按钮
        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton("全选")
        self.deselect_all_btn = QPushButton("取消全选")
        btn_row.addWidget(self.select_all_btn)
        btn_row.addWidget(self.deselect_all_btn)
        list_layout.addLayout(btn_row)
        
        # 图像列表
        self.image_list = QListWidget()
        self.image_list.setSelectionMode(QListWidget.MultiSelection)
        list_layout.addWidget(self.image_list)
        
        layout.addWidget(list_group)
        
        # 参数设置
        param_group = QGroupBox("参数设置")
        param_layout = QVBoxLayout(param_group)
        
        # 特征检测器
        det_layout = QHBoxLayout()
        det_layout.addWidget(QLabel("特征检测:"))
        self.detector_combo = QComboBox()
        self.detector_combo.addItems(["SIFT", "ORB"])
        det_layout.addWidget(self.detector_combo)
        param_layout.addLayout(det_layout)
        
        layout.addWidget(param_group)
        
        # 选项
        self.overwrite_check = QCheckBox("覆盖原文件")
        self.overwrite_check.setToolTip("对齐后直接覆盖原图像文件")
        layout.addWidget(self.overwrite_check)
        
        # 对齐按钮
        self.align_btn = QPushButton("🔄 执行对齐")
        self.align_btn.setEnabled(False)
        self.align_btn.setMinimumHeight(36)
        layout.addWidget(self.align_btn)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 状态标签
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        # 设置最小宽度
        self.setMinimumWidth(250)
    
    def _connect_signals(self):
        """连接信号"""
        self.ref_combo.currentIndexChanged.connect(self._on_ref_combo_changed)
        self.set_ref_btn.clicked.connect(self._on_set_reference)
        self.select_all_btn.clicked.connect(self._select_all)
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        self.align_btn.clicked.connect(self._on_align_clicked)
        self.image_list.itemSelectionChanged.connect(self._update_align_btn_state)
        
        # 新增信号连接
        self.auto_match_btn.clicked.connect(self._on_auto_match_clicked)
        self.detector_combo.currentTextChanged.connect(self._on_detector_changed)
        
        # 对齐器信号
        self.aligner.alignment_progress.connect(self._on_progress)
        self.aligner.alignment_completed.connect(self._on_item_aligned)
    
    def _on_detector_changed(self, text):
        """特征检测器变化"""
        self.aligner.set_feature_detector(text)
        
    def _on_auto_match_clicked(self):
        """自动匹配五波段图像"""
        if not self._image_files:
            return
            
        # 简单的后缀规则
        # D: RGB参考, R, G, RE, NIR
        suffix_map = {
            'D': ['d', 'rgb'],
            'R': ['r'],
            'G': ['g'],
            'RE': ['re'],
            'NIR': ['nir']
        }
        
        found_groups = {}
        
        # 遍历所有文件，尝试分组
        for path in self._image_files:
            filename = os.path.splitext(os.path.basename(path))[0]
            # 尝试分离后缀（假设是下划线分隔）
            parts = filename.rsplit('_', 1)
            if len(parts) != 2:
                continue
                
            base_name = parts[0]
            suffix = parts[1].upper()
            
            if base_name not in found_groups:
                found_groups[base_name] = {}
            
            # 检查后缀属于哪一类
            for key, val_list in suffix_map.items():
                if suffix.lower() in [v.lower() for v in val_list]:
                    found_groups[base_name][key] = path
                    break
        
        # 寻找包含完整或者大部分波段的组
        target_group = None
        for base_name, group in found_groups.items():
            if 'D' in group and len(group) >= 2:
                target_group = group
                break
        
        if target_group:
            # 设置参考图像 (D)
            ref_path = target_group['D']
            
            # 在下拉框中找到并选中
            index = self.ref_combo.findData(ref_path)
            if index >= 0:
                self.ref_combo.setCurrentIndex(index)
                self._on_set_reference()  # 触发设置
            
            # 选中其他图像
            self.image_list.clearSelection()
            for key, path in target_group.items():
                if key == 'D':
                    continue
                    
                # 在列表中找到并选中
                for i in range(self.image_list.count()):
                    item = self.image_list.item(i)
                    if item.data(Qt.UserRole) == path:
                        item.setSelected(True)
                        break
            
            count = len(self.image_list.selectedItems())
            self.status_label.setText(f"已自动选择 {count} 个待对齐图像")
            QMessageBox.information(self, "自动匹配", f"已匹配到组: {os.path.basename(ref_path).split('_')[0]}\n参考图像: D\n待对齐图像: {count} 个")
        else:
            QMessageBox.warning(self, "自动匹配", "未找到符合命名规则的图像组 (需要包含 _D, _R, _G 等后缀)")
    
    def load_images(self, image_files: list):
        """
        加载图像文件列表
        
        Args:
            image_files: 图像文件路径列表
        """
        self._image_files = image_files
        
        # 更新参考图像下拉框
        self.ref_combo.clear()
        for path in image_files:
            self.ref_combo.addItem(os.path.basename(path), path)
        
        # 更新图像列表
        self.image_list.clear()
        for path in image_files:
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.image_list.addItem(item)
        
        # 重置状态
        self.ref_label.setText("未设置参考图像")
        self.aligner.clear_cache()
        self._update_align_btn_state()
    
    def _on_ref_combo_changed(self, index):
        """参考图像下拉框变化"""
        self.set_ref_btn.setEnabled(index >= 0)
    
    def _on_set_reference(self):
        """设置参考图像"""
        index = self.ref_combo.currentIndex()
        if index < 0:
            return
            
        path = self.ref_combo.itemData(index)
        if self.aligner.set_reference(path):
            filename = os.path.basename(path)
            self.ref_label.setText(f"✓ {filename}")
            self.ref_label.setStyleSheet("color: green; font-size: 11px;")
            self._update_align_btn_state()
            self.status_label.setText(f"已设置参考图像: {filename}")
        else:
            self.ref_label.setText("设置失败")
            self.ref_label.setStyleSheet("color: red; font-size: 11px;")
    
    def _select_all(self):
        """全选"""
        self.image_list.selectAll()
    
    def _deselect_all(self):
        """取消全选"""
        self.image_list.clearSelection()
    
    def _update_align_btn_state(self):
        """更新对齐按钮状态"""
        has_ref = self.aligner.has_reference
        has_selection = len(self.image_list.selectedItems()) > 0
        self.align_btn.setEnabled(has_ref and has_selection)
    
    def _on_align_clicked(self):
        """执行对齐"""
        selected_items = self.image_list.selectedItems()
        if not selected_items:
            return
        
        # 获取选中的路径
        paths = [item.data(Qt.UserRole) for item in selected_items]
        
        # 显示进度条
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(paths))
        self.progress_bar.setValue(0)
        
        self.align_btn.setEnabled(False)
        self.status_label.setText("正在对齐...")
        
        # 执行对齐
        save_results = self.overwrite_check.isChecked()
        results = self.aligner.align_batch(paths, save_results=save_results)
        
        # 统计结果
        success_count = sum(1 for _, (_, success, _) in results.items() if success)
        
        self.progress_bar.setVisible(False)
        self.align_btn.setEnabled(True)
        self.status_label.setText(f"完成: {success_count}/{len(paths)} 成功")
        
        if save_results:
            QMessageBox.information(
                self, "对齐完成",
                f"成功对齐 {success_count}/{len(paths)} 张图像\n"
                f"已覆盖原文件"
            )
        
        self.alignment_done.emit()
    
    def _on_progress(self, current, total):
        """更新进度"""
        self.progress_bar.setValue(current)
    
    def _on_item_aligned(self, path, success, message):
        """单个图像对齐完成"""
        # 更新列表项状态
        for i in range(self.image_list.count()):
            item = self.image_list.item(i)
            if item.data(Qt.UserRole) == path:
                if success:
                    item.setForeground(QColor("green"))
                    item.setText(f"✓ {os.path.basename(path)}")
                else:
                    item.setForeground(QColor("red"))
                    item.setText(f"✗ {os.path.basename(path)}")
                break
    
    def get_aligned_image(self, path: str):
        """获取对齐后的图像"""
        return self.aligner.get_aligned_image(path)
