# -*- coding: utf-8 -*-
"""核心引擎: 网络重置/诊断/代理修复/监控/测速/WiFi 信息 (纯逻辑, 不直接构造 Tk 控件)。"""
import os
import sys
import json
import subprocess
import threading
import time
import re
import shlex
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import ctypes
import functools
import platform
import html as _html
import shutil
from datetime import datetime
import socket
import urllib.request
import urllib.error

from network_toolbox.i18n import tr, tr_f
from network_toolbox.plugins import run_diagnostics  # F13: 插件式诊断项
from network_toolbox._shared import (
    ADAPTER_AUTO,
    APP_AUTHOR,
    APP_NAME,
    APP_VERSION,
    APP_VERSION_SHORT,
    COLORS,
    DNS_PRESETS,
    FONT_FAMILY,
    FONT_MONO,
    IS_LINUX,
    IS_MAC,
    IS_WINDOWS,
    _HOSTNAME_RE,
    _IPV4_RE,
    _SINGLETON_PORT,
    _SINGLETON_SOCKET,
    _acquire_singleton,
    _am_first,
    _app_data_dir,
    _apply_proxy_setting,
    _init_font,
    _is_mothers_day,
    _is_win7_or_older,
    _mac_primary_service,
    _release_singleton,
    decode_output,
    http_user_agent,
    is_admin,
    is_valid_target,
    make_btn_style,
    styled_btn,
    ui_sync,
)

import network_toolbox._shared as _shared  # noqa: F401 (live patch point)


def run_cmd_capture(args, timeout=15):
    """静默执行命令并捕获输出（参数列表, 不经 shell, 防注入）。

    返回 (returncode, stdout, stderr)；解码沿用 decode_output 的链路。
    """
    try:
        proc = subprocess.run(list(args), capture_output=True, timeout=timeout)
        return proc.returncode, decode_output(proc.stdout), decode_output(proc.stderr)
    except Exception as e:
        return -1, "", str(e)


class NetworkResetTool:
    # 统一解码入口（原先 ResetPanel 误调用 self._decode_output 却未定义 → AttributeError）
    _decode_output = staticmethod(decode_output)

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

    def list_adapters(self):
        """列出本机网卡，供下拉框选择。

        返回: [{'name', 'desc', 'ip', 'gw', 'up'}, ...]
              gw=True 表示该网卡有默认网关（通常是真正的出口网卡）。
        排序: 有网关的排前面，便于用户一眼看到该选哪个。
        失败时返回空列表（UI 会退回自动检测）。
        """
        items = []
        if IS_MAC:
            try:
                r = subprocess.run(['networksetup', '-listallnetworkservices'],
                                   capture_output=True, timeout=8)
                for line in decode_output(r.stdout).split('\n'):
                    line = line.strip()
                    # 首行是说明，带 * 的是已禁用服务
                    if line and not line.startswith('*') and 'network service' not in line.lower():
                        items.append({'name': line, 'desc': '', 'ip': '', 'gw': False, 'up': True})
            except Exception:
                pass
            return items

        if IS_LINUX:
            try:
                r = subprocess.run(['ip', '-o', '-4', 'addr', 'show'],
                                   capture_output=True, timeout=8)
                for line in decode_output(r.stdout).split('\n'):
                    parts = line.split()
                    if len(parts) >= 4:
                        items.append({'name': parts[1], 'desc': '', 'ip': parts[3].split('/')[0],
                                      'gw': False, 'up': True})
            except Exception:
                pass
            return items

        # ---- Windows ----
        # Win8+ 优先 Get-NetAdapter，Win7 / 失败时退回 WMI
        ps_modern = '''
$out = @()
foreach ($a in (Get-NetAdapter -ErrorAction SilentlyContinue)) {
    $c = Get-NetIPConfiguration -InterfaceIndex $a.ifIndex -ErrorAction SilentlyContinue
    $ip = if ($c -and $c.IPv4Address) { ($c.IPv4Address.IPAddress -join ',') } else { '' }
    $gw = if ($c -and $c.IPv4DefaultGateway) { '1' } else { '0' }
    $up = if ($a.Status -eq 'Up') { '1' } else { '0' }
    $out += ("{0}`t{1}`t{2}`t{3}`t{4}" -f $a.Name, $a.InterfaceDescription, $ip, $gw, $up)
}
Write-Output ($out -join "`n")
'''
        raw = ''
        try:
            if not _is_win7_or_older():
                r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_modern],
                                   capture_output=True, timeout=15)
                raw = decode_output(r.stdout)
        except Exception:
            raw = ''

        if not raw.strip():
            ps_wmi = '''
$out = @()
foreach ($c in (Get-WmiObject Win32_NetworkAdapterConfiguration -ErrorAction SilentlyContinue | Where-Object { $_.IPEnabled -eq $true })) {
    $nic = Get-WmiObject Win32_NetworkAdapter -ErrorAction SilentlyContinue | Where-Object { $_.GUID -eq $c.SettingID } | Select-Object -First 1
    $name = if ($nic) { $nic.NetConnectionID } else { $c.Description }
    $ip = ($c.IPAddress | Where-Object { $_ -match '\\.' }) -join ','
    $gw = if ($c.DefaultIPGateway) { '1' } else { '0' }
    $out += ("{0}`t{1}`t{2}`t{3}`t1" -f $name, $c.Description, $ip, $gw)
}
Write-Output ($out -join "`n")
'''
            try:
                r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_wmi],
                                   capture_output=True, timeout=15)
                raw = decode_output(r.stdout)
            except Exception:
                raw = ''

        for line in raw.split('\n'):
            line = line.strip()
            if not line or '\t' not in line:
                continue
            parts = line.split('\t')
            parts += [''] * (5 - len(parts))
            name, desc, ip, gw, up = parts[:5]
            if not name:
                continue
            items.append({'name': name, 'desc': desc, 'ip': ip,
                          'gw': gw.strip() == '1', 'up': up.strip() != '0'})

        items.sort(key=lambda x: (not x['gw'], not x['up'], x['name']))
        return items

    # ============================================================
    #  配置快照与回滚 (F2)
    # ============================================================
    @staticmethod
    def snapshot_dir():
        d = os.path.join(_app_data_dir(), "snapshots")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d

    def get_all_adapter_configs(self):
        """一次性取回所有网卡的 IP/掩码/网关/DNS。

        get_current_dns() 只返回"出口网卡"的 DNS，做快照必须逐网卡采集，
        否则回滚时只会恢复一块网卡。
        返回: {网卡名: {'ip', 'mask', 'gw', 'dns': [...], 'mode': 'dhcp'|'static'}}
        """
        out = {}
        if IS_MAC:
            try:
                name = _mac_primary_service()
                if name:
                    dns, mode = self.get_current_dns(name)
                    out[name] = {'ip': '', 'mask': '', 'gw': '', 'dns': dns, 'mode': mode}
            except Exception:
                pass
            return out

        ps = '''
$out = @()
foreach ($c in (Get-WmiObject Win32_NetworkAdapterConfiguration -ErrorAction SilentlyContinue | Where-Object { $_.IPEnabled -eq $true })) {
    $nic = Get-WmiObject Win32_NetworkAdapter -ErrorAction SilentlyContinue | Where-Object { $_.GUID -eq $c.SettingID } | Select-Object -First 1
    $name = if ($nic) { $nic.NetConnectionID } else { '' }
    if (-not $name) { continue }
    $ip = (($c.IPAddress) | Where-Object { $_ -match '\\.' }) -join ','
    $mask = (($c.IPSubnet) | Where-Object { $_ -match '\\.' }) -join ','
    $gw = ($c.DefaultIPGateway -join ',')
    $dns = ($c.DNSServerSearchOrder -join ',')
    $mode = if ($c.DHCPEnabled) { 'dhcp' } else { 'static' }
    $out += ("{0}`t{1}`t{2}`t{3}`t{4}`t{5}" -f $name, $ip, $mask, $gw, $dns, $mode)
}
Write-Output ($out -join "`n")
'''
        try:
            r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                               capture_output=True, timeout=20)
            raw = decode_output(r.stdout)
        except Exception as e:
            self.log(f"  ⚠ 读取网卡配置失败: {e}")
            return out

        for line in raw.split('\n'):
            line = line.strip()
            if '\t' not in line:
                continue
            parts = line.split('\t')
            parts += [''] * (6 - len(parts))
            name, ip, mask, gw, dns, mode = parts[:6]
            if not name:
                continue
            out[name] = {
                'ip': ip, 'mask': mask, 'gw': gw,
                'dns': [d.strip() for d in dns.split(',') if d.strip()],
                'mode': (mode.strip() or 'unknown').lower(),
            }
        return out

    def take_snapshot(self):
        """采集当前网络配置快照（重置操作前调用）。返回快照 dict。"""
        snap = {
            'schema': 1,
            'app': APP_VERSION,
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'adapters': {},
            'proxy': None,
        }
        try:
            snap['adapters'] = self.get_all_adapter_configs()
        except Exception as e:
            self.log(f"  ⚠ 快照: 网卡采集失败 {e}")

        try:
            enabled, server = ProxyRepairTool().get_system_proxy()
            snap['proxy'] = {'enabled': bool(enabled), 'server': server or ''}
        except Exception:
            snap['proxy'] = None

        return snap

    @staticmethod
    def save_snapshot(snap):
        """把快照写入 %LOCALAPPDATA%\\NetworkResetTool\\snapshots\\，返回文件路径。"""
        d = NetworkResetTool.snapshot_dir()
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(d, f'snapshot_{ts}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        return path

    @staticmethod
    def list_snapshots(limit=20):
        """按时间倒序列出已有快照，返回 [(path, time_str, adapter_count), ...]"""
        d = NetworkResetTool.snapshot_dir()
        items = []
        try:
            for fn in os.listdir(d):
                if not (fn.startswith('snapshot_') and fn.endswith('.json')):
                    continue
                p = os.path.join(d, fn)
                try:
                    with open(p, encoding='utf-8') as f:
                        data = json.load(f)
                    items.append((p, data.get('time', fn), len(data.get('adapters') or {})))
                except Exception:
                    continue
        except Exception:
            return []
        items.sort(key=lambda x: x[0], reverse=True)
        return items[:limit]

    def rollback_snapshot(self, snap, restore_ip=False):
        """按快照恢复网络配置。

        restore_ip=True 时才会恢复静态 IP/掩码/网关（风险较高，默认关闭）。
        返回 (成功项数, 总项数)。
        """
        done = total = 0

        adapters = (snap or {}).get('adapters') or {}
        for name, cfg in adapters.items():
            total += 1
            dns_list = cfg.get('dns') or []
            mode = (cfg.get('mode') or '').lower()
            try:
                if dns_list and mode == 'static':
                    ok = self.set_dns(name, dns_list[0],
                                      dns_list[1] if len(dns_list) > 1 else None)
                elif dns_list:
                    # dhcp 模式下也会记录实际在用的 DNS，一并写回更稳妥
                    ok = self.set_dns(name, dns_list[0],
                                      dns_list[1] if len(dns_list) > 1 else None)
                else:
                    ok = self.set_dhcp_dns(name)
                if ok:
                    done += 1
                    self.log(f"  ✓ {name} DNS 已恢复: {', '.join(dns_list) or 'DHCP'}")
                else:
                    self.log(f"  ✗ {name} DNS 恢复失败")
            except Exception as e:
                self.log(f"  ✗ {name} DNS 恢复异常: {e}")

        if restore_ip and IS_WINDOWS:
            for name, cfg in adapters.items():
                ip = (cfg.get('ip') or '').split(',')[0]
                mask = (cfg.get('mask') or '').split(',')[0]
                gw = (cfg.get('gw') or '').split(',')[0]
                if not (ip and mask):
                    continue
                # 快照里 mode=dhcp 的网卡不要写成静态，否则会把自动获取改成固定 IP
                if (cfg.get('mode') or '').lower() == 'dhcp':
                    continue
                total += 1
                cmd = f'netsh interface ip set address "{name}" static {ip} {mask}' + (f' {gw} 1' if gw else '')
                if self.run_cmd(cmd, timeout=15):
                    done += 1
                    self.log(f"  ✓ {name} IP 已恢复: {ip}")
                else:
                    self.log(f"  ✗ {name} IP 恢复失败")

        proxy = (snap or {}).get('proxy')
        if proxy:
            total += 1
            try:
                server = proxy.get('server') or ''
                enable = bool(proxy.get('enabled'))
                ok = _shared._apply_proxy_setting(enable, server)
                if ok:
                    done += 1
                    self.log(f"  ✓ 系统代理已恢复: {'启用 ' + server if enable else '关闭'}")
                else:
                    self.log(tr("  ✗ 系统代理恢复失败"))
            except Exception as e:
                self.log(f"  ✗ 系统代理恢复异常: {e}")

        return done, total

    def backup_static_ip(self):
        if not IS_WINDOWS:
            return
        self.log(tr("[备份] 静态IP配置..."))
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
                self.log(tr("  ✓ 无静态IP配置"))
        except Exception as e:
            self.log(f"  备份失败: {e}")

    def reset_winsock(self):
        if not IS_WINDOWS:
            self.log(tr("  ⚠ 重置 Winsock 仅支持 Windows"))
            return False
        self.log(tr("[操作] 重置 Winsock..."))
        if self.run_cmd('netsh winsock reset'):
            self.log(tr("  ✓ Winsock 重置完成"))
            return True
        else:
            self.log(tr("  ✗ Winsock 重置失败"))
            return False

    def reset_tcpip(self):
        if not IS_WINDOWS:
            self.log(tr("  ⚠ 重置 TCP/IP 仅支持 Windows"))
            return False
        self.log(tr("[操作] 重置 TCP/IP 协议栈..."))
        ok4 = self.run_cmd('netsh int ip reset', timeout=30)
        ok6 = self.run_cmd('netsh int ipv6 reset', timeout=30)
        ok = ok4 and ok6
        if ok:
            self.log(tr("  ✓ TCP/IP 重置完成"))
        else:
            self.log(tr("  ✗ TCP/IP 重置未完全成功(IPv4/IPv6 之一失败)"))
        return ok

    def flush_dns(self):
        self.log(tr("[操作] 清除 DNS 缓存..."))
        if IS_LINUX:
            # systemd-resolved / nscd 两种常见实现，任一成功即可
            ok = (self.run_cmd('resolvectl flush-caches', timeout=10)
                  or self.run_cmd('systemd-resolve --flush-caches', timeout=10)
                  or self.run_cmd('service nscd restart', timeout=15))
            if ok:
                self.log(tr("  ✓ DNS 缓存已清除 (Linux)"))
            else:
                self.log("  ⚠ Linux 清除 DNS 缓存失败,可手动执行: "
                         "sudo resolvectl flush-caches")
            return ok
        if IS_MAC:
            # macOS: 需 sudo; 普通用户会提示权限不足,这里尽量尝试
            ok = self.run_cmd('sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder',
                              timeout=15)
            if ok:
                self.log(tr("  ✓ DNS 缓存已清除 (macOS)"))
            else:
                self.log("  ⚠ macOS 清除 DNS 需管理员权限(sudo),"
                         "请在本机终端运行: sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder")
            return ok
        if self.run_cmd('ipconfig /flushdns'):
            self.log(tr("  ✓ DNS 缓存已清除"))
            return True
        else:
            self.log(tr("  ✗ DNS 缓存清除失败"))
            return False

    def flush_arp(self):
        if IS_MAC:
            self.log(tr("[操作] 清除 ARP 缓存..."))
            self.run_cmd('sudo arp -ad', timeout=10)
            self.log(tr("  ✓ ARP 缓存已清除 (macOS)"))
            return True
        if not IS_WINDOWS:
            self.log(tr("  ⚠ 清除 ARP 仅支持 Windows/macOS"))
            return False
        self.log(tr("[操作] 清除 ARP 缓存..."))
        if self.run_cmd('netsh interface ip delete arpcache'):
            self.log(tr("  ✓ ARP 缓存已清除"))
            return True
        else:
            self.log(tr("  ✗ ARP 缓存清除失败"))
            return False

    def renew_dhcp(self):
        if not IS_WINDOWS:
            self.log(tr("  ⚠ 刷新 DHCP 仅支持 Windows"))
            return False
        self.log(tr("[操作] 刷新 DHCP..."))
        self.run_cmd('ipconfig /release', timeout=10)
        self.run_cmd('ipconfig /renew', timeout=15)
        self.log(tr("  ✓ DHCP 已刷新"))
        return True

    def restore_static_ip(self):
        if not IS_WINDOWS:
            return
        if not self.static_configs:
            return
        self.log(tr("[恢复] 静态IP配置..."))
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
        if not IS_WINDOWS:
            return
        self.log(tr("[代理] 备份系统代理设置..."))
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
        if not IS_WINDOWS:
            return
        if not hasattr(self, '_proxy_enable') or self._proxy_enable is None:
            self.log(tr("[代理] 无代理配置需要恢复"))
            return
        self.log(tr("[代理] 恢复系统代理设置..."))
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
        if IS_MAC:
            svc = adapter_name or _mac_primary_service()
            if not svc:
                return [], 'unknown'
            try:
                out = subprocess.run(['networksetup', '-getdnsservers', svc],
                                     capture_output=True, text=True, timeout=10).stdout
                lines = [l.strip() for l in out.splitlines() if l.strip()]
                if lines and lines[0].lower().startswith(('there', 'any')):
                    return [], 'dhcp'
                return lines, 'static'
            except Exception:
                return [], 'unknown'
        ps_script = '''
$adapters = Get-WmiObject Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -eq $true }
foreach ($a in $adapters) {
    $name = (Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.GUID -eq $a.SettingID }).NetConnectionID
    $dhcp = $a.DHCPEnabled
    $dns = $a.DNSServerSearchOrder -join ','
    $gw = if ($a.DefaultIPGateway) { 1 } else { 0 }
    if ($name -and $dns) { Write-Output "$gw|$name|$dhcp|$dns" }
}
'''
        try:
            result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive',
                                     '-Command', ps_script],
                                   capture_output=True, timeout=10)
            stdout = self._decode_output(result.stdout)
            lines = [l.strip() for l in stdout.strip().split('\n') if l.strip() and '|' in l]
            if not lines:
                return [], 'unknown'
            # 优先取"有默认网关"的网卡(真实出口)，其次才是第一个有 DNS 的
            lines.sort(key=lambda l: l.startswith('1|'), reverse=True)
            parts = lines[0].split('|')
            if len(parts) == 4:
                parts = parts[1:]
            if len(parts) >= 3:
                is_dhcp = parts[1].strip().lower() == 'true'
                dns_list = [d.strip() for d in parts[2].split(',') if d.strip()]
                return dns_list, ('dhcp' if is_dhcp else 'static')
        except Exception:
            pass
        return [], 'unknown'

    def set_dns(self, adapter_name, primary, secondary=None):
        """设置 DNS 服务器"""
        if IS_MAC:
            svc = adapter_name or _mac_primary_service()
            if not svc:
                self.log(tr("  ✗ 未找到 macOS 网络服务"))
                return False
            self.log(f"[macOS] 设置 DNS: {svc}")
            self.run_cmd(f'sudo networksetup -setdnsservers {shlex.quote(svc)} {primary}'
                         + (f' {secondary}' if secondary else ''), timeout=15)
            self.log(f"  ✓ 主 DNS: {primary}")
            if secondary:
                self.log(f"  ✓ 备用 DNS: {secondary}")
            return True
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
        if IS_MAC:
            svc = adapter_name or _mac_primary_service()
            if not svc:
                self.log(tr("  ✗ 未找到 macOS 网络服务"))
                return False
            self.run_cmd(f'sudo networksetup -setdnsservers {shlex.quote(svc)} Empty',
                          timeout=15)
            self.log(f"  ✓ DNS 已切换为自动获取 (DHCP) [macOS: {svc}]")
            return True
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
        if not IS_WINDOWS:
            self.log(tr("⚠ 完整网络重置(重置 Winsock/TCP-IP/ARP/DHCP/静态IP)仅支持 Windows。"))
            self.log(tr("  → 在 macOS 上请使用「代理修复」标签页修复代理,或终端手动处理。"))
            return
        self.log("=" * 50)
        self.log(tr("🔄 开始完整网络重置"))
        self.log("=" * 50)
        self.log("")
        self.backup_static_ip()
        self._backup_proxy()
        self.log("")
        if self._cancel:
            self.log("")
            self.log(tr("⏹ 已取消,未执行的步骤已跳过"))
            return
        self.reset_winsock()
        self.log("")
        if self._cancel:
            self.log("")
            self.log(tr("⏹ 已取消,未执行的步骤已跳过"))
            return
        self.reset_tcpip()
        self.log("")
        if self._cancel:
            self.log("")
            self.log(tr("⏹ 已取消,未执行的步骤已跳过"))
            return
        self.flush_dns()
        self.flush_arp()
        self.log("")
        if self._cancel:
            self.log("")
            self.log(tr("⏹ 已取消,未执行的步骤已跳过"))
            return
        self.renew_dhcp()
        self.log("")
        self.restore_static_ip()
        self._restore_proxy()
        self.log("")
        self.log("=" * 50)
        self.log(tr("🎉 网络重置完成!"))
        self.log(tr("建议重启电脑使设置生效"))
        self.log("=" * 50)

class NetworkDiagnostic:
    """诊断工具类"""

    _decode_output = staticmethod(decode_output)

    # label 存规范中文原文: 这些字段会随结果写进报告。
    # 若在类定义时就 tr(), 语言就被冻结在 import 那一刻,
    # 用户切换语言后这些标签不会跟着变——改为展示时按需 tr()。
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
        """执行 PowerShell 脚本并安全解码输出（失败时记录原因，不再静默返回空串）。"""
        if not IS_WINDOWS:
            return ""
        try:
            result = subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                capture_output=True, text=False, timeout=timeout
            )
            output = decode_output(result.stdout).strip()
            if not output:
                err = decode_output(result.stderr).strip()
                if err and self.log_callback:
                    self.log_callback(f"  · PowerShell 提示: {err.splitlines()[0][:120]}")
            return output
        except subprocess.TimeoutExpired:
            if self.log_callback:
                self.log_callback(f"  ⚠ PowerShell 执行超时 ({timeout}s)")
            return ""
        except Exception as e:
            if self.log_callback:
                self.log_callback(f"  ⚠ PowerShell 执行失败: {e}")
            return ""

    def _get_overview_modern(self):
        """使用 Get-NetAdapter（Win8+）"""
        results = []
        ps = '''
$out = @()
# 优先选"有默认网关"的网卡：否则会选中 Hyper-V / VMware / Docker 虚拟网卡
$active = $null
$cfg = $null
foreach ($a in (Get-NetAdapter | Where-Object { $_.Status -eq 'Up' })) {
    $c = Get-NetIPConfiguration -InterfaceIndex $a.ifIndex -ErrorAction SilentlyContinue
    if ($c -and $c.IPv4DefaultGateway) { $active = $a; $cfg = $c; break }
    if (-not $active) { $active = $a; $cfg = $c }
}
if ($active) {
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
    # 优先取有默认网关的网卡(真实出口),避免选中虚拟网卡
    $a = $null
    foreach ($x in $adapters) { if ($x.DefaultIPGateway) { $a = $x; break } }
    if (-not $a) { $a = $adapters | Select-Object -First 1 }
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
                for m in re.finditer(tr(r'默认网关[^:]*:\s*(\S+)'), output):
                    results.append((tr('网关'), m.group(1)))
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

    # 解码统一走模块级 decode_output（BOM/UTF-16 特征探测，避免 UTF-8 被误判成 GBK）

    def ping(self, target, count=4):
        """Ping 一个目标，返回 (ok, avg_ms, loss_pct, output)

        修复要点：
          - 先校验目标合法性，杜绝 `8.8.8.8 & calc` 这类 shell 注入；
          - 用参数列表调用，不再 shell=True + f-string 拼命令；
          - 解析同时适配 Windows(中/英)、macOS、Linux 三种输出格式。
        """
        if not is_valid_target(target):
            return False, None, 100, f"目标地址非法: {target!r}"
        try:
            if IS_WINDOWS:
                argv = ['ping', '-n', str(int(count)), target]
                timeout = 6 + 2 * int(count)
            else:
                argv = ['ping', '-c', str(int(count)), '-W', '2000', target] \
                    if not IS_MAC else ['ping', '-c', str(int(count)), '-t', '2', target]
                timeout = 6 + 2 * int(count)

            proc = subprocess.run(argv, capture_output=True, timeout=timeout)
            output = decode_output(proc.stdout) or decode_output(proc.stderr)
            if not output.strip():
                return False, None, 100, tr("(无输出)")

            # ---- 是否收到回复 ----
            has_reply = ('Reply from' in output or '来自' in output or '回复' in output
                         or 'bytes from' in output.lower() or 'bytes=' in output)
            if not has_reply:
                return False, None, 100, output.strip()

            # ---- 平均延迟 ----
            avg_ms = None
            m = re.search(tr(r'(?:Average|平均)\s*=\s*(\d+)ms'), output, re.I)
            if m:
                avg_ms = int(m.group(1))
            else:
                m = re.search(r'(?:min/avg/max(?:/\w+)?\s*=\s*|round-trip[^=]*=\s*)'
                              r'[\d.]+/([\d.]+)/[\d.]+', output, re.I)
                if m:
                    avg_ms = int(float(m.group(1)))

            # ---- 丢包率 ----
            loss = 0
            m = re.search(tr(r'(\d+(?:\.\d+)?)%\s*(?:loss|丢失|packet loss)'), output, re.I)
            if m:
                loss = int(float(m.group(1)))
            else:
                m = re.search(tr(r'\((\d+)%\s*(?:loss|丢失)\)'), output, re.I)
                if m:
                    loss = int(m.group(1))
                else:
                    m = re.search(r'Sent\s*=\s*(\d+)\s*,\s*Received\s*=\s*(\d+)', output, re.I)
                    if m and int(m.group(1)):
                        sent, recv = int(m.group(1)), int(m.group(2))
                        loss = int((sent - recv) * 100 / sent)

            return True, avg_ms, loss, output.strip()
        except subprocess.TimeoutExpired:
            return False, None, 100, 'timeout'
        except FileNotFoundError:
            return False, None, 100, tr('当前系统未找到 ping 命令')
        except Exception as e:
            return False, None, 100, str(e)

    @staticmethod
    def _parse_nslookup(output, dns_server=None):
        """解析 nslookup 输出，跳过 DNS 服务器自身地址，只取应答区 IP。"""
        text = output or ""
        parts = re.split(tr(r'(?:Non-authoritative answer|非权威应答)\s*:?'), text,
                         maxsplit=1, flags=re.I)
        body = parts[1] if len(parts) > 1 else text

        def _collect(scope):
            found = []
            for a in re.findall(r'Address(?:es)?\s*:\s*([0-9A-Fa-f:.#]+)', scope):
                ip = a.split('#')[0]          # 去掉 Linux 的 "1.2.3.4#53"
                if _IPV4_RE.match(ip) and ip != dns_server:
                    found.append(ip)
            return found

        found = _collect(body) or _collect(text)
        failed = bool(re.search(
            r"can't find|找不到|Non-existent domain|server can't find|"
            r"timed out|超时|Request timed out|no servers could be reached",
            text, re.I))
        ok = bool(found) and not failed
        return ok, (found[0] if found else None), text.strip()

    def _dns_lookup_nslookup(self, target, dns_server=None):
        """跨平台回退方案：nslookup（Win7 / macOS / Linux 均可用）"""
        argv = ['nslookup', target]
        if dns_server:
            argv.append(dns_server)
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=12)
            output = decode_output(proc.stdout) or decode_output(proc.stderr)
            return self._parse_nslookup(output, dns_server)
        except subprocess.TimeoutExpired:
            return False, None, f"nslookup {target} 超时"
        except FileNotFoundError:
            return False, None, tr("当前系统未找到 nslookup 命令")
        except Exception as e:
            return False, None, str(e)

    def dns_lookup(self, target, dns_server=None):
        """DNS 解析测试

        Win8+ 走 Resolve-DnsName，其余（Win7 / macOS / Linux）走 nslookup，
        任一路径失败自动回退。解析结果会剔除 DNS 服务器自身 IP，避免"假成功"。
        """
        if not is_valid_target(target):
            return False, None, f"目标地址非法: {target!r}"
        if dns_server and not _IPV4_RE.match(dns_server):
            return False, None, f"DNS 服务器地址非法: {dns_server!r}"

        if IS_WINDOWS and not _is_win7_or_older():
            try:
                server_opt = f" -Server {dns_server}" if dns_server else ""
                ps_script = (f"Resolve-DnsName {target} -DnsOnly{server_opt} "
                             f"-ErrorAction Stop | Select-Object IPAddress,NameHost | Format-List")
                result = subprocess.run(
                    ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script],
                    capture_output=True, timeout=12
                )
                output = decode_output(result.stdout)
                ips = [a for a in re.findall(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', output)
                       if a != dns_server]
                failed = ("can't find" in output.lower() or '找不到' in output
                          or 'Resolve-DnsName' in output and not ips)
                if ips and not failed:
                    return True, ips[0], output
            except Exception:
                pass  # 落到 nslookup

        return self._dns_lookup_nslookup(target, dns_server)

    def benchmark_dns(self, presets=None, domain="www.baidu.com", rounds=3,
                        progress_callback=None):
        """DNS 批量测速(F9): 对每个静态预设解析同一域名 rounds 次, 按平均耗时排序。

        返回 [{name, primary, secondary, ok, avg_ms, min_ms, fail_rounds, ip}],
        最快的排最前; avg_ms 为 None(全部失败)的排最后。
        "自动获取(DHCP)"没有固定 DNS 地址, 不参与测速。
        progress_callback(name, done_rounds, total_rounds) 供 UI 显示进度。
        """
        if presets is None:
            presets = DNS_PRESETS
        rounds = max(1, int(rounds))
        candidates = [(name, cfg) for name, cfg in presets.items()
                      if cfg.get("mode") == "static" and cfg.get("primary")]
        out = []
        for name, cfg in candidates:
            server = cfg["primary"]
            times, ok_rounds, ip = [], 0, None
            for i in range(rounds):
                t0 = time.perf_counter()
                try:
                    ok, addr, _out = self.dns_lookup(domain, dns_server=server)
                except Exception:
                    ok, addr = False, None
                elapsed_ms = (time.perf_counter() - t0) * 1000
                if ok:
                    ok_rounds += 1
                    times.append(elapsed_ms)
                    ip = addr
                if progress_callback:
                    try:
                        progress_callback(name, i + 1, rounds)
                    except Exception:
                        pass
            out.append({
                "name": name, "primary": server,
                "secondary": cfg.get("secondary", ""),
                "ok": ok_rounds > 0,
                "avg_ms": round(sum(times) / len(times), 1) if times else None,
                "min_ms": round(min(times), 1) if times else None,
                "fail_rounds": rounds - ok_rounds,
                "ip": ip,
            })
        out.sort(key=lambda x: (x["avg_ms"] is None,
                                x["avg_ms"] if x["avg_ms"] is not None else 0))
        return out

    def traceroute(self, target):
        """路由追踪：Windows 用 tracert，macOS/Linux 用 traceroute。

        统一加 `-d/-n` 关闭反向 DNS，追踪速度从"分钟级"降到"秒级"；
        参数列表调用，杜绝命令注入。
        """
        if not is_valid_target(target):
            return f"目标地址非法: {target!r}"
        if IS_WINDOWS:
            argv = ['tracert', '-d', '-h', '30', '-w', '2000', target]
        else:
            argv = ['traceroute', '-n', '-m', '30', '-w', '2', target]
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=90)
            output = decode_output(proc.stdout)
            if not output.strip():
                output = decode_output(proc.stderr)
            return output.strip() or tr("(无输出，目标可能不可达或已被防火墙拦截)")
        except subprocess.TimeoutExpired:
            return tr("追踪超时(90秒)，目标可能不可达")
        except FileNotFoundError:
            return (tr("当前系统未找到 tracert 命令") if IS_WINDOWS
                    else tr("当前系统未找到 traceroute 命令（Linux 可安装 traceroute 包）"))
        except Exception as e:
            return f"追踪失败: {e}"

    def run_full_diagnostic(self, progress_callback=None):
        """运行完整诊断, 返回结果字典（F13: 由 plugins 注册表驱动）。

        依次跑 `network_toolbox.plugins.diagnostic_items()` 里的每一项：
        内置 overview / ping / dns 三项之外，第三方还可以
        `register_item()` 追加自己的检查，无需改这里。
        """
        return run_diagnostics(self, progress_callback)

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
    if IS_MAC:
        _home = os.path.expanduser("~")
        CLASH_CONFIG_DIRS = [
            os.path.join(_home, "Library", "Application Support", "clash-verge-rev", "config"),
            os.path.join(_home, ".config", "clash-verge", "config"),
            os.path.join(_home, ".config", "clash-nyanpasu", ".config", "clash-verge"),
            os.path.join(_home, ".config", "Clash Nyanpasu", ".config", "clash-verge"),
        ] + CLASH_CONFIG_DIRS

    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def log(self, msg, color=None):
        if self.log_callback:
            self.log_callback(msg, color)

    # ---------- 系统代理 ----------
    def get_system_proxy(self):
        if IS_MAC:
            try:
                svc = _mac_primary_service()
                if not svc:
                    return False, ""
                out = subprocess.run(['networksetup', '-getwebproxy', svc],
                                     capture_output=True, text=True, timeout=10).stdout
                enabled = False
                host, port = "", ""
                for line in out.splitlines():
                    s = line.strip()
                    if s.startswith('Enabled:'):
                        enabled = s.split(':', 1)[1].strip().lower() == 'yes'
                    elif s.startswith('Server:'):
                        host = s.split(':', 1)[1].strip()
                    elif s.startswith('Port:'):
                        port = s.split(':', 1)[1].strip()
                server = f"{host}:{port}" if (host and port) else ""
                return enabled, server
            except Exception as e:
                self.log(f"读取系统代理失败(macOS): {e}")
                return False, ""
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
        if IS_MAC:
            try:
                svc = _mac_primary_service()
                if not svc:
                    self.log(tr("  ⚠ 未找到 macOS 网络服务,无法设置系统代理"))
                    return False
                if enable:
                    self.run_cmd(f'sudo networksetup -setwebproxy {shlex.quote(svc)} {host} {port}', timeout=15)
                    self.run_cmd(f'sudo networksetup -setsecurewebproxy {shlex.quote(svc)} {host} {port}', timeout=15)
                    self.run_cmd(f'sudo networksetup -setwebproxystate {shlex.quote(svc)} on', timeout=15)
                    self.run_cmd(f'sudo networksetup -setsecurewebproxystate {shlex.quote(svc)} on', timeout=15)
                else:
                    self.run_cmd(f'sudo networksetup -setwebproxystate {shlex.quote(svc)} off', timeout=15)
                    self.run_cmd(f'sudo networksetup -setsecurewebproxystate {shlex.quote(svc)} off', timeout=15)
                self.log(f"  ✓ macOS 系统代理已{'启用' if enable else '关闭'}: {host}:{port}")
                return True
            except Exception as e:
                self.log(f"设置系统代理失败(macOS): {e}")
                return False
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
        if IS_MAC:
            try:
                # lsof 列出所有监听 TCP 端口及进程名
                out = subprocess.run(
                    ['lsof', '-nP', '-iTCP', '-sTCP:LISTEN', '-F', 'n', '-F', 'p'],
                    capture_output=True, text=True, timeout=15).stdout
                pid_to_name = {}
                name_for_port = {}
                cur_pid = None
                cur_name = None
                for line in out.splitlines():
                    if line.startswith('p'):
                        cur_pid = line[1:].strip()
                        try:
                            cur_name = subprocess.run(
                                ['ps', '-o', 'comm=', '-p', cur_pid],
                                capture_output=True, text=True, timeout=8).stdout.strip()
                            cur_name = os.path.basename(cur_name)
                        except Exception:
                            cur_name = None
                    elif line.startswith('n') and cur_pid:
                        addr = line[1:]
                        if ':' in addr:
                            port_s = addr.rsplit(':', 1)[1].split('.')[0]
                            try:
                                port = int(port_s)
                            except ValueError:
                                continue
                            name = cur_name or ''
                            cores.append({'port': port, 'process': name})
                # 也把当前系统代理端口对应的进程补上(若未匹配到名字)
            except Exception as e:
                self.log(f"扫描监听端口失败(macOS): {e}")
            return cores
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
        mixed = None
        # 基准文件 + Clash 运行时 override 文件（后者优先，与 Clash 合并行为一致）
        for fn in ('clash-config.yaml', 'clash-guard-overrides.yaml'):
            path = os.path.join(cfg_dir, fn)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        st = line.strip()
                        if st.startswith('mixed-port:'):
                            try:
                                mixed = int(st.split(':', 1)[1].strip())
                            except ValueError:
                                pass
            except Exception:
                pass
        return mixed

    def read_clash_controller(self, cfg_dir):
        port, secret = None, None
        path = os.path.join(cfg_dir, 'clash-config.yaml')
        if not os.path.isfile(path):
            return port, secret
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

    # ---------- Clash 节点检查 / 自动切换 ----------
    def _clash_api_get(self, port, secret, path):
        """GET Clash external-controller API"""
        import urllib.request
        url = f"http://127.0.0.1:{port}{path}"
        headers = {}
        if secret:
            headers['Authorization'] = f"Bearer {secret}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=6) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            self.log(f"Clash API GET {path} 失败: {e}")
            return None

    def _clash_api_put(self, port, secret, path, payload):
        """PUT Clash external-controller API"""
        import urllib.request
        url = f"http://127.0.0.1:{port}{path}"
        headers = {'Content-Type': 'application/json'}
        if secret:
            headers['Authorization'] = f"Bearer {secret}"
        try:
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode('utf-8'),
                headers=headers, method='PUT')
            with urllib.request.urlopen(req, timeout=6) as resp:
                return resp.status in (200, 204)
        except Exception as e:
            self.log(f"Clash API PUT {path} 失败: {e}")
            return False

    def _find_dead_group(self, port, secret):
        """返回第一个选中了死节点(delay=0/None)的 Selector 组 (group, node)，没有则 None"""
        data = self._clash_api_get(port, secret, '/proxies')
        if not data or 'proxies' not in data:
            return None
        proxies = data['proxies']
        for name, info in proxies.items():
            if info.get('type') != 'Selector':
                continue
            now = info.get('now')
            if not now:
                continue
            node = proxies.get(now)
            delay = node.get('delay') if node else None
            if delay is None or delay == 0:
                return name, now
        return None

    def _find_auto_group(self, proxies):
        """在 /proxies 数据中找 URLTest 自动选择组（优先类型，其次常见中文名兜底）"""
        auto = next((n for n, i in proxies.items() if i.get('type') == 'URLTest'), None)
        if not auto:
            # 同样不能 tr(): 比的是用户配置里的节点组名
            for cand in ('自动选择', '🚀 节点选择', '♻️ 自动选择', 'Auto', 'auto'):
                if cand in proxies:
                    auto = cand
                    break
        return auto

    def repair_clash_selection(self, port, secret):
        """检查 Clash 当前选中的节点：若 delay=0(死节点) 则自动切到 URLTest 自动选择组。
        返回 [(描述, 是否成功), ...]"""
        import urllib.parse
        result = []
        data = self._clash_api_get(port, secret, '/proxies')
        if not data or 'proxies' not in data:
            return result
        proxies = data['proxies']
        # 收集用户可选组(Selector)，检查其当前选中节点
        dead_groups = []
        for name, info in proxies.items():
            if info.get('type') != 'Selector':
                continue
            now = info.get('now')
            if not now:
                continue
            node = proxies.get(now)
            delay = node.get('delay') if node else None
            if delay is None or delay == 0:
                dead_groups.append((name, now))
        if not dead_groups:
            return result
        # 找 URLTest 自动选择组
        auto = self._find_auto_group(proxies)
        if not auto:
            result.append((tr("检测到死节点，但未找到可用的自动选择组"), False))
            return result
        for name, now in dead_groups:
            ok = self._clash_api_put(port, secret,
                                     '/proxies/' + urllib.parse.quote(name),
                                     {'name': auto})
            result.append((
                f"节点 [{now}] 已失效(delay=0)，已把 [{name}] 自动切到 [{auto}]",
                ok))
        return result

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
                tr("把系统代理重新指向真正在工作的代理端口(见下方「代理核心」)"))
        core = self.find_clash_core()
        result['clash_core'] = core
        # 配置目录只探测一次（内部会遍历多个候选路径）
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
                    tr("Clash 的 dns.enable=false,而 enhanced-mode=fake-ip,会导致所有域名解析超时"))
                result['suggestions'].append(
                    tr("开启 Clash DNS(enable:true)并重启核心"))
            # 死节点检测：当前选中节点 delay=0
            port, secret = self.read_clash_controller(cfg_dir)
            if port:
                dead = self._find_dead_group(port, secret)
                if dead:
                    group, node = dead
                    result['issues'].append(
                        f"Clash 当前选中节点 [{node}] 已失效(delay=0),外网会连不上")
                    result['suggestions'].append(
                        f"一键修复会自动把 [{group}] 切到自动选择组")
        elif core:
            result['suggestions'].append(
                tr("未找到 Clash 配置目录,无法自动修复 DNS,请手动检查订阅"))
        if not result['issues']:
            result['suggestions'].append(tr("未发现明显代理问题"))
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
                actions.append(tr("系统代理重设失败"))
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
                            actions.append(tr("已重启 Clash 核心使 DNS 生效"))
                        else:
                            actions.append(tr("DNS 配置已改,但核心重启失败(请手动在 GUI 里应用/重启)"))
                else:
                    actions.append(tr("Clash DNS 无需修改"))
        # 3) Clash 当前选中的节点已失效(delay=0) -> 自动切到自动选择组
        if cfg_dir:
            port, secret = self.read_clash_controller(cfg_dir)
            if port:
                for desc, success in self.repair_clash_selection(port, secret):
                    actions.append(desc)
                    if not success:
                        ok = False
        if not actions:
            actions.append(tr("无需修复"))
        return ok, actions

# ============================================================
#  hosts 检查与清理 (F4) / 监听端口查看 (F5)
# ============================================================

class HostsTool:
    """hosts 文件检查与清理。

    hosts 被软件写脏是"某些网站打不开/广告域名被指错"的常见原因。
    只做非注释条目的列举、可疑标记、注释与还原, 且任何写操作前先备份。
    """

    # 视为"正常"的 hosts 目标: 本地回环 / 黑洞地址
    BENIGN_IPS = {"127.0.0.1", "0.0.0.0", "::1", "localhost", "255.255.255.255", ""}
    # 注释掉一行时保留原内容
    COMMENT_PREFIX = tr("# [网络工具箱] ")

    def __init__(self, hosts_path=None):
        if hosts_path:
            self.path = hosts_path
        elif IS_WINDOWS:
            self.path = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"),
                                     "System32", "drivers", "etc", "hosts")
        else:
            self.path = "/etc/hosts"

    # ---------- 读取/判定 ----------
    def read_entries(self):
        """返回 [{line, raw, ip, host, commented, suspicious, reason}, ...]。

        line 为 1 起始行号(对应文件真实行号, 供注释用)。
        """
        entries = []
        try:
            # utf-8-sig: 兼容 Notepad 保存的带 BOM hosts(否则首个 # 注释行会被当成映射条目)
            with open(self.path, "r", encoding="utf-8-sig", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            return entries
        for idx, raw in enumerate(lines, 1):
            stripped = raw.strip().lstrip("\ufeff").strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            ip, hosts = parts[0], parts[1:]
            suspicious, reason = self.is_suspicious(ip, hosts)
            for host in hosts:
                entries.append({
                    "line": idx, "raw": raw.rstrip(), "ip": ip, "host": host,
                    "commented": False, "suspicious": suspicious, "reason": reason,
                })
        return entries

    @classmethod
    def is_suspicious(cls, ip, hosts):
        """判定一条 hosts 映射是否可疑, 返回 (bool, reason)。"""
        ip = (ip or "").lower()
        for host in hosts:
            if host.lower() in ("localhost", "localhost.localdomain"):
                return False, ""
        if ip in ("::1", "127.0.0.1"):
            # 回环映射: 通常用于本地开发, 也可能是屏蔽(指向自身) —— 视为正常
            return False, ""
        if ip in ("0.0.0.0", "255.255.255.255"):
            return False, tr("黑洞地址(通常为广告屏蔽)")
        if not cls._looks_like_ip(ip):
            return True, tr("目标不是合法 IP 地址")
        if cls._is_private_or_local(ip):
            return False, tr("指向内网/本机地址")
        return True, tr("指向外部 IP ") + ip + tr(", 域名解析可能被劫持")

    @staticmethod
    def _looks_like_ip(ip):
        parts = ip.split(".")
        if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            return True
        return ":" in ip  # 粗略匹配 IPv6

    @staticmethod
    def _is_private_or_local(ip):
        if ip.startswith(("127.", "10.", "192.168.")):
            return True
        if ip.startswith("172.") and len(ip.split(".")) > 1 and ip.split(".")[1].isdigit():
            return 16 <= int(ip.split(".")[1]) <= 31
        return ip.startswith("169.254.") or ip == "::1"

    # ---------- 备份 / 写回 ----------
    def backup(self):
        """备份 hosts, 返回备份路径(失败返回 None)。"""
        try:
            backup_dir = os.path.join(_app_data_dir(), "hosts_backups")
            os.makedirs(backup_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(backup_dir, "hosts_" + stamp + ".bak")
            shutil.copy2(self.path, dest)
            return dest
        except Exception:
            return None

    def list_backups(self):
        """返回 [(path, 修改时间字符串), ...] 按文件名倒序(即时间倒序)。"""
        out = []
        try:
            backup_dir = os.path.join(_app_data_dir(), "hosts_backups")
            for name in sorted(os.listdir(backup_dir), reverse=True):
                if not name.endswith(".bak"):
                    continue
                p = os.path.join(backup_dir, name)
                mt = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")
                out.append((p, mt))
        except Exception:
            pass
        return out

    def comment_entries(self, line_numbers):
        """注释指定行号(1 起始)。返回 (ok, 被注释行数, 错误信息)。"""
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception as e:
            return False, 0, tr("读取失败: ") + str(e)
        changed = 0
        for ln in line_numbers:
            if 1 <= ln <= len(lines):
                raw = lines[ln - 1]
                if raw.strip() and not raw.lstrip().startswith("#"):
                    lines[ln - 1] = self.COMMENT_PREFIX + raw
                    changed += 1
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            return False, 0, tr("写入失败(可能需要管理员权限): ") + str(e)
        return True, changed, ""

    def comment_suspicious(self):
        """一键注释所有可疑条目。返回 (ok, 条数, 错误信息)。"""
        lines_to_comment = sorted({e["line"] for e in self.read_entries() if e["suspicious"]})
        if not lines_to_comment:
            return True, 0, ""
        return self.comment_entries(lines_to_comment)

    def restore(self, backup_path):
        """从备份还原 hosts。返回 (ok, 错误信息)。"""
        try:
            shutil.copy2(backup_path, self.path)
            return True, ""
        except Exception as e:
            return False, tr("还原失败(可能需要管理员权限): ") + str(e)


class PortTool:
    """本机监听端口查看 (F5)。

    "代理端口没人听"是本项目最高频的诊断结论; 这里列出 LISTENING
    端口与对应进程, 支持按端口/进程过滤, Windows 上可结束进程。
    """

    # ---------- 纯解析(便于测试) ----------
    @staticmethod
    def parse_netstat(text):
        """解析 netstat -ano 输出为 [{proto, addr, port, pid, state}]。"""
        out = []
        for line in text.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            proto = parts[0]
            if proto not in ("TCP", "UDP", "TCP6", "UDP6"):
                continue
            local, foreign, state = parts[1], parts[2], parts[3]
            pid = None
            if len(parts) >= 5 and parts[4].isdigit():
                pid = int(parts[4])
            if proto.startswith("TCP") and state.upper() != "LISTENING":
                continue
            addr, _, port_s = local.rpartition(":")
            try:
                port = int(port_s)
            except ValueError:
                continue
            out.append({"proto": proto, "addr": addr.strip("[]"), "port": port,
                        "pid": pid,
                        "state": state.upper() if not proto.startswith("UDP") else "LISTENING"})
        return out

    @staticmethod
    def parse_tasklist(text):
        """解析 tasklist /nh /fo csv 输出为 {pid: 进程名}。"""
        import csv
        import io
        mapping = {}
        try:
            for row in csv.reader(io.StringIO(text)):
                if len(row) >= 2 and row[1].isdigit():
                    mapping[int(row[1])] = row[0]
        except Exception:
            pass
        return mapping

    # ---------- 实际操作 ----------
    def list_listening(self):
        """返回当前监听端口列表(含进程名), 失败返回 []。"""
        if IS_WINDOWS:
            rc, out, _err = run_cmd_capture(["netstat", "-ano"])
            items = self.parse_netstat(out) if rc == 0 else []
            if items:
                rc2, tl, _ = run_cmd_capture(["tasklist", "/nh", "/fo", "csv"])
                if rc2 == 0:
                    mapping = self.parse_tasklist(tl)
                    for it in items:
                        it["process"] = mapping.get(it["pid"], "-")
        elif IS_MAC:
            rc, out, _err = run_cmd_capture(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"])
            items = self._parse_lsof(out) if rc == 0 else []
        else:
            rc, out, _err = run_cmd_capture(["ss", "-tlnp"])
            items = self.parse_netstat(out) if rc == 0 else []
        for it in items:
            it.setdefault("process", "-")
        items.sort(key=lambda x: (x["port"], x["proto"]))
        return items

    @staticmethod
    def _parse_lsof(text):
        out = []
        for line in text.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 9 or parts[3] != "TCP":
                continue
            name = parts[0]
            local = parts[8]
            addr, _, port_s = local.rpartition(":")
            try:
                port = int(port_s)
            except ValueError:
                continue
            pid = int(parts[1]) if parts[1].isdigit() else None
            out.append({"proto": "TCP", "addr": addr, "port": port,
                        "pid": pid, "state": "LISTENING", "process": name})
        return out

    def kill_process(self, pid):
        """结束进程(仅 Windows/macOS)。返回 (ok, 信息)。"""
        if not IS_WINDOWS and not IS_MAC:
            return False, tr("当前平台不支持结束进程")
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return False, tr("PID 无效")
        if IS_WINDOWS:
            rc, _o, err = run_cmd_capture(["taskkill", "/PID", str(pid), "/F"])
        else:
            rc, _o, err = run_cmd_capture(["kill", "-9", str(pid)])
        if rc == 0:
            return True, tr("已结束进程 ") + str(pid)
        return False, tr("结束失败: ") + (err or tr("未知错误"))


class NetworkMonitor:
    """定时网络体检 + 掉线记录(F7)。

    周期性 Ping 网关与外网目标(默认每 5 分钟); 判定掉线/恢复,
    记录断线事件(起止时间 + 持续时长)并落盘 JSON, 重启后可回看。
    线程模型: daemon 线程跑循环, 采集只做数据, UI 刷新经 on_tick/on_event
    回调交由调用方投递回主线程(遵守线程安全铁律)。
    """

    INTERNET_TARGET = "223.5.5.5"   # 阿里公共 DNS, 国内可达性基准
    MIN_INTERVAL = 30               # 最小间隔(秒), 防止把本机 ping 爆

    def __init__(self, interval_seconds=300, targets=None, data_dir=None,
                 on_tick=None, on_event=None):
        self.interval = max(self.MIN_INTERVAL, int(interval_seconds))
        self.data_dir = data_dir or os.path.join(_app_data_dir(), "monitor")
        self.on_tick = on_tick        # callback(status_dict) 每次检查后
        self.on_event = on_event      # callback(event_dict) 掉线事件闭合时
        self._targets_override = list(targets) if targets else None
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self.online = True
        self.offline_since = None
        self.last_check = None
        self.targets = []
        self.events = self._load_events()

    # ---------- 目标 ----------
    def resolve_targets(self):
        """确定巡检目标: 默认网关(若有) + 外网基准; 失败时只用外网基准。"""
        if self._targets_override:
            self.targets = list(self._targets_override)
            return self.targets
        targets = []
        try:
            overview = NetworkDiagnostic().get_overview()
            gw = next((v for k, v in overview if "网关" in k and v), None)
            if gw:
                targets.append(gw)
        except Exception:
            pass
        targets.append(self.INTERNET_TARGET)
        self.targets = targets
        return targets

    # ---------- 单次检查 ----------
    def check_once(self):
        """Ping 一遍全部目标, 返回状态字典(纯数据, 线程安全)。"""
        if not self.targets:
            self.resolve_targets()
        results = {}
        for t in self.targets:
            ok, avg_ms, loss, _out = NetworkDiagnostic().ping(t, count=2)
            results[t] = {"ok": bool(ok), "avg_ms": avg_ms, "loss": loss}
        # 判定: 全部失败才算掉线(单目标抖动不误报); 无目标时视为在线
        online = any(r["ok"] for r in results.values()) if results else True
        status = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "online": online,
            "results": results,
        }
        closed_event = None
        with self._lock:
            self.last_check = status
            was_online = self.online
            self.online = online
            if was_online and not online:
                self.offline_since = datetime.now()
            elif not was_online and online:
                start, end = self.offline_since, datetime.now()
                self.offline_since = None
                closed_event = {
                    "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                    "end": end.strftime("%Y-%m-%d %H:%M:%S"),
                    "duration_seconds": int((end - start).total_seconds()),
                }
                self.events.append(closed_event)
                self._save_events()
        # 回调必须在锁外触发: on_event 的 UI 处理会走 summarize() 再拿这把锁,
        # 锁内回调会死锁(非重入锁), 整个界面卡死。
        if closed_event is not None and self.on_event:
            try:
                self.on_event(closed_event)
            except Exception:
                pass
        if self.on_tick:
            try:
                self.on_tick(status)
            except Exception:
                pass
        return status

    # ---------- 启停 ----------
    def start(self):
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self.resolve_targets()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="network-monitor")
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        return True

    def is_running(self):
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:
                pass  # 巡检失败不杀线程, 下一轮再来
            self._stop.wait(self.interval)

    # ---------- 事件存取 ----------
    @property
    def events_file(self):
        return os.path.join(self.data_dir, "outages.json")

    def _load_events(self):
        try:
            with open(self.events_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_events(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.events_file, "w", encoding="utf-8") as f:
                json.dump(self.events, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def clear_events(self):
        with self._lock:
            self.events = []
            self._save_events()

    def summarize(self):
        """汇总: 次数 / 合计时长 / 最近一次。"""
        with self._lock:
            events = list(self.events)
        total = sum(int(e.get("duration_seconds", 0)) for e in events)
        return {
            "count": len(events),
            "total_seconds": total,
            "latest": events[-1] if events else None,
            "ongoing": self.offline_since is not None,
        }

    @staticmethod
    def format_duration(seconds):
        """秒 -> "4 分钟" / "1 小时 3 分钟" / "45 秒"。"""
        seconds = int(seconds)
        if seconds < 60:
            return f"{seconds} 秒"
        minutes, sec = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes} 分钟" + (f" {sec} 秒" if sec else "")
        hours, minutes = divmod(minutes, 60)
        return f"{hours} 小时 {minutes} 分钟"

    @classmethod
    def format_event(cls, event):
        """形如 "14:23–14:27 断网 4 分钟" 的单行文本。"""
        start = str(event.get("start", ""))
        end = str(event.get("end", ""))
        duration = cls.format_duration(event.get("duration_seconds", 0))
        s = start[11:16] if len(start) >= 16 else start
        e = end[11:16] if len(end) >= 16 else end
        return f"{s}–{e} 断网 {duration}"


class _Stopped(Exception):
    """测速在被取消且未收到任何数据时抛出(内部信号)。"""


class SpeedTester:
    """简易下行测速(F6): 从公开端点流式下载固定大小数据, 计算带宽。

    - 纯标准库(urllib), 无第三方依赖; 端点白名单固定 https 地址, 不接触用户输入
    - 线程模型: 阻塞下载由调用方放 daemon 线程, 本类只采数据; 进度经
      progress_callback(total_bytes, elapsed) 交出, UI 刷新由调用方投递回主线程
    - 上限保护: max_seconds / max_mb 先到先停, 单次读超时 TIMEOUT, 绝不挂死
    - 可取消: stop_event 置位后, 已下载部分仍有效(按实测窗口估算带宽)
    """

    ENDPOINTS = [
        "https://speed.cloudflare.com/__down?bytes=26214400",   # 25MB
        "https://cachefly.cachefly.net/10mb.test",              # 10MB
        "https://proof.ovh.net/files/10Mb.dat",                 # 10MB
    ]
    TIMEOUT = 10            # 单次连接/读超时(秒)
    CHUNK = 64 * 1024       # 64KB 读块

    def __init__(self, log_callback=None, stop_event=None):
        self._log_cb = log_callback
        self._stop = stop_event if stop_event is not None else threading.Event()

    def log(self, msg):
        if self._log_cb:
            try:
                self._log_cb(msg)
            except Exception:
                pass

    def test(self, max_seconds=12, max_mb=64, progress_callback=None):
        """执行一次测速, 返回结果 dict(纯数据, 线程安全)。

        ok=True: {ok, mbps, downloaded_mb, seconds, latency_ms, endpoint, stopped};
        ok=False: {ok, error, stopped}。
        """
        deadline = time.time() + max(1, int(max_seconds))
        cap_bytes = max(1, int(max_mb)) * 1024 * 1024
        last_err = ""
        for url in self.ENDPOINTS:
            try:
                return self._run_one(url, deadline, cap_bytes, progress_callback)
            except _Stopped:
                return {"ok": False, "error": tr("已取消"), "stopped": True}
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                continue
        return {"ok": False, "error": last_err or tr("无可用测速端点"),
                "stopped": False}

    def _run_one(self, url, deadline, cap_bytes, progress_callback):
        if self._stop.is_set():
            raise _Stopped()
        req = urllib.request.Request(
            url, headers={"User-Agent": http_user_agent(
                "%s/%s" % (APP_NAME, APP_VERSION_SHORT))})
        started = time.perf_counter()
        first_byte_at = None
        total = 0
        with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
            while True:
                if self._stop.is_set() or total >= cap_bytes or time.time() >= deadline:
                    break
                chunk = resp.read(self.CHUNK)
                if not chunk:
                    break
                if first_byte_at is None:
                    first_byte_at = time.perf_counter()
                total += len(chunk)
                if progress_callback:
                    try:
                        progress_callback(total, time.perf_counter() - started)
                    except Exception:
                        pass
        elapsed = max(time.perf_counter() - started, 1e-6)
        if total <= 0:
            if self._stop.is_set():
                raise _Stopped()
            raise RuntimeError(tr("端点未返回数据"))
        return {
            "ok": True,
            "mbps": round(total * 8 / (elapsed * 1_000_000), 1),
            "downloaded_mb": round(total / 1048576, 4),
            "seconds": round(elapsed, 1),
            "latency_ms": (int(round((first_byte_at - started) * 1000))
                           if first_byte_at else None),
            "endpoint": url.split("?")[0],
            "stopped": self._stop.is_set(),
        }


class WifiTool:
    """已保存 WiFi 查看 (F8): 列 SSID + 回读密码 (netsh wlan, 仅 Windows)。

    - 列 profiles 普通权限即可; `key=clear` 读密码需要管理员权限
    - 命令均以参数列表执行(不经 shell), SSID 含空格/引号也不会注入
    - 解析为纯函数(parse_profiles/parse_profile_detail), 命令执行单独一层, 便于测试
    - 线程模型: 调用方放 daemon 线程, 本类只返回纯数据
    """

    # 下面这些都是**匹配标记**而不是展示文案, 绝不能包 tr():
    # 它们要和 netsh 的原话(简/繁/英)做 in / == 比较。一旦被翻译,
    # 中文系统的输出在英文界面下就匹上不了——密码全变 None。
    PROFILE_PREFIXES = ("所有用户配置文件", "所有用户設定檔", "All User Profile")
    # "show profile key=clear" 输出里的密码/认证行标签(简体/繁体/英文)
    KEY_LABELS = ("关键内容", "金鑰內容", "Key Content")
    AUTH_LABELS = ("身份验证", "驗證", "Authentication")
    # 服务未运行 / 拒绝访问 / 找不到配置文件的识别串(中/英)
    DENIED_MARKS = ("拒绝访问", "access is denied", "access denied")
    NOT_RUNNING_MARKS = ("没有运行", "not running")
    NOT_FOUND_MARKS = ("未找到", "找不到", "not found")

    def __init__(self, log_callback=None):
        self._log_cb = log_callback

    def log(self, msg):
        if self._log_cb:
            try:
                self._log_cb(msg)
            except Exception:
                pass

    # ---------- 纯解析(便于测试) ----------
    @classmethod
    def parse_profiles(cls, text):
        """解析 `netsh wlan show profiles` 输出, 返回 [SSID](去重保序)。"""
        out = []
        for line in text.splitlines():
            for prefix in cls.PROFILE_PREFIXES:
                idx = line.find(prefix)
                if idx < 0:
                    continue
                name = line[idx + len(prefix):].lstrip(" \t:：").strip()
                if name and name not in out:
                    out.append(name)
                break
        return out

    @classmethod
    def parse_profile_detail(cls, text):
        """解析 `netsh wlan show profile ... key=clear` 输出。

        返回 {auth, password, error}; password 非 None 即取到明文。
        拒绝访问/服务未运行/找不到配置文件时 error 给出原因。
        """
        info = {"auth": None, "password": None, "error": None}
        lowered = text.lower()
        if any(m in text or m in lowered for m in cls.DENIED_MARKS):
            info["error"] = tr("拒绝访问：读取密码需要管理员权限")
            return info
        if any(m in text or m in lowered for m in cls.NOT_RUNNING_MARKS):
            info["error"] = tr("WLAN 自动配置服务 (wlansvc) 未运行")
            return info
        if any(m in text or m in lowered for m in cls.NOT_FOUND_MARKS):
            info["error"] = tr("找不到该配置文件")
            return info
        for line in text.splitlines():
            label, sep, value = line.partition(":")
            if not sep:
                continue
            label, value = label.strip(), value.strip()
            if not value:
                continue
            if label in cls.KEY_LABELS:
                info["password"] = value
            elif label in cls.AUTH_LABELS and info["auth"] is None:
                info["auth"] = value
        return info

    # ---------- 实际操作 ----------
    def list_profiles(self):
        """列出已保存 WiFi 的 SSID。返回 (names, error)。"""
        if not IS_WINDOWS:
            return [], tr("WiFi 信息查看仅支持 Windows (netsh wlan)")
        rc, out, err = run_cmd_capture(
            ["netsh", "wlan", "show", "profiles"], timeout=15)
        if rc != 0 and not out.strip():
            return [], (err or tr("netsh wlan show profiles 执行失败")).strip()
        names = self.parse_profiles(out)
        if not names and any(m in out or m in out.lower()
                             for m in self.NOT_RUNNING_MARKS):
            return [], tr("WLAN 自动配置服务 (wlansvc) 未运行")
        return names, None

    def get_password(self, name):
        """读取单个 SSID 的密码(需管理员)。返回 (password, auth, error)。"""
        if not IS_WINDOWS:
            return None, None, tr("WiFi 信息查看仅支持 Windows (netsh wlan)")
        if not name or not isinstance(name, str):
            return None, None, tr("SSID 无效")
        rc, out, err = run_cmd_capture(
            ["netsh", "wlan", "show", "profile", 'name="' + name + '"',
             "key=clear"], timeout=15)
        if rc != 0 and not out.strip():
            return None, None, (err or tr("netsh 执行失败")).strip()
        info = self.parse_profile_detail(out)
        return info["password"], info["auth"], info["error"]

    def list_wifi(self, progress_callback=None):
        """列出全部已保存 WiFi 及密码。返回 (items, error)。

        items: [{ssid, password, auth, error}], password 为 None 表示未取到,
        error 说明原因(无管理员权限/开放网络无密码等)。
        """
        names, error = self.list_profiles()
        if error:
            return [], error
        items = []
        for i, name in enumerate(names, 1):
            password, auth, perr = self.get_password(name)
            items.append({"ssid": name, "password": password,
                          "auth": auth or "-", "error": perr})
            self.log("[WiFi] " + name + ": "
                     + (tr("已取到密码") if password else (perr or tr("无密码"))))
            if progress_callback:
                try:
                    progress_callback(i, len(names))
                except Exception:
                    pass
        return items, None

    @staticmethod
    def export_text(items):
        """把结果导出为 txt 文本(纯函数, 便于测试)。"""
        lines = [tr("已保存 WiFi 列表 —— 由网络工具箱导出"), ""]
        for it in items or []:
            lines.append("SSID: " + str(it.get("ssid", "")))
            lines.append(tr("密码: ") + (str(it["password"])
                                    if it.get("password") else tr("(未取到)")))
            lines.append(tr("认证: ") + str(it.get("auth") or "-"))
            if it.get("error"):
                lines.append(tr("备注: ") + str(it["error"]))
            lines.append("-" * 40)
        return "\n".join(lines) + "\n"
