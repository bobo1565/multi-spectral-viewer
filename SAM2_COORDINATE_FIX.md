# SAM2 坐标对齐修复说明

## 问题描述
1. 鼠标点击坐标传递到 SAM2 服务时出现偏差
2. SAM2 返回的掩码图像位置没有正确对齐到当前视图

## 修复内容

### 前端修复

#### 1. SAM2ClickCanvas.tsx - 掩码显示对齐
**问题**: 掩码图片使用了不正确的变换方式，导致显示位置偏移

**修复**:
```tsx
// 修改前
style={{
    transform: `translate(${offsetX}px, ${offsetY}px) scale(${scale})`,
    width: imageWidth,
    height: imageHeight,
}}

// 修改后
style={{
    position: 'absolute',
    left: 0,
    top: 0,
    width: '100%',
    height: '100%',
    transform: `translate(${offsetX}px, ${offsetY}px) scale(${scale})`,
    transformOrigin: '0 0',
}}
```

#### 2. SAM2ClickCanvas.css - 容器样式
**问题**: 容器边界定义不够简洁

**修复**:
```css
.sam2-overlay {
    position: absolute;
    inset: 0;  /* 使用 inset 替代 top/left/right/bottom */
    z-index: 20;
    cursor: crosshair;
}
```

#### 3. 添加调试日志
在关键位置添加 console.log 输出：
- 鼠标点击时的屏幕坐标和图像坐标转换
- 坐标超出范围时的警告

### 后端修复

#### 1. alignment.py - SAM2 预览接口
添加调试信息：
```python
print(f"[SAM2Preview] 接收到的坐标：point_x={request.point_x}, point_y={request.point_y}")
print(f"[SAM2Preview] 图像信息：{image.width}x{image.height}, 路径：{image_path}")
print(f"[SAM2Preview] 返回掩码信息：area={best_mask['area']}, bbox={best_mask['bbox']}")
```

#### 2. sam2_service/app/main.py - SAM2 分割服务
添加调试信息：
```python
print(f"[SAM2] 接收到的点坐标：{points}, 图像尺寸：{img_w}x{img_h}")
```

#### 3. image_aligner_service.py - 掩码尺寸对齐
**问题**: 参考图和目标图的掩码尺寸可能与图像尺寸不一致

**修复**:
```python
# 确保掩码尺寸与图像尺寸匹配
if ref_mask.shape[:2] != ref_img.shape[:2]:
    ref_mask = cv2.resize(ref_mask, (ref_img.shape[1], ref_img.shape[0]))

if tgt_mask.shape[:2] != tgt_img.shape[:2]:
    tgt_mask = cv2.resize(tgt_mask, (tgt_img.shape[1], tgt_img.shape[0]))

# 如果参考图和目标图尺寸不同，需要调整目标图和掩码
if (h_ref, w_ref) != (h_tgt, w_tgt):
    tgt_img_aligned = cv2.resize(tgt_img, (w_ref, h_ref))
    tgt_mask_aligned = cv2.resize(tgt_mask, (w_ref, h_ref), interpolation=cv2.INTER_NEAREST)
```

## 坐标转换流程

### 前端坐标转换
```
屏幕坐标 (mx, my) 
  ↓
图像坐标 (imgX, imgY) = ((mx - offsetX) / scale, (my - offsetY) / scale)
  ↓
传递给后端 API
```

### 后端处理
```
接收图像坐标 (point_x, point_y)
  ↓
SAM2 分割服务处理
  ↓
返回掩码 (尺寸 = 原始图像尺寸)
```

### 前端显示
```
掩码图像 (原始尺寸)
  ↓
应用变换：translate(offsetX, offsetY) + scale(scale)
  ↓
显示在视图上（与原图完全对齐）
```

## 验证步骤

### 1. 检查浏览器控制台
打开浏览器开发者工具 (F12)，查看 Console 标签：
- 点击时应输出：`[SAM2Click] 鼠标点击：屏幕=(xxx, xxx), 图像=(xxx, xxx), scale=xxx, offset=(xxx, xxx)`
- 验证图像坐标是否在合理范围内

### 2. 检查后端日志
查看后端控制台输出：
- `[SAM2Preview] 接收到的坐标：point_x=xxx, point_y=xxx`
- `[SAM2Preview] 图像信息：1920x1080, 路径：xxx`
- `[SAM2Preview] 返回掩码信息：area=xxx, bbox=[x1, y1, x2, y2]`

### 3. 检查 SAM2 服务日志
查看 SAM2 服务控制台输出：
- `[SAM2] 接收到的点坐标：[[x, y]], 图像尺寸：1920x1080`

### 4. 视觉验证
- 点击图像上的某个特征点
- 观察绿色掩码是否准确覆盖所选物体
- 掩码边缘应该与物体边缘完全对齐

## 常见问题排查

### 问题 1: 掩码位置偏移
**可能原因**: 
- 容器尺寸不一致
- transform 原点设置错误

**检查**:
- 确保 SAM2ClickCanvas 的父容器设置了 `position: relative`
- 验证 transformOrigin 设置为 `'0 0'`

### 问题 2: 坐标传递错误
**可能原因**:
- scale 或 offset 值不正确
- 容器边界计算错误

**检查**:
- 查看浏览器控制台的坐标转换日志
- 验证 viewerTransform 状态是否正确更新

### 问题 3: 掩码尺寸不匹配
**可能原因**:
- 多波段图像尺寸不一致
- 掩码 resize 时插值方法不当

**检查**:
- 查看后端日志中的图像和掩码尺寸信息
- 确保使用 `cv2.INTER_NEAREST` 进行掩码 resize

## 测试用例

### 测试 1: 不同缩放比例
1. 放大图像 (scale > 1)
2. 点击物体
3. 验证掩码对齐

### 测试 2: 不同偏移位置
1. 拖拽图像到不同位置
2. 点击物体
3. 验证掩码对齐

### 测试 3: 不同图像尺寸
1. 使用不同尺寸的图像
2. 点击物体
3. 验证掩码对齐

## 文件修改清单

### 前端文件
- `frontend/src/components/SAM2ClickCanvas.tsx` - 掩码显示和坐标转换
- `frontend/src/components/SAM2ClickCanvas.css` - 样式优化

### 后端文件
- `backend/app/api/routes/alignment.py` - 添加调试日志
- `backend/app/core/image_aligner_service.py` - 掩码尺寸对齐
- `sam2_service/app/main.py` - 添加调试日志

### 测试文件
- `test_sam2_coords.py` - 坐标转换测试脚本

## 下一步优化建议

1. **性能优化**: 缓存 SAM2 分割结果，避免重复请求
2. **用户体验**: 添加掩码透明度调节滑块
3. **错误处理**: 增强坐标范围验证和错误提示
4. **功能增强**: 支持多点提示分割
