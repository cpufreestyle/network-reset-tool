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
import ctypes


# ===== 单例检测 =====
_SINGLETON_MUTEX = None

def _acquire_singleton():
    """尝试获取单例 Mutex"""
    global _SINGLETON_MUTEX
    try:
        _SINGLETON_MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "NetworkResetTool_v2")
        if _SINGLETON_MUTEX == 0 or _SINGLETON_MUTEX is None:
            return True
        return (ctypes.windll.kernel32.GetLastError() != 183)
    except Exception:
        return True

_am_first = _acquire_singleton()


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
        self._cancel = False
    
    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)
    
    def run_cmd(self, cmd, show_output=False, timeout=10):
        """执行命令"""
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
        """备份静态IP配置"""
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
                self.log("  ✓ 无静态IP配置")
        except Exception as e:
            self.log(f"  备份失败: {e}")
    
    def reset_winsock(self):
        """重置 Winsock"""
        self.log("[操作] 重置 Winsock...")
        if self.run_cmd('netsh winsock reset'):
            self.log("  ✓ Winsock 重置完成")
            return True
        else:
            self.log("  ✗ Winsock 重置失败")
            return False
    
    def reset_tcpip(self):
        """重置 TCP/IP 协议栈"""
        self.log("[操作] 重置 TCP/IP 协议栈...")
        self.run_cmd('netsh int ip reset', timeout=15)
        self.run_cmd('netsh int ipv6 reset', timeout=15)
        self.log("  ✓ TCP/IP 重置完成")
        return True
    
    def flush_dns(self):
        """清除 DNS 缓存"""
        self.log("[操作] 清除 DNS 缓存...")
        if self.run_cmd('ipconfig /flushdns'):
            self.log("  ✓ DNS 缓存已清除")
            return True
        else:
            self.log("  ✗ DNS 缓存清除失败")
            return False
    
    def flush_arp(self):
        """清除 ARP 缓存"""
        self.log("[操作] 清除 ARP 缓存...")
        if self.run_cmd('netsh interface ip delete arpcache'):
            self.log("  ✓ ARP 缓存已清除")
            return True
        else:
            self.log("  ✗ ARP 缓存清除失败")
            return False
    
    def renew_dhcp(self):
        """刷新 DHCP"""
        self.log("[操作] 刷新 DHCP...")
        self.run_cmd('ipconfig /release', timeout=10)
        self.run_cmd('ipconfig /renew', timeout=15)
        self.log("  ✓ DHCP 已刷新")
        return True
    
    def restore_static_ip(self):
        """恢复静态IP配置"""
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
    
    def run_full_reset(self):
        """执行完整重置（所有步骤）"""
        self.log("=" * 50)
        self.log("🔄 开始完整网络重置")
        self.log("=" * 50)
        self.log("")
        
        self.backup_static_ip()
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
        self.log("")
        self.log("=" * 50)
        self.log("🎉 网络重置完成！")
        self.log("建议重启电脑使设置生效")
        self.log("=" * 50)


# ===== 按钮样式工厂 =====
def make_btn_style():
    """创建按钮样式"""
    return {
        'relief': "flat",
        'cursor': "hand2",
        'padx': 15,
        'pady': 6,
    }


class App(tk.Tk):
    def __init__(self):
        # 先初始化
        super().__init__()
        
        # 单例检查（必须在初始化之后）
        global _am_first
        if not _am_first:
            self.withdraw()
            self.attributes("-topmost", True)
            messagebox.showwarning("提示", "程序已在运行！\n请先关闭旧窗口。", parent=self)
            self.destroy()
            return
        
        self.title("Windows 网络重置工具 v2.1")
        self.geometry("700x580")
        self.minsize(650, 520)
        self.configure(bg="#1e1e2e")
        self._running = False
        self._current_task = None
        
        self._build_ui()
        
        # 用于存储备份的IP配置
        self._static_configs = []
    
    def _build_ui(self):
        # === 标题区 ===
        header = tk.Frame(self, bg="#313244", pady=15)
        header.pack(fill="x")
        tk.Label(header, text="🌐 Windows 网络重置工具", font=("微软雅黑", 18, "bold"), 
                 fg="#cdd6f4", bg="#313244").pack()
        tk.Label(header, text="重置网络配置 · 修复网络问题 · 保留静态IP", 
                 font=("微软雅黑", 10), fg="#a6adc8", bg="#313244").pack()
        
        # === 主按钮区 ===
        btn_area = tk.Frame(self, bg="#1e1e2e", pady=15)
        btn_area.pack(fill="x", padx=20)
        
        # 一键重置按钮（醒目）
        self.btn_all = tk.Button(btn_area, text="🚀 一键重置全部", 
                                  font=("微软雅黑", 13, "bold"),
                                  bg="#a6e3a1", fg="#1e1e2e",
                                  activebackground="#94d2b3", activeforeground="#1e1e2e",
                                  command=self._do_all_reset, **make_btn_style())
        self.btn_all.pack(fill="x", pady=(0, 12))
        
        # 分隔线
        tk.Frame(btn_area, bg="#45475a", height=1).pack(fill="x", pady=5)
        tk.Label(btn_area, text="— 单独操作 —", font=("微软雅黑", 9), 
                 fg="#6c7086", bg="#1e1e2e").pack(pady=3)
        
        # 单独功能按钮（两行 x 3列）
        btn_row1 = tk.Frame(btn_area, bg="#1e1e2e")
        btn_row1.pack(fill="x", pady=3)
        btn_row2 = tk.Frame(btn_area, bg="#1e1e2e")
        btn_row2.pack(fill="x", pady=3)
        
        # 第一行
        self._make_btn(btn_row1, "🔄 重置 Winsock", self._do_winsock, "#89b4fa").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(btn_row1, "🔄 重置 TCP/IP", self._do_tcpip, "#cba6f7").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(btn_row1, "🧹 清除 DNS", self._do_dns, "#fab387").pack(side="left", expand=True, fill="x", padx=3)
        
        # 第二行
        self._make_btn(btn_row2, "📋 清除 ARP", self._do_arp, "#94e2d5").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(btn_row2, "🔄 刷新 DHCP", self._do_dhcp, "#f5c2e7").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(btn_row2, "💾 备份IP", self._do_backup, "#f9e2af").pack(side="left", expand=True, fill="x", padx=3)
        
        # 第三行（还原IP）
        btn_row3 = tk.Frame(btn_area, bg="#1e1e2e")
        btn_row3.pack(fill="x", pady=3)
        self._make_btn(btn_row3, "📥 还原IP", self._do_restore, "#89dceb").pack(side="left", expand=True, fill="x", padx=3)
        
        # === 状态标签 ===
        self.status_label = tk.Label(self, text="就绪", font=("微软雅黑", 10), 
                                      fg="#a6e3a1", bg="#1e1e2e", anchor="w")
        self.status_label.pack(fill="x", padx=20, pady=(5, 0))
        
        # === 进度条 ===
        self.progress = ttk.Progressbar(self, mode="indeterminate", 
                                         style="green.Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=20, pady=5)
        
        # === 日志区 ===
        log_frame = tk.Frame(self, bg="#1e1e2e")
        log_frame.pack(fill="both", expand=True, padx=20, pady=5)
        
        log_header = tk.Frame(log_frame, bg="#1e1e2e")
        log_header.pack(fill="x")
        tk.Label(log_header, text="📋 执行日志", font=("微软雅黑", 10, "bold"), 
                 fg="#cdd6f4", bg="#1e1e2e").pack(side="left")
        tk.Button(log_header, text="清空", font=("微软雅黑", 9), bg="#45475a", fg="#cdd6f4",
                  relief="flat", command=self._clear_log, cursor="hand2").pack(side="right")
        
        log_container = tk.Frame(log_frame, bg="#181825")
        log_container.pack(fill="both", expand=True, pady=5)
        
        scrollbar = tk.Scrollbar(log_container)
        scrollbar.pack(side="right", fill="y")
        
        self.log_box = tk.Text(log_container, font=("Consolas", 10), 
                               bg="#181825", fg="#cdd6f4",
                               insertbackground="#cdd6f4", relief="flat", bd=0,
                               state="disabled", yscrollcommand=scrollbar.set)
        self.log_box.pack(fill="both", expand=True, padx=5, pady=5)
        scrollbar.config(command=self.log_box.yview)
        
        # === 底部按钮 ===
        bottom_frame = tk.Frame(self, bg="#1e1e2e", pady=10)
        bottom_frame.pack(fill="x", padx=20)
        
        # 左边：提示信息
        self.hint_label = tk.Label(bottom_frame, text="", font=("微软雅黑", 9), 
                                    fg="#6c7086", bg="#1e1e2e", anchor="w")
        self.hint_label.pack(side="left")
        
        # 右边：操作按钮
        btn_group = tk.Frame(bottom_frame, bg="#1e1e2e")
        btn_group.pack(side="right")
        
        self.btn_restart = tk.Button(btn_group, text="🔁 重启电脑", font=("微软雅黑", 10),
                                      bg="#f9e2af", fg="#1e1e2e",
                                      activebackground="#f9e2af", activeforeground="#1e1e2e",
                                      state="disabled", command=self._restart, **make_btn_style())
        self.btn_restart.pack(side="left", padx=5)
        
        self.btn_quit = tk.Button(btn_group, text="✕ 退出", font=("微软雅黑", 10),
                                   bg="#f38ba8", fg="#1e1e2e",
                                   activebackground="#eba0ac", activeforeground="#1e1e2e",
                                   command=self._quit, **make_btn_style())
        self.btn_quit.pack(side="left", padx=5)
        
        # === 样式 ===
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("green.Horizontal.TProgressbar", 
                        troughcolor="#313244", background="#a6e3a1", thickness=8)
        
        # === 管理员检查 ===
        if not is_admin():
            self._log("⚠ 警告: 未以管理员身份运行，部分功能可能受限")
            self._log("  → 右键选择 [以管理员身份运行] 获得完整功能")
        
        self._log("✅ 程序已就绪，请选择操作...")
    
    def _make_btn(self, parent, text, cmd, color):
        """创建功能按钮"""
        btn = tk.Button(parent, text=text, font=("微软雅黑", 10, "bold"),
                        bg=color, fg="#1e1e2e",
                        activebackground="#cdd6f4", activeforeground="#1e1e2e",
                        command=cmd, **make_btn_style())
        return btn
    
    def _log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
    
    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
    
    def _set_status(self, msg, color="#a6e3a1"):
        self.status_label.config(text=msg, fg=color)
    
    def _set_running(self, running, task=""):
        """设置运行状态"""
        self._running = running
        state_normal = "normal" if not running else "disabled"
        state_dark = "normal" if not running else "disabled"
        
        self.btn_all.config(state=state_dark)
        self.btn_restart.config(state=state_normal if task else "disabled")
        
        if running:
            self._set_status(f"⏳ 正在执行: {task}...")
            self.progress.start(10)
        else:
            self._set_status("✅ 操作完成", "#a6e3a1")
            self.progress.stop()
    
    # ===== 各个单独操作 =====
    def _do_winsock(self):
        if self._running:
            return
        self._set_running(True, "重置 Winsock")
        threading.Thread(target=self._thread_winsock, daemon=True).start()
    
    def _thread_winsock(self):
        tool = NetworkResetTool(log_callback=lambda m: self.after(0, lambda: self._log(m)))
        ok = tool.reset_winsock()
        self.after(0, lambda: self._set_running(False, ""))
        self.after(0, lambda: self._set_status("✅ Winsock 重置完成" if ok else "❌ 操作失败", 
                                                  "#a6e3a1" if ok else "#f38ba8"))
        self.after(0, lambda: self._log("\n⚠ 可能需要重启电脑使设置生效"))
    
    def _do_tcpip(self):
        if self._running:
            return
        self._set_running(True, "重置 TCP/IP")
        threading.Thread(target=self._thread_tcpip, daemon=True).start()
    
    def _thread_tcpip(self):
        tool = NetworkResetTool(log_callback=lambda m: self.after(0, lambda: self._log(m)))
        tool.reset_tcpip()
        self.after(0, lambda: self._set_running(False, ""))
        self.after(0, lambda: self._set_status("✅ TCP/IP 重置完成", "#a6e3a1"))
        self.after(0, lambda: self._log("\n⚠ 必须重启电脑使设置生效"))
    
    def _do_dns(self):
        if self._running:
            return
        self._set_running(True, "清除 DNS 缓存")
        threading.Thread(target=self._thread_dns, daemon=True).start()
    
    def _thread_dns(self):
        tool = NetworkResetTool(log_callback=lambda m: self.after(0, lambda: self._log(m)))
        ok = tool.flush_dns()
        self.after(0, lambda: self._set_running(False, ""))
        self.after(0, lambda: self._set_status("✅ DNS 缓存已清除" if ok else "❌ 操作失败",
                                                  "#a6e3a1" if ok else "#f38ba8"))
    
    def _do_arp(self):
        if self._running:
            return
        self._set_running(True, "清除 ARP 缓存")
        threading.Thread(target=self._thread_arp, daemon=True).start()
    
    def _thread_arp(self):
        tool = NetworkResetTool(log_callback=lambda m: self.after(0, lambda: self._log(m)))
        ok = tool.flush_arp()
        self.after(0, lambda: self._set_running(False, ""))
        self.after(0, lambda: self._set_status("✅ ARP 缓存已清除" if ok else "❌ 操作失败",
                                                  "#a6e3a1" if ok else "#f38ba8"))
    
    def _do_dhcp(self):
        if self._running:
            return
        self._set_running(True, "刷新 DHCP")
        threading.Thread(target=self._thread_dhcp, daemon=True).start()
    
    def _thread_dhcp(self):
        tool = NetworkResetTool(log_callback=lambda m: self.after(0, lambda: self._log(m)))
        tool.renew_dhcp()
        self.after(0, lambda: self._set_running(False, ""))
        self.after(0, lambda: self._set_status("✅ DHCP 已刷新", "#a6e3a1"))
    
    def _do_backup(self):
        if self._running:
            return
        self._set_running(True, "备份 IP 配置")
        threading.Thread(target=self._thread_backup, daemon=True).start()
    
    def _thread_backup(self):
        tool = NetworkResetTool(log_callback=lambda m: self.after(0, lambda: self._log(m)))
        tool.backup_static_ip()
        self._static_configs = tool.static_configs  # 保存到实例变量
        self.after(0, lambda: self._set_running(False, ""))
        self.after(0, lambda: self._set_status("✅ IP 配置备份完成", "#a6e3a1"))
    
    def _do_restore(self):
        if self._running:
            return
        if not hasattr(self, '_static_configs') or not self._static_configs:
            self._log("⚠ 请先点击「备份IP」按钮")
            self._set_status("⚠ 请先备份IP", "#fab387")
            return
        self._set_running(True, "还原 IP 配置")
        threading.Thread(target=self._thread_restore, daemon=True).start()
    
    def _thread_restore(self):
        tool = NetworkResetTool(log_callback=lambda m: self.after(0, lambda: self._log(m)))
        tool.static_configs = self._static_configs  # 使用保存的配置
        tool.restore_static_ip()
        self.after(0, lambda: self._set_running(False, ""))
        self.after(0, lambda: self._set_status("✅ IP 配置已还原", "#a6e3a1"))
    
    # ===== 一键重置全部 =====
    def _do_all_reset(self):
        if self._running:
            return
        
        if not messagebox.askyesno("确认", "将执行完整网络重置：\n\n"
                                   "1. 备份静态IP配置\n"
                                   "2. 重置 Winsock\n"
                                   "3. 重置 TCP/IP\n"
                                   "4. 清除 DNS/ARP 缓存\n"
                                   "5. 刷新 DHCP\n"
                                   "6. 恢复静态IP（如有）\n\n"
                                   "确定要继续吗？"):
            return
        
        self._set_running(True, "一键重置全部")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        
        threading.Thread(target=self._thread_all_reset, daemon=True).start()
    
    def _thread_all_reset(self):
        tool = NetworkResetTool(log_callback=lambda m: self.after(0, lambda: self._log(m)))
        tool.run_full_reset()
        self.after(0, lambda: self._set_running(False, ""))
        self.after(0, lambda: self.btn_restart.config(state="normal"))
    
    # ===== 底部操作 =====
    def _restart(self):
        if messagebox.askyesno("确认重启", "网络重置后需要重启电脑才能生效\n\n确定要立即重启吗？"):
            subprocess.run('shutdown /r /t 5', shell=True)
            self._log("5秒后重启电脑...")
    
    def _quit(self):
        if messagebox.askyesno("确认退出", "确定要退出程序吗？"):
            self.destroy()


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", lambda: app._quit())
    app.mainloop()
