/**
 * 工具面板组件 - 包含直方图、白平衡、饱和度、通道调节
 */
import { Card, Slider, Collapse, Row, Col, Select } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer } from 'recharts';
import type { ImageInfo } from '../types';
import './ToolPanel.css';

interface Props {
    image: ImageInfo | null;
    colormap?: string;
    onColormapChange?: (colormap: string) => void;
    whiteBalance?: { r: number; g: number; b: number };
    onWhiteBalanceChange?: (wb: { r: number; g: number; b: number }) => void;
    saturation?: number;
    onSaturationChange?: (sat: number) => void;
    histogram?: { r: number[], g: number[], b: number[] } | null;
}

export default function ToolPanel({
    image,
    colormap = 'gray',
    onColormapChange,
    whiteBalance = { r: 1, g: 1, b: 1 },
    onWhiteBalanceChange,
    saturation = 1,
    onSaturationChange,
    histogram
}: Props) {

    const resetParams = () => {
        onWhiteBalanceChange?.({ r: 1, g: 1, b: 1 });
        onSaturationChange?.(1);
    };

    // 准备直方图数据
    const histogramChartData = histogram?.r?.map((_, i) => ({
        x: i,
        r: histogram.r?.[i] || 0,
        g: histogram.g?.[i] || 0,
        b: histogram.b?.[i] || 0,
    })) || [];

    const items = [
        {
            key: 'colormap',
            label: '色带',
            children: (
                <div className="slider-group">
                    <Select
                        value={colormap}
                        onChange={onColormapChange}
                        style={{ width: '100%' }}
                        options={[
                            { value: 'gray', label: '灰度' },
                            { value: 'jet', label: 'Jet' },
                            { value: 'hot', label: 'Hot' },
                            { value: 'viridis', label: 'Viridis' }
                        ]}
                    />
                    <div className="value-display" style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
                        当前色带：{colormap}
                    </div>
                </div>
            ),
        },
        {
            key: 'histogram',
            label: '直方图',
            children: (
                <div className="histogram-container">
                    {histogram ? (
                        <ResponsiveContainer width="100%" height={120}>
                            <LineChart data={histogramChartData}>
                                <XAxis dataKey="x" hide />
                                <YAxis hide />
                                <Line type="monotone" dataKey="r" stroke="#ff4d4f" dot={false} strokeWidth={1} />
                                <Line type="monotone" dataKey="g" stroke="#52c41a" dot={false} strokeWidth={1} />
                                <Line type="monotone" dataKey="b" stroke="#1890ff" dot={false} strokeWidth={1} />
                            </LineChart>
                        </ResponsiveContainer>
                    ) : (
                        <div className="no-data">暂无数据</div>
                    )}
                </div>
            ),
        },
        {
            key: 'whiteBalance',
            label: '白平衡',
            children: (
                <div className="slider-group">
                    <Row align="middle">
                        <Col span={4}><span className="label red">R</span></Col>
                        <Col span={16}>
                            <Slider min={0.1} max={4} step={0.1} value={whiteBalance.r}
                                onChange={(v) => onWhiteBalanceChange?.({ ...whiteBalance, r: v })} />
                        </Col>
                        <Col span={4}><span className="value">{whiteBalance.r.toFixed(1)}</span></Col>
                    </Row>
                    <Row align="middle">
                        <Col span={4}><span className="label green">G</span></Col>
                        <Col span={16}>
                            <Slider min={0.1} max={4} step={0.1} value={whiteBalance.g}
                                onChange={(v) => onWhiteBalanceChange?.({ ...whiteBalance, g: v })} />
                        </Col>
                        <Col span={4}><span className="value">{whiteBalance.g.toFixed(1)}</span></Col>
                    </Row>
                    <Row align="middle">
                        <Col span={4}><span className="label blue">B</span></Col>
                        <Col span={16}>
                            <Slider min={0.1} max={4} step={0.1} value={whiteBalance.b}
                                onChange={(v) => onWhiteBalanceChange?.({ ...whiteBalance, b: v })} />
                        </Col>
                        <Col span={4}><span className="value">{whiteBalance.b.toFixed(1)}</span></Col>
                    </Row>
                </div>
            ),
        },
        {
            key: 'saturation',
            label: '饱和度',
            children: (
                <div className="slider-group">
                    <Slider min={0} max={3} step={0.1} value={saturation}
                        onChange={onSaturationChange} />
                    <div className="value-display">当前值: {saturation.toFixed(1)}</div>
                </div>
            ),
        },
    ];

    return (
        <Card
            className="tool-panel"
            title="图像调节"
            extra={<ReloadOutlined onClick={resetParams} title="重置" />}
            size="small"
        >
            {image ? (
                <Collapse items={items} defaultActiveKey={['histogram']} size="small" />
            ) : (
                <div className="no-image">请先选择图像</div>
            )}
        </Card>
    );
}
