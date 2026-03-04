from flask import Flask, request, jsonify
import os
import cv2
import numpy as np
import json

def get_roi_config_from_request(roi_config_data, roi_config_path=None):
    """
    严格模式：从请求中获取ROI配置，不提供默认值
    返回: (is_valid, error_code, error_message, config_data)
    """
    # 检查是否同时提供了两种配置方式
    if roi_config_data and roi_config_path:
        return False, 4, "不能同时提供roi_config和roi_config_path参数，请选择其中一种方式", None

    # 检查是否至少提供了配置方式
    if not roi_config_data and not roi_config_path:
        return False, 4, "必须提供roi_config或roi_config_path参数中的一个", None

    # 方式1：直接提供ROI配置数据
    if roi_config_data:
        # 校验直接提供的配置数据
        if not isinstance(roi_config_data, dict):
            return False, 6, "roi_config必须是字典格式", None

        required_fields = ['roi_x_ratio', 'roi_y_ratio', 'roi_width_ratio', 'roi_height_ratio']
        missing_fields = []

        for field in required_fields:
            if field not in roi_config_data:
                missing_fields.append(field)

        if missing_fields:
            return False, 6, f"roi_config缺少必需字段: {', '.join(missing_fields)}", None

        # 校验字段值
        for field in required_fields:
            value = roi_config_data[field]
            if not isinstance(value, (int, float)):
                return False, 6, f"roi_config字段 '{field}' 必须是数字类型", None
            if not (0 <= value <= 1):
                return False, 6, f"roi_config字段 '{field}' 值必须在0-1之间", None

        return True, 0, "ROI配置校验通过", roi_config_data

    # 方式2：通过文件路径提供配置
    if roi_config_path:
        return validate_roi_config_path(roi_config_path)




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
                 use_ecc=True, min_inlier_ratio=0.15, min_inlier_count=50):
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
    return aligned_img2def validate_image_filenames(image_paths_dict):
    """
    校验图片文件名是否与参数对应
    参数: image_paths_dict - 包含图片路径的字典
    返回: (is_valid, error_message)
    """
    # 定义期望的文件名后缀映射
    expected_suffixes = {
        'image_abs_path_rgb': ['d'],
        'image_abs_path_g': ['g'],
        'image_abs_path_r': ['r'],
        'image_abs_path_re': ['re'],
        'image_abs_path_nir': ['nir']
    }

    for param_key, file_path in image_paths_dict.items():
        if param_key not in expected_suffixes:
            continue

        # 获取文件名（不含扩展名）
        filename = os.path.splitext(os.path.basename(file_path))[0].lower()
        expected_suffix_list = expected_suffixes[param_key]

        # 检查文件名是否以期望的后缀结尾
        is_valid = False
        for expected_suffix in expected_suffix_list:
            if filename.endswith(expected_suffix.lower()):
                is_valid = True
                break

        if not is_valid:
            param_display_name = param_key.replace('image_abs_path_', '').upper()
            expected_display = '/'.join(expected_suffix_list)
            return False, f"参数 '{param_key}' 对应的文件名应以 '{expected_display}' 结尾，当前文件: {os.path.basename(file_path)}"

    return True, None


# 错误码定义
ERROR_CODES = {
    'SUCCESS': 0,
    'MISSING_PARAMS': 1,
    'FILE_NOT_FOUND': 1,
    'IMAGE_LOAD_FAILED': 1,
    'PROCESSING_FAILED': 2,
    'FILENAME_VALIDATION_FAILED': 3,
    'ROI_CONFIG_PATH_INVALID': 4,
    'ROI_CONFIG_FILE_NOT_FOUND': 5,
    'ROI_CONFIG_CONTENT_INVALID': 6,
    'ROI_CONFIG_FORMAT_ERROR': 7
}

def feature_matching_batch_api():
    """批量处理五个图像的配准和剪裁"""
    data = request.get_json()

    # 检查输入参数
    required_keys = ['image_abs_path_rgb', 'image_abs_path_g', 'image_abs_path_r',
                     'image_abs_path_re', 'image_abs_path_nir']

    if not data or not all(key in data for key in required_keys):
        return jsonify({'code': 1, 'msg': f'缺少必要参数: {required_keys}'}), 400

    # 严格校验ROI配置（不提供默认值）
    roi_config_data = data.get('roi_config')
    roi_config_path = data.get('roi_config_path')

    is_valid, error_code, error_message, roi_config = get_roi_config_from_request(
        roi_config_data, roi_config_path
    )

    if not is_valid:
        return jsonify({'code': error_code, 'msg': error_message}), 400

    image_paths = [data[key] for key in required_keys]

    # 检查所有图片是否存在
    for path in image_paths:
        if not os.path.isfile(path):
            return jsonify({'code': 1, 'msg': f'图片路径无效或文件不存在: {path}'}), 400

    # 校验图片文件名是否与参数对应
    image_paths_dict = {key: data[key] for key in required_keys}
    is_valid, validation_error = validate_image_filenames(image_paths_dict)
    if not is_valid:
        return jsonify({'code': 3, 'msg': f'文件名校验失败: {validation_error}'}), 400

    # 简化后的图像加载部分
    try:
        # 加载所有图像
        images = []

        for path in image_paths:
            img = cv2.imread(path)
            if img is None:
                return jsonify({'code': 1, 'msg': f'图片加载失败: {path}'}), 400
            images.append(img)

        # 以RGB图像为基准进行配准
        reference_img = images[0]  # RGB图像
        aligned_images = [reference_img]  # 第一个图像作为参考

        # 对其他四个图像进行配准
        for i in range(1, len(images)):
            aligned_img = align_images(reference_img, images[i], roi_config, roi_config)
            if aligned_img is None:
                return jsonify({'code': 2, 'msg': f'第{i + 1}个图像配准失败'}), 500
            aligned_images.append(aligned_img)

        # 检测每个图像的有效区域
        valid_regions = []
        for img in aligned_images:
            region = find_valid_region(img)
            valid_regions.append(region)

        # 计算公共有效区域
        common_region = calculate_common_region(valid_regions)
        if common_region is None:
            return jsonify({'code': 2, 'msg': '无法找到公共有效区域'}), 500

        # 剪裁所有图像
        cropped_images = []
        for img in aligned_images:
            cropped_img = crop_image(img, common_region)
            cropped_images.append(cropped_img)

        # 保存剪裁后的图像（直接覆盖原始图片）
        output_paths = []

        for i, (img, original_path) in enumerate(zip(cropped_images, image_paths)):
            # 直接使用原始图片的路径和文件名
            cv2.imwrite(original_path, img)
            output_paths.append(original_path)
            print(f"已覆盖原始图片: {original_path}")

        return jsonify({
            'code': 0,
            'msg': 'success',
            'output_paths': output_paths,
            'common_region': [int(x) for x in common_region] if common_region else None,
            'cropped_size': {
                'width': int(common_region[2] - common_region[0]),
                'height': int(common_region[3] - common_region[1])
            } if common_region else None
        })

    except Exception as e:
        return jsonify({'code': 2, 'msg': f'程序运行失败: {str(e)}'}), 500


def validate_roi_config_path(roi_config_path):
    """
    严格校验ROI配置文件路径和内容
    返回: (is_valid, error_code, error_message, config_data)
    """
    if not roi_config_path:
        return False, 4, "ROI配置文件路径不能为空", None

    # 1. 校验路径格式
    if not isinstance(roi_config_path, str):
        return False, 4, "ROI配置文件路径必须是字符串格式", None

    # 2. 校验文件扩展名
    if not roi_config_path.lower().endswith('.json'):
        return False, 4, "ROI配置文件必须是.json格式", None

    # 3. 校验路径是否为绝对路径
    if not os.path.isabs(roi_config_path):
        return False, 4, "ROI配置文件路径必须是绝对路径", None

    # 4. 校验文件是否存在
    if not os.path.exists(roi_config_path):
        return False, 5, f"ROI配置文件不存在: {roi_config_path}", None

    # 5. 校验是否为文件（不是目录）
    if not os.path.isfile(roi_config_path):
        return False, 5, f"指定路径不是文件: {roi_config_path}", None

    # 6. 尝试读取和解析JSON文件
    try:
        with open(roi_config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
    except json.JSONDecodeError as e:
        return False, 7, f"ROI配置文件JSON格式错误: {str(e)}", None
    except UnicodeDecodeError as e:
        return False, 7, f"ROI配置文件编码错误: {str(e)}", None
    except Exception as e:
        return False, 5, f"读取ROI配置文件失败: {str(e)}", None

    # 7. 校验JSON内容结构
    required_fields = ['roi_x_ratio', 'roi_y_ratio', 'roi_width_ratio', 'roi_height_ratio']
    missing_fields = []

    for field in required_fields:
        if field not in config_data:
            missing_fields.append(field)

    if missing_fields:
        return False, 6, f"ROI配置文件缺少必需字段: {', '.join(missing_fields)}", None

    # 8. 校验字段值的类型和范围
    for field in required_fields:
        value = config_data[field]

        # 检查是否为数字类型
        if not isinstance(value, (int, float)):
            return False, 6, f"ROI配置字段 '{field}' 必须是数字类型，当前类型: {type(value).__name__}", None

        # 检查数值范围（0-1之间）
        if not (0 <= value <= 1):
            return False, 6, f"ROI配置字段 '{field}' 值必须在0-1之间，当前值: {value}", None

    # 9. 校验ROI区域的逻辑合理性
    x_ratio = config_data['roi_x_ratio']
    y_ratio = config_data['roi_y_ratio']
    width_ratio = config_data['roi_width_ratio']
    height_ratio = config_data['roi_height_ratio']

    # 检查ROI区域是否超出图像边界
    if x_ratio + width_ratio > 1:
        return False, 6, f"ROI区域超出图像宽度边界: x_ratio({x_ratio}) + width_ratio({width_ratio}) > 1", None

    if y_ratio + height_ratio > 1:
        return False, 6, f"ROI区域超出图像高度边界: y_ratio({y_ratio}) + height_ratio({height_ratio}) > 1", None

    # 检查ROI区域大小是否合理（不能太小）
    if width_ratio < 0.01 or height_ratio < 0.01:
        return False, 6, f"ROI区域太小: width_ratio({width_ratio}), height_ratio({height_ratio})，最小值应为0.01", None

    return True, 0, "ROI配置文件校验通过", config_data