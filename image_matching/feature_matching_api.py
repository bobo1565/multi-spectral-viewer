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


def get_roi_from_config(img_width, img_height, roi_config):  # 根据配置计算ROI区域

    roi_x = int(img_width * roi_config['roi_x_ratio'])
    roi_y = int(img_height * roi_config['roi_y_ratio'])
    roi_w = int(img_width * roi_config['roi_width_ratio'])
    roi_h = int(img_height * roi_config['roi_height_ratio'])

    # 确保ROI不超出图像边界
    roi_x = max(0, min(roi_x, img_width - 1))
    roi_y = max(0, min(roi_y, img_height - 1))
    roi_w = max(1, min(roi_w, img_width - roi_x))
    roi_h = max(1, min(roi_h, img_height - roi_y))

    return roi_x, roi_y, roi_w, roi_h


def find_valid_region(img, threshold=10):  # 检测图像中的有效区域（非黑边区域）
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img

    # 找到非黑色像素
    mask = gray > threshold

    # 找到有效区域的边界
    coords = np.column_stack(np.where(mask))
    if len(coords) == 0:
        return None

    y_min, x_min = coords.min(axis=0)
    y_max, x_max = coords.max(axis=0)

    return (x_min, y_min, x_max, y_max)


def calculate_common_region(regions):  # 计算多个区域的交集
    if not regions or any(r is None for r in regions):
        return None

    x_min = max(r[0] for r in regions)
    y_min = max(r[1] for r in regions)
    x_max = min(r[2] for r in regions)
    y_max = min(r[3] for r in regions)

    # 检查是否有有效的交集
    if x_min >= x_max or y_min >= y_max:
        return None

    return (x_min, y_min, x_max, y_max)


def crop_image(img, region):  # 根据区域剪裁图像
    if region is None:
        return img

    x_min, y_min, x_max, y_max = region
    return img[y_min:y_max, x_min:x_max]


def align_images(img1_color, img2_color, roi_config1=None, roi_config2=None,
                 feature_detector_type='SIFT',
                 ratio_test_thresh=0.75, min_match_count=10):
    h1, w1 = img1_color.shape[:2]
    h2, w2 = img2_color.shape[:2]

    # 直接使用传入的ROI配置，不提供默认值
    if not roi_config1 or not roi_config2:
        raise ValueError("必须提供有效的ROI配置")

    # 根据配置计算ROI区域
    roi_x1, roi_y1, roi_w1, roi_h1 = get_roi_from_config(w1, h1, roi_config1)
    roi_x2, roi_y2, roi_w2, roi_h2 = get_roi_from_config(w2, h2, roi_config2)

    print(f"图像1 ROI: x={roi_x1}, y={roi_y1}, w={roi_w1}, h={roi_h1}")
    print(f"图像2 ROI: x={roi_x2}, y={roi_y2}, w={roi_w2}, h={roi_h2}")

    mask1 = np.zeros((h1, w1), dtype=np.uint8)
    mask1[roi_y1:roi_y1 + roi_h1, roi_x1:roi_x1 + roi_w1] = 255
    mask2 = np.zeros((h2, w2), dtype=np.uint8)
    mask2[roi_y2:roi_y2 + roi_h2, roi_x2:roi_x2 + roi_w2] = 255
    img1 = cv2.cvtColor(img1_color, cv2.COLOR_BGR2GRAY)
    img2 = cv2.cvtColor(img2_color, cv2.COLOR_BGR2GRAY)

    # SIFT/ORB兼容性处理
    detector = None
    try:
        if feature_detector_type == 'SIFT':
            if hasattr(cv2, 'SIFT_create'):
                detector = cv2.SIFT_create()
            elif hasattr(cv2, 'xfeatures2d') and hasattr(cv2.xfeatures2d, 'SIFT_create'):
                detector = cv2.xfeatures2d.SIFT_create()
            else:
                raise AttributeError('OpenCV未编译SIFT')
        elif feature_detector_type == 'ORB':
            if hasattr(cv2, 'ORB_create'):
                detector = cv2.ORB_create(nfeatures=2000)
            else:
                raise AttributeError('OpenCV未编译ORB')
        else:
            raise ValueError(f"不支持的特征检测器: {feature_detector_type}")
    except Exception as e:
        print(f"OpenCV不支持SIFT/ORB: {e}")
        return None

    kp1, des1 = detector.detectAndCompute(img1, mask1)
    kp2, des2 = detector.detectAndCompute(img2, mask2)

    if des1 is None or des2 is None or len(kp1) < min_match_count or len(kp2) < min_match_count:
        print("特征点不足，无法进行匹配。")
        return None

    if feature_detector_type == 'SIFT':
        bf = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
    elif feature_detector_type == 'ORB':
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    else:
        bf = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)

    matches = bf.knnMatch(des1, des2, k=2)
    good_matches = []
    for m, n in matches:
        if m.distance < ratio_test_thresh * n.distance:
            good_matches.append(m)

    if len(good_matches) < min_match_count:
        print(f"好的匹配点不足 ({len(good_matches)}/{min_match_count})，无法计算单应矩阵。")
        return None

    if not good_matches:
        print("无有效匹配点。")
        return None

    src_pts = np.array([kp1[m.queryIdx].pt for m in good_matches], dtype=np.float32).reshape(-1, 1, 2)
    dst_pts = np.array([kp2[m.trainIdx].pt for m in good_matches], dtype=np.float32).reshape(-1, 1, 2)
    H, mask_homography = cv2.findHomography(dst_pts, src_pts, cv2.RANSAC, 2.0)

    if H is None:
        print("无法计算单应矩阵。")
        return None

    aligned_img2 = cv2.warpPerspective(img2_color, H, (w1, h1))
    return aligned_img2


def validate_image_filenames(image_paths_dict):
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