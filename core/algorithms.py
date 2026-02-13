"""
图像处理算法模块
包含白平衡和饱和度调节算法
"""
import numpy as np
import cv2


def gray_world_white_balance(img: np.ndarray) -> tuple:
    """
    灰度世界白平衡算法
    假设场景平均颜色为灰色，计算R/G/B增益系数
    
    Args:
        img: BGR格式的图像数组
        
    Returns:
        (r_gain, g_gain, b_gain) 增益元组
    """
    avg_b = np.mean(img[:, :, 0])
    avg_g = np.mean(img[:, :, 1])
    avg_r = np.mean(img[:, :, 2])
    
    avg_gray = (avg_r + avg_g + avg_b) / 3
    
    # 避免除零
    r_gain = avg_gray / avg_r if avg_r > 0 else 1.0
    g_gain = avg_gray / avg_g if avg_g > 0 else 1.0
    b_gain = avg_gray / avg_b if avg_b > 0 else 1.0
    
    return (r_gain, g_gain, b_gain)


def apply_white_balance(img: np.ndarray, r_gain: float, g_gain: float, b_gain: float) -> np.ndarray:
    """
    应用白平衡增益
    
    Args:
        img: BGR格式的图像数组
        r_gain, g_gain, b_gain: 各通道增益系数
        
    Returns:
        调整后的图像数组
    """
    result = img.astype(np.float32)
    result[:, :, 0] = np.clip(result[:, :, 0] * b_gain, 0, 255)
    result[:, :, 1] = np.clip(result[:, :, 1] * g_gain, 0, 255)
    result[:, :, 2] = np.clip(result[:, :, 2] * r_gain, 0, 255)
    return result.astype(np.uint8)


def adjust_saturation(img: np.ndarray, factor: float) -> np.ndarray:
    """
    调节图像饱和度
    
    Args:
        img: BGR格式的图像数组
        factor: 饱和度因子 (0.0 = 灰度, 1.0 = 原始, 2.0 = 两倍饱和度)
        
    Returns:
        调整后的图像数组
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * factor, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def calculate_histogram(img: np.ndarray, is_grayscale: bool = False) -> dict:
    """
    计算图像直方图数据
    
    Args:
        img: 图像数组 (BGR或灰度)
        is_grayscale: 是否为灰度图
        
    Returns:
        包含直方图数据的字典
    """
    if is_grayscale or len(img.shape) == 2:
        gray = img if len(img.shape) == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
        return {'gray': hist}
    else:
        hist_b = cv2.calcHist([img], [0], None, [256], [0, 256]).flatten()
        hist_g = cv2.calcHist([img], [1], None, [256], [0, 256]).flatten()
        hist_r = cv2.calcHist([img], [2], None, [256], [0, 256]).flatten()
        return {'r': hist_r, 'g': hist_g, 'b': hist_b}


def apply_channel_gains(img: np.ndarray, gains: dict) -> np.ndarray:
    """
    应用独立通道增益调整
    
    Args:
        img: BGR格式的图像数组
        gains: 包含各通道增益的字典 {'r': (gain, offset), 'g': (gain, offset), 'b': (gain, offset)}
               gain: 增益系数 (例如 0.5-4.0)
               offset: 偏移量 (例如 -128 到 128)
               
    Returns:
        调整后的图像数组
    """
    result = img.astype(np.float32)
    
    # B 通道 (index 0)
    if 'b' in gains:
        b_gain, b_offset = gains['b']
        result[:, :, 0] = result[:, :, 0] * b_gain + b_offset
    
    # G 通道 (index 1)
    if 'g' in gains:
        g_gain, g_offset = gains['g']
        result[:, :, 1] = result[:, :, 1] * g_gain + g_offset
    
    # R 通道 (index 2)
    if 'r' in gains:
        r_gain, r_offset = gains['r']
        result[:, :, 2] = result[:, :, 2] * r_gain + r_offset
    
    return np.clip(result, 0, 255).astype(np.uint8)


def linear_stretch_channel(img: np.ndarray, channel: int, 
                           input_min: int = None, input_max: int = None,
                           output_min: int = 0, output_max: int = 255) -> np.ndarray:
    """
    对单个通道进行线性拉伸
    
    Args:
        img: BGR格式的图像数组
        channel: 通道索引 (0=B, 1=G, 2=R)
        input_min, input_max: 输入范围，如果为None则自动检测
        output_min, output_max: 输出范围
        
    Returns:
        拉伸后的图像数组
    """
    result = img.copy()
    ch = result[:, :, channel].astype(np.float32)
    
    if input_min is None:
        input_min = ch.min()
    if input_max is None:
        input_max = ch.max()
    
    # 避免除零
    if input_max - input_min < 1:
        return result
    
    # 线性拉伸: output = (input - in_min) * (out_max - out_min) / (in_max - in_min) + out_min
    stretched = (ch - input_min) * (output_max - output_min) / (input_max - input_min) + output_min
    result[:, :, channel] = np.clip(stretched, 0, 255).astype(np.uint8)
    
    return result


def auto_stretch_all_channels(img: np.ndarray, percentile: float = 1.0) -> np.ndarray:
    """
    自动拉伸所有通道的直方图
    
    Args:
        img: BGR格式的图像数组
        percentile: 剪切百分位数 (避免极端值影响)
        
    Returns:
        拉伸后的图像数组
    """
    result = img.copy()
    
    for ch in range(3):
        channel_data = result[:, :, ch]
        in_min = np.percentile(channel_data, percentile)
        in_max = np.percentile(channel_data, 100 - percentile)
        
        if in_max - in_min > 1:
            stretched = (channel_data.astype(np.float32) - in_min) * 255 / (in_max - in_min)
            result[:, :, ch] = np.clip(stretched, 0, 255).astype(np.uint8)
    
    return result

