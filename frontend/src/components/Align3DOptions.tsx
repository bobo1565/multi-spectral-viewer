import { useState, useEffect } from 'react';
import { Form, Select, InputNumber, Switch, Button, Alert, Space, Tag, message } from 'antd';
import { EyeOutlined, SettingOutlined } from '@ant-design/icons';
import { align3dService } from '../services/api';
import type { Align3DParams, RigProfileInfo } from '../services/align3dApi';
import CalibrationPanel from './CalibrationPanel';

interface Props {
    batchId: string;
    referenceImageId?: string;
    params: Align3DParams;
    onChange: (params: Align3DParams) => void;
    onPreviewDepth?: (depthB64: string, method: string, confidence: number) => void;
}

export default function Align3DOptions({
    batchId,
    referenceImageId,
    params,
    onChange,
    onPreviewDepth,
}: Props) {
    const [profiles, setProfiles] = useState<RigProfileInfo[]>([]);
    const [loadingProfiles, setLoadingProfiles] = useState(false);
    const [previewLoading, setPreviewLoading] = useState(false);
    const [calibOpen, setCalibOpen] = useState(false);

    const loadProfiles = async () => {
        setLoadingProfiles(true);
        try {
            const list = await align3dService.listProfiles();
            setProfiles(list.filter(p => !p.error));
        } catch {
            setProfiles([]);
        } finally {
            setLoadingProfiles(false);
        }
    };

    useEffect(() => {
        loadProfiles();
    }, []);

    const update = (patch: Partial<Align3DParams>) => {
        onChange({ ...params, ...patch });
    };

    const handlePreview = async () => {
        setPreviewLoading(true);
        try {
            const res = await align3dService.previewDepth(batchId, referenceImageId, params);
            onPreviewDepth?.(res.depth_b64, res.method, res.confidence);
            message.success(`深度预览已生成 (${res.method}, 置信度 ${(res.confidence * 100).toFixed(1)}%)`);
        } catch (e: unknown) {
            const err = e as { response?: { data?: { detail?: string } } };
            message.error(err.response?.data?.detail || '深度预览失败');
        } finally {
            setPreviewLoading(false);
        }
    };

    return (
        <>
            <Alert
                message="三维重建配准"
                description="通过多视图深度估计实现逐像素对齐，适合近景多深度场景。建议优先使用棋盘格标定档案；无标定文件时自动回退到自标定 + SGBM。"
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
            />

            <Form layout="vertical" size="small">
                <Form.Item label="标定档案" style={{ marginBottom: 8 }}>
                    <Space.Compact style={{ width: '100%' }}>
                        <Select
                            style={{ flex: 1 }}
                            placeholder="自动（无标定则自标定）"
                            allowClear
                            loading={loadingProfiles}
                            value={params.rig_profile || undefined}
                            onChange={(v) => update({ rig_profile: v || '' })}
                            options={profiles.map(p => ({
                                label: `${p.name} (${p.calibration_method})`,
                                value: p.name,
                            }))}
                        />
                        <Button icon={<SettingOutlined />} onClick={() => setCalibOpen(true)}>
                            标定
                        </Button>
                    </Space.Compact>
                </Form.Item>

                <Form.Item label="深度范围 (米)" style={{ marginBottom: 8 }}>
                    <Space>
                        <InputNumber
                            min={0.1}
                            max={100}
                            step={0.5}
                            value={params.depth_min ?? 0.5}
                            onChange={(v) => update({ depth_min: v ?? 0.5 })}
                            addonBefore="近"
                        />
                        <InputNumber
                            min={0.5}
                            max={200}
                            step={1}
                            value={params.depth_max ?? 20}
                            onChange={(v) => update({ depth_max: v ?? 20 })}
                            addonBefore="远"
                        />
                    </Space>
                </Form.Item>

                <Form.Item label="深度层数" style={{ marginBottom: 8 }}>
                    <InputNumber
                        min={8}
                        max={128}
                        step={4}
                        value={params.num_planes ?? 32}
                        onChange={(v) => update({ num_planes: v ?? 32 })}
                        style={{ width: '100%' }}
                    />
                </Form.Item>

                <Form.Item label="深度后端" style={{ marginBottom: 8 }}>
                    <Select
                        value={params.depth_backend ?? 'auto'}
                        onChange={(v) => update({ depth_backend: v })}
                        options={[
                            { label: '自动', value: 'auto' },
                            { label: '平面扫描 (标定)', value: 'plane_sweep' },
                            { label: 'SGBM 立体匹配', value: 'sgbm' },
                            { label: 'Torch 立体 (可选)', value: 'torch_stereo' },
                        ]}
                    />
                </Form.Item>

                <Form.Item label="代价函数" style={{ marginBottom: 8 }}>
                    <Select
                        value={params.cost_method ?? 'census'}
                        onChange={(v) => update({ cost_method: v })}
                        options={[
                            { label: 'Census (跨光谱推荐)', value: 'census' },
                            { label: 'ZNCC', value: 'zncc' },
                            { label: '梯度', value: 'gradient' },
                        ]}
                    />
                </Form.Item>

                <Form.Item style={{ marginBottom: 8 }}>
                    <Switch
                        checked={params.fallback_to_homography !== false}
                        onChange={(v) => update({ fallback_to_homography: v })}
                    />
                    <span style={{ marginLeft: 8 }}>失败时回退到单应矩阵</span>
                </Form.Item>

                <Space direction="vertical" style={{ width: '100%' }}>
                    <Button
                        icon={<EyeOutlined />}
                        onClick={handlePreview}
                        loading={previewLoading}
                        block
                    >
                        预览深度图
                    </Button>
                    {params.rig_profile && (
                        <Tag color="blue">使用标定: {params.rig_profile}</Tag>
                    )}
                </Space>
            </Form>

            <CalibrationPanel
                open={calibOpen}
                onClose={() => setCalibOpen(false)}
                batchId={batchId}
                referenceImageId={referenceImageId}
                onProfileCreated={() => loadProfiles()}
            />
        </>
    );
}
