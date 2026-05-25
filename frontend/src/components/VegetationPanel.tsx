/**
 * 植被指数面板组件
 */
import { useState, useEffect, useMemo } from 'react';
import { Card, Select, Button, Row, Col, Statistic, Divider, Tag, message, Modal, Input, Slider, Radio } from 'antd';
import { vegetationService } from '../services/api';
import { batchService } from '../services/api';
import { API_BASE } from '../services/api';
import type { ImageInfo, VegetationIndexInfo, BatchInfo } from '../types';
import { BAND_TYPES, BAND_LABELS } from '../types';
import './VegetationPanel.css';

interface CompareLayer {
    url: string;
    opacity: number;
    clipPath?: string;
}

interface Props {
    images: ImageInfo[];
    batches?: BatchInfo[];
    batchId?: string;
    onBlendedImageUrlChange?: (url: string | null) => void;
    onGeneratedImageAdded?: () => Promise<void>;
    onCompareChange?: (layer: CompareLayer | null) => void;
}

// 波段类型（用于后续扩展）
// const BAND_TYPES = ['NIR', 'RED', 'GREEN', 'BLUE', 'RED_EDGE'];

// 色带选项
const COLORMAP_OPTIONS = [
    { label: 'RdYlGn (红黄绿)', value: 'RdYlGn' },
    { label: 'Viridis', value: 'Viridis' },
    { label: 'Plasma', value: 'Plasma' },
    { label: 'Turbo', value: 'Turbo' },
    { label: 'Gray (灰度)', value: 'Gray' },
];

export default function VegetationPanel({ images, batches, batchId, onBlendedImageUrlChange, onGeneratedImageAdded, onCompareChange }: Props) {
    const [indices, setIndices] = useState<VegetationIndexInfo[]>([]);
    const [selectedIndex, setSelectedIndex] = useState<string>('NDVI');
    const [bandMapping, setBandMapping] = useState<Record<string, { imageId: string; channel: string }>>({});
    const [colormap, setColormap] = useState('RdYlGn');
    const [result, setResult] = useState<{ url: string; stats: Record<string, number> } | null>(null);
    const [loading, setLoading] = useState(false);
    const [saveDialogOpen, setSaveDialogOpen] = useState(false);
    const [saveName, setSaveName] = useState('');
    const [calcMeta, setCalcMeta] = useState<{
        filepath: string; width: number; height: number; channels: number; fileSize: number;
        indexName: string;
    } | null>(null);

    const getEffectiveBatchId = (): string | undefined => {
        if (batchId) return batchId;
        if (!batches) return undefined;
        for (const b of Object.values(bandMapping)) {
            if (!b.imageId) continue;
            const found = batches.find(batch => {
                for (const bt of BAND_TYPES) {
                    const img = batch.source_images?.[bt] || batch.aligned_images?.[bt] || batch.images?.[bt];
                    if (img?.id === b.imageId) return true;
                }
                if ((batch.generated_images || []).some(g => g.id === b.imageId)) return true;
                return false;
            });
            if (found) return found.id;
        }
        return undefined;
    };

    // 图像比对状态
    const [compareSelectedKey, setCompareSelectedKey] = useState<string>('');
    const [compareMode, setCompareMode] = useState<'off' | 'slider' | 'curtain'>('off');
    const [compareValue, setCompareValue] = useState(50);

    // 收集当前批次中可用于比对的所有图像
    const compareOptions = useMemo(() => {
        const options: { key: string; label: string; url: string }[] = [{ key: '', label: '关闭比对', url: '' }];
        if (!batches) return options;
        const targetBatchId = getEffectiveBatchId();
        const batch = batches.find(b => b.id === targetBatchId);
        if (!batch) return options;
        BAND_TYPES.forEach(bt => {
            const img = batch.aligned_images?.[bt];
            if (img) {
                const fullUrl = img.url.startsWith('http') ? img.url : `${API_BASE}${img.url}`;
                options.push({ key: `aligned-${bt}`, label: `[Aligned] ${BAND_LABELS[bt]}`, url: fullUrl });
            }
        });
        (batch.generated_images || []).forEach(gImg => {
            const fullUrl = gImg.url.startsWith('http') ? gImg.url : `${API_BASE}${gImg.url}`;
            options.push({ key: `gen-${gImg.id}`, label: `[Generated] ${gImg.filename}`, url: fullUrl });
        });
        return options;
    }, [batches, bandMapping, batchId]);

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

    // 同步比对状态到父组件
    useEffect(() => {
        if (!onCompareChange) return;
        if (compareMode === 'off' || !compareSelectedKey) {
            onCompareChange(null);
            return;
        }
        const opt = compareOptions.find(o => o.key === compareSelectedKey);
        if (!opt || !opt.url) {
            onCompareChange(null);
            return;
        }
        if (compareMode === 'slider') {
            onCompareChange({ url: opt.url, opacity: compareValue / 100 });
        } else {
            onCompareChange({
                url: opt.url,
                opacity: 1,
                clipPath: `inset(0 ${100 - compareValue}% 0 0)`
            });
        }
    }, [compareMode, compareSelectedKey, compareValue, compareOptions, onCompareChange]);

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
        setResult(null);
        setCalcMeta(null);
        try {
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

            let fullUrl: string;
            if (data.result_url.startsWith('http')) {
                fullUrl = data.result_url;
            } else {
                fullUrl = `${API_BASE}${data.result_url}`;
            }
            console.log('Result Full URL:', fullUrl);
            setResult({
                url: fullUrl,
                stats: data.statistics
            });
            setCalcMeta({
                filepath: data.result_filepath || '',
                width: data.width || 0,
                height: data.height || 0,
                channels: data.channels || 3,
                fileSize: data.file_size || 0,
                indexName: selectedIndex,
            });

            onBlendedImageUrlChange?.(fullUrl);
        } catch (error) {
            console.error('Calculation failed:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        const targetBatchId = getEffectiveBatchId();
        if (!targetBatchId) {
            message.warning('无法确定目标批次，请在左侧树中先选择一个批次');
            return;
        }
        if (!calcMeta || !saveName.trim()) return;

        setLoading(true);
        try {
            await batchService.saveGeneratedImage(
                targetBatchId,
                calcMeta.filepath,
                saveName.trim(),
                calcMeta.width,
                calcMeta.height,
                calcMeta.channels,
                calcMeta.fileSize
            );
            setSaveDialogOpen(false);
            setSaveName('');
            message.success(`已保存 "${saveName.trim()}" 到 Generated 目录`);
            if (onGeneratedImageAdded) {
                await onGeneratedImageAdded();
            }
            window.dispatchEvent(new CustomEvent('generated-image-added', {
                detail: { batchId: targetBatchId }
            }));
        } catch (error) {
            console.error('Save failed:', error);
            message.error('保存失败');
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

            {result && calcMeta && (
                <>
                    <Divider />
                    <Button
                        type="default"
                        block
                        onClick={() => {
                            setSaveName(`${calcMeta.indexName}_${colormap}.png`);
                            setSaveDialogOpen(true);
                        }}
                    >
                        保存到批次
                    </Button>
                </>
            )}

            <Divider>图像比对</Divider>

            <Select
                value={compareSelectedKey}
                onChange={(v) => {
                    setCompareSelectedKey(v);
                    if (!v) setCompareMode('off');
                }}
                options={compareOptions.map(o => ({ value: o.key, label: o.label }))}
                style={{ width: '100%', marginBottom: 8 }}
                placeholder="选择比对图像"
            />

            {compareSelectedKey && (
                <>
                    <Radio.Group
                        value={compareMode}
                        onChange={(e) => setCompareMode(e.target.value)}
                        size="small"
                        style={{ marginBottom: 8 }}
                    >
                        <Radio.Button value="slider">百分比过渡</Radio.Button>
                        <Radio.Button value="curtain">卷帘对比</Radio.Button>
                    </Radio.Group>

                    <div style={{ padding: '0 4px' }}>
                        <span style={{ fontSize: 12, color: '#888' }}>
                            {compareMode === 'slider' ? `透明度: ${compareValue}%` : `分割位置: ${compareValue}%`}
                        </span>
                        <Slider
                            min={0}
                            max={100}
                            value={compareValue}
                            onChange={(v) => setCompareValue(v)}
                            tooltip={{ formatter: (v) => `${v}%` }}
                        />
                    </div>
                </>
            )}

            <Modal
                title="保存生成图像"
                open={saveDialogOpen}
                onOk={handleSave}
                onCancel={() => setSaveDialogOpen(false)}
                okText="保存"
                cancelText="取消"
                confirmLoading={loading}
                destroyOnHidden
            >
                <div style={{ marginBottom: 8 }}>
                    <span>图像名称：</span>
                </div>
                <Input
                    value={saveName}
                    onChange={(e) => setSaveName(e.target.value)}
                    onPressEnter={handleSave}
                    placeholder="输入图像名称"
                />
            </Modal>

            {result && result.stats && (
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
