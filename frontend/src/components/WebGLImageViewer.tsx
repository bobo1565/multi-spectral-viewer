/**
 * WebGL 图像查看器组件
 * 移植自 school-remote-sense WebGLImageViewer.vue
 * 支持: float 纹理、色带映射、多层混合、缩放平移、像素拾取
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { Spin } from 'antd';
import { mat4, vec4 } from 'gl-matrix';
import type { ImageInfo } from '../types';
import { API_BASE } from '../services/api';
import {
  MAX_LAYERS,
  VERTEX_SHADER_SOURCE,
  FRAGMENT_SHADER_SOURCE,
} from '../webgl/shaders';
import {
  createShader,
  createProgram,
  setupGeometry,
  setupTextureUnits,
  getWebGLCoordinates,
  getPixelCoordinates,
  decodeBase64ToUint16,
  uint16ToFloat32,
  getFloatTextureExtension,
} from '../webgl/utils';
import type { ColormapState, TiffDataResponse } from '../webgl/types';
import { DEFAULT_COLORMAP_STATE, COLORMAP_TYPE_MAP } from '../webgl/types';
import './WebGLImageViewer.css';

function sanitizeUrlPath(url: string): string {
  try {
    const u = new URL(url);
    // 规范化路径：将 /a/b/../c 解析为 /a/c
    const parts: string[] = [];
    for (const seg of u.pathname.split('/')) {
      if (seg === '' || seg === '.') continue;
      if (seg === '..') {
        parts.pop();
      } else {
        parts.push(seg);
      }
    }
    u.pathname = '/' + parts.join('/');
    return u.toString();
  } catch {
    return url;
  }
}

// ---- 类型 ----

type ChannelType = 'rgb' | 'r' | 'g' | 'b' | 'tiff';

interface PixelValue {
  x: number;
  y: number;
  r: number;
  g: number;
  b: number;
  gray?: number;
}

export interface ViewerLayer {
  id: string;
  url: string;
  opacity?: number;
  blendMode?: React.CSSProperties['mixBlendMode'];
  visible?: boolean;
  clipPath?: string;
}

interface Props {
  image: ImageInfo | null;
  blendedUrl?: string | null;
  channel?: ChannelType;
  colormap?: string;
  colormapState?: ColormapState;
  layers?: ViewerLayer[];
  onPixelHover?: (x: number, y: number) => void;
  onPixelValue?: (pixel: PixelValue) => void;
  onTransformChange?: (transform: {
    scale: number;
    offsetX: number;
    offsetY: number;
    imageWidth: number;
    imageHeight: number;
  }) => void;
  children?: React.ReactNode;
}

// ---- 像素缓存 ----

interface PixelCacheData {
  data: Float32Array | Uint8Array | null;
  width: number;
  height: number;
  isRGB: boolean;
  min: number;
  max: number;
  layerIndex: number;

  initialize(
    gl: WebGLRenderingContext,
    texture: WebGLTexture,
    textureIndex: number,
    width: number,
    height: number,
    isRGB: boolean,
    dataMin: number,
    dataMax: number,
  ): boolean;

  getPixelValue(x: number, y: number): number | { r: number; g: number; b: number; a: number } | null;

  clear(): void;
}

function createPixelCache(): PixelCacheData {
  const cache: PixelCacheData = {
    data: null,
    width: 0,
    height: 0,
    isRGB: false,
    min: 0,
    max: 0,
    layerIndex: 0,

    initialize(gl, texture, textureIndex, width, height, isRGB, dataMin, dataMax) {
      const framebuffer = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);

      if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
        gl.deleteFramebuffer(framebuffer);
        return false;
      }

      const pixels = new Uint8Array(width * height * 4);
      gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);

      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.deleteFramebuffer(framebuffer);

      this.width = width;
      this.height = height;
      this.isRGB = isRGB;
      this.layerIndex = textureIndex;
      this.min = dataMin;
      this.max = dataMax;

      if (isRGB) {
        this.data = pixels;
      } else {
        const floatData = new Float32Array(width * height);
        for (let i = 0; i < width * height; i++) {
          const normalized = pixels[i * 4] / 255.0;
          floatData[i] = normalized * (dataMax - dataMin) + dataMin;
        }
        this.data = floatData;
      }
      return true;
    },

    getPixelValue(x, y) {
      if (!this.data || x < 0 || x >= this.width || y < 0 || y >= this.height) {
        return null;
      }
      const index = y * this.width + x;
      if (this.isRGB && this.data instanceof Uint8Array) {
        const i = index * 4;
        return { r: this.data[i], g: this.data[i + 1], b: this.data[i + 2], a: this.data[i + 3] };
      }
      return (this.data as Float32Array)[index];
    },

    clear() {
      this.data = null;
      this.width = 0;
      this.height = 0;
    },
  };
  return cache;
}

// ---- 组件 ----

export default function WebGLImageViewer({
  image,
  blendedUrl = null,
  channel = 'rgb',
  colormap = 'gray',
  colormapState: colormapStateProp,
  layers = [],
  onPixelHover,
  onPixelValue,
  onTransformChange,
  children,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // WebGL 资源 (不触发重渲染)
  const glRef = useRef<WebGLRenderingContext | null>(null);
  const programRef = useRef<WebGLProgram | null>(null);
  const texturesRef = useRef<(WebGLTexture | null)[]>(new Array(MAX_LAYERS).fill(null));
  const textureSizesRef = useRef<{ width: number; height: number }[]>(
    new Array(MAX_LAYERS).fill({ width: 0, height: 0 }),
  );
  const isRGBArrayRef = useRef<Int32Array>(new Int32Array(MAX_LAYERS));
  const matrixRef = useRef<mat4>(mat4.create());
  const weightsRef = useRef<Float32Array>(new Float32Array(MAX_LAYERS));
  const hasFloatExtRef = useRef(false);
  const hasFloatLinearExtRef = useRef(false);
  const animFrameRef = useRef(0);
  const pixelCacheRef = useRef<PixelCacheData>(createPixelCache());
  const imageRangeRef = useRef<Float32Array>(new Float32Array(MAX_LAYERS * 2)); // [min0,max0, min1,max1, ...]

  // 色带状态
  const colormapStateRef = useRef<ColormapState>(
    colormapStateProp || { ...DEFAULT_COLORMAP_STATE },
  );
  // 用 ref 追踪最新 prop 值 (因为 rAF 闭包问题)
  const colormapPropRef = useRef(colormap);
  const channelPropRef = useRef(channel);

  // 视图状态
  const [scale, setScale] = useState(1);
  const [pixelValue, setPixelValue] = useState<PixelValue | null>(null);
  const [loading, setLoading] = useState(false);
  const [viewReady, setViewReady] = useState(false);

  const scaleRef = useRef(1);
  const offsetRef = useRef({ x: 0, y: 0 });
  const isDraggingRef = useRef(false);
  const lastMouseRef = useRef({ x: 0, y: 0 });
  const renderSizeRef = useRef({ width: 0, height: 0 });
  const lastPixelUpdateRef = useRef(0);
  const needsRenderRef = useRef(true);
  const hasRenderableSource = Boolean(image || blendedUrl);

  // 同步 props → refs
  useEffect(() => {
    colormapPropRef.current = colormap;
    channelPropRef.current = channel;
  }, [colormap, channel]);

  useEffect(() => {
    if (colormapStateProp) {
      colormapStateRef.current = colormapStateProp;
      updateColormapUniforms();
      needsRenderRef.current = true;
    }
  }, [colormapStateProp]);

  // ---- emitTransform ----
  const emitTransform = useCallback(
    (s: number, o: { x: number; y: number }) => {
      onTransformChange?.({
        scale: s,
        offsetX: o.x,
        offsetY: o.y,
        imageWidth: renderSizeRef.current.width,
        imageHeight: renderSizeRef.current.height,
      });
    },
    [onTransformChange],
  );

  // ---- 更新矩阵 ----
  const updateMatrix = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const cw = canvas.width;
    const ch = canvas.height;
    if (!cw || !ch) return;

    const iw = renderSizeRef.current.width;
    const ih = renderSizeRef.current.height;
    const s = scaleRef.current;
    const ox = offsetRef.current.x;
    const oy = offsetRef.current.y;

    const matrix = matrixRef.current;
    mat4.identity(matrix);

    // Pixel-space → clip-space:
    // Quad [-1,1] should map to pixel rect [ox, ox+s*iw] × [oy, oy+s*ih]
    // Clip space: [-1,1] = cw pixels horizontally, ch pixels vertically
    // Scale: make 2 clip-units = s*iw pixels → scaleX = s*iw/cw
    // Translate: move center to (2*centerX/cw - 1, 1 - 2*centerY/ch) in clip space
    const cx = ox + s * iw / 2;
    const cy = oy + s * ih / 2;

    mat4.translate(matrix, matrix, [
      2 * cx / cw - 1,
      1 - 2 * cy / ch,
      0,
    ]);
    mat4.scale(matrix, matrix, [
      s * iw / cw,
      s * ih / ch,
      1,
    ]);
  }, []);

  // ---- 更新色带 uniforms ----
  const updateColormapUniforms = useCallback(() => {
    const gl = glRef.current;
    const program = programRef.current;
    if (!gl || !program) return;

    const state = colormapStateRef.current;
    gl.useProgram(program);
    gl.uniform1i(gl.getUniformLocation(program, 'u_useColormap'), state.useColormap ? 1 : 0);
    gl.uniform1i(gl.getUniformLocation(program, 'u_colormapType'), state.colormapType);
    gl.uniform2f(gl.getUniformLocation(program, 'u_colormapRange'), state.minValue, state.maxValue);
    gl.uniform1f(gl.getUniformLocation(program, 'u_scaleMethod'), state.scaleMethod || 0);
    const channelMode = channelPropRef.current === 'r'
      ? 1
      : channelPropRef.current === 'g'
        ? 2
        : channelPropRef.current === 'b'
          ? 3
          : 0;
    gl.uniform1i(gl.getUniformLocation(program, 'u_channelMode'), channelMode);
    gl.uniform2f(
      gl.getUniformLocation(program, 'u_threshold'),
      state.threshold?.min ?? 0,
      state.threshold?.max ?? 1,
    );
  }, []);

  // ---- 初始化 WebGL ----
  const initWebGL = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext('webgl', {
      preserveDrawingBuffer: true,
      alpha: true,
      premultipliedAlpha: false,
    });
    if (!gl) {
      console.error('WebGL not supported');
      return;
    }
    glRef.current = gl;

    // Float 纹理扩展
    hasFloatExtRef.current = !!getFloatTextureExtension(gl);
    hasFloatLinearExtRef.current = !!gl.getExtension('OES_texture_float_linear');

    // 编译着色器
    const vs = createShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER_SOURCE);
    const fs = createShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER_SOURCE);
    if (!vs || !fs) return;

    const program = createProgram(gl, vs, fs);
    if (!program) return;

    programRef.current = program;
    gl.useProgram(program);

    setupGeometry(gl, program);
    setupTextureUnits(gl, program, MAX_LAYERS);

    // 初始化 weights
    weightsRef.current.fill(0);
    gl.uniform1fv(gl.getUniformLocation(program, 'u_weights'), weightsRef.current);

    // 初始化 isRGB
    isRGBArrayRef.current.fill(0);
    gl.uniform1iv(gl.getUniformLocation(program, 'u_isRGB'), isRGBArrayRef.current);

    // 初始化 imageRange
    for (let i = 0; i < MAX_LAYERS; i++) {
      imageRangeRef.current[i * 2] = 0;
      imageRangeRef.current[i * 2 + 1] = 1;
    }

    updateMatrix();
    updateColormapUniforms();

    // 设置初始 imageRange uniforms
    for (let i = 0; i < MAX_LAYERS; i++) {
      const loc = gl.getUniformLocation(program, `u_imageRange[${i}]`);
      gl.uniform2f(loc, 0, 1);
    }
  }, [updateMatrix, updateColormapUniforms]);

  // ---- 上传 TIFF 浮点数据到纹理 ----
  const uploadFloatTexture = useCallback(
    (textureIndex: number, floatData: Float32Array, width: number, height: number) => {
      const gl = glRef.current;
      const program = programRef.current;
      if (!gl || !program) return;

      // 计算 min/max
      let min = Infinity;
      let max = -Infinity;
      for (let i = 0; i < floatData.length; i++) {
        if (floatData[i] < min) min = floatData[i];
        if (floatData[i] > max) max = floatData[i];
      }
      if (!isFinite(min)) min = 0;
      if (!isFinite(max)) max = 1;
      if (max === min) max = min + 1;

      // 更新色带范围
      const state = colormapStateRef.current;
      state.imageMin = min;
      state.imageMax = max;
      if (state.autoScale) {
        state.minValue = min;
        state.maxValue = max;
      }

      // 更新 imageRange
      imageRangeRef.current[textureIndex * 2] = min;
      imageRangeRef.current[textureIndex * 2 + 1] = max;

      const texture = gl.createTexture();
      gl.activeTexture(gl.TEXTURE0 + textureIndex);
      gl.bindTexture(gl.TEXTURE_2D, texture);

      const maxTexSize = gl.getParameter(gl.MAX_TEXTURE_SIZE);
      let textureUsesFloatData = false;

      if (hasFloatExtRef.current) {
        // Float 纹理路径: 保留完整精度
        const floatTexData = new Float32Array(width * height * 4);
        for (let i = 0; i < floatData.length; i++) {
          const normalized = (floatData[i] - min) / (max - min);
          floatTexData[i * 4] = normalized;
          floatTexData[i * 4 + 1] = normalized;
          floatTexData[i * 4 + 2] = normalized;
          floatTexData[i * 4 + 3] = 1.0;
        }

        if (width > maxTexSize || height > maxTexSize) {
          const scale = Math.min(maxTexSize / width, maxTexSize / height);
          const sw = Math.floor(width * scale);
          const sh = Math.floor(height * scale);
          const tempCanvas = document.createElement('canvas');
          tempCanvas.width = sw;
          tempCanvas.height = sh;
          const ctx = tempCanvas.getContext('2d');
          if (ctx) {
            const rgbaData = new Uint8ClampedArray(floatData.length * 4);
            for (let i = 0; i < floatData.length; i++) {
              const v = Math.round(((floatData[i] - min) / (max - min)) * 255);
              rgbaData[i * 4] = v;
              rgbaData[i * 4 + 1] = v;
              rgbaData[i * 4 + 2] = v;
              rgbaData[i * 4 + 3] = 255;
            }
            const imgData = new ImageData(rgbaData, width, height);
            ctx.putImageData(imgData, 0, 0);
            // 用 canvas 缩放后回退到 Uint8
            const scaledCanvas = document.createElement('canvas');
            scaledCanvas.width = sw;
            scaledCanvas.height = sh;
            const sctx = scaledCanvas.getContext('2d');
            if (sctx) {
              sctx.drawImage(tempCanvas, 0, 0, sw, sh);
              gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, scaledCanvas);
            }
          }
        } else {
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.FLOAT, floatTexData);
          textureUsesFloatData = true;
        }
      } else {
        // Uint8 回退路径
        const rgbaData = new Uint8Array(width * height * 4);
        for (let i = 0; i < floatData.length; i++) {
          const normalized = (floatData[i] - min) / (max - min);
          const value = Math.round(normalized * 255);
          rgbaData[i * 4] = value;
          rgbaData[i * 4 + 1] = value;
          rgbaData[i * 4 + 2] = value;
          rgbaData[i * 4 + 3] = 255;
        }

        if (width > maxTexSize || height > maxTexSize) {
          const scale = Math.min(maxTexSize / width, maxTexSize / height);
          const sw = Math.floor(width * scale);
          const sh = Math.floor(height * scale);
          const tempCanvas = document.createElement('canvas');
          tempCanvas.width = width;
          tempCanvas.height = height;
          const ctx = tempCanvas.getContext('2d');
          if (ctx) {
            const imgData = new ImageData(new Uint8ClampedArray(rgbaData), width, height);
            ctx.putImageData(imgData, 0, 0);
            const scaledCanvas = document.createElement('canvas');
            scaledCanvas.width = sw;
            scaledCanvas.height = sh;
            const sctx = scaledCanvas.getContext('2d');
            if (sctx) {
              sctx.drawImage(tempCanvas, 0, 0, sw, sh);
              gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, scaledCanvas);
            }
          }
        } else {
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, rgbaData);
        }
      }

      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      const filter = textureUsesFloatData && !hasFloatLinearExtRef.current ? gl.NEAREST : gl.LINEAR;
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);

      // 清理旧纹理
      if (texturesRef.current[textureIndex]) {
        gl.deleteTexture(texturesRef.current[textureIndex]!);
      }
      texturesRef.current[textureIndex] = texture;
      textureSizesRef.current[textureIndex] = { width, height };
      isRGBArrayRef.current[textureIndex] = 0;

      // 更新 shader uniforms
      gl.uniform1iv(gl.getUniformLocation(program, 'u_isRGB'), isRGBArrayRef.current);
      const rangeLoc = gl.getUniformLocation(program, `u_imageRange[${textureIndex}]`);
      gl.uniform2f(rangeLoc, min, max);

      renderSizeRef.current = { width, height };
      updateColormapUniforms();

      // 初始化像素缓存
      pixelCacheRef.current.initialize(gl, texture, textureIndex, width, height, false, min, max);

      // 加载完成后重置视图
      setViewReady(false);
      setTimeout(() => {
        resetView();
        setViewReady(true);
      }, 50);
    },
    [updateColormapUniforms],
  );

  // ---- 上传 RGB 图像到纹理 ----
  const uploadImageTexture = useCallback(
    (textureIndex: number, imageElement: HTMLImageElement) => {
      const gl = glRef.current;
      const program = programRef.current;
      if (!gl || !program) return;

      const width = imageElement.width;
      const height = imageElement.height;

      const texture = gl.createTexture();
      gl.activeTexture(gl.TEXTURE0 + textureIndex);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, imageElement);

      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

      if (texturesRef.current[textureIndex]) {
        gl.deleteTexture(texturesRef.current[textureIndex]!);
      }
      texturesRef.current[textureIndex] = texture;
      textureSizesRef.current[textureIndex] = { width, height };
      isRGBArrayRef.current[textureIndex] = 1;

      gl.uniform1iv(gl.getUniformLocation(program, 'u_isRGB'), isRGBArrayRef.current);
      const rangeLoc = gl.getUniformLocation(program, `u_imageRange[${textureIndex}]`);
      gl.uniform2f(rangeLoc, 0, 255);
      imageRangeRef.current[textureIndex * 2] = 0;
      imageRangeRef.current[textureIndex * 2 + 1] = 255;

      renderSizeRef.current = { width, height };

      pixelCacheRef.current.initialize(gl, texture, textureIndex, width, height, true, 0, 255);

      setViewReady(false);
      setTimeout(() => {
        resetView();
        setViewReady(true);
      }, 50);
    },
    [],
  );

  // ---- 加载 TIFF 数据 ----
  const loadTiffData = useCallback(
    async (imageId: string) => {
      setLoading(true);
      try {
        const url = `${API_BASE}/api/images/${imageId}/tiff-data`;
        const response = await fetch(url);
        const json: TiffDataResponse = await response.json();

        // 解码 base64 → Uint16 → Float32
        const uint16Data = decodeBase64ToUint16(json.data);
        const floatData = uint16ToFloat32(uint16Data);

        uploadFloatTexture(0, floatData, json.width, json.height);

        // 设置权重 (仅基础层)
        weightsRef.current[0] = 1.0;
        for (let i = 1; i < MAX_LAYERS; i++) weightsRef.current[i] = 0;
        const gl = glRef.current;
        if (gl && programRef.current) {
          gl.uniform1fv(
            gl.getUniformLocation(programRef.current, 'u_weights'),
            weightsRef.current,
          );
        }
      } catch (err) {
        console.error('Failed to load TIFF data:', err);
        // 回退: 使用 tiff-preview 作为 RGB 图像
        await loadImageUrl(`${API_BASE}/api/images/${imageId}/tiff-preview`);
      } finally {
        setLoading(false);
        needsRenderRef.current = true;
      }
    },
    [uploadFloatTexture],
  );

  // ---- 加载普通图像 URL ----
  const loadImageUrl = useCallback(
    async (url: string) => {
      setLoading(true);
      try {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        await new Promise<void>((resolve, reject) => {
          img.onload = () => resolve();
          img.onerror = reject;
          img.src = url;
        });
        uploadImageTexture(0, img);

        weightsRef.current[0] = 1.0;
        for (let i = 1; i < MAX_LAYERS; i++) weightsRef.current[i] = 0;
        const gl = glRef.current;
        if (gl && programRef.current) {
          gl.uniform1fv(
            gl.getUniformLocation(programRef.current, 'u_weights'),
            weightsRef.current,
          );
        }
      } catch (err) {
        console.error('Failed to load image URL:', url, err);
      } finally {
        setLoading(false);
        needsRenderRef.current = true;
      }
    },
    [uploadImageTexture],
  );

  // ---- 加载覆盖层纹理 ----
  const loadOverlayTexture = useCallback(
    async (textureIndex: number, url: string) => {
      const gl = glRef.current;
      if (!gl) return;

      try {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        await new Promise<void>((resolve, reject) => {
          img.onload = () => resolve();
          img.onerror = reject;
          img.src = url;
        });

        const texture = gl.createTexture();
        gl.activeTexture(gl.TEXTURE0 + textureIndex);
        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

        if (texturesRef.current[textureIndex]) {
          gl.deleteTexture(texturesRef.current[textureIndex]!);
        }
        texturesRef.current[textureIndex] = texture;
        textureSizesRef.current[textureIndex] = { width: img.width, height: img.height };
        isRGBArrayRef.current[textureIndex] = 1;

        gl.uniform1iv(gl.getUniformLocation(programRef.current!, 'u_isRGB'), isRGBArrayRef.current);
        const rangeLoc = gl.getUniformLocation(programRef.current!, `u_imageRange[${textureIndex}]`);
        gl.uniform2f(rangeLoc, 0, 255);
      } catch (err) {
        console.error('Failed to load overlay texture:', url, err);
      }
    },
    [],
  );

  // ---- 更新覆盖层 ----
  useEffect(() => {
    if (!glRef.current) return;

    const activeLayers = layers.filter((l) => l.visible !== false);
    let totalOverlayOpacity = 0;
    for (let i = 0; i < Math.min(activeLayers.length, MAX_LAYERS - 1); i++) {
      const layer = activeLayers[i];
      const texIndex = i + 1;
      if (layer.url) {
        loadOverlayTexture(texIndex, layer.url);
        const w = (layer.opacity ?? 1);
        weightsRef.current[texIndex] = w;
        totalOverlayOpacity += w;
      } else {
        weightsRef.current[texIndex] = 0;
      }
    }
    // 清除多余的覆盖层
    for (let i = activeLayers.length + 1; i < MAX_LAYERS; i++) {
      weightsRef.current[i] = 0;
    }

    // 调整基础图层权重，使加权平均模拟正确的透明度混合：
    // result = base*(1-opacity) + overlay*opacity
    weightsRef.current[0] = Math.max(0, 1 - totalOverlayOpacity);

    const gl = glRef.current;
    if (gl && programRef.current) {
      gl.uniform1fv(
        gl.getUniformLocation(programRef.current, 'u_weights'),
        weightsRef.current,
      );
    }
    needsRenderRef.current = true;
  }, [layers, loadOverlayTexture]);

  // ---- 重置视图 ----
  const resetView = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const cw = container.clientWidth;
    const ch = container.clientHeight;
    const iw = renderSizeRef.current.width;
    const ih = renderSizeRef.current.height;
    if (!iw || !ih) return;

    const newScale = Math.min(cw / iw, ch / ih, 1) * 0.9;
    const newOffset = {
      x: (cw - iw * newScale) / 2,
      y: (ch - ih * newScale) / 2,
    };

    setScale(newScale);
    scaleRef.current = newScale;
    offsetRef.current = newOffset;
    updateMatrix();
    emitTransform(newScale, newOffset);
    needsRenderRef.current = true;
  }, [emitTransform, updateMatrix]);

  // ---- 缩放 ----
  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      const zoomFactor = 1.1;
      const direction = e.deltaY < 0 ? 1 : -1;
      const currentScale = scaleRef.current;
      const newScale =
        direction > 0
          ? Math.min(currentScale * zoomFactor, 20)
          : Math.max(currentScale / zoomFactor, 0.05);

      if (newScale === currentScale) return;

      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;

      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const ratio = newScale / currentScale;
      const newOffset = {
        x: mx - ratio * (mx - offsetRef.current.x),
        y: my - ratio * (my - offsetRef.current.y),
      };

      setScale(newScale);
      scaleRef.current = newScale;
      offsetRef.current = newOffset;
      updateMatrix();
      emitTransform(newScale, newOffset);
      needsRenderRef.current = true;
    },
    [emitTransform, updateMatrix],
  );

  // ---- 平移 ----
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    isDraggingRef.current = true;
    lastMouseRef.current = { x: e.clientX, y: e.clientY };
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const coords = getWebGLCoordinates(canvas, e.clientX, e.clientY);

      if (isDraggingRef.current) {
        const dx = e.clientX - lastMouseRef.current.x;
        const dy = e.clientY - lastMouseRef.current.y;
        lastMouseRef.current = { x: e.clientX, y: e.clientY };
        offsetRef.current = {
          x: offsetRef.current.x + dx,
          y: offsetRef.current.y + dy,
        };
        updateMatrix();
        needsRenderRef.current = true;
        return;
      }

      // 像素拾取 (非拖拽时)
      if (!texturesRef.current[0]) return;
      const texSize = textureSizesRef.current[0];
      if (!texSize.width || !texSize.height) return;

      const invMatrix = mat4.create();
      mat4.invert(invMatrix, matrixRef.current);
      const point = vec4.fromValues(coords.x, coords.y, 0, 1);
      const transformed = vec4.create();
      vec4.transformMat4(transformed, point, invMatrix);

      const pixel = getPixelCoordinates(transformed[0], transformed[1], texSize.width, texSize.height);

      if (pixel.x >= 0 && pixel.x < texSize.width && pixel.y >= 0 && pixel.y < texSize.height) {
        onPixelHover?.(pixel.x, pixel.y);

        const now = performance.now();
        if (now - lastPixelUpdateRef.current < 33) return;
        lastPixelUpdateRef.current = now;

        // 从缓存读取像素值
        const cache = pixelCacheRef.current;
        if (cache.data && cache.layerIndex === 0) {
          const value = cache.getPixelValue(pixel.x, pixel.y);
          if (value !== null) {
            if (typeof value === 'object' && 'r' in value) {
              setPixelValue({ x: pixel.x, y: pixel.y, r: value.r, g: value.g, b: value.b });
              onPixelValue?.({ x: pixel.x, y: pixel.y, r: value.r, g: value.g, b: value.b });
            } else {
              const v = value as number;
              setPixelValue({ x: pixel.x, y: pixel.y, r: v, g: v, b: v, gray: v });
              onPixelValue?.({ x: pixel.x, y: pixel.y, r: v, g: v, b: v, gray: v });
            }
          }
        }
      }
    };

    const handleMouseUp = () => {
      isDraggingRef.current = false;
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [onPixelHover, onPixelValue, updateMatrix]);

  // ---- 渲染循环 ----
  useEffect(() => {
    let running = true;

    const render = () => {
      if (!running) return;
      const gl = glRef.current;
      const program = programRef.current;
      if (!gl || !program) {
        animFrameRef.current = requestAnimationFrame(render);
        return;
      }

      const canvas = canvasRef.current;
      if (canvas && (canvas.width !== canvas.clientWidth || canvas.height !== canvas.clientHeight)) {
        canvas.width = canvas.clientWidth;
        canvas.height = canvas.clientHeight;
        needsRenderRef.current = true;
      }

      if (needsRenderRef.current) {
        gl.viewport(0, 0, gl.canvas.width, gl.canvas.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);

        gl.useProgram(program);
        setupGeometry(gl, program);
        gl.uniformMatrix4fv(gl.getUniformLocation(program, 'u_matrix'), false, matrixRef.current);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

        needsRenderRef.current = false;
      }

      animFrameRef.current = requestAnimationFrame(render);
    };

    animFrameRef.current = requestAnimationFrame(render);
    return () => {
      running = false;
      cancelAnimationFrame(animFrameRef.current);
    };
  }, []);

  // ---- 初始化 ----
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !hasRenderableSource) return;
    canvas.width = canvas.clientWidth;
    canvas.height = canvas.clientHeight;

    initWebGL();
    needsRenderRef.current = true;

    const handleResize = () => {
      if (!canvasRef.current) return;
      canvasRef.current.width = canvasRef.current.clientWidth;
      canvasRef.current.height = canvasRef.current.clientHeight;
      needsRenderRef.current = true;
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      // 清理 WebGL 资源
      const gl = glRef.current;
      if (gl) {
        texturesRef.current.forEach((t) => {
          if (t) gl.deleteTexture(t);
        });
        gl.getExtension('WEBGL_lose_context')?.loseContext();
      }
      pixelCacheRef.current.clear();
    };
  }, [hasRenderableSource, initWebGL]);

  // ---- 加载图像 ----
  useEffect(() => {
    setPixelValue(null);
    pixelCacheRef.current.clear();
    renderSizeRef.current = { width: 0, height: 0 };

    if (blendedUrl) {
      loadImageUrl(blendedUrl);
    } else if (image) {
      const isTiff = image.filename?.toLowerCase().endsWith('.tiff') || image.filename?.toLowerCase().endsWith('.tif');
      if (channel === 'tiff' && isTiff) {
        loadTiffData(image.id);
      } else if (isTiff) {
        loadImageUrl(`${API_BASE}/api/images/${image.id}/tiff-preview`);
      } else {
        const imageUrl = image.url
          ? sanitizeUrlPath(`${API_BASE}${image.url}`)
          : `${API_BASE}/api/images/${image.id}`;
        loadImageUrl(imageUrl);
      }
    } else {
      // 清除纹理
      const gl = glRef.current;
      if (gl) {
        for (let i = 0; i < MAX_LAYERS; i++) {
          if (texturesRef.current[i]) {
            gl.deleteTexture(texturesRef.current[i]!);
            texturesRef.current[i] = null;
          }
          weightsRef.current[i] = 0;
          if (programRef.current) {
            gl.uniform1fv(
              gl.getUniformLocation(programRef.current, 'u_weights'),
              weightsRef.current,
            );
          }
        }
      }
      needsRenderRef.current = true;
    }
  }, [image?.id, image?.url, image?.filename, blendedUrl, channel, loadImageUrl, loadTiffData]);

  // ---- 更新色带 ----
  useEffect(() => {
    const gl = glRef.current;
    const program = programRef.current;
    if (!gl || !program) return;

    const colormapType = COLORMAP_TYPE_MAP[colormap] ?? 3;
    colormapStateRef.current.colormapType = colormapType;
    colormapStateRef.current.useColormap = colormap !== 'rgb' || channel === 'tiff';
    updateColormapUniforms();
    needsRenderRef.current = true;
  }, [colormap, channel, updateColormapUniforms]);

  // ---- 鼠标离开 ----
  const handleMouseLeave = useCallback(() => {
    setPixelValue(null);
  }, []);

  // ---- 缩放按钮 ----
  const handleZoomIn = useCallback(() => {
    const s = scaleRef.current * 1.2;
    const newScale = Math.min(s, 20);
    scaleRef.current = newScale;
    setScale(newScale);
    updateMatrix();
    emitTransform(newScale, offsetRef.current);
    needsRenderRef.current = true;
  }, [emitTransform, updateMatrix]);

  const handleZoomOut = useCallback(() => {
    const s = scaleRef.current / 1.2;
    const newScale = Math.max(s, 0.05);
    scaleRef.current = newScale;
    setScale(newScale);
    updateMatrix();
    emitTransform(newScale, offsetRef.current);
    needsRenderRef.current = true;
  }, [emitTransform, updateMatrix]);

  // ---- 空状态 ----
  if (!image && !blendedUrl) {
    return (
      <div className="webgl-viewer empty">
        <div className="placeholder">请选择或上传图像</div>
      </div>
    );
  }

  const channelLabel: Record<string, string> = {
    rgb: 'RGB 彩图',
    r: 'R 通道 (灰度)',
    g: 'G 通道 (灰度)',
    b: 'B 通道 (灰度)',
    tiff: 'TIFF 灰度',
  };
  const displayTitle = image ? image.filename : '计算结果';
  const displayLabel = channelLabel[channel] || '';

  return (
    <div className="webgl-viewer">
      <div className="viewer-header">
        <span>
          {displayTitle}
          <span className={`channel-badge channel-${channel}`}>{displayLabel}</span>
        </span>
        <div className="zoom-controls">
          <button onClick={handleZoomOut} title="缩小">−</button>
          <span>{Math.round(scale * 100)}%</span>
          <button onClick={handleZoomIn} title="放大">+</button>
          <button onClick={resetView} title="适应视图">⊡</button>
        </div>
      </div>

      <div
        className="viewer-container"
        ref={containerRef}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseLeave={handleMouseLeave}
      >
        {loading && (
          <div className="loading-spin">
            <Spin />
          </div>
        )}
        <canvas ref={canvasRef} className="webgl-canvas" />
        {viewReady && children}
      </div>

      {/* 像素状态栏 */}
      <div className="pixel-status-bar">
        {image ? (
          <>
            <span className="info-item">{image.width} × {image.height}</span>
            <span className="info-item">{image.channels}通道</span>
            <span className="info-item">{(image.size / 1024).toFixed(1)} KB</span>
            <span className="divider">|</span>
          </>
        ) : (
          <span className="info-item">计算结果图像</span>
        )}
        {pixelValue ? (
          <>
            <span className="coord">X: {pixelValue.x}, Y: {pixelValue.y}</span>
            {pixelValue.gray !== undefined ? (
              <span className="pixel-gray">
                Gray: {typeof pixelValue.gray === 'number' ? pixelValue.gray.toFixed(4) : pixelValue.gray}
                <span className="mapped-color" style={{ marginLeft: 8, fontSize: 10, color: '#999' }}>
                  (Mapped: {Math.round(pixelValue.r)}, {Math.round(pixelValue.g)}, {Math.round(pixelValue.b)})
                </span>
              </span>
            ) : (
              <span className="pixel-rgb">
                <span className="r">R: {pixelValue.r}</span>
                <span className="g">G: {pixelValue.g}</span>
                <span className="b">B: {pixelValue.b}</span>
              </span>
            )}
          </>
        ) : (
          <span className="hint">移动鼠标查看像素值</span>
        )}
      </div>
    </div>
  );
}
