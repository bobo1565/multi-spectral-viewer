/**
 * 图像查看器组件
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { Card, Spin } from 'antd';
import { ZoomInOutlined, ZoomOutOutlined, FullscreenOutlined } from '@ant-design/icons';
import type { ImageInfo } from '../types';
import { API_BASE } from '../services/api';
import './ImageViewer.css';

function sanitizeUrlPath(url: string): string {
  try {
    const u = new URL(url);
    const parts: string[] = [];
    for (const seg of u.pathname.split('/')) {
      if (seg === '' || seg === '.') continue;
      if (seg === '..') {
        parts.pop();
      } else {
        parts.push(seg);
      }
    }
    u.pathname = '/' + parts.join('/');
    return u.toString();
  } catch {
    return url;
  }
}

type ChannelType = 'rgb' | 'r' | 'g' | 'b' | 'tiff';

interface PixelValue {
    x: number;
    y: number;
    r: number;
    g: number;
    b: number;
    gray?: number;
}

export interface ViewerLayer {
    id: string;
    url: string;
    opacity?: number;
    blendMode?: React.CSSProperties['mixBlendMode'];
    visible?: boolean;
    clipPath?: string;
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
    onTransformChange?: (transform: {
        scale: number;
        offsetX: number;
        offsetY: number;
        imageWidth: number;
        imageHeight: number;
    }) => void;
    layers?: ViewerLayer[];
    children?: React.ReactNode;
}

export default function ImageViewer({
    image,
    blendedUrl = null,
    channel = 'rgb',
    colormap = 'gray',
    whiteBalance = { r: 1, g: 1, b: 1 },
    saturation = 1,
    onHistogramChange,
    onPixelHover,
    onTransformChange,
    layers = [],
    children,
}: Props) {
    const [scale, setScale] = useState(1);
    const [offset, setOffset] = useState({ x: 0, y: 0 });
    const [isDragging, setIsDragging] = useState(false);
    const [loading, setLoading] = useState(false);

    const containerRef = useRef<HTMLDivElement>(null);
    const imgRef = useRef<HTMLImageElement>(null);
    const lastMouseRef = useRef({ x: 0, y: 0 });
    const renderSizeRef = useRef({ width: image?.width || 0, height: image?.height || 0 });

    const [processedUrl, setProcessedUrl] = useState<string | null>(null);
    const [pixelValue, setPixelValue] = useState<PixelValue | null>(null);
    const imageDataRef = useRef<ImageData | null>(null);
    const originalImageDataRef = useRef<ImageData | null>(null);
    // 记录当前原图 URL，默认参数直通时作为 processedUrl，避免 canvas 处理
    const originalImageUrlRef = useRef<string | null>(null);
    // 图像处理 Worker（逐像素运算放后台线程，避免阻塞 UI）
    const workerRef = useRef<Worker | null>(null);
    // 处理请求序号：丢弃过期结果（快速连续调参时只用最新一次）
    const processSeqRef = useRef(0);

    // 防抖计时器用于直方图计算
    const histogramTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    // 像素值更新节流
    const lastPixelUpdateRef = useRef(0);

    // 组件卸载时清理定时器和 Worker
    useEffect(() => {
        return () => {
            if (histogramTimerRef.current) clearTimeout(histogramTimerRef.current);
            if (workerRef.current) {
                workerRef.current.terminate();
                workerRef.current = null;
            }
        };
    }, []);

    // 懒加载获取图像处理 Worker
    const getWorker = (): Worker => {
        if (!workerRef.current) {
            workerRef.current = new Worker(new URL('./imageWorker.ts', import.meta.url), { type: 'module' });
        }
        return workerRef.current;
    };

    // 将视图重置为适应容器
    const emitTransform = useCallback((nextScale: number, nextOffset: { x: number; y: number }) => {
        onTransformChange?.({
            scale: nextScale,
            offsetX: nextOffset.x,
            offsetY: nextOffset.y,
            imageWidth: renderSizeRef.current.width,
            imageHeight: renderSizeRef.current.height,
        });
    }, [onTransformChange]);

    const resetView = useCallback(() => {
        if (!containerRef.current || !image) return;

        const cw = containerRef.current.clientWidth;
        const ch = containerRef.current.clientHeight;
        const iw = renderSizeRef.current.width || image.width;
        const ih = renderSizeRef.current.height || image.height;
        if (!iw || !ih) return;

        const newScale = Math.min(cw / iw, ch / ih, 1) * 0.9;
        const newOffset = {
            x: (cw - iw * newScale) / 2,
            y: (ch - ih * newScale) / 2
        };
        setScale(newScale);
        setOffset(newOffset);
        emitTransform(newScale, newOffset);
    }, [image, emitTransform]);

    // 加载图片
    useEffect(() => {
        setPixelValue(null);
        imageDataRef.current = null;
        originalImageDataRef.current = null;
        renderSizeRef.current = { width: image?.width || 0, height: image?.height || 0 };

        if (blendedUrl) {
            setProcessedUrl(blendedUrl);
            loadImageUrl(blendedUrl);
        } else if (image) {
            setProcessedUrl(null);
            let imageUrl: string;
            if (channel === 'tiff' && image.filename?.toLowerCase().endsWith('.tiff')) {
                imageUrl = `${API_BASE}/api/images/${image.id}/tiff-preview`;
            } else {
                imageUrl = image.url
                    ? sanitizeUrlPath(`${API_BASE}${image.url}`)
                    : `${API_BASE}/api/images/${image.id}`;
            }
            loadImageUrl(imageUrl);
        } else {
            setProcessedUrl(null);
        }
    }, [image?.id, image?.url, image?.filename, blendedUrl, channel]);

    // 图片加载完成且尺寸就绪后，重置视图
    useEffect(() => {
        if (processedUrl && (image || blendedUrl)) {
            // 延迟一下确保 DOM 已渲染且尺寸可用
            const timer = setTimeout(resetView, 100);
            return () => clearTimeout(timer);
        }
    }, [processedUrl, image?.id, blendedUrl, resetView]);

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

            setOffset((prev: { x: number; y: number }) => {
                const newOffset = { x: prev.x + dx, y: prev.y + dy };
                emitTransform(scale, newOffset);
                return newOffset;
            });
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
    }, [isDragging, scale, emitTransform]);

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
        emitTransform(newScale, { x: ox, y: oy });
    };

    const loadImageUrl = async (url: string) => {
        setLoading(true);
        const imgElement = new Image();
        imgElement.crossOrigin = 'anonymous';
        // 记录原图 URL，默认参数直通时直接使用，跳过 canvas 像素处理
        originalImageUrlRef.current = url;

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
            renderSizeRef.current = { width: imageData.width, height: imageData.height };

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

    // 仅统计直方图（不生成新图），用于默认参数直通场景，避免 canvas 循环 + toDataURL。
    const computeHistogramFromOriginal = () => {
        if (!originalImageDataRef.current) return;
        const srcData = originalImageDataRef.current.data;
        const histR = new Array(256).fill(0);
        const histG = new Array(256).fill(0);
        const histB = new Array(256).fill(0);
        for (let i = 0; i < srcData.length; i += 4) {
            histR[srcData[i]]++;
            histG[srcData[i + 1]]++;
            histB[srcData[i + 2]]++;
        }
        if (histogramTimerRef.current) clearTimeout(histogramTimerRef.current);
        histogramTimerRef.current = setTimeout(() => {
            onHistogramChange?.({ r: histR, g: histG, b: histB });
        }, 100);
    };

    // 判断当前参数是否需要逐像素处理。
    // rgb 通道 + 白平衡全 1 + 饱和度 1 时，输出恒等于原图，可跳过昂贵的 canvas 循环。
    const needsPixelProcessing = () => {
        if (channel === 'tiff' || channel !== 'rgb') return true;
        if (saturation !== 1) return true;
        if (whiteBalance.r !== 1 || whiteBalance.g !== 1 || whiteBalance.b !== 1) return true;
        return false;
    };

    const processImageData = () => {
        if (!originalImageDataRef.current) return;

        // 默认参数：跳过逐像素处理，直方图单独轻量统计后直接用原图。
        if (!needsPixelProcessing()) {
            computeHistogramFromOriginal();
            setProcessedUrl(originalImageUrlRef.current);
            return;
        }

        const width = originalImageDataRef.current.width;
        const height = originalImageDataRef.current.height;

        // 逐像素处理放到 Web Worker，避免 465 万次循环阻塞主线程。
        // 这里拷贝一份数据发给 worker（originalImageDataRef 仍需保留供像素拾取/调参复用）。
        const srcCopy = new Uint8ClampedArray(originalImageDataRef.current.data);
        const seq = ++processSeqRef.current;
        const worker = getWorker();

        worker.onmessage = (e: MessageEvent) => {
            // 丢弃过期结果：快速连续调参时只采用最新一次
            if (seq !== processSeqRef.current) return;
            const { data: dstData, width: w, height: h, histogram } = e.data;

            const canvas = document.createElement('canvas');
            canvas.width = w;
            canvas.height = h;
            const ctx = canvas.getContext('2d');
            if (!ctx) return;

            const newImageData = new ImageData(dstData, w, h);
            imageDataRef.current = newImageData; // 更新当前显示用的数据用于像素拾取
            ctx.putImageData(newImageData, 0, 0);
            setProcessedUrl(canvas.toDataURL('image/png'));

            if (histogramTimerRef.current) clearTimeout(histogramTimerRef.current);
            histogramTimerRef.current = setTimeout(() => {
                onHistogramChange?.(histogram);
            }, 100);
        };

        worker.postMessage({
            width,
            height,
            data: srcCopy,
            channel,
            colormap,
            whiteBalance,
            saturation,
        }, [srcCopy.buffer]);
    };

    const handleZoomIn = () => {
        if (!containerRef.current) return;
        const rect = containerRef.current.getBoundingClientRect();
        const mx = rect.width / 2;
        const my = rect.height / 2;
        const zoomFactor = 1.2;
        const newScale = Math.min(scale * zoomFactor, 20);
        const ratio = newScale / scale;
        const newOffset = {
            x: mx - ratio * (mx - offset.x),
            y: my - ratio * (my - offset.y)
        };
        setOffset(newOffset);
        setScale(newScale);
        emitTransform(newScale, newOffset);
    };

    const handleZoomOut = () => {
        if (!containerRef.current) return;
        const rect = containerRef.current.getBoundingClientRect();
        const mx = rect.width / 2;
        const my = rect.height / 2;
        const zoomFactor = 1 / 1.2;
        const newScale = Math.max(scale * zoomFactor, 0.05);
        const ratio = newScale / scale;
        const newOffset = {
            x: mx - ratio * (mx - offset.x),
            y: my - ratio * (my - offset.y)
        };
        setOffset(newOffset);
        setScale(newScale);
        emitTransform(newScale, newOffset);
    };

    const handleReset = () => resetView();

    const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
        if (!containerRef.current || !image) return;

        const rect = containerRef.current.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const displayWidth = renderSizeRef.current.width || image.width;
        const displayHeight = renderSizeRef.current.height || image.height;

        // 计算实际像素坐标：(mx - offset.x) / scale
        const x = Math.floor((mx - offset.x) / scale);
        const y = Math.floor((my - offset.y) / scale);

        if (x >= 0 && x < displayWidth && y >= 0 && y < displayHeight) {
            onPixelHover?.(x, y);

            // 节流像素值更新（~30fps）
            const now = performance.now();
            if (now - lastPixelUpdateRef.current < 33) return;
            lastPixelUpdateRef.current = now;

            // 读取像素值
            if (imageDataRef.current) {
                const idx = (y * displayWidth + x) * 4;
                const data = imageDataRef.current.data;
                const originData = originalImageDataRef.current?.data;

                if (channel === 'rgb') {
                    setPixelValue({
                        x, y,
                        r: data[idx],
                        g: data[idx + 1],
                        b: data[idx + 2]
                    });
                } else if (channel === 'tiff') {
                    const od = originData;
                    const grayValue = od ? Math.round(0.299 * od[idx] + 0.587 * od[idx + 1] + 0.114 * od[idx + 2]) : 0;
                    setPixelValue({
                        x, y,
                        r: data[idx],
                        g: data[idx + 1],
                        b: data[idx + 2],
                        gray: grayValue
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
        tiff: 'TIFF 灰度',
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
                    <div
                        className="viewer-stage"
                        style={{
                            width: renderSizeRef.current.width,
                            height: renderSizeRef.current.height,
                            transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
                            transition: isDragging ? 'none' : 'transform 0.1s ease'
                        }}
                    >
                        <img
                            ref={imgRef}
                            src={processedUrl}
                            alt={displayTitle}
                            className="viewer-layer viewer-base-layer"
                            onLoad={() => setLoading(false)}
                            draggable={false}
                        />
                        {layers
                            .filter(layer => layer.visible !== false)
                            .map(layer => (
                                <img
                                    key={layer.id}
                                    src={layer.url}
                                    alt={layer.id}
                                    className="viewer-layer viewer-overlay-layer"
                                    style={{
                                        opacity: layer.opacity ?? 1,
                                        mixBlendMode: layer.blendMode ?? 'normal',
                                        clipPath: layer.clipPath ?? 'none',
                                    }}
                                    draggable={false}
                                />
                            ))}
                    </div>
                )}
                {children}
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
