#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows 网络重置工具 - GUI 版本 v3.2
修复:
  1. DNS切换"未找到活动网卡"问题 - 改进适配器检测逻辑
  2. 日志界面闪退 - 修复线程安全问题
  3. Lambda捕获bug - 使用functools.partial或默认参数
  4. 网络诊断卡死 - 增加超时和异常处理
  5. DNS lookup bug - 跳过DNS服务器自身IP取真实结果
  6. 母亲节特别版 - 温馨问候语
  7. Windows 7 (32/64-bit) 兼容性支持
     - Get-NetAdapter/WMI 双通道自动切换
     - Resolve-DnsName → nslookup 回退
     - Test-NetConnection → tracert.exe 回退
     - 字体自动检测回退
"""

import os
import sys
import subprocess
import threading
import time
import re
import tkinter as tk
from tkinter import ttk, messagebox
import ctypes
import functools


# ===== 单例检测(socket方式) =====
import socket

_SINGLETON_PORT = 45678  # 固定端口
_SINGLETON_SOCKET = None

def _acquire_singleton():
    """使用socket端口绑定实现单例检测(Windows友好)"""
    global _SINGLETON_SOCKET
    try:
        _SINGLETON_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _SINGLETON_SOCKET.bind(('127.0.0.1', _SINGLETON_PORT))
        _SINGLETON_SOCKET.listen(1)
        return True  # 成功绑定 = 第一个实例
    except socket.error:
        return False  # 端口已被占用 = 已有实例运行

_am_first = _acquire_singleton()

def _release_singleton():
    """释放socket(程序退出时调用)"""
    global _SINGLETON_SOCKET
    if _SINGLETON_SOCKET:
        try:
            _SINGLETON_SOCKET.close()
        except Exception:
            pass


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def _is_win7_or_older():
    """检测是否 Windows 7 或更早版本（Get-NetAdapter/Resolve-DnsName 等命令不可用）"""
    try:
        ver = sys.getwindowsversion()
        # Win7 = 6.1, Vista = 6.0, Win2k8 = 6.0, XP = 5.1
        return ver.major <= 5 or (ver.major == 6 and ver.minor <= 1)
    except Exception:
        return False


# ===== 配色方案 =====
COLORS = {
    "bg": "#1e1e2e",
    "surface": "#313244",
    "surface2": "#45475a",
    "bg2": "#181825",
    "text": "#cdd6f4",
    "subtext": "#a6adc8",
    "muted": "#6c7086",
    "green": "#a6e3a1",
    "yellow": "#f9e2af",
    "red": "#f38ba8",
    "blue": "#89b4fa",
    "purple": "#cba6f7",
    "orange": "#fab387",
    "teal": "#94e2d5",
    "pink": "#f5c2e7",
    "sky": "#89dceb",
}


# ============================================================
#  网络重置核心类
# ============================================================

# ===== DNS 预设配置 =====
DNS_PRESETS = {
    "自动获取(DHCP)": {"mode": "dhcp", "primary": "", "secondary": "", "color": COLORS["muted"]},
    "阿里 DNS":    {"mode": "static", "primary": "223.5.5.5",  "secondary": "223.6.6.6",  "color": COLORS["orange"]},
    "Google DNS": {"mode": "static", "primary": "8.8.8.8",    "secondary": "8.8.4.4",    "color": COLORS["blue"]},
    "Cloudflare": {"mode": "static", "primary": "1.1.1.1",    "secondary": "1.0.0.1",    "color": COLORS["sky"]},
    "114 DNS":    {"mode": "static", "primary": "114.114.114.114", "secondary": "114.114.115.115", "color": COLORS["pink"]},
}


class NetworkResetTool:
    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.static_configs = []
        self._cancel = False

    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    def run_cmd(self, cmd, show_output=False, timeout=10):
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                   encoding='gbk', errors='ignore', timeout=timeout)
            if show_output and result.stdout:
                self.log(result.stdout.strip())
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
            stdout = self._decode_output(result.stdout)
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
        else:
            self.log("  ✗ Winsock 重置失败")
            return False

    def reset_tcpip(self):
        self.log("[操作] 重置 TCP/IP 协议栈...")
        self.run_cmd('netsh int ip reset', timeout=15)
        self.run_cmd('netsh int ipv6 reset', timeout=15)
        self.log("  ✓ TCP/IP 重置完成")
        return True

    def flush_dns(self):
        self.log("[操作] 清除 DNS 缓存...")
        if self.run_cmd('ipconfig /flushdns'):
            self.log("  ✓ DNS 缓存已清除")
            return True
        else:
            self.log("  ✗ DNS 缓存清除失败")
            return False

    def flush_arp(self):
        self.log("[操作] 清除 ARP 缓存...")
        if self.run_cmd('netsh interface ip delete arpcache'):
            self.log("  ✓ ARP 缓存已清除")
            return True
        else:
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
            if ip:
                self.log(f"  恢复: {name}")
                cmd = f'netsh interface ip set address "{name}" static {ip} {mask} {gateway} 1'
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
            import ctypes
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
            stdout = self._decode_output(result.stdout)
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
        # 先设主 DNS
        cmd_set_primary = f'netsh interface ip set dns "{adapter_name}" static {primary} primary'
        ok1 = self.run_cmd(cmd_set_primary)
        if not ok1:
            self.log(f"  ✗ 主 DNS {primary} 设置失败")
        else:
            self.log(f"  ✓ 主 DNS: {primary}")
        # 再设备用 DNS
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
            self.log(f"  ✓ DNS 已切换为自动获取 (DHCP)")
            return True
        else:
            self.log(f"  ✗ DNS 切换失败")
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
        if self._cancel:
            return
        self.reset_winsock()
        self.log("")
        if self._cancel:
            return
        self.reset_tcpip()
        self.log("")
        if self._cancel:
            return
        self.flush_dns()
        self.flush_arp()
        self.log("")
        if self._cancel:
            return
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
        ("8.8.8.8",    "Google DNS",           "blue"),
        ("1.1.1.1",    "Cloudflare DNS",       "sky"),
        ("223.5.5.5",  "阿里 DNS",              "orange"),
        ("www.baidu.com",  "百度",            "red"),
        ("www.qq.com",     "腾讯",            "green"),
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
                capture_output=True, text=False, timeout=timeout
            )
            # PowerShell outputs UTF-8 on modern Windows (or system OEM codepage)
            output = result.stdout
            # Try UTF-8 first (most common), then GBK (Chinese Windows), then UTF-16LE
            for enc in ('utf-8', 'gbk', 'utf-16-le'):
                try:
                    return output.decode(enc).strip()
                except (UnicodeDecodeError, UnicodeError):
                    continue
            # Fallback: replace errors
            return output.decode('utf-8', errors='replace').strip()
        except Exception as e:
            return ""

    def _get_overview_modern(self):
        """使用 Get-NetAdapter（Win8+）"""
        results = []
        ps = '''
$out = @()
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

    def _get_overview_legacy(self):
        """使用 WMI + netsh 查询（Win7 兼容）"""
        results = []
        ps_wmi = '''
$adapters = Get-WmiObject Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -eq $true }
if ($adapters) {
    $a = $adapters | Select-Object -First 1
    $nic = Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.GUID -eq $a.SettingID } | Select-Object -First 1
    $name = if ($nic) { $nic.NetConnectionID } else { "未知" }
    $desc = if ($nic) { $nic.Description } else { "" }
    $mac = if ($nic) { $nic.MacAddress } else { "" }
    $speed = if ($nic) { [math]::Round($nic.Speed / 1000000) } else { 0 }
    $ip = ($a.IPAddress | Where-Object { $_ -match '\\\\.' }) -join ','
    $gw = ($a.DefaultIPGateway -join ',')
    $dns = ($a.DNSServerSearchOrder -join ', ')
    $dhcp = if ($a.DHCPEnabled) { "已启用" } else { "手动" }
    Write-Output "状态|up"
    Write-Output "接口|$name"
    Write-Output "描述|$desc"
    Write-Output "MAC|$mac"
    Write-Output "速度|${speed} Mbps"
    if ($ip) { Write-Output "IPv4|$ip" }
    if ($gw) { Write-Output "网关|$gw" }
    if ($dns) { Write-Output "DNS|$dns" }
    Write-Output "DHCP|$dhcp"
}
'''
        output = self._run_ps(ps_wmi, timeout=10)
        lines = [l for l in output.split('\n') if l.strip() and '|' in l]
        for line in lines:
            parts = line.split('|', 1)
            if len(parts) == 2:
                k, v = parts[0].strip(), parts[1].strip()
                results.append((k, v))
        if not results:
            # 最后备选：ipconfig
            try:
                raw = subprocess.run('ipconfig', shell=True, capture_output=True, timeout=5).stdout
                try:
                    output = raw.decode('gbk')
                except Exception:
                    output = raw.decode('utf-8', errors='replace')
                # 简单提取 IPv4 和默认网关
                for m in re.finditer(r'IPv4[^:]*:\s*(\S+)', output):
                    results.append(('IPv4', m.group(1)))
                for m in re.finditer(r'默认网关[^:]*:\s*(\S+)', output):
                    results.append(('网关', m.group(1)))
            except Exception:
                pass
        return results

    def get_overview(self):
        """自动选择 Win7/Win8+ 命令获取网络状态总览"""
        if _is_win7_or_older():
            return self._get_overview_legacy()
        results = self._get_overview_modern()
        if not results:
            results = self._get_overview_legacy()
        return results

    @staticmethod
    def _decode_output(raw_bytes):
        """解码 subprocess 输出,中文 Windows 优先 GBK,尝试 UTF-16LE(Win7 PowerShell 默认输出编码)"""
        for enc in ('gbk', 'utf-16-le', 'utf-8'):
            try:
                return raw_bytes.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw_bytes.decode('utf-8', errors='replace')

    def ping(self, target, count=4):
        """Ping 一个目标,使用 cmd /c ping,返回 (ok, avg_ms, loss_pct, output)"""
        try:
            # 先用 GBK 解码(中文 Windows 默认代码页 936),回退 UTF-8
            raw = subprocess.run(
                f'cmd /c ping -n {count} {target}',
                shell=True,
                capture_output=True, timeout=15
            ).stdout or b''
            try:
                output = raw.decode('gbk')
            except (UnicodeDecodeError, LookupError):
                output = raw.decode('utf-8', errors='replace')
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
        """DNS 解析测试 - PowerShell Resolve-DnsName（Win7 备选 nslookup）"""
        # Win7 没有 Resolve-DnsName，使用 nslookup
        use_nslookup = sys.getwindowsversion().major <= 5 or (
            sys.getwindowsversion().major == 6 and sys.getwindowsversion().minor <= 1
        ) if hasattr(sys, 'getwindowsversion') else False

        if use_nslookup:
            try:
                if dns_server:
                    cmd_line = f'nslookup {target} {dns_server}'
                else:
                    cmd_line = f'nslookup {target}'
                raw = subprocess.run(
                    ['cmd', '/c', cmd_line],
                    shell=True, capture_output=True, timeout=10
                )
                try:
                    output = raw.stdout.decode('gbk')
                except Exception:
                    output = raw.stdout.decode('utf-8', errors='replace')
                # nslookup 成功输出包含 "Name:" 和 "Address:"
                ip_addrs = re.findall(r'Address(?:es)?:\s+(\S+)', output)
                ip = None
                for addr in ip_addrs:
                    if re.match(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', addr):
                        ip = addr
                        break
                name_resolved = (ip is not None and '找不到' not in output
                                 and "can't find" not in output.lower()
                                 and 'Non-existent domain' not in output)
                return name_resolved, ip, output.strip()
            except Exception as e:
                return False, None, str(e)

        # Win8+ 使用 Resolve-DnsName
        try:
            if dns_server:
                ps_script = f'Resolve-DnsName {target} -DnsOnly -Server {dns_server} -ErrorAction Stop | Select-Object IPAddress,NameHost | Format-List'
            else:
                ps_script = f'Resolve-DnsName {target} -DnsOnly -ErrorAction Stop | Select-Object IPAddress,NameHost | Format-List'
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps_script],
                capture_output=True, timeout=10
            )
            output = self._decode_output(result.stdout)
            # 提取所有 IPv4 地址
            ipv4_addrs = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', output)
            ip = ipv4_addrs[0] if ipv4_addrs else None
            # 检查是否解析成功
            name_resolved = (ip is not None and "can't find" not in output.lower()
                             and '找不到' not in output)
            return name_resolved, ip, output
        except Exception as e:
            # 回退到 nslookup
            try:
                cmd_line = f'nslookup {target}'
                if dns_server:
                    cmd_line = f'nslookup {target} {dns_server}'
                raw = subprocess.run(
                    ['cmd', '/c', cmd_line],
                    shell=True, capture_output=True, timeout=10
                )
                try:
                    output = raw.stdout.decode('gbk')
                except Exception:
                    output = raw.stdout.decode('utf-8', errors='replace')
                ip_addrs = re.findall(r'Address(?:es)?:\s+(\S+)', output)
                ip = None
                for addr in ip_addrs:
                    if re.match(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', addr):
                        ip = addr
                        break
                name_resolved = (ip is not None and '找不到' not in output
                                 and "can't find" not in output.lower())
                return name_resolved, ip, output.strip()
            except Exception as e2:
                return False, None, str(e2)

    def traceroute(self, target):
        """Tracert 路由追踪 - 优先 PowerShell，Win7 回退到 tracert.exe"""
        # Win7 没有 Test-NetConnection，使用 tracert.exe
        use_tracert = sys.getwindowsversion().major <= 5 or (
            sys.getwindowsversion().major == 6 and sys.getwindowsversion().minor <= 1
        ) if hasattr(sys, 'getwindowsversion') else False

        if use_tracert:
            try:
                raw = subprocess.run(
                    ['cmd', '/c', f'tracert -h 30 {target}'],
                    shell=True, capture_output=True, timeout=60
                )
                try:
                    output = raw.stdout.decode('gbk')
                except Exception:
                    output = raw.stdout.decode('utf-8', errors='replace')
                if not output.strip():
                    try:
                        output = raw.stderr.decode('gbk')
                    except Exception:
                        output = raw.stderr.decode('utf-8', errors='replace')
                return output.strip()
            except Exception as e:
                return f"追踪失败: {e}"

        try:
            ps_script = f'Test-NetConnection -ComputerName {target} -TraceRoute -WarningAction SilentlyContinue | Select-Object RemoteAddress,RemotePort,TcpTestSucceeded,TraceRoute | Format-List'
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps_script],
                capture_output=True, timeout=60
            )
            output = self._decode_output(result.stdout)
            if '找不到' in output or output.strip() == '':
                raise Exception("Resolve-DnsName not available")
            return output
        except Exception:
            # 回退到 tracert.exe
            try:
                raw = subprocess.run(
                    ['cmd', '/c', f'tracert -h 30 {target}'],
                    shell=True, capture_output=True, timeout=60
                )
                try:
                    output = raw.stdout.decode('gbk')
                except Exception:
                    output = raw.stdout.decode('utf-8', errors='replace')
                return output.strip()
            except Exception as e:
                return f"追踪失败: {e}"

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


# ============================================================
#  代理 / Clash 诊断与修复
# ============================================================

class ProxyRepairTool:
    """代理 / Clash 诊断与修复

    针对"外网连不上"最常见的两类根因:
      1. 系统代理指向了一个已经宕机 / 未监听的端口(例如 7897 无人监听)
         -> 浏览器/系统走该端口全部失败
      2. Clash(mihomo) 的 dns.enable 被关掉,而 enhanced-mode=fake-ip,
         导致所有域名解析 i/o timeout,代理节点与直连域名全部超时

    对应修复: 把系统代理重新指向真正在工作的 Clash 端口; 并开启 Clash DNS。
    """

    # Clash 系常见配置目录(按优先级探测)
    CLASH_CONFIG_DIRS = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "moe.elaina.clash.nyanpasu", ".config", "clash-verge"),
        os.path.join(os.environ.get("APPDATA", ""),
                     "moe.elaina.clash.nyanpasu", ".config", "clash-verge"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "clash-verge", "config"),
        r"D:\Software\Clash.Nyanpasu_1.6.1_x64_portable\.config\clash-verge",
    ]

    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def log(self, msg, color=None):
        if self.log_callback:
            self.log_callback(msg, color)

    # ---------- 系统代理 ----------
    def get_system_proxy(self):
        import winreg
        enable, server = 0, ""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
            try:
                enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            except FileNotFoundError:
                enable = 0
            try:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
            except FileNotFoundError:
                server = ""
            winreg.CloseKey(key)
        except Exception as e:
            self.log(f"读取系统代理失败: {e}")
        return bool(enable), (server or "").strip()

    @staticmethod
    def parse_proxy_server(server):
        """解析 ProxyServer -> [(scheme, host, port), ...]"""
        results = []
        server = (server or "").strip()
        if not server:
            return results
        for part in server.replace(' ', '').split(';'):
            if '=' in part:
                scheme, addr = part.split('=', 1)
            else:
                scheme, addr = 'http', part
            if ':' in addr:
                host, _, port = addr.rpartition(':')
                try:
                    results.append((scheme, host, int(port)))
                except ValueError:
                    continue
        return results

    @staticmethod
    def is_port_open(host, port, timeout=2):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((host, port))
            s.close()
            return True
        except Exception:
            return False

    def set_system_proxy(self, host, port, enable=True):
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                                 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1 if enable else 0)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
            try:
                winreg.QueryValueEx(key, "ProxyOverride")
            except FileNotFoundError:
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ,
                                  "localhost;127.*;[::1]")
            winreg.CloseKey(key)
            ctypes.windll.Wininet.InternetSetOptionW(0, 39, 0, 0)  # SETTINGS_CHANGED
            ctypes.windll.Wininet.InternetSetOptionW(0, 37, 0, 0)  # REFRESH
            return True
        except Exception as e:
            self.log(f"设置系统代理失败: {e}")
            return False

    # ---------- 发现运行中的代理核心 ----------
    def find_proxy_cores(self):
        cores = []
        try:
            ps = ('Get-NetTCPConnection -State Listen | '
                  'Select-Object LocalPort,OwningProcess | '
                  'ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; '
                  'if ($p) { Write-Output ($_.LocalPort.ToString() + ":" + $p.Name) } }')
            out = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                                 capture_output=True, timeout=15).stdout
            out = out.decode('utf-8', errors='replace')
            for line in out.splitlines():
                line = line.strip()
                if ':' in line:
                    port_s, _, name = line.rpartition(':')
                    try:
                        cores.append({'port': int(port_s), 'process': name})
                    except ValueError:
                        continue
        except Exception as e:
            self.log(f"扫描监听端口失败: {e}")
        return cores

    def find_clash_core(self):
        for c in self.find_proxy_cores():
            n = (c.get('process') or '').lower()
            if 'mihomo' in n or 'clash' in n:
                return c
        return None

    # ---------- Clash 配置检查 / 修复 ----------
    def find_clash_config_dir(self):
        for d in self.CLASH_CONFIG_DIRS:
            if d and os.path.isdir(d):
                return d
        return None

    def read_clash_mixed_port(self, cfg_dir):
        path = os.path.join(cfg_dir, 'clash-config.yaml')
        if not os.path.isfile(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    st = line.strip()
                    if st.startswith('mixed-port:'):
                        try:
                            return int(st.split(':', 1)[1].strip())
                        except ValueError:
                            return None
        except Exception:
            pass
        return None

    def read_clash_controller(self, cfg_dir):
        port, secret = None, None
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        st = line.strip()
                        if st.startswith('external-controller:'):
                            val = st.split(':', 1)[1].strip()
                            if ':' in val:
                                _, _, p = val.rpartition(':')
                                try:
                                    port = int(p)
                                except ValueError:
                                    pass
                        elif st.startswith('secret:'):
                            secret = st.split(':', 1)[1].strip().strip('"\'')
            except Exception:
                pass
        return port, secret

    def read_clash_dns_enabled(self, cfg_dir):
        path = os.path.join(cfg_dir, 'clash-config.yaml')
        if not os.path.isfile(path):
            return None
        enabled, _ = self._scan_dns_enable(path)
        return enabled

    def _scan_dns_enable(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception:
            return None, False
        in_dns = False
        base_indent = None
        for line in lines:
            st = line.lstrip()
            ind = len(line) - len(st)
            if st.startswith('dns:'):
                in_dns = True
                base_indent = ind
                continue
            if in_dns:
                if st and ind <= base_indent:
                    in_dns = False
                    continue
                if st.startswith('enable:'):
                    val = st.split(':', 1)[1].strip().lower()
                    return val == 'true', True
        return None, False

    def enable_clash_dns(self, cfg_dir):
        changed = []
        for fname in ['clash-config.yaml', 'clash-guard-overrides.yaml']:
            path = os.path.join(cfg_dir, fname)
            if not os.path.isfile(path):
                continue
            if self._set_dns_enable_true(path):
                changed.append(fname)
        return changed

    def _set_dns_enable_true(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            self.log(f"读取 {os.path.basename(path)} 失败: {e}")
            return False
        out = []
        changed = False
        in_dns = False
        base_indent = None
        for line in lines:
            st = line.lstrip()
            ind = len(line) - len(st)
            if st.startswith('dns:'):
                in_dns = True
                base_indent = ind
                out.append(line)
                continue
            if in_dns:
                if st and ind <= base_indent:
                    in_dns = False
                elif st.startswith('enable:'):
                    prefix = line[:line.index('enable:')]
                    new = f"{prefix}enable: true\n"
                    if new.strip() != line.strip():
                        changed = True
                    out.append(new)
                    continue
            out.append(line)
        if changed:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.writelines(out)
            except Exception as e:
                self.log(f"写入 {os.path.basename(path)} 失败: {e}")
                return False
        return changed

    def restart_clash_core(self, port=17650, secret=None):
        import urllib.request
        url = f"http://127.0.0.1:{port}/restart"
        headers = {}
        if secret:
            headers['Authorization'] = f"Bearer {secret}"
        try:
            req = urllib.request.Request(url, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.status == 200
        except Exception as e:
            self.log(f"重启 Clash 核心失败: {e}")
            return False

    # ---------- 一键诊断 ----------
    def diagnose(self):
        """返回诊断结论字典"""
        result = {
            'proxy_enabled': False,
            'proxy_server': '',
            'proxy_ports': [],
            'proxy_alive': None,
            'clash_core': None,
            'clash_dns': None,
            'issues': [],
            'suggestions': [],
        }
        en, server = self.get_system_proxy()
        result['proxy_enabled'] = en
        result['proxy_server'] = server
        ports = self.parse_proxy_server(server)
        result['proxy_ports'] = ports
        alive_any = None
        for _, host, port in ports:
            ok = self.is_port_open(host, port)
            alive_any = ok if alive_any is None else (alive_any or ok)
        result['proxy_alive'] = alive_any
        if en and ports and alive_any is False:
            result['issues'].append(
                f"系统代理指向 {server} 但该端口没有服务在监听,外网会全部失败")
            result['suggestions'].append(
                "把系统代理重新指向真正在工作的代理端口(见下方「代理核心」)")
        core = self.find_clash_core()
        result['clash_core'] = core
        cfg_dir = self.find_clash_config_dir()
        proxy_port = self.read_clash_mixed_port(cfg_dir) if cfg_dir else None
        result['clash_proxy_port'] = proxy_port
        if core:
            if proxy_port:
                result['suggestions'].append(
                    f"发现 Clash 核心({core['process']}),其代理端口为 {proxy_port},可把系统代理指向它")
            else:
                result['suggestions'].append(
                    f"发现 Clash 核心在端口 {core['port']} 运行({core['process']}),可把系统代理指向它")
        cfg_dir = self.find_clash_config_dir()
        if cfg_dir:
            dns_on = self.read_clash_dns_enabled(cfg_dir)
            result['clash_dns'] = dns_on
            if dns_on is False:
                result['issues'].append(
                    "Clash 的 dns.enable=false,而 enhanced-mode=fake-ip,会导致所有域名解析超时")
                result['suggestions'].append(
                    "开启 Clash DNS(enable:true)并重启核心")
        elif core:
            result['suggestions'].append(
                "未找到 Clash 配置目录,无法自动修复 DNS,请手动检查订阅")
        if not result['issues']:
            result['suggestions'].append("未发现明显代理问题")
        return result

    # ---------- 一键修复 ----------
    def repair(self):
        """返回 (success, list_of_actions)"""
        actions = []
        ok = True
        en, server = self.get_system_proxy()
        ports = self.parse_proxy_server(server)
        alive = any(self.is_port_open(h, p) for _, h, p in ports) if ports else False
        core = self.find_clash_core()
        cfg_dir = self.find_clash_config_dir()
        target_port = self.read_clash_mixed_port(cfg_dir) if cfg_dir else None
        if target_port is None and core:
            target_port = core['port']
        # 1) 系统代理端口死了 -> 指向 Clash 代理端口
        if en and ports and not alive and target_port:
            if self.set_system_proxy('127.0.0.1', target_port, enable=True):
                actions.append(f"系统代理已重新指向 Clash 端口 127.0.0.1:{target_port}")
            else:
                ok = False
                actions.append("系统代理重设失败")
        elif (not en) and target_port:
            if self.set_system_proxy('127.0.0.1', target_port, enable=True):
                actions.append(f"已为系统启用代理并指向 Clash 端口 127.0.0.1:{target_port}")
            else:
                ok = False
        # 2) Clash DNS 关闭 -> 开启并重启
        cfg_dir = self.find_clash_config_dir()
        if cfg_dir:
            dns_on = self.read_clash_dns_enabled(cfg_dir)
            if dns_on is False:
                changed = self.enable_clash_dns(cfg_dir)
                if changed:
                    actions.append(f"已开启 Clash DNS: {', '.join(changed)}")
                    port, secret = self.read_clash_controller(cfg_dir)
                    if port:
                        if self.restart_clash_core(port, secret):
                            actions.append("已重启 Clash 核心使 DNS 生效")
                        else:
                            actions.append("DNS 配置已改,但核心重启失败(请手动在 GUI 里应用/重启)")
                else:
                    actions.append("Clash DNS 无需修改")
        if not actions:
            actions.append("无需修复")
        return ok, actions


# ============================================================
#  UI 公共组件
# ============================================================

def make_btn_style():
    return {'relief': "flat", 'cursor': "hand2", 'padx': 15, 'pady': 6}


def styled_btn(parent, text, cmd, bg, fg=None, font_size=10, bold=False, **kw):
    if fg is None:
        fg = COLORS["bg"]
    font_name = FONT_FAMILY
    font_weight = "bold" if bold else "normal"
    return tk.Button(parent, text=text, font=(font_name, font_size, font_weight),
                     bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
                     command=cmd, **make_btn_style(), **kw)


# ============================================================
#  重置面板(Tab 1)
# ============================================================

class ResetPanel(tk.Frame):
    """左侧"网络重置"标签页"""

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        self._running = False
        self._static_configs = []
        self._build_ui()

    def _build_ui(self):
        # 标题
        header = tk.Frame(self, bg=COLORS["surface"], pady=12)
        header.pack(fill="x")
        tk.Label(header, text="🌐 Windows 网络重置工具", font=(FONT_FAMILY, 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text="重置网络配置 · 修复网络问题 · 保留静态IP",
                 font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        # 按钮区
        btn_area = tk.Frame(self, bg=self["bg"], pady=12)
        btn_area.pack(fill="x", padx=20)

        # 一键重置
        self.btn_all = styled_btn(btn_area, "🚀 一键重置全部",
                                  self._do_all_reset, COLORS["green"],
                                  font_size=13, bold=True)
        self.btn_all.pack(fill="x", pady=(0, 10))

        tk.Frame(btn_area, bg=COLORS["surface2"], height=1).pack(fill="x", pady=5)
        tk.Label(btn_area, text="- 单独操作 -", font=(FONT_FAMILY, 9),
                 fg=COLORS["muted"], bg=self["bg"]).pack(pady=3)

        # 2行 x 3列按钮
        row1 = tk.Frame(btn_area, bg=self["bg"])
        row1.pack(fill="x", pady=3)
        row2 = tk.Frame(btn_area, bg=self["bg"])
        row2.pack(fill="x", pady=3)
        row3 = tk.Frame(btn_area, bg=self["bg"])
        row3.pack(fill="x", pady=3)

        self._make_btn(row1, "🔄 重置 Winsock", self._do_winsock, COLORS["blue"]).pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row1, "🔄 重置 TCP/IP", self._do_tcpip, COLORS["purple"]).pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row1, "🧹 清除 DNS",    self._do_dns,    COLORS["orange"]).pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row2, "📋 清除 ARP",   self._do_arp,    COLORS["teal"]).pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row2, "🔄 刷新 DHCP",  self._do_dhcp,   COLORS["pink"]).pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row2, "💾 备份IP",      self._do_backup, COLORS["yellow"]).pack(side="left", expand=True, fill="x", padx=3)

        self._make_btn(row3, "📥 还原IP",      self._do_restore, COLORS["sky"]).pack(side="left", expand=True, fill="x", padx=3)

        # ===== DNS 一键切换 =====
        tk.Frame(btn_area, bg=COLORS["surface2"], height=1).pack(fill="x", pady=(8, 3))
        dns_header = tk.Frame(btn_area, bg=self["bg"])
        dns_header.pack(fill="x", pady=(0, 4))
        tk.Label(dns_header, text="- DNS 一键切换 -", font=(FONT_FAMILY, 9),
                 fg=COLORS["muted"], bg=self["bg"]).pack(side="left")
        self.dns_current_label = tk.Label(dns_header, text="", font=(FONT_FAMILY, 9),
                                          fg=COLORS["yellow"], bg=self["bg"])
        self.dns_current_label.pack(side="right")

        # DNS 预设按钮行
        dns_row1 = tk.Frame(btn_area, bg=self["bg"])
        dns_row1.pack(fill="x", pady=2)
        dns_row2 = tk.Frame(btn_area, bg=self["bg"])
        dns_row2.pack(fill="x", pady=2)

        for i, (name, cfg) in enumerate(DNS_PRESETS.items()):
            row = dns_row1 if i < 3 else dns_row2
            self._make_dns_btn(row, name, cfg).pack(side="left", expand=True, fill="x", padx=3)

        # 自定义 DNS 输入行
        dns_custom_row = tk.Frame(btn_area, bg=self["bg"])
        dns_custom_row.pack(fill="x", pady=(2, 0))
        tk.Label(dns_custom_row, text="自定义:", font=(FONT_FAMILY, 9),
                 fg=COLORS["subtext"], bg=self["bg"]).pack(side="left", padx=(3, 4))
        self.dns_primary_entry = tk.Entry(dns_custom_row, font=(FONT_MONO, 9),
                                           bg=COLORS["surface"], fg=COLORS["text"],
                                           insertbackground=COLORS["text"],
                                           relief="flat", bd=0, width=14)
        self.dns_primary_entry.pack(side="left", padx=2)
        self.dns_primary_entry.insert(0, "")
        tk.Label(dns_custom_row, text="备用:", font=(FONT_FAMILY, 9),
                 fg=COLORS["subtext"], bg=self["bg"]).pack(side="left", padx=(6, 4))
        self.dns_secondary_entry = tk.Entry(dns_custom_row, font=(FONT_MONO, 9),
                                            bg=COLORS["surface"], fg=COLORS["text"],
                                            insertbackground=COLORS["text"],
                                            relief="flat", bd=0, width=14)
        self.dns_secondary_entry.pack(side="left", padx=2)
        styled_btn(dns_custom_row, "应用", self._do_custom_dns,
                   COLORS["green"], font_size=9).pack(side="left", padx=6)

        # 状态 + 进度
        self.status_label = tk.Label(self, text="就绪", font=(FONT_FAMILY, 10),
                                      fg=COLORS["green"], bg=self["bg"], anchor="w")
        self.status_label.pack(fill="x", padx=20, pady=(5, 0))

        self.progress = ttk.Progressbar(self, mode="indeterminate",
                                        style="green.Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=20, pady=5)

        # 日志区
        log_frame = tk.Frame(self, bg=self["bg"])
        log_frame.pack(fill="both", expand=True, padx=20, pady=5)

        log_header = tk.Frame(log_frame, bg=self["bg"])
        log_header.pack(fill="x")
        tk.Label(log_header, text="📋 执行日志", font=(FONT_FAMILY, 10, "bold"),
                 fg=COLORS["text"], bg=self["bg"]).pack(side="left")
        tk.Button(log_header, text="清空", font=(FONT_FAMILY, 9),
                  bg=COLORS["surface2"], fg=COLORS["text"], relief="flat",
                  command=self._clear_log, cursor="hand2").pack(side="right")

        log_container = tk.Frame(log_frame, bg=COLORS["bg2"])
        log_container.pack(fill="both", expand=True, pady=5)

        scrollbar = tk.Scrollbar(log_container)
        scrollbar.pack(side="right", fill="y")
        self.log_box = tk.Text(log_container, font=(FONT_MONO, 10),
                               bg=COLORS["bg2"], fg=COLORS["text"],
                               insertbackground=COLORS["text"], relief="flat", bd=0,
                               state="disabled", yscrollcommand=scrollbar.set)
        self.log_box.pack(fill="both", expand=True, padx=5, pady=5)
        scrollbar.config(command=self.log_box.yview)

        # 底部按钮
        bottom = tk.Frame(self, bg=self["bg"], pady=10)
        bottom.pack(fill="x", padx=20)

        self.hint_label = tk.Label(bottom, text="", font=(FONT_FAMILY, 9),
                                    fg=COLORS["muted"], bg=self["bg"], anchor="w")
        self.hint_label.pack(side="left")

        btn_group = tk.Frame(bottom, bg=self["bg"])
        btn_group.pack(side="right")
        self.btn_restart = styled_btn(btn_group, "🔁 重启电脑", self._restart,
                                       COLORS["yellow"], state="disabled")
        self.btn_restart.pack(side="left", padx=5)
        styled_btn(btn_group, "✕ 退出", self._quit, COLORS["red"]).pack(side="left", padx=5)

        # 样式
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("green.Horizontal.TProgressbar",
                        troughcolor=COLORS["surface"], background=COLORS["green"], thickness=8)

        # 管理员检查
        if not is_admin():
            self._log("⚠ 警告: 未以管理员身份运行,部分功能可能受限")
            self._log("  → 右键选择 [以管理员身份运行] 获得完整功能")

        self._log("✅ 程序已就绪,请选择操作...")

        # 刷新当前 DNS 状态
        self.after(500, self._refresh_dns_status)

    def _make_btn(self, parent, text, cmd, color):
        return styled_btn(parent, text, cmd, color, font_size=10, bold=True)

    def _get_active_adapter(self):
        """获取活动网卡名称 - Win7 兼容（自动选择 WMI/NetAdapter）"""
        # Win7: 先试 WMI（更可靠）
        if _is_win7_or_older():
            try:
                ps_wmi = '''
$adapter = Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.NetConnectionStatus -eq 2 -and $_.NetEnabled -eq $true } | Select-Object -First 1
if ($adapter) { Write-Output $adapter.NetConnectionID }
'''
                result = subprocess.run(['powershell', '-NoProfile', '-Command', ps_wmi],
                                       capture_output=True, timeout=5)
                name = self._decode_output(result.stdout).strip()
                if name:
                    self._log(f"  ✓ 检测到网卡(WMI): {name}")
                    return name
            except Exception:
                pass
        else:
            # Win8+: 先试 Get-NetAdapter
            try:
                ps1 = '''
$adapter = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | Select-Object -First 1
if ($adapter) { Write-Output $adapter.NetConnectionID }
'''
                result = subprocess.run(['powershell', '-NoProfile', '-Command', ps1],
                                       capture_output=True, timeout=5)
                name = self._decode_output(result.stdout).strip()
                if name:
                    return name
            except Exception as e:
                self._log(f"Get-NetAdapter 失败: {e}")

        # 通用备选: WMI (Win7/Win8+ 均可)
        try:
            ps2 = '''
$adapter = Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.NetConnectionStatus -eq 2 } | Select-Object -First 1
if ($adapter) { Write-Output $adapter.NetConnectionID }
'''
            result = subprocess.run(['powershell', '-NoProfile', '-Command', ps2],
                                   capture_output=True, timeout=5)
            name = self._decode_output(result.stdout).strip()
            if name:
                return name
        except Exception as e:
            self._log(f"WMI 查询失败: {e}")

        # ipconfig 解析
        try:
            result = subprocess.run(['ipconfig'], capture_output=True, timeout=5)
            output = self._decode_output(result.stdout)
            # 查找 "适配器 xxx:" 段落后有 IPv4 地址
            in_adapter = False
            for line in output.split('\n'):
                if '适配器' in line or 'adapter' in line.lower():
                    in_adapter = True
                    m = re.match(r'.*(?:适配器|adapter)\s+(.+?):', line)
                    current_name = m.group(1).strip() if m else None
                elif in_adapter and 'IPv4' in line:
                    if current_name:
                        self._log(f"  ✓ 检测到网卡(ipconfig): {current_name}")
                        return current_name
        except Exception:
            pass

        self._log("  ⚠ 未找到活动网卡")
        return None

    def _make_dns_btn(self, parent, name, cfg):
        btn = tk.Button(parent, text=name, font=(FONT_FAMILY, 9, "bold"),
                        bg=cfg['color'], fg=COLORS["bg"],
                        activebackground=cfg['color'], activeforeground=COLORS["bg"],
                        relief="flat", cursor="hand2", padx=5, pady=4,
                        command=lambda n=name: self._do_dns_switch(n))
        return btn

    def _do_dns_switch(self, preset_name):
        if self._running:
            return
        self._set_running(True, f"切换 DNS 到 {preset_name}")
        threading.Thread(target=self._thread_dns_switch,
                        args=(preset_name,), daemon=True).start()

    def _thread_dns_switch(self, preset_name):
        """修复: 使用默认参数避免lambda捕获bug"""
        adapter = self._get_active_adapter()
        if not adapter:
            # 修复: 使用after和默认参数
            self.after(0, functools.partial(self._log, "⚠ 未找到活动网卡,请检查网络连接"))
            self.after(0, functools.partial(self._set_running, False, ""))
            self.after(0, functools.partial(self._set_status, "⚠ 未找到活动网卡", COLORS["orange"]))
            return
        # 修复: 使用functools.partial避免lambda捕获问题
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.switch_dns(preset_name, adapter)
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status, f"✅ DNS 已切换到 {preset_name}", COLORS["green"]))
        self.after(0, self._refresh_dns_status)

    def _safe_log(self, msg):
        """线程安全的日志输出"""
        self.after(0, functools.partial(self._log, msg))

    def _do_custom_dns(self):
        if self._running:
            return
        primary = self.dns_primary_entry.get().strip()
        if not primary:
            self._set_status("⚠ 请输入主 DNS 地址", COLORS["orange"])
            return
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', primary):
            self._set_status("⚠ DNS 地址格式不正确", COLORS["red"])
            return
        secondary = self.dns_secondary_entry.get().strip()
        self._set_running(True, f"设置自定义 DNS: {primary}")
        threading.Thread(target=self._thread_custom_dns,
                        args=(primary, secondary), daemon=True).start()

    def _thread_custom_dns(self, primary, secondary):
        adapter = self._get_active_adapter()
        if not adapter:
            self.after(0, functools.partial(self._log, "⚠ 未找到活动网卡"))
            self.after(0, functools.partial(self._set_running, False, ""))
            return
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.log(f"[DNS] 自定义 DNS: {primary}")
        ok = tool.set_dns(adapter, primary, secondary if secondary else None)
        tool.flush_dns()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status,
            f"✅ 自定义 DNS 设置成功" if ok else "❌ DNS 设置失败",
            COLORS["green"] if ok else COLORS["red"]))
        self.after(0, self._refresh_dns_status)

    def _refresh_dns_status(self):
        """刷新当前 DNS 显示(异步,不阻塞主线程)"""
        self.dns_current_label.config(text="当前: 获取中...")

        def _worker():
            tool = NetworkResetTool()
            dns_list, mode = tool.get_current_dns()
            if dns_list:
                mode_text = "自动" if mode == "dhcp" else "手动"
                text = f"当前: {', '.join(dns_list)} [{mode_text}]"
            else:
                text = "当前: 未知"
            self.after(0, lambda: self.dns_current_label.config(text=text))

        threading.Thread(target=_worker, daemon=True).start()

    def _log(self, msg):
        """修复: 确保线程安全"""
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _set_status(self, msg, color=None):
        if color is None:
            color = COLORS["green"]
        self.status_label.config(text=msg, fg=color)

    def _set_running(self, running, task=""):
        self._running = running
        state = "disabled" if running else "normal"
        self.btn_all.config(state=state)
        if task:
            self._set_status(f"⏳ 正在执行: {task}...")
            self.progress.start(10)
        else:
            self._set_status("✅ 操作完成", COLORS["green"])
            self.progress.stop()

    def _thread_log(self, tool):
        for msg in []:
            self.after(0, lambda m=msg: self._log(m))

    # ----- 单独操作 -----
    def _do_winsock(self):
        if self._running: return
        self._set_running(True, "重置 Winsock")
        threading.Thread(target=self._thread_winsock, daemon=True).start()

    def _thread_winsock(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        ok = tool.reset_winsock()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status,
            "✅ Winsock 重置完成" if ok else "❌ 操作失败",
            COLORS["green"] if ok else COLORS["red"]))
        self.after(0, functools.partial(self._log, "\n⚠ 可能需要重启电脑使设置生效"))

    def _do_tcpip(self):
        if self._running: return
        self._set_running(True, "重置 TCP/IP")
        threading.Thread(target=self._thread_tcpip, daemon=True).start()

    def _thread_tcpip(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.reset_tcpip()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status, "✅ TCP/IP 重置完成", COLORS["green"]))
        self.after(0, functools.partial(self._log, "\n⚠ 必须重启电脑使设置生效"))

    def _do_dns(self):
        if self._running: return
        self._set_running(True, "清除 DNS 缓存")
        threading.Thread(target=self._thread_dns, daemon=True).start()

    def _thread_dns(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        ok = tool.flush_dns()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status,
            "✅ DNS 缓存已清除" if ok else "❌ 操作失败",
            COLORS["green"] if ok else COLORS["red"]))

    def _do_arp(self):
        if self._running: return
        self._set_running(True, "清除 ARP 缓存")
        threading.Thread(target=self._thread_arp, daemon=True).start()

    def _thread_arp(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        ok = tool.flush_arp()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status,
            "✅ ARP 缓存已清除" if ok else "❌ 操作失败",
            COLORS["green"] if ok else COLORS["red"]))

    def _do_dhcp(self):
        if self._running: return
        self._set_running(True, "刷新 DHCP")
        threading.Thread(target=self._thread_dhcp, daemon=True).start()

    def _thread_dhcp(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.renew_dhcp()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status, "✅ DHCP 已刷新", COLORS["green"]))

    def _do_backup(self):
        if self._running: return
        self._set_running(True, "备份 IP 配置")
        threading.Thread(target=self._thread_backup, daemon=True).start()

    def _thread_backup(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.backup_static_ip()
        self._static_configs = tool.static_configs
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status, "✅ IP 配置备份完成", COLORS["green"]))

    def _do_restore(self):
        if self._running: return
        if not self._static_configs:
            self._log("⚠ 请先点击「备份IP」按钮")
            self._set_status("⚠ 请先备份IP", COLORS["orange"])
            return
        self._set_running(True, "还原 IP 配置")
        threading.Thread(target=self._thread_restore, daemon=True).start()

    def _thread_restore(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.static_configs = self._static_configs
        tool.restore_static_ip()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status, "✅ IP 配置已还原", COLORS["green"]))

    # ----- 一键重置 -----
    def _do_all_reset(self):
        if self._running: return
        if not messagebox.askyesno("确认", "将执行完整网络重置:\n\n"
                               "1. 备份静态IP配置\n"
                               "2. 重置 Winsock\n"
                               "3. 重置 TCP/IP\n"
                               "4. 清除 DNS/ARP 缓存\n"
                               "5. 刷新 DHCP\n"
                               "6. 恢复静态IP(如有)\n\n"
                               "确定要继续吗?"):
            return
        self._set_running(True, "一键重置全部")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        threading.Thread(target=self._thread_all_reset, daemon=True).start()

    def _thread_all_reset(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.run_full_reset()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, lambda: self.btn_restart.config(state="normal"))

    def _restart(self):
        if messagebox.askyesno("确认重启", "网络重置后需要重启电脑才能生效\n\n确定要立即重启吗?"):
            # 使用 shutdown.exe 替代 Restart-Computer（Win7 兼容）
            try:
                subprocess.run(['shutdown', '/r', '/f', '/t', '5', '/c', '网络重置后系统将重启'])
                self._log("5秒后重启电脑...")
            except Exception as e:
                self._log(f"重启失败: {e}")

    def _quit(self):
        if messagebox.askyesno("确认退出", "确定要退出程序吗?"):
            self.destroy()


# ============================================================
#  诊断面板(Tab 2)
# ============================================================

class DiagnosticPanel(tk.Frame):
    """右侧"网络诊断"标签页"""

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        self._running = False
        self._latest_results = None
        self._build_ui()

    def _build_ui(self):
        # 标题
        header = tk.Frame(self, bg=COLORS["surface"], pady=12)
        header.pack(fill="x")
        tk.Label(header, text="🔍 网络诊断工具", font=(FONT_FAMILY, 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text="一键检测网络状态 · Ping / DNS / 路由追踪",
                 font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        # 按钮行
        ctrl = tk.Frame(self, bg=self["bg"], pady=10, padx=20)
        ctrl.pack(fill="x")

        self.btn_all_diag = styled_btn(ctrl, "🚀 一键完整诊断", self._do_full_diagnostic,
                                        COLORS["green"], font_size=12, bold=True)
        self.btn_all_diag.pack(side="left", padx=(0, 8))

        self.btn_quick = styled_btn(ctrl, "⚡ 快速 Ping", self._do_quick_ping,
                                     COLORS["blue"], font_size=11)
        self.btn_quick.pack(side="left", padx=4)

        self.btn_overview = styled_btn(ctrl, "📋 网络总览", self._do_overview,
                                        COLORS["sky"], font_size=11)
        self.btn_overview.pack(side="left", padx=4)

        self.btn_traceroute = styled_btn(ctrl, "🛤️ Traceroute", self._do_traceroute,
                                          COLORS["purple"], font_size=11)
        self.btn_traceroute.pack(side="left", padx=4)

        self.btn_health = styled_btn(ctrl, "📊 健康报告", self._do_health_report,
                                      COLORS["teal"], font_size=11)
        self.btn_health.pack(side="left", padx=4)

        # 自定义 Ping 输入
        self.custom_target = tk.StringVar(value="www.baidu.com")
        tk.Entry(ctrl, textvariable=self.custom_target, font=(FONT_MONO, 10),
                 bg=COLORS["surface"], fg=COLORS["text"], insertbackground=COLORS["text"],
                 relief="flat", bd=0, width=18).pack(side="left", padx=(10, 4))
        self.btn_custom_ping = styled_btn(ctrl, "Ping", self._do_custom_ping, COLORS["orange"], font_size=11)
        self.btn_custom_ping.pack(side="left")

        # 进度条
        self.diag_progress = ttk.Progressbar(self, mode="determinate",
                                              style="diag.Horizontal.TProgressbar")
        self.diag_progress.pack(fill="x", padx=20, pady=(0, 5))

        self.diag_status = tk.Label(self, text="就绪", font=(FONT_FAMILY, 9),
                                     fg=COLORS["muted"], bg=self["bg"], anchor="w")
        self.diag_status.pack(fill="x", padx=20)

        # 结果区域(Canvas + Scrollbar)
        result_frame = tk.Frame(self, bg=self["bg"])
        result_frame.pack(fill="both", expand=True, padx=20, pady=8)

        canvas = tk.Canvas(result_frame, bg=COLORS["bg2"], highlightthickness=0)
        scrollbar = tk.Scrollbar(result_frame, orient="vertical", command=canvas.yview)
        self.results_inner = tk.Frame(canvas, bg=COLORS["bg2"])
        self.results_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.results_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 样式
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("diag.Horizontal.TProgressbar",
                        troughcolor=COLORS["surface"], background=COLORS["blue"], thickness=6)

        # 欢迎提示
        self._show_hint()

    def _show_hint(self):
        for w in self.results_inner.winfo_children():
            w.destroy()
        hint = tk.Label(self.results_inner,
                        text="点击上方按钮开始诊断\n\n📡 Ping 测试:检测到目标的网络延迟和连通性\n"
                             "🔍 DNS 解析:测试各 DNS 服务器解析是否正常\n"
                             "🛤️ Traceroute:追踪本机到目标的网络路由路径\n"
                             "📋 网络总览:显示当前 IP/网关/DNS 等信息",
                        font=(FONT_FAMILY, 11), fg=COLORS["muted"], bg=COLORS["bg2"],
                        justify="left", padx=20, pady=30)
        hint.pack(fill="both", expand=True)

    def _clear_results(self):
        for w in self.results_inner.winfo_children():
            w.destroy()

    def _set_diag_status(self, msg, color=None):
        if color is None:
            color = COLORS["muted"]
        self.diag_status.config(text=msg, fg=color)

    def _set_running(self, running):
        self._running = running
        state = "disabled" if running else "normal"
        for btn in [self.btn_all_diag, self.btn_quick, self.btn_overview,
                    self.btn_traceroute, self.btn_health]:
            btn.config(state=state)
        if running:
            self.diag_progress.start(8)
        else:
            self.diag_progress.stop()

    # ---- 单个诊断卡片 ----
    def _card(self, parent, title, bg=COLORS["surface"]):
        f = tk.Frame(parent, bg=bg, padx=12, pady=8)
        f.pack(fill="x", pady=2)
        tk.Label(f, text=title, font=(FONT_FAMILY, 10, "bold"),
                 fg=COLORS["text"], bg=bg).pack(anchor="w")
        return f

    def _result_ok(self, parent, text, sub=""):
        color = COLORS["green"]
        icon = "✅"
        tk.Label(parent, text=f"  {icon} {text}", font=(FONT_FAMILY, 10),
                 fg=color, bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)
        if sub:
            tk.Label(parent, text=f"      {sub}", font=(FONT_FAMILY, 9),
                     fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    def _result_fail(self, parent, text, sub=""):
        color = COLORS["red"]
        icon = "❌"
        tk.Label(parent, text=f"  {icon} {text}", font=(FONT_FAMILY, 10),
                 fg=color, bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)
        if sub:
            tk.Label(parent, text=f"      {sub}", font=(FONT_FAMILY, 9),
                     fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    def _result_info(self, parent, text):
        tk.Label(parent, text=f"  {text}", font=(FONT_FAMILY, 9),
                 fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    # ---- 快速 Ping ----
    def _do_quick_ping(self):
        if self._running: return
        self._set_running(True)
        self.diag_progress.configure(mode="indeterminate")
        self.diag_progress.start(8)
        self._set_diag_status("⏳ Ping 测试中...", COLORS["blue"])
        self._clear_results()
        threading.Thread(target=self._thread_quick_ping, daemon=True).start()

    def _thread_quick_ping(self):
        diag = NetworkDiagnostic()
        self.after(0, self._clear_results)
        row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row.pack(fill="x", pady=4, padx=4)
        card = self._card(row, "📡 Ping 连通性测试")

        all_ok = True
        for target, label, color_name in NetworkDiagnostic.PING_TARGETS:
            ok, avg_ms, loss, _ = diag.ping(target)
            # 捕获 avg_ms=None 边界情况
            latency_str = f"{avg_ms}ms" if avg_ms is not None else "<1ms"
            if ok:
                self.after(0, lambda r=card, t=label, m=latency_str, l=loss, tgt=target:
                           self._result_ok(r, f"{t} ({tgt})", f"延迟 {m} · 丢包 {l}%"))
            else:
                all_ok = False
                self.after(0, lambda r=card, t=label, l=loss, tgt=target:
                           self._result_fail(r, f"{t} ({tgt})", f"丢包率 {l}%"))

        self.after(0, lambda: self._set_running(False))
        self.diag_progress.stop()
        self.diag_progress.configure(mode="determinate")
        if all_ok:
            self.after(0, lambda: self._set_diag_status("✅ 所有目标 Ping 正常", COLORS["green"]))
        else:
            self.after(0, lambda: self._set_diag_status("⚠ 部分目标连接异常,可尝试网络重置", COLORS["yellow"]))

    # ---- 网络总览 ----
    def _do_overview(self):
        if self._running: return
        self._set_running(True)
        self._clear_results()
        self._set_diag_status("⏳ 读取网络信息...", COLORS["sky"])
        threading.Thread(target=self._thread_overview, daemon=True).start()

    def _thread_overview(self):
        diag = NetworkDiagnostic()
        overview = diag.get_overview()

        self.after(0, self._clear_results)
        row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row.pack(fill="x", pady=4, padx=4)
        card = self._card(row, "📋 网络状态总览")

        if overview:
            label_map = {
                "状态": ("接口状态", None),
                "描述": ("网卡描述", None),
                "MAC": ("MAC 地址", None),
                "速度": ("连接速度", None),
                "IPv4": ("IPv4 地址", None),
                "网关": ("默认网关", None),
                "DNS": ("DNS 服务器", None),
                "DHCP": ("DHCP 状态", None),
            }
            for k, v in overview:
                if k in label_map:
                    label, _ = label_map[k]
                    self.after(0, lambda r=card, lbl=label, val=v:
                               self._result_info(r, f"{lbl}:{val}"))
        else:
            self.after(0, lambda r=card: self._result_fail(r, "无法获取网络信息"))

        self.after(0, lambda: self._set_running(False))
        self.after(0, lambda: self._set_diag_status("✅ 网络总览完成", COLORS["green"]))

    # ---- Traceroute ----
    def _do_traceroute(self):
        if self._running: return
        target = self.custom_target.get().strip()
        if not target:
            self._set_diag_status("⚠ 请输入目标地址", COLORS["orange"])
            return
        self._set_running(True)
        self._clear_results()
        self._set_diag_status(f"⏳ 追踪路由到 {target}...", COLORS["purple"])
        threading.Thread(target=self._thread_traceroute, args=(target,), daemon=True).start()

    def _thread_traceroute(self, target):
        diag = NetworkDiagnostic()
        output = diag.traceroute(target)

        self.after(0, self._clear_results)
        row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row.pack(fill="both", expand=True, pady=4, padx=4)
        card = self._card(row, f"🛤️ 路由追踪: {target}")

        text_widget = tk.Text(card, font=(FONT_MONO, 9), bg=COLORS["bg2"],
                               fg=COLORS["subtext"], relief="flat", bd=0,
                               height=min(20, max(10, len(output.split('\n')))))
        text_widget.pack(fill="x", padx=8, pady=4)
        text_widget.insert("1.0", output)
        text_widget.configure(state="disabled")

        # 复制按钮
        def copy_trace():
            self.clipboard_clear()
            self.clipboard_append(output)
            self._set_diag_status("✅ 路由追踪结果已复制", COLORS["green"])

        btn_copy = tk.Button(card, text="📋 复制结果", font=(FONT_FAMILY, 9),
                              bg=COLORS["surface"], fg=COLORS["text"],
                              relief="flat", cursor="hand2", command=copy_trace)
        btn_copy.pack(anchor="e", padx=10, pady=4)

        self.after(0, lambda: self._set_running(False))
        self.after(0, lambda: self._set_diag_status(f"✅ 追踪完成", COLORS["green"]))

    # ---- 自定义 Ping ----
    def _do_custom_ping(self):
        if self._running: return
        target = self.custom_target.get().strip()
        if not target:
            self._set_diag_status("⚠ 请输入目标地址", COLORS["orange"])
            return
        self._set_running(True)
        self.diag_progress.configure(mode="indeterminate")
        self.diag_progress.start(8)
        self._clear_results()
        self._set_diag_status(f"⏳ Ping {target}...", COLORS["orange"])
        threading.Thread(target=self._thread_custom_ping, args=(target,), daemon=True).start()

    def _thread_custom_ping(self, target):
        diag = NetworkDiagnostic()
        ok, avg_ms, loss, output = diag.ping(target, count=4)

        self.after(0, self._clear_results)
        row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row.pack(fill="both", expand=True, pady=4, padx=4)
        card = self._card(row, f"📡 Ping: {target}")

        latency_str = f"{avg_ms}ms" if avg_ms is not None else "<1ms"
        if ok:
            self.after(0, lambda r=card, m=latency_str, l=loss:
                       self._result_ok(r, f"连接正常", f"延迟 {m} · 丢包率 {l}%"))
        else:
            self.after(0, lambda r=card, l=loss:
                       self._result_fail(r, f"连接失败", f"丢包率 {l}%"))

        # 原始输出
        raw = tk.Text(card, font=(FONT_MONO, 9), bg=COLORS["bg2"],
                      fg=COLORS["subtext"], relief="flat", bd=0,
                      height=min(12, max(5, len(output.split('\n')))))
        raw.pack(fill="x", padx=8, pady=4)
        raw.insert("1.0", output)
        raw.configure(state="disabled")

        self.after(0, lambda: self._set_running(False))
        self.diag_progress.stop()
        self.diag_progress.configure(mode="determinate")

    # ---- 一键完整诊断 ----
    def _do_full_diagnostic(self):
        if self._running: return

        self._set_running(True)
        self.diag_progress.configure(mode="determinate")
        self.diag_progress["value"] = 0
        self._clear_results()
        self._set_diag_status("⏳ 完整诊断中...", COLORS["green"])
        threading.Thread(target=self._thread_full_diagnostic, daemon=True).start()

    def _thread_full_diagnostic(self):
        diag = NetworkDiagnostic()

        def progress(pct, msg):
            self.after(0, lambda: self.diag_progress.configure(value=pct))
            self.after(0, lambda: self._set_diag_status(f"⏳ {msg}", COLORS["blue"]))

        try:
            results = diag.run_full_diagnostic(progress_callback=progress)
        except Exception as e:
            self.after(0, lambda: self._set_diag_status(f"❌ 诊断失败: {e}", COLORS["red"]))
            self.after(0, lambda: self._set_running(False))
            return

        self._latest_results = results

        self.after(0, self._clear_results)

        # ---- 网络总览卡片 ----
        row0 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row0.pack(fill="x", pady=4, padx=4)
        card0 = self._card(row0, "📋 网络状态总览", bg="#2a2a3e")
        overview = results.get('overview', [])
        if overview:
            for k, v in overview:
                self.after(0, lambda r=card0, kk=k, vv=v: self._result_info(r, f"{kk}:{vv}"))
        else:
            self.after(0, lambda r=card0: self._result_fail(r, "无法获取网络信息"))

        # ---- Ping 卡片 ----
        row1 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row1.pack(fill="x", pady=4, padx=4)
        card1 = self._card(row1, "📡 Ping 连通性测试", bg="#2a2a3e")
        ping_results = results.get('ping', [])
        for p in ping_results:
            color = COLORS[p['color']]
            latency_str = f"{p['avg_ms']}ms" if p['avg_ms'] is not None else "<1ms"
            if p['ok']:
                self.after(0, lambda r=card1, lbl=p['label'], tgt=p['target'], m=latency_str, los=p['loss']:
                           self._result_ok(r, f"{lbl} ({tgt})",
                                          f"延迟 {m} · 丢包 {los}%"))
            else:
                self.after(0, lambda r=card1, lbl=p['label'], tgt=p['target'], los=p['loss']:
                           self._result_fail(r, f"{lbl} ({tgt})",
                                             f"丢包率 {los}%"))

        # ---- DNS 卡片 ----
        row2 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row2.pack(fill="x", pady=4, padx=4)
        card2 = self._card(row2, "🔍 DNS 解析测试", bg="#2a2a3e")
        dns_results = results.get('dns', [])
        for d in dns_results:
            if d['ok']:
                self.after(0, lambda r=card2, lbl=d['label'], dns=d['dns'], ip=d['ip']:
                           self._result_ok(r, f"{lbl} ({dns})",
                                          f"解析成功 → {ip}"))
            else:
                self.after(0, lambda r=card2, lbl=d['label'], dns=d['dns']:
                           self._result_fail(r, f"{lbl} ({dns})", "解析失败"))

        # ---- 结论 ----
        row3 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row3.pack(fill="x", pady=4, padx=4)
        card3 = self._card(row3, "💡 诊断结论", bg="#2a2a3e")

        all_ping_ok = all(p['ok'] for p in ping_results)
        all_dns_ok = all(d['ok'] for d in dns_results)

        if all_ping_ok and all_dns_ok:
            self.after(0, lambda r=card3:
                       self._result_ok(r, "网络状态正常", "所有目标连通,DNS 解析正常"))
        elif all_ping_ok and not all_dns_ok:
            self.after(0, lambda r=card3:
                       self._result_fail(r, "DNS 异常", "Ping 正常但 DNS 解析失败,尝试清除 DNS 缓存"))
        else:
            self.after(0, lambda r=card3:
                       self._result_fail(r, "网络连接异常", "部分目标不可达,建议使用「网络重置」标签修复"))

        self.after(0, lambda: self._set_running(False))
        self.after(0, lambda: self.diag_progress.configure(value=100))
        self.after(0, lambda: self._set_diag_status("✅ 完整诊断完成", COLORS["green"]))

    # ---- 健康报告 ----
    def _do_health_report(self):
        if self._running:
            return
        self._set_running(True)
        self.after(0, self._clear_results)
        self._set_diag_status("⏳ 生成健康报告...", COLORS["teal"])
        threading.Thread(target=self._thread_health_report, daemon=True).start()

    def _thread_health_report(self):
        diag = NetworkDiagnostic()
        try:
            results = diag.run_full_diagnostic()
        except Exception as e:
            self.after(0, lambda: self._set_diag_status(f"❌ 健康报告生成失败: {e}", COLORS["red"]))
            self.after(0, lambda: self._set_running(False))
            return

        self._latest_results = results

        ping_results = results.get('ping', [])
        dns_results = results.get('dns', [])
        overview = results.get('overview', [])

        # 计算评分
        # 连通性 (40分): 5个目标,每个8分
        ping_ok = sum(1 for p in ping_results if p['ok'])
        conn_score = ping_ok * 8

        # DNS可用性 (30分): 3个DNS,每个10分
        dns_ok = sum(1 for d in dns_results if d['ok'])
        dns_score = dns_ok * 10

        # 网络配置完整性 (30分)
        cfg_score = 0
        has_ip = has_gw = has_dns = False
        for k, v in overview:
            if 'IP' in k: has_ip = True
            if '网关' in k: has_gw = True
            if 'DNS' in k: has_dns = True
        if has_ip: cfg_score += 10
        if has_gw: cfg_score += 10
        if has_dns: cfg_score += 10

        total = conn_score + dns_score + cfg_score

        # 等级
        if total >= 90:
            grade, grade_color = "优秀", COLORS["green"]
        elif total >= 70:
            grade, grade_color = "良好", COLORS["blue"]
        elif total >= 50:
            grade, grade_color = "一般", COLORS["yellow"]
        else:
            grade, grade_color = "较差", COLORS["red"]

        # 平均延迟
        ok_pings = [p for p in ping_results if p['ok']]
        avg_latency = round(sum(p['avg_ms'] for p in ok_pings) / len(ok_pings), 1) if ok_pings else 0

        # 丢包率
        avg_loss = round(sum(p['loss'] for p in ping_results) / len(ping_results), 1) if ping_results else 100

        # 渲染卡片
        def rc(parent, icon, title, value, sub=None, color=None):
            card = self._card(parent, icon + " " + title, bg="#2a2a3e")
            if color:
                vc = color
            else:
                try:
                    num = float(value.rstrip('%'))
                    vc = COLORS["green"] if num >= 80 else COLORS["yellow"] if num >= 50 else COLORS["red"]
                except (ValueError, TypeError):
                    vc = COLORS["subtext"]
            lbl = tk.Label(card, text=value, font=(FONT_FAMILY, 16, "bold"),
                           fg=vc, bg="#2a2a3e")
            lbl.pack(pady=(4, 0))
            if sub:
                tk.Label(card, text=sub, font=(FONT_FAMILY, 8),
                         fg=COLORS["muted"], bg="#2a2a3e").pack()

        # 顶部:总分 + 等级
        top = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        top.pack(fill="x", pady=4, padx=4)
        score_card = tk.Frame(top, bg="#2a2a3e")
        score_card.pack(side="left", fill="both", expand=True, padx=(0, 4))
        tk.Label(score_card, text="网络健康评分", font=(FONT_FAMILY, 10),
                 fg=COLORS["text"], bg="#2a2a3e").pack(pady=(8, 0))
        score_num = tk.Label(score_card, text=f"{total}",
                             font=(FONT_FAMILY, 36, "bold"),
                             fg=grade_color, bg="#2a2a3e")
        score_num.pack()
        tk.Label(score_card, text=f"{grade}", font=(FONT_FAMILY, 11, "bold"),
                 fg=grade_color, bg="#2a2a3e").pack(pady=(0, 8))

        # 等级说明
        advice_card = tk.Frame(top, bg="#2a2a3e")
        advice_card.pack(side="right", fill="both", expand=True, padx=(4, 0))
        tk.Label(advice_card, text="💡 健康建议", font=(FONT_FAMILY, 10, "bold"),
                 fg=COLORS["text"], bg="#2a2a3e").pack(anchor="w", padx=10, pady=(8, 2))
        if total >= 90:
            advice_text = "网络状态优秀,所有检测通过,继续保持。"
        elif total >= 70:
            advice_text = "网络状态良好,个别指标待优化,可尝试 DNS 一键切换。"
        elif total >= 50:
            advice_text = "网络状态一般,建议执行「网络重置」修复潜在问题。"
        else:
            advice_text = "网络状态较差,建议立即执行「一键重置全部」修复网络。"
        tk.Label(advice_card, text=advice_text, font=(FONT_FAMILY, 9),
                 fg=COLORS["subtext"], bg="#2a2a3e", wraplength=200,
                 justify="left", anchor="w").pack(anchor="w", padx=10, pady=(0, 8))

        # 维度卡片行
        row1 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row1.pack(fill="x", pady=4, padx=4)
        conn_pct = f"{round(ping_ok / max(len(ping_results), 1) * 100)}%"
        dns_pct = f"{round(dns_ok / max(len(dns_results), 1) * 100)}%"
        cfg_pct = f"{round(cfg_score / 30 * 100)}%"
        rc(row1, "📡", "连通性", conn_pct, f"{ping_ok}/{len(ping_results)} 目标可达")
        rc(row1, "🔍", "DNS可用", dns_pct, f"{dns_ok}/{len(dns_results)} DNS正常")
        rc(row1, "🔧", "配置完整", cfg_pct, "IP/网关/DNS状态")

        # 性能行
        row2 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row2.pack(fill="x", pady=4, padx=4)
        rc(row2, "⚡", "平均延迟", f"{avg_latency}ms", "5个目标平均",
           COLORS["green"] if avg_latency < 100 else COLORS["yellow"] if avg_latency < 300 else COLORS["red"])
        rc(row2, "📉", "平均丢包", f"{avg_loss}%", "5个目标平均",
           COLORS["green"] if avg_loss == 0 else COLORS["yellow"] if avg_loss < 20 else COLORS["red"])
        # DNS服务器
        dns_svr = next((v for k, v in overview if 'DNS' in k), "-")
        rc(row2, "🌐", "当前DNS", dns_svr[:20] if len(dns_svr) > 20 else dns_svr, "当前使用")

        self.after(0, lambda: self._set_running(False))
        self.after(0, lambda: self.diag_progress.configure(value=100))
        self.after(0, lambda: self._set_diag_status(
            f"📊 健康报告: {total}分 {grade} | {advice_text[:20]}...",
            grade_color))


# ============================================================
#  主窗口
# ============================================================

class ProxyPanel(tk.Frame):
    """第三个标签页:代理诊断与修复"""

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        self._running = False
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=COLORS["surface"], pady=12)
        header.pack(fill="x")
        tk.Label(header, text="🛡️ 代理诊断与修复", font=(FONT_FAMILY, 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text="检测系统代理 / Clash 端口与 DNS · 一键修复外网连不上",
                 font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        ctrl = tk.Frame(self, bg=self["bg"], pady=10, padx=20)
        ctrl.pack(fill="x")
        self.btn_diag = styled_btn(ctrl, "🔍 诊断代理", self._do_diagnose,
                                   COLORS["green"], font_size=12, bold=True)
        self.btn_diag.pack(side="left", padx=(0, 8))
        self.btn_repair = styled_btn(ctrl, "🔧 一键修复", self._do_repair,
                                     COLORS["orange"], font_size=12, bold=True)
        self.btn_repair.pack(side="left", padx=4)

        self.proxy_progress = ttk.Progressbar(self, mode="indeterminate")
        self.proxy_progress.pack(fill="x", padx=20, pady=(0, 5))
        self.proxy_status = tk.Label(self, text="就绪", font=(FONT_FAMILY, 9),
                                     fg=COLORS["muted"], bg=self["bg"], anchor="w")
        self.proxy_status.pack(fill="x", padx=20)

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("HP.Horizontal.TProgressbar",
                        troughcolor=COLORS["surface"], background=COLORS["orange"], thickness=6)

        result_frame = tk.Frame(self, bg=self["bg"])
        result_frame.pack(fill="both", expand=True, padx=20, pady=8)
        canvas = tk.Canvas(result_frame, bg=COLORS["bg2"], highlightthickness=0)
        scrollbar = tk.Scrollbar(result_frame, orient="vertical", command=canvas.yview)
        self.results_inner = tk.Frame(canvas, bg=COLORS["bg2"])
        self.results_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.results_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._show_hint()

    def _show_hint(self):
        for w in self.results_inner.winfo_children():
            w.destroy()
        tk.Label(self.results_inner,
                 text="点击「诊断代理」检测以下问题:\n\n"
                      "🔌 系统代理是否指向已宕机的端口(外网会全部失败)\n"
                      "🛡️ 是否发现正在运行的 Clash / mihomo 代理核心\n"
                      "🌐 Clash 的 dns.enable 是否被关掉(导致域名解析超时)\n\n"
                      "发现问题后点「一键修复」自动处理。",
                 font=(FONT_FAMILY, 11), fg=COLORS["muted"], bg=COLORS["bg2"],
                 justify="left", padx=20, pady=30).pack(fill="both", expand=True)

    def _clear_results(self):
        for w in self.results_inner.winfo_children():
            w.destroy()

    def _set_status(self, msg, color=None):
        self.proxy_status.config(text=msg, fg=color or COLORS["muted"])

    def _set_running(self, running):
        self._running = running
        state = "disabled" if running else "normal"
        self.btn_diag.config(state=state)
        self.btn_repair.config(state=state)
        if running:
            self.proxy_progress.start(8)
        else:
            self.proxy_progress.stop()

    def _card(self, parent, title, bg="#2a2a3e"):
        f = tk.Frame(parent, bg=bg, padx=12, pady=8)
        f.pack(fill="x", pady=2)
        tk.Label(f, text=title, font=(FONT_FAMILY, 10, "bold"),
                 fg=COLORS["text"], bg=bg).pack(anchor="w")
        return f

    def _result_ok(self, parent, text, sub=""):
        tk.Label(parent, text=f"  ✅ {text}", font=(FONT_FAMILY, 10),
                 fg=COLORS["green"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)
        if sub:
            tk.Label(parent, text=f"      {sub}", font=(FONT_FAMILY, 9),
                     fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    def _result_fail(self, parent, text, sub=""):
        tk.Label(parent, text=f"  ❌ {text}", font=(FONT_FAMILY, 10),
                 fg=COLORS["red"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)
        if sub:
            tk.Label(parent, text=f"      {sub}", font=(FONT_FAMILY, 9),
                     fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    def _result_info(self, parent, text):
        tk.Label(parent, text=f"  {text}", font=(FONT_FAMILY, 9),
                 fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    # ---- 诊断 ----
    def _do_diagnose(self):
        if self._running:
            return
        self._set_running(True)
        self._clear_results()
        self._set_status("⏳ 诊断代理中...", COLORS["green"])
        threading.Thread(target=self._thread_diagnose, daemon=True).start()

    def _thread_diagnose(self):
        res = ProxyRepairTool().diagnose()
        self.after(0, self._clear_results)

        row = tk.Frame(self.results_inner, bg=COLORS["bg2"]); row.pack(fill="x", pady=4, padx=4)
        card = self._card(row, "🔌 系统代理", bg="#2a2a3e")
        if res['proxy_enabled']:
            srv = res['proxy_server'] or "(空)"
        else:
            srv = None
        if res['proxy_enabled']:
            self.after(0, lambda r=card, s=srv: self._result_info(r, f"已启用,地址: {s}"))
        else:
            self.after(0, lambda r=card: self._result_info(r, "未启用系统代理"))
        if res['proxy_ports']:
            if res['proxy_alive']:
                self.after(0, lambda r=card: self._result_ok(r, "代理端口可连通", "外网出口正常"))
            else:
                self.after(0, lambda r=card: self._result_fail(r, "代理端口无服务监听", "外网会全部失败!"))

        row2 = tk.Frame(self.results_inner, bg=COLORS["bg2"]); row2.pack(fill="x", pady=4, padx=4)
        card2 = self._card(row2, "🛡️ 代理核心", bg="#2a2a3e")
        core = res['clash_core']
        if core:
            pp = res.get('clash_proxy_port')
            if pp:
                self.after(0, lambda r=card2, c=core, p=pp:
                           self._result_ok(r, f"发现 {c['process']} (代理端口 {p})"))
            else:
                self.after(0, lambda r=card2, c=core:
                           self._result_ok(r, f"发现 {c['process']} 在端口 {c['port']} 运行"))
        else:
            self.after(0, lambda r=card2: self._result_info(r, "未发现 Clash/mihomo 核心"))

        row3 = tk.Frame(self.results_inner, bg=COLORS["bg2"]); row3.pack(fill="x", pady=4, padx=4)
        card3 = self._card(row3, "🌐 Clash DNS", bg="#2a2a3e")
        dns = res['clash_dns']
        if dns is True:
            self.after(0, lambda r=card3: self._result_ok(r, "dns.enable = true", "DNS 模块正常"))
        elif dns is False:
            self.after(0, lambda r=card3: self._result_fail(r, "dns.enable = false", "fake-ip 模式下会导致解析超时!"))
        else:
            self.after(0, lambda r=card3: self._result_info(r, "未找到 Clash 配置,无法检测"))

        row4 = tk.Frame(self.results_inner, bg=COLORS["bg2"]); row4.pack(fill="x", pady=4, padx=4)
        card4 = self._card(row4, "💡 诊断结论", bg="#2a2a3e")
        if res['issues']:
            for issue in res['issues']:
                self.after(0, lambda r=card4, t=issue: self._result_fail(r, t))
            self.after(0, lambda r=card4: self._result_info(r, "建议点击「一键修复」自动处理"))
            self.after(0, lambda: self._set_status("⚠ 发现代理问题,可一键修复", COLORS["yellow"]))
        else:
            self.after(0, lambda r=card4: self._result_ok(r, "未发现明显代理问题"))
            self.after(0, lambda: self._set_status("✅ 代理诊断正常", COLORS["green"]))

        self.after(0, lambda: self._set_running(False))

    # ---- 修复 ----
    def _do_repair(self):
        if self._running:
            return
        self._set_running(True)
        self._clear_results()
        self._set_status("⏳ 正在修复...", COLORS["orange"])
        threading.Thread(target=self._thread_repair, daemon=True).start()

    def _thread_repair(self):
        tool = ProxyRepairTool(log_callback=self._safe_log)
        ok, actions = tool.repair()
        self.after(0, self._clear_results)
        row = tk.Frame(self.results_inner, bg=COLORS["bg2"]); row.pack(fill="x", pady=4, padx=4)
        card = self._card(row, "🔧 修复结果", bg="#2a2a3e")
        if not actions:
            self.after(0, lambda r=card: self._result_info(r, "无需修复,或请先点「诊断代理」"))
        for a in actions:
            self.after(0, lambda r=card, t=a: self._result_info(r, "• " + t))
        if ok:
            self.after(0, lambda r=card: self._result_ok(r, "修复完成!", "建议重开浏览器/相关程序使代理生效"))
            self.after(0, lambda: self._set_status("✅ 代理修复完成", COLORS["green"]))
        else:
            self.after(0, lambda r=card: self._result_fail(r, "部分修复失败", "请查看上方信息/手动处理"))
            self.after(0, lambda: self._set_status("⚠ 修复未完全成功", COLORS["yellow"]))
        self.after(0, lambda: self._set_running(False))

    def _safe_log(self, msg, color=None):
        self.after(0, lambda m=msg: self._set_status("修复中: " + m[:60], COLORS["orange"]))


class App(tk.Tk):
    def __init__(self, start_tab=None):
        super().__init__()

        # 检测系统字体（Win7 兼容）
        _init_font()

        # 关闭 PyInstaller 启动画面
        try:
            import pyi_splash
            pyi_splash.close()
        except Exception:
            pass

        self.title("网络工具箱 v3.2 ✨")
        self.geometry("780x640")
        self.minsize(720, 580)
        self.configure(bg=COLORS["bg"])

        # 先让窗口显示出来,再做后续初始化
        self.update_idletasks()

        # ===== 母亲节问候 =====
        try:
            import datetime
            today = datetime.datetime.now()
            mother_day_msg = (
                "🌷 母亲节快乐!🌷\n\n"
                "祝天下所有妈妈:\n"
                "健康平安,笑口常开!\n\n"
                "❤️ 感谢您一直以来的付出 ❤️\n\n"
                "-- 您的网络工具箱 v3.2"
            )
            # 母亲节是每年5月第二个周日,2026年是5月10日
            if today.month == 5 and today.day in [9, 10]:
                messagebox.showinfo("🌸 母亲节快乐 🌸", mother_day_msg)
        except Exception:
            pass  # 静默忽略任何节日弹窗错误

        self._build_ui()

        # 若指定了启动标签页，则直接切换过去
        if start_tab and start_tab in self.tab_buttons:
            self._switch_tab(start_tab)

    def _build_ui(self):
        # 顶部标题栏
        topbar = tk.Frame(self, bg=COLORS["surface"], pady=8, padx=15)
        topbar.pack(fill="x")
        tk.Label(topbar, text="🛠️  网络工具箱",
                 font=(FONT_FAMILY, 14, "bold"), fg=COLORS["text"],
                 bg=COLORS["surface"]).pack(side="left")
        tk.Label(topbar, text="v3.2  ·  重置 + 诊断  ·  🌸 母亲节快乐!",
                 font=(FONT_FAMILY, 9), fg=COLORS["pink"],
                 bg=COLORS["surface"]).pack(side="left", padx=10)

        # Tab 控制
        tabbar = tk.Frame(self, bg=COLORS["surface2"], padx=15, pady=0)
        tabbar.pack(fill="x")
        self.tab_buttons = {}
        tabs = [
            ("reset",       "🔄 网络重置"),
            ("diagnostic",  "🔍 网络诊断"),
            ("proxy",       "🛡️ 代理修复"),
        ]
        tab_btn_frame = tk.Frame(tabbar, bg=COLORS["surface2"])
        tab_btn_frame.pack(side="left")

        self._active_tab = "reset"
        for tid, label in tabs:
            btn = tk.Button(tab_btn_frame, text=label,
                            font=(FONT_FAMILY, 10, "bold"),
                            bg=COLORS["surface2"], fg=COLORS["muted"],
                            relief="flat", cursor="hand2", padx=15, pady=6,
                            command=lambda t=tid: self._switch_tab(t))
            btn.pack(side="left", padx=(0, 2))
            self.tab_buttons[tid] = btn

        self._indicator = tk.Frame(tabbar, bg=COLORS["green"], height=2)
        self._indicator.pack(fill="x", padx=15)
        self._indicator.pack_forget()  # hide, use button style instead

        self.tab_buttons[self._active_tab].config(
            bg=COLORS["surface"], fg=COLORS["green"])

        # 内容区
        self.content = tk.Frame(self, bg=COLORS["bg"])
        self.content.pack(fill="both", expand=True)

        self.reset_panel = ResetPanel(self.content)
        self.reset_panel.pack(fill="both", expand=True)

        self.diag_panel = DiagnosticPanel(self.content)
        self.diag_panel.pack(fill="both", expand=True)
        self.diag_panel.forget()  # hidden by default

        self.proxy_panel = ProxyPanel(self.content)
        self.proxy_panel.pack(fill="both", expand=True)
        self.proxy_panel.forget()  # hidden by default

        # 底部版本信息
        footer = tk.Frame(self, bg=COLORS["surface"], pady=4)
        footer.pack(fill="x")
        tk.Label(footer, text="Network Reset Tool v3.2  ·  michaelqiu  ·  🌷 5月10日 母亲节",
                 font=(FONT_FAMILY, 8), fg=COLORS["muted"], bg=COLORS["surface"]).pack(side="right", padx=10)

    def _switch_tab(self, tid):
        if tid == self._active_tab:
            return
        # 更新按钮样式
        self.tab_buttons[self._active_tab].config(bg=COLORS["surface2"], fg=COLORS["muted"])
        self.tab_buttons[tid].config(bg=COLORS["surface"], fg=COLORS["green"])

        # 切换面板
        for p in (self.reset_panel, self.diag_panel, self.proxy_panel):
            p.forget()
        {
            "reset": self.reset_panel,
            "diagnostic": self.diag_panel,
            "proxy": self.proxy_panel,
        }[tid].pack(fill="both", expand=True)

        self._active_tab = tid


# 启动时自动检测系统可用字体（Win7 兼容）
FONT_FAMILY = None  # will be set after Tk root init
FONT_MONO = "Consolas"


def _init_font():
    """在 Tk 根窗口创建后调用，检测系统字体"""
    global FONT_FAMILY, FONT_MONO
    import tkinter.font as tkfont
    try:
        root = tk.Tk()
        root.withdraw()
        available = list(tkfont.families(root))
        root.destroy()
    except Exception:
        available = []
    if not available:
        FONT_FAMILY = "Tahoma"
        return
    # 中文字体优选
    for name in ["微软雅黑", "Microsoft YaHei UI", "Microsoft YaHei",
                 "Segoe UI", "Tahoma", "Microsoft Sans Serif", "Arial"]:
        if name in available:
            FONT_FAMILY = name
            break
    else:
        FONT_FAMILY = "Tahoma"
    # 等宽字体
    for name in ["Consolas", "Lucida Console", "Courier New"]:
        if name in available:
            FONT_MONO = name
            break


if __name__ == "__main__":
    # 单例检测
    if not _am_first:
        import tkinter as tk_temp
        from tkinter import messagebox as mb_temp
        root_temp = tk_temp.Tk()
        root_temp.withdraw()
        root_temp.attributes("-topmost", True)
        mb_temp.showwarning("提示", "程序已在运行!\n请先关闭旧窗口。", parent=root_temp)
        root_temp.destroy()
        sys.exit(1)

    try:
        # 解析启动参数（--tab <reset|diagnostic|proxy>）
        start_tab = None
        if "--tab" in sys.argv:
            try:
                start_tab = sys.argv[sys.argv.index("--tab") + 1]
            except IndexError:
                start_tab = None

        app = App(start_tab=start_tab)
        app.protocol("WM_DELETE_WINDOW", lambda: (_release_singleton(), app.destroy()))
        app.mainloop()
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        # 写入日志文件
        log_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'crash.log')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(f"Crash at {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(error_msg)
        # 如果是打包环境,显示错误弹窗
        try:
            import tkinter as tk_err
            from tkinter import messagebox as mb_err
            root_err = tk_err.Tk()
            root_err.withdraw()
            mb_err.showerror("程序错误", f"{error_msg[:500]}\n\n日志已保存: {log_path}", parent=root_err)
            root_err.destroy()
        except Exception:
            pass
        sys.exit(1)
