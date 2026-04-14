import cv2
import numpy as np


# ─────────────────────────────────────────────
#  辅助：CLAHE 预处理（用于跨波段特征匹配）
# ─────────────────────────────────────────────
def preprocess_for_matching(img):
    """
    多光谱配准专用预处理：转灰度 + CLAHE 对比度均衡化。
    目的：缩小 RGB 与 NIR/RE 等波段之间的亮度/纹理差异，
    使 SIFT 描述子更具跨波段可比性。
    """
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


# ─────────────────────────────────────────────
#  辅助：ECC 二次精配准
# ─────────────────────────────────────────────
def refine_with_ecc(img1_gray, img2_gray, H_init, max_iter=200, eps=1e-7):
    """
    用 ECC (Enhanced Correlation Coefficient) 算法对初始单应矩阵做亚像素级精化。
    配准精度可从像素级提升至亚像素级。
    若 ECC 迭代失败（纹理不足等），则原样返回 H_init。
    """
    try:
        warp_mode = cv2.MOTION_HOMOGRAPHY
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, max_iter, eps)
        _, H_refined = cv2.findTransformECC(
            img1_gray.astype(np.float32),
            img2_gray.astype(np.float32),
            H_init.astype(np.float32),
            warp_mode,
            criteria,
            inputMask=None,
            gaussFiltSize=5
        )
        return H_refined
    except cv2.error as e:
        print(f"[ECC] 精化失败，保留 RANSAC 结果: {e}")
        return H_init


# ─────────────────────────────────────────────
#  ROI 计算
# ─────────────────────────────────────────────
def get_roi_from_config(img_width, img_height, roi_config):
    """根据比例配置计算 ROI 像素坐标"""
    roi_x = int(img_width * roi_config['roi_x_ratio'])
    roi_y = int(img_height * roi_config['roi_y_ratio'])
    roi_w = int(img_width * roi_config['roi_width_ratio'])
    roi_h = int(img_height * roi_config['roi_height_ratio'])

    roi_x = max(0, min(roi_x, img_width - 1))
    roi_y = max(0, min(roi_y, img_height - 1))
    roi_w = max(1, min(roi_w, img_width - roi_x))
    roi_h = max(1, min(roi_h, img_height - roi_y))

    return roi_x, roi_y, roi_w, roi_h


# ─────────────────────────────────────────────
#  有效区域检测（鲁棒版：百分位数边界）
# ─────────────────────────────────────────────
def find_valid_region(img, threshold=10, percentile=1):
    """
    检测图像中的有效区域（非黑边区域）。
    改进：使用百分位数而非极值，避免单个噪声点扩大边界。
    percentile=1 表示忽略最外侧 1% 的极端坐标。
    """
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

    mask = gray > threshold
    coords = np.column_stack(np.where(mask))
    if len(coords) == 0:
        return None

    y_min = int(np.percentile(coords[:, 0], percentile))
    x_min = int(np.percentile(coords[:, 1], percentile))
    y_max = int(np.percentile(coords[:, 0], 100 - percentile))
    x_max = int(np.percentile(coords[:, 1], 100 - percentile))

    return (x_min, y_min, x_max, y_max)


# ─────────────────────────────────────────────
#  公共区域计算
# ─────────────────────────────────────────────
def calculate_common_region(regions):
    """计算多个有效区域的交集"""
    if not regions or any(r is None for r in regions):
        return None

    x_min = max(r[0] for r in regions)
    y_min = max(r[1] for r in regions)
    x_max = min(r[2] for r in regions)
    y_max = min(r[3] for r in regions)

    if x_min >= x_max or y_min >= y_max:
        return None

    return (x_min, y_min, x_max, y_max)


# ─────────────────────────────────────────────
#  图像裁剪
# ─────────────────────────────────────────────
def crop_image(img, region):
    """根据区域裁剪图像"""
    if region is None or img is None:
        return img

    x_min, y_min, x_max, y_max = region
    return img[y_min:y_max, x_min:x_max]


# ─────────────────────────────────────────────
#  核心配准函数
# ─────────────────────────────────────────────
def align_images(img1_color, img2_color, roi_config1=None, roi_config2=None,
                 feature_detector_type='SIFT',
                 ratio_test_thresh=0.70, min_match_count=10,
                 use_ecc=False, min_inlier_ratio=0.15, min_inlier_count=50):
    """
    将 img2_color 配准到 img1_color 的坐标系。

    改进清单：
    1. CLAHE 预处理 — 缩小跨波段亮度差，提升描述子可比性
    2. ratio_test_thresh 0.75→0.65 — 减少模糊匹配
    3. RANSAC reprojThresh 2.0→1.0 + 内点比例验证 — 更严格的几何约束
    4. ECC 二次精配准 — 提供亚像素级精度
    """
    if img1_color is None or img2_color is None:
        return None

    h1, w1 = img1_color.shape[:2]
    h2, w2 = img2_color.shape[:2]

    if not roi_config1 or not roi_config2:
        raise ValueError("必须提供有效的 ROI 配置")

    # 计算 ROI 掩码
    roi_x1, roi_y1, roi_w1, roi_h1 = get_roi_from_config(w1, h1, roi_config1)
    roi_x2, roi_y2, roi_w2, roi_h2 = get_roi_from_config(w2, h2, roi_config2)

    mask1 = np.zeros((h1, w1), dtype=np.uint8)
    mask1[roi_y1:roi_y1 + roi_h1, roi_x1:roi_x1 + roi_w1] = 255
    mask2 = np.zeros((h2, w2), dtype=np.uint8)
    mask2[roi_y2:roi_y2 + roi_h2, roi_x2:roi_x2 + roi_w2] = 255

    # ── 改进1：CLAHE 预处理 ──────────────────────
    img1_gray = preprocess_for_matching(img1_color)
    img2_gray = preprocess_for_matching(img2_color)

    # 特征检测器初始化
    detector = None
    if feature_detector_type == 'SIFT':
        try:
            detector = cv2.SIFT_create(nfeatures=0, contrastThreshold=0.03)
        except Exception:
            if hasattr(cv2, 'xfeatures2d'):
                detector = cv2.xfeatures2d.SIFT_create()
    elif feature_detector_type == 'ORB':
        detector = cv2.ORB_create(nfeatures=3000)

    if detector is None:
        print(f"[AlignImages] 无法创建特征检测器: {feature_detector_type}")
        return None

    kp1, des1 = detector.detectAndCompute(img1_gray, mask1)
    kp2, des2 = detector.detectAndCompute(img2_gray, mask2)

    if des1 is None or des2 is None or len(kp1) < min_match_count or len(kp2) < min_match_count:
        print(f"[AlignImages] 特征点不足: img1={len(kp1) if kp1 else 0}, img2={len(kp2) if kp2 else 0}")
        return None

    # 特征匹配
    norm_type = cv2.NORM_L2 if feature_detector_type == 'SIFT' else cv2.NORM_HAMMING
    bf = cv2.BFMatcher(norm_type, crossCheck=False)
    matches = bf.knnMatch(des1, des2, k=2)

    # ── 改进2：更严格的 Lowe 比率测试（0.65）────
    good_matches = []
    for m_n in matches:
        if len(m_n) == 2:
            m, n = m_n
            if m.distance < ratio_test_thresh * n.distance:
                good_matches.append(m)

    if len(good_matches) < min_match_count:
        print(f"[AlignImages] 有效匹配点不足: {len(good_matches)}/{min_match_count}")
        return None

    src_pts = np.array([kp1[m.queryIdx].pt for m in good_matches], dtype=np.float32).reshape(-1, 1, 2)
    dst_pts = np.array([kp2[m.trainIdx].pt for m in good_matches], dtype=np.float32).reshape(-1, 1, 2)

    # ── 改进3：RANSAC 阈值 2.0→1.0 + 内点比例验证 ──
    H, mask_homography = cv2.findHomography(dst_pts, src_pts, cv2.RANSAC, 1.0)

    if H is None:
        print("[AlignImages] 无法计算单应矩阵")
        return None

    inlier_count = int(mask_homography.sum()) if mask_homography is not None else 0
    inlier_ratio = inlier_count / len(good_matches) if len(good_matches) > 0 else 0
    print(f"[AlignImages] 内点数: {inlier_count}/{len(good_matches)}, 内点比例: {inlier_ratio:.2%}")

    # 放宽条件：如果比例达到 15%，或者绝对内点数量超过 50 个（说明绝对匹配点足够多），都算作可以接受
    if inlier_ratio < min_inlier_ratio and inlier_count < min_inlier_count:
        print(f"[AlignImages] 配准质量不可靠：内点比例过低 ({inlier_ratio:.2%} < {min_inlier_ratio:.0%}) 且绝对内点数不足 ({inlier_count} < {min_inlier_count})")
        return None

    # ── 改进4：ECC 二次精配准（亚像素级）──────────
    if use_ecc:
        H = refine_with_ecc(img1_gray, img2_gray, H)

    aligned_img2 = cv2.warpPerspective(img2_color, H, (w1, h1))
    return aligned_img2


# ─────────────────────────────────────────────
#  稠密光流配准（逐像素级）
# ─────────────────────────────────────────────
def align_images_optical_flow(img1_color, img2_color, roi_config1=None, roi_config2=None,
                               feature_detector_type='SIFT',
                               ratio_test_thresh=0.70, min_match_count=10,
                               min_inlier_ratio=0.15, min_inlier_count=50):
    """
    两阶段配准：
      阶段1 — Homography 粗对齐（消除大范围平移/旋转/缩放）
      阶段2 — Farneback 稠密光流精细补偿（处理因深度差异导致的逐像素局部视差）

    适用于多目相机、视差明显、场景深度不均匀的情况。
    """
    if img1_color is None or img2_color is None:
        return None

    h1, w1 = img1_color.shape[:2]

    # ── 阶段 1：Homography 粗对齐 ──────────────────
    #    复用现有 align_images，先消除大范围偏移
    coarse_aligned = align_images(
        img1_color, img2_color,
        roi_config1=roi_config1,
        roi_config2=roi_config2,
        feature_detector_type=feature_detector_type,
        ratio_test_thresh=ratio_test_thresh,
        min_match_count=min_match_count,
        use_ecc=False,
        min_inlier_ratio=min_inlier_ratio,
        min_inlier_count=min_inlier_count
    )

    if coarse_aligned is None:
        print("[OpticalFlow] Homography 粗对齐失败，无法继续光流精配")
        return None

    # ── 阶段 2：Farneback 稠密光流 ──────────────────
    #    在粗对齐的基础上计算残余位移场
    ref_gray = preprocess_for_matching(img1_color)
    aligned_gray = preprocess_for_matching(coarse_aligned)

    print("[OpticalFlow] 计算稠密光流场...")
    flow = cv2.calcOpticalFlowFarneback(
        aligned_gray,   # prev (已粗对齐的目标图)
        ref_gray,        # next (参考图)
        flow=None,
        pyr_scale=0.5,   # 金字塔缩放比
        levels=5,        # 金字塔层数
        winsize=15,      # 窗口大小
        iterations=5,    # 每层迭代次数
        poly_n=7,        # 多项式展开邻域
        poly_sigma=1.5,  # 高斯标准差
        flags=0
    )

    # 构建 remap 坐标网格
    h, w = coarse_aligned.shape[:2]
    map_x = np.arange(w, dtype=np.float32)[np.newaxis, :].repeat(h, axis=0)
    map_y = np.arange(h, dtype=np.float32)[:, np.newaxis].repeat(w, axis=1)

    # 加上光流位移
    map_x += flow[:, :, 0]
    map_y += flow[:, :, 1]

    # 应用 remap
    refined = cv2.remap(coarse_aligned, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

    # 计算光流统计信息
    flow_mag = np.sqrt(flow[:, :, 0] ** 2 + flow[:, :, 1] ** 2)
    print(f"[OpticalFlow] 光流统计 — 平均位移: {flow_mag.mean():.2f}px, "
          f"最大位移: {flow_mag.max():.2f}px, "
          f"中位数: {np.median(flow_mag):.2f}px")

    return refined


# ─────────────────────────────────────────────
#  基于掩码的配准（SAM2 物体分割驱动）
# ─────────────────────────────────────────────
def align_images_with_mask(img1_color, img2_color, mask1, mask2,
                           feature_detector_type='SIFT',
                           ratio_test_thresh=0.70, min_match_count=10,
                           use_ecc=False, min_inlier_ratio=0.15, min_inlier_count=50):
    """
    基于物体掩码的配准：只在掩码区域提取特征点。

    与 align_images() 的区别：
    - align_images() 使用矩形 ROI 作为特征提取区域
    - 本函数使用任意形状的二值掩码（由 SAM2 分割生成）

    参数:
        mask1, mask2: np.ndarray (H, W), 值为 0 或 255 的二值掩码
    """
    if img1_color is None or img2_color is None:
        return None
    if mask1 is None or mask2 is None:
        print("[AlignMask] 掩码为空，回退到全图配准")
        # 使用全图掩码
        h1, w1 = img1_color.shape[:2]
        h2, w2 = img2_color.shape[:2]
        mask1 = np.ones((h1, w1), dtype=np.uint8) * 255
        mask2 = np.ones((h2, w2), dtype=np.uint8) * 255

    h1, w1 = img1_color.shape[:2]

    # ── CLAHE 预处理 ──────────────────────────────
    img1_gray = preprocess_for_matching(img1_color)
    img2_gray = preprocess_for_matching(img2_color)

    # 确保掩码是 uint8 且大小匹配
    if mask1.shape[:2] != img1_gray.shape[:2]:
        mask1 = cv2.resize(mask1, (w1, h1), interpolation=cv2.INTER_NEAREST)
    if mask2.shape[:2] != img2_gray.shape[:2]:
        h2, w2 = img2_color.shape[:2]
        mask2 = cv2.resize(mask2, (w2, h2), interpolation=cv2.INTER_NEAREST)

    mask1 = mask1.astype(np.uint8)
    mask2 = mask2.astype(np.uint8)

    # 特征检测器初始化
    detector = None
    if feature_detector_type == 'SIFT':
        try:
            detector = cv2.SIFT_create(nfeatures=0, contrastThreshold=0.03)
        except Exception:
            if hasattr(cv2, 'xfeatures2d'):
                detector = cv2.xfeatures2d.SIFT_create()
    elif feature_detector_type == 'ORB':
        detector = cv2.ORB_create(nfeatures=3000)

    if detector is None:
        print(f"[AlignMask] 无法创建特征检测器: {feature_detector_type}")
        return None

    # 使用掩码约束特征提取
    kp1, des1 = detector.detectAndCompute(img1_gray, mask1)
    kp2, des2 = detector.detectAndCompute(img2_gray, mask2)

    print(f"[AlignMask] 掩码区域特征点: img1={len(kp1) if kp1 else 0}, img2={len(kp2) if kp2 else 0}")

    if des1 is None or des2 is None or len(kp1) < min_match_count or len(kp2) < min_match_count:
        print(f"[AlignMask] 掩码区域特征点不足")
        return None

    # 特征匹配
    norm_type = cv2.NORM_L2 if feature_detector_type == 'SIFT' else cv2.NORM_HAMMING
    bf = cv2.BFMatcher(norm_type, crossCheck=False)
    matches = bf.knnMatch(des1, des2, k=2)

    # Lowe 比率测试
    good_matches = []
    for m_n in matches:
        if len(m_n) == 2:
            m, n = m_n
            if m.distance < ratio_test_thresh * n.distance:
                good_matches.append(m)

    if len(good_matches) < min_match_count:
        print(f"[AlignMask] 掩码区域有效匹配不足: {len(good_matches)}/{min_match_count}")
        return None

    src_pts = np.array([kp1[m.queryIdx].pt for m in good_matches], dtype=np.float32).reshape(-1, 1, 2)
    dst_pts = np.array([kp2[m.trainIdx].pt for m in good_matches], dtype=np.float32).reshape(-1, 1, 2)

    # RANSAC 求解 Homography
    H, mask_homography = cv2.findHomography(dst_pts, src_pts, cv2.RANSAC, 1.0)

    if H is None:
        print("[AlignMask] 无法计算单应矩阵")
        return None

    inlier_count = int(mask_homography.sum()) if mask_homography is not None else 0
    inlier_ratio = inlier_count / len(good_matches) if len(good_matches) > 0 else 0
    print(f"[AlignMask] 内点数: {inlier_count}/{len(good_matches)}, 内点比例: {inlier_ratio:.2%}")

    if inlier_ratio < min_inlier_ratio and inlier_count < min_inlier_count:
        print(f"[AlignMask] 配准质量不可靠")
        return None

    # ECC 精化
    if use_ecc:
        H = refine_with_ecc(img1_gray, img2_gray, H)

    aligned_img2 = cv2.warpPerspective(img2_color, H, (w1, h1))
    return aligned_img2