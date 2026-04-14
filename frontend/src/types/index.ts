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

