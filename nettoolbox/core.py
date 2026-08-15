#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nettoolbox.core - 网络重置与诊断核心逻辑
纯逻辑层,不依赖 tkinter,可独立测试与复用。
"""

import ctypes
import re
import subprocess


# ===== DNS 预设配置(按钮颜色由 UI 层映射) =====
DNS_PRESETS = {
    "自动获取(DHCP)": {"mode": "dhcp", "primary": "", "secondary": ""},
    "阿里 DNS":    {"mode": "static", "primary": "223.5.5.5",      "secondary": "223.6.6.6"},
    "Google DNS": {"mode": "static", "primary": "8.8.8.8",         "secondary": "8.8.4.4"},
    "Cloudflare": {"mode": "static", "primary": "1.1.1.1",         "secondary": "1.0.0.1"},
    "114 DNS":    {"mode": "static", "primary": "114.114.114.114", "secondary": "114.114.115.115"},
}


# 主机名/IP 合法字符校验(防止拼入 shell/PowerShell 命令导致注入)
_HOSTNAME_RE = re.compile(
    r'^(?=.{1,253}$)'
    r'[0-9A-Za-z](?:[0-9A-Za-z-]{0,61}[0-9A-Za-z])?'
    r'(?:\.[0-9A-Za-z](?:[0-9A-Za-z-]{0,61}[0-9A-Za-z])?)*$'
)
_IPV6_RE = re.compile(r'^[0-9A-Fa-f:.%]{2,45}$')

IPV4_RE = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')


def validate_host(target):
    """校验 ping/traceroute 目标:仅允许合法主机名/IPv4/IPv6,拒绝命令注入"""
    if not target:
        return False
    if ':' in target:  # IPv6 字面量(可含 %zone)
        return _IPV6_RE.match(target) is not None and target.count('::') <= 1
    return _HOSTNAME_RE.match(target) is not None


def validate_ipv4(addr):
    """校验 IPv4 地址格式与数值范围"""
    if not IPV4_RE.match(addr or ''):
        return False
    return all(0 <= int(p) <= 255 for p in addr.split('.'))


def decode_output(raw_bytes):
    """解码 subprocess 输出字节流:中文 Windows 先 GBK,回退 UTF-8"""
    if not raw_bytes:
        return ""
    try:
        return raw_bytes.decode('gbk')
    except (UnicodeDecodeError, LookupError):
        return raw_bytes.decode('utf-8', errors='replace')


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def get_active_adapter():
    """获取活动网卡名称(Get-NetAdapter 优先,WMI 兜底)"""
    scripts = (
        # 方法1: Get-NetAdapter (Windows 8/Server 2012+)
        '''
$adapter = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | Select-Object -First 1
if ($adapter) { Write-Output $adapter.NetConnectionID }
''',
        # 方法2: WMI (兼容性更好)
        '''
$adapter = Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.NetConnectionStatus -eq 2 } | Select-Object -First 1
if ($adapter) { Write-Output $adapter.NetConnectionID }
''',
    )
    for ps in scripts:
        try:
            result = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                                    capture_output=True, timeout=5)
            name = decode_output(result.stdout).strip()
            if name:
                return name
        except Exception:
            continue
    return None


# ============================================================
#  网络重置核心类
# ============================================================

class NetworkResetTool:
    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.static_configs = []

    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    def run_cmd(self, cmd, show_output=False, timeout=10):
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout)
            if show_output and result.stdout:
                self.log(decode_output(result.stdout).strip())
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            self.log(f"  ⚠ 命令执行超时 ({timeout}秒)")
            return False
        except Exception as e:
            self.log(f"  错误: {e}")
            return False

    def backup_static_ip(self):
        self.log("[备份] 静态IP配置...")
        ps_script = '''
$adapters = Get-WmiObject Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -and $_.DHCPEnabled -eq $false }
if ($adapters) {
    foreach ($a in $adapters) {
        $id = $a.SettingID
        $name = (Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.GUID -eq $id }).NetConnectionID
        $ip = $a.IPAddress -join ','
        $mask = $a.IPSubnet -join ','
        $gw = $a.DefaultIPGateway -join ','
        $dns = $a.DNSServerSearchOrder -join ','
        Write-Output "$name|$ip|$mask|$gw|$dns"
    }
}
'''
        try:
            result = subprocess.run(['powershell', '-NoProfile', '-Command', ps_script],
                                    capture_output=True, timeout=10)
            stdout = decode_output(result.stdout)
            if stdout.strip():
                for line in stdout.strip().split('\n'):
                    if line.strip():
                        parts = line.strip().split('|')
                        if len(parts) >= 5:
                            self.static_configs.append({
                                'name': parts[0],
                                'ip': parts[1],
                                'mask': parts[2],
                                'gateway': parts[3],
                                'dns': parts[4]
                            })
                            self.log(f"  ✓ 备份: {parts[0]} - {parts[1]}")
            if not self.static_configs:
                self.log("  ✓ 无静态IP配置")
        except Exception as e:
            self.log(f"  备份失败: {e}")

    def reset_winsock(self):
        self.log("[操作] 重置 Winsock...")
        if self.run_cmd('netsh winsock reset'):
            self.log("  ✓ Winsock 重置完成")
            return True
        self.log("  ✗ Winsock 重置失败")
        return False

    def reset_tcpip(self):
        self.log("[操作] 重置 TCP/IP 协议栈...")
        ok1 = self.run_cmd('netsh int ip reset', timeout=15)
        ok2 = self.run_cmd('netsh int ipv6 reset', timeout=15)
        if ok1 and ok2:
            self.log("  ✓ TCP/IP 重置完成")
        else:
            self.log("  ⚠ TCP/IP 重置命令已执行(部分返回非零,通常可忽略)")
        return ok1 and ok2

    def flush_dns(self):
        self.log("[操作] 清除 DNS 缓存...")
        if self.run_cmd('ipconfig /flushdns'):
            self.log("  ✓ DNS 缓存已清除")
            return True
        self.log("  ✗ DNS 缓存清除失败")
        return False

    def flush_arp(self):
        self.log("[操作] 清除 ARP 缓存...")
        if self.run_cmd('netsh interface ip delete arpcache'):
            self.log("  ✓ ARP 缓存已清除")
            return True
        self.log("  ✗ ARP 缓存清除失败")
        return False

    def renew_dhcp(self):
        self.log("[操作] 刷新 DHCP...")
        self.run_cmd('ipconfig /release', timeout=10)
        self.run_cmd('ipconfig /renew', timeout=15)
        self.log("  ✓ DHCP 已刷新")
        return True

    def restore_static_ip(self):
        if not self.static_configs:
            return
        self.log("[恢复] 静态IP配置...")
        for cfg in self.static_configs:
            name = cfg['name']
            ip = cfg['ip'].split(',')[0] if cfg['ip'] else ''
            mask = cfg['mask'].split(',')[0] if cfg['mask'] else ''
            gateway = cfg['gateway'].split(',')[0] if cfg['gateway'] else ''
            dns = cfg['dns'].split(',')[0] if cfg['dns'] else ''
            if not (ip and mask):
                self.log(f"  跳过 {name}: 缺少 IP 或掩码")
                continue
            self.log(f"  恢复: {name}")
            # 无网关时省略 gw 参数,避免 netsh 语法错误
            if gateway:
                cmd = f'netsh interface ip set address "{name}" static {ip} {mask} {gateway} 1'
            else:
                cmd = f'netsh interface ip set address "{name}" static {ip} {mask}'
            self.run_cmd(cmd)
            self.log(f"    IP: {ip}")
            if dns:
                cmd = f'netsh interface ip set dns "{name}" static {dns} primary'
                self.run_cmd(cmd)

    def _backup_proxy(self):
        """备份系统代理设置(保护 Clash 等代理软件配置)"""
        self.log("[代理] 备份系统代理设置...")
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
            try:
                self._proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            except FileNotFoundError:
                self._proxy_enable = 0
            try:
                self._proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
            except FileNotFoundError:
                self._proxy_server = ""
            winreg.CloseKey(key)
            self.log(f"  ✓ 已备份: ProxyEnable={self._proxy_enable}, ProxyServer={self._proxy_server}")
        except Exception as e:
            self.log(f"  ✗ 备份失败: {e}")
            self._proxy_enable = None
            self._proxy_server = None

    def _restore_proxy(self):
        """恢复系统代理设置"""
        if not hasattr(self, '_proxy_enable') or self._proxy_enable is None:
            self.log("[代理] 无代理配置需要恢复")
            return
        self.log("[代理] 恢复系统代理设置...")
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                                 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, self._proxy_enable)
            if self._proxy_server:
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, self._proxy_server)
            winreg.CloseKey(key)
            self.log(f"  ✓ 已恢复: ProxyEnable={self._proxy_enable}, ProxyServer={self._proxy_server}")
            # 通知系统代理设置已变更
            ctypes.windll.Wininet.InternetSetOptionW(0, 39, 0, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
            ctypes.windll.Wininet.InternetSetOptionW(0, 37, 0, 0)  # INTERNET_OPTION_REFRESH
        except Exception as e:
            self.log(f"  ✗ 恢复失败: {e}")

    def get_current_dns(self, adapter_name=None):
        """获取当前 DNS 服务器地址"""
        ps_script = '''
$adapters = Get-WmiObject Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -eq $true }
if ($adapters) {
    foreach ($a in $adapters) {
        $name = (Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.GUID -eq $a.SettingID }).NetConnectionID
        $dhcp = $a.DHCPEnabled
        $dns = $a.DNSServerSearchOrder -join ','
        if ($name -and $dns) { Write-Output "$name|$dhcp|$dns" }
    }
}
'''
        try:
            result = subprocess.run(['powershell', '-NoProfile', '-Command', ps_script],
                                    capture_output=True, timeout=10)
            stdout = decode_output(result.stdout)
            lines = [l.strip() for l in stdout.strip().split('\n') if l.strip() and '|' in l]
            if not lines:
                return [], 'unknown'
            # 取第一个有 DNS 的适配器
            parts = lines[0].split('|')
            if len(parts) >= 3:
                is_dhcp = parts[1].strip().lower() == 'true'
                dns_list = [d.strip() for d in parts[2].split(',') if d.strip()]
                return dns_list, ('dhcp' if is_dhcp else 'static')
        except Exception:
            pass
        return [], 'unknown'

    def set_dns(self, adapter_name, primary, secondary=None):
        """设置 DNS 服务器"""
        cmd_set_primary = f'netsh interface ip set dns "{adapter_name}" static {primary} primary'
        ok1 = self.run_cmd(cmd_set_primary)
        if not ok1:
            self.log(f"  ✗ 主 DNS {primary} 设置失败")
        else:
            self.log(f"  ✓ 主 DNS: {primary}")
        if secondary:
            cmd_set_secondary = f'netsh interface ip add dns "{adapter_name}" {secondary} index=2'
            ok2 = self.run_cmd(cmd_set_secondary)
            if not ok2:
                self.log(f"  ✗ 备用 DNS {secondary} 设置失败")
            else:
                self.log(f"  ✓ 备用 DNS: {secondary}")
        return ok1

    def set_dhcp_dns(self, adapter_name):
        """切换为 DHCP 自动获取 DNS"""
        cmd = f'netsh interface ip set dns "{adapter_name}" dhcp'
        if self.run_cmd(cmd):
            self.log("  ✓ DNS 已切换为自动获取 (DHCP)")
            return True
        self.log("  ✗ DNS 切换失败")
        return False

    def switch_dns(self, preset_name, adapter_name=None):
        """切换 DNS 到预设值"""
        preset = DNS_PRESETS.get(preset_name)
        if not preset:
            return
        self.log(f"[DNS] 切换到: {preset_name}")
        if preset['mode'] == 'dhcp':
            self.set_dhcp_dns(adapter_name)
        else:
            self.set_dns(adapter_name, preset['primary'], preset.get('secondary'))
        self.flush_dns()

    def run_full_reset(self):
        self.log("=" * 50)
        self.log("🔄 开始完整网络重置")
        self.log("=" * 50)
        self.log("")
        self.backup_static_ip()
        self._backup_proxy()
        self.log("")
        self.reset_winsock()
        self.log("")
        self.reset_tcpip()
        self.log("")
        self.flush_dns()
        self.flush_arp()
        self.log("")
        self.renew_dhcp()
        self.log("")
        self.restore_static_ip()
        self._restore_proxy()
        self.log("")
        self.log("=" * 50)
        self.log("🎉 网络重置完成!")
        self.log("建议重启电脑使设置生效")
        self.log("=" * 50)


# ============================================================
#  网络诊断类
# ============================================================

class NetworkDiagnostic:
    """诊断工具类"""

    PING_TARGETS = [
        ("8.8.8.8",    "Google DNS",      "blue"),
        ("1.1.1.1",    "Cloudflare DNS",  "sky"),
        ("223.5.5.5",  "阿里 DNS",         "orange"),
        ("www.baidu.com", "百度",          "red"),
        ("www.qq.com", "腾讯",             "green"),
    ]

    DNS_TARGETS = [
        ("223.5.5.5", "阿里 DNS"),
        ("8.8.8.8",   "Google DNS"),
        ("1.1.1.1",   "Cloudflare"),
    ]

    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def log(self, msg, color=None):
        if self.log_callback:
            self.log_callback(msg, color)

    def _run_ps(self, script, timeout=10):
        try:
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', script],
                capture_output=True, timeout=timeout
            )
            output = result.stdout
            # 尝试 UTF-8(现代 Windows)→ GBK(中文 Windows)→ UTF-16LE
            for enc in ('utf-8', 'gbk', 'utf-16-le'):
                try:
                    return output.decode(enc).strip()
                except (UnicodeDecodeError, UnicodeError):
                    continue
            return output.decode('utf-8', errors='replace').strip()
        except Exception:
            return ""

    def get_overview(self):
        """获取网络状态总览"""
        results = []
        ps = '''
$out = @()

# 适配器信息
$adapters = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | Select-Object Name, InterfaceDescription, MacAddress, LinkSpeed
$active = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | Select-Object -First 1
if ($active) {
    $cfg = Get-NetIPConfiguration -InterfaceIndex $active.ifIndex -ErrorAction SilentlyContinue
    $out += "状态|up"
    $out += "接口|$($active.Name)"
    $out += "描述|$($active.InterfaceDescription)"
    $out += "MAC|$($active.MacAddress)"
    $out += "速度|$($active.LinkSpeed)"
    if ($cfg.IPv4Address) { $out += "IPv4|$($cfg.IPv4Address.IPAddress)" }
    if ($cfg.IPv4DefaultGateway) { $out += "网关|$($cfg.IPv4DefaultGateway.NextHop)" }
    if ($cfg.DNSServer) { $out += "DNS|$($cfg.DNSServer.ServerAddresses -join ', ')" }
    if ($cfg.IPv4DHCP) { $out += "DHCP|$($cfg.IPv4DHCP)" }
}
Write-Output ($out -join "`n")
'''
        output = self._run_ps(ps, timeout=10)
        lines = [l for l in output.split('\n') if l.strip() and '|' in l]
        for line in lines:
            parts = line.split('|', 1)
            if len(parts) == 2:
                k, v = parts[0].strip(), parts[1].strip()
                results.append((k, v))
        return results

    def ping(self, target, count=4):
        """Ping 一个目标,返回 (ok, avg_ms, loss_pct, output)"""
        try:
            raw = subprocess.run(
                f'cmd /c ping -n {count} {target}',
                shell=True,
                capture_output=True, timeout=15
            ).stdout or b''
            output = decode_output(raw)
            # 判断是否收到回复(英文 & 中文)
            has_reply = ('Reply from' in output or '来自' in output
                         or '回复' in output or 'bytes=' in output)
            if not has_reply:
                return False, None, 100, output.strip()
            # 解析平均延迟(英文 & 中文 Windows 均适配)
            avg_ms = None
            m = re.search(r'Average\s*=\s*(\d+)ms|平均\s*=\s*(\d+)ms', output)
            if m:
                avg_ms = int(m.group(1) or m.group(2))
            # 解析丢包率
            loss = 0
            m = re.search(r'\((\d+)%\s*loss\)|\((\d+)%\s*丢失\)', output)
            if m:
                loss = int(m.group(1) or m.group(2))
            return True, avg_ms, loss, output.strip()
        except subprocess.TimeoutExpired:
            return False, None, 100, 'timeout'
        except Exception as e:
            return False, None, 100, str(e)

    def dns_lookup(self, target, dns_server=None):
        """DNS 解析测试 - 使用 PowerShell Resolve-DnsName"""
        try:
            if dns_server:
                ps_script = f'Resolve-DnsName {target} -DnsOnly -Server {dns_server} -ErrorAction Stop | Select-Object IPAddress,NameHost | Format-List'
            else:
                ps_script = f'Resolve-DnsName {target} -DnsOnly -ErrorAction Stop | Select-Object IPAddress,NameHost | Format-List'
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps_script],
                capture_output=True, timeout=10
            )
            output = decode_output(result.stdout)
            # 提取所有 IPv4 地址
            ipv4_addrs = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', output)
            ip = ipv4_addrs[0] if ipv4_addrs else None
            name_resolved = (ip is not None and "can't find" not in output.lower()
                             and '找不到' not in output)
            return name_resolved, ip, output
        except Exception as e:
            return False, None, str(e)

    def traceroute(self, target):
        """Tracert 路由追踪 - 使用 PowerShell"""
        try:
            ps_script = f'Test-NetConnection -ComputerName {target} -TraceRoute -WarningAction SilentlyContinue | Select-Object RemoteAddress,RemotePort,TcpTestSucceeded,TraceRoute | Format-List'
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps_script],
                capture_output=True, timeout=60
            )
            return decode_output(result.stdout)
        except Exception:
            return "追踪失败"

    def run_full_diagnostic(self, progress_callback=None):
        """运行完整诊断,返回结果字典"""
        results = {}

        # 1. 网络状态总览
        if progress_callback:
            progress_callback(0, "获取网络状态...")
        try:
            results['overview'] = self.get_overview()
        except Exception as e:
            results['overview'] = []
            if self.log_callback:
                self.log_callback(f"获取网络状态失败: {e}")

        # 2. Ping 测试
        results['ping'] = []
        total_ping = len(self.PING_TARGETS)
        for i, (target, label, color) in enumerate(self.PING_TARGETS):
            if progress_callback:
                pct = int((i / total_ping) * 40) + 10
                progress_callback(pct, f"Ping {label}...")
            try:
                ok, avg_ms, loss, _ = self.ping(target)
                results['ping'].append({
                    'target': target,
                    'label': label,
                    'color': color,
                    'ok': ok,
                    'avg_ms': avg_ms,
                    'loss': loss,
                })
            except Exception as e:
                results['ping'].append({
                    'target': target,
                    'label': label,
                    'color': color,
                    'ok': False,
                    'avg_ms': None,
                    'loss': 100,
                })
                if self.log_callback:
                    self.log_callback(f"Ping {label} 失败: {e}")

        # 3. DNS 解析
        results['dns'] = []
        test_host = "www.baidu.com"
        total_dns = len(self.DNS_TARGETS)
        for i, (dns, label) in enumerate(self.DNS_TARGETS):
            if progress_callback:
                pct = 55 + int((i / total_dns) * 40)
                progress_callback(pct, f"DNS {label}...")
            try:
                ok, ip, _ = self.dns_lookup(test_host, dns)
                results['dns'].append({
                    'dns': dns,
                    'label': label,
                    'ok': ok,
                    'ip': ip,
                })
            except Exception as e:
                results['dns'].append({
                    'dns': dns,
                    'label': label,
                    'ok': False,
                    'ip': None,
                })
                if self.log_callback:
                    self.log_callback(f"DNS {label} 解析失败: {e}")

        if progress_callback:
            progress_callback(100, "诊断完成")
        return results
