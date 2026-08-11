# align3d — 三维重建多镜头对齐模块

独立工具包，用于多光谱多镜头系统的**逐像素深度驱动配准**，解决单应矩阵在近景多深度场景下的对齐失败问题。

算法流程详见 **[ALGORITHM.md](ALGORITHM.md)**（标定 → 深度估计 → Warp → 质量门控）。

## 为什么需要 align3d

单应矩阵假设场景为平面或相机纯旋转。多镜头设备存在物理基线，近景时不同深度物体视差不同，单一 3×3 矩阵无法同时配准前景与背景。

align3d 流程：

1. 获取各镜头内参与相对位姿（棋盘格标定 或 自标定）
2. 多视图深度估计（平面扫描 / SGBM）
3. 按深度逐像素重映射到参考视角
4. 质量门控，必要时回退到单应矩阵

## 目录结构

```
align3d/
  pipeline.py          # 主编排 + 回退链
  warp.py              # 深度驱动 remap
  calibration/         # 棋盘格标定 + 自标定
  depth/               # plane_sweep / sgbm / torch_stereo(可选)
  cli.py               # 命令行工具
```

## 快速开始

### 命令行

```bash
cd backend

# 从批次图像对齐（自标定）
python -m align3d align \
  -r test1.jpg \
  -t test2.jpg \
  --bands rgb,570nm \
  -o ./aligned_output \
  --debug

# 深度预览
python -m align3d preview -r test1.jpg -t test2.jpg -o depth.png

# 棋盘格标定
python -m align3d calib \
  --bands rgb,570nm,650nm,730nm,850nm \
  --dirs ./calib/rgb,./calib/570,./calib/650,./calib/730,./calib/850 \
  --reference-band rgb \
  --name my_rig
```

### API 接入

在现有对齐接口中选择 `align_mode: "reconstruction_3d"`：

```json
POST /api/alignment/batch-align
{
  "batch_id": "...",
  "align_mode": "reconstruction_3d",
  "align3d_params": {
    "rig_profile": "my_rig",
    "depth_min": 0.5,
    "depth_max": 20,
    "num_planes": 32,
    "depth_backend": "auto",
    "fallback_to_homography": true
  }
}
```

独立 align3d API：

| 端点 | 说明 |
|------|------|
| `GET/PUT /api/align3d/config` | 默认参数热加载 |
| `GET/DELETE /api/align3d/profiles` | 标定档案管理 |
| `POST /api/align3d/profiles/checkerboard` | 上传标定板图像建档案 |
| `POST /api/align3d/profiles/selfcalib` | 从批次 source 图自标定 |
| `POST /api/align3d/preview-depth` | 深度图预览 |

## 标定流程（推荐）

1. 打印 9×6 棋盘格（方格 25mm）
2. 5 镜头同步拍摄 15–30 组不同角度/距离的标定板照片
3. 通过前端「标定」按钮或 CLI `calib` 创建 `uploads/calib/rig_<name>.json`
4. 对齐时选择该档案

## 参数调优

| 参数 | 默认 | 说明 |
|------|------|------|
| `depth_min` / `depth_max` | 0.5 / 20 m | 场景深度范围，按实际距离调整 |
| `num_planes` | 32 | 平面扫描层数，越大越精细但更慢 |
| `depth_backend` | auto | 有标定→plane_sweep，无标定→sgbm |
| `cost_method` | census | 跨光谱匹配推荐 census |
| `fallback_to_homography` | true | 3D 失败时回退单应 |
| `min_valid_ratio` | 0.3 | 有效深度像素比例阈值 |

## 产物

- `uploads/{batch_id}/aligned/` — 对齐结果（与现有流程相同）
- `uploads/{batch_id}/align3d/` — 深度图、掩码、remap LUT 缓存
- `uploads/calib/rig_*.json` — 标定档案

## 可选依赖

```bash
pip install -r requirements-align3d-optional.txt
```

安装后可启用 `depth_backend: torch_stereo`（当前为 SGBM 占位，可扩展 RAFT-Stereo 等模型）。

## 测试

```bash
cd backend
.venv/bin/python -m pytest align3d/tests/ -v
```

## 限制

- 无标定路径无法校正明显镜头畸变，近景任务强烈建议棋盘格标定
- 跨光谱稠密匹配依赖 census/梯度代价 + 多视图聚合
- 平面扫描计算量 O(层数 × 视图数 × 像素)，大图建议降低 `num_planes` 或使用金字塔
