/**
 * WebGL 着色器源码
 * 移植自 school-remote-sense WebGLImageViewer.vue
 */

export const MAX_LAYERS = 4;

export const VERTEX_SHADER_SOURCE = `
attribute vec2 a_position;
attribute vec2 a_texCoord;
varying vec2 v_texCoord;
uniform mat4 u_matrix;

void main() {
    gl_Position = u_matrix * vec4(a_position, 0, 1);
    v_texCoord = a_texCoord;
}
`;

export const FRAGMENT_SHADER_SOURCE = `
precision highp float;
varying vec2 v_texCoord;
uniform sampler2D u_textures[${MAX_LAYERS}];
uniform float u_weights[${MAX_LAYERS}];
uniform int u_useColormap;
uniform int u_colormapType;
uniform vec2 u_colormapRange;
uniform float u_scaleMethod;
uniform vec2 u_imageRange[${MAX_LAYERS}];
uniform int u_isRGB[${MAX_LAYERS}];
uniform vec2 u_threshold;
uniform int u_channelMode;

float smartScale(float normalizedValue, vec2 displayRange, vec2 imageRange) {
    float originalValue = normalizedValue * (imageRange.y - imageRange.x) + imageRange.x;

    if (u_scaleMethod == 0.0) {
        return clamp((originalValue - displayRange.x) / (displayRange.y - displayRange.x), 0.0, 1.0);
    }
    else if (u_scaleMethod == 1.0) {
        float mean = (imageRange.x + imageRange.y) * 0.5;
        float stdDev = (imageRange.y - imageRange.x) * 0.34;
        float z = (originalValue - mean) / stdDev;
        return clamp(0.5 + z * 0.2, 0.0, 1.0);
    }
    else {
        float scaled = clamp((originalValue - displayRange.x) / (displayRange.y - displayRange.x), 0.0, 1.0);
        return pow(scaled, 0.5);
    }
}

vec3 getColorFromNormalizedMap(float normalizedValue) {
    if (u_colormapType == 0) {
        // Jet
        float r = clamp(1.5 - abs(4.0 * normalizedValue - 3.0), 0.0, 1.0);
        float g = clamp(1.5 - abs(4.0 * normalizedValue - 2.0), 0.0, 1.0);
        float b = clamp(1.5 - abs(4.0 * normalizedValue - 1.0), 0.0, 1.0);
        return vec3(r, g, b);
    } else if (u_colormapType == 5) {
        // Hot
        return vec3(
            clamp(normalizedValue * 3.0, 0.0, 1.0),
            clamp(normalizedValue * 3.0 - 1.0, 0.0, 1.0),
            clamp(normalizedValue * 3.0 - 2.0, 0.0, 1.0)
        );
    } else if (u_colormapType == 1) {
        // Viridis (approximation)
        return vec3(
            normalizedValue * 0.9 + 0.1,
            normalizedValue * 0.7 + 0.1,
            1.0 - normalizedValue * 0.8
        );
    } else if (u_colormapType == 2) {
        // Rainbow
        return vec3(
            abs(2.0 * normalizedValue - 0.5),
            sin(3.14159 * normalizedValue),
            cos(3.14159 * normalizedValue * 0.5)
        );
    } else if (u_colormapType == 4) {
        // Threshold
        float t = (normalizedValue >= u_threshold.x && normalizedValue <= u_threshold.y) ? 1.0 : 0.0;
        return vec3(t);
    } else {
        // Grayscale (type 3 or default)
        return vec3(normalizedValue);
    }
}

vec3 getColorFromMap(float value, vec2 imageRange) {
    float normalizedValue = smartScale(value, u_colormapRange, imageRange);

    if (u_colormapType == 4) {
        float originalValue = value * (imageRange.y - imageRange.x) + imageRange.x;
        float t = (originalValue >= u_threshold.x && originalValue <= u_threshold.y) ? 1.0 : 0.0;
        return vec3(t);
    }

    return getColorFromNormalizedMap(normalizedValue);
}

vec4 getLayerColor(vec4 texColor, int isRGB, vec2 imageRange) {
    if (isRGB == 1) {
        if (u_channelMode == 1) {
            return vec4(getColorFromNormalizedMap(texColor.r), texColor.a);
        } else if (u_channelMode == 2) {
            return vec4(getColorFromNormalizedMap(texColor.g), texColor.a);
        } else if (u_channelMode == 3) {
            return vec4(getColorFromNormalizedMap(texColor.b), texColor.a);
        }
        return texColor;
    }

    if (u_useColormap == 1) {
        vec3 mappedColor = getColorFromMap(texColor.r, imageRange);
        return vec4(mappedColor, 1.0);
    }

    return texColor;
}

void accumulateLayer(
    vec4 texColor,
    float weight,
    int isRGB,
    vec2 imageRange,
    inout vec4 finalColor,
    inout float sumW
) {
    if (weight <= 0.0) {
        return;
    }
    sumW += weight;
    finalColor += getLayerColor(texColor, isRGB, imageRange) * weight;
}

void main() {
    vec4 finalColor = vec4(0.0);
    float sumW = 0.0;

    // WebGL 1 does not reliably allow dynamic indexing of sampler arrays.
    // Keep texture sampling explicitly unrolled so the shader compiles across browsers.
    accumulateLayer(texture2D(u_textures[0], v_texCoord), u_weights[0], u_isRGB[0], u_imageRange[0], finalColor, sumW);
    accumulateLayer(texture2D(u_textures[1], v_texCoord), u_weights[1], u_isRGB[1], u_imageRange[1], finalColor, sumW);
    accumulateLayer(texture2D(u_textures[2], v_texCoord), u_weights[2], u_isRGB[2], u_imageRange[2], finalColor, sumW);
    accumulateLayer(texture2D(u_textures[3], v_texCoord), u_weights[3], u_isRGB[3], u_imageRange[3], finalColor, sumW);

    if (sumW > 0.0) {
        finalColor.rgb = finalColor.rgb / sumW;
        finalColor.a = clamp(sumW, 0.0, 1.0);
    }

    gl_FragColor = finalColor;
}
`;

/** 标注系统着色器 */
export const ANNOTATION_VERTEX_SHADER = `
attribute vec2 a_position;
uniform mat4 u_matrix;
void main() {
    gl_Position = u_matrix * vec4(a_position, 0, 1);
}
`;

export const ANNOTATION_FRAGMENT_SHADER = `
precision highp float;
uniform vec4 u_color;
void main() {
    gl_FragColor = u_color;
}
`;
