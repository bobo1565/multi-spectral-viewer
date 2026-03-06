import { useState, useMemo, useEffect } from 'react';
import { Card, Button, Checkbox, message, Alert, Select, Form, Tag } from 'antd';
import { SyncOutlined, ThunderboltOutlined, AimOutlined, CloseCircleOutlined } from '@ant-design/icons';
import type { BatchInfo, ImageInfo } from '../types';
import { alignmentService } from '../services/api';
import type { ROICoords } from './ROICanvas';
import './AlignmentPanel.css';

interface Props {
    images: ImageInfo[];
    batch?: BatchInfo | null;
    batchId?: string;
    onAlignmentComplete: () => Promise<void>;
    /** 当前已绘制的 ROI（来自主画面），由父组件注入 */
    roi: ROICoords | null;
    /** 点击"绘制 ROI"按钮时触发，父组件负责打开主画面绘图模式 */
    onStartDrawROI: () => void;
    /** 点击"清除 ROI" */
    onClearROI: () => void;

    // SAM2 交互属性
    sam2ClickMode?: boolean;
    onStartSam2Click?: () => void;
    onCancelSam2Click?: () => void;
    sam2MaskB64?: string | null;
    sam2ClickPoint?: { x: number; y: number } | null;
    setSam2MaskB64?: (b64: string | null) => void;
    setSam2ClickPoint?: (pt: { x: number; y: number } | null) => void;
    sam2Loading?: boolean;
    setSam2Loading?: (l: boolean) => void;
}

export default function AlignmentPanel({
    batch,
    batchId,
    onAlignmentComplete,
    roi,
    onStartDrawROI,
    onClearROI,
    sam2ClickMode,
    onStartSam2Click,
    onCancelSam2Click,
    sam2MaskB64,
    sam2ClickPoint,
    sam2Loading
}: Props) {
    const [overwrite, setOverwrite] = useState<boolean>(true);
    const [loading, setLoading] = useState(false);
    const [selectedRefId, setSelectedRefId] = useState<string | null>(null);
    const [alignMode, setAlignMode] = useState<'homography' | 'homography_roi' | 'optical_flow' | 'sam2_object'>('homography');

    const actualBatchId = batch?.id || batchId;

    const sourceImages = useMemo(() => {
        if (!batch) return [];
        const imgs: { label: string; value: string; band: string }[] = [];
        const sourceMap = batch.source_images || batch.images || {};
        Object.entries(sourceMap).forEach(([band, img]) => {
            if (img) {
                imgs.push({
                    label: `${band.toUpperCase()} - ${img.filename}`,
                    value: img.id,
                    band: band
                });
            }
        });
        return imgs;
    }, [batch]);

    useEffect(() => {
        if (sourceImages.length > 0 && !selectedRefId) {
            const rgb = sourceImages.find(i => i.band === 'rgb');
            setSelectedRefId(rgb ? rgb.value : sourceImages[0].value);
        }
    }, [sourceImages]);

    // 切换模式时清除 ROI
    useEffect(() => {
        if (alignMode !== 'homography_roi') {
            onClearROI?.();
        }
    }, [alignMode]);

    const handleAlign = async () => {
        if (!actualBatchId) {
            message.error('请先选择一个批次');
            return;
        }

        setLoading(true);
        try {
            const sam2Points = (alignMode === 'sam2_object' && sam2ClickPoint)
                ? [[sam2ClickPoint.x, sam2ClickPoint.y]]
                : undefined;

            const result = await alignmentService.batchAlign(
                actualBatchId,
                overwrite,
                selectedRefId || undefined, // Pass undefined if null
                alignMode === 'homography_roi' && roi ? {
                    x: roi.x,
                    y: roi.y,
                    width: roi.width,
                    height: roi.height
                } : undefined,
                alignMode, // Pass alignMode directly as backendMode
                sam2Points
            );

            if (result.new_images && result.new_images.length > 0) {
                message.success(`${result.summary}，已生成 ${result.new_images.length} 个新文件`);
            } else {
                message.success(result.summary || '对齐完成');
            }

            if (onAlignmentComplete) {
                onAlignmentComplete();
            }
        } catch (error: any) {
            console.error(error);
            message.error(error.response?.data?.detail || '对齐失败');
        } finally {
            setLoading(false);
        }
    };

    if (!actualBatchId) {
        return (
            <Card title="图像对齐" size="small">
                <Alert message="请在左侧选择一个批次以进行对齐操作" type="info" showIcon />
            </Card>
        );
    }

    return (
        <Card title="图像对齐" size="small" extra={<ThunderboltOutlined />}>
            <Alert
                message="批量对齐模式"
                description="选择一张Source图像作为参考，其他Source图像将对齐到该图像。结果将保存在新的aligned目录中。"
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
            />

            <Form layout="vertical">
                <Form.Item label="当前批次ID" style={{ marginBottom: 12 }}>
                    <span style={{ fontSize: '12px', color: '#888' }}>{actualBatchId}</span>
                </Form.Item>

                <Form.Item label="包含Source图像数" style={{ marginBottom: 12 }}>
                    {sourceImages.length} 张
                </Form.Item>

                <Form.Item label="选择参考图像 (Reference)" required style={{ marginBottom: 12 }}>
                    <Select
                        placeholder="请选择参考图像"
                        value={selectedRefId}
                        onChange={setSelectedRefId}
                        options={sourceImages}
                        disabled={loading}
                    />
                </Form.Item>

                <Form.Item style={{ marginBottom: 12 }}>
                    <Checkbox
                        checked={overwrite}
                        onChange={e => setOverwrite(e.target.checked)}
                    >
                        覆盖同名文件 (在相同输出目录下)
                    </Checkbox>
                </Form.Item>

                <Form.Item label="对齐模式" style={{ marginBottom: 12 }}>
                    <Select
                        value={alignMode}
                        onChange={setAlignMode}
                        disabled={loading}
                        options={[
                            { label: 'Homography（全局）', value: 'homography' },
                            { label: 'Homography + ROI（深度选择）', value: 'homography_roi' },
                            { label: '稠密光流（逐像素）', value: 'optical_flow' },
                            { label: 'SAM2 物体配准 (Object-Based)', value: 'sam2_object' },
                        ]}
                    />
                </Form.Item>

                {alignMode === 'optical_flow' && (
                    <Alert
                        message="稠密光流模式"
                        description="先用 Homography 粗对齐，再用 Farneback 光流逐像素精细补偿。适合不同深度物体的场景，计算量较大。"
                        type="info"
                        showIcon
                        style={{ marginBottom: 12 }}
                    />
                )}

                {alignMode === 'sam2_object' && (
                    <Form.Item label="SAM2 物体选择" style={{ marginBottom: 16 }}>
                        <Alert
                            message="SAM2 物体配准模式"
                            description="使用 SAM2 自动分割图像中的物体，仅在指定物体区域提取特征进行配准。模型首次使用时会自动下载。"
                            type="info"
                            showIcon
                            style={{ marginBottom: 12 }}
                        />
                        {sam2ClickPoint && sam2MaskB64 ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                <Tag color="success" style={{ padding: '4px 8px', fontSize: 13 }}>
                                    ✓ 已生成参考物体掩码 (点击位置: {sam2ClickPoint.x}, {sam2ClickPoint.y})
                                </Tag>
                                <div style={{ display: 'flex', gap: 8 }}>
                                    <Button
                                        size="small"
                                        icon={<AimOutlined />}
                                        onClick={onStartSam2Click}
                                        disabled={loading || sam2Loading}
                                    >
                                        重新选择物体
                                    </Button>
                                    <Button
                                        size="small"
                                        danger
                                        icon={<CloseCircleOutlined />}
                                        onClick={onCancelSam2Click}
                                        disabled={loading || sam2Loading}
                                    >
                                        取消选择
                                    </Button>
                                </div>
                            </div>
                        ) : (
                            <Button
                                icon={<AimOutlined />}
                                onClick={onStartSam2Click}
                                disabled={loading || sam2Loading}
                                type={sam2ClickMode ? "primary" : "dashed"}
                                danger={sam2ClickMode} // 用于提示"正在选择"状态
                                block
                            >
                                {sam2Loading ? '⏳ 分割中...' : sam2ClickMode ? '🖱️ 请在左侧主视口点击物体' : '点击选择参考图上的物体'}
                            </Button>
                        )}
                    </Form.Item>
                )}

                {/* ROI 绘制区 */}
                {alignMode === 'homography_roi' && (
                    <Form.Item label="ROI 选区" style={{ marginBottom: 16 }}>
                        {roi ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                <Tag color="success" icon={<AimOutlined />} style={{ width: 'fit-content' }}>
                                    已选 {(roi.x * 100).toFixed(1)}%, {(roi.y * 100).toFixed(1)}%
                                    &nbsp;→&nbsp;
                                    {((roi.x + roi.width) * 100).toFixed(1)}%, {((roi.y + roi.height) * 100).toFixed(1)}%
                                </Tag>
                                <div style={{ display: 'flex', gap: 8 }}>
                                    <Button
                                        size="small"
                                        icon={<AimOutlined />}
                                        onClick={onStartDrawROI}
                                        disabled={loading}
                                    >
                                        重新绘制
                                    </Button>
                                    <Button
                                        size="small"
                                        danger
                                        icon={<CloseCircleOutlined />}
                                        onClick={onClearROI}
                                        disabled={loading}
                                    >
                                        清除选区
                                    </Button>
                                </div>
                                <Button
                                    size="small"
                                    type="dashed"
                                    disabled={loading}
                                    onClick={async () => {
                                        try {
                                            setLoading(true);
                                            await alignmentService.updateRoiConfig({
                                                roi_x_ratio: roi.x,
                                                roi_y_ratio: roi.y,
                                                roi_width_ratio: roi.width,
                                                roi_height_ratio: roi.height
                                            });
                                            message.success('已将当前选区保存为全局默认 ROI 配置 (matching.json)');
                                        } catch (error) {
                                            message.error('保存默认 ROI 失败');
                                        } finally {
                                            setLoading(false);
                                        }
                                    }}
                                >
                                    保存当前选区为全局默认
                                </Button>
                            </div>
                        ) : (
                            <Button
                                icon={<AimOutlined />}
                                onClick={onStartDrawROI}
                                disabled={loading}
                                type="dashed"
                                block
                            >
                                在主画面中绘制 ROI
                            </Button>
                        )}
                    </Form.Item>
                )}

                <Button
                    type="primary"
                    block
                    icon={<SyncOutlined spin={loading} />}
                    onClick={handleAlign}
                    loading={loading}
                    disabled={!selectedRefId || (alignMode === 'homography_roi' && !roi) || (alignMode === 'sam2_object' && !sam2ClickPoint)}
                >
                    {alignMode === 'homography_roi' && !roi
                        ? '请先绘制 ROI'
                        : (alignMode === 'sam2_object' && !sam2ClickPoint)
                            ? '请先选择 SAM2 配准物体'
                            : '执行批量对齐'}
                </Button>
            </Form>

            <Alert
                style={{ marginTop: 12 }}
                type="warning"
                message="对齐后的图像将保存在 aligned (或 aligned_n) 目录下。"
                showIcon
            />
        </Card>
    );
}
