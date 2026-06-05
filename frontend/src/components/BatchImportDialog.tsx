/**
 * 批次导入对话框
 */
import { useState } from 'react';
import { Modal, Form, Input, Upload, Button, Progress, message, Steps, Space, InputNumber, Select } from 'antd';
import { UploadOutlined, CheckCircleOutlined, FileImageOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd/es/upload/interface';
import { batchService } from '../services/api';
import type { BandType, RawImageParams } from '../types';
import { BAND_TYPES, BAND_LABELS } from '../types';
import './BatchImportDialog.css';

const RAW_PARAMS_STORAGE_KEY = 'raw_image_params';

function loadSavedRawParams(): Partial<Record<BandType, RawImageParams>> {
    try {
        const saved = localStorage.getItem(RAW_PARAMS_STORAGE_KEY);
        return saved ? JSON.parse(saved) : {};
    } catch {
        return {};
    }
}

function saveRawParams(params: Partial<Record<BandType, RawImageParams>>) {
    try {
        localStorage.setItem(RAW_PARAMS_STORAGE_KEY, JSON.stringify(params));
    } catch {
        // ignore storage errors
    }
}

interface BatchImportDialogProps {
    open: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

interface FileState {
    rgb: UploadFile | null;
    '570nm': UploadFile | null;
    '650nm': UploadFile | null;
    '730nm': UploadFile | null;
    '850nm': UploadFile | null;
}

const initialFileState: FileState = {
    rgb: null,
    '570nm': null,
    '650nm': null,
    '730nm': null,
    '850nm': null,
};

export function BatchImportDialog({ open, onClose, onSuccess }: BatchImportDialogProps) {
    const [currentStep, setCurrentStep] = useState(0);
    const [batchName, setBatchName] = useState('');
    const [files, setFiles] = useState<FileState>(initialFileState);
    const [uploading, setUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    const [rawParams, setRawParams] = useState<Partial<Record<BandType, RawImageParams>>>(loadSavedRawParams());
    const [form] = Form.useForm();

    const isRawFile = (file: UploadFile | null): boolean => {
        if (!file?.name) return false;
        return file.name.toLowerCase().endsWith('.raw');
    };

    const updateRawParam = (band: BandType, key: keyof RawImageParams, value: any) => {
        setRawParams(prev => {
            const next = {
                ...prev,
                [band]: {
                    width: prev[band]?.width || 0,
                    height: prev[band]?.height || 0,
                    bit_depth: prev[band]?.bit_depth || 8,
                    channels: prev[band]?.channels || 1,
                    byte_order: prev[band]?.byte_order || 'little',
                    [key]: value,
                } as RawImageParams
            };
            saveRawParams(next);
            return next;
        });
    };

    const resetState = () => {
        setCurrentStep(0);
        setBatchName('');
        setFiles(initialFileState);
        setUploadProgress(0);
        setUploading(false);
        setRawParams(loadSavedRawParams());
        form.resetFields();
    };

    const handleClose = () => {
        resetState();
        onClose();
    };

    const handleNextStep = async () => {
        if (currentStep === 0) {
            try {
                await form.validateFields(['batchName']);
                setCurrentStep(1);
            } catch {
                // validation failed
            }
        } else if (currentStep === 1) {
            // 检查至少有一个文件
            const hasFile = Object.values(files).some(f => f !== null);
            if (!hasFile) {
                message.warning('请至少选择一个波段图像');
                return;
            }
            setCurrentStep(2);
            await handleUpload();
        }
    };

    const handlePrevStep = () => {
        if (currentStep > 0) {
            setCurrentStep(currentStep - 1);
        }
    };

    const handleUpload = async () => {
        setUploading(true);
        setUploadProgress(0);

        try {
            // 验证 RAW 文件参数
            for (const band of BAND_TYPES) {
                const uploadFile = files[band];
                if (uploadFile && isRawFile(uploadFile)) {
                    const params = rawParams[band];
                    if (!params || !params.width || !params.height) {
                        message.error(`${BAND_LABELS[band]} 是 RAW 文件，请填写宽度和高度`);
                        setUploading(false);
                        setCurrentStep(1);
                        return;
                    }
                }
            }

            // 创建批次
            setUploadProgress(10);
            const batch = await batchService.createBatch(batchName);

            // 准备文件对象
            const fileMap: Partial<Record<BandType, File | null>> = {};
            for (const band of BAND_TYPES) {
                const uploadFile = files[band];
                if (uploadFile && uploadFile.originFileObj) {
                    fileMap[band] = uploadFile.originFileObj;
                }
            }

            setUploadProgress(30);

            // 上传图像（附带 RAW 参数）
            const rawParamsToSend: Partial<Record<BandType, RawImageParams>> = {};
            for (const band of BAND_TYPES) {
                if (isRawFile(files[band]) && rawParams[band]) {
                    rawParamsToSend[band] = rawParams[band];
                }
            }
            await batchService.importImages(batch.id, fileMap, rawParamsToSend);

            setUploadProgress(100);
            message.success('批次导入成功!');

            setTimeout(() => {
                onSuccess();
                handleClose();
            }, 500);

        } catch (error: any) {
            message.error(error?.response?.data?.detail || '导入失败');
            setCurrentStep(1);
            setUploading(false);
        }
    };

    const handleFileChange = (band: BandType, file: UploadFile | null) => {
        setFiles(prev => ({
            ...prev,
            [band]: file
        }));
        if (!file || !isRawFile(file)) {
            setRawParams(prev => {
                const next = { ...prev };
                delete next[band];
                return next;
            });
        } else {
            // RAW 文件：自动加载该波段的已保存参数
            const saved = loadSavedRawParams()[band];
            if (saved) {
                setRawParams(prev => ({ ...prev, [band]: saved }));
            }
        }
    };

    const renderStep0 = () => (
        <Form form={form} layout="vertical">
            <Form.Item
                name="batchName"
                label="批次名称"
                rules={[{ required: true, message: '请输入批次名称' }]}
            >
                <Input
                    placeholder="例如：实验区A-2026年2月"
                    value={batchName}
                    onChange={e => setBatchName(e.target.value)}
                    size="large"
                />
            </Form.Item>
        </Form>
    );

    const renderStep1 = () => (
        <div className="band-upload-grid">
            {BAND_TYPES.map(band => (
                <div key={band} className="band-upload-item">
                    <div className="band-label">
                        <FileImageOutlined />
                        <span>{BAND_LABELS[band]}</span>
                    </div>
                    <Upload
                        maxCount={1}
                        beforeUpload={() => false}
                        accept="image/*,.raw"
                        fileList={files[band] ? [files[band]!] : []}
                        onChange={({ fileList }) => {
                            handleFileChange(band, fileList[0] || null);
                        }}
                        onRemove={() => {
                            handleFileChange(band, null);
                        }}
                    >
                        <Button icon={<UploadOutlined />}>
                            {files[band] ? '更换文件' : '选择文件'}
                        </Button>
                    </Upload>
                    {isRawFile(files[band]) && (
                        <div className="raw-params-form">
                            <div className="raw-params-grid">
                                <div>
                                    <label>宽度 (px)</label>
                                    <InputNumber size="small" min={1} style={{ width: '100%' }}
                                        value={rawParams[band]?.width}
                                        onChange={v => updateRawParam(band, 'width', v || 0)} />
                                </div>
                                <div>
                                    <label>高度 (px)</label>
                                    <InputNumber size="small" min={1} style={{ width: '100%' }}
                                        value={rawParams[band]?.height}
                                        onChange={v => updateRawParam(band, 'height', v || 0)} />
                                </div>
                                <div>
                                    <label>位深</label>
                                    <Select size="small" style={{ width: '100%' }}
                                        value={rawParams[band]?.bit_depth || 8}
                                        onChange={v => updateRawParam(band, 'bit_depth', v)}>
                                        <Select.Option value={8}>8-bit</Select.Option>
                                        <Select.Option value={12}>12-bit</Select.Option>
                                        <Select.Option value={16}>16-bit</Select.Option>
                                    </Select>
                                </div>
                                <div>
                                    <label>通道数</label>
                                    <Select size="small" style={{ width: '100%' }}
                                        value={rawParams[band]?.channels || 1}
                                        onChange={v => updateRawParam(band, 'channels', v)}>
                                        <Select.Option value={1}>灰度 (1)</Select.Option>
                                        <Select.Option value={3}>RGB (3)</Select.Option>
                                    </Select>
                                </div>
                            </div>
                            <div style={{ marginTop: 8 }}>
                                <label>字节序</label>
                                <Select size="small" style={{ width: '100%' }}
                                    value={rawParams[band]?.byte_order || 'little'}
                                    onChange={v => updateRawParam(band, 'byte_order', v)}>
                                    <Select.Option value="little">Little Endian</Select.Option>
                                    <Select.Option value="big">Big Endian</Select.Option>
                                </Select>
                            </div>
                        </div>
                    )}
                </div>
            ))}
        </div>
    );

    const renderStep2 = () => (
        <div className="upload-progress">
            <Progress
                percent={uploadProgress}
                status={uploadProgress === 100 ? 'success' : 'active'}
            />
            <p style={{ textAlign: 'center', marginTop: 16 }}>
                {uploadProgress < 100 ? '正在上传图像...' : '上传完成!'}
            </p>
        </div>
    );

    const steps = [
        { title: '命名批次', description: '输入批次名称' },
        { title: '选择图像', description: '选择各波段图像' },
        { title: '上传', description: '等待上传完成' },
    ];

    return (
        <Modal
            title="导入图像批次"
            open={open}
            onCancel={handleClose}
            width={600}
            footer={
                currentStep < 2 ? (
                    <Space>
                        {currentStep > 0 && (
                            <Button onClick={handlePrevStep}>
                                上一步
                            </Button>
                        )}
                        <Button type="primary" onClick={handleNextStep}>
                            {currentStep === 1 ? '开始上传' : '下一步'}
                        </Button>
                    </Space>
                ) : uploadProgress === 100 ? (
                    <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleClose}>
                        完成
                    </Button>
                ) : null
            }
            maskClosable={!uploading}
            closable={!uploading}
        >
            <Steps
                current={currentStep}
                items={steps}
                style={{ marginBottom: 24 }}
                size="small"
            />

            {currentStep === 0 && renderStep0()}
            {currentStep === 1 && renderStep1()}
            {currentStep === 2 && renderStep2()}
        </Modal>
    );
}
