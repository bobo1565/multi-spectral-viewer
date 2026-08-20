#!/usr/bin/env python3
"""
雄迈（XiongMai）Sofia / DVRIP 私有协议客户端（TCP 34567）

背景（方案文档 §18）：这批相机的 ONVIF Imaging Service 对曝光/增益是
"假设置"——Set 被接受、回读也生效，但传感器实际不变（自动曝光仍在运行）。
而亮度/对比度等 ISP 后处理参数经 ONVIF 是真实生效的。

Sofia 协议则可以直接控制曝光窗口与增益：
- 读取配置：type 1042, {"Name": "Camera"} → Camera.Param[0].ExposureParam 等
- 写入配置：type 1040, {"Name": "Camera.Param.[0]", "Camera.Param.[0": {...}}

曝光语义（实测）：
- ExposureParam.LeastTime / MostTime（微秒，十六进制字符串）是自动曝光的调节窗口；
  两者压成同一个值即为手动固定曝光
- GainParam.AutoGain / Gain 控制自动增益与固定增益（ParamEx.BroadTrends 同步设置）
"""
from __future__ import annotations

import hashlib
import json
import socket
import struct
import threading
from typing import Dict, Optional


class SofiaError(Exception):
    """Sofia 协议相关错误（消息面向用户，使用中文）"""


_HDR = struct.Struct('<BBxxIIBBHI')
_DEC = json.JSONDecoder()

# 自动曝光的默认窗口（微秒）：相机出厂值
AUTO_LEAST_TIME_US = 10
AUTO_MOST_TIME_US = 65536  # 0x10000，约等于 15fps 的帧周期

# 登录/配置的报文类型
_MSG_LOGIN = 1000
_MSG_CONFIG_SET = 1040
_MSG_CONFIG_GET = 1042


def _sofia_hash(password: str) -> str:
    """雄迈 XMMD5 口令散列：MD5 后按字节对求和 mod 62 映射字符，取 8 位"""
    md5 = hashlib.md5(password.encode('utf-8')).digest()
    magic = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    return ''.join(magic[(a + b) % 62] for a, b in zip(md5[0::2], md5[1::2]))[:8]


def _hex_us(value_us: float) -> str:
    """微秒 → 相机使用的十六进制字符串（如 '0x00009C40'）"""
    return f"0x{int(round(value_us)):08X}"


def _us_from_hex(text) -> Optional[float]:
    try:
        return float(int(str(text), 16))
    except (TypeError, ValueError):
        return None


class SofiaClient:
    """单台雄迈相机的 Sofia 协议客户端（短连接：每次操作重新登录，避免会话保活问题）"""

    PORT = 34567

    def __init__(self, ip: str, username: str = "", password: str = "", timeout: float = 5.0):
        self.ip = ip
        self.username = username or ""
        self.password = password or ""
        self.timeout = timeout

    # ---------- 协议 ----------

    def _transact(self, requests):
        """建立连接、登录，依次执行 [(msg_type, payload)]，返回最后一个响应"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        seq = 0
        try:
            sock.connect((self.ip, self.PORT))
            payload = json.dumps({
                "EncryptType": "MD5",
                "LoginType": "DVRIP-Web",
                "UserName": self.username,
                "PassWord": _sofia_hash(self.password),
                "SessionID": "0x00000000",
            }).encode() + b'\n\x00'
            seq += 2
            sock.sendall(_HDR.pack(0xFF, 0x01, 0, seq, 0, 0, _MSG_LOGIN, len(payload)) + payload)
            reply = self._recv(sock)
            if reply.get('Ret') != 100:
                raise SofiaError(
                    f"相机 {self.ip} Sofia 登录失败（Ret={reply.get('Ret')}），"
                    "请检查账号密码"
                )
            session = int(reply['SessionID'], 16)

            result = reply
            for msg_type, obj in requests:
                obj['SessionID'] = f'0x{session:08X}'
                payload = json.dumps(obj).encode() + b'\n\x00'
                seq += 2
                sock.sendall(_HDR.pack(0xFF, 0x01, session, seq, 0, 0, msg_type, len(payload)) + payload)
                result = self._recv(sock)
            return result
        except SofiaError:
            raise
        except (OSError, ValueError, json.JSONDecodeError) as e:
            raise SofiaError(f"相机 {self.ip} Sofia 通信失败: {e}")
        finally:
            try:
                sock.close()
            except OSError:
                pass

    @staticmethod
    def _recv(sock) -> Dict:
        buf = b''
        while len(buf) < _HDR.size:
            chunk = sock.recv(_HDR.size - len(buf))
            if not chunk:
                raise SofiaError("连接被相机关闭")
            buf += chunk
        _, _, _, _, _, _, _, length = _HDR.unpack(buf)
        data = b''
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                break
            data += chunk
        text = data.decode('utf-8', 'replace').strip('\x00\n\r ')
        parsed, _ = _DEC.raw_decode(text)
        return parsed

    # ---------- 配置读写 ----------

    def get_camera_config(self) -> Dict:
        reply = self._transact([(_MSG_CONFIG_GET, {"Name": "Camera"})])
        if reply.get('Ret') != 100 or 'Camera' not in reply:
            raise SofiaError(f"读取相机参数失败（Ret={reply.get('Ret')}）")
        return reply['Camera']

    def _set_param(self, sub_key: str, data: Dict):
        name = "Camera.Param.[0]"
        reply = self._transact([(_MSG_CONFIG_SET, {"Name": name, name: {sub_key: data}})])
        if reply.get('Ret') != 100:
            raise SofiaError(f"设置相机参数被拒绝（Ret={reply.get('Ret')}）")

    def _set_param_ex(self, sub_key: str, data: Dict):
        name = "Camera.ParamEx.[0]"
        reply = self._transact([(_MSG_CONFIG_SET, {"Name": name, name: {sub_key: data}})])
        if reply.get('Ret') != 100:
            raise SofiaError(f"设置相机扩展参数被拒绝（Ret={reply.get('Ret')}）")

    # ---------- 归一化曝光/增益 ----------

    def get_exposure(self) -> Dict:
        """返回 {exposure_mode, exposure_time_us, gain, gain_auto,
                 exposure_range: {min, max}}"""
        config = self.get_camera_config()
        params = (config.get('Param') or [{}])[0]
        exposure = params.get('ExposureParam') or {}
        gain = params.get('GainParam') or {}

        least = _us_from_hex(exposure.get('LeastTime'))
        most = _us_from_hex(exposure.get('MostTime'))
        gain_auto = bool(gain.get('AutoGain', 1))

        manual = least is not None and most is not None and least == most
        return {
            'exposure_mode': 'MANUAL' if manual else 'AUTO',
            # 手动时为锁定值；自动时取当前窗口上限供参考
            'exposure_time_us': least if manual else most,
            'gain': gain.get('Gain'),
            'gain_auto': gain_auto,
            'exposure_range': {
                'min': AUTO_LEAST_TIME_US,
                'max': AUTO_MOST_TIME_US,
            },
        }

    def set_exposure(self, mode: Optional[str] = None,
                     exposure_time_us: Optional[float] = None,
                     gain: Optional[float] = None):
        """设置曝光模式/时间/增益。

        - MANUAL：把 AE 窗口压到指定曝光时间；给了 gain 则同时固定增益
        - AUTO：恢复默认 AE 窗口，并恢复自动增益
        """
        if mode == 'MANUAL':
            if exposure_time_us is None:
                raise SofiaError("手动曝光需要同时给出曝光时间")
            t = _hex_us(exposure_time_us)
            self._set_param('ExposureParam', {
                'LeastTime': t, 'MostTime': t, 'Level': 0,
            })
            if gain is not None:
                self._set_param('GainParam', {'AutoGain': 0, 'Gain': int(gain)})
                self._set_param_ex('BroadTrends', {'AutoGain': 0, 'Gain': int(gain)})
        elif mode == 'AUTO':
            self._set_param('ExposureParam', {
                'LeastTime': _hex_us(AUTO_LEAST_TIME_US),
                'MostTime': _hex_us(AUTO_MOST_TIME_US),
                'Level': 0,
            })
            self._set_param('GainParam', {'AutoGain': 1, 'Gain': 0})
            self._set_param_ex('BroadTrends', {'AutoGain': 1, 'Gain': 50})
        else:
            # 未切换模式时的单点调整
            if exposure_time_us is not None:
                t = _hex_us(exposure_time_us)
                self._set_param('ExposureParam', {
                    'LeastTime': t, 'MostTime': t, 'Level': 0,
                })
            if gain is not None:
                self._set_param('GainParam', {'AutoGain': 0, 'Gain': int(gain)})
                self._set_param_ex('BroadTrends', {'AutoGain': 0, 'Gain': int(gain)})


# ---------- 客户端缓存 ----------

_sofia_clients: Dict[str, SofiaClient] = {}
_sofia_lock = threading.Lock()


def probe_sofia_client(ip: str, username: str = "", password: str = "",
                       stream_url: str = "") -> Optional[SofiaClient]:
    """探测相机是否支持雄迈 Sofia 协议；支持则返回缓存的客户端，否则返回 None。

    相机的 Sofia/DVRIP 口令可能与 ONVIF 口令不一致（实测存在 ONVIF 用
    admin/admin 而 DVRIP 用 admin/空 的设备），因此依次尝试多个候选凭据。
    结果（含否定结果）按 IP 缓存，避免重复探测拖慢流程。
    """
    from .onvif_imaging import credentials_from_stream_url

    if not username and stream_url:
        username, password = credentials_from_stream_url(stream_url)

    key = ip
    with _sofia_lock:
        if key in _sofia_clients:
            cached = _sofia_clients[key]
            if cached is None:
                return None
            return cached if cached.username == username else None

    # 候选凭据：DB 记录口令 → 空口令（雄迈常见默认）
    candidates = []
    for pwd in (password, ""):
        if (username, pwd) not in candidates:
            candidates.append((username, pwd))

    client = None
    for user, pwd in candidates:
        probe = SofiaClient(ip, user, pwd, timeout=3.0)
        try:
            probe.get_camera_config()
            client = probe
            break
        except Exception:
            continue

    with _sofia_lock:
        _sofia_clients[key] = client  # type: ignore[assignment]
    return client


def clear_sofia_cache():
    with _sofia_lock:
        _sofia_clients.clear()
