/**
 * 摄像头成像参数控制面板（ONVIF Imaging）
 *
 * 对应《Mac_ONVIF_多光谱摄像头监看与参数控制方案》§10 的界面：
 * - 参数滑块范围完全由 GetOptions 返回决定（§7.2，不假设范围）
 * - 应用 / 应用到全部摄像头 / 波段曝光策略表 / 一键多光谱模式（§8/§9）
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    Alert, Button, Checkbox, Drawer, InputNumber, Modal, Segmented,
    Slider, Space, Spin, Tag, message,
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';

import { cameraApi, imagingApi } from '../services/cameraApi';
import type {
    BandImagingProfile,
    CameraInfo,
    ImagingActionResult,
    ImagingRange,
    ImagingSettings,
} from '../types';
import { BAND_TYPES, BAND_LABELS } from '../types';
import type { BandType } from '../types';
import './ImagingPanel.css';

interface ImagingPanelProps {
    open: boolean;
    /** 初始选中的摄像头（通常为当前主画面） */
    cameraId: string | null;
    onClose: () => void;
}

const isRange = (v: unknown): v is ImagingRange =>
    !!v && typeof v === 'object' && 'min' in (v as object) && 'max' in (v as object);

/** 数值型参数的配置：归一化字段名 → 显示名/单位/步长 */
const NUMERIC_FIELDS: Array<{ key: keyof ImagingSettings; label: string; unit?: string; step?: number }> = [
    { key: 'exposure_time_us', label: '曝光时间', unit: 'us', step: 100 },
    { key: 'gain', label: '增益 Gain', step: 1 },
    { key: 'brightness', label: '亮度', step: 1 },
    { key: 'contrast', label: '对比度', step: 1 },
    { key: 'saturation', label: '饱和度', step: 1 },
    { key: 'sharpness', label: '锐度', step: 1 },
    { key: 'wb_r_gain', label: '白平衡 R 增益', step: 1 },
    { key: 'wb_b_gain', label: '白平衡 B 增益', step: 1 },
    { key: 'wdr_level', label: 'WDR 强度', step: 1 },
];

/** 枚举型参数 */
const ENUM_FIELDS: Array<{ key: keyof ImagingSettings; label: string }> = [
    { key: 'exposure_mode', label: '曝光模式' },
    { key: 'wb_mode', label: '白平衡模式' },
    { key: 'wdr_mode', label: '宽动态 WDR' },
    { key: 'ir_cut', label: 'IR-Cut' },
];

/** 数值滑块受模式开关禁用的规则 */
const DISABLED_WHEN: Partial<Record<keyof ImagingSettings, { modeKey: keyof ImagingSettings; offValue: string }>> = {
    exposure_time_us: { modeKey: 'exposure_mode', offValue: 'AUTO' },
    gain: { modeKey: 'exposure_mode', offValue: 'AUTO' },
    wb_r_gain: { modeKey: 'wb_mode', offValue: 'AUTO' },
    wb_b_gain: { modeKey: 'wb_mode', offValue: 'AUTO' },
    wdr_level: { modeKey: 'wdr_mode', offValue: 'OFF' },
};

const ImagingPanel: React.FC<ImagingPanelProps> = ({ open, cameraId, onClose }) => {
    const [cameras, setCameras] = useState<CameraInfo[]>([]);
    const [activeId, setActiveId] = useState<string>('');
    const [settings, setSettings] = useState<ImagingSettings>({});
    const [options, setOptions] = useState<Record<string, ImagingRange | string[]>>({});
    const [supported, setSupported] = useState(true);
    const [unsupportedReason, setUnsupportedReason] = useState('');
    const [loading, setLoading] = useState(false);
    const [applying, setApplying] = useState(false);
    const [dirty, setDirty] = useState<Partial<ImagingSettings>>({});
    const [profiles, setProfiles] = useState<Record<string, BandImagingProfile>>({});
    const [profilesDirty, setProfilesDirty] = useState(false);

    const loadCameras = useCallback(async () => {
        try {
            setCameras(await cameraApi.list());
        } catch {
            message.error('加载摄像头列表失败');
        }
    }, []);

    const loadState = useCallback(async (camId: string) => {
        setLoading(true);
        setDirty({});
        try {
            const state = await imagingApi.get(camId);
            setSupported(state.supported);
            setUnsupportedReason(state.message);
            setSettings(state.settings || {});
            setOptions(state.options || {});
        } catch {
            setSupported(false);
            setUnsupportedReason('读取参数失败，请检查后端服务');
        } finally {
            setLoading(false);
        }
    }, []);

    const loadProfiles = useCallback(async () => {
        try {
            setProfiles(await imagingApi.bandProfiles());
            setProfilesDirty(false);
        } catch {
            // 策略表读取失败不阻断面板
        }
    }, []);

    useEffect(() => {
        if (open) {
            void loadCameras();
            void loadProfiles();
        }
    }, [open, loadCameras, loadProfiles]);

    // 外部指定 / 默认选中第一台
    useEffect(() => {
        if (!open) return;
        if (cameraId) {
            setActiveId(cameraId);
        } else if (!activeId && cameras.length > 0) {
            setActiveId(cameras[0].id);
        }
    }, [open, cameraId, cameras, activeId]);

    useEffect(() => {
        if (open && activeId) {
            void loadState(activeId);
        }
    }, [open, activeId, loadState]);

    const activeCamera = useMemo(
        () => cameras.find(c => c.id === activeId) || null,
        [cameras, activeId],
    );

    const patchSetting = (key: keyof ImagingSettings, value: number | string) => {
        setSettings(prev => ({ ...prev, [key]: value }));
        setDirty(prev => ({ ...prev, [key]: value }));
    };

    const showActionResults = (title: string, results: ImagingActionResult[]) => {
        const failed = results.filter(r => !r.success);
        Modal.info({
            title,
            width: 520,
            content: (
                <div className="imaging-action-results">
                    {results.map(r => (
                        <div key={r.camera_id} className={r.success ? 'result-ok' : 'result-fail'}>
                            {r.success ? '✓' : '✗'} {r.name}
                            {r.band_type ? `（${r.band_type}）` : ''}：{r.message}
                        </div>
                    ))}
                </div>
            ),
        });
        if (failed.length === 0) {
            message.success(`${title}：全部 ${results.length} 台成功`);
        } else {
            message.warning(`${title}：${results.length - failed.length} 台成功，${failed.length} 台失败`);
        }
    };

    const handleApply = async () => {
        if (!activeId || Object.keys(dirty).length === 0) {
            message.info('没有待应用的修改');
            return;
        }
        setApplying(true);
        try {
            const state = await imagingApi.update(activeId, dirty);
            setSupported(state.supported);
            setUnsupportedReason(state.message);
            setSettings(state.settings || {});
            setOptions(state.options || {});
            setDirty({});
            if (!state.supported) {
                // 硬拒绝：相机直接返回错误（原因已中文化）
                Modal.error({
                    title: '相机拒绝了参数设置',
                    content: state.message || '设置失败',
                });
            } else if (state.rejected && state.rejected.length > 0) {
                // 软拒绝：Set 请求被接受但部分字段未生效（回读校验发现）
                Modal.warning({
                    title: '部分参数未生效',
                    content: (
                        <div className="imaging-action-results">
                            {state.rejected.map(r => (
                                <div key={r.field} className="result-fail">
                                    {r.label}：请求 {String(r.requested)}，实际 {r.actual === null ? '（相机不支持）' : String(r.actual)}
                                </div>
                            ))}
                        </div>
                    ),
                });
            } else {
                message.success('参数已应用');
            }
        } catch {
            message.error('设置参数失败');
        } finally {
            setApplying(false);
        }
    };

    const handleApplyAll = () => {
        const payload: Partial<ImagingSettings> = { ...dirty };
        // 未做任何修改时，把当前面板参数一并下发
        if (Object.keys(payload).length === 0) {
            (Object.keys(settings) as Array<keyof ImagingSettings>).forEach((k) => {
                const v = settings[k];
                if (typeof v === 'number' || typeof v === 'string') {
                    (payload as Record<string, number | string>)[k] = v;
                }
            });
        }
        Modal.confirm({
            title: '应用到全部摄像头？',
            content: '将把当前面板参数下发到所有监控中的摄像头（不支持的字段会被各相机忽略）。',
            okText: '应用',
            cancelText: '取消',
            onOk: async () => {
                setApplying(true);
                try {
                    const results = await imagingApi.applyAll(payload);
                    showActionResults('应用到全部摄像头', results);
                    setDirty({});
                    if (activeId) await loadState(activeId);
                } catch {
                    message.error('批量应用失败');
                } finally {
                    setApplying(false);
                }
            },
        });
    };

    const handleMultispectralMode = () => {
        Modal.confirm({
            title: '一键多光谱模式',
            content: (
                <div>
                    <div>将按波段曝光策略表固定每台摄像头的曝光与 Gain，并关闭自动白平衡与 WDR。</div>
                    <div style={{ marginTop: 8, color: '#888' }}>
                        固定曝光后画面亮度不再自动调节，请确保光照条件与标定时一致。
                    </div>
                </div>
            ),
            okText: '应用多光谱模式',
            cancelText: '取消',
            onOk: async () => {
                setApplying(true);
                try {
                    const results = await imagingApi.multispectralMode();
                    showActionResults('多光谱模式', results);
                    if (activeId) await loadState(activeId);
                } catch {
                    message.error('多光谱模式应用失败');
                } finally {
                    setApplying(false);
                }
            },
        });
    };

    const handleSaveProfiles = async () => {
        try {
            await imagingApi.saveBandProfiles(profiles);
            setProfilesDirty(false);
            message.success('波段曝光策略表已保存');
        } catch {
            message.error('保存策略表失败');
        }
    };

    const renderEnumControl = (key: keyof ImagingSettings, label: string) => {
        const enumOptions = options[key];
        const value = settings[key];
        if (!Array.isArray(enumOptions) || typeof value !== 'string') return null;
        return (
            <div className="imaging-field" key={key}>
                <span className="imaging-field-label">{label}</span>
                <Segmented
                    size="small"
                    value={value}
                    options={enumOptions}
                    onChange={(v) => patchSetting(key, String(v))}
                />
            </div>
        );
    };

    const renderNumericControl = (key: keyof ImagingSettings, label: string, unit?: string, step?: number) => {
        const range = options[key];
        const value = settings[key];
        if (!isRange(range) || typeof value !== 'number') return null;
        const disableRule = DISABLED_WHEN[key];
        const disabled = !!disableRule && settings[disableRule.modeKey] === disableRule.offValue;
        return (
            <div className="imaging-field" key={key}>
                <span className="imaging-field-label">{label}</span>
                <Slider
                    className="imaging-field-slider"
                    min={range.min}
                    max={range.max}
                    step={step}
                    value={value}
                    disabled={disabled}
                    onChange={(v) => patchSetting(key, v as number)}
                />
                <InputNumber
                    size="small"
                    min={range.min}
                    max={range.max}
                    step={step}
                    value={value}
                    disabled={disabled}
                    onChange={(v) => typeof v === 'number' && patchSetting(key, v)}
                />
                {unit && <span className="imaging-field-unit">{unit}</span>}
            </div>
        );
    };

    return (
        <Drawer
            title="摄像头成像参数"
            placement="right"
            width={520}
            open={open}
            onClose={onClose}
            destroyOnHidden={false}
        >
            <div className="imaging-panel">
                <div className="imaging-field">
                    <span className="imaging-field-label">摄像头</span>
                    <Segmented
                        size="small"
                        value={activeId}
                        onChange={(v) => setActiveId(String(v))}
                        options={cameras.map(c => ({
                            value: c.id,
                            label: c.band_type ? c.band_type : c.name,
                        }))}
                    />
                    <Button
                        size="small"
                        icon={<ReloadOutlined />}
                        loading={loading}
                        onClick={() => activeId && loadState(activeId)}
                    />
                </div>
                {activeCamera && (
                    <div className="imaging-camera-meta">
                        <span>{activeCamera.name}</span>
                        <span>{activeCamera.ip}</span>
                        {activeCamera.band_type && (
                            <Tag color="blue">{BAND_LABELS[activeCamera.band_type as BandType] || activeCamera.band_type}</Tag>
                        )}
                    </div>
                )}

                {loading ? (
                    <div className="imaging-loading"><Spin /> 正在读取摄像头参数…</div>
                ) : !supported ? (
                    <Alert
                        type="warning"
                        showIcon
                        message="该摄像头暂不支持 ONVIF 参数控制"
                        description={unsupportedReason || '无法通过 ONVIF Imaging Service 读取参数。可在摄像头管理页检查设备账号密码，或改用厂商 Web 页面配置。'}
                    />
                ) : (
                    <>
                        {ENUM_FIELDS.map(f => renderEnumControl(f.key, f.label))}
                        {NUMERIC_FIELDS.map(f => renderNumericControl(f.key, f.label, f.unit, f.step))}

                        <Space className="imaging-actions" wrap>
                            <Button
                                type="primary"
                                loading={applying}
                                disabled={Object.keys(dirty).length === 0}
                                onClick={handleApply}
                            >
                                应用
                            </Button>
                            <Button loading={applying} onClick={handleApplyAll}>
                                应用到全部摄像头
                            </Button>
                            <Button loading={applying} onClick={handleMultispectralMode}>
                                一键多光谱模式
                            </Button>
                        </Space>
                    </>
                )}

                <div className="imaging-profiles">
                    <div className="imaging-profiles-title">各波段曝光策略表（多光谱模式使用）</div>
                    {BAND_TYPES.map(band => {
                        const p = profiles[band] || {};
                        const auto = !!p.auto_exposure;
                        return (
                            <div className="imaging-field" key={band}>
                                <span className="imaging-field-label">{BAND_LABELS[band]}</span>
                                <Checkbox
                                    checked={auto}
                                    onChange={(e) => {
                                        setProfiles(prev => ({
                                            ...prev,
                                            [band]: e.target.checked
                                                ? { auto_exposure: true }
                                                : { exposure_time_us: p.exposure_time_us ?? 10000, gain: p.gain ?? 0 },
                                        }));
                                        setProfilesDirty(true);
                                    }}
                                >
                                    自动
                                </Checkbox>
                                {!auto && (
                                    <>
                                        <InputNumber
                                            size="small"
                                            min={0}
                                            max={40000}
                                            step={500}
                                            value={p.exposure_time_us}
                                            placeholder="曝光us"
                                            onChange={(v) => {
                                                setProfiles(prev => ({
                                                    ...prev,
                                                    [band]: { ...prev[band], exposure_time_us: v ?? 0 },
                                                }));
                                                setProfilesDirty(true);
                                            }}
                                        />
                                        <InputNumber
                                            size="small"
                                            min={0}
                                            max={100}
                                            value={p.gain}
                                            placeholder="Gain"
                                            onChange={(v) => {
                                                setProfiles(prev => ({
                                                    ...prev,
                                                    [band]: { ...prev[band], gain: v ?? 0 },
                                                }));
                                                setProfilesDirty(true);
                                            }}
                                        />
                                    </>
                                )}
                            </div>
                        );
                    })}
                    <Button size="small" disabled={!profilesDirty} onClick={handleSaveProfiles}>
                        保存策略表
                    </Button>
                </div>
            </div>
        </Drawer>
    );
};

export default ImagingPanel;
