# align3d 三维配准算法流程

本文档描述 `align3d` 模块的完整算法流程：从标定、深度估计到逐像素重映射，以及质量门控与回退策略。

---

## 1. 问题背景

多光谱设备有多个镜头（如 RGB、570nm、650nm、730nm、850nm），镜头之间存在物理基线。

| 方法 | 假设 | 近景多深度场景 |
|------|------|----------------|
| 单应矩阵 Homography | 场景平面 或 相机纯旋转 | **失败**：前景/背景视差不同，一个 3×3 矩阵无法同时对齐 |
| 三维重建配准 | 已知（或估计）内参、相对位姿与深度 | **可行**：每个像素按自身深度做投影，视差随深度变化 |

核心思想：

1. 在参考相机坐标系下估计**深度图** \(Z(u,v)\)
2. 对每个目标波段，将参考像素 \((u,v,Z)\) 投影到目标相机，得到采样坐标
3. 用 `cv2.remap` 把目标图逐像素拉回参考视角

---

## 2. 总体流程

```
┌─────────────────────────────────────────────────────────────────┐
│                     align_batch_3d()                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ ① 加载图像 & 波段映射                                              │
│    reference + targets → {band: image}                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ ② 解析相机标定档案 (RigProfile)                                    │
│    有 rig_profile → 加载 checkerboard 标定                        │
│    无档案     → 现场自标定 (selfcalib)                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ ③ 多视图深度估计                                                   │
│    auto: checkerboard → plane_sweep / selfcalib → sgbm          │
│    输出: depth(H×W), mask(H×W), confidence                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ ④ 逐目标波段 Warp                                                  │
│    depth + K_ref/K_tgt + R|t → map_x/map_y → remap → 对齐图      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ ⑤ 质量门控 & 回退                                                   │
│    valid_ratio 过低 或 NCC(3D) < NCC(单应) → 回退 Homography      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ ⑥ 输出                                                             │
│    aligned/ 对齐图 + align3d/ 深度图、掩码、remap LUT 缓存         │
└─────────────────────────────────────────────────────────────────┘
```

对应代码入口：[`pipeline.py`](pipeline.py) 的 `align_batch_3d()`。

---

## 3. 阶段一：相机标定（RigProfile）

标定档案包含每个波段的：

- **内参** \(K\)（3×3）、畸变 `dist`
- **外参** \(R, t\)：相对参考相机的旋转与平移
- 标定方法标记：`checkerboard` 或 `selfcalib`

### 3.1 路径 A：棋盘格标定（推荐）

适用于刚性固定镜头、可做离线标定的情况。

```
多组同步标定板图像（15–30 组）
        │
        ▼
┌───────────────────────┐
│ 单相机标定              │  cv2.findChessboardCorners
│ calibrateCamera       │  → 各波段 K, dist
└───────────────────────┘
        │
        ▼
┌───────────────────────┐
│ 立体标定                │  cv2.stereoCalibrate
│ (参考相机 ↔ 各目标)     │  → R, t（相对位姿）
└───────────────────────┘
        │
        ▼
   rig_<name>.json
```

关键公式（平面诱导单应，后续平面扫描会用到）：

\[
H_j(d) = K_j \left(R_j - \frac{t_j n^\top}{d}\right) K_{\mathrm{ref}}^{-1}
\]

其中 \(d\) 为假设深度，\(n\) 为平面法向（默认 \([0,0,1]^\top\)，即平行于像平面的平面）。

### 3.2 路径 B：自标定（无标定板时自动启用）

```
参考图 + 目标图
        │
        ▼
CLAHE 预处理 + SIFT 特征匹配
        │
        ▼
cv2.findFundamentalMat (RANSAC) → F
        │
        ▼
E = Kᵀ F K
        │
        ▼
cv2.recoverPose → R, t（单位基线长度）
```

注意：

- \(K\) 由图像尺寸 + 配置项 `assumed_hfov_deg` 近似，畸变置零
- \(t\) 只有方向、尺度未知 → **不能**做联合绝对深度平面扫描，改走逐对 SGBM

---

## 4. 阶段二：跨光谱预处理

多光谱波段（尤其 NIR 与 RGB）灰度外观差异大，直接做像素匹配很脆。预处理在 [`preprocess.py`](preprocess.py)：

| 模式 | 做法 | 用途 |
|------|------|------|
| `clahe` | 灰度 + CLAHE 对比度均衡 | 基础匹配、自标定特征点 |
| `census` | CLAHE 后 Census 变换 | 平面扫描默认代价（对亮度单调变化鲁棒） |
| `zncc` | 零均值归一化互相关代价 | 可选稠密匹配 |
| `gradient` | Sobel 梯度幅值 | 强调边缘结构 |

Census Hamming 距离：对窗口内每个邻域像素与中心比较得到比特串，两幅图 XOR 后 popcount 作为代价。

---

## 5. 阶段三：深度估计

### 5.1 后端选择（`depth_backend`）

| 配置 | 行为 |
|------|------|
| `auto` | 标定方法为 checkerboard → `plane_sweep`；否则 → `sgbm` |
| `plane_sweep` | 多视图平面扫描 |
| `sgbm` | 立体校正 + StereoSGBM |
| `torch_stereo` | 可选深度学习立体（未装 torch 则回退 SGBM） |

### 5.2 平面扫描 Plane Sweep（标定路径主力）

适用于有度量尺度 \(R,t\) 的情况，并可聚合多个目标视图。

```
输入: 参考图, 多个目标图, RigProfile, [z_min, z_max], L 层
        │
        ▼
可选金字塔降采样（pyramid_levels）
        │
        ▼
逆深度均匀采样:
  inv_d ∈ [1/z_max, 1/z_min], 共 L 层
  d_i = 1 / inv_d_i
        │
        ▼
对每个深度层 d_i、每个目标视图 j:
  1. 计算平面诱导单应 H_j(d_i)
  2. 把目标图 warp 到参考视角
  3. 计算与参考图的代价图 C_j(d_i)
  4. 多视图取 min 聚合 → cost_volume[i]
        │
        ▼
Winner-Take-All: best_idx = argmin_i cost_volume
        │
        ▼
抛物线亚像素精化（邻层代价二次拟合）
        │
        ▼
引导滤波 / 双边滤波（边缘保持平滑）
        │
        ▼
上采样回原分辨率 + 代价阈值生成有效掩码
```

复杂度大致为 \(O(L \times N_{\mathrm{views}} \times H \times W)\)，通过金字塔与降低 `num_planes` 控制耗时。

### 5.3 SGBM 立体匹配（自标定路径主力）

各对基线尺度不一致，因此**逐对**处理，不依赖绝对深度：

```
对每个 (参考, 目标) 对:
  stereoRectify(K_ref, K_tgt, R, t)
        │
        ▼
initUndistortRectifyMap → 校正后左右图
        │
        ▼
CLAHE 预处理
        │
        ▼
StereoSGBM → 视差 disp
  （可选 ximgproc WLS 左右一致性滤波）
        │
        ▼
伪深度: Z ≈ (baseline × fx) / disp
        │
        ▼
多对结果加权平均 + 掩码合并
```

校正空间中的视差本身就是逐像素位移信息，后续 warp 仍走统一的深度投影接口。

---

## 6. 阶段四：深度驱动 Warp

对每个目标波段，将目标图像对齐到参考视角。

### 6.1 反投影与投影

对参考图每个像素 \((u, v)\) 及其深度 \(Z\)：

\[
\begin{aligned}
X &= (u - c_x) \cdot Z / f_x \\
Y &= (v - c_y) \cdot Z / f_y \\
P_{\mathrm{ref}} &= (X, Y, Z, 1)^\top
\end{aligned}
\]

变换到目标相机：

\[
P_{\mathrm{tgt}} = [R \mid t]\, P_{\mathrm{ref}}
\]

再投影到目标像平面：

\[
\begin{aligned}
u_t &= f_x' \cdot X_t / Z_t + c_x' \\
v_t &= f_y' \cdot Y_t / Z_t + c_y'
\end{aligned}
\]

得到 `map_x(u,v) = u_t`、`map_y(u,v) = v_t`。

无效条件（置为 -1）：

- \(Z \le 0\)
- \(Z_t \le 0\)（点在目标相机后方）
- \((u_t, v_t)\) 越界

### 6.2 重采样

```
aligned = cv2.remap(target, map_x, map_y, INTER_CUBIC)
```

含义：参考视角每个像素，从目标图的 \((u_t, v_t)\) 采样颜色。

空洞用 `cv2.inpaint` 填补；最终有效掩码 = remap 有效区域 ∩ 深度掩码。

### 6.3 LUT 缓存

`map_x` / `map_y` 可存为 `align3d/remap_<band>.npz`，同一标定下可复用，也为后续实时流预留加速路径。

---

## 7. 阶段五：质量门控与回退链

```
                    深度估计成功?
                         │
            ┌────────────┴────────────┐
            │ valid_ratio < 阈值       │ 否则
            │ (默认 0.3)               ▼
            │                   3D Warp 得到 aligned_3d
            │                          │
            │                   计算 NCC(ref, aligned_3d)
            │                          │
            │                   同时算 Homography 对齐
            │                   计算 NCC(ref, aligned_homo)
            │                          │
            │              NCC_3d < NCC_homo + margin ?
            │                    │            │
            │                   是            否
            ▼                    ▼            ▼
        回退单应              回退单应      采用 3D 结果
```

回退链优先级（实际执行）：

1. **标定 + plane_sweep**（最优）
2. **自标定 + SGBM**（无档案或 plane_sweep 失败）
3. **Homography**（有效像素不足，或 3D 的 NCC 不如单应）

每条路径都会在结果 `message` / `notes` 中写明实际使用的方法，避免静默失败。

NCC 评估：对两幅图做 CLAHE 后零均值归一化互相关（越高越好）。

---

## 8. 数据流与产物

```
uploads/
  calib/
    rig_<name>.json          ← 标定档案 (K, dist, R, t)
  {batch_id}/
    source/                  ← 原始多波段图
    aligned/                 ← 对齐结果（与现有 Homography 产物同构）
    align3d/
      depth.npy              ← 浮点深度
      depth_colormap.png     ← 伪彩色深度预览
      depth_mask.png         ← 有效掩码
      remap_<band>.npz     ← 重映射 LUT
      method.txt             ← 实际使用的方法与置信度
```

下游混合 / 植被指数等模块仍读取 `aligned/`，无需感知是 Homography 还是 3D 产生的。

---

## 9. 与单应矩阵路径的对比

| 步骤 | Homography | align3d |
|------|------------|---------|
| 几何模型 | 全局 3×3 矩阵 | 逐像素深度投影 |
| 特征 | SIFT/ORB + RANSAC | 稠密匹配（Census/ZNCC）或 SGBM |
| 近景多深度 | 失效 | 设计目标 |
| 标定需求 | 无 | 推荐棋盘格；无则自标定 |
| 计算量 | 低 | 中～高（与层数、分辨率相关） |
| 失败处理 | 特征不足则失败 | 可回退到 Homography |

---

## 10. 关键代码索引

| 步骤 | 文件 | 函数 |
|------|------|------|
| 主编排 | `pipeline.py` | `align_batch_3d`, `preview_depth` |
| 棋盘格标定 | `calibration/checkerboard.py` | `build_profile_from_checkerboard` |
| 自标定 | `calibration/selfcalib.py` | `build_profile_from_images` |
| 平面扫描 | `depth/plane_sweep.py` | `PlaneSweepEstimator.estimate` |
| SGBM | `depth/sgbm.py` | `SGBMEstimator.estimate` |
| 预处理 | `preprocess.py` | `preprocess_for_matching`, `census_transform` |
| Warp | `warp.py` | `project_ref_to_target`, `align_target_with_depth` |
| 配置 | `config.py` / `align3d.json` | `load_config`, `Align3DConfig` |

---

## 11. 使用建议（算法侧）

1. **近景任务务必做棋盘格标定**，自标定无法校正明显畸变，且尺度不统一。
2. `depth_min` / `depth_max` 按真实拍摄距离设置，范围过宽会稀释平面扫描层分辨率。
3. 跨光谱优先 `cost_method: census`；纹理极弱时可试 `gradient`。
4. 大图先用较小 `num_planes`（如 16）预览深度，确认合理再提高层数。
5. 先用 `/api/align3d/preview-depth` 看深度伪彩色，再跑全量对齐。
