/**
 * 植被指数面板组件
 */
import { useState, useEffect } from 'react';
import { Card, Select, Button, Row, Col, Statistic, Divider, Tag } from 'antd';
import { vegetationService } from '../services/api';
import type { ImageInfo, VegetationIndexInfo } from '../types';
import './VegetationPanel.css';

interface Props {
    images: ImageInfo[];
    onBlendedImageUrlChange?: (url: string | null) => void;
}

// 波段类型（用于后续扩展）
// const BAND_TYPES = ['NIR', 'RED', 'GREEN', 'BLUE', 'RED_EDGE'];

// 色带选项
const COLORMAP_OPTIONS = [
    { label: 'RdYlGn (红黄绿)', value: 'RdYlGn' },
    { label: 'Viridis', value: 'Viridis' },
    { label: 'Plasma', value: 'Plasma' },
    { label: 'Turbo', value: 'Turbo' },
];

export default function VegetationPanel({ images, onBlendedImageUrlChange }: Props) {
    const [indices, setIndices] = useState<VegetationIndexInfo[]>([]);
    const [selectedIndex, setSelectedIndex] = useState<string>('NDVI');
    const [bandMapping, setBandMapping] = useState<Record<string, { imageId: string; channel: string }>>({});
    const [colormap, setColormap] = useState('RdYlGn');
    const [result, setResult] = useState<{ url: string; stats: Record<string, number> } | null>(null);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        loadIndices();
    }, []);

    // 自动匹配波段
    useEffect(() => {
        const current = indices.find(i => i.name === selectedIndex);
        if (!current || !images.length) return;

        const newMapping = { ...bandMapping };
        let hasChanges = false;

        current.required_bands.forEach(band => {
            // 如果该波段尚未选择图像，尝试自动匹配
            if (!newMapping[band]?.imageId) {
                let keyword = '';
                // G->570nm，R->650nm，RE->730nm，NIR->850nm
                if (band === 'NIR') keyword = '850';
                else if (band === 'RED') keyword = '650';
                else if (band === 'GREEN') keyword = '570';
                else if (band === 'RED_EDGE') keyword = '730';

                if (keyword) {
                    const match = images.find(img => img.filename.includes(keyword));
                    if (match) {
                        newMapping[band] = { imageId: match.id, channel: 'r' };
                        hasChanges = true;
                    }
                }
            }
        });

        if (hasChanges) {
            setBandMapping(newMapping);
        }
    }, [selectedIndex, images, indices]);

    const loadIndices = async () => {
        try {
            const data = await vegetationService.listIndices();
            setIndices(data);
        } catch (error) {
            console.error('Failed to load indices:', error);
            // 使用默认值
            setIndices([
                { name: 'NDVI', full_name: '归一化差值植被指数', formula: '(NIR-RED)/(NIR+RED)', required_bands: ['NIR', 'RED'] },
                { name: 'GNDVI', full_name: '绿色归一化差值植被指数', formula: '(NIR-GREEN)/(NIR+GREEN)', required_bands: ['NIR', 'GREEN'] },
                { name: 'NDRE', full_name: '归一化差值红边指数', formula: '(NIR-RED_EDGE)/(NIR+RED_EDGE)', required_bands: ['NIR', 'RED_EDGE'] },
                { name: 'SAVI', full_name: '土壤调节植被指数', formula: '(NIR-RED)*1.5/(NIR+RED+0.5)', required_bands: ['NIR', 'RED'] },
            ]);
        }
    };

    const handleBandChange = (bandType: string, imageId: string, channel: string) => {
        setBandMapping(prev => ({
            ...prev,
            [bandType]: { imageId, channel }
        }));
    };

    const handleCalculate = async () => {
        setLoading(true);
        try {
            // 构造后端需要的波段映射格式
            const bands: any = {};
            let missing = false;

            currentIndex?.required_bands.forEach(b => {
                if (!bandMapping[b]) {
                    missing = true;
                } else {
                    bands[b] = {
                        image_id: bandMapping[b].imageId,
                        channel: bandMapping[b].channel
                    };
                }
            });

            if (missing) return;

            const data = await vegetationService.calculateIndex(selectedIndex, bands, colormap);
            console.log('Calculated Index Data:', data);

            // 结果 URL 需要补全 host
            const fullUrl = `http://localhost:8000${data.result_url}`;
            console.log('Result Full URL:', fullUrl);
            setResult({
                url: fullUrl,
                stats: data.statistics
            });

            // 通知 ImageViewer 显示结果
            onBlendedImageUrlChange?.(fullUrl);
        } catch (error) {
            console.error('Calculation failed:', error);
        } finally {
            setLoading(false);
        }
    };

    const currentIndex = indices.find(i => i.name === selectedIndex);

    const imageOptions = images.map(img => ({
        label: img.filename,
        value: img.id,
    }));

    const channelOptions = [
        { label: 'R', value: 'r' },
        { label: 'G', value: 'g' },
        { label: 'B', value: 'b' },
    ];

    return (
        <Card className="vegetation-panel" title="植被指数" size="small">
            <div className="index-selector">
                <Select
                    style={{ width: '100%' }}
                    value={selectedIndex}
                    onChange={setSelectedIndex}
                    options={indices.map(i => ({ label: i.name, value: i.name }))}
                />
                {currentIndex && (
                    <div className="index-info">
                        <div className="index-name">{currentIndex.full_name}</div>
                        <code className="formula">{currentIndex.formula}</code>
                        <div className="required-bands">
                            需要波段: {currentIndex.required_bands.map(b => (
                                <Tag key={b} color="blue">{b}</Tag>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            <Divider>波段映射</Divider>

            <div className="band-mapping">
                {currentIndex?.required_bands.map(bandType => (
                    <div key={bandType} className="mapping-row">
                        <div className="band-type">{bandType}</div>
                        <Row gutter={8}>
                            <Col span={14}>
                                <Select
                                    size="small"
                                    placeholder="选择图像"
                                    style={{ width: '100%' }}
                                    options={imageOptions}
                                    value={bandMapping[bandType]?.imageId}
                                    onChange={(v) => handleBandChange(bandType, v, bandMapping[bandType]?.channel || 'r')}
                                />
                            </Col>
                            <Col span={10}>
                                <Select
                                    size="small"
                                    style={{ width: '100%' }}
                                    options={channelOptions}
                                    value={bandMapping[bandType]?.channel || 'r'}
                                    onChange={(v) => handleBandChange(bandType, bandMapping[bandType]?.imageId || '', v)}
                                />
                            </Col>
                        </Row>
                    </div>
                ))}
            </div>

            <div className="colormap-selector">
                <span>色带:</span>
                <Select
                    size="small"
                    style={{ flex: 1 }}
                    options={COLORMAP_OPTIONS}
                    value={colormap}
                    onChange={setColormap}
                />
            </div>

            <Button type="primary" block onClick={handleCalculate} loading={loading}>
                计算 {selectedIndex}
            </Button>

            {result && (
                <>
                    <Divider>统计结果</Divider>
                    <Row gutter={16}>
                        <Col span={12}>
                            <Statistic title="最小值" value={result.stats.min} precision={3} />
                        </Col>
                        <Col span={12}>
                            <Statistic title="最大值" value={result.stats.max} precision={3} />
                        </Col>
                        <Col span={12}>
                            <Statistic title="平均值" value={result.stats.mean} precision={3} />
                        </Col>
                        <Col span={12}>
                            <Statistic title="标准差" value={result.stats.std} precision={3} />
                        </Col>
                    </Row>
                </>
            )}
        </Card>
    );
}
