/**
 * TypeScript类型定义
 */

// 图像相关
export interface ImageInfo {
    id: string;
    filename: string;
    filepath: string;
    url: string;
    size: number;
    width: number;
    height: number;
    channels: number;
    upload_time: string;
}

// 图像处理相关
export interface WhiteBalanceParams {
    r_gain: number;
    g_gain: number;
    b_gain: number;
}

export interface ChannelGainParams {
    channel: 'r' | 'g' | 'b';
    gain: number;
    offset: number;
}

export interface HistogramData {
    r?: number[];
    g?: number[];
    b?: number[];
    gray?: number[];
}

// 混合相关
export interface BandSelection {
    image_id: string;
    channel: 'r' | 'g' | 'b' | 'gray';
}

export interface BlendingParams {
    bands: Record<string, BandSelection>;
    weights: Record<string, number>;
}

export interface SpectralCurveData {
    wavelengths: number[];
    values: number[];
}

// 植被指数相关
export interface VegetationIndexInfo {
    name: string;
    full_name: string;
    formula: string;
    required_bands: string[];
}

export interface VegetationIndexParams {
    index_name: string;
    bands: Record<string, BandSelection>;
    colormap: string;
}

export interface VegetationStatistics {
    min: number;
    max: number;
    mean: number;
    std: number;
}


// 批次相关
export type BandType = 'rgb' | '570nm' | '650nm' | '730nm' | '850nm';

export const BAND_TYPES: BandType[] = ['rgb', '570nm', '650nm', '730nm', '850nm'];

export const BAND_LABELS: Record<BandType, string> = {
    'rgb': 'RGB 影像',
    '570nm': '570nm 波段',
    '650nm': '650nm 波段',
    '730nm': '730nm 波段',
    '850nm': '850nm 波段',
};

export interface BatchImageInfo {
    id: string;
    band_type: BandType;
    filename: string;
    filepath: string;
    url: string;
    size: number;
    width: number;
    height: number;
    channels: number;
    upload_time: string;
}

export interface BatchInfo {
    id: string;
    name: string;
    created_at: string;
    images: Record<BandType, BatchImageInfo | null>;
    source_images?: Record<BandType, BatchImageInfo | null>;
    aligned_images?: Record<BandType, BatchImageInfo | null>;
}


// 摄像头相关
export interface CameraInfo {
    id: string;
    name: string;
    ip?: string | null;
    stream_url: string;
    username?: string | null;
    camera_type?: string | null;
    band_type?: BandType | null;
    added_at: string;
    is_running?: boolean;
    is_connected?: boolean;
    fps?: number;
}

export interface CameraCreatePayload {
    name?: string;
    stream_url: string;
    username?: string;
    password?: string;
    camera_type?: string;
    band_type?: BandType | null;
}

export interface CameraScanStatus {
    is_scanning: boolean;
    progress: number;
    total: number;
    found: number;
    message: string;
    last_result: any[];
    scan_logs: string[];
}

export interface StreamStatus {
    camera_id: string;
    name: string;
    is_running: boolean;
    is_connected: boolean;
    fps: number;
    error_count: number;
    frame_age: number;
    rtsp_url: string;
    band_type?: BandType | null;
}

export interface CaptureBatchRequest {
    camera_ids: string[];
    batch_name?: string;
    image_type?: 'source' | 'aligned';
    band_overrides?: Record<string, BandType>;
    jpeg_quality?: number;
}

export interface CaptureImageResult {
    camera_id: string;
    image_id: string;
    band_type: string;
    filename: string;
    success: boolean;
    message?: string;
}

export interface CaptureBatchResponse {
    batch_id: string;
    batch_name: string;
    results: CaptureImageResult[];
    succeeded: number;
    failed: number;
}

