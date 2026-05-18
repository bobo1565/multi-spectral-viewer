#!/usr/bin/env python3
"""
IP Camera Discovery Module
从 ip_camera_viewer 迁入：ONVIF 多播发现 + RTSP 探测
"""

import socket
import subprocess
import platform
import threading
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
from urllib.parse import urlparse
import time


class CameraDiscovery:
    """摄像头发现类"""

    # 常见摄像头的RTSP路径 - 按优先级排序
    COMMON_RTSP_PATHS = [
        "/Streaming/Channels/101",
        "/Streaming/Channels/102",
        "/ch1/main/av_stream",
        "/ch1/sub/av_stream",
        "/cam/realmonitor?channel=1&subtype=0",
        "/cam/realmonitor?channel=1&subtype=1",
        "/live/ch00_0",
        "/live/ch01_0",
        "/live/stream1",
        "/live/stream2",
        "/stream1",
        "/stream2",
        "/ch0_0.h264",
        "/ch0_1.h264",
        "/videoMain",
        "/videoSub",
        "/11",
        "/12",
        "/1",
        "/onvif1",
        "/onvif2",
        "/profile1",
        "/profile2",
        "/media/video1",
        "/media/video2",
        "/av0_0",
        "/av0_1",
        "/live.sdp",
        "/mpeg4",
        "/h264",
    ]

    PRIVATE_NETWORKS = [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
    ]

    def __init__(self, config: Dict):
        self.config = config
        self.discovered_cameras: List[Dict] = []
        self.lock = threading.Lock()
        self.verbose = True

    def log(self, msg: str):
        if self.verbose:
            print(f"[Discovery] {msg}")

    def get_local_networks(self) -> List[str]:
        """获取本地网络IP段，过滤VPN/虚拟网卡"""
        networks = []
        vpn_networks = []

        try:
            import netifaces
            for interface in netifaces.interfaces():
                if self._is_virtual_interface(interface):
                    continue

                addrs = netifaces.ifaddresses(interface)
                if netifaces.AF_INET in addrs:
                    for addr_info in addrs[netifaces.AF_INET]:
                        ip = addr_info.get('addr')
                        netmask = addr_info.get('netmask')
                        if ip and netmask and not ip.startswith('127.'):
                            try:
                                network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)

                                if self._is_vpn_network(network):
                                    vpn_networks.append(str(network))
                                else:
                                    networks.append(str(network))
                                    self.log(f"发现本地网段: {interface} -> {network}")
                            except Exception:
                                pass
        except ImportError:
            pass

        if not networks:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(('8.8.8.8', 80))
                local_ip = s.getsockname()[0]
                networks.append(f"{local_ip.rsplit('.', 1)[0]}.0/24")
                self.log(f"使用备用方案发现网段: {networks[0]}")
            except Exception:
                networks = ["192.168.1.0/24", "192.168.0.0/24", "10.0.0.0/24"]
            finally:
                s.close()

        if vpn_networks:
            self.log(f"跳过VPN网段: {vpn_networks}")

        if self.config.get('discovery', {}).get('ip_ranges'):
            networks = self.config['discovery']['ip_ranges']
            self.log(f"使用配置网段: {networks}")

        return networks if networks else ["192.168.1.0/24"]

    def _is_virtual_interface(self, iface: str) -> bool:
        virtual_prefixes = ('utun', 'tun', 'tap', 'veth', 'docker', 'br-', 'vmnet',
                            'ppp', 'gif', 'stf', 'awdl', 'llw', 'bridge')
        return iface.startswith(virtual_prefixes)

    def _is_vpn_network(self, network: ipaddress.IPv4Network) -> bool:
        vpn_ranges = [
            ipaddress.ip_network("198.18.0.0/15"),
            ipaddress.ip_network("100.64.0.0/10"),
        ]
        for vpn_range in vpn_ranges:
            if network.subnet_of(vpn_range) or network.supernet_of(vpn_range):
                return True
        if network.prefixlen >= 30:
            return True
        return False

    def ping_host(self, ip: str, timeout: int = 1) -> bool:
        try:
            system = platform.system().lower()
            if system == "windows":
                cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), ip]
            else:
                cmd = ["ping", "-c", "1", "-W", str(timeout), ip]
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=timeout + 1)
            return result.returncode == 0
        except Exception:
            return False

    def check_port_open(self, ip: str, port: int, timeout: float = 1.0) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def try_rtsp_url(self, ip: str, port: int, path: str,
                     username: str = "", password: str = "",
                     timeout: int = 3) -> Optional[str]:
        """尝试连接RTSP URL - 使用线程防止卡死"""
        import cv2

        result = [None]

        if username and password:
            url = f"rtsp://{username}:{password}@{ip}:{port}{path}"
        else:
            url = f"rtsp://{ip}:{port}{path}"

        def try_connect():
            try:
                cap = cv2.VideoCapture(url)
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout * 1000)
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, timeout * 1000)

                if cap.isOpened():
                    ret, frame = cap.read()
                    cap.release()
                    if ret and frame is not None and frame.size > 0:
                        result[0] = url
                else:
                    cap.release()
            except Exception:
                pass

        thread = threading.Thread(target=try_connect)
        thread.daemon = True
        thread.start()
        thread.join(timeout + 1)

        return result[0]

    def onvif_discovery(self, timeout: int = 2) -> List[Dict]:
        """ONVIF WS-Discovery 多播发现"""
        cameras = []

        multicast_addr = "239.255.255.250"
        multicast_port = 3702

        probe_msg = '''<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:%s</w:MessageID>
    <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </e:Body>
</e:Envelope>''' % self._gen_uuid()

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.settimeout(timeout)

            sock.bind(("0.0.0.0", 0))

            self.log(f"发送ONVIF多播探测到 {multicast_addr}:{multicast_port}")
            sock.sendto(probe_msg.encode('utf-8'), (multicast_addr, multicast_port))

            start_time = time.time()
            seen_ips = set()
            while time.time() - start_time < timeout:
                try:
                    data, addr = sock.recvfrom(4096)
                    ip = addr[0]
                    if ip in seen_ips:
                        continue
                    seen_ips.add(ip)
                    self.log(f"收到ONVIF响应来自: {ip}")

                    camera_info = {
                        'ip': ip,
                        'type': 'ONVIF',
                        'source': 'multicast_discovery',
                        'name': f"ONVIF_Camera_{ip.split('.')[-1]}"
                    }
                    cameras.append(camera_info)
                except socket.timeout:
                    break
                except Exception:
                    pass

            sock.close()
        except Exception as e:
            self.log(f"ONVIF多播发现错误: {e}")

        return cameras

    def _gen_uuid(self) -> str:
        import uuid
        return str(uuid.uuid4())

    def probe_rtsp_stream(self, ip: str, port: int = 554) -> Dict:
        """尝试查找 RTSP 流，并返回详细诊断信息"""
        if not self.check_port_open(ip, port, 1.0):
            return {
                'success': False,
                'reason': f'端口 {port} 未开放',
                'port': port,
            }

        self.log(f"  {ip}:{port} 端口开放，尝试RTSP路径...")

        for path in self.COMMON_RTSP_PATHS[:5]:
            url = self.try_rtsp_url(ip, port, path, "", "", 2)
            if url:
                self.log(f"  ✓ 发现RTSP流: {path}")
                return {
                    'success': True,
                    'info': {
                        'ip': ip,
                        'port': port,
                        'rtsp_url': url,
                        'path': path,
                        'auth_required': False,
                    },
                    'reason': f'匿名访问成功，路径 {path}',
                    'port': port,
                }

        credential_count = 0
        for cred in self.config.get('discovery', {}).get('common_credentials', []):
            for path in self.COMMON_RTSP_PATHS:
                credential_count += 1
                url = self.try_rtsp_url(ip, port, path, cred['username'], cred['password'], 2)
                if url:
                    self.log(f"  ✓ 发现RTSP流(需认证): {path}")
                    return {
                        'success': True,
                        'info': {
                            'ip': ip,
                            'rtsp_url': url,
                            'username': cred['username'],
                            'password': cred['password'],
                            'auth_required': True,
                            'path': path,
                            'port': port,
                        },
                        'reason': f"认证成功，账号 {cred['username']}，路径 {path}",
                        'port': port,
                    }

        return {
            'success': False,
            'reason': (
                f'端口 {port} 可连接，但 RTSP 路径无效或认证失败；'
                f'已尝试 5 个匿名路径和 {credential_count} 个带认证组合'
            ),
            'port': port,
        }

    def find_rtsp_stream(self, ip: str, port: int = 554) -> Optional[Dict]:
        """尝试查找RTSP流"""
        result = self.probe_rtsp_stream(ip, port)
        return result.get('info') if result.get('success') else None

    def scan_ip(self, ip: str) -> Optional[Dict]:
        if not self.ping_host(ip, timeout=1):
            return None

        self.log(f"扫描存活主机: {ip}")

        camera_info = {
            'ip': ip,
            'found_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'services': {}
        }

        for rtsp_port in self.config.get('discovery', {}).get('rtsp_ports', [554, 8554]):
            rtsp_info = self.find_rtsp_stream(ip, rtsp_port)
            if rtsp_info:
                camera_info['rtsp'] = rtsp_info
                camera_info['type'] = 'RTSP'
                camera_info['stream_url'] = rtsp_info['rtsp_url']
                break

        if 'rtsp' not in camera_info:
            return None

        camera_info['name'] = f"Camera_{ip.split('.')[-1]}"
        return camera_info

    def add_camera_manually(self, name: str, rtsp_url: str,
                            username: str = "", password: str = "") -> bool:
        """手动添加摄像头并验证流可用"""
        try:
            parsed = urlparse(rtsp_url)
            ip = parsed.hostname

            camera_info = {
                'name': name,
                'ip': ip,
                'stream_url': rtsp_url,
                'username': username,
                'password': password,
                'manual': True,
                'found_time': time.strftime('%Y-%m-%d %H:%M:%S')
            }

            import cv2
            cap = cv2.VideoCapture(rtsp_url)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)

            if cap.isOpened():
                ret, _ = cap.read()
                cap.release()
                if ret:
                    with self.lock:
                        for i, cam in enumerate(self.discovered_cameras):
                            if cam.get('ip') == ip:
                                self.discovered_cameras[i] = camera_info
                                return True
                        self.discovered_cameras.append(camera_info)
                    return True
            else:
                cap.release()
        except Exception as e:
            self.log(f"手动添加摄像头失败: {e}")

        return False
