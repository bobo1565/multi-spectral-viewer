import React, { useState, useRef } from 'react';
import './ROICanvas.css';

interface ROICoords {
    x: number;
    y: number;
    width: number;
    height: number;
}

interface Props {
    imageUrl: string;
    onROIChange: (roi: ROICoords | null) => void;
}

export default function ROICanvas({ imageUrl, onROIChange }: Props) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [isDrawing, setIsDrawing] = useState(false);
    const [startPos, setStartPos] = useState({ x: 0, y: 0 });
    const [currentRect, setCurrentRect] = useState<ROICoords | null>(null);

    const handleMouseDown = (e: React.MouseEvent) => {
        if (!containerRef.current) return;

        const rect = containerRef.current.getBoundingClientRect();
        const absoluteX = e.clientX - rect.left;
        const absoluteY = e.clientY - rect.top;

        // Calculate relative coordinates (0 to 1)
        const relX = Math.max(0, Math.min(1, absoluteX / rect.width));
        const relY = Math.max(0, Math.min(1, absoluteY / rect.height));

        setIsDrawing(true);
        setStartPos({ x: relX, y: relY });
        const newRect = { x: relX, y: relY, width: 0, height: 0 };
        setCurrentRect(newRect);
        onROIChange(newRect); // Immediate update to show UI binding
    };

    const handleMouseMove = (e: React.MouseEvent) => {
        if (!isDrawing || !containerRef.current) return;

        const rect = containerRef.current.getBoundingClientRect();
        const absoluteX = e.clientX - rect.left;
        const absoluteY = e.clientY - rect.top;

        const currentRelX = Math.max(0, Math.min(1, absoluteX / rect.width));
        const currentRelY = Math.max(0, Math.min(1, absoluteY / rect.height));

        const minX = Math.min(startPos.x, currentRelX);
        const minY = Math.min(startPos.y, currentRelY);
        const maxX = Math.max(startPos.x, currentRelX);
        const maxY = Math.max(startPos.y, currentRelY);

        const newRect = {
            x: minX,
            y: minY,
            width: maxX - minX,
            height: maxY - minY
        };

        setCurrentRect(newRect);
    };

    const handleMouseUp = () => {
        if (!isDrawing) return;
        setIsDrawing(false);

        // If the drawn rectangle is too small (e.g. just a click), ignore it
        if (currentRect && (currentRect.width < 0.01 || currentRect.height < 0.01)) {
            setCurrentRect(null);
            onROIChange(null);
        } else {
            onROIChange(currentRect);
        }
    };

    const handleClear = () => {
        setCurrentRect(null);
        onROIChange(null);
    };

    return (
        <div className="roi-canvas-wrapper">
            <div className="roi-canvas-toolbar">
                <span className="roi-hint">请在图像上按住鼠标左键并拖拽以框选匹配区域：</span>
                <button type="button" onClick={handleClear} disabled={!currentRect} className="roi-clear-btn">
                    清除选择
                </button>
            </div>

            <div
                className="roi-image-container"
                ref={containerRef}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
            >
                <img src={imageUrl} alt="Reference" className="roi-background-img" draggable={false} />

                {currentRect && (
                    <div
                        className="roi-selection-box"
                        style={{
                            left: `${currentRect.x * 100}%`,
                            top: `${currentRect.y * 100}%`,
                            width: `${currentRect.width * 100}%`,
                            height: `${currentRect.height * 100}%`,
                        }}
                    >
                        {/* 遮罩，让框外变暗 (可选，比较复杂，这里仅通过框本身来提示) */}
                    </div>
                )}
            </div>
        </div>
    );
}
