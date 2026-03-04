import { useState, useMemo, useEffect } from 'react';
import { Card, Button, Checkbox, message, Alert, Select, Form } from 'antd';
import { SyncOutlined, ThunderboltOutlined } from '@ant-design/icons';
import type { BatchInfo, ImageInfo } from '../types';
import { alignmentService, api } from '../services/api';
import ROICanvas from './ROICanvas';
import './AlignmentPanel.css'; // Assume CSS exists or styling is inline

interface Props {
    images?: ImageInfo[]; // Deprecated, use batch instead
    batch?: BatchInfo | null;
    batchId?: string; // Keep for backward compatibility if needed
    onAlignmentComplete?: () => void;
}

export default function AlignmentPanel({ batch, batchId, onAlignmentComplete }: Props) {
    const [overwrite, setOverwrite] = useState<boolean>(true);
    const [loading, setLoading] = useState(false);
    const [selectedRefId, setSelectedRefId] = useState<string | null>(null);
    const [enableRoi, setEnableRoi] = useState(false);
    const [customRoi, setCustomRoi] = useState<{ x: number, y: number, width: number, height: number } | null>(null);

    const actualBatchId = batch?.id || batchId;

    // 获取 Source 图像列表
    const sourceImages = useMemo(() => {
        if (!batch) return [];
        const imgs: { label: string; value: string; band: string }[] = [];

        // Handle source_images object
        const sourceMap = batch.source_images || batch.images || {};

        Object.entries(sourceMap).forEach(([band, img]) => {
            if (img) {
                // Filter out if it's explicitly marked as aligned (though checking source_images map should be enough)
                imgs.push({
                    label: `${band.toUpperCase()} - ${img.filename}`,
                    value: img.id,
                    band: band
                });
            }
        });

        return imgs;
    }, [batch]);

    // Set default reference ID (RGB)
    useEffect(() => {
        if (sourceImages.length > 0 && !selectedRefId) {
            const rgb = sourceImages.find(i => i.band === 'rgb');
            if (rgb) {
                setSelectedRefId(rgb.value);
            } else {
                setSelectedRefId(sourceImages[0].value);
            }
        }
    }, [sourceImages]);

    const refImageUrl = useMemo(() => {
        if (!selectedRefId || !batch) return null;
        let p = '';
        Object.values(batch.source_images || {}).forEach(img => {
            if (img && img.id === selectedRefId) {
                p = img.filepath;
            }
        });
        if (!p) return null;
        // Fix path to url logic
        return api.defaults.baseURL + '/uploads/' + p;
    }, [selectedRefId, batch]);

    const handleAlign = async () => {
        if (!actualBatchId) {
            message.error('请先选择一个批次');
            return;
        }

        setLoading(true);
        try {
            const roiParam = enableRoi && customRoi ? customRoi : undefined;
            const result = await alignmentService.batchAlign(
                actualBatchId,
                overwrite,
                selectedRefId || undefined,
                roiParam
            );

            // 显示结果信息
            if (result.new_images && result.new_images.length > 0) {
                message.success(`${result.summary}，已生成 ${result.new_images.length} 个新文件`);
            } else {
                message.success(result.summary || '对齐完成');
            }

            // 刷新图像列表
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

                <Form.Item style={{ marginBottom: 12 }}>
                    <Checkbox
                        checked={enableRoi}
                        onChange={e => setEnableRoi(e.target.checked)}
                    >
                        启用手动绘制 ROI (局部高精度对齐)
                    </Checkbox>
                </Form.Item>

                {enableRoi && refImageUrl && (
                    <Form.Item label="绘制 ROI">
                        <ROICanvas
                            imageUrl={refImageUrl}
                            onROIChange={setCustomRoi}
                        />
                    </Form.Item>
                )}

                <Button
                    type="primary"
                    block
                    icon={<SyncOutlined spin={loading} />}
                    onClick={handleAlign}
                    loading={loading}
                    disabled={!selectedRefId}
                >
                    执行批量对齐
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
