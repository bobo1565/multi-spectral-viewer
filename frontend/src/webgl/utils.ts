/**
 * WebGL 工具函数
 */

/**
 * 编译着色器
 */
export function createShader(
  gl: WebGLRenderingContext,
  type: number,
  source: string
): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;

  gl.shaderSource(shader, source);
  gl.compileShader(shader);

  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error('Shader compile error:', gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

/**
 * 链接着色器程序
 */
export function createProgram(
  gl: WebGLRenderingContext,
  vertexShader: WebGLShader,
  fragmentShader: WebGLShader
): WebGLProgram | null {
  const program = gl.createProgram();
  if (!program) return null;

  gl.attachShader(program, vertexShader);
  gl.attachShader(program, fragmentShader);
  gl.linkProgram(program);

  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error('Program link error:', gl.getProgramInfoLog(program));
    gl.deleteProgram(program);
    return null;
  }
  return program;
}

/**
 * 设置全屏四边形几何体
 * 返回需要绑定的 buffer 信息
 */
export function setupGeometry(
  gl: WebGLRenderingContext,
  program: WebGLProgram
): void {
  const positions = new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]);
  const texCoords = new Float32Array([0, 1, 1, 1, 0, 0, 1, 0]);

  // 位置
  const posLoc = gl.getAttribLocation(program, 'a_position');
  const posBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, posBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
  gl.enableVertexAttribArray(posLoc);
  gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

  // 纹理坐标
  const texLoc = gl.getAttribLocation(program, 'a_texCoord');
  const texBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, texBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, texCoords, gl.STATIC_DRAW);
  gl.enableVertexAttribArray(texLoc);
  gl.vertexAttribPointer(texLoc, 2, gl.FLOAT, false, 0, 0);
}

/**
 * 设置纹理单元 uniform
 */
export function setupTextureUnits(
  gl: WebGLRenderingContext,
  program: WebGLProgram,
  maxLayers: number
): void {
  for (let i = 0; i < maxLayers; i++) {
    const loc = gl.getUniformLocation(program, `u_textures[${i}]`);
    gl.uniform1i(loc, i);
  }
}

/**
 * 获取 WebGL 坐标 (从 canvas 鼠标事件)
 * WebGL 坐标系: X 左→右 (-1,1), Y 下→上 (-1,1)
 */
export function getWebGLCoordinates(
  canvas: HTMLCanvasElement,
  clientX: number,
  clientY: number
): { x: number; y: number } {
  const rect = canvas.getBoundingClientRect();
  const x = ((clientX - rect.left) / rect.width) * 2 - 1;
  const y = 1 - ((clientY - rect.top) / rect.height) * 2;
  return { x, y };
}

/**
 * 图像空间坐标 → 像素坐标
 * 图像空间: X 左→右 (-1,1), Y 上→下 (-1,1)
 */
export function getPixelCoordinates(
  imageX: number,
  imageY: number,
  imageWidth: number,
  imageHeight: number
): { x: number; y: number } {
  const pixelX = Math.floor(((imageX + 1) * imageWidth) / 2);
  const pixelY = Math.floor(((1 - imageY) * imageHeight) / 2);
  return { x: pixelX, y: pixelY };
}

/**
 * 解码 base64 字符串为 Uint16Array (little-endian)
 */
export function decodeBase64ToUint16(base64: string): Uint16Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Uint16Array(bytes.buffer);
}

/**
 * Uint16Array → Float32Array (保留原始值)
 */
export function uint16ToFloat32(data: Uint16Array): Float32Array {
  const result = new Float32Array(data.length);
  for (let i = 0; i < data.length; i++) {
    result[i] = data[i];
  }
  return result;
}

/**
 * 检查并获取 WebGL 扩展
 */
export function getFloatTextureExtension(
  gl: WebGLRenderingContext
): OES_texture_float | null {
  const ext = gl.getExtension('OES_texture_float');
  if (!ext) {
    console.warn('OES_texture_float not supported, falling back to Uint8 textures');
  }
  return ext;
}
