/**
 * API服务层
 */
import axios from 'axios';
import type { ImageInfo, HistogramData, WhiteBalanceParams, VegetationIndexInfo, BatchInfo, BandType } from '../types';

const API_BASE = import.meta.env.DEV ? 'http://localhost:8000' : '';

const api = axios.create({
    baseURL: API_BASE,
    headers: {
        'Content-Type': 'application/json',
    },
});

// 图像管理
export const imageService = {
    async uploadImage(file: File): Promise<ImageInfo> {
        const formData = new FormData();
        formData.append('file', file);
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

    async calculateIndex(indexName: string, bands: any, colormap: string): Promise<any> {
        const response = await api.post('/api/vegetation/calculate', {
            index_name: indexName,
            bands,
            colormap
        });
        return response.data;
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
export const alignmentService = {
    async batchAlign(batchId: string, overwrite: boolean = true, referenceImageId?: string): Promise<any> {
        const response = await api.post('/api/alignment/batch-align', {
            batch_id: batchId,
            overwrite,
            reference_image_id: referenceImageId
        });
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

    async importImages(
        batchId: string,
        files: Partial<Record<BandType, File | null>>
    ): Promise<BatchInfo> {
        const formData = new FormData();

        if (files.rgb) formData.append('rgb', files.rgb);
        if (files['570nm']) formData.append('band_570nm', files['570nm']);
        if (files['650nm']) formData.append('band_650nm', files['650nm']);
        if (files['730nm']) formData.append('band_730nm', files['730nm']);
        if (files['850nm']) formData.append('band_850nm', files['850nm']);

        const response = await api.post(`/api/batches/${batchId}/import`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
        return response.data;
    }
};

export { api };

