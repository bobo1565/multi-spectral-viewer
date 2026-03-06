"""
SAM2 分割服务
基于 ultralytics 框架运行 Segment Anything Model 2
提供自动分割 API，模型权重首次使用时自动下载
"""
import os
import io
import base64
import traceback
import numpy as np
import cv2
from PIL import Image, ImageOps
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── 模型配置 ──────────────────────────────────
# 可选: sam2.1_t.pt (tiny), sam2.1_s.pt (small), sam2.1_b.pt (base), sam2.1_l.pt (large)
SAM2_MODEL_NAME = os.environ.get("SAM2_MODEL", "sam2.1_l.pt")

app = FastAPI(
    title="SAM2 Segmentation Service",
    description="Segment Anything Model 2 API powered by Ultralytics (模型自动下载)",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 全局模型实例（懒加载，首次使用时自动下载权重）────
_sam_model = None


def get_sam_model():
    """懒加载 SAM2 模型（ultralytics 自动下载权重）"""
    global _sam_model
    if _sam_model is None:
        from ultralytics import SAM
        print(f"[SAM2] Loading model: {SAM2_MODEL_NAME} (首次使用会自动下载) ...")
        _sam_model = SAM(SAM2_MODEL_NAME)
        print(f"[SAM2] Model {SAM2_MODEL_NAME} loaded successfully.")
    return _sam_model


# ── 响应模型 ──────────────────────────────────
class MaskInfo(BaseModel):
    mask_b64: str       # base64 编码的二值掩码 (PNG)
    area: int           # 掩码面积（像素数）
    bbox: List[float]   # [x1, y1, x2, y2]
    score: float        # 置信度


class SegmentResponse(BaseModel):
    num_masks: int
    masks: List[MaskInfo]
    image_width: int
    image_height: int


# ── 辅助函数 ──────────────────────────────────
def _read_image_from_upload(file_bytes: bytes) -> np.ndarray:
    """从上传的文件字节读取图像"""
    pil_img = Image.open(io.BytesIO(file_bytes))
    pil_img = ImageOps.exif_transpose(pil_img)
    if pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")
    rgb = np.array(pil_img)
    if rgb.size == 0:
        raise ValueError("无法解码图像")
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _mask_to_b64(mask: np.ndarray) -> str:
    """将二值掩码编码为 base64 PNG"""
    mask_uint8 = (mask * 255).astype(np.uint8) if mask.max() <= 1 else mask.astype(np.uint8)
    _, buffer = cv2.imencode('.png', mask_uint8)
    return base64.b64encode(buffer).decode('utf-8')


# ── API 端点 ──────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "model": SAM2_MODEL_NAME,
        "service": "SAM2 Segmentation Service",
        "auto_download": True,
    }


@app.post("/segment", response_model=SegmentResponse)
async def segment(file: UploadFile = File(...)):
    """
    自动分割：使用 SAM2 "Segment Everything" 模式。
    
    SAM2 在不提供任何 prompt（点/框）时会自动分割整张图像中的所有物体。
    返回所有检测到的掩码列表（按面积降序）。
    """
    try:
        file_bytes = await file.read()
        img = _read_image_from_upload(file_bytes)
        img_h, img_w = img.shape[:2]

        model = get_sam_model()

        # SAM2 "Segment Everything" 模式：不传 points/bboxes
        print(f"[SAM2] Running Segment Everything on image ({img_w}x{img_h}) ...")
        results = model(img, verbose=False)

        masks_list = []

        if results and len(results) > 0:
            result = results[0]

            if result.masks is not None:
                masks_data = result.masks.data.cpu().numpy()  # (N, H, W)
                boxes = result.boxes

                for i in range(masks_data.shape[0]):
                    mask = masks_data[i]

                    # 如果掩码尺寸与原图不同，resize
                    if mask.shape[0] != img_h or mask.shape[1] != img_w:
                        mask = cv2.resize(mask, (img_w, img_h), interpolation=cv2.INTER_NEAREST)

                    area = int((mask > 0.5).sum())

                    # 过滤过小的掩码
                    if area < 100:
                        continue

                    # 获取 bbox
                    if boxes is not None and i < len(boxes):
                        bbox = boxes[i].xyxy[0].cpu().numpy().tolist()
                        score = float(boxes[i].conf[0].cpu().numpy()) if boxes[i].conf is not None else 1.0
                    else:
                        # 从掩码计算 bbox
                        coords = np.where(mask > 0.5)
                        if len(coords[0]) > 0:
                            bbox = [
                                float(coords[1].min()),
                                float(coords[0].min()),
                                float(coords[1].max()),
                                float(coords[0].max())
                            ]
                        else:
                            bbox = [0.0, 0.0, 0.0, 0.0]
                        score = 1.0

                    masks_list.append(MaskInfo(
                        mask_b64=_mask_to_b64(mask),
                        area=area,
                        bbox=bbox,
                        score=score,
                    ))

        # 按面积降序排列
        masks_list.sort(key=lambda m: m.area, reverse=True)

        print(f"[SAM2] Found {len(masks_list)} valid masks")

        return SegmentResponse(
            num_masks=len(masks_list),
            masks=masks_list,
            image_width=img_w,
            image_height=img_h,
        )

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"分割失败: {str(e)}")


@app.post("/segment-by-points", response_model=SegmentResponse)
async def segment_by_points(
    file: UploadFile = File(...),
    points_x: str = Form("[]"),
    points_y: str = Form("[]"),
):
    """
    点提示分割：使用指定的点坐标分割对应物体。
    
    points_x, points_y: JSON 格式的坐标数组，如 "[100,200]"
    """
    import json

    try:
        file_bytes = await file.read()
        img = _read_image_from_upload(file_bytes)
        img_h, img_w = img.shape[:2]

        px = json.loads(points_x)
        py = json.loads(points_y)

        if not px or not py or len(px) != len(py):
            raise ValueError("points_x 和 points_y 必须等长且非空")

        points = [[x, y] for x, y in zip(px, py)]
        labels = [1] * len(points)

        print(f"[SAM2] 接收到的点坐标：{points}, 图像尺寸：{img_w}x{img_h}")

        model = get_sam_model()
        results = model(img, points=points, labels=labels, verbose=False)

        masks_list = []
        if results and len(results) > 0:
            result = results[0]
            if result.masks is not None:
                masks_data = result.masks.data.cpu().numpy()
                boxes = result.boxes
                for i in range(masks_data.shape[0]):
                    mask = masks_data[i]
                    if mask.shape[0] != img_h or mask.shape[1] != img_w:
                        mask = cv2.resize(mask, (img_w, img_h), interpolation=cv2.INTER_NEAREST)
                    area = int((mask > 0.5).sum())
                    if area < 100:
                        continue

                    if boxes is not None and i < len(boxes):
                        bbox = boxes[i].xyxy[0].cpu().numpy().tolist()
                        score = float(boxes[i].conf[0].cpu().numpy()) if boxes[i].conf is not None else 1.0
                    else:
                        coords = np.where(mask > 0.5)
                        bbox = [float(coords[1].min()), float(coords[0].min()),
                                float(coords[1].max()), float(coords[0].max())] if len(coords[0]) > 0 else [0, 0, 0, 0]
                        score = 1.0

                    masks_list.append(MaskInfo(
                        mask_b64=_mask_to_b64(mask), area=area, bbox=bbox, score=score,
                    ))

        masks_list.sort(key=lambda m: m.area, reverse=True)

        return SegmentResponse(
            num_masks=len(masks_list), masks=masks_list,
            image_width=img_w, image_height=img_h,
        )

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"点提示分割失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
