/**
 * 批次导入对话框
 */
import { useState } from 'react';
import { Modal, Form, Input, Upload, Button, Progress, message, Steps, Space } from 'antd';
import { UploadOutlined, CheckCircleOutlined, FileImageOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd/es/upload/interface';
import { batchService } from '../services/api';
import type { BandType } from '../types';
import { BAND_TYPES, BAND_LABELS } from '../types';
import './BatchImportDialog.css';

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
    const [form] = Form.useForm();

    const resetState = () => {
        setCurrentStep(0);
        setBatchName('');
        setFiles(initialFileState);
        setUploadProgress(0);
        setUploading(false);
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

            // 上传图像
            await batchService.importImages(batch.id, fileMap);

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
                        accept="image/*"
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
