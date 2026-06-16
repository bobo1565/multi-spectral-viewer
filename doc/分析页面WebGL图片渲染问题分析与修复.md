# 分析页面 WebGL 图片渲染问题分析与修复

## 背景

多光谱图像分析系统的分析页面切换到类似 WebGL 的渲染方式后，选择图像时页面无法正常显示图片，尤其是 TIFF 波段图像。前端界面能正常加载批次树和工具面板，但中间图像查看区域长期保持深色背景或空状态。

## 问题现象

1. 打开 `http://localhost:3000` 后，分析页可以加载批次列表。
2. 展开批次并选择 TIFF 波段图像后，标题栏会显示已选中的文件名和尺寸信息，但画面区域没有图像内容。
3. WebGL canvas 在问题状态下仍保持浏览器默认内部尺寸 `300 x 150`，没有同步到实际容器尺寸。
4. 部分 TIFF 图像在前端被当成普通 `<img>` 资源加载，浏览器无法直接解码 TIFF，导致纹理上传失败或无法显示。

## 根因分析

### 1. WebGL 初始化时机错误

`WebGLImageViewer` 在没有选中图片时会提前返回空状态占位内容，此时组件内没有 `<canvas>` 元素。初始化 WebGL 的 `useEffect` 在首次渲染时已经执行过，但由于找不到 canvas 直接返回。

后续选择图片后，canvas 才真正出现在 DOM 中，但原来的初始化 effect 不会再次执行，导致：

- WebGL context 没有创建；
- shader/program 没有初始化；
- canvas 内部尺寸仍为默认 `300 x 150`；
- 图像数据即使请求成功，也无法被正确绘制。

### 2. TIFF 默认通道选择不正确

点击波段节点时，前端默认使用 `rgb` 通道。对于 `.tif/.tiff` 文件，这会走普通图片加载路径，而浏览器不能直接作为 `<img>` 解码 TIFF 文件。

因此，TIFF 波段即使后端数据存在，也会因为前端加载路径错误而无法渲染。

### 3. WebGL 1 shader 兼容性问题

原 fragment shader 在循环中动态索引 `sampler2D` 数组：

```glsl
for (int i = 0; i < MAX_LAYERS; i++) {
    vec4 texColor = texture2D(u_textures[i], v_texCoord);
}
```

这在 WebGL 1 中兼容性不稳定，部分浏览器/驱动会导致 shader 编译失败或渲染异常。

### 4. 后端按 image_id 查找文件路径不完整

`/api/images/{image_id}`、`/api/images/{image_id}/tiff-preview`、`/api/images/{image_id}/tiff-data` 原先主要依赖 `uploads/original` 下的文件命名规则查找。

批次图像、对齐图像、生成图像可能位于不同目录，数据库中已经保存了真实 `filepath`，但接口没有优先使用该路径，导致部分图像或 TIFF 数据接口可能返回 404。

## 修复内容

### 前端修复

#### `frontend/src/components/WebGLImageViewer.tsx`

1. 增加 `hasRenderableSource`，当 `image` 或 `blendedUrl` 从空变为有值时重新执行 WebGL 初始化。
2. 初始化 effect 依赖 `hasRenderableSource`，确保 canvas 首次出现后能创建 WebGL context。
3. TIFF 图像在 `channel === 'tiff'` 时走 `/api/images/{id}/tiff-data`。
4. TIFF 图像即使选择了非 `tiff` 子通道，也回退到 `/api/images/{id}/tiff-preview`，避免浏览器直接加载 TIFF。
5. 对浮点纹理增加 `OES_texture_float_linear` 检测；缺少扩展时使用 `NEAREST` 过滤，避免纹理不完整导致黑屏。
6. 增加 `u_channelMode` uniform，用于 RGB 图片的 R/G/B 灰度通道显示。

#### `frontend/src/webgl/shaders.ts`

1. 将 sampler 数组动态索引改为显式展开采样：

```glsl
accumulateLayer(texture2D(u_textures[0], v_texCoord), ...);
accumulateLayer(texture2D(u_textures[1], v_texCoord), ...);
accumulateLayer(texture2D(u_textures[2], v_texCoord), ...);
accumulateLayer(texture2D(u_textures[3], v_texCoord), ...);
```

2. 增加 `u_channelMode`，支持 RGB 图片的单通道灰度/色带显示。
3. 恢复 `hot` 色带的 shader 映射。

#### `frontend/src/webgl/types.ts`

将 `hot` 色带映射到 shader 中新增的编号 `5`。

#### `frontend/src/App.tsx`

1. 新增 `_isTiffImage` 和 `_defaultChannelForImage`。
2. `.tif/.tiff` 图像默认通道设置为 `tiff`。
3. TIFF 图像节点增加 `TIFF 灰度` 子节点。
4. 点击批次、Source/Aligned 文件夹、波段节点、Generated 图像时，都根据文件类型自动选择默认通道。
5. 分析页中间查看器切换为 `WebGLImageViewer`。

### 后端修复

#### `backend/app/api/routes/images.py`

1. 新增 `_resolve_image_path(image_id, db)`。
2. 图像读取接口优先使用数据库中的真实 `filepath`。
3. 保留旧版 `uploads/original` 查找逻辑作为兼容回退。
4. `/api/images/` 列表 URL 优先根据真实文件路径构建 `/uploads/...` URL。
5. `tiff-preview` 和 `tiff-data` 接口统一使用真实文件路径读取图像。

## 验证记录

### 静态检查

```bash
cd frontend
npm run build
```

结果：通过。

```bash
python -m py_compile backend/app/api/routes/images.py
```

结果：通过。

### 浏览器验证

验证环境：

- 前端：`http://localhost:3000`
- 后端：`http://localhost:8000`
- 页面：分析页

验证步骤：

1. 打开分析页。
2. 展开 `0528 -> Source`。
3. 直接点击 `570nm 波段(pipe0_ptz000_560nm_16h44m27s.tiff)`。
4. 观察中间 WebGL 查看器。
5. 点击放大按钮验证交互。

验证结果：

1. TIFF 图像正常显示为灰度图。
2. canvas 内部尺寸从默认 `300 x 150` 变为实际容器尺寸 `636 x 546`。
3. 标题栏显示 `TIFF 灰度`。
4. 初始适配比例显示为 `22%`。
5. 点击放大后比例更新到 `27%`。
6. 浏览器控制台无相关 error/warn。

## 结论

本次问题不是单一图片路径问题，而是 WebGL 初始化时机、TIFF 加载策略、shader 兼容性和后端文件路径解析共同导致的渲染失败。

修复后，分析页面可以直接选择 TIFF 波段并通过 WebGL 正常渲染；普通图片、TIFF 预览、TIFF 原始数据渲染和缩放交互均具备正确路径。
