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