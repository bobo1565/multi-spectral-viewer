/**
 * WebGL 渲染相关类型定义
 */

export const MAX_LAYERS = 4;

/** 色带类型 */
export type ColormapType = 'gray' | 'jet' | 'hot' | 'viridis' | 'rainbow' | 'threshold';

/** 色带配置 */
export interface ColormapState {
  useColormap: boolean;
  colormapType: number; // 0=Jet, 1=Viridis, 2=Rainbow, 3=Gray, 4=Threshold
  scaleMethod: number;  // 0=linear, 1=stddev, 2=histogram
  imageMin: number;
  imageMax: number;
  minValue: number;     // display range min
  maxValue: number;     // display range max
  threshold?: { min: number; max: number };
  autoScale?: boolean;
}

/** 默认色带状态 */
export const DEFAULT_COLORMAP_STATE: ColormapState = {
  useColormap: true,
  colormapType: 3, // Gray
  scaleMethod: 0,  // Linear
  imageMin: 0,
  imageMax: 65535,
  minValue: 0,
  maxValue: 65535,
  autoScale: true,
};

/** 色带类型→数字映射 */
export const COLORMAP_TYPE_MAP: Record<string, number> = {
  'gray': 3,
  'jet': 0,
  'hot': 5,
  'viridis': 1,
  'rainbow': 2,
  'threshold': 4,
};

/** 图层配置 */
export interface WebGLLayerConfig {
  textureIndex: number;
  weight: number;
  isRGB: boolean;
  dataMin: number;
  dataMax: number;
}

/** 像素缓存 */
export interface PixelCache {
  data: Float32Array | Uint8Array | null;
  width: number;
  height: number;
  isRGB: boolean;
  min: number;
  max: number;
  layerIndex: number;
}

/** TIFF 数据响应 */
export interface TiffDataResponse {
  width: number;
  height: number;
  bit_depth: number;
  data_min: number;
  data_max: number;
  data: string; // base64 encoded uint16 array
}

/** 像素值 */
export interface GLPixelValue {
  x: number;
  y: number;
  layers: {
    layerIndex: number;
    value: number | { r: number; g: number; b: number; a: number };
    displayValue: string;
    isRGB: boolean;
    color: string;
    weight: number;
  }[];
}
