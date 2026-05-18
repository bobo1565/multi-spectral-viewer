/**
 * 摄像头管理：列表、手动添加、扫描发现、从扫描结果添加、同步替换、波段绑定
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
    Button,
    Table,
    Modal,
    Form,
    Input,
    Select,
    message,
    Popconfirm,
    Progress,
    Tag,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
    ArrowLeftOutlined,
    PlusOutlined,
    RadarChartOutlined,
    ReloadOutlined,
    SyncOutlined,
    DeleteOutlined,
} from '@ant-design/icons';

import { cameraApi } from '../services/cameraApi';
import type { CameraInfo, CameraScanStatus, BandType } from '../types';
import { BAND_TYPES, BAND_LABELS } from '../types';
import './CameraManager.css';

interface CameraManagerProps {
    onBack: () => void;
}

const SCAN_POLL_MS = 1000;

const CameraManager: React.FC<CameraManagerProps> = ({ onBack }) => {
    const [cameras, setCameras] = useState<CameraInfo[]>([]);
    const [loading, setLoading] = useState(false);
    const [scanStatus, setScanStatus] = useState<CameraScanStatus | null>(null);
    const [addOpen, setAddOpen] = useState(false);
    const [addForm] = Form.useForm();

    const loadCameras = useCallback(async () => {
        setLoading(true);
        try {
            const data = await cameraApi.list();
            setCameras(data);
        } catch {
            message.error('加载摄像头列表失败');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadCameras();
    }, [loadCameras]);

    // 扫描进行中时轮询状态
    useEffect(() => {
        let timer: ReturnType<typeof setInterval> | undefined;
        const poll = async () => {
            try {
                const st = await cameraApi.scanStatus();
                setScanStatus(st);
                if (!st.is_scanning) {
                    if (timer) clearInterval(timer);
                    timer = undefined;
                }
            } catch {
                /* ignore */
            }
        };
        if (scanStatus?.is_scanning) {
            timer = setInterval(poll, SCAN_POLL_MS);
        }
        return () => {
            if (timer) clearInterval(timer);
        };
    }, [scanStatus?.is_scanning]);

    const handleStartScan = async () => {
        try {
            const st = await cameraApi.startScan();
            setScanStatus(st);
            message.info(st.is_scanning ? '扫描已启动' : '扫描已在进行中');
        } catch {
            message.error('启动扫描失败');
        }
    };

    const handleRefreshScanStatus = async () => {
        try {
            const st = await cameraApi.scanStatus();
            setScanStatus(st);
        } catch {
            /* ignore */
        }
    };

    const handleRefreshSavedCameras = async () => {
        await loadCameras();
        message.success('已刷新已保存摄像头列表');
    };

    const handleSyncAll = () => {
        Modal.confirm({
            title: '用扫描结果替换全部摄像头？',
            content: '将删除当前已保存的所有摄像头，并以最近一次扫描结果覆盖。正在播放的流会停止。',
            okText: '确定同步',
            cancelText: '取消',
            okButtonProps: { danger: true },
            onOk: async () => {
                try {
                    const res = await cameraApi.syncFromScan();
                    message.success(`已同步 ${res.count} 台摄像头`);
                    await loadCameras();
                } catch (e: any) {
                    message.error(e?.response?.data?.detail || '同步失败');
                }
            },
        });
    };

    const handleAddFromScan = async (match: string) => {
        try {
            await cameraApi.addFromScan(match);
            message.success('已添加到列表');
            await loadCameras();
        } catch (e: any) {
            message.error(e?.response?.data?.detail || '添加失败');
        }
    };

    const handleDelete = async (id: string) => {
        try {
            await cameraApi.remove(id);
            message.success('已删除');
            await loadCameras();
        } catch {
            message.error('删除失败');
        }
    };

    const handleBandChange = async (camId: string, band: BandType | null) => {
        try {
            await cameraApi.setBand(camId, band);
            await loadCameras();
        } catch {
            message.error('设置波段失败');
        }
    };

    const submitManualAdd = async () => {
        try {
            const v = await addForm.validateFields();
            await cameraApi.create({
                name: v.name,
                stream_url: v.stream_url,
                username: v.username || undefined,
                password: v.password || undefined,
                band_type: v.band_type || undefined,
            });
            message.success('已添加');
            setAddOpen(false);
            addForm.resetFields();
            await loadCameras();
        } catch (e: any) {
            if (e?.errorFields) return;
            message.error(e?.response?.data?.detail || '添加失败');
        }
    };

    const scanResults = scanStatus?.last_result ?? [];
    const scanLogs = scanStatus?.scan_logs ?? [];
    const scanning = scanStatus?.is_scanning ?? false;

    const camColumns: ColumnsType<CameraInfo> = [
        { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
        { title: 'IP', dataIndex: 'ip', key: 'ip', width: 130 },
        {
            title: '流地址',
            dataIndex: 'stream_url',
            key: 'stream_url',
            ellipsis: true,
            render: (t: string) => <span title={t}>{t}</span>,
        },
        {
            title: '波段',
            key: 'band',
            width: 150,
            render: (_, row) => (
                <Select
                    size="small"
                    style={{ width: 140 }}
                    value={row.band_type || ''}
                    onChange={(v) => handleBandChange(row.id, (v || null) as BandType | null)}
                    options={[
                        { value: '', label: '未绑定' },
                        ...BAND_TYPES.map((b) => ({ value: b, label: BAND_LABELS[b] })),
                    ]}
                />
            ),
        },
        {
            title: '状态',
            key: 'st',
            width: 100,
            render: (_, row) =>
                row.is_connected ? <Tag color="green">在线</Tag> : <Tag>离线</Tag>,
        },
        {
            title: '操作',
            key: 'act',
            width: 80,
            render: (_, row) => (
                <Popconfirm title="确定删除？" onConfirm={() => handleDelete(row.id)}>
                    <Button type="link" danger size="small" icon={<DeleteOutlined />} />
                </Popconfirm>
            ),
        },
    ];

    const scanColumns: ColumnsType<Record<string, any>> = [
        { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
        { title: 'IP', dataIndex: 'ip', key: 'ip', width: 130 },
        {
            title: '流',
            dataIndex: 'stream_url',
            key: 'stream_url',
            ellipsis: true,
        },
        {
            title: '操作',
            key: 'add',
            width: 100,
            render: (_, row) => (
                <Button
                    type="link"
                    size="small"
                    onClick={() => handleAddFromScan(row.id || row.ip)}
                    disabled={!row.stream_url}
                >
                    添加
                </Button>
            ),
        },
    ];

    return (
        <div className="camera-manager">
            <div className="camera-manager-section">
                <h3>
                    <Button type="text" icon={<ArrowLeftOutlined />} onClick={onBack} />
                    摄像头管理
                </h3>
                <div className="camera-manager-toolbar">
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
                        手动添加
                    </Button>
                    <Button icon={<ReloadOutlined />} onClick={handleRefreshSavedCameras}>
                        刷新摄像头列表
                    </Button>
                    <Button icon={<RadarChartOutlined />} onClick={handleStartScan} loading={scanning}>
                        扫描网络
                    </Button>
                    <Button icon={<SyncOutlined />} onClick={handleRefreshScanStatus}>
                        刷新扫描状态
                    </Button>
                    <Button danger onClick={handleSyncAll} disabled={scanResults.length === 0}>
                        用扫描结果替换全部
                    </Button>
                </div>
                {scanStatus && (
                    <div className="scan-progress-line">
                        <Progress
                            percent={
                                scanStatus.total > 0
                                    ? Math.round((scanStatus.progress / scanStatus.total) * 100)
                                    : 0
                            }
                            status={scanning ? 'active' : 'normal'}
                        />
                        <div className="scan-status-summary">
                            <span>{scanStatus.message}</span>
                            <span>已发现 {scanStatus.found} 台</span>
                            <span>{scanning ? '扫描中' : '扫描结束'}</span>
                        </div>
                    </div>
                )}
            </div>

            {scanStatus && (
                <div className="camera-manager-section">
                    <h3>扫描日志</h3>
                    <div className="scan-log-panel">
                        {scanLogs.length === 0 ? (
                            <div className="scan-log-empty">暂无扫描日志，点击“扫描网络”后会在这里显示详细过程。</div>
                        ) : (
                            scanLogs.map((log, index) => (
                                <div key={`${index}-${log}`} className="scan-log-line">
                                    <span className="scan-log-index">{String(index + 1).padStart(2, '0')}</span>
                                    <span className="scan-log-text">{log}</span>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            )}

            {scanResults.length > 0 && (
                <div className="camera-manager-section">
                    <h3>最近一次扫描结果</h3>
                    <Table
                        size="small"
                        rowKey={(r) => r.id || r.ip}
                        columns={scanColumns}
                        dataSource={scanResults}
                        pagination={false}
                    />
                </div>
            )}

            <div className="camera-manager-section">
                <h3>已保存的摄像头 ({cameras.length})</h3>
                <Table
                    size="small"
                    rowKey="id"
                    columns={camColumns}
                    dataSource={cameras}
                    loading={loading}
                    pagination={{ pageSize: 10 }}
                />
            </div>

            <Modal
                title="手动添加摄像头"
                open={addOpen}
                onCancel={() => {
                    setAddOpen(false);
                    addForm.resetFields();
                }}
                onOk={submitManualAdd}
                destroyOnClose
            >
                <Form form={addForm} layout="vertical">
                    <Form.Item name="name" label="名称">
                        <Input placeholder="可选" />
                    </Form.Item>
                    <Form.Item
                        name="stream_url"
                        label="RTSP 地址"
                        rules={[{ required: true, message: '请输入 RTSP URL' }]}
                    >
                        <Input placeholder="rtsp://..." />
                    </Form.Item>
                    <Form.Item name="username" label="用户名">
                        <Input />
                    </Form.Item>
                    <Form.Item name="password" label="密码">
                        <Input.Password />
                    </Form.Item>
                    <Form.Item name="band_type" label="默认波段（可选）">
                        <Select
                            allowClear
                            placeholder="未绑定"
                            options={BAND_TYPES.map((b) => ({ value: b, label: BAND_LABELS[b] }))}
                        />
                    </Form.Item>
                </Form>
            </Modal>
        </div>
    );
};

export default CameraManager;
