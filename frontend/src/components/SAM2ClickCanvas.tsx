/**
 * SAM2 物体选择覆盖层
 * 叠加在图像查看器上，点击选择物体，显示 SAM2 掩码预览
 */
import React, { useRef, useCallback } from 'react';
import './SAM2ClickCanvas.css';

interface Props {
    /** 图像原始宽度（像素） */
    imageWidth: number;
    /** 图像原始高度（像素） */
    imageHeight: number;
    displayWidth?: number;
    displayHeight?: number;
    /** 图像变换参数（来自 ImageViewer） */
    scale: number;
    offsetX: number;
    offsetY: number;
    /** 用户点击回调，返回图像像素坐标 */
    onPointClick: (x: number, y: number) => void;
    /** 当前标记点 */
    clickPoint?: { x: number; y: number } | null;
    /** 是否正在加载 */
    loading?: boolean;
    clickEnabled?: boolean;
}

export default function SAM2ClickCanvas({
    imageWidth,
    imageHeight,
    displayWidth,
    displayHeight,
    scale,
    offsetX,
    offsetY,
    onPointClick,
    clickPoint,
    loading = false,
    clickEnabled = true,
}: Props) {
    const containerRef = useRef<HTMLDivElement>(null);
    const viewWidth = displayWidth || imageWidth;
    const viewHeight = displayHeight || imageHeight;

    const handleClick = useCallback((e: React.MouseEvent) => {
        if (!containerRef.current || loading || !clickEnabled) return;
        e.stopPropagation();
        e.preventDefault();

        const rect = containerRef.current.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;

        // 还原到图像像素坐标
        const imgX = Math.floor((mx - offsetX) / scale);
        const imgY = Math.floor((my - offsetY) / scale);

        console.log(`[SAM2Click] 鼠标点击：屏幕=(${mx.toFixed(1)}, ${my.toFixed(1)}), 显示图像=(${imgX}, ${imgY}), scale=${scale}, offset=(${offsetX}, ${offsetY}), display=${viewWidth}x${viewHeight}, target=${imageWidth}x${imageHeight}`);

        // 确保在图像范围内
        if (imgX >= 0 && imgX < viewWidth && imgY >= 0 && imgY < viewHeight) {
            onPointClick(imgX, imgY);
        } else {
            console.warn(`[SAM2Click] 点击超出范围：(${imgX}, ${imgY}), 显示尺寸：${viewWidth}x${viewHeight}`);
        }
    }, [imageWidth, imageHeight, viewWidth, viewHeight, scale, offsetX, offsetY, onPointClick, loading, clickEnabled]);

    return (
        <div
            ref={containerRef}
            className={`sam2-overlay ${loading ? 'sam2-loading' : ''}`}
            onClick={handleClick}
        >
            {/* 点击标记 */}
            {clickPoint && (
                <div
                    className="sam2-click-marker"
                    style={{
                        left: clickPoint.x * scale + offsetX - 8,
                        top: clickPoint.y * scale + offsetY - 8,
                    }}
                />
            )}

            {/* 提示文字 */}
            <div className="sam2-hint-label">
                {loading
                    ? '⏳ SAM2 正在分割...'
                    : clickPoint
                        ? '已选择物体（点击其他位置重新选择）'
                        : '🎯 点击图像上的目标物体进行分割'}
            </div>
        </div>
    );
}
