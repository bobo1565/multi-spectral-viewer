/**
 * 多光谱混合面板组件 - 重构版
 * 自动从当前批次选择对应波段的图像
 */
import { useState, useEffect, useMemo } from 'react';
import { Card, Select, Slider, Row, Col, Button, Divider, message, Alert } from 'antd';
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import type { BatchInfo, BandType } from '../types';
import { blendingService } from '../services/api';
import './BlendPanel.css';

interface Props {
    batch?: BatchInfo | null;  // 当前选中的批次
    imageType?: 'source' | 'aligned';  // 选中的图像类型
    pixelPosition?: { x: number; y: number } | null;
    onBlendedImageUrlChange?: (url: string | null) => void;
}

// 预定义光谱波段（不包含RGB）
const SPECTRAL_BANDS: { name: BandType; wavelength: number; color: string }[] = [
    { name: '570nm', wavelength: 570, color: '#00ff66' },
    { name: '650nm', wavelength: 650, color: '#ff0000' },
    { name: '730nm', wavelength: 730, color: '#cc0066' },
    { name: '850nm', wavelength: 850, color: '#660033' },
];

interface BandConfig {
    imageId: string | null;
    channel: 'r' | 'g' | 'b' | 'gray';
    weight: number;
}

export default function BlendPanel({ batch, imageType = 'source', pixelPosition, onBlendedImageUrlChange }: Props) {
    // 根据 imageType 自动从批次中获取对应波段的图像ID
    const bandImageIds = useMemo(() => {
        if (!batch) return {};

        // 根据选中的节点类型决定使用哪组图像
        const imagesMap = imageType === 'aligned'
            ? (batch.aligned_images || {})
            : (batch.source_images || batch.images || {});

        const ids: Record<string, string | null> = {};
        SPECTRAL_BANDS.forEach(band => {
            const img = (imagesMap as Record<string, any>)[band.name];
            ids[band.name] = img?.id || null;
        });
        return ids;
    }, [batch, imageType]);

    const [bands, setBands] = useState<Record<string, BandConfig>>(() => {
        const initial: Record<string, BandConfig> = {};
        SPECTRAL_BANDS.forEach(band => {
            initial[band.name] = { imageId: null, channel: 'gray', weight: 0.25 };
        });
        return initial;
    });

    // 当批次变化时，自动更新波段配置
    useEffect(() => {
        if (Object.keys(bandImageIds).length > 0) {
            setBands(prev => {
                const updated = { ...prev };
                SPECTRAL_BANDS.forEach(band => {
                    if (bandImageIds[band.name]) {
                        updated[band.name] = {
                            ...prev[band.name],
                            imageId: bandImageIds[band.name]
                        };
                    }
                });
                return updated;
            });
        }
    }, [bandImageIds]);

    const [spectralData, setSpectralData] = useState<{ wavelength: number; value: number }[]>([]);

    const handleChannelChange = (bandName: string, channel: 'r' | 'g' | 'b' | 'gray') => {
        setBands(prev => ({
            ...prev,
            [bandName]: { ...prev[bandName], channel }
        }));
    };

    const handleWeightChange = (bandName: string, weight: number) => {
        setBands(prev => ({
            ...prev,
            [bandName]: { ...prev[bandName], weight }
        }));
    };

    // 监听位置或波段配置变化，更新光谱曲线
    useEffect(() => {
        if (!pixelPosition) return;

        // 检查是否有波段已配置
        const activeBands: any = {};
        Object.entries(bands).forEach(([name, config]: [string, any]) => {
            if (config.imageId) {
                activeBands[name] = { image_id: config.imageId, channel: config.channel };
            }
        });

        if (Object.keys(activeBands).length === 0) return;

        const updateCurve = async () => {
            try {
                const data = await blendingService.getSpectralCurve(
                    pixelPosition.x,
                    pixelPosition.y,
                    activeBands
                );

                const points = data.wavelengths.map((w: number, i: number) => ({
                    wavelength: w,
                    value: data.values[i]
                }));
                setSpectralData(points);
            } catch (error) {
                console.error('获取光谱曲线失败:', error);
            }
        };

        const timer = setTimeout(updateCurve, 100);
        return () => clearTimeout(timer);
    }, [pixelPosition, bands]);

    const handleBlend = async () => {
        try {
            const activeBands: any = {};
            const weights: any = {};

            Object.entries(bands).forEach(([name, config]) => {
                if (config.imageId) {
                    activeBands[name] = { image_id: config.imageId, channel: config.channel };
                    weights[name] = config.weight;
                }
            });

            if (Object.keys(activeBands).length === 0) {
                message.warning('请确保批次中包含光谱波段图像');
                return;
            }

            const blob = await blendingService.createBlendedImage(activeBands, weights);
            const url = URL.createObjectURL(blob);

            onBlendedImageUrlChange?.(url);
            message.success('图像混合生成成功');
        } catch (error) {
            message.error('混合失败');
        }
    };

    const channelOptions = [
        { label: '全彩 (灰度)', value: 'gray' },
        { label: 'R通道', value: 'r' },
        { label: 'G通道', value: 'g' },
        { label: 'B通道', value: 'b' },
    ];

    // 获取可用波段数量
    const availableBandCount = SPECTRAL_BANDS.filter(band => bandImageIds[band.name]).length;

    if (!batch) {
        return (
            <Card className="blend-panel" title="多光谱混合" size="small">
                <Alert message="请在左侧选择一个批次" type="info" showIcon />
            </Card>
        );
    }

    return (
        <Card className="blend-panel" title="多光谱混合" size="small">
            <Alert
                message={`${imageType === 'aligned' ? 'Aligned' : 'Source'} 图像模式`}
                description={`已从当前批次的 ${imageType === 'aligned' ? 'Aligned' : 'Source'} 图像中自动选择 ${availableBandCount} 个波段。您只需选择每个波段使用的通道。`}
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
            />

            <div className="band-list">
                {SPECTRAL_BANDS.map(band => {
                    const hasImage = !!bandImageIds[band.name];
                    return (
                        <div key={band.name} className={`band-item ${!hasImage ? 'disabled' : ''}`}>
                            <div className="band-header">
                                <span className="band-name" style={{ color: hasImage ? band.color : '#999' }}>
                                    {band.name}
                                </span>
                                {hasImage ? (
                                    <span className="weight-value">{(bands[band.name].weight * 100).toFixed(0)}%</span>
                                ) : (
                                    <span className="status-text" style={{ fontSize: 12, color: '#999' }}>未找到</span>
                                )}
                            </div>
                            {hasImage && (
                                <>
                                    <Row gutter={8}>
                                        <Col span={24}>
                                            <Select
                                                size="small"
                                                style={{ width: '100%' }}
                                                options={channelOptions}
                                                value={bands[band.name].channel}
                                                onChange={(v) => handleChannelChange(band.name, v)}
                                            />
                                        </Col>
                                    </Row>
                                    <Slider
                                        min={0}
                                        max={1}
                                        step={0.05}
                                        value={bands[band.name].weight}
                                        onChange={(v) => handleWeightChange(band.name, v)}
                                        trackStyle={{ background: band.color }}
                                    />
                                </>
                            )}
                        </div>
                    );
                })}
            </div>

            <Button
                type="primary"
                block
                onClick={handleBlend}
                disabled={availableBandCount === 0}
            >
                生成混合图像
            </Button>

            <Divider>光谱曲线</Divider>

            <div className="spectral-chart">
                {pixelPosition && <div className="pixel-pos">位置: ({pixelPosition.x}, {pixelPosition.y})</div>}
                <ResponsiveContainer width="100%" height={150}>
                    <LineChart data={spectralData.length ? spectralData : SPECTRAL_BANDS.map(b => ({ wavelength: b.wavelength, value: 0 }))}>
                        <XAxis dataKey="wavelength" tick={{ fontSize: 10 }} label={{ value: 'nm', fontSize: 10, position: 'right' }} />
                        <YAxis tick={{ fontSize: 10 }} domain={[0, 255]} />
                        <Tooltip />
                        <Line type="monotone" dataKey="value" stroke="#1890ff" dot strokeWidth={2} />
                    </LineChart>
                </ResponsiveContainer>
            </div>
        </Card>
    );
}
