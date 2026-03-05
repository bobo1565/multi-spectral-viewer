import React, { useState, useRef } from 'react';
import './ROICanvas.css';

export interface ROICoords {
    x: number;
    y: number;
    width: number;
    height: number;
}

interface Props {
    /** 传入已经存在的 ROI，用于持久化显示 */
    roi?: ROICoords | null;
    /** 绘制完成（鼠标松开）时的回调 */
    onROIDraw?: (roi: ROICoords) => void;
}

/**
 * 全屏覆盖的 ROI 绘制层。
 * 调用方负责将它叠加在主画面上 (position: absolute / overlay)。
 */
export default function ROICanvas({ roi, onROIDraw }: Props) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [isDrawing, setIsDrawing] = useState(false);
    const [startPos, setStartPos] = useState({ x: 0, y: 0 });
    const [liveRect, setLiveRect] = useState<ROICoords | null>(null);

    // 决定显示哪个框：正在画的临时框 > 已保存的 roi
    const displayRect = liveRect ?? roi ?? null;

    const toRel = (clientX: number, clientY: number) => {
        const el = containerRef.current!;
        const r = el.getBoundingClientRect();
        return {
            x: Math.max(0, Math.min(1, (clientX - r.left) / r.width)),
            y: Math.max(0, Math.min(1, (clientY - r.top) / r.height)),
        };
    };

    const handleMouseDown = (e: React.MouseEvent) => {
        e.preventDefault();
        const rel = toRel(e.clientX, e.clientY);
        setIsDrawing(true);
        setStartPos(rel);
        setLiveRect({ x: rel.x, y: rel.y, width: 0, height: 0 });
    };

    const handleMouseMove = (e: React.MouseEvent) => {
        if (!isDrawing) return;
        const rel = toRel(e.clientX, e.clientY);
        setLiveRect({
            x: Math.min(startPos.x, rel.x),
            y: Math.min(startPos.y, rel.y),
            width: Math.abs(rel.x - startPos.x),
            height: Math.abs(rel.y - startPos.y),
        });
    };

    const handleMouseUp = (_e: React.MouseEvent) => {
        if (!isDrawing) return;
        setIsDrawing(false);
        if (liveRect && liveRect.width > 0.005 && liveRect.height > 0.005) {
            onROIDraw?.(liveRect);
        }
        setLiveRect(null);
    };

    return (
        <div
            ref={containerRef}
            className="roi-overlay"
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
        >
            {/* 暗色遮罩 */}
            <div className="roi-dim" />

            {displayRect && (
                <>
                    {/* 选框 "打洞" 区域：通过4块阴影矩形实现外部遮暗、内部清晰 */}
                    <div className="roi-clear-box" style={{
                        left: `${displayRect.x * 100}%`,
                        top: `${displayRect.y * 100}%`,
                        width: `${displayRect.width * 100}%`,
                        height: `${displayRect.height * 100}%`,
                    }}>
                        <div className="roi-border" />
                        <div className="roi-corner roi-corner-tl" />
                        <div className="roi-corner roi-corner-tr" />
                        <div className="roi-corner roi-corner-bl" />
                        <div className="roi-corner roi-corner-br" />
                    </div>
                </>
            )}

            <div className="roi-hint-label">
                {isDrawing
                    ? `选框: ${((liveRect?.width ?? 0) * 100).toFixed(0)}% × ${((liveRect?.height ?? 0) * 100).toFixed(0)}%`
                    : '拖拽鼠标绘制 ROI 区域（框外特征将被忽略）'}
            </div>
        </div>
    );
}
