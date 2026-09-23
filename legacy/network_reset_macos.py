#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macOS 网络工具箱 v3.1 - GUI 版本
网络重置 + DNS切换 + 网络诊断，保留静态IP设置

⚠️ 注意: 此脚本需要 sudo 权限运行
运行方式: sudo python3 network_reset_macos.py
"""

import os
import sys
import subprocess
import threading
import re
import tkinter as tk
from tkinter import ttk, messagebox
import time


def is_admin():
    """检查是否有管理员权限 (root)"""
    try:
        return os.geteuid() == 0
    except:
        return False


# ===== DNS 预设配置 =====
DNS_PRESETS = {
    "自动获取(DHCP)": {"mode": "dhcp", "primary": "", "secondary": ""},
    "阿里 DNS":    {"mode": "static", "primary": "223.5.5.5",  "secondary": "223.6.6.6"},
    "Google DNS": {"mode": "static", "primary": "8.8.8.8",    "secondary": "8.8.4.4"},
    "Cloudflare": {"mode": "static", "primary": "1.1.1.1",    "secondary": "1.0.0.1"},
    "114 DNS":    {"mode": "static", "primary": "114.114.114.114", "secondary": "114.114.115.115"},
}


class NetworkResetTool:
    """网络重置核心类 - macOS 版"""

    NETWORK_INTERFACES = [
        ("Wi-Fi", "en0"),
        ("Ethernet", "en1"),
        ("Ethernet 2", "en2"),
        ("Thunderbolt Ethernet", "en3"),
        ("USB Ethernet", "en5"),
    ]

    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.static_configs = []
        self.primary_interface = "en0"

    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    def run_cmd(self, cmd, show_output=False, timeout=10):
        """执行命令"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=timeout)
            if show_output and result.stdout:
                self.log(result.stdout.strip())
            if result.returncode != 0 and result.stderr:
                self.log(f"  警告: {result.stderr.strip()}")
            return result.returncode == 0, result.stdout
        except subprocess.TimeoutExpired:
            self.log(f"  超时: {cmd[:50]}...")
            return False, ""
        except Exception as e:
            self.log(f"  错误: {e}")
            return False, ""

    def get_network_services(self):
        """获取所有网络服务列表"""
        try:
            result = subprocess.run(
                ['networksetup', '-listallnetworkservices'],
                capture_output=True, text=True, encoding='utf-8', errors='replace'
            )
            services = []
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]:
                    line = line.strip()
                    if line and not line.startswith('*'):
                        services.append(line)
            return services
        except Exception as e:
            self.log(f"  获取网络服务失败: {e}")
            return ["Wi-Fi", "Ethernet"]

    def get_primary_interface(self):
        """获取主网络接口"""
        try:
            result = subprocess.run(
                ['route', '-n', 'get', 'default'],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'interface' in line:
                        return line.split(':')[1].strip()
        except:
            pass
        return "en0"

    def get_primary_service(self):
        """获取主网络服务名称"""
        primary = self.get_primary_interface()
        try:
            result = subprocess.run(
                ['networksetup', '-listnetworkserviceorder'],
                capture_output=True, text=True, encoding='utf-8', errors='replace'
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for i, line in enumerate(lines):
                    if primary in line and 'Device' in line:
                        # 往上找服务名
                        for j in range(i - 1, max(i - 3, 0), -1):
                            if '(' in lines[j]:
                                # 提取括号内的服务名
                                match = re.search(r'\(([^)]+)\)', lines[j])
                                if match:
                                    return match.group(1)
        except:
            pass
        return "Wi-Fi"

    def get_current_dns(self, service=None):
        """获取当前 DNS 配置"""
        if not service:
            service = self.get_primary_service()
        try:
            result = subprocess.run(
                ['networksetup', '-getdnsservers', service],
                capture_output=True, text=True, encoding='utf-8', errors='replace'
            )
            if result.returncode == 0:
                dns_str = result.stdout.strip()
                if dns_str and "aren't any DNS" not in dns_str:
                    return dns_str.replace('\n', ', '), 'static'
                else:
                    return "DHCP自动获取", 'dhcp'
        except:
            pass
        return "未知", 'unknown'

    def set_dns(self, service, primary, secondary=None):
        """设置静态 DNS"""
        cmd = f'networksetup -setdnsservers "{service}" {primary}'
        if secondary:
            cmd += f' {secondary}'
        ok, _ = self.run_cmd(cmd)
        return ok

    def set_dhcp_dns(self, service):
        """设置为 DHCP DNS"""
        ok, _ = self.run_cmd(f'networksetup -setdnsservers "{service}" empty')
        return ok

    def switch_dns(self, preset_name, service=None):
        """切换 DNS 到预设值"""
        if not service:
            service = self.get_primary_service()
        preset = DNS_PRESETS.get(preset_name)
        if not preset:
            self.log(f"  未知预设: {preset_name}")
            return False

        if preset["mode"] == "dhcp":
            if self.set_dhcp_dns(service):
                self.log(f"  ✓ 已切换为 DHCP 自动获取 DNS")
                return True
        else:
            if self.set_dns(service, preset["primary"], preset.get("secondary")):
                self.log(f"  ✓ 已切换为 {preset_name} ({preset['primary']}")
                if preset.get("secondary"):
                    self.log(f"    备用: {preset['secondary']})")
                return True
        return False

    def backup_static_ip(self):
        """备份静态IP配置"""
        self.log("[阶段 1/6] 备份静态IP配置...")

        services = self.get_network_services()
        found_static = False

        for service in services:
            try:
                result = subprocess.run(
                    ['networksetup', '-getinfo', service],
                    capture_output=True, text=True, encoding='utf-8', errors='replace'
                )
                if result.returncode == 0:
                    output = result.stdout
                    if 'Manual' in output or 'Manually' in output:
                        found_static = True
                        config = {'service': service}

                        for line in output.split('\n'):
                            line = line.strip()
                            if line.startswith('IP address:'):
                                config['ip'] = line.split(':')[1].strip()
                            elif line.startswith('Subnet mask:'):
                                config['mask'] = line.split(':')[1].strip()
                            elif line.startswith('Router:'):
                                config['gateway'] = line.split(':')[1].strip()

                        dns_result = subprocess.run(
                            ['networksetup', '-getdnsservers', service],
                            capture_output=True, text=True, encoding='utf-8', errors='replace'
                        )
                        if dns_result.returncode == 0 and dns_result.stdout.strip():
                            dns_servers = dns_result.stdout.strip().split('\n')
                            if dns_servers and dns_servers[0] not in ["There aren't any DNS servers", '']:
                                config['dns'] = ','.join(dns_servers)

                        if 'ip' in config:
                            self.static_configs.append(config)
                            self.log(f"  ✓ 备份: {service} - IP: {config['ip']}")
            except Exception as e:
                self.log(f"  处理 {service} 时出错: {e}")

        if not found_static:
            self.log("  未发现静态IP配置 (全部使用DHCP)")

    def reset_winsock(self):
        """重置网络接口"""
        self.log("[阶段 2/6] 重置网络接口...")

        primary = self.get_primary_interface()
        self.log(f"  主接口: {primary}")

        success = True

        if self.run_cmd(f'ifconfig {primary} down')[0]:
            self.log(f"  ✓ 已关闭接口 {primary}")
        else:
            self.log(f"  ⚠ 关闭接口失败")
            success = False

        time.sleep(1)

        if self.run_cmd(f'ifconfig {primary} up')[0]:
            self.log(f"  ✓ 已重新启用接口 {primary}")
        else:
            self.log(f"  ⚠ 重新启用失败")
            success = False

        services = self.get_network_services()
        for service in services[:3]:
            self.run_cmd(f'networksetup -setnetworkserviceenabled "{service}" off')

        time.sleep(1)

        for service in services[:3]:
            self.run_cmd(f'networksetup -setnetworkserviceenabled "{service}" on')

        if success:
            self.log("  ✓ 网络接口重置完成")

    def reset_tcpip(self):
        """重置 TCP/IP 协议栈"""
        self.log("[阶段 3/6] 重置 TCP/IP 协议栈...")

        primary = self.get_primary_interface()

        if self.run_cmd(f'ipconfig set {primary} DHCP')[0]:
            self.log(f"  ✓ 已将 {primary} 设置为 DHCP")

        services = self.get_network_services()
        for service in services[:2]:
            self.run_cmd(f'networksetup -setv6off "{service}"')

        self.log("  ✓ IPv6 已关闭")

        if self.run_cmd('route -n flush')[0]:
            self.log("  ✓ 路由表已清除")

        self.log("  ✓ TCP/IP 协议栈重置完成")

    def flush_cache(self):
        """清除缓存"""
        self.log("[阶段 4/6] 清除缓存...")

        if self.run_cmd('dscacheutil -flushcache')[0]:
            self.log("  ✓ DNS 缓存已清除")

        if self.run_cmd('killall -HUP mDNSResponder')[0]:
            self.log("  ✓ mDNSResponder 已重启")

        if self.run_cmd('arp -d -a')[0]:
            self.log("  ✓ ARP 缓存已清除")

        self.log("  ✓ 缓存清除完成")

    def renew_dhcp(self):
        """刷新 DHCP"""
        self.log("[阶段 5/6] 刷新 DHCP...")

        primary = self.get_primary_interface()

        if self.run_cmd(f'ipconfig set {primary} NONE')[0]:
            self.log(f"  ✓ 已释放 {primary} 的 IP")

        time.sleep(2)

        if self.run_cmd(f'ipconfig set {primary} DHCP')[0]:
            self.log(f"  ✓ 已重新获取 IP")

        try:
            result = subprocess.run(
                ['ifconfig', primary],
                capture_output=True, text=True, encoding='utf-8', errors='replace'
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'inet ' in line and 'inet6' not in line:
                        self.log(f"  当前 IP: {line.strip()}")
                        break
        except:
            pass

        self.log("  ✓ DHCP 刷新完成")

    def restore_static_ip(self):
        """恢复静态IP配置"""
        self.log("[阶段 6/6] 恢复静态IP配置...")

        if not self.static_configs:
            self.log("  无需恢复")
            return

        for cfg in self.static_configs:
            service = cfg.get('service', '')
            ip = cfg.get('ip', '')
            mask = cfg.get('mask', '')
            gateway = cfg.get('gateway', '')
            dns = cfg.get('dns', '')

            if ip and service:
                self.log(f"  恢复: {service}")
                cmd = f'networksetup -setmanual "{service}" {ip} {mask} {gateway}'
                if self.run_cmd(cmd)[0]:
                    self.log(f"    ✓ IP: {ip}")

                if dns:
                    dns_list = dns.split(',')
                    dns_cmd = f'networksetup -setdnsservers "{service}" ' + ' '.join(dns_list)
                    if self.run_cmd(dns_cmd)[0]:
                        self.log(f"    ✓ DNS: {dns}")

        self.log("  ✓ 静态IP恢复完成")

    def run_full_reset(self):
        """执行完整重置"""
        self.backup_static_ip()
        self.reset_winsock()
        self.reset_tcpip()
        self.flush_cache()
        self.renew_dhcp()
        self.restore_static_ip()
        self.log("")
        self.log("=" * 50)
        self.log("🎉 网络重置完成！")
        self.log("=" * 50)


class NetworkDiagnostic:
    """网络诊断类 - macOS 版"""

    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def log(self, msg, color=None):
        if self.log_callback:
            self.log_callback(msg, color)

    def ping(self, target, count=4):
        """Ping 测试"""
        try:
            result = subprocess.run(
                ['ping', '-c', str(count), '-W', '3', target],
                capture_output=True, timeout=count * 3 + 5
            )
            output = result.stdout.decode('utf-8', errors='replace')

            has_reply = 'bytes from' in output
            m = re.search(r'(\d+)% packet loss', output)
            loss = int(m.group(1)) if m else 100

            m = re.search(r'rtt min/avg/max/\w+\s*=\s*[\d.]+/([\d.]+)', output)
            avg = float(m.group(1)) if m else None

            return has_reply, avg, loss
        except subprocess.TimeoutExpired:
            return False, None, 100
        except Exception as e:
            return False, None, 100

    def dns_lookup(self, target, dns_server=None):
        """DNS 解析测试"""
        try:
            cmd = ['nslookup', target]
            if dns_server:
                cmd.append(dns_server)
            result = subprocess.run(
                cmd, capture_output=True, timeout=10
            )
            output = result.stdout.decode('utf-8', errors='replace')

            ipv4_addrs = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', output)
            ip = ipv4_addrs[-1] if ipv4_addrs else None  # nslookup 显示的最后一个 IP 是解析结果
            success = ip is not None
            return success, ip, output
        except Exception as e:
            return False, None, str(e)

    def get_overview(self):
        """获取网络状态总览"""
        results = []

        # 主接口
        try:
            result = subprocess.run(
                ['route', '-n', 'get', 'default'],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'interface' in line:
                        iface = line.split(':')[1].strip()
                        results.append(("主接口", iface))
                    elif 'gateway' in line and 'default' not in line:
                        gw = line.split(':')[1].strip()
                        results.append(("默认网关", gw))
        except:
            pass

        # IP 配置
        try:
            primary = results[0][1] if results else "en0"
            result = subprocess.run(
                ['ifconfig', primary],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'inet ' in line and 'inet6' not in line:
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            results.append(("IP 地址", parts[1]))
                    elif 'status' in line:
                        status = line.split(':')[1].strip()
                        results.append(("连接状态", status))
        except:
            pass

        # DNS
        try:
            result = subprocess.run(
                ['scutil', '--dns'],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'nameserver' in line and '#' not in line:
                        ns = line.split(':')[1].strip()
                        if ns and ns[0].isdigit():
                            results.append(("DNS 服务器", ns))
                            break
        except:
            pass

        return results

    def quick_ping(self):
        """快速 ping 测试"""
        targets = [
            ("baidu.com", "百度"),
            ("8.8.8.8", "Google DNS"),
            ("1.1.1.1", "Cloudflare"),
            ("114.114.114.114", "114 DNS"),
        ]
        results = []
        for target, name in targets:
            ok, avg, loss = self.ping(target, count=2)
            results.append((name, target, ok, avg, loss))
        return results

    def full_diagnostic(self, log_fn=None):
        """完整诊断"""
        if log_fn:
            log_fn("=== 网络诊断开始 ===")

        # 概览
        if log_fn:
            log_fn("\n--- 网络概览 ---")
        overview = self.get_overview()
        for k, v in overview:
            if log_fn:
                log_fn(f"  {k}: {v}")

        # 快速 ping
        if log_fn:
            log_fn("\n--- 连接测试 ---")
        ping_results = self.quick_ping()
        for name, target, ok, avg, loss in ping_results:
            status = "✓ 正常" if ok else "✗ 失败"
            ms = f" ({avg:.0f}ms)" if avg else ""
            loss_str = f" 丢包{loss}%" if loss > 0 else ""
            if log_fn:
                log_fn(f"  {name} ({target}): {status}{ms}{loss_str}")

        # DNS 解析
        if log_fn:
            log_fn("\n--- DNS 解析 ---")
        success, ip, _ = self.dns_lookup("baidu.com")
        if log_fn:
            log_fn(f"  baidu.com → {ip or '解析失败'} ({'✓' if success else '✗'})")

        success, ip, _ = self.dns_lookup("google.com")
        if log_fn:
            log_fn(f"  google.com → {ip or '解析失败'} ({'✓' if success else '✗'})")

        if log_fn:
            log_fn("\n=== 诊断完成 ===")

        return overview, ping_results


# ===== 配色方案 (Catppuccin Mocha) =====
COLORS = {
    "bg": "#1e1e2e",
    "surface": "#313244",
    "overlay": "#45475a",
    "text": "#cdd6f4",
    "subtext": "#a6adc8",
    "accent": "#89b4fa",
    "green": "#a6e3a1",
    "red": "#f38ba8",
    "orange": "#fab387",
    "blue": "#89b4fa",
    "sky": "#89dceb",
    "pink": "#f5c2e7",
    "yellow": "#f9e2af",
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("macOS 网络工具箱 v3.1")
        self.geometry("720x620")
        self.resizable(True, True)
        self.configure(bg=COLORS["bg"])
        self._running = False
        self._build_ui()

    def _build_ui(self):
        # 顶部标题栏
        topbar = tk.Frame(self, bg=COLORS["surface"], pady=12)
        topbar.pack(fill="x")

        tk.Label(topbar, text="🍎 网络工具箱 v3.1",
                 font=("PingFang SC", 18, "bold"), fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(topbar, text="网络重置 + DNS切换 + 诊断",
                 font=("PingFang SC", 10), fg=COLORS["subtext"], bg=COLORS["surface"]).pack()

        # Tab 控制
        tab_frame = tk.Frame(self, bg=COLORS["bg"])
        tab_frame.pack(fill="x", padx=10, pady=(10, 0))

        self._tab = "reset"
        self._tab_btns = {}
        for tab_id, label in [("reset", "🔄 网络重置"), ("dns", "🌐 DNS切换"), ("diag", "🔍 网络诊断")]:
            btn = tk.Button(tab_frame, text=label, font=("PingFang SC", 11, "bold"),
                            bg=COLORS["accent"] if tab_id == "reset" else COLORS["surface"],
                            fg=COLORS["bg"] if tab_id == "reset" else COLORS["subtext"],
                            relief="flat", padx=16, pady=6,
                            command=lambda t=tab_id: self._switch_tab(t))
            btn.pack(side="left", padx=3)
            self._tab_btns[tab_id] = btn

        # 内容区域 - 3 个 frame
        self._frames = {}
        for tab_id in ("reset", "dns", "diag"):
            f = tk.Frame(self, bg=COLORS["bg"])
            self._frames[tab_id] = f

        self._build_reset_tab()
        self._build_dns_tab()
        self._build_diag_tab()

        self._frames["reset"].pack(fill="both", expand=True, padx=10, pady=5)

    def _switch_tab(self, tab_id):
        for f in self._frames.values():
            f.pack_forget()
        self._frames[tab_id].pack(fill="both", expand=True, padx=10, pady=5)
        self._tab = tab_id
        for tid, btn in self._tab_btns.items():
            btn.configure(bg=COLORS["accent"] if tid == tab_id else COLORS["surface"],
                          fg=COLORS["bg"] if tid == tab_id else COLORS["subtext"])

    # ---- 网络重置 Tab ----
    def _build_reset_tab(self):
        f = self._frames["reset"]

        # 功能说明
        info = tk.Frame(f, bg=COLORS["bg"], pady=8)
        info.pack(fill="x")

        features = [
            ("🔄 重置网络接口", "关闭并重新启用"),
            ("🔄 重置 TCP/IP", "重置协议栈，清除路由"),
            ("🧹 清除缓存", "DNS + ARP 缓存"),
            ("🔄 刷新 DHCP", "重新获取 IP"),
            ("💾 保留静态IP", "自动备份恢复"),
        ]
        for i, (title, desc) in enumerate(features):
            row = i // 2
            col = i % 2
            item = tk.Frame(info, bg=COLORS["surface"], padx=10, pady=6)
            item.grid(row=row, column=col, padx=4, pady=2, sticky="w")
            tk.Label(item, text=title, font=("PingFang SC", 10, "bold"),
                     fg=COLORS["accent"], bg=COLORS["surface"]).pack(anchor="w")
            tk.Label(item, text=desc, font=("PingFang SC", 9),
                     fg=COLORS["subtext"], bg=COLORS["surface"]).pack(anchor="w")

        # 进度条
        self._reset_progress = ttk.Progressbar(f, mode="indeterminate")
        self._reset_progress.pack(fill="x", padx=5, pady=8)

        # 日志
        tk.Label(f, text="执行日志:", font=("PingFang SC", 10),
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(anchor="w", padx=5)

        log_container = tk.Frame(f, bg="#181825")
        log_container.pack(fill="both", expand=True, pady=5)

        scrollbar = tk.Scrollbar(log_container)
        scrollbar.pack(side="right", fill="y")

        self._reset_log = tk.Text(log_container, font=("Menlo", 10), bg="#181825", fg=COLORS["text"],
                                  insertbackground=COLORS["text"], relief="flat", bd=0,
                                  state="disabled", yscrollcommand=scrollbar.set)
        self._reset_log.pack(fill="both", expand=True, padx=5, pady=5)
        scrollbar.config(command=self._reset_log.yview)

        # 按钮
        btn_frame = tk.Frame(f, bg=COLORS["bg"], pady=8)
        btn_frame.pack()

        self._btn_reset = tk.Button(btn_frame, text="🔄 开始重置", font=("PingFang SC", 12, "bold"),
                                    bg=COLORS["accent"], fg=COLORS["bg"], relief="flat", padx=25, pady=8,
                                    command=self._start_reset)
        self._btn_reset.pack(side="left", padx=8)

        self._btn_restart = tk.Button(btn_frame, text="🔄 重启网络服务", font=("PingFang SC", 12),
                                      bg=COLORS["yellow"], fg=COLORS["bg"], relief="flat", padx=25, pady=8,
                                      command=self._restart_network)
        self._btn_restart.pack(side="left", padx=8)

        # 权限检查
        if not is_admin():
            self._log_reset("⚠ 未以 sudo 运行，部分功能受限", COLORS["yellow"])
            self._log_reset("  建议: sudo python3 network_reset_macos.py", COLORS["yellow"])
        else:
            self._log_reset("✓ 已获取 root 权限", COLORS["green"])

        self._show_network_info()

    # ---- DNS 切换 Tab ----
    def _build_dns_tab(self):
        f = self._frames["dns"]

        # 当前 DNS 状态
        status_frame = tk.Frame(f, bg=COLORS["surface"], padx=15, pady=10)
        status_frame.pack(fill="x", pady=8)

        tk.Label(status_frame, text="当前 DNS 配置", font=("PingFang SC", 12, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack(anchor="w")

        self._dns_status_label = tk.Label(status_frame, text="检测中...",
                                          font=("Menlo", 10), fg=COLORS["green"], bg=COLORS["surface"])
        self._dns_status_label.pack(anchor="w", pady=5)

        self._dns_service_label = tk.Label(status_frame, text="",
                                           font=("PingFang SC", 9), fg=COLORS["subtext"], bg=COLORS["surface"])
        self._dns_service_label.pack(anchor="w")

        # DNS 预设按钮
        tk.Label(f, text="点击切换 DNS:", font=("PingFang SC", 11, "bold"),
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(anchor="w", pady=(10, 5))

        presets_frame = tk.Frame(f, bg=COLORS["bg"])
        presets_frame.pack(fill="x", pady=5)

        dns_colors = {
            "自动获取(DHCP)": COLORS["subtext"],
            "阿里 DNS": COLORS["orange"],
            "Google DNS": COLORS["blue"],
            "Cloudflare": COLORS["sky"],
            "114 DNS": COLORS["pink"],
        }

        for i, (name, cfg) in enumerate(DNS_PRESETS.items()):
            btn = tk.Button(presets_frame, text=name, font=("PingFang SC", 10, "bold"),
                            bg=dns_colors.get(name, COLORS["accent"]),
                            fg=COLORS["bg"], relief="flat", padx=16, pady=8,
                            command=lambda n=name: self._switch_dns(n))
            btn.grid(row=i // 3, column=i % 3, padx=4, pady=4, sticky="ew")

        presets_frame.columnconfigure(0, weight=1)
        presets_frame.columnconfigure(1, weight=1)
        presets_frame.columnconfigure(2, weight=1)

        # DNS 操作日志
        tk.Label(f, text="操作日志:", font=("PingFang SC", 10),
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(anchor="w", pady=(10, 0))

        log_container = tk.Frame(f, bg="#181825")
        log_container.pack(fill="both", expand=True, pady=5)

        scrollbar = tk.Scrollbar(log_container)
        scrollbar.pack(side="right", fill="y")

        self._dns_log = tk.Text(log_container, font=("Menlo", 10), bg="#181825", fg=COLORS["text"],
                                insertbackground=COLORS["text"], relief="flat", bd=0,
                                state="disabled", yscrollcommand=scrollbar.set)
        self._dns_log.pack(fill="both", expand=True, padx=5, pady=5)
        scrollbar.config(command=self._dns_log.yview)

        # 刷新 DNS 状态
        self._refresh_dns_status()

    # ---- 网络诊断 Tab ----
    def _build_diag_tab(self):
        f = self._frames["diag"]

        # 诊断按钮
        btn_frame = tk.Frame(f, bg=COLORS["bg"], pady=10)
        btn_frame.pack(fill="x")

        self._btn_quick = tk.Button(btn_frame, text="⚡ 快速 Ping", font=("PingFang SC", 11, "bold"),
                                    bg=COLORS["green"], fg=COLORS["bg"], relief="flat", padx=20, pady=8,
                                    command=self._quick_diag)
        self._btn_quick.pack(side="left", padx=5)

        self._btn_full = tk.Button(btn_frame, text="🔍 完整诊断", font=("PingFang SC", 11, "bold"),
                                   bg=COLORS["accent"], fg=COLORS["bg"], relief="flat", padx=20, pady=8,
                                   command=self._full_diag)
        self._btn_full.pack(side="left", padx=5)

        # 诊断日志
        log_container = tk.Frame(f, bg="#181825")
        log_container.pack(fill="both", expand=True, pady=5)

        scrollbar = tk.Scrollbar(log_container)
        scrollbar.pack(side="right", fill="y")

        self._diag_log = tk.Text(log_container, font=("Menlo", 10), bg="#181825", fg=COLORS["text"],
                                 insertbackground=COLORS["text"], relief="flat", bd=0,
                                 state="disabled", yscrollcommand=scrollbar.set)
        self._diag_log.pack(fill="both", expand=True, padx=5, pady=5)
        scrollbar.config(command=self._diag_log.yview)

    # ===== 日志辅助 =====
    def _log_reset(self, msg, color=None):
        self._reset_log.configure(state="normal")
        self._reset_log.insert("end", msg + "\n")
        self._reset_log.see("end")
        self._reset_log.configure(state="disabled")

    def _log_dns(self, msg, color=None):
        self._dns_log.configure(state="normal")
        self._dns_log.insert("end", msg + "\n")
        self._dns_log.see("end")
        self._dns_log.configure(state="disabled")

    def _log_diag(self, msg, color=None):
        self._diag_log.configure(state="normal")
        self._diag_log.insert("end", msg + "\n")
        self._diag_log.see("end")
        self._diag_log.configure(state="disabled")

    # ===== 网络信息 =====
    def _show_network_info(self):
        self._log_reset("\n当前网络接口:", COLORS["accent"])
        try:
            result = subprocess.run(
                ['networksetup', '-listallhardwareports'],
                capture_output=True, text=True, encoding='utf-8', errors='replace'
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                current_port = None
                for line in lines:
                    if line.startswith('Hardware Port:'):
                        current_port = line.split(':')[1].strip()
                    elif line.startswith('Device:') and current_port:
                        device = line.split(':')[1].strip()
                        self._log_reset(f"  • {current_port} ({device})")
                        current_port = None
        except:
            pass
        self._log_reset("")

    def _refresh_dns_status(self):
        """异步刷新 DNS 状态"""
        def _do():
            tool = NetworkResetTool()
            service = tool.get_primary_service()
            dns_str, mode = tool.get_current_dns(service)
            self.after(0, lambda: self._dns_status_label.config(text=f"DNS: {dns_str}"))
            self.after(0, lambda: self._dns_service_label.config(text=f"网卡: {service}"))

        threading.Thread(target=_do, daemon=True).start()

    # ===== 网络重置 =====
    def _start_reset(self):
        if self._running:
            return
        if not messagebox.askyesno("确认", "即将重置网络配置\n\n确定要继续吗？"):
            return

        self._running = True
        self._btn_reset.config(state="disabled")
        self._reset_log.configure(state="normal")
        self._reset_log.delete("1.0", "end")
        self._reset_log.configure(state="disabled")
        self._reset_progress.start(12)

        threading.Thread(target=self._do_reset, daemon=True).start()

    def _do_reset(self):
        tool = NetworkResetTool(log_callback=lambda m: self.after(0, lambda: self._log_reset(m)))
        tool.run_full_reset()
        self.after(0, self._reset_done)

    def _reset_done(self):
        self._running = False
        self._reset_progress.stop()
        self._btn_reset.config(state="normal")

    def _restart_network(self):
        if messagebox.askyesno("确认", "确定要重启网络服务吗？\n\n这将暂时断开网络。"):
            self._log_reset("正在重启网络服务...", COLORS["yellow"])
            subprocess.run(['networksetup', '-setairportpower', 'en0', 'off'], capture_output=True)
            time.sleep(2)
            subprocess.run(['networksetup', '-setairportpower', 'en0', 'on'], capture_output=True)
            self._log_reset("✓ 网络服务已重启", COLORS["green"])

    # ===== DNS 切换 =====
    def _switch_dns(self, preset_name):
        if self._running:
            return
        self._log_dns(f"\n切换 DNS → {preset_name}")

        def _do():
            tool = NetworkResetTool(log_callback=lambda m: self.after(0, lambda: self._log_dns(m)))
            service = tool.get_primary_service()
            self.after(0, lambda: self._log_dns(f"目标网卡: {service}"))
            tool.switch_dns(preset_name, service)

            # 刷新 DNS 缓存
            tool.run_cmd('dscacheutil -flushcache')
            tool.run_cmd('killall -HUP mDNSResponder')
            self.after(0, lambda: self._log_dns("✓ DNS 缓存已刷新"))
            self.after(0, self._refresh_dns_status)

        threading.Thread(target=_do, daemon=True).start()

    # ===== 诊断 =====
    def _quick_diag(self):
        if self._running:
            return
        self._running = True
        self._btn_quick.config(state="disabled")
        self._btn_full.config(state="disabled")
        self._diag_log.configure(state="normal")
        self._diag_log.delete("1.0", "end")
        self._diag_log.configure(state="disabled")

        def _do():
            diag = NetworkDiagnostic()
            self.after(0, lambda: self._log_diag("⚡ 快速 Ping 测试\n"))

            results = diag.quick_ping()
            for name, target, ok, avg, loss in results:
                status = "✓ 正常" if ok else "✗ 失败"
                ms = f" ({avg:.0f}ms)" if avg else ""
                loss_str = f" 丢包{loss}%" if loss > 0 else ""
                color = COLORS["green"] if ok else COLORS["red"]
                self.after(0, lambda s=status, n=name, t=target, m=ms, l=loss_str: 
                           self._log_diag(f"  {n} ({t}): {s}{m}{l}"))

            self.after(0, lambda: self._log_diag("\n快速测试完成"))
            self.after(0, self._diag_done)

        threading.Thread(target=_do, daemon=True).start()

    def _full_diag(self):
        if self._running:
            return
        self._running = True
        self._btn_quick.config(state="disabled")
        self._btn_full.config(state="disabled")
        self._diag_log.configure(state="normal")
        self._diag_log.delete("1.0", "end")
        self._diag_log.configure(state="disabled")

        def _do():
            diag = NetworkDiagnostic()
            diag.full_diagnostic(log_fn=lambda m: self.after(0, lambda: self._log_diag(m)))
            self.after(0, self._diag_done)

        threading.Thread(target=_do, daemon=True).start()

    def _diag_done(self):
        self._running = False
        self._btn_quick.config(state="normal")
        self._btn_full.config(state="normal")


def main():
    if sys.platform != 'darwin':
        print("错误: 此工具仅支持 macOS")
        print("当前系统:", sys.platform)
        sys.exit(1)

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
