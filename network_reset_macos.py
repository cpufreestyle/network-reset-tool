#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macOS 网络重置工具 - GUI 版本
重置网络配置，修复网络问题，保留静态IP设置

⚠️ 注意: 此脚本需要 sudo 权限运行
运行方式: sudo python3 network_reset_macos.py
"""

import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import plistlib
import tempfile


def is_admin():
    """检查是否有管理员权限 (root)"""
    try:
        return os.geteuid() == 0
    except:
        return False


class NetworkResetTool:
    """网络重置核心类 - macOS 版"""
    
    # macOS 常用网络接口
    NETWORK_INTERFACES = [
        ("Wi-Fi", "en0"),
        ("Ethernet", "en1"),
        ("Ethernet 2", "en2"),
        ("Thunderbolt Ethernet", "en3"),
        ("Thunderbolt Ethernet 2", "en4"),
        ("USB Ethernet", "en5"),
        ("iPhone USB", "en6"),
    ]
    
    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.static_configs = []
        self.primary_interface = "en0"  # 默认主接口
    
    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)
    
    def run_cmd(self, cmd, show_output=False):
        """执行命令"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            if show_output and result.stdout:
                self.log(result.stdout.strip())
            if result.returncode != 0 and result.stderr:
                self.log(f"  警告: {result.stderr.strip()}")
            return result.returncode == 0
        except Exception as e:
            self.log(f"  错误: {e}")
            return False
    
    def get_network_services(self):
        """获取所有网络服务列表"""
        try:
            result = subprocess.run(
                ['networksetup', '-listallnetworkservices'],
                capture_output=True, text=True, encoding='utf-8'
            )
            services = []
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                # 第一行是说明文字，跳过
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
                capture_output=True, text=True, encoding='utf-8'
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'interface' in line:
                        return line.split(':')[1].strip()
        except:
            pass
        return "en0"
    
    def backup_static_ip(self):
        """备份静态IP配置 - macOS 版"""
        self.log("[阶段 1/6] 备份静态IP配置...")
        
        services = self.get_network_services()
        found_static = False
        
        for service in services:
            try:
                # 获取网络服务信息
                result = subprocess.run(
                    ['networksetup', '-getinfo', service],
                    capture_output=True, text=True, encoding='utf-8'
                )
                
                if result.returncode == 0:
                    output = result.stdout
                    # 检查是否为手动配置（静态IP）
                    if 'Manual' in output or 'Manually' in output:
                        found_static = True
                        config = {'service': service}
                        
                        # 解析配置
                        for line in output.split('\n'):
                            line = line.strip()
                            if line.startswith('IP address:'):
                                config['ip'] = line.split(':')[1].strip()
                            elif line.startswith('Subnet mask:'):
                                config['mask'] = line.split(':')[1].strip()
                            elif line.startswith('Router:'):
                                config['gateway'] = line.split(':')[1].strip()
                        
                        # 获取DNS
                        dns_result = subprocess.run(
                            ['networksetup', '-getdnsservers', service],
                            capture_output=True, text=True, encoding='utf-8'
                        )
                        if dns_result.returncode == 0 and dns_result.stdout.strip():
                            dns_servers = dns_result.stdout.strip().split('\n')
                            if dns_servers and dns_servers[0] not in ['There aren\'t any DNS servers', '']:
                                config['dns'] = ','.join(dns_servers)
                        
                        if 'ip' in config:
                            self.static_configs.append(config)
                            dns_str = f", DNS: {config.get('dns', '无')}" if config.get('dns') else ""
                            self.log(f"  ✓ 备份: {service} - IP: {config['ip']}{dns_str}")
            except Exception as e:
                self.log(f"  处理 {service} 时出错: {e}")
        
        if not found_static:
            self.log("  未发现静态IP配置 (全部使用DHCP)")
    
    def reset_winsock(self):
        """重置网络接口 (相当于 Windows 的 Winsock 重置)"""
        self.log("[阶段 2/6] 重置网络接口...")
        
        # 获取主接口
        primary = self.get_primary_interface()
        self.log(f"  主接口: {primary}")
        
        # 关闭并重新启用主网络接口
        success = True
        
        # 关闭接口
        if self.run_cmd(f'ifconfig {primary} down'):
            self.log(f"  ✓ 已关闭接口 {primary}")
        else:
            self.log(f"  ⚠ 关闭接口 {primary} 失败")
            success = False
        
        # 短暂等待
        import time
        time.sleep(1)
        
        # 重新启用接口
        if self.run_cmd(f'ifconfig {primary} up'):
            self.log(f"  ✓ 已重新启用接口 {primary}")
        else:
            self.log(f"  ⚠ 重新启用接口 {primary} 失败")
            success = False
        
        # 重置所有网络服务
        services = self.get_network_services()
        for service in services[:3]:  # 只处理前3个服务，避免太慢
            # 关闭网络服务
            self.run_cmd(f'networksetup -setnetworkserviceenabled "{service}" off')
        
        time.sleep(1)
        
        for service in services[:3]:
            # 重新启用网络服务
            self.run_cmd(f'networksetup -setnetworkserviceenabled "{service}" on')
        
        if success:
            self.log("  ✓ 网络接口重置完成")
    
    def reset_tcpip(self):
        """重置 TCP/IP 协议栈"""
        self.log("[阶段 3/6] 重置 TCP/IP 协议栈...")
        
        # 重置 IPv4 配置为 DHCP
        primary = self.get_primary_interface()
        
        # 将主接口设置为 DHCP
        if self.run_cmd(f'ipconfig set {primary} DHCP'):
            self.log(f"  ✓ 已将 {primary} 设置为 DHCP")
        else:
            self.log(f"  ⚠ 设置 DHCP 失败")
        
        # 关闭 IPv6 (可选，某些网络需要 IPv6)
        services = self.get_network_services()
        for service in services[:2]:  # 只处理 Wi-Fi 和 Ethernet
            self.run_cmd(f'networksetup -setv6off "{service}"')
        
        self.log("  ✓ IPv6 已关闭 (可在系统偏好设置中重新启用)")
        
        # 清除路由表
        if self.run_cmd('route -n flush'):
            self.log("  ✓ 路由表已清除")
        
        self.log("  ✓ TCP/IP 协议栈重置完成")
    
    def flush_cache(self):
        """清除缓存"""
        self.log("[阶段 4/6] 清除缓存...")
        
        # 清除 DNS 缓存
        if self.run_cmd('dscacheutil -flushcache'):
            self.log("  ✓ DNS 缓存已清除 (dscacheutil)")
        
        # 重启 mDNSResponder
        if self.run_cmd('killall -HUP mDNSResponder'):
            self.log("  ✓ mDNSResponder 已重启")
        
        # 清除 ARP 缓存
        if self.run_cmd('arp -d -a'):
            self.log("  ✓ ARP 缓存已清除")
        
        self.log("  ✓ 缓存清除完成")
    
    def renew_dhcp(self):
        """刷新 DHCP"""
        self.log("[阶段 5/6] 刷新 DHCP...")
        
        primary = self.get_primary_interface()
        
        # 释放 IP
        if self.run_cmd(f'ipconfig set {primary} NONE'):
            self.log(f"  ✓ 已释放 {primary} 的 IP")
        
        # 短暂等待
        import time
        time.sleep(2)
        
        # 重新获取 IP
        if self.run_cmd(f'ipconfig set {primary} DHCP'):
            self.log(f"  ✓ 已为 {primary} 重新获取 IP")
        
        # 显示新的 IP 配置
        try:
            result = subprocess.run(
                ['ifconfig', primary],
                capture_output=True, text=True, encoding='utf-8'
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
            self.log("  无需恢复 (没有静态IP配置)")
            return
        
        for cfg in self.static_configs:
            service = cfg.get('service', '')
            ip = cfg.get('ip', '')
            mask = cfg.get('mask', '')
            gateway = cfg.get('gateway', '')
            dns = cfg.get('dns', '')
            
            if ip and service:
                self.log(f"  恢复: {service}")
                
                # 设置静态 IP
                cmd = f'networksetup -setmanual "{service}" {ip} {mask} {gateway}'
                if self.run_cmd(cmd):
                    self.log(f"    ✓ IP: {ip}")
                    self.log(f"    ✓ 子网掩码: {mask}")
                    self.log(f"    ✓ 网关: {gateway}")
                else:
                    self.log(f"    ⚠ 设置失败")
                
                # 设置 DNS
                if dns:
                    dns_list = dns.split(',')
                    dns_cmd = f'networksetup -setdnsservers "{service}" ' + ' '.join(dns_list)
                    if self.run_cmd(dns_cmd):
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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("macOS 网络重置工具 v2.0")
        self.geometry("650x550")
        self.resizable(True, True)
        self.configure(bg="#1e1e2e")
        self._running = False
        self._build_ui()
    
    def _build_ui(self):
        # 标题
        header = tk.Frame(self, bg="#313244", pady=15)
        header.pack(fill="x")
        tk.Label(header, text="🍎 macOS 网络重置工具", font=("PingFang SC", 16, "bold"), fg="#cdd6f4", bg="#313244").pack()
        tk.Label(header, text="重置网络配置，修复网络问题，保留静态IP设置", font=("PingFang SC", 9), fg="#a6adc8", bg="#313244").pack()
        
        # 功能说明
        info_frame = tk.Frame(self, bg="#1e1e2e", pady=15)
        info_frame.pack(fill="x", padx=20)
        
        features = [
            ("🔄 重置网络接口", "关闭并重新启用网络接口"),
            ("🔄 重置 TCP/IP", "重置协议栈，清除路由表"),
            ("🧹 清除缓存", "清理DNS和ARP缓存"),
            ("🔄 刷新 DHCP", "重新获取IP地址"),
            ("💾 保留静态IP", "自动备份并恢复静态IP配置"),
        ]
        
        for i, (title, desc) in enumerate(features):
            row = i // 2
            col = i % 2
            f = tk.Frame(info_frame, bg="#313244", padx=12, pady=8)
            f.grid(row=row, column=col, padx=5, pady=3, sticky="w")
            tk.Label(f, text=title, font=("PingFang SC", 10, "bold"), fg="#89b4fa", bg="#313244").pack(anchor="w")
            tk.Label(f, text=desc, font=("PingFang SC", 9), fg="#a6adc8", bg="#313244").pack(anchor="w")
        
        # 进度条
        self.progress = ttk.Progressbar(self, mode="indeterminate", style="green.Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=20, pady=10)
        
        # 日志
        log_frame = tk.Frame(self, bg="#1e1e2e")
        log_frame.pack(fill="both", expand=True, padx=20, pady=5)
        
        tk.Label(log_frame, text="执行日志:", font=("PingFang SC", 10), fg="#cdd6f4", bg="#1e1e2e").pack(anchor="w")
        
        log_container = tk.Frame(log_frame, bg="#181825")
        log_container.pack(fill="both", expand=True, pady=5)
        
        scrollbar = tk.Scrollbar(log_container)
        scrollbar.pack(side="right", fill="y")
        
        self.log_box = tk.Text(log_container, font=("Menlo", 10), bg="#181825", fg="#cdd6f4",
                               insertbackground="#cdd6f4", relief="flat", bd=0,
                               state="disabled", yscrollcommand=scrollbar.set)
        self.log_box.pack(fill="both", expand=True, padx=5, pady=5)
        scrollbar.config(command=self.log_box.yview)
        
        # 按钮
        btn_frame = tk.Frame(self, bg="#1e1e2e", pady=10)
        btn_frame.pack()
        
        self.btn_reset = tk.Button(btn_frame, text="🔄 开始重置", font=("PingFang SC", 12, "bold"),
                                    bg="#89b4fa", fg="#1e1e2e", relief="flat", padx=25, pady=8,
                                    command=self._start_reset)
        self.btn_reset.pack(side="left", padx=8)
        
        self.btn_restart = tk.Button(btn_frame, text="🔄 重启网络服务", font=("PingFang SC", 12),
                                      bg="#f9e2af", fg="#1e1e2e", relief="flat", padx=25, pady=8,
                                      state="disabled", command=self._restart_network)
        self.btn_restart.pack(side="left", padx=8)
        
        # 样式
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("green.Horizontal.TProgressbar", troughcolor="#313244", background="#a6e3a1", thickness=10)
        
        # 检查管理员权限 (sudo)
        if not is_admin():
            self._log("⚠ 警告: 未以 sudo 权限运行，部分功能可能受限", "#f9e2af")
            self._log("  建议使用: sudo python3 network_reset_macos.py", "#f9e2af")
            self._log("", "#cdd6f4")
        else:
            self._log("✓ 已获取 root 权限", "#a6e3a1")
            self._log("", "#cdd6f4")
        
        # 显示网络接口信息
        self._show_network_info()
    
    def _show_network_info(self):
        """显示当前网络接口信息"""
        self._log("当前网络接口:", "#89b4fa")
        try:
            result = subprocess.run(
                ['networksetup', '-listallhardwareports'],
                capture_output=True, text=True, encoding='utf-8'
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                current_port = None
                for line in lines:
                    if line.startswith('Hardware Port:'):
                        current_port = line.split(':')[1].strip()
                    elif line.startswith('Device:') and current_port:
                        device = line.split(':')[1].strip()
                        self._log(f"  • {current_port} ({device})", "#cdd6f4")
                        current_port = None
        except:
            pass
        self._log("", "#cdd6f4")
    
    def _log(self, msg, color="#cdd6f4"):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
    
    def _start_reset(self):
        if self._running:
            return
        
        if not messagebox.askyesno("确认", "即将重置网络配置\n\n确定要继续吗？"):
            return
        
        self._running = True
        self.btn_reset.config(state="disabled")
        self.btn_restart.config(state="disabled")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.progress.start(12)
        
        threading.Thread(target=self._do_reset, daemon=True).start()
    
    def _do_reset(self):
        tool = NetworkResetTool(log_callback=lambda m: self.after(0, lambda: self._log(m)))
        tool.run_full_reset()
        self.after(0, self._reset_done)
    
    def _reset_done(self):
        self._running = False
        self.progress.stop()
        self.btn_reset.config(state="normal")
        self.btn_restart.config(state="normal")
    
    def _restart_network(self):
        """重启网络服务"""
        if messagebox.askyesno("确认", "确定要重启网络服务吗？\n\n这将暂时断开网络连接。"):
            self._log("正在重启网络服务...", "#f9e2af")
            
            # 关闭 Wi-Fi
            subprocess.run(['networksetup', '-setairportpower', 'en0', 'off'], capture_output=True)
            
            import time
            time.sleep(2)
            
            # 重新开启 Wi-Fi
            subprocess.run(['networksetup', '-setairportpower', 'en0', 'on'], capture_output=True)
            
            self._log("✓ 网络服务已重启", "#a6e3a1")


def main():
    """主函数"""
    # 检查是否在 macOS 上运行
    if sys.platform != 'darwin':
        print("错误: 此工具仅支持 macOS")
        print("当前系统:", sys.platform)
        sys.exit(1)
    
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
