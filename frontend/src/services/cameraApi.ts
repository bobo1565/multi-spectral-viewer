/**
 * 摄像头 & 抓拍相关 API
 */
import axios from 'axios';
import type {
    CameraInfo,
    CameraCreatePayload,
    CameraScanStatus,
    StreamStatus,
    CaptureBatchRequest,
    CaptureBatchResponse,
    BandType,
    ImagingState,
    ImagingSettings,
    ImagingActionResult,
    BandImagingProfile,
} from '../types';

const API_BASE = import.meta.env.DEV ? 'http://localhost:8002' : '';

const api = axios.create({ baseURL: API_BASE });

export const cameraApi = {
    baseUrl: API_BASE,

    async list(): Promise<CameraInfo[]> {
        const res = await api.get('/api/cameras/');
        return res.data;
    },

    async create(payload: CameraCreatePayload): Promise<CameraInfo> {
        const res = await api.post('/api/cameras/', payload);
        return res.data;
    },

    async update(cam_id: string, payload: Partial<CameraCreatePayload>): Promise<CameraInfo> {
        const res = await api.patch(`/api/cameras/${cam_id}`, payload);
        return res.data;
    },

    async setBand(cam_id: string, band_type: BandType | null): Promise<CameraInfo> {
        const res = await api.put(`/api/cameras/${cam_id}/band`, { band_type });
        return res.data;
    },

    async toggleMonitoring(cam_id: string): Promise<CameraInfo> {
        const res = await api.put(`/api/cameras/${cam_id}/monitoring`);
        return res.data;
    },

    async remove(cam_id: string): Promise<void> {
        await api.delete(`/api/cameras/${cam_id}`);
    },

    async startScan(): Promise<CameraScanStatus> {
        const res = await api.post('/api/cameras/scan');
        return res.data;
    },

    async scanStatus(): Promise<CameraScanStatus> {
        const res = await api.get('/api/cameras/scan/status');
        return res.data;
    },

    async scanResults(): Promise<any[]> {
        const res = await api.get('/api/cameras/scan/results');
        return res.data;
    },

    async syncFromScan(): Promise<{ success: boolean; count: number; cameras: CameraInfo[] }> {
        const res = await api.post('/api/cameras/sync');
        return res.data;
    },

    /** 从最近一次扫描结果添加一台（match 为扫描结果中的 id 或 ip） */
    async addFromScan(match: string): Promise<CameraInfo> {
        const res = await api.post('/api/cameras/scan/add', { match });
        return res.data;
    },

    async streamsStatus(active_ids: string[], main_id?: string): Promise<StreamStatus[]> {
        const res = await api.post('/api/cameras/streams/status', {
            active_ids,
            main_id: main_id || '',
        });
        return res.data;
    },

    streamUrl(cam_id: string, quality: number = 60, cacheKey?: string | number): string {
        const suffix = cacheKey !== undefined ? `&r=${encodeURIComponent(String(cacheKey))}` : '';
        return `${API_BASE}/api/cameras/${cam_id}/stream?quality=${quality}${suffix}`;
    },

    snapshotUrl(cam_id: string, quality: number = 95): string {
        return `${API_BASE}/api/cameras/${cam_id}/snapshot?quality=${quality}`;
    },

    async refreshStreams(active_ids: string[]): Promise<{ success: boolean; refreshed: number }> {
        const res = await api.post('/api/cameras/streams/refresh', {
            active_ids,
            main_id: '',
        });
        return res.data;
    },
};

/** ONVIF Imaging 参数控制（曝光/增益/白平衡等） */
export const imagingApi = {
    async get(cam_id: string): Promise<ImagingState> {
        const res = await api.get(`/api/cameras/${cam_id}/imaging`);
        return res.data;
    },

    async update(cam_id: string, settings: Partial<ImagingSettings>): Promise<ImagingState> {
        const res = await api.put(`/api/cameras/${cam_id}/imaging`, { settings });
        return res.data;
    },

    async bandProfiles(): Promise<Record<string, BandImagingProfile>> {
        const res = await api.get('/api/cameras/imaging/band-profiles');
        return res.data.profiles;
    },

    async saveBandProfiles(profiles: Record<string, BandImagingProfile>): Promise<void> {
        await api.put('/api/cameras/imaging/band-profiles', { profiles });
    },

    /** 一键多光谱模式：按波段策略表固定曝光/Gain，关自动白平衡与 WDR */
    async multispectralMode(): Promise<ImagingActionResult[]> {
        const res = await api.post('/api/cameras/imaging/multispectral-mode');
        return res.data;
    },

    /** 把同一组参数应用到多台（默认全部监控中）摄像头 */
    async applyAll(settings: Partial<ImagingSettings>, camera_ids?: string[]): Promise<ImagingActionResult[]> {
        const res = await api.post('/api/cameras/imaging/apply-all', { settings, camera_ids });
        return res.data;
    },
};

export const captureApi = {
    async captureBatch(req: CaptureBatchRequest): Promise<CaptureBatchResponse> {
        const res = await api.post('/api/capture/batch', req);
        return res.data;
    },
};
