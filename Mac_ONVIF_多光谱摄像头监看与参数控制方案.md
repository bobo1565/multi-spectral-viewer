# Mac 多路 ONVIF 多光谱摄像头监看与参数控制方案

## 1. 项目背景

本方案面向多路网络摄像头，尤其适用于由多个独立镜头构成的多光谱相机系统，例如：

- RGB
- 560 nm
- 650 nm
- 730 nm
- 850/860 nm

系统运行于 macOS，要求不仅能够同时查看多路视频，还需要能够配置摄像头成像参数，例如：

- 曝光时间（Exposure Time）
- 增益（Gain）
- 自动曝光（Auto Exposure）
- 自动增益（Auto Gain）
- 白平衡（White Balance）
- Gamma
- 亮度（Brightness）
- 对比度（Contrast）
- 锐度（Sharpness）
- 宽动态（WDR）
- 降噪（Noise Reduction）
- IR-Cut / 日夜模式

因此，本项目本质上不是普通的视频监控需求，而是：

> **多路网络摄像头集中控制 + 实时预览 + 成像参数统一管理 + 多光谱数据采集。**

---

## 2. 技术需求分析

### 2.1 视频接入

网络摄像头通常通过以下方式接入：

- IPv4：负责网络地址与通信
- ONVIF：负责设备发现、能力查询、参数配置、PTZ 等
- RTSP：负责实时视频码流传输
- HTTP/CGI/REST API：部分厂商用于扩展参数控制

需要特别说明：

> IPv4 只是网络层协议，实际视频数据通常通过 RTSP 传输。

一个典型摄像头可能类似：

```text
192.168.40.101 → RGB
192.168.40.102 → 560 nm
192.168.40.103 → 650 nm
192.168.40.104 → 730 nm
192.168.40.105 → 850 nm
```

对应视频流：

```text
rtsp://192.168.40.101:554/stream
rtsp://192.168.40.102:554/stream
rtsp://192.168.40.103:554/stream
rtsp://192.168.40.104:554/stream
rtsp://192.168.40.105:554/stream
```

---

## 3. 为什么普通监控软件不完全适合

VLC、Agent DVR、普通 NVR/VMS 软件虽然可以：

- 查看视频
- 多画面显示
- 录像
- RTSP 拉流
- 部分支持 ONVIF 自动发现

但很多软件只使用 ONVIF 的：

- Device Service
- Media Service
- PTZ Service

并没有完整实现：

- **ONVIF Imaging Service**

因此，即使软件写着“支持 ONVIF”，也不代表能够修改：

```text
ExposureTime
Gain
WhiteBalance
Brightness
Contrast
Sharpness
WDR
```

所以选型时不能只看：

> 是否支持 ONVIF

而应该重点确认：

> 是否支持 ONVIF Imaging Service。

---

# 4. 推荐软件方案

## 4.1 Cayenue

### 定位

Cayenue 是一个跨平台的 ONVIF 网络摄像头管理工具，适合作为 macOS 下的免费测试工具。

适合：

- ONVIF 摄像头发现
- 多摄像头管理
- RTSP 视频查看
- 摄像头能力测试
- 部分摄像头参数调整

建议首先使用 Cayenue 检查摄像头是否真正开放了 ONVIF Imaging 参数。

### 推荐程度

```text
★★★★★
```

### 适合当前阶段

主要用于：

> 验证摄像头 ONVIF 能力。

如果 Cayenue 能够读取并修改：

```text
Exposure
Gain
Brightness
Contrast
WhiteBalance
```

说明摄像头的 ONVIF Imaging Service 基本可用。

---

## 4.2 OpenIPC Companion / Configurator

如果摄像头使用 OpenIPC 固件，可以考虑：

```text
OpenIPC Companion
OpenIPC Configurator
```

这类工具可以直接修改：

- 分辨率
- 帧率
- 曝光
- 图像参数
- 编码参数

如果摄像头硬件平台属于：

- HiSilicon
- SigmaStar
- Ingenic
- 其他 OpenIPC 支持平台

则值得重点考虑。

但它的适用前提是：

> 摄像头运行 OpenIPC 固件。

因此它不属于通用 ONVIF 控制方案。

---

## 4.3 摄像头自身 Web 管理页面

很多网络摄像头自身 Web 页面提供最完整的控制能力，包括：

```text
曝光
增益
Gamma
WDR
锐度
降噪
码率
帧率
IR-Cut
图像翻转
白平衡
```

优点：

- 参数最完整
- 厂商支持最好
- 通常能够访问 ISP 的底层设置

缺点：

- 多台摄像头需要逐台配置
- 无法方便地统一控制多个波段
- 不适合自动化实验

因此：

> Web 页面适合调试和确认参数能力，但不适合作为最终多光谱控制系统。

---

# 5. 推荐的最终技术路线

对于多光谱相机系统，推荐最终采用：

```text
Python + PySide6
        │
        ├── ONVIF Imaging API
        │
        ├── RTSP
        │
        ├── FFmpeg / GStreamer
        │
        └── OpenCV
```

实现一个专用：

> **多光谱相机控制台**

---

# 6. 系统总体架构

```text
                    Mac
                     │
            多光谱相机控制台
              Python / PySide6
                     │
        ┌────────────┴────────────┐
        │                         │
    ONVIF 控制                RTSP 视频
        │                         │
        │                   FFmpeg/GStreamer
        │                         │
        │                      OpenCV
        │                         │
 ┌──────┼──────┬──────┬──────┐   │
 │      │      │      │      │   │
RGB    560    650    730    850  │
 │      │      │      │      │   │
曝光   曝光    曝光    曝光    曝光  │
Gain   Gain   Gain   Gain   Gain │
 │      │      │      │      │   │
 └──────┴──────┴──────┴──────┘   │
                     │            │
                     └──────┬─────┘
                            │
                         同步采集
                            │
                  ┌─────────┼─────────┐
                  │         │         │
                图像配准   辐射校正   植被指数
                                    NDVI/GNDVI
```

---

# 7. ONVIF Imaging Service

ONVIF Imaging Service 是本项目的核心。

通常需要实现以下接口。

---

## 7.1 获取当前参数

```text
GetImagingSettings
```

可以读取：

```text
Exposure
Gain
Brightness
Contrast
Sharpness
WhiteBalance
WideDynamicRange
```

示意：

```text
Camera
   ↓
GetImagingSettings
   ↓
Exposure.Mode = MANUAL
Exposure.ExposureTime = 10000
Exposure.Gain = 1.0
```

---

## 7.2 查询可设置范围

必须调用：

```text
GetOptions
```

例如相机可能返回：

```text
ExposureTime:
    min = 100 us
    max = 30000 us

Gain:
    min = 1
    max = 16
```

程序界面必须根据该范围生成控制滑块。

不建议直接假设：

```text
曝光范围 = 1~100 ms
```

不同摄像头可能完全不同。

---

## 7.3 修改参数

使用：

```text
SetImagingSettings
```

例如：

```text
Exposure.Mode = MANUAL
Exposure.ExposureTime = 10000 us
Exposure.Gain = 1.0
```

流程应该是：

```text
发现摄像头
    ↓
获取 VideoSourceToken
    ↓
GetImagingSettings
    ↓
GetOptions
    ↓
用户修改参数
    ↓
SetImagingSettings
```

---

# 8. 多光谱相机为什么必须关闭自动曝光

普通监控摄像头通常默认启用：

```text
Auto Exposure
Auto Gain
Auto White Balance
WDR
Gamma
Noise Reduction
```

这样做的目标是：

> 让画面“看起来更好”。

但多光谱遥感的目标不同。

需要的是：

> 让灰度值具有可比较性。

例如：

```text
真实反射变化
      +
自动曝光变化
      +
自动 Gain
      +
Gamma
      +
WDR
      +
降噪
      ↓
输出灰度值
```

这样无法判断某个像素变亮究竟来自：

- 真实反射率变化
- 曝光时间变化
- Gain 变化
- ISP 调整

因此，多光谱采集建议固定：

```text
Exposure
Gain
Gamma
WDR
Sharpness
Noise Reduction
```

尽量关闭：

```text
Auto Exposure
Auto Gain
Auto White Balance
动态 WDR
自动 Gamma
```

---

# 9. 各波段曝光策略

需要注意：

> 不建议简单要求所有波段曝光时间完全一致。

原因是：

- 滤光片透过率不同
- CMOS 在不同波长的量子效率不同
- 镜头透过率不同
- 光源光谱不同

因此更合理的方法是：

```text
560 nm → 8 ms
650 nm → 10 ms
730 nm → 12 ms
850 nm → 15 ms
```

但是：

> 每个波段自己的曝光参数一旦确定，应保持长期稳定。

例如：

| 波段 | 曝光时间 | Gain |
|---|---:|---:|
| RGB | Auto / 独立控制 | - |
| 560 nm | 8 ms | 1.0 |
| 650 nm | 10 ms | 1.0 |
| 730 nm | 12 ms | 1.0 |
| 850 nm | 15 ms | 1.0 |

---

# 10. 建议的软件界面

可以设计成：

```text
┌─────────────────────────────────────────────┐
│            多光谱相机控制台                 │
├─────────────────────────────────────────────┤
│ RGB     560     650     730     850         │
│ [视频]  [视频]  [视频]  [视频]  [视频]      │
├─────────────────────────────────────────────┤
│ 当前摄像头：650 nm                          │
│                                             │
│ 曝光模式     MANUAL                         │
│ 曝光时间     10000 us                       │
│ Gain         1.0                            │
│ Gamma        1.0                            │
│ Brightness   50                             │
│ Contrast     50                             │
│ Sharpness    0                              │
│ WDR          OFF                            │
│ NoiseReduce  OFF                            │
│                                             │
│ [应用]                                      │
│ [应用到全部摄像头]                          │
│ [保存为配置模板]                            │
├─────────────────────────────────────────────┤
│ [同步抓图] [开始采集] [停止采集]            │
└─────────────────────────────────────────────┘
```

---

# 11. 摄像头配置文件

建议不要把摄像头 IP 写死在程序中。

可以设计：

```yaml
cameras:

  rgb:
    ip: 192.168.40.101
    username: admin
    password: password
    band: RGB

  green:
    ip: 192.168.40.102
    username: admin
    password: password
    band: 560

  red:
    ip: 192.168.40.103
    username: admin
    password: password
    band: 650

  rededge:
    ip: 192.168.40.104
    username: admin
    password: password
    band: 730

  nir:
    ip: 192.168.40.105
    username: admin
    password: password
    band: 850
```

---

# 12. 图像元数据记录

每次采集图像时必须同时记录相机参数。

建议每张图片保存：

```json
{
  "camera_ip": "192.168.40.103",
  "band_nm": 650,
  "timestamp": "2026-08-12T10:32:23.125",
  "exposure_us": 10000,
  "gain": 1.0,
  "gamma": 1.0,
  "auto_exposure": false,
  "auto_gain": false,
  "width": 1920,
  "height": 1080
}
```

推荐目录结构：

```text
dataset/

2026-08-12/

    10-32-23/

        RGB.jpg
        RGB.json

        560.jpg
        560.json

        650.jpg
        650.json

        730.jpg
        730.json

        850.jpg
        850.json
```

这样方便后续：

- 多光谱配准
- 跨时间比较
- 辐射校正
- 植被指数计算
- AI 数据训练
- 实验数据追溯

---

# 13. 视频读取方案

推荐优先级：

## 第一选择：GStreamer

适合：

- 多路 RTSP
- 低延迟
- 实时系统
- 多线程采集

架构：

```text
RTSP
 ↓
GStreamer
 ↓
Decode
 ↓
OpenCV
```

---

## 第二选择：FFmpeg

优点：

- 稳定
- 支持协议多
- 调试方便

架构：

```text
RTSP
 ↓
FFmpeg
 ↓
Python
 ↓
OpenCV
```

---

## 第三选择：OpenCV VideoCapture

可以快速验证：

```python
cv2.VideoCapture(rtsp_url)
```

但是正式系统不建议完全依赖它。

原因：

- RTSP 重连能力有限
- 延迟控制不够灵活
- 多路视频稳定性一般

---

# 14. 推荐开发技术栈

## 桌面界面

推荐：

```text
PySide6
```

理由：

- Qt 官方 Python 绑定
- macOS 支持好
- 多窗口/视频显示方便
- GUI 控件丰富

---

## 摄像头控制

推荐：

```text
Python ONVIF Client
```

实现：

```text
Device Service
Media Service
Imaging Service
```

---

## 视频采集

推荐：

```text
GStreamer
```

或：

```text
FFmpeg
```

---

## 图像处理

推荐：

```text
OpenCV
NumPy
```

---

# 15. 建议的软件模块划分

```text
multispectral-camera-console/

├── app.py
│
├── camera/
│   ├── onvif_client.py
│   ├── imaging_control.py
│   ├── rtsp_stream.py
│   └── camera_manager.py
│
├── acquisition/
│   ├── synchronizer.py
│   ├── recorder.py
│   └── metadata.py
│
├── processing/
│   ├── registration.py
│   ├── radiometric.py
│   ├── ndvi.py
│   └── gndvi.py
│
├── ui/
│   ├── main_window.py
│   ├── camera_panel.py
│   ├── imaging_panel.py
│   └── preview_widget.py
│
├── config/
│   └── cameras.yaml
│
└── data/
```

---

# 16. Camera Manager

建议设计统一的 Camera 类：

```text
Camera
 │
 ├── IP
 ├── Username
 ├── Password
 ├── Band
 │
 ├── connect()
 │
 ├── get_stream_uri()
 │
 ├── get_imaging_settings()
 │
 ├── get_imaging_options()
 │
 ├── set_exposure()
 │
 ├── set_gain()
 │
 └── capture()
```

然后：

```text
CameraManager
 │
 ├── RGB
 ├── 560
 ├── 650
 ├── 730
 └── 850
```

实现统一管理。

---

# 17. 同步采集问题

如果五个网络摄像头都是独立设备，仅依靠：

```text
RTSP
```

不能实现严格的硬件同步。

可能存在：

```text
RGB     10:00:00.010
560     10:00:00.035
650     10:00:00.050
730     10:00:00.070
850     10:00:00.090
```

时间差可能达到几十毫秒甚至更高。

对于：

- 固定植物
- 建筑
- 静态模型
- 校园长期监测

通常可以接受。

但对于：

- 风吹树叶
- 行人
- 车辆
- 无人机
- 运动目标

可能影响配准。

后期如果需要严格同步，应考虑：

```text
Hardware Trigger
PTP
GPIO Trigger
统一时钟
```

---

# 18. ONVIF 不支持曝光控制怎么办

这是实际开发中非常可能遇到的问题。

如果出现：

```text
可以发现摄像头
可以获取 RTSP
可以 PTZ

但是：

无法设置 Exposure
无法设置 Gain
```

说明摄像头可能没有完整实现：

```text
ONVIF Imaging Service
```

这时应该检查厂商是否提供：

```text
HTTP CGI API
REST API
SDK
Private Protocol
```

架构可以改成：

```text
CameraControl
      │
      ├── ONVIF Adapter
      │
      ├── HTTP API Adapter
      │
      ├── CGI Adapter
      │
      └── Vendor SDK Adapter
```

上层程序保持统一接口。

---

# 19. 推荐的研发步骤

## 阶段 1：验证硬件能力

使用：

```text
Cayenue
```

完成：

1. 搜索全部摄像头
2. 验证 RTSP
3. 查看 Imaging 参数
4. 测试曝光时间
5. 测试 Gain
6. 测试白平衡
7. 测试自动曝光关闭
8. 测试参数重启后是否保持

---

## 阶段 2：ONVIF API 验证

编写 Python 测试程序：

```text
connect()
 ↓
get_video_source()
 ↓
get_imaging_options()
 ↓
get_imaging_settings()
 ↓
set_exposure()
 ↓
再次读取验证
```

---

## 阶段 3：单摄像头 GUI

完成：

```text
实时视频
+
曝光设置
+
Gain 设置
```

---

## 阶段 4：扩展到五路摄像头

实现：

```text
RGB
560
650
730
850
```

五路同时预览。

---

## 阶段 5：同步采集

实现：

```text
一键采集
 ↓
五个波段保存
 ↓
保存 Metadata
```

---

## 阶段 6：图像处理

增加：

```text
图像配准
辐射校正
NDVI
GNDVI
```

最终形成完整多光谱采集系统。

---

# 20. 最终推荐

对于当前研发阶段，建议：

```text
Cayenue
    ↓
验证 ONVIF Imaging
```

如果摄像头支持：

```text
GetImagingSettings
GetOptions
SetImagingSettings
```

则继续开发：

```text
Python
+
PySide6
+
ONVIF
+
GStreamer
+
OpenCV
```

形成自己的：

> **多光谱网络相机控制台**

长期来看，这比使用普通 NVR/VMS 更适合多光谱遥感，因为系统可以统一管理：

- 各波段曝光
- Gain
- ISP 参数
- 视频流
- 同步采集
- 元数据
- 配准
- 辐射校正
- NDVI/GNDVI

最终推荐架构：

```text
5 路多光谱摄像头
       │
       ├──────── ONVIF ────────┐
       │                       │
       └──────── RTSP ─────────┤
                               ↓
                    多光谱相机控制台
                Python + PySide6
                               │
                 ┌─────────────┼─────────────┐
                 │             │             │
               参数控制       视频预览       同步采集
                 │             │             │
                 └─────────────┼─────────────┘
                               ↓
                         多光谱数据集
                               │
                  ┌────────────┼────────────┐
                  │            │            │
                配准         辐射校正     NDVI/GNDVI
```

---

## 21. 核心结论

1. **普通 ONVIF 监控软件不一定能够调曝光。**
2. 真正需要确认的是摄像头是否实现了 **ONVIF Imaging Service**。
3. 免费测试工具可以优先使用 **Cayenue**。
4. 如果 ONVIF Imaging 不完整，需要调用厂商 HTTP/CGI/SDK。
5. 对多光谱相机，建议关闭自动曝光、自动增益等会改变灰度关系的 ISP 功能。
6. 各波段曝光时间不一定相同，但确定后应固定并记录。
7. 每次采集必须保存曝光、Gain 等元数据。
8. 最终建议自己开发：
   **PySide6 + ONVIF + GStreamer/FFmpeg + OpenCV**
9. 该控制台后续可自然扩展到：
   - 图像配准
   - 辐射校正
   - NDVI
   - GNDVI
   - 长期时间序列分析

