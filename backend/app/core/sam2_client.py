"""
SAM2 分割服务客户端
通过 HTTP 调用独立的 SAM2 Docker 服务进行图像分割
"""
import os
import base64
import httpx
import cv2
import numpy as np
from typing import List, Optional


# SAM2 服务地址（Docker 内部网络 or 本地开发）
SAM2_SERVICE_URL = os.environ.get("SAM2_SERVICE_URL", "http://localhost:8001")

# HTTP 超时设置（SAM2 推理可能需要较长时间）
TIMEOUT = httpx.Timeout(timeout=120.0, connect=10.0)


def _decode_mask_b64(mask_b64: str) -> np.ndarray:
    """将 base64 编码的 PNG 掩码解码为 numpy 数组"""
    mask_bytes = base64.b64decode(mask_b64)
    nparr = np.frombuffer(mask_bytes, np.uint8)
    mask = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
    return (mask > 127).astype(np.uint8)


def segment_image(image_path: str) -> List[dict]:
    """
    调用 SAM2 服务对图像进行自动分割（Segment Everything）。
    
    返回掩码列表，每个掩码包含:
      - mask: np.ndarray (H, W) 二值掩码
      - area: int
      - bbox: [x1, y1, x2, y2]
      - score: float
    """
    with open(image_path, 'rb') as f:
        files = {"file": (os.path.basename(image_path), f, "image/jpeg")}
        response = httpx.post(
            f"{SAM2_SERVICE_URL}/segment",
            files=files,
            timeout=TIMEOUT,
        )

    if response.status_code != 200:
        print(f"[SAM2Client] 分割请求失败: {response.status_code} - {response.text}")
        return []

    data = response.json()
    masks = []
    for m in data.get("masks", []):
        masks.append({
            "mask": _decode_mask_b64(m["mask_b64"]),
            "area": m["area"],
            "bbox": m["bbox"],
            "score": m["score"],
        })

    print(f"[SAM2Client] 检测到 {len(masks)} 个物体")
    return masks


def get_largest_mask(masks: List[dict], top_n: int = 1) -> Optional[np.ndarray]:
    """
    获取面积最大的 N 个掩码的联合掩码。
    
    当 top_n > 1 时，将多个掩码合并为一个联合掩码，
    确保特征提取覆盖多个主要物体区域。
    """
    if not masks:
        return None

    # 按面积降序排列
    sorted_masks = sorted(masks, key=lambda m: m["area"], reverse=True)

    # 取前 N 个
    selected = sorted_masks[:top_n]

    # 合并掩码
    combined = selected[0]["mask"].copy()
    for m in selected[1:]:
        combined = np.logical_or(combined, m["mask"]).astype(np.uint8)

    return combined * 255  # 转为 0/255 格式，兼容 OpenCV mask 参数


def segment_image_by_points(image_path: str, points: List[List[int]]) -> List[dict]:
    """
    调用 SAM2 服务使用点提示进行分割。
    
    参数:
        image_path: 图像文件路径
        points: 点坐标列表，例如 [[x1, y1], [x2, y2]]
    
    返回: 同 segment_image() 格式的掩码列表
    """
    import json

    points_x = json.dumps([p[0] for p in points])
    points_y = json.dumps([p[1] for p in points])

    with open(image_path, 'rb') as f:
        files = {"file": (os.path.basename(image_path), f, "image/jpeg")}
        data = {"points_x": points_x, "points_y": points_y}
        response = httpx.post(
            f"{SAM2_SERVICE_URL}/segment-by-points",
            files=files,
            data=data,
            timeout=TIMEOUT,
        )

    if response.status_code != 200:
        print(f"[SAM2Client] 点提示分割失败: {response.status_code} - {response.text}")
        return []

    resp_data = response.json()
    masks = []
    for m in resp_data.get("masks", []):
        masks.append({
            "mask": _decode_mask_b64(m["mask_b64"]),
            "mask_b64": m["mask_b64"],  # 保留原始 base64 用于预览
            "area": m["area"],
            "bbox": m["bbox"],
            "score": m["score"],
        })

    print(f"[SAM2Client] 点提示分割检测到 {len(masks)} 个掩码")
    return masks


def check_health() -> bool:
    """检查 SAM2 服务是否可用"""
    try:
        response = httpx.get(f"{SAM2_SERVICE_URL}/health", timeout=5.0)
        return response.status_code == 200
    except Exception:
        return False
