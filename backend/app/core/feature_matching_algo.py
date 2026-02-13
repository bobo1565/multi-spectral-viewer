import cv2
import numpy as np

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
    if img is None: return None
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
    if region is None or img is None:
        return img

    x_min, y_min, x_max, y_max = region
    return img[y_min:y_max, x_min:x_max]


def align_images(img1_color, img2_color, roi_config1=None, roi_config2=None,
                 feature_detector_type='SIFT',
                 ratio_test_thresh=0.75, min_match_count=10):
    if img1_color is None or img2_color is None:
        return None
        
    h1, w1 = img1_color.shape[:2]
    h2, w2 = img2_color.shape[:2]

    # 直接使用传入的ROI配置，不提供默认值
    if not roi_config1 or not roi_config2:
        raise ValueError("必须提供有效的ROI配置")

    # 根据配置计算ROI区域
    roi_x1, roi_y1, roi_w1, roi_h1 = get_roi_from_config(w1, h1, roi_config1)
    roi_x2, roi_y2, roi_w2, roi_h2 = get_roi_from_config(w2, h2, roi_config2)

    mask1 = np.zeros((h1, w1), dtype=np.uint8)
    mask1[roi_y1:roi_y1 + roi_h1, roi_x1:roi_x1 + roi_w1] = 255
    mask2 = np.zeros((h2, w2), dtype=np.uint8)
    mask2[roi_y2:roi_y2 + roi_h2, roi_x2:roi_x2 + roi_w2] = 255
    
    img1 = cv2.cvtColor(img1_color, cv2.COLOR_BGR2GRAY) if len(img1_color.shape) == 3 else img1_color
    img2 = cv2.cvtColor(img2_color, cv2.COLOR_BGR2GRAY) if len(img2_color.shape) == 3 else img2_color

    # SIFT/ORB兼容性处理
    detector = None
    if feature_detector_type == 'SIFT':
        try:
            detector = cv2.SIFT_create()
        except:
            if hasattr(cv2, 'xfeatures2d'):
                detector = cv2.xfeatures2d.SIFT_create()
    elif feature_detector_type == 'ORB':
        detector = cv2.ORB_create(nfeatures=2000)

    if detector is None:
        return None

    kp1, des1 = detector.detectAndCompute(img1, mask1)
    kp2, des2 = detector.detectAndCompute(img2, mask2)

    if des1 is None or des2 is None or len(kp1) < min_match_count or len(kp2) < min_match_count:
        return None

    if feature_detector_type == 'SIFT':
        bf = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
    else:
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

    matches = bf.knnMatch(des1, des2, k=2)
    good_matches = []
    for m, n in matches:
        if m.distance < ratio_test_thresh * n.distance:
            good_matches.append(m)

    if len(good_matches) < min_match_count:
        return None

    src_pts = np.array([kp1[m.queryIdx].pt for m in good_matches], dtype=np.float32).reshape(-1, 1, 2)
    dst_pts = np.array([kp2[m.trainIdx].pt for m in good_matches], dtype=np.float32).reshape(-1, 1, 2)
    H, mask_homography = cv2.findHomography(dst_pts, src_pts, cv2.RANSAC, 2.0)

    if H is None:
        return None

    aligned_img2 = cv2.warpPerspective(img2_color, H, (w1, h1))
    return aligned_img2