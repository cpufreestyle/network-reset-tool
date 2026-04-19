#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows 网络重置工具 - GUI 版本
重置网络配置，修复网络问题，保留静态IP设置
"""

import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import tempfile
import ctypes


def is_admin():
    """检查是否有管理员权限"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


class NetworkResetTool:
    """网络重置核心类"""
    
    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.static_configs = []
    
    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)
    
    def run_cmd(self, cmd, show_output=False):
        """执行命令"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='gbk', errors='ignore')
            if show_output and result.stdout:
                self.log(result.stdout.strip())
            return result.returncode == 0
        except Exception as e:
            self.log(f"  错误: {e}")
            return False
    
    def backup_static_ip(self):
        """备份静态IP配置"""
        self.log("[阶段 1/6] 备份静态IP配置...")
        
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
                                   capture_output=True, text=True, encoding='utf-8')
            if result.stdout.strip():
                for line in result.stdout.strip().split('\n'):
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
                self.log("  未发现静态IP配置")
        except Exception as e:
            self.log(f"  备份失败: {e}")
    
    def reset_winsock(self):
        """重置 Winsock"""
        self.log("[阶段 2/6] 重置 Winsock...")
        if self.run_cmd('netsh winsock reset'):
            self.log("  ✓ 完成")
        else:
            self.log("  ⚠ 执行失败")
    
    def reset_tcpip(self):
        """重置 TCP/IP 协议栈"""
        self.log("[阶段 3/6] 重置 TCP/IP 协议栈...")
        self.run_cmd('netsh int ip reset')
        self.run_cmd('netsh int ipv6 reset')
        self.log("  ✓ 完成")
    
    def flush_cache(self):
        """清除缓存"""
        self.log("[阶段 4/6] 清除缓存...")
        self.run_cmd('ipconfig /flushdns')
        self.run_cmd('netsh interface ip delete arpcache')
        self.log("  ✓ 完成")
    
    def renew_dhcp(self):
        """刷新 DHCP"""
        self.log("[阶段 5/6] 刷新 DHCP...")
        self.run_cmd('ipconfig /release')
        self.log("  ✓ 已释放")
        self.run_cmd('ipconfig /renew')
        self.log("  ✓ 已更新")
    
    def restore_static_ip(self):
        """恢复静态IP配置"""
        self.log("[阶段 6/6] 恢复静态IP配置...")
        
        if not self.static_configs:
            self.log("  无需恢复")
            return
        
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
        self.title("Windows 网络重置工具 v2.0")
        self.geometry("650x500")
        self.resizable(True, True)
        self.configure(bg="#1e1e2e")
        self._running = False
        self._build_ui()
    
    def _build_ui(self):
        # 标题
        header = tk.Frame(self, bg="#313244", pady=15)
        header.pack(fill="x")
        tk.Label(header, text="🌐 Windows 网络重置工具", font=("微软雅黑", 16, "bold"), fg="#cdd6f4", bg="#313244").pack()
        tk.Label(header, text="重置网络配置，修复网络问题，保留静态IP设置", font=("微软雅黑", 9), fg="#a6adc8", bg="#313244").pack()
        
        # 功能说明
        info_frame = tk.Frame(self, bg="#1e1e2e", pady=15)
        info_frame.pack(fill="x", padx=20)
        
        features = [
            ("🔄 重置 Winsock", "修复网络套接字问题"),
            ("🔄 重置 TCP/IP", "重置网络协议栈"),
            ("🧹 清除缓存", "清理DNS和ARP缓存"),
            ("🔄 刷新 DHCP", "重新获取IP地址"),
            ("💾 保留静态IP", "自动备份并恢复静态IP配置"),
        ]
        
        for i, (title, desc) in enumerate(features):
            row = i // 2
            col = i % 2
            f = tk.Frame(info_frame, bg="#313244", padx=12, pady=8)
            f.grid(row=row, column=col, padx=5, pady=3, sticky="w")
            tk.Label(f, text=title, font=("微软雅黑", 10, "bold"), fg="#89b4fa", bg="#313244").pack(anchor="w")
            tk.Label(f, text=desc, font=("微软雅黑", 9), fg="#a6adc8", bg="#313244").pack(anchor="w")
        
        # 进度条
        self.progress = ttk.Progressbar(self, mode="indeterminate", style="green.Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=20, pady=10)
        
        # 日志
        log_frame = tk.Frame(self, bg="#1e1e2e")
        log_frame.pack(fill="both", expand=True, padx=20, pady=5)
        
        tk.Label(log_frame, text="执行日志:", font=("微软雅黑", 10), fg="#cdd6f4", bg="#1e1e2e").pack(anchor="w")
        
        log_container = tk.Frame(log_frame, bg="#181825")
        log_container.pack(fill="both", expand=True, pady=5)
        
        scrollbar = tk.Scrollbar(log_container)
        scrollbar.pack(side="right", fill="y")
        
        self.log_box = tk.Text(log_container, font=("Consolas", 10), bg="#181825", fg="#cdd6f4",
                               insertbackground="#cdd6f4", relief="flat", bd=0,
                               state="disabled", yscrollcommand=scrollbar.set)
        self.log_box.pack(fill="both", expand=True, padx=5, pady=5)
        scrollbar.config(command=self.log_box.yview)
        
        # 按钮
        btn_frame = tk.Frame(self, bg="#1e1e2e", pady=10)
        btn_frame.pack()
        
        self.btn_reset = tk.Button(btn_frame, text="🔄 开始重置", font=("微软雅黑", 12, "bold"),
                                    bg="#89b4fa", fg="#1e1e2e", relief="flat", padx=25, pady=8,
                                    command=self._start_reset)
        self.btn_reset.pack(side="left", padx=8)
        
        self.btn_restart = tk.Button(btn_frame, text="🔁 重启电脑", font=("微软雅黑", 12),
                                      bg="#f9e2af", fg="#1e1e2e", relief="flat", padx=25, pady=8,
                                      state="disabled", command=self._restart)
        self.btn_restart.pack(side="left", padx=8)
        
        # 样式
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("green.Horizontal.TProgressbar", troughcolor="#313244", background="#a6e3a1", thickness=10)
        
        # 检查管理员权限
        if not is_admin():
            self._log("⚠ 警告: 未以管理员身份运行，部分功能可能受限", "#f9e2af")
            self._log("  建议右键选择[以管理员身份运行]", "#f9e2af")
    
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
    
    def _restart(self):
        if messagebox.askyesno("确认重启", "网络重置后需要重启电脑才能生效\n\n确定要立即重启吗？"):
            subprocess.run('shutdown /r /t 5', shell=True)
            self._log("5秒后重启电脑...")


if __name__ == "__main__":
    app = App()
    app.mainloop()
