# -*- coding: utf-8 -*-
"""核心引擎: 网络重置/诊断/代理修复 (纯逻辑, 不直接构造 Tk 控件)。"""
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
from datetime import datetime
import socket

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
    is_admin,
    is_valid_target,
    make_btn_style,
    styled_btn,
    ui_sync,
)

import network_toolbox._shared as _shared  # noqa: F401 (live patch point)
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
                    self.log("  ✗ 系统代理恢复失败")
            except Exception as e:
                self.log(f"  ✗ 系统代理恢复异常: {e}")

        return done, total

    def backup_static_ip(self):
        if not IS_WINDOWS:
            return
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
        if not IS_WINDOWS:
            self.log("  ⚠ 重置 Winsock 仅支持 Windows")
            return False
        self.log("[操作] 重置 Winsock...")
        if self.run_cmd('netsh winsock reset'):
            self.log("  ✓ Winsock 重置完成")
            return True
        else:
            self.log("  ✗ Winsock 重置失败")
            return False

    def reset_tcpip(self):
        if not IS_WINDOWS:
            self.log("  ⚠ 重置 TCP/IP 仅支持 Windows")
            return False
        self.log("[操作] 重置 TCP/IP 协议栈...")
        ok4 = self.run_cmd('netsh int ip reset', timeout=30)
        ok6 = self.run_cmd('netsh int ipv6 reset', timeout=30)
        ok = ok4 and ok6
        if ok:
            self.log("  ✓ TCP/IP 重置完成")
        else:
            self.log("  ✗ TCP/IP 重置未完全成功(IPv4/IPv6 之一失败)")
        return ok

    def flush_dns(self):
        self.log("[操作] 清除 DNS 缓存...")
        if IS_LINUX:
            # systemd-resolved / nscd 两种常见实现，任一成功即可
            ok = (self.run_cmd('resolvectl flush-caches', timeout=10)
                  or self.run_cmd('systemd-resolve --flush-caches', timeout=10)
                  or self.run_cmd('service nscd restart', timeout=15))
            if ok:
                self.log("  ✓ DNS 缓存已清除 (Linux)")
            else:
                self.log("  ⚠ Linux 清除 DNS 缓存失败,可手动执行: "
                         "sudo resolvectl flush-caches")
            return ok
        if IS_MAC:
            # macOS: 需 sudo; 普通用户会提示权限不足,这里尽量尝试
            ok = self.run_cmd('sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder',
                              timeout=15)
            if ok:
                self.log("  ✓ DNS 缓存已清除 (macOS)")
            else:
                self.log("  ⚠ macOS 清除 DNS 需管理员权限(sudo),"
                         "请在本机终端运行: sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder")
            return ok
        if self.run_cmd('ipconfig /flushdns'):
            self.log("  ✓ DNS 缓存已清除")
            return True
        else:
            self.log("  ✗ DNS 缓存清除失败")
            return False

    def flush_arp(self):
        if IS_MAC:
            self.log("[操作] 清除 ARP 缓存...")
            self.run_cmd('sudo arp -ad', timeout=10)
            self.log("  ✓ ARP 缓存已清除 (macOS)")
            return True
        if not IS_WINDOWS:
            self.log("  ⚠ 清除 ARP 仅支持 Windows/macOS")
            return False
        self.log("[操作] 清除 ARP 缓存...")
        if self.run_cmd('netsh interface ip delete arpcache'):
            self.log("  ✓ ARP 缓存已清除")
            return True
        else:
            self.log("  ✗ ARP 缓存清除失败")
            return False

    def renew_dhcp(self):
        if not IS_WINDOWS:
            self.log("  ⚠ 刷新 DHCP 仅支持 Windows")
            return False
        self.log("[操作] 刷新 DHCP...")
        self.run_cmd('ipconfig /release', timeout=10)
        self.run_cmd('ipconfig /renew', timeout=15)
        self.log("  ✓ DHCP 已刷新")
        return True

    def restore_static_ip(self):
        if not IS_WINDOWS:
            return
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
        if not IS_WINDOWS:
            return
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
        if not IS_WINDOWS:
            return
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
                self.log("  ✗ 未找到 macOS 网络服务")
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
                self.log("  ✗ 未找到 macOS 网络服务")
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
            self.log("⚠ 完整网络重置(重置 Winsock/TCP-IP/ARP/DHCP/静态IP)仅支持 Windows。")
            self.log("  → 在 macOS 上请使用「代理修复」标签页修复代理,或终端手动处理。")
            return
        self.log("=" * 50)
        self.log("🔄 开始完整网络重置")
        self.log("=" * 50)
        self.log("")
        self.backup_static_ip()
        self._backup_proxy()
        self.log("")
        if self._cancel:
            self.log("")
            self.log("⏹ 已取消,未执行的步骤已跳过")
            return
        self.reset_winsock()
        self.log("")
        if self._cancel:
            self.log("")
            self.log("⏹ 已取消,未执行的步骤已跳过")
            return
        self.reset_tcpip()
        self.log("")
        if self._cancel:
            self.log("")
            self.log("⏹ 已取消,未执行的步骤已跳过")
            return
        self.flush_dns()
        self.flush_arp()
        self.log("")
        if self._cancel:
            self.log("")
            self.log("⏹ 已取消,未执行的步骤已跳过")
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

class NetworkDiagnostic:
    """诊断工具类"""

    _decode_output = staticmethod(decode_output)

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
                return False, None, 100, "(无输出)"

            # ---- 是否收到回复 ----
            has_reply = ('Reply from' in output or '来自' in output or '回复' in output
                         or 'bytes from' in output.lower() or 'bytes=' in output)
            if not has_reply:
                return False, None, 100, output.strip()

            # ---- 平均延迟 ----
            avg_ms = None
            m = re.search(r'(?:Average|平均)\s*=\s*(\d+)ms', output, re.I)
            if m:
                avg_ms = int(m.group(1))
            else:
                m = re.search(r'(?:min/avg/max(?:/\w+)?\s*=\s*|round-trip[^=]*=\s*)'
                              r'[\d.]+/([\d.]+)/[\d.]+', output, re.I)
                if m:
                    avg_ms = int(float(m.group(1)))

            # ---- 丢包率 ----
            loss = 0
            m = re.search(r'(\d+(?:\.\d+)?)%\s*(?:loss|丢失|packet loss)', output, re.I)
            if m:
                loss = int(float(m.group(1)))
            else:
                m = re.search(r'\((\d+)%\s*(?:loss|丢失)\)', output, re.I)
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
            return False, None, 100, '当前系统未找到 ping 命令'
        except Exception as e:
            return False, None, 100, str(e)

    @staticmethod
    def _parse_nslookup(output, dns_server=None):
        """解析 nslookup 输出，跳过 DNS 服务器自身地址，只取应答区 IP。"""
        text = output or ""
        parts = re.split(r'(?:Non-authoritative answer|非权威应答)\s*:?', text,
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
            return False, None, "当前系统未找到 nslookup 命令"
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
            return output.strip() or "(无输出，目标可能不可达或已被防火墙拦截)"
        except subprocess.TimeoutExpired:
            return "追踪超时(90秒)，目标可能不可达"
        except FileNotFoundError:
            return ("当前系统未找到 tracert 命令" if IS_WINDOWS
                    else "当前系统未找到 traceroute 命令（Linux 可安装 traceroute 包）")
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
                    self.log("  ⚠ 未找到 macOS 网络服务,无法设置系统代理")
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