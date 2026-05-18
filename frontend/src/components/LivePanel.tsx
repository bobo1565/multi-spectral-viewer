/**
 * 实时监控面板
 * - 以网格展示所有摄像头的 MJPEG 流
 * - 支持勾选 + 一键同步抓拍，生成新批次后回调跳转到分析视图
 */
import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { Button, Checkbox, Input, Select, Space, Tag, message, Modal, Tooltip } from 'antd';
import { CameraOutlined, ExpandOutlined, ReloadOutlined, SettingOutlined } from '@ant-design/icons';

import { cameraApi, captureApi } from '../services/cameraApi';
import type { CameraInfo, BandType, StreamStatus } from '../types';
import { BAND_TYPES, BAND_LABELS } from '../types';
import './LivePanel.css';

interface LivePanelProps {
    onCaptureSuccess: (batchId: string) => void;
    onGoCameraManager: () => void;
}

const STATUS_POLL_MS = 3000;
const EXPECTED_CAMERA_COUNT = BAND_TYPES.length;
const isDocumentVisible = () => typeof document === "undefined" || document.visibilityState === "visible";

type LiveTileItem =
    | { kind: 'camera'; key: string; camera: CameraInfo }
    | { kind: 'placeholder'; key: string; band: BandType };

const LivePanel: React.FC<LivePanelProps> = ({ onCaptureSuccess, onGoCameraManager }) => {
    const [cameras, setCameras] = useState<CameraInfo[]>([]);
    const [streamStatuses, setStreamStatuses] = useState<Record<string, StreamStatus>>({});
    const [selectedIds, setSelectedIds] = useState<string[]>([]);
    const [mainId, setMainId] = useState<string>('');
    const [capturing, setCapturing] = useState(false);
    const [batchName, setBatchName] = useState('');
    const [refreshKey, setRefreshKey] = useState(0);
    const [previewSessionKey, setPreviewSessionKey] = useState(0);
    const [isStreamRenderingEnabled, setIsStreamRenderingEnabled] = useState(isDocumentVisible);
    const [maximizedCameraId, setMaximizedCameraId] = useState<string | null>(null);

    const loadCameras = useCallback(async () => {
        try {
            const data = await cameraApi.list();
            setCameras(data);
            setSelectedIds(prev => prev.filter(id => data.some(c => c.id === id)));
        } catch {
            message.error('加载摄像头列表失败');
        }
    }, []);

    useEffect(() => {
        loadCameras();
    }, [loadCameras]);

    const resumeStreamRendering = useCallback((notify = false) => {
        setIsStreamRenderingEnabled(true);
        setRefreshKey(k => k + 1);
        setPreviewSessionKey(k => k + 1);
        void loadCameras();
        if (notify) {
            message.success("已恢复摄像头画面");
        }
    }, [loadCameras]);

    const pauseStreamRendering = useCallback(() => {
        setIsStreamRenderingEnabled(false);
    }, []);

    useEffect(() => {
        const handleVisibilityChange = () => {
            if (isDocumentVisible()) {
                resumeStreamRendering();
            } else {
                pauseStreamRendering();
            }
        };

        // pageshow: 处理浏览器前进/后退缓存恢复
        const handlePageShow = () => {
            resumeStreamRendering();
        };

        document.addEventListener("visibilitychange", handleVisibilityChange);
        window.addEventListener("pageshow", handlePageShow);

        return () => {
            document.removeEventListener("visibilitychange", handleVisibilityChange);
            window.removeEventListener("pageshow", handlePageShow);
        };
    }, [pauseStreamRendering, resumeStreamRendering]);

    // 轮询流状态 + 按需启停流
    useEffect(() => {
        if (cameras.length === 0) return;
        const activeIds = cameras.map(c => c.id);

        let cancelled = false;
        const poll = async () => {
            try {
                const statuses = await cameraApi.streamsStatus(activeIds, mainId);
                if (cancelled) return;
                const map: Record<string, StreamStatus> = {};
                statuses.forEach(s => { map[s.camera_id] = s; });
                setStreamStatuses(map);
            } catch {
                // 静默
            }
        };
        poll();
        const h = setInterval(poll, STATUS_POLL_MS);
        return () => { cancelled = true; clearInterval(h); };
    }, [cameras, mainId]);

    useEffect(() => {
        if (maximizedCameraId && !cameras.some(cam => cam.id === maximizedCameraId)) {
            setMaximizedCameraId(null);
            setMainId("");
        }
    }, [cameras, maximizedCameraId]);

    const toggleSelect = (cam_id: string) => {
        setSelectedIds(prev => prev.includes(cam_id)
            ? prev.filter(x => x !== cam_id)
            : [...prev, cam_id]);
    };

    const selectAll = () => {
        setSelectedIds(cameras.map(c => c.id));
    };

    const clearSelection = () => {
        setSelectedIds([]);
    };

    const handleSetBand = async (cam_id: string, band: BandType | null) => {
        try {
            await cameraApi.setBand(cam_id, band);
            await loadCameras();
        } catch {
            message.error('设置波段失败');
        }
    };

    const runCapture = async (camera_ids: string[]) => {
        if (camera_ids.length === 0) {
            message.warning('请至少选择一台摄像头');
            return;
        }

        const chosen = cameras.filter(c => camera_ids.includes(c.id));
        const unbound = chosen.filter(c => !c.band_type);
        if (unbound.length > 0) {
            const proceed = await new Promise<boolean>(resolve => {
                Modal.confirm({
                    title: '以下摄像头未绑定波段',
                    content: (
                        <div>
                            {unbound.map(c => <div key={c.id}>• {c.name}</div>)}
                            <div style={{ marginTop: 8, color: '#888' }}>未绑定的将默认归入 rgb 波段，可能与其他摄像头冲突。是否继续？</div>
                        </div>
                    ),
                    okText: '继续抓拍',
                    cancelText: '取消',
                    onOk: () => resolve(true),
                    onCancel: () => resolve(false),
                });
            });
            if (!proceed) return;
        }

        setCapturing(true);
        try {
            const resp = await captureApi.captureBatch({
                camera_ids,
                batch_name: batchName.trim() || undefined,
            });
            const failedResults = resp.results.filter(r => !r.success);
            if (failedResults.length > 0) {
                message.warning(`批次 ${resp.batch_name} 创建成功，但有 ${failedResults.length} 张抓拍失败`);
            } else {
                message.success(`批次 ${resp.batch_name} 创建成功：${resp.succeeded} 张图像`);
            }
            onCaptureSuccess(resp.batch_id);
        } catch (e: any) {
            const detail = e?.response?.data?.detail;
            message.error(typeof detail === 'string' ? detail : '抓拍失败');
        } finally {
            setCapturing(false);
        }
    };

    // 刷新流：先重启后端 RTSP 连接，再刷新前端 MJPEG 连接
    const handleRefreshStreams = async () => {
        const activeIds = cameras.map(c => c.id);
        if (activeIds.length > 0) {
            try {
                await cameraApi.refreshStreams(activeIds);
            } catch {
                // 后端重启失败不阻断前端刷新
            }
        }
        resumeStreamRendering(true);
    };

    const handleOpenMaximized = (cam_id: string) => {
        // 同时递增 previewSessionKey 和 refreshKey，确保 Modal 内的 img src 每次都是
        // 全新的 URL，强制浏览器建立全新的 MJPEG 连接，避免复用上一个摄像头的旧连接
        setPreviewSessionKey(k => k + 1);
        setRefreshKey(k => k + 1);
        setMainId(cam_id);
        setMaximizedCameraId(cam_id);
    };

    const handleCloseMaximized = () => {
        setMaximizedCameraId(null);
        setMainId("");
    };

    const tileItems = useMemo<LiveTileItem[]>(() => {
        const usedIds = new Set<string>();
        const ordered: LiveTileItem[] = [];

        BAND_TYPES.forEach((band) => {
            const cam = cameras.find(item => item.band_type === band && !usedIds.has(item.id));
            if (cam) {
                usedIds.add(cam.id);
                ordered.push({ kind: 'camera', key: cam.id, camera: cam });
                return;
            }
            ordered.push({ kind: 'placeholder', key: `placeholder-${band}`, band });
        });

        cameras.forEach((cam) => {
            if (!usedIds.has(cam.id)) {
                ordered.push({ kind: 'camera', key: cam.id, camera: cam });
            }
        });

        return ordered;
    }, [cameras]);

    const gridTiles = useMemo(() => tileItems.map((item) => {
        if (item.kind === 'placeholder') {
            return (
                <div key={item.key} className="live-tile live-tile-placeholder">
                    <div className="tile-placeholder-content">
                        <Tag color="default">{BAND_LABELS[item.band]}</Tag>
                        <div className="tile-placeholder-title">该波段还未配置摄像头</div>
                        <div className="tile-placeholder-desc">当前系统按 5 路波段槽位展示，可到摄像头管理中补充这一台设备。</div>
                        <Button type="primary" ghost onClick={onGoCameraManager}>
                            去配置摄像头
                        </Button>
                    </div>
                </div>
            );
        }

        const cam = item.camera;
        const status = streamStatuses[cam.id];
        const isPausedForPreview = maximizedCameraId === cam.id;
        const pauseReason = !isStreamRenderingEnabled ? "页面切换后已暂停" : isPausedForPreview ? "单窗查看中" : null;
        const streamSrc = pauseReason ? "" : cameraApi.streamUrl(cam.id, 60, refreshKey);
        const checked = selectedIds.includes(cam.id);
        const online = status?.is_connected ?? cam.is_connected ?? false;

        return (
            <div key={cam.id} className={`live-tile ${checked ? 'selected' : ''}`}>
                {pauseReason ? (
                    <div
                        className="tile-video tile-video-paused"
                        onClick={() => toggleSelect(cam.id)}
                        onDoubleClick={() => handleOpenMaximized(cam.id)}
                    >
                        <span className="tile-paused-badge">{pauseReason}</span>
                    </div>
                ) : (
                    <img
                        key={`${cam.id}-${refreshKey}`}
                        className="tile-video"
                        src={streamSrc}
                        alt={cam.name}
                        onClick={() => toggleSelect(cam.id)}
                        onDoubleClick={() => handleOpenMaximized(cam.id)}
                        onLoad={(e) => {
                            (e.target as HTMLImageElement).style.opacity = "1";
                        }}
                        onError={(e) => {
                            (e.target as HTMLImageElement).style.opacity = "0.5";
                            console.warn(`[Live] 流加载失败: ${cam.name}`);
                        }}
                    />
                )}

                <div className="tile-overlay-top">
                    <span className="tile-name" title={cam.stream_url}>{cam.name}</span>
                    <div className="tile-tools">
                        <div className="tile-band-badge">
                            <Select
                                size="small"
                                value={cam.band_type || ''}
                                style={{ width: 120 }}
                                onChange={(v) => handleSetBand(cam.id, (v || null) as BandType | null)}
                                options={[
                                    { value: '', label: '未绑定' },
                                    ...BAND_TYPES.map(b => ({ value: b, label: BAND_LABELS[b] })),
                                ]}
                            />
                        </div>
                        <Tooltip title="最大化查看">
                            <Button
                                size="small"
                                className="tile-maximize-btn"
                                icon={<ExpandOutlined />}
                                onClick={() => handleOpenMaximized(cam.id)}
                            />
                        </Tooltip>
                    </div>
                </div>

                <div className="tile-overlay-bottom">
                    <span className="tile-status">
                        <span className={`status-dot ${online ? '' : 'offline'}`} />
                        {online ? `${status?.fps ?? 0} fps` : '离线'}
                    </span>
                    <span className="tile-select">
                        <Checkbox checked={checked} onChange={() => toggleSelect(cam.id)}>
                            <span style={{ color: '#fff' }}>抓拍</span>
                        </Checkbox>
                    </span>
                </div>
            </div>
        );
    }), [tileItems, streamStatuses, selectedIds, refreshKey, maximizedCameraId, isStreamRenderingEnabled, onGoCameraManager]);

    const maximizedCamera = useMemo(
        () => cameras.find(cam => cam.id === maximizedCameraId) || null,
        [cameras, maximizedCameraId]
    );
    const maximizedStatus = maximizedCamera ? streamStatuses[maximizedCamera.id] : undefined;

    return (
        <div className="live-panel">
            <div className="live-panel-header">
                <div className="header-left">
                    <CameraOutlined />
                    <span>实时监控</span>
                    <Tag>{`已配置 ${cameras.length}/${EXPECTED_CAMERA_COUNT} 台摄像头`}</Tag>
                    <Tag color="blue">已选 {selectedIds.length}</Tag>
                </div>

                <div className="header-right">
                    <Input
                        placeholder="批次名称（可选）"
                        style={{ width: 200 }}
                        value={batchName}
                        onChange={(e) => setBatchName(e.target.value)}
                        allowClear
                    />
                    <Space.Compact>
                        <Button onClick={selectAll} disabled={cameras.length === 0}>全选</Button>
                        <Button onClick={clearSelection} disabled={selectedIds.length === 0}>清空</Button>
                    </Space.Compact>
                    <Button
                        icon={<CameraOutlined />}
                        type="primary"
                        loading={capturing}
                        disabled={selectedIds.length === 0}
                        onClick={() => runCapture(selectedIds)}
                    >
                        同步抓拍（{selectedIds.length}）
                    </Button>
                    <Button
                        icon={<CameraOutlined />}
                        loading={capturing}
                        disabled={cameras.length === 0}
                        onClick={() => runCapture(cameras.map(c => c.id))}
                    >
                        抓拍全部
                    </Button>
                    <Button icon={<ReloadOutlined />} onClick={handleRefreshStreams}>刷新流</Button>
                    <Button icon={<SettingOutlined />} onClick={onGoCameraManager}>摄像头管理</Button>
                </div>
            </div>

            {cameras.length === 0 ? (
                <div className="live-empty">
                    <Space direction="vertical" align="center">
                        <CameraOutlined style={{ fontSize: 36, color: '#ccc' }} />
                        <span>还没有任何摄像头，先去摄像头管理里扫描或手动添加</span>
                        <Button type="primary" onClick={onGoCameraManager}>去管理摄像头</Button>
                    </Space>
                </div>
            ) : (
                <div className="live-grid">
                    {gridTiles}
                </div>
            )}

            <Modal
                open={!!maximizedCamera}
                title={maximizedCamera ? `单窗查看: ${maximizedCamera.name}` : '单窗查看'}
                footer={null}
                width="92vw"
                onCancel={handleCloseMaximized}
                destroyOnHidden
                centered
            >
                {maximizedCamera && (
                    <div className="live-preview-modal">
                        <div className="live-preview-toolbar">
                            <Tag color={maximizedStatus?.is_connected ? 'green' : 'default'}>
                                {maximizedStatus?.is_connected ? `${maximizedStatus?.fps ?? 0} fps` : '离线'}
                            </Tag>
                            <Tag>{maximizedCamera.band_type ? BAND_LABELS[maximizedCamera.band_type] : '未绑定波段'}</Tag>
                            <Tag>{maximizedCamera.ip || '未知 IP'}</Tag>
                        </div>
                        <div className="live-preview-stage">
                            {isStreamRenderingEnabled ? (
                                <img
                                    key={`${maximizedCamera.id}-${previewSessionKey}-${refreshKey}`}
                                    className="live-preview-image"
                                    src={cameraApi.streamUrl(maximizedCamera.id, 85, refreshKey)}
                                    alt={maximizedCamera.name}
                                    onLoad={(e) => {
                                        (e.target as HTMLImageElement).style.opacity = "1";
                                    }}
                                    onError={(e) => {
                                        (e.target as HTMLImageElement).style.opacity = "0.5";
                                        console.warn(`[Live] 预览流加载失败: ${maximizedCamera?.name}`);
                                    }}
                                />
                            ) : (
                                <div className="tile-video tile-video-paused">
                                    <span className="tile-paused-badge">页面切换后已暂停</span>
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </Modal>
        </div>
    );
};

export default LivePanel;
