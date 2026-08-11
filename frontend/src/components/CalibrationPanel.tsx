import { useState } from 'react';
import { Modal, Tabs, Form, Input, Button, Upload, message, Alert, Select } from 'antd';
import { UploadOutlined, ThunderboltOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd/es/upload/interface';
import { align3dService } from '../services/api';

interface Props {
    open: boolean;
    onClose: () => void;
    batchId?: string;
    referenceImageId?: string;
    onProfileCreated?: (profileName: string) => void;
}

const BAND_OPTIONS = [
    { label: 'RGB', value: 'rgb' },
    { label: '560nm', value: '560nm' },
    { label: '650nm', value: '650nm' },
    { label: '730nm', value: '730nm' },
    { label: '850nm', value: '850nm' },
];

export default function CalibrationPanel({
    open,
    onClose,
    batchId,
    referenceImageId,
    onProfileCreated,
}: Props) {
    const [profileName, setProfileName] = useState('default');
    const [referenceBand, setReferenceBand] = useState('rgb');
    const [fileList, setFileList] = useState<UploadFile[]>([]);
    const [bandLabels, setBandLabels] = useState<string[]>([]);
    const [loading, setLoading] = useState(false);

    const handleCheckerboardSubmit = async () => {
        if (fileList.length < 3) {
            message.warning('请至少上传 3 张标定板图像');
            return;
        }
        const files = fileList.map(f => f.originFileObj).filter(Boolean) as File[];
        const labels = bandLabels.length === files.length
            ? bandLabels
            : files.map((_, i) => BAND_OPTIONS[i % BAND_OPTIONS.length].value);

        const bands = [...new Set(labels)];
        setLoading(true);
        try {
            const res = await align3dService.createCheckerboardProfile(
                profileName,
                referenceBand,
                bands,
                files,
                labels,
            );
            message.success(res.message);
            onProfileCreated?.(res.profile_name);
            onClose();
        } catch (e: unknown) {
            const err = e as { response?: { data?: { detail?: string } } };
            message.error(err.response?.data?.detail || '标定失败');
        } finally {
            setLoading(false);
        }
    };

    const handleSelfcalib = async () => {
        if (!batchId) {
            message.warning('请先选择批次');
            return;
        }
        setLoading(true);
        try {
            const res = await align3dService.createSelfcalibProfile(
                batchId,
                profileName,
                referenceImageId,
            );
            message.success(res.message);
            onProfileCreated?.(res.profile_name);
            onClose();
        } catch (e: unknown) {
            const err = e as { response?: { data?: { detail?: string } } };
            message.error(err.response?.data?.detail || '自标定失败');
        } finally {
            setLoading(false);
        }
    };

    const tabItems = [
        {
            key: 'checkerboard',
            label: '棋盘格标定',
            children: (
                <>
                    <Alert
                        message="推荐方式"
                        description="使用标定板拍摄 15-30 组图像，5 个镜头同步拍摄。每张图像需标注所属波段。"
                        type="info"
                        showIcon
                        style={{ marginBottom: 16 }}
                    />
                    <Form layout="vertical">
                        <Form.Item label="档案名称">
                            <Input value={profileName} onChange={e => setProfileName(e.target.value)} />
                        </Form.Item>
                        <Form.Item label="参考波段">
                            <Select
                                value={referenceBand}
                                onChange={setReferenceBand}
                                options={BAND_OPTIONS}
                            />
                        </Form.Item>
                        <Form.Item label="标定图像（需标注波段）">
                            <Upload
                                multiple
                                beforeUpload={() => false}
                                fileList={fileList}
                                onChange={({ fileList: fl }) => {
                                    setFileList(fl);
                                    setBandLabels(fl.map((_, i) => BAND_OPTIONS[i % BAND_OPTIONS.length].value));
                                }}
                            >
                                <Button icon={<UploadOutlined />}>选择标定板图像</Button>
                            </Upload>
                        </Form.Item>
                        {fileList.length > 0 && (
                            <Form.Item label="各图像波段标签">
                                {fileList.map((f, i) => (
                                    <div key={f.uid} style={{ marginBottom: 4, display: 'flex', gap: 8, alignItems: 'center' }}>
                                        <span style={{ flex: 1, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                            {f.name}
                                        </span>
                                        <Select
                                            size="small"
                                            style={{ width: 100 }}
                                            value={bandLabels[i] || 'rgb'}
                                            onChange={(v) => {
                                                const next = [...bandLabels];
                                                next[i] = v;
                                                setBandLabels(next);
                                            }}
                                            options={BAND_OPTIONS}
                                        />
                                    </div>
                                ))}
                            </Form.Item>
                        )}
                        <Button
                            type="primary"
                            icon={<ThunderboltOutlined />}
                            loading={loading}
                            onClick={handleCheckerboardSubmit}
                            block
                        >
                            创建标定档案
                        </Button>
                    </Form>
                </>
            ),
        },
        {
            key: 'selfcalib',
            label: '自标定（从批次）',
            children: (
                <>
                    <Alert
                        message="快速回退方式"
                        description="从当前批次的 source 图像自动估计相机位姿。精度低于棋盘格标定，适合无标定板的场景。"
                        type="warning"
                        showIcon
                        style={{ marginBottom: 16 }}
                    />
                    <Form layout="vertical">
                        <Form.Item label="档案名称">
                            <Input value={profileName} onChange={e => setProfileName(e.target.value)} />
                        </Form.Item>
                        <Button
                            type="primary"
                            icon={<ThunderboltOutlined />}
                            loading={loading}
                            disabled={!batchId}
                            onClick={handleSelfcalib}
                            block
                        >
                            从当前批次自标定
                        </Button>
                    </Form>
                </>
            ),
        },
    ];

    return (
        <Modal
            title="相机标定"
            open={open}
            onCancel={onClose}
            footer={null}
            width={520}
            destroyOnClose
        >
            <Tabs items={tabItems} />
        </Modal>
    );
}
