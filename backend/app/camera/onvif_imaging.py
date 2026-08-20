#!/usr/bin/env python3
"""
ONVIF Imaging Service 客户端

对应《Mac_ONVIF_多光谱摄像头监看与参数控制方案》§7：
  发现摄像头 → 获取 VideoSourceToken → GetImagingSettings / GetOptions
  → 用户修改参数 → SetImagingSettings

多光谱采集要求灰度值可比较（§8），因此本模块的核心用途是：
固定曝光 / Gain / 白平衡，关闭 AUTO 类 ISP 功能。

注意：不同摄像头 ONVIF 服务端口不同（实测本项目的雄迈方案相机在 8899），
因此连接时做端口探测并缓存结果。
"""
from __future__ import annotations

import socket
import threading
from typing import Dict, List, Optional
from urllib.parse import urlparse

from zeep.transports import Transport


class ImagingError(Exception):
    """ONVIF Imaging 相关错误（消息面向用户，使用中文）"""


# ONVIF 服务常见端口。实测本项目摄像头（雄迈方案）在 8899；
# 海康等在 80，部分在 8080/2020/8000。
ONVIF_PORTS = [8899, 80, 8080, 2020, 8000]

# zeep 网络超时（秒）：局域网设备应快速响应，避免离线摄像头拖死线程
_CONNECT_TIMEOUT = 3
_OPERATION_TIMEOUT = 6

# 归一化后支持的枚举取值（供前端渲染选项）
EXPOSURE_MODES = ["AUTO", "MANUAL"]
WB_MODES = ["AUTO", "MANUAL"]
WDR_MODES = ["ON", "OFF"]
IR_CUT_MODES = ["ON", "OFF", "AUTO"]
BLC_MODES = ["OFF", "ON"]

# 归一化字段名 → 中文名（用于拒绝/未生效提示）
FIELD_LABELS = {
    'exposure_mode': '曝光模式',
    'exposure_time_us': '曝光时间',
    'min_exposure_time_us': '曝光下限',
    'max_exposure_time_us': '曝光上限',
    'gain': '增益',
    'brightness': '亮度',
    'contrast': '对比度',
    'saturation': '饱和度',
    'sharpness': '锐度',
    'wb_mode': '白平衡模式',
    'wb_r_gain': '白平衡R增益',
    'wb_b_gain': '白平衡B增益',
    'wdr_mode': '宽动态WDR',
    'wdr_level': 'WDR强度',
    'ir_cut': 'IR-Cut',
    'blc_mode': '背光补偿',
    'blc_level': '背光补偿强度',
}


def describe_rejection(err: str) -> str:
    """把相机的原始拒绝信息翻译成用户可读的说明"""
    if 'settings are incorrect' in err:
        return (
            "相机拒绝了参数设置：请求的值超出当前允许范围或不支持"
            "（注意：曝光时间不能超过帧周期，如 25fps 时上限约 40000us）"
        )
    if 'ter:ActionNotSupported' in err or 'not supported' in err.lower():
        return f"相机不支持该参数设置：{err}"
    return f"相机拒绝了参数设置：{err}"


def _check_port(ip: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def credentials_from_stream_url(stream_url: str) -> tuple:
    """从 rtsp://user:pass@host/... 中解析 (username, password) 作为兜底凭据"""
    try:
        parsed = urlparse(stream_url)
        return parsed.username or "", parsed.password or ""
    except Exception:
        return "", ""


class ImagingClient:
    """单台摄像头的 ONVIF Imaging 控制客户端"""

    def __init__(self, ip: str, username: str = "", password: str = ""):
        self.ip = ip
        self.username = username or ""
        self.password = password or ""
        self.port: Optional[int] = None
        self._cam = None
        self._imaging = None
        self._vs_token: Optional[str] = None
        # 雄迈 Sofia 私有协议客户端：这批相机的 ONVIF 曝光是"假设置"，
        # 曝光/增益必须走 Sofia 才真实生效（None 表示该相机不支持 Sofia）
        self._sofia = None
        self._lock = threading.Lock()

    # ---------- 连接 ----------

    def _make_transport(self) -> Transport:
        return Transport(timeout=_CONNECT_TIMEOUT, operation_timeout=_OPERATION_TIMEOUT)

    def _connect_unlocked(self):
        """端口探测 + 建立 ONVIF 连接（需在 self._lock 内调用）"""
        from onvif import ONVIFCamera  # 延迟导入，加快模块加载

        ports = ([self.port] if self.port else []) + [p for p in ONVIF_PORTS if p != self.port]
        last_err: Optional[Exception] = None

        for port in ports:
            if not _check_port(self.ip, port):
                continue
            try:
                cam = ONVIFCamera(self.ip, port, self.username, self.password,
                                  transport=self._make_transport())
                media = cam.create_media_service()
                sources = media.GetVideoSources()
                if not sources:
                    raise ImagingError("摄像头未返回任何视频源")
                self._cam = cam
                self._imaging = cam.create_imaging_service()
                self._vs_token = sources[0].token
                self.port = port
                # 探测雄迈 Sofia 私有协议（曝光/增益的真实通道）
                try:
                    from .sofia_control import probe_sofia_client
                    self._sofia = probe_sofia_client(self.ip, self.username, self.password)
                    if self._sofia is not None:
                        print(f"[Imaging {self.ip}] 检测到雄迈 Sofia 协议，曝光/增益走私有通道")
                except Exception:
                    self._sofia = None
                return
            except ImagingError:
                raise
            except Exception as e:
                last_err = e
                continue

        if last_err is not None:
            raise ImagingError(
                f"ONVIF 连接失败（{self.ip}）：{last_err}。"
                "请确认摄像头已开启 ONVIF 服务且账号密码正确"
            )
        raise ImagingError(
            f"无法连接摄像头 {self.ip} 的 ONVIF 服务"
            f"（已尝试端口 {ONVIF_PORTS}），请确认设备在线"
        )

    def _ensure_connected(self):
        with self._lock:
            if self._imaging is None or self._vs_token is None:
                self._connect_unlocked()

    def _call(self, func, *args, **kwargs):
        """调用 ONVIF 接口，连接类错误时重连重试一次"""
        self._ensure_connected()
        try:
            return func(*args, **kwargs)
        except ImagingError:
            raise
        except Exception as first:
            # 连接可能已失效（摄像头重启/网络抖动），重建连接重试一次
            try:
                with self._lock:
                    self._imaging = None
                    self._cam = None
                    self._vs_token = None
                    self._connect_unlocked()
                return func(*args, **kwargs)
            except ImagingError:
                raise
            except Exception:
                raise ImagingError(f"ONVIF 请求失败（{self.ip}）：{first}")

    # ---------- 参数读取（文档 §7.1 / §7.2） ----------

    def get_settings(self) -> Dict:
        """GetImagingSettings → 归一化扁平 dict（按相机实际返回字段取子集）"""
        def _get():
            return self._imaging.GetImagingSettings({'VideoSourceToken': self._vs_token})

        raw = self._call(_get)
        out = self._normalize_settings(raw)

        # 雄迈相机：ONVIF 的曝光/增益是装饰性的，用 Sofia 读取真实值覆盖
        if self._sofia is not None:
            try:
                exp = self._sofia.get_exposure()
                out['exposure_mode'] = exp['exposure_mode']
                if exp['exposure_mode'] == 'MANUAL':
                    out['exposure_time_us'] = exp['exposure_time_us']
                if exp.get('gain') is not None:
                    out['gain'] = exp['gain']
                out['gain_auto'] = exp.get('gain_auto')
            except Exception as e:
                print(f"[Imaging {self.ip}] Sofia 读取曝光失败，回退 ONVIF 显示值: {e}")
        return out

    @staticmethod
    def _normalize_settings(s) -> Dict:
        out: Dict = {}
        exposure = getattr(s, 'Exposure', None)
        if exposure is not None:
            out['exposure_mode'] = getattr(exposure, 'Mode', None)
            out['exposure_time_us'] = getattr(exposure, 'ExposureTime', None)
            out['gain'] = getattr(exposure, 'Gain', None)
            # AUTO 模式下的曝光时间上下限（自动曝光的调节边界）
            out['min_exposure_time_us'] = getattr(exposure, 'MinExposureTime', None)
            out['max_exposure_time_us'] = getattr(exposure, 'MaxExposureTime', None)
        wb = getattr(s, 'WhiteBalance', None)
        if wb is not None:
            out['wb_mode'] = getattr(wb, 'Mode', None)
            # 雄迈返回 YrGain/YbGain，标准 ONVIF 是 CrGain/CbGain
            out['wb_r_gain'] = getattr(wb, 'CrGain', None) or getattr(wb, 'YrGain', None)
            out['wb_b_gain'] = getattr(wb, 'CbGain', None) or getattr(wb, 'YbGain', None)
        wdr = getattr(s, 'WideDynamicRange', None)
        if wdr is not None:
            out['wdr_mode'] = getattr(wdr, 'Mode', None)
            out['wdr_level'] = getattr(wdr, 'Level', None)
        blc = getattr(s, 'BacklightCompensation', None)
        if blc is not None:
            out['blc_mode'] = getattr(blc, 'Mode', None)
            out['blc_level'] = getattr(blc, 'Level', None)
        for src_key, dst_key in (('Brightness', 'brightness'),
                                 ('Contrast', 'contrast'),
                                 ('ColorSaturation', 'saturation'),
                                 ('Sharpness', 'sharpness')):
            val = getattr(s, src_key, None)
            if val is not None:
                out[dst_key] = val
        ir_cut = getattr(s, 'IrCutFilter', None)
        if ir_cut is not None:
            out['ir_cut'] = ir_cut
        return out

    def get_options(self) -> Dict:
        """GetOptions → 各参数 min/max 与枚举值（文档 §7.2：界面滑块必须按此生成）"""
        def _get():
            return self._imaging.GetOptions({'VideoSourceToken': self._vs_token})

        raw = self._call(_get)
        out = self._normalize_options(raw)

        # 雄迈相机：曝光滑块范围用 Sofia 的真实窗口（ONVIF 上报的是装饰值）
        if self._sofia is not None:
            from .sofia_control import AUTO_LEAST_TIME_US, AUTO_MOST_TIME_US
            out['exposure_time_us'] = {'min': AUTO_LEAST_TIME_US, 'max': AUTO_MOST_TIME_US}
        return out

    @staticmethod
    def _range(node) -> Optional[Dict]:
        if node is None:
            return None
        lo = getattr(node, 'Min', None)
        hi = getattr(node, 'Max', None)
        if lo is None or hi is None:
            return None
        return {'min': lo, 'max': hi}

    @classmethod
    def _normalize_options(cls, o) -> Dict:
        out: Dict = {}
        exposure = getattr(o, 'Exposure', None)
        if exposure is not None:
            modes = getattr(exposure, 'Mode', None)
            if modes:
                out['exposure_mode'] = list(modes)
            # 手动曝光时间的滑块范围使用相机上报的上下限
            # （MinExposureTime/MaxExposureTime 的可设范围），而非 ExposureTime
            # 自带的窄范围（后者往往只是当前自动曝光上限的镜像，如 0~40000us）
            min_exp = cls._range(getattr(exposure, 'MinExposureTime', None))
            max_exp = cls._range(getattr(exposure, 'MaxExposureTime', None))
            if min_exp or max_exp:
                out['exposure_time_us'] = {
                    'min': (min_exp or {}).get('min', 0.0),
                    'max': (max_exp or {}).get('max', 40000.0),
                }
            else:
                r = cls._range(getattr(exposure, 'ExposureTime', None))
                if r:
                    out['exposure_time_us'] = r
            r = cls._range(getattr(exposure, 'Gain', None))
            if r:
                out['gain'] = r
        wb = getattr(o, 'WhiteBalance', None)
        if wb is not None:
            modes = getattr(wb, 'Mode', None)
            if modes:
                out['wb_mode'] = list(modes)
            r = cls._range(getattr(wb, 'YrGain', None))
            if r:
                out['wb_r_gain'] = r
            r = cls._range(getattr(wb, 'YbGain', None))
            if r:
                out['wb_b_gain'] = r
        wdr = getattr(o, 'WideDynamicRange', None)
        if wdr is not None:
            modes = getattr(wdr, 'Mode', None)
            if modes:
                out['wdr_mode'] = list(modes)
            r = cls._range(getattr(wdr, 'Level', None))
            if r:
                out['wdr_level'] = r
        blc = getattr(o, 'BacklightCompensation', None)
        if blc is not None:
            modes = getattr(blc, 'Mode', None)
            if modes:
                out['blc_mode'] = list(modes)
            r = cls._range(getattr(blc, 'Level', None))
            if r:
                out['blc_level'] = r
        for src_key, dst_key in (('Brightness', 'brightness'),
                                 ('Contrast', 'contrast'),
                                 ('ColorSaturation', 'saturation'),
                                 ('Sharpness', 'sharpness')):
            r = cls._range(getattr(o, src_key, None))
            if r:
                out[dst_key] = r
        ir_modes = getattr(o, 'IrCutFilterModes', None)
        if ir_modes:
            out['ir_cut'] = list(ir_modes)
        return out

    # ---------- 参数写入（文档 §7.3） ----------

    def set_settings(self, changes: Dict) -> tuple:
        """合并当前值后 SetImagingSettings，并回读逐字段校验。

        changes 的键为归一化字段名，None 值会被忽略。

        返回 (最新归一化参数, rejected)。rejected 是未生效字段列表：
        [{'field', 'label', 'requested', 'actual'}]——相机可能接受 Set 请求
        但实际忽略/钳制某些值（软拒绝），只有回读对比才能发现。
        """
        current = self.get_settings()
        merged = dict(current)
        for key, val in changes.items():
            if val is not None:
                merged[key] = val

        # 雄迈相机：曝光/增益走 Sofia 私有协议（ONVIF 上是假设置）
        if self._sofia is not None:
            touched = {k for k, v in changes.items()
                       if v is not None and k in ('exposure_mode', 'exposure_time_us', 'gain')}
            if touched:
                if 'exposure_mode' in touched:
                    if merged.get('exposure_mode') == 'MANUAL':
                        self._sofia.set_exposure(
                            'MANUAL', merged.get('exposure_time_us'), merged.get('gain'))
                    else:
                        self._sofia.set_exposure('AUTO')
                else:
                    self._sofia.set_exposure(
                        None, changes.get('exposure_time_us'), changes.get('gain'))

        payload: Dict = {}
        # 只发送该相机在 GetImagingSettings 中实际出现的字段，
        # 避免不支持的元素被固件拒绝
        if 'brightness' in current:
            payload['Brightness'] = float(merged['brightness'])
        if 'contrast' in current:
            payload['Contrast'] = float(merged['contrast'])
        if 'saturation' in current:
            payload['ColorSaturation'] = float(merged['saturation'])
        if 'sharpness' in current:
            payload['Sharpness'] = float(merged['sharpness'])
        # Sofia 相机曝光走私有通道，ONVIF 侧不再发送 Exposure
        # （避免 Sofia 接受但 ONVIF 认为超范围而整体拒绝）
        if 'exposure_mode' in current and self._sofia is None:
            exp: Dict = {'Mode': merged['exposure_mode']}
            if merged.get('exposure_time_us') is not None:
                exp['ExposureTime'] = float(merged['exposure_time_us'])
            if merged.get('gain') is not None:
                exp['Gain'] = float(merged['gain'])
            if merged.get('min_exposure_time_us') is not None:
                exp['MinExposureTime'] = float(merged['min_exposure_time_us'])
            if merged.get('max_exposure_time_us') is not None:
                exp['MaxExposureTime'] = float(merged['max_exposure_time_us'])
            payload['Exposure'] = exp
        if 'wb_mode' in current:
            wb: Dict = {'Mode': merged['wb_mode']}
            if merged.get('wb_r_gain') is not None:
                wb['CrGain'] = float(merged['wb_r_gain'])
            if merged.get('wb_b_gain') is not None:
                wb['CbGain'] = float(merged['wb_b_gain'])
            payload['WhiteBalance'] = wb
        if 'wdr_mode' in current:
            wdr: Dict = {'Mode': merged['wdr_mode']}
            if merged.get('wdr_level') is not None:
                wdr['Level'] = float(merged['wdr_level'])
            payload['WideDynamicRange'] = wdr
        if 'blc_mode' in current:
            blc: Dict = {'Mode': merged['blc_mode']}
            if merged.get('blc_level') is not None:
                blc['Level'] = float(merged['blc_level'])
            payload['BacklightCompensation'] = blc
        if 'ir_cut' in current:
            payload['IrCutFilter'] = merged['ir_cut']

        def _set():
            return self._imaging.SetImagingSettings({
                'VideoSourceToken': self._vs_token,
                'ImagingSettings': payload,
                'ForcePersistence': True,
            })

        try:
            if payload:
                self._call(_set)
        except ImagingError as e:
            # 硬拒绝：相机直接返回 SOAP Fault，翻译成可读说明
            raise ImagingError(describe_rejection(str(e))) from e

        new_settings = self.get_settings()

        # 软拒绝检测：请求值与回读值不一致的字段
        rejected = []
        for key, wanted in changes.items():
            if wanted is None:
                continue
            actual = new_settings.get(key)
            if actual is None:
                # 相机未暴露该字段，视为不支持
                rejected.append({
                    'field': key,
                    'label': FIELD_LABELS.get(key, key),
                    'requested': wanted,
                    'actual': None,
                })
                continue
            if isinstance(wanted, (int, float)) and isinstance(actual, (int, float)):
                if abs(float(actual) - float(wanted)) < 1e-6:
                    continue
            elif str(actual) == str(wanted):
                continue
            rejected.append({
                'field': key,
                'label': FIELD_LABELS.get(key, key),
                'requested': wanted,
                'actual': actual,
            })
        return new_settings, rejected


# ---------- 客户端缓存（按摄像头 IP 复用连接，避免每次重新握手） ----------

_clients: Dict[str, ImagingClient] = {}
_clients_lock = threading.Lock()


def get_imaging_client(ip: str, username: str = "", password: str = "",
                       stream_url: str = "") -> ImagingClient:
    """获取（或创建）某台摄像头的 ImagingClient。

    凭据优先用显式传入的 username/password，缺失时从 stream_url 解析。
    凭据变化时重建客户端。
    """
    if not username and stream_url:
        username, password = credentials_from_stream_url(stream_url)

    key = ip
    with _clients_lock:
        client = _clients.get(key)
        if client is None or client.username != username or client.password != password:
            client = ImagingClient(ip, username, password)
            _clients[key] = client
    return client
