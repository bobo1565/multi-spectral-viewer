/**
 * 图像查看器组件
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { Card, Spin } from 'antd';
import { ZoomInOutlined, ZoomOutOutlined, FullscreenOutlined } from '@ant-design/icons';
import type { ImageInfo } from '../types';
import './ImageViewer.css';

type ChannelType = 'rgb' | 'r' | 'g' | 'b';

interface PixelValue {
    x: number;
    y: number;
    r: number;
    g: number;
    b: number;
    gray?: number;
}

interface Props {
    image: ImageInfo | null;
    blendedUrl?: string | null;
    channel?: ChannelType;
    colormap?: string;
    whiteBalance?: { r: number; g: number; b: number };
    saturation?: number;
    onHistogramChange?: (histogram: { r: number[], g: number[], b: number[] }) => void;
    onPixelHover?: (x: number, y: number) => void;
}

export default function ImageViewer({
    image,
    blendedUrl = null,
    channel = 'rgb',
    colormap = 'gray',
    whiteBalance = { r: 1, g: 1, b: 1 },
    saturation = 1,
    onHistogramChange,
    onPixelHover
}: Props) {
    const [scale, setScale] = useState(1);
    const [offset, setOffset] = useState({ x: 0, y: 0 });
    const [isDragging, setIsDragging] = useState(false);
    const [loading, setLoading] = useState(false);

    const containerRef = useRef<HTMLDivElement>(null);
    const imgRef = useRef<HTMLImageElement>(null);
    const lastMouseRef = useRef({ x: 0, y: 0 });

    const [processedUrl, setProcessedUrl] = useState<string | null>(null);
    const [pixelValue, setPixelValue] = useState<PixelValue | null>(null);
    const imageDataRef = useRef<ImageData | null>(null);
    const originalImageDataRef = useRef<ImageData | null>(null);

    // 防抖计时器用于直方图计算
    const histogramTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // 将视图重置为适应容器
    const resetView = useCallback(() => {
        if (!containerRef.current || !image) return;

        const cw = containerRef.current.clientWidth;
        const ch = containerRef.current.clientHeight;
        const iw = image.width;
        const ih = image.height;

        const s = Math.min(cw / iw, ch / ih, 1) * 0.9;
        setScale(s);
        setOffset({
            x: (cw - iw * s) / 2,
            y: (ch - ih * s) / 2
        });
    }, [image]);

    // 加载图片
    useEffect(() => {
        setPixelValue(null);
        imageDataRef.current = null;
        originalImageDataRef.current = null;

        if (blendedUrl) {
            setProcessedUrl(blendedUrl);
            loadImageUrl(blendedUrl);
        } else if (image) {
            setProcessedUrl(null);
            const imageUrl = image.url
                ? `http://localhost:8000${image.url}`
                : `http://localhost:8000/api/images/${image.id}`;
            loadImageUrl(imageUrl);
        } else {
            setProcessedUrl(null);
        }
    }, [image?.id, image?.url, blendedUrl]);

    // 图片加载完成且尺寸就绪后，重置视图
    useEffect(() => {
        if (processedUrl && image) {
            // 延迟一下确保 DOM 已渲染且尺寸可用
            const timer = setTimeout(resetView, 100);
            return () => clearTimeout(timer);
        }
    }, [processedUrl, image?.id, resetView]);

    // 处理图片：当参数变化时重新处理
    useEffect(() => {
        if (originalImageDataRef.current) {
            processImageData();
        }
    }, [channel, colormap, whiteBalance, saturation]);

    // 处理拖拽
    useEffect(() => {
        const handleGlobalMouseMove = (e: MouseEvent) => {
            if (!isDragging) return;

            const dx = e.clientX - lastMouseRef.current.x;
            const dy = e.clientY - lastMouseRef.current.y;

            setOffset((prev: { x: number; y: number }) => ({ x: prev.x + dx, y: prev.y + dy }));
            lastMouseRef.current = { x: e.clientX, y: e.clientY };
        };

        const handleGlobalMouseUp = () => {
            setIsDragging(false);
        };

        if (isDragging) {
            window.addEventListener('mousemove', handleGlobalMouseMove);
            window.addEventListener('mouseup', handleGlobalMouseUp);
        }

        return () => {
            window.removeEventListener('mousemove', handleGlobalMouseMove);
            window.removeEventListener('mouseup', handleGlobalMouseUp);
        };
    }, [isDragging]);

    const handleMouseDown = (e: React.MouseEvent) => {
        if (e.button !== 0) return; // 仅左键拖拽
        setIsDragging(true);
        lastMouseRef.current = { x: e.clientX, y: e.clientY };
    };

    const handleWheel = (e: React.WheelEvent) => {
        if (!containerRef.current) return;

        const zoomFactor = 1.1;
        const direction = e.deltaY < 0 ? 1 : -1;
        const newScale = direction > 0
            ? Math.min(scale * zoomFactor, 20)
            : Math.max(scale / zoomFactor, 0.05);

        if (newScale === scale) return;

        // 锚点缩放：保证鼠标下的像素位置不变
        const rect = containerRef.current.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;

        // o2 = v_m - (s2/s1) * (v_m - o1)
        const ratio = newScale / scale;
        const ox = mx - ratio * (mx - offset.x);
        const oy = my - ratio * (my - offset.y);

        setScale(newScale);
        setOffset({ x: ox, y: oy });
    };

    const loadImageUrl = async (url: string) => {
        setLoading(true);
        const imgElement = new Image();
        imgElement.crossOrigin = 'anonymous';

        imgElement.onload = () => {
            const canvas = document.createElement('canvas');
            canvas.width = imgElement.width;
            canvas.height = imgElement.height;
            const ctx = canvas.getContext('2d');

            if (!ctx) {
                setLoading(false);
                return;
            }

            ctx.drawImage(imgElement, 0, 0);
            const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);

            // 保存当前显示的数据用于像素拾取
            imageDataRef.current = imageData;

            // 保存原始数据
            originalImageDataRef.current = new ImageData(
                new Uint8ClampedArray(imageData.data),
                imageData.width,
                imageData.height
            );

            if (!blendedUrl) {
                processImageData();
            }
            setLoading(false);
        };

        imgElement.onerror = (err) => {
            console.error('Failed to load image:', err);
            setLoading(false);
            if (!blendedUrl) setProcessedUrl(url); // 回退
        };

        imgElement.src = url;
    };

    const processImageData = () => {
        if (!originalImageDataRef.current) return;

        const width = originalImageDataRef.current.width;
        const height = originalImageDataRef.current.height;
        const srcData = originalImageDataRef.current.data;

        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const newImageData = ctx.createImageData(width, height);
        const dstData = newImageData.data;

        // 直方图数据
        const histR = new Array(256).fill(0);
        const histG = new Array(256).fill(0);
        const histB = new Array(256).fill(0);

        for (let i = 0; i < srcData.length; i += 4) {
            let r = srcData[i];
            let g = srcData[i + 1];
            let b = srcData[i + 2];
            let a = srcData[i + 3];

            // 1. 提取通道
            if (channel !== 'rgb') {
                const channelIndex = channel === 'r' ? 0 : channel === 'g' ? 1 : 2;
                const value = srcData[i + channelIndex];
                // 应用色带
                const [cr, cg, cb] = applyColormap(value, colormap);
                r = cr; g = cg; b = cb;
            } else {
                // 2. 应用白平衡 (仅RGB模式)
                r = Math.min(255, r * whiteBalance.r);
                g = Math.min(255, g * whiteBalance.g);
                b = Math.min(255, b * whiteBalance.b);

                // 3. 应用饱和度 (仅RGB模式)
                if (saturation !== 1) {
                    const gray = 0.2989 * r + 0.5870 * g + 0.1140 * b;
                    r = Math.min(255, Math.max(0, gray + (r - gray) * saturation));
                    g = Math.min(255, Math.max(0, gray + (g - gray) * saturation));
                    b = Math.min(255, Math.max(0, gray + (b - gray) * saturation));
                }
            }

            dstData[i] = r;
            dstData[i + 1] = g;
            dstData[i + 2] = b;
            dstData[i + 3] = a;

            // 统计直方图
            histR[Math.round(r)]++;
            histG[Math.round(g)]++;
            histB[Math.round(b)]++;
        }

        imageDataRef.current = newImageData; // 更新当前显示用的数据用于像素拾取
        ctx.putImageData(newImageData, 0, 0);
        setProcessedUrl(canvas.toDataURL('image/png'));

        // 更新直方图（防抖）
        if (histogramTimerRef.current) clearTimeout(histogramTimerRef.current);
        histogramTimerRef.current = setTimeout(() => {
            onHistogramChange?.({ r: histR, g: histG, b: histB });
        }, 100);
    };

    // 色带映射函数
    const applyColormap = (value: number, map: string): [number, number, number] => {
        const norm = value / 255;

        switch (map) {
            case 'gray':
                return [value, value, value];
            case 'jet':
                if (norm < 0.125) {
                    return [0, 0, Math.round(128 + norm * 1024)];
                } else if (norm < 0.375) {
                    return [0, Math.round((norm - 0.125) * 1024), 255];
                } else if (norm < 0.625) {
                    return [Math.round((norm - 0.375) * 1024), 255, Math.round(255 - (norm - 0.375) * 1024)];
                } else if (norm < 0.875) {
                    return [255, Math.round(255 - (norm - 0.625) * 1024), 0];
                } else {
                    return [Math.round(255 - (norm - 0.875) * 1024), 0, 0];
                }
            case 'hot':
                if (norm < 0.33) {
                    return [Math.round(norm * 768), 0, 0];
                } else if (norm < 0.67) {
                    return [255, Math.round((norm - 0.33) * 768), 0];
                } else {
                    return [255, 255, Math.round((norm - 0.67) * 768)];
                }
            case 'viridis':
                const r = Math.round(68 + norm * 185);
                const g = Math.round(1 + norm * 230);
                const b = Math.round(84 - norm * 47);
                return [Math.max(0, Math.min(255, r)), Math.max(0, Math.min(255, g)), Math.max(0, Math.min(255, b))];
            default:
                return [value, value, value];
        }
    };

    const handleZoomIn = () => {
        if (!containerRef.current) return;
        const rect = containerRef.current.getBoundingClientRect();
        const mx = rect.width / 2;
        const my = rect.height / 2;
        const zoomFactor = 1.2;
        const newScale = Math.min(scale * zoomFactor, 20);
        const ratio = newScale / scale;
        setOffset({
            x: mx - ratio * (mx - offset.x),
            y: my - ratio * (my - offset.y)
        });
        setScale(newScale);
    };

    const handleZoomOut = () => {
        if (!containerRef.current) return;
        const rect = containerRef.current.getBoundingClientRect();
        const mx = rect.width / 2;
        const my = rect.height / 2;
        const zoomFactor = 1 / 1.2;
        const newScale = Math.max(scale * zoomFactor, 0.05);
        const ratio = newScale / scale;
        setOffset({
            x: mx - ratio * (mx - offset.x),
            y: my - ratio * (my - offset.y)
        });
        setScale(newScale);
    };

    const handleReset = () => resetView();

    const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
        if (!containerRef.current || !image) return;

        const rect = containerRef.current.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;

        // 计算实际像素坐标：(mx - offset.x) / scale
        const x = Math.floor((mx - offset.x) / scale);
        const y = Math.floor((my - offset.y) / scale);

        if (x >= 0 && x < image.width && y >= 0 && y < image.height) {
            onPixelHover?.(x, y);

            // 读取像素值
            if (imageDataRef.current) {
                const idx = (y * image.width + x) * 4;
                const data = imageDataRef.current.data;
                const originData = originalImageDataRef.current?.data;

                if (channel === 'rgb') {
                    setPixelValue({
                        x, y,
                        r: data[idx],
                        g: data[idx + 1],
                        b: data[idx + 2]
                    });
                } else {
                    let grayValue = 0;
                    if (originData) {
                        const channelIndex = channel === 'r' ? 0 : channel === 'g' ? 1 : 2;
                        grayValue = originData[idx + channelIndex];
                    }

                    setPixelValue({
                        x, y,
                        r: data[idx],
                        g: data[idx + 1],
                        b: data[idx + 2],
                        gray: grayValue
                    });
                }
            }
        }
    }, [image, scale, offset, channel, onPixelHover]);

    const handleMouseLeave = () => {
        setPixelValue(null);
    };

    if (!image && !blendedUrl) {
        return (
            <Card className="image-viewer empty">
                <div className="placeholder">请选择或上传图像</div>
            </Card>
        );
    }

    // 标题显示通道信息
    const channelLabel = {
        rgb: 'RGB 彩图',
        r: 'R 通道 (灰度)',
        g: 'G 通道 (灰度)',
        b: 'B 通道 (灰度)',
    }[channel];

    // 当只有 blendedUrl 时的显示标题
    const displayTitle = image ? image.filename : '计算结果';
    const displayLabel = image ? channelLabel : '植被指数';

    return (
        <Card
            className="image-viewer"
            title={
                <span>
                    {displayTitle}
                    <span className={`channel-badge channel-${channel}`}>{displayLabel}</span>
                </span>
            }
            extra={
                <div className="zoom-controls">
                    <ZoomOutOutlined onClick={handleZoomOut} />
                    <span>{Math.round(scale * 100)}%</span>
                    <ZoomInOutlined onClick={handleZoomIn} />
                    <FullscreenOutlined onClick={handleReset} />
                </div>
            }
        >
            <div
                className="viewer-container"
                ref={containerRef}
                onWheel={handleWheel}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseLeave={handleMouseLeave}
            >
                {loading && <Spin className="loading-spin" />}
                {processedUrl && (
                    <img
                        ref={imgRef}
                        src={processedUrl}
                        alt={displayTitle}
                        style={{
                            transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
                            transition: isDragging ? 'none' : 'transform 0.1s ease'
                        }}
                        onLoad={() => setLoading(false)}
                        draggable={false}
                    />
                )}
            </div>

            {/* 像素状态栏 */}
            <div className="pixel-status-bar">
                {image ? (
                    <>
                        <span className="info-item">{image.width} × {image.height}</span>
                        <span className="info-item">{image.channels}通道</span>
                        <span className="info-item">{(image.size / 1024).toFixed(1)} KB</span>
                        <span className="divider">|</span>
                    </>
                ) : (
                    <span className="info-item">计算结果图像</span>
                )}
                {pixelValue ? (
                    <>
                        <span className="coord">X: {pixelValue.x}, Y: {pixelValue.y}</span>
                        {channel === 'rgb' ? (
                            <span className="pixel-rgb">
                                <span className="r">R: {pixelValue.r}</span>
                                <span className="g">G: {pixelValue.g}</span>
                                <span className="b">B: {pixelValue.b}</span>
                            </span>
                        ) : (
                            <span className="pixel-gray">
                                Gray: {pixelValue.gray}
                                <span className="mapped-color" style={{ marginLeft: 8, fontSize: 10, color: '#999' }}>
                                    (Mapped: {pixelValue.r}, {pixelValue.g}, {pixelValue.b})
                                </span>
                            </span>
                        )}
                    </>
                ) : (
                    <span className="hint">移动鼠标查看像素值</span>
                )}
            </div>
        </Card>
    );
}
