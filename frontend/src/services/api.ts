/**
 * API服务层
 */
import axios from 'axios';
import type { ImageInfo, HistogramData, WhiteBalanceParams, VegetationIndexInfo, BatchInfo, BandType, RawImageParams } from '../types';
import type { Align3DParams, Align3DConfig, RigProfileInfo, PreviewDepthResponse, AlignmentBatchResponse } from './align3dApi';

export type { Align3DParams, Align3DConfig, RigProfileInfo, PreviewDepthResponse, AlignmentBatchResponse };

const API_BASE = import.meta.env.DEV ? 'http://localhost:8002' : '';

const api = axios.create({
    baseURL: API_BASE,
    headers: {
        'Content-Type': 'application/json',
    },
});

// 图像管理
export const imageService = {
    async uploadImage(file: File, rawParams?: RawImageParams): Promise<ImageInfo> {
        const formData = new FormData();
        formData.append('file', file);
        if (rawParams) {
            formData.append('raw_params', JSON.stringify(rawParams));
        }
        const response = await api.post('/api/images/upload', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
        return response.data;
    },

    async listImages(): Promise<ImageInfo[]> {
        const response = await api.get('/api/images/');
        return response.data;
    },

    async deleteImage(imageId: string): Promise<void> {
        await api.delete(`/api/images/${imageId}`);
    },

    getImageUrl(imageId: string): string {
        return `${API_BASE}/api/images/${imageId}`;
    },
};

// 图像处理
export const processingService = {
    async applyWhiteBalance(imageId: string, params: WhiteBalanceParams): Promise<Blob> {
        const response = await api.post('/api/processing/white-balance', {
            image_id: imageId,
            ...params,
        }, { responseType: 'blob' });
        return response.data;
    },

    async getHistogram(imageId: string, channel: string = 'rgb'): Promise<HistogramData> {
        const response = await api.get(`/api/processing/histogram/${imageId}`, {
            params: { channel },
        });
        return response.data;
    },
};

// 植被指数
export const vegetationService = {
    async listIndices(): Promise<VegetationIndexInfo[]> {
        const response = await api.get('/api/vegetation/indices');
        return response.data;
    },

    async calculateIndex(indexName: string, bands: any, colormap: string, batchId?: string): Promise<any> {
        const payload: any = {
            index_name: indexName,
            bands,
            colormap,
        };
        if (batchId) {
            payload.batch_id = batchId;
        }
        const response = await api.post('/api/vegetation/calculate', payload);
        return response.data;
    },

    /** 获取各波段辐射补偿系数 {波长nm: 系数} */
    async getBandCorrection(): Promise<Record<string, number>> {
        const response = await api.get('/api/vegetation/band-correction');
        return response.data.corrections;
    },

    /** 更新各波段辐射补偿系数（持久化，后续计算生效） */
    async updateBandCorrection(corrections: Record<string, number>): Promise<Record<string, number>> {
        const response = await api.put('/api/vegetation/band-correction', { corrections });
        return response.data.corrections;
    }
};

// 图像混合与光谱分析
export const blendingService = {
    async createBlendedImage(bands: any, weights: any): Promise<Blob> {
        const response = await api.post('/api/blending/create', {
            bands,
            weights
        }, { responseType: 'blob' });
        return response.data;
    },

    async getSpectralCurve(x: number, y: number, bands: any): Promise<{ wavelengths: number[], values: number[] }> {
        const response = await api.post('/api/blending/spectral-curve', {
            x,
            y,
            bands
        });
        return response.data;
    }
};

// 图像对齐
export interface ROIConfig {
    roi_x_ratio: number;
    roi_y_ratio: number;
    roi_width_ratio: number;
    roi_height_ratio: number;
}

export const alignmentService = {
    async batchAlign(
        batchId: string,
        overwrite: boolean = true,
        referenceImageId?: string,
        roi?: { x: number, y: number, width: number, height: number },
        alignMode?: string,
        sam2Points?: number[][],
        align3dParams?: Align3DParams,
    ): Promise<AlignmentBatchResponse> {
        const payload: Record<string, unknown> = {
            batch_id: batchId,
            overwrite,
            reference_image_id: referenceImageId,
            align_mode: alignMode || 'homography'
        };
        if (roi) {
            payload.roi = roi;
        }
        if (sam2Points && sam2Points.length > 0) {
            payload.sam2_points = sam2Points;
        }
        if (align3dParams) {
            payload.align3d_params = align3dParams;
        }
        const response = await api.post('/api/alignment/batch-align', payload);
        return response.data;
    },

    async sam2Preview(imageId: string, pointX: number, pointY: number): Promise<{
        mask_b64: string;
        area: number;
        bbox: number[];
        score: number;
        point_x: number;
        point_y: number;
    }> {
        const response = await api.post('/api/alignment/sam2-preview', {
            image_id: imageId,
            point_x: pointX,
            point_y: pointY,
        });
        return response.data;
    },

    async getRoiConfig(): Promise<ROIConfig> {
        const response = await api.get('/api/alignment/roi-config');
        return response.data;
    },

    async updateRoiConfig(config: ROIConfig): Promise<ROIConfig> {
        const response = await api.put('/api/alignment/roi-config', config);
        return response.data;
    }
};

// 批次管理
export const batchService = {
    async createBatch(name: string): Promise<BatchInfo> {
        const response = await api.post('/api/batches/', { name });
        return response.data;
    },

    async listBatches(): Promise<BatchInfo[]> {
        const response = await api.get('/api/batches/');
        return response.data;
    },

    async getBatch(batchId: string): Promise<BatchInfo> {
        const response = await api.get(`/api/batches/${batchId}`);
        return response.data;
    },

    async deleteBatch(batchId: string): Promise<void> {
        await api.delete(`/api/batches/${batchId}`);
    },

    async deleteBatchImages(batchId: string, imageType: 'source' | 'aligned' | 'generated'): Promise<void> {
        await api.delete(`/api/batches/${batchId}/images/${imageType}`);
    },

    async renameBatch(batchId: string, newName: string): Promise<BatchInfo> {
        const response = await api.patch(`/api/batches/${batchId}`, { new_name: newName });
        return response.data;
    },

    async renameImage(batchId: string, imageId: string, newFilename: string): Promise<void> {
        await api.patch(`/api/batches/${batchId}/images/${imageId}`, { new_filename: newFilename });
    },

    async saveGeneratedImage(
        batchId: string,
        filepath: string,
        filename: string,
        width: number,
        height: number,
        channels: number,
        fileSize: number
    ): Promise<any> {
        const formData = new FormData();
        formData.append('filepath', filepath);
        formData.append('filename', filename);
        formData.append('width', String(width));
        formData.append('height', String(height));
        formData.append('channels', String(channels));
        formData.append('file_size', String(fileSize));
        const response = await api.post(`/api/batches/${batchId}/generated`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
        return response.data;
    },

    async importImages(
        batchId: string,
        files: Partial<Record<BandType, File | null>>,
        rawParamsMap?: Partial<Record<BandType, RawImageParams>>
    ): Promise<BatchInfo> {
        const formData = new FormData();

        if (files.rgb) formData.append('rgb', files.rgb);
        if (files['560nm']) formData.append('band_560nm', files['560nm']);
        if (files['650nm']) formData.append('band_650nm', files['650nm']);
        if (files['730nm']) formData.append('band_730nm', files['730nm']);
        if (files['850nm']) formData.append('band_850nm', files['850nm']);

        const bandToFormKey: Record<BandType, string> = {
            'rgb': 'raw_params_rgb',
            '560nm': 'raw_params_560nm',
            '650nm': 'raw_params_650nm',
            '730nm': 'raw_params_730nm',
            '850nm': 'raw_params_850nm',
        };
        if (rawParamsMap) {
            for (const band of Object.keys(rawParamsMap) as BandType[]) {
                const params = rawParamsMap[band];
                if (params) {
                    formData.append(bandToFormKey[band], JSON.stringify(params));
                }
            }
        }

        const response = await api.post(`/api/batches/${batchId}/import`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
        return response.data;
    }
};

export const align3dService = {
    async getConfig(): Promise<Align3DConfig> {
        const response = await api.get('/api/align3d/config');
        return response.data;
    },

    async updateConfig(config: Partial<Align3DConfig>): Promise<Align3DConfig> {
        const response = await api.put('/api/align3d/config', config);
        return response.data;
    },

    async listProfiles(): Promise<RigProfileInfo[]> {
        const response = await api.get('/api/align3d/profiles');
        return response.data;
    },

    async deleteProfile(name: string): Promise<void> {
        await api.delete(`/api/align3d/profiles/${encodeURIComponent(name)}`);
    },

    async previewDepth(
        batchId: string,
        referenceImageId?: string,
        align3dParams?: Align3DParams,
    ): Promise<PreviewDepthResponse> {
        const response = await api.post('/api/align3d/preview-depth', {
            batch_id: batchId,
            reference_image_id: referenceImageId,
            align3d_params: align3dParams,
        });
        return response.data;
    },

    async createSelfcalibProfile(
        batchId: string,
        profileName: string = 'selfcalib',
        referenceImageId?: string,
    ): Promise<{ message: string; profile_name: string; path: string; bands: string[] }> {
        const formData = new FormData();
        formData.append('batch_id', batchId);
        formData.append('profile_name', profileName);
        if (referenceImageId) {
            formData.append('reference_image_id', referenceImageId);
        }
        const response = await api.post('/api/align3d/profiles/selfcalib', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
        return response.data;
    },

    async createCheckerboardProfile(
        profileName: string,
        referenceBand: string,
        bands: string[],
        files: File[],
        bandLabels: string[],
    ): Promise<{ message: string; profile_name: string; path: string; bands: string[]; errors: Record<string, number> }> {
        const formData = new FormData();
        formData.append('profile_name', profileName);
        formData.append('reference_band', referenceBand);
        formData.append('bands', bands.join(','));
        formData.append('band_labels', bandLabels.join(','));
        files.forEach(f => formData.append('files', f));
        const response = await api.post('/api/align3d/profiles/checkerboard', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
        return response.data;
    },
};

export { api, API_BASE };

