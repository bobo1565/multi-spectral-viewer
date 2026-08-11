/** align3d API types and service */

export interface Align3DParams {
    depth_min?: number;
    depth_max?: number;
    num_planes?: number;
    depth_backend?: 'auto' | 'plane_sweep' | 'sgbm' | 'torch_stereo';
    cost_method?: 'census' | 'zncc' | 'gradient';
    fallback_to_homography?: boolean;
    rig_profile?: string;
    min_valid_ratio?: number;
}

export interface Align3DConfig extends Required<Pick<Align3DParams, 'depth_min' | 'depth_max' | 'num_planes' | 'depth_backend' | 'fallback_to_homography' | 'rig_profile'>> {
    cost_method: string;
    assumed_hfov_deg: number;
    min_valid_ratio: number;
    min_ncc_improvement: number;
    pyramid_levels: number;
    sgbm_num_disparities: number;
    sgbm_block_size: number;
    use_wls_filter: boolean;
    checkerboard_cols: number;
    checkerboard_rows: number;
    checkerboard_square_size_mm: number;
}

export interface RigProfileInfo {
    name: string;
    reference_band?: string;
    calibration_method?: string;
    created_at?: string;
    bands?: string[];
    path?: string;
    error?: string;
}

export interface PreviewDepthResponse {
    depth_b64: string;
    method: string;
    confidence: number;
    width: number;
    height: number;
}

export interface AlignmentBatchResponse {
    summary: string;
    details: Array<{
        image_id: string;
        success: boolean;
        message: string;
        new_file?: {
            id: string;
            filename: string;
            size: number;
            width: number;
            height: number;
            channels: number;
        };
    }>;
    new_images: Array<{
        id: string;
        filename: string;
        size: number;
        width: number;
        height: number;
        channels: number;
    }>;
}
