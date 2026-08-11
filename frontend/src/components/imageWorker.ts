/**
 * 图像逐像素处理 Web Worker
 *
 * 背景：分析页切换/调参时，对 2880x1616（约 465 万像素）的图做通道分离、
 * 白平衡、饱和度、colormap 计算并统计直方图。放在主线程会阻塞 UI 数秒。
 * 这里把整段逐像素运算移到 Worker 线程，主线程只负责回绘 canvas。
 */

export interface ImageWorkerRequest {
    width: number;
    height: number;
    /** RGBA 像素数据，会被 Transferable 转移所有权（主线程不再可用） */
    data: Uint8ClampedArray;
    channel: 'rgb' | 'r' | 'g' | 'b' | 'tiff';
    colormap: string;
    whiteBalance: { r: number; g: number; b: number };
    saturation: number;
}

export interface ImageWorkerResult {
    width: number;
    height: number;
    /** 处理后的 RGBA 像素数据 */
    data: Uint8ClampedArray;
    histogram: { r: number[]; g: number[]; b: number[] };
}

function applyColormap(value: number, map: string): [number, number, number] {
    const norm = value / 255;
    switch (map) {
        case 'gray':
            return [value, value, value];
        case 'jet':
            if (norm < 0.125) return [0, 0, Math.round(128 + norm * 1024)];
            if (norm < 0.375) return [0, Math.round((norm - 0.125) * 1024), 255];
            if (norm < 0.625) return [Math.round((norm - 0.375) * 1024), 255, Math.round(255 - (norm - 0.375) * 1024)];
            if (norm < 0.875) return [255, Math.round(255 - (norm - 0.625) * 1024), 0];
            return [Math.round(255 - (norm - 0.875) * 1024), 0, 0];
        case 'hot':
            if (norm < 0.33) return [Math.round(norm * 768), 0, 0];
            if (norm < 0.67) return [255, Math.round((norm - 0.33) * 768), 0];
            return [255, 255, Math.round((norm - 0.67) * 768)];
        case 'viridis': {
            const r = Math.round(68 + norm * 185);
            const g = Math.round(1 + norm * 230);
            const b = Math.round(84 - norm * 47);
            return [Math.max(0, Math.min(255, r)), Math.max(0, Math.min(255, g)), Math.max(0, Math.min(255, b))];
        }
        default:
            return [value, value, value];
    }
}

self.onmessage = (e: MessageEvent<ImageWorkerRequest>) => {
    const { width, height, data: srcData, channel, colormap, whiteBalance, saturation } = e.data;
    const dstData = new Uint8ClampedArray(srcData.length);

    const histR = new Array(256).fill(0);
    const histG = new Array(256).fill(0);
    const histB = new Array(256).fill(0);

    for (let i = 0; i < srcData.length; i += 4) {
        let r = srcData[i];
        let g = srcData[i + 1];
        let b = srcData[i + 2];
        const a = srcData[i + 3];

        if (channel === 'tiff') {
            const value = Math.round(0.299 * r + 0.587 * g + 0.114 * b);
            const [cr, cg, cb] = applyColormap(value, colormap);
            r = cr; g = cg; b = cb;
        } else if (channel !== 'rgb') {
            const channelIndex = channel === 'r' ? 0 : channel === 'g' ? 1 : 2;
            const value = srcData[i + channelIndex];
            const [cr, cg, cb] = applyColormap(value, colormap);
            r = cr; g = cg; b = cb;
        } else {
            r = Math.min(255, r * whiteBalance.r);
            g = Math.min(255, g * whiteBalance.g);
            b = Math.min(255, b * whiteBalance.b);
            if (saturation !== 1) {
                const gray = 0.2989 * r + 0.587 * g + 0.114 * b;
                r = Math.min(255, Math.max(0, gray + (r - gray) * saturation));
                g = Math.min(255, Math.max(0, gray + (g - gray) * saturation));
                b = Math.min(255, Math.max(0, gray + (b - gray) * saturation));
            }
        }

        dstData[i] = r;
        dstData[i + 1] = g;
        dstData[i + 2] = b;
        dstData[i + 3] = a;

        histR[Math.min(255, Math.round(r))]++;
        histG[Math.min(255, Math.round(g))]++;
        histB[Math.min(255, Math.round(b))]++;
    }

    const result: ImageWorkerResult = {
        width,
        height,
        data: dstData,
        histogram: { r: histR, g: histG, b: histB },
    };
    // 转移 dstData 所有权，避免拷贝
    (self as unknown as Worker).postMessage(result, [dstData.buffer]);
};
