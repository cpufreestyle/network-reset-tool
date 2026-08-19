#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nettoolbox.ui - GUI 面板(网络重置 + 网络诊断)
所有 Tkinter 控件的创建与更新都在主线程执行,
工作线程仅做计算,通过 self.after(0, render, data) 回传结果。
"""

import functools
import subprocess
import threading

import tkinter as tk
from tkinter import ttk, messagebox

from .core import (DNS_PRESETS, NetworkDiagnostic, NetworkResetTool,
                   get_active_adapter, is_admin, validate_host, validate_ipv4)


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

# DNS 预设按钮颜色(与 DNS_PRESETS 顺序一一对应)
DNS_PRESET_COLORS = [
    COLORS["muted"],   # 自动获取(DHCP)
    COLORS["orange"],  # 阿里 DNS
    COLORS["blue"],    # Google DNS
    COLORS["sky"],     # Cloudflare
    COLORS["pink"],    # 114 DNS
]


# ===== UI 公共组件 =====

def make_btn_style():
    return {'relief': "flat", 'cursor': "hand2", 'padx': 15, 'pady': 6}


def styled_btn(parent, text, cmd, bg, fg=None, font_size=10, bold=False, **kw):
    if fg is None:
        fg = COLORS["bg"]
    font_name = "微软雅黑"
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
        tk.Label(header, text="🌐 Windows 网络重置工具", font=("微软雅黑", 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text="重置网络配置 · 修复网络问题 · 保留静态IP",
                 font=("微软雅黑", 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        # 按钮区
        btn_area = tk.Frame(self, bg=self["bg"], pady=12)
        btn_area.pack(fill="x", padx=20)

        # 一键重置
        self.btn_all = styled_btn(btn_area, "🚀 一键重置全部",
                                  self._do_all_reset, COLORS["green"],
                                  font_size=13, bold=True)
        self.btn_all.pack(fill="x", pady=(0, 10))

        tk.Frame(btn_area, bg=COLORS["surface2"], height=1).pack(fill="x", pady=5)
        tk.Label(btn_area, text="- 单独操作 -", font=("微软雅黑", 9),
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
        self._make_btn(row2, "📋 清除 ARP",    self._do_arp,    COLORS["teal"]).pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row2, "🔄 刷新 DHCP",   self._do_dhcp,   COLORS["pink"]).pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row2, "💾 备份IP",      self._do_backup, COLORS["yellow"]).pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row3, "📥 还原IP",      self._do_restore, COLORS["sky"]).pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row3, "🧯 重置防火墙",  self._do_firewall, COLORS["orange"]).pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row3, "📄 备份Hosts",   self._do_hosts_bak, COLORS["teal"]).pack(side="left", expand=True, fill="x", padx=3)

        # ===== DNS 一键切换 =====
        tk.Frame(btn_area, bg=COLORS["surface2"], height=1).pack(fill="x", pady=(8, 3))
        dns_header = tk.Frame(btn_area, bg=self["bg"])
        dns_header.pack(fill="x", pady=(0, 4))
        tk.Label(dns_header, text="- DNS 一键切换 -", font=("微软雅黑", 9),
                 fg=COLORS["muted"], bg=self["bg"]).pack(side="left")
        self.dns_current_label = tk.Label(dns_header, text="", font=("微软雅黑", 9),
                                          fg=COLORS["yellow"], bg=self["bg"])
        self.dns_current_label.pack(side="right")

        # DNS 预设按钮行
        dns_row1 = tk.Frame(btn_area, bg=self["bg"])
        dns_row1.pack(fill="x", pady=2)
        dns_row2 = tk.Frame(btn_area, bg=self["bg"])
        dns_row2.pack(fill="x", pady=2)

        for i, (name, _cfg) in enumerate(DNS_PRESETS.items()):
            row = dns_row1 if i < 3 else dns_row2
            color = DNS_PRESET_COLORS[i % len(DNS_PRESET_COLORS)]
            self._make_dns_btn(row, name, color).pack(side="left", expand=True, fill="x", padx=3)

        # 自定义 DNS 输入行
        dns_custom_row = tk.Frame(btn_area, bg=self["bg"])
        dns_custom_row.pack(fill="x", pady=(2, 0))
        tk.Label(dns_custom_row, text="自定义:", font=("微软雅黑", 9),
                 fg=COLORS["subtext"], bg=self["bg"]).pack(side="left", padx=(3, 4))
        self.dns_primary_entry = tk.Entry(dns_custom_row, font=("Consolas", 9),
                                          bg=COLORS["surface"], fg=COLORS["text"],
                                          insertbackground=COLORS["text"],
                                          relief="flat", bd=0, width=14)
        self.dns_primary_entry.pack(side="left", padx=2)
        tk.Label(dns_custom_row, text="备用:", font=("微软雅黑", 9),
                 fg=COLORS["subtext"], bg=self["bg"]).pack(side="left", padx=(6, 4))
        self.dns_secondary_entry = tk.Entry(dns_custom_row, font=("Consolas", 9),
                                            bg=COLORS["surface"], fg=COLORS["text"],
                                            insertbackground=COLORS["text"],
                                            relief="flat", bd=0, width=14)
        self.dns_secondary_entry.pack(side="left", padx=2)
        styled_btn(dns_custom_row, "应用", self._do_custom_dns,
                   COLORS["green"], font_size=9).pack(side="left", padx=6)

        # 状态 + 进度
        self.status_label = tk.Label(self, text="就绪", font=("微软雅黑", 10),
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
        tk.Label(log_header, text="📋 执行日志", font=("微软雅黑", 10, "bold"),
                 fg=COLORS["text"], bg=self["bg"]).pack(side="left")
        tk.Button(log_header, text="清空", font=("微软雅黑", 9),
                  bg=COLORS["surface2"], fg=COLORS["text"], relief="flat",
                  command=self._clear_log, cursor="hand2").pack(side="right")

        log_container = tk.Frame(log_frame, bg=COLORS["bg2"])
        log_container.pack(fill="both", expand=True, pady=5)

        scrollbar = tk.Scrollbar(log_container)
        scrollbar.pack(side="right", fill="y")
        self.log_box = tk.Text(log_container, font=("Consolas", 10),
                               bg=COLORS["bg2"], fg=COLORS["text"],
                               insertbackground=COLORS["text"], relief="flat", bd=0,
                               state="disabled", yscrollcommand=scrollbar.set)
        self.log_box.pack(fill="both", expand=True, padx=5, pady=5)
        scrollbar.config(command=self.log_box.yview)

        # 底部按钮
        bottom = tk.Frame(self, bg=self["bg"], pady=10)
        bottom.pack(fill="x", padx=20)

        self.hint_label = tk.Label(bottom, text="", font=("微软雅黑", 9),
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

    def _make_dns_btn(self, parent, name, color):
        return tk.Button(parent, text=name, font=("微软雅黑", 9, "bold"),
                         bg=color, fg=COLORS["bg"],
                         activebackground=color, activeforeground=COLORS["bg"],
                         relief="flat", cursor="hand2", padx=5, pady=4,
                         command=lambda n=name: self._do_dns_switch(n))

    # ----- 线程安全辅助 -----
    def _safe_log(self, msg):
        """供工作线程使用的线程安全日志输出"""
        self.after(0, functools.partial(self._log, msg))

    def _make_tool(self):
        return NetworkResetTool(log_callback=self._safe_log)

    def _log(self, msg):
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

    def _finish(self, ok_msg=None, fail_msg=None, ok=True, extra_log=None):
        """统一收尾:恢复按钮 + 设置状态(仅在主线程调用)"""
        self._set_running(False)
        if ok_msg is not None:
            msg = ok_msg if (fail_msg is None or ok) else fail_msg
            self._set_status(msg, COLORS["green"] if ok else COLORS["red"])
        if extra_log:
            self._log(extra_log)

    # ----- DNS 切换 -----
    def _do_dns_switch(self, preset_name):
        if self._running:
            return
        self._set_running(True, f"切换 DNS 到 {preset_name}")
        threading.Thread(target=self._thread_dns_switch,
                         args=(preset_name,), daemon=True).start()

    def _thread_dns_switch(self, preset_name):
        adapter = get_active_adapter()
        if not adapter:
            self.after(0, functools.partial(self._log, "⚠ 未找到活动网卡,请检查网络连接"))
            self.after(0, functools.partial(self._set_running, False))
            self.after(0, functools.partial(self._set_status, "⚠ 未找到活动网卡", COLORS["orange"]))
            return
        tool = self._make_tool()
        tool.switch_dns(preset_name, adapter)
        self.after(0, functools.partial(self._finish, f"✅ DNS 已切换到 {preset_name}"))
        self.after(0, self._refresh_dns_status)

    def _do_custom_dns(self):
        if self._running:
            return
        primary = self.dns_primary_entry.get().strip()
        if not primary:
            self._set_status("⚠ 请输入主 DNS 地址", COLORS["orange"])
            return
        if not validate_ipv4(primary):
            self._set_status("⚠ 主 DNS 地址格式不正确", COLORS["red"])
            return
        secondary = self.dns_secondary_entry.get().strip()
        if secondary and not validate_ipv4(secondary):
            self._set_status("⚠ 备用 DNS 地址格式不正确", COLORS["red"])
            return
        self._set_running(True, f"设置自定义 DNS: {primary}")
        threading.Thread(target=self._thread_custom_dns,
                         args=(primary, secondary), daemon=True).start()

    def _thread_custom_dns(self, primary, secondary):
        adapter = get_active_adapter()
        if not adapter:
            self.after(0, functools.partial(self._log, "⚠ 未找到活动网卡"))
            self.after(0, functools.partial(self._set_status, "⚠ 未找到活动网卡", COLORS["orange"]))
            self.after(0, functools.partial(self._set_running, False))
            return
        tool = self._make_tool()
        tool.log(f"[DNS] 自定义 DNS: {primary}")
        ok = tool.set_dns(adapter, primary, secondary if secondary else None)
        tool.flush_dns()
        self.after(0, functools.partial(self._finish,
                                        "✅ 自定义 DNS 设置成功" if ok else "❌ DNS 设置失败",
                                        "✅ 自定义 DNS 设置成功" if ok else "❌ DNS 设置失败",
                                        ok))
        self.after(0, self._refresh_dns_status)

    def _refresh_dns_status(self):
        """刷新当前 DNS 显示(异步,不阻塞主线程)"""
        self.dns_current_label.config(text="当前: 获取中...")

        def _worker():
            tool = NetworkResetTool()
            dns_list, mode = tool.get_current_dns()
            if dns_list:
                mode_text = "自动" if mode == 'dhcp' else "手动"
                text = f"当前: {', '.join(dns_list)} [{mode_text}]"
            else:
                text = "当前: 未知"
            self.after(0, lambda: self.dns_current_label.config(text=text))

        threading.Thread(target=_worker, daemon=True).start()

    # ----- 单独操作 -----
    def _do_winsock(self):
        if self._running: return
        self._set_running(True, "重置 Winsock")
        threading.Thread(target=self._thread_winsock, daemon=True).start()

    def _thread_winsock(self):
        ok = self._make_tool().reset_winsock()
        self.after(0, functools.partial(self._finish,
                                        "✅ Winsock 重置完成" if ok else "❌ 操作失败",
                                        "✅ Winsock 重置完成" if ok else "❌ 操作失败",
                                        ok, "\n⚠ 可能需要重启电脑使设置生效"))

    def _do_tcpip(self):
        if self._running: return
        self._set_running(True, "重置 TCP/IP")
        threading.Thread(target=self._thread_tcpip, daemon=True).start()

    def _thread_tcpip(self):
        ok = self._make_tool().reset_tcpip()
        msg = "✅ TCP/IP 重置完成" if ok else "⚠ TCP/IP 重置已执行(建议重启后验证)"
        self.after(0, functools.partial(self._finish, msg, msg, True, "\n⚠ 必须重启电脑使设置生效"))

    def _do_dns(self):
        if self._running: return
        self._set_running(True, "清除 DNS 缓存")
        threading.Thread(target=self._thread_dns, daemon=True).start()

    def _thread_dns(self):
        ok = self._make_tool().flush_dns()
        self.after(0, functools.partial(self._finish,
                                        "✅ DNS 缓存已清除" if ok else "❌ 操作失败",
                                        "✅ DNS 缓存已清除" if ok else "❌ 操作失败",
                                        ok))

    def _do_arp(self):
        if self._running: return
        self._set_running(True, "清除 ARP 缓存")
        threading.Thread(target=self._thread_arp, daemon=True).start()

    def _thread_arp(self):
        ok = self._make_tool().flush_arp()
        self.after(0, functools.partial(self._finish,
                                        "✅ ARP 缓存已清除" if ok else "❌ 操作失败",
                                        "✅ ARP 缓存已清除" if ok else "❌ 操作失败",
                                        ok))

    def _do_dhcp(self):
        if self._running: return
        self._set_running(True, "刷新 DHCP")
        threading.Thread(target=self._thread_dhcp, daemon=True).start()

    def _thread_dhcp(self):
        self._make_tool().renew_dhcp()
        self.after(0, functools.partial(self._finish, "✅ DHCP 已刷新"))

    def _do_backup(self):
        if self._running: return
        self._set_running(True, "备份 IP 配置")
        threading.Thread(target=self._thread_backup, daemon=True).start()

    def _thread_backup(self):
        tool = self._make_tool()
        tool.backup_static_ip()
        self._static_configs = tool.static_configs
        self.after(0, functools.partial(self._finish, "✅ IP 配置备份完成"))

    def _do_restore(self):
        if self._running: return
        if not self._static_configs:
            self._log("⚠ 请先点击「备份IP」按钮")
            self._set_status("⚠ 请先备份IP", COLORS["orange"])
            return
        self._set_running(True, "还原 IP 配置")
        threading.Thread(target=self._thread_restore, daemon=True).start()

    def _thread_restore(self):
        tool = self._make_tool()
        tool.static_configs = self._static_configs
        tool.restore_static_ip()
        self.after(0, functools.partial(self._finish, "✅ IP 配置已还原"))

    # ----- 单独操作: 防火墙 / Hosts -----
    def _do_firewall(self):
        if self._running: return
        if not messagebox.askyesno("确认", "将重置 Windows 防火墙到默认配置。\n\n"
                                   "会清除所有自定义防火墙规则(入站/出站)。\n确定要继续吗?"):
            return
        self._set_running(True, "重置防火墙")
        threading.Thread(target=self._thread_firewall, daemon=True).start()

    def _thread_firewall(self):
        ok = self._make_tool().reset_firewall()
        self.after(0, functools.partial(self._finish,
                                        "✅ 防火墙已重置" if ok else "❌ 防火墙重置失败",
                                        "✅ 防火墙已重置" if ok else "❌ 防火墙重置失败",
                                        ok))

    def _do_hosts_bak(self):
        if self._running: return
        self._set_running(True, "备份 Hosts")
        threading.Thread(target=self._thread_hosts_bak, daemon=True).start()

    def _thread_hosts_bak(self):
        ok = self._make_tool().backup_hosts()
        self.after(0, functools.partial(self._finish,
                                        "✅ hosts 已备份" if ok else "❌ hosts 备份失败",
                                        "✅ hosts 已备份" if ok else "❌ hosts 备份失败",
                                        ok))

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
        self._clear_log()
        threading.Thread(target=self._thread_all_reset, daemon=True).start()

    def _thread_all_reset(self):
        self._make_tool().run_full_reset()
        self.after(0, functools.partial(self._set_running, False))
        self.after(0, lambda: self.btn_restart.config(state="normal"))

    def _restart(self):
        if messagebox.askyesno("确认重启", "网络重置后需要重启电脑才能生效\n\n确定要立即重启吗?"):
            self._log("5秒后重启电脑...")
            # shutdown /r /t 5: 5 秒后重启(原 PowerShell 命令参数错误,不会执行)
            threading.Thread(target=lambda: subprocess.run('shutdown /r /t 5', shell=True),
                             daemon=True).start()

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
        tk.Label(header, text="🔍 网络诊断工具", font=("微软雅黑", 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text="一键检测网络状态 · Ping / DNS / 路由追踪",
                 font=("微软雅黑", 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

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

        self.btn_speed = styled_btn(ctrl, "⚡ 网络测速", self._do_speed_test,
                                    COLORS["green"], font_size=11)
        self.btn_speed.pack(side="left", padx=4)

        # 自定义 Ping 输入
        self.custom_target = tk.StringVar(value="www.baidu.com")
        tk.Entry(ctrl, textvariable=self.custom_target, font=("Consolas", 10),
                 bg=COLORS["surface"], fg=COLORS["text"], insertbackground=COLORS["text"],
                 relief="flat", bd=0, width=18).pack(side="left", padx=(10, 4))
        self.btn_custom_ping = styled_btn(ctrl, "Ping", self._do_custom_ping, COLORS["orange"], font_size=11)
        self.btn_custom_ping.pack(side="left")

        # 进度条
        self.diag_progress = ttk.Progressbar(self, mode="determinate",
                                             style="diag.Horizontal.TProgressbar")
        self.diag_progress.pack(fill="x", padx=20, pady=(0, 5))

        self.diag_status = tk.Label(self, text="就绪", font=("微软雅黑", 9),
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

        self._show_hint()

    def _show_hint(self):
        self._clear_results()
        hint = tk.Label(self.results_inner,
                        text="点击上方按钮开始诊断\n\n📡 Ping 测试:检测到目标的网络延迟和连通性\n"
                             "🔍 DNS 解析:测试各 DNS 服务器解析是否正常\n"
                             "🛤️ Traceroute:追踪本机到目标的网络路由路径\n"
                             "📋 网络总览:显示当前 IP/网关/DNS 等信息",
                        font=("微软雅黑", 11), fg=COLORS["muted"], bg=COLORS["bg2"],
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
        # 修复: 自定义 Ping 按钮此前未加入禁用列表
        for btn in [self.btn_all_diag, self.btn_quick, self.btn_overview,
                    self.btn_traceroute, self.btn_health, self.btn_custom_ping,
                    self.btn_speed]:
            btn.config(state=state)
        if running:
            self.diag_progress.start(8)
        else:
            self.diag_progress.stop()

    def _validate_target(self):
        """校验自定义目标,合法返回目标字符串,否则返回 None 并提示"""
        target = self.custom_target.get().strip()
        if not target:
            self._set_diag_status("⚠ 请输入目标地址", COLORS["orange"])
            return None
        if not validate_host(target):
            self._set_diag_status("⚠ 目标地址含非法字符(仅支持域名/IP)", COLORS["red"])
            return None
        return target

    # ---- 结果卡片辅助(仅在主线程调用) ----
    def _card(self, parent, title, bg=COLORS["surface"]):
        f = tk.Frame(parent, bg=bg, padx=12, pady=8)
        f.pack(fill="x", pady=2)
        tk.Label(f, text=title, font=("微软雅黑", 10, "bold"),
                 fg=COLORS["text"], bg=bg).pack(anchor="w")
        return f

    def _result_ok(self, parent, text, sub=""):
        tk.Label(parent, text=f"  ✅ {text}", font=("微软雅黑", 10),
                 fg=COLORS["green"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)
        if sub:
            tk.Label(parent, text=f"      {sub}", font=("微软雅黑", 9),
                     fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    def _result_fail(self, parent, text, sub=""):
        tk.Label(parent, text=f"  ❌ {text}", font=("微软雅黑", 10),
                 fg=COLORS["red"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)
        if sub:
            tk.Label(parent, text=f"      {sub}", font=("微软雅黑", 9),
                     fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    def _result_info(self, parent, text):
        tk.Label(parent, text=f"  {text}", font=("微软雅黑", 9),
                 fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    # ---- 快速 Ping ----
    def _do_quick_ping(self):
        if self._running: return
        self._set_running(True)
        self.diag_progress.configure(mode="indeterminate")
        self._set_diag_status("⏳ Ping 测试中...", COLORS["blue"])
        threading.Thread(target=self._thread_quick_ping, daemon=True).start()

    def _thread_quick_ping(self):
        diag = NetworkDiagnostic()
        rows = []
        for target, label, _color in NetworkDiagnostic.PING_TARGETS:
            ok, avg_ms, loss, _ = diag.ping(target)
            rows.append((label, target, ok, avg_ms, loss))
        self.after(0, self._render_quick_ping, rows)

    def _render_quick_ping(self, rows):
        self._clear_results()
        row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row.pack(fill="x", pady=4, padx=4)
        card = self._card(row, "📡 Ping 连通性测试")

        all_ok = True
        for label, target, ok, avg_ms, loss in rows:
            latency = f"{avg_ms}ms" if avg_ms is not None else "<1ms"
            if ok:
                self._result_ok(card, f"{label} ({target})", f"延迟 {latency} · 丢包 {loss}%")
            else:
                all_ok = False
                self._result_fail(card, f"{label} ({target})", f"丢包率 {loss}%")

        self._set_running(False)
        self.diag_progress.configure(mode="determinate")
        if all_ok:
            self._set_diag_status("✅ 所有目标 Ping 正常", COLORS["green"])
        else:
            self._set_diag_status("⚠ 部分目标连接异常,可尝试网络重置", COLORS["yellow"])

    # ---- 网络总览 ----
    def _do_overview(self):
        if self._running: return
        self._set_running(True)
        self._set_diag_status("⏳ 读取网络信息...", COLORS["sky"])
        threading.Thread(target=self._thread_overview, daemon=True).start()

    def _thread_overview(self):
        overview = NetworkDiagnostic().get_overview()
        self.after(0, self._render_overview, overview)

    def _render_overview(self, overview):
        self._clear_results()
        row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row.pack(fill="x", pady=4, padx=4)
        card = self._card(row, "📋 网络状态总览")

        label_map = {
            "状态": "接口状态",
            "描述": "网卡描述",
            "MAC": "MAC 地址",
            "速度": "连接速度",
            "IPv4": "IPv4 地址",
            "网关": "默认网关",
            "DNS": "DNS 服务器",
            "DHCP": "DHCP 状态",
        }
        if overview:
            for k, v in overview:
                if k in label_map:
                    self._result_info(card, f"{label_map[k]}:{v}")
        else:
            self._result_fail(card, "无法获取网络信息")

        self._set_running(False)
        self._set_diag_status("✅ 网络总览完成", COLORS["green"])

    # ---- Traceroute ----
    def _do_traceroute(self):
        if self._running: return
        target = self._validate_target()
        if not target:
            return
        self._set_running(True)
        self._set_diag_status(f"⏳ 追踪路由到 {target}...", COLORS["purple"])
        threading.Thread(target=self._thread_traceroute, args=(target,), daemon=True).start()

    def _thread_traceroute(self, target):
        output = NetworkDiagnostic().traceroute(target)
        self.after(0, self._render_traceroute, target, output)

    def _render_traceroute(self, target, output):
        self._clear_results()
        row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row.pack(fill="both", expand=True, pady=4, padx=4)
        card = self._card(row, f"🛤️ 路由追踪: {target}")

        text_widget = tk.Text(card, font=("Consolas", 9), bg=COLORS["bg2"],
                              fg=COLORS["subtext"], relief="flat", bd=0,
                              height=min(20, max(10, len(output.split('\n')))))
        text_widget.pack(fill="x", padx=8, pady=4)
        text_widget.insert("1.0", output)
        text_widget.configure(state="disabled")

        def copy_trace():
            self.clipboard_clear()
            self.clipboard_append(output)
            self._set_diag_status("✅ 路由追踪结果已复制", COLORS["green"])

        tk.Button(card, text="📋 复制结果", font=("微软雅黑", 9),
                  bg=COLORS["surface"], fg=COLORS["text"],
                  relief="flat", cursor="hand2", command=copy_trace).pack(anchor="e", padx=10, pady=4)

        self._set_running(False)
        self._set_diag_status("✅ 追踪完成", COLORS["green"])

    # ---- 自定义 Ping ----
    def _do_custom_ping(self):
        if self._running: return
        target = self._validate_target()
        if not target:
            return
        self._set_running(True)
        self.diag_progress.configure(mode="indeterminate")
        self._set_diag_status(f"⏳ Ping {target}...", COLORS["orange"])
        threading.Thread(target=self._thread_custom_ping, args=(target,), daemon=True).start()

    def _thread_custom_ping(self, target):
        ok, avg_ms, loss, output = NetworkDiagnostic().ping(target, count=4)
        self.after(0, self._render_custom_ping, target, ok, avg_ms, loss, output)

    def _render_custom_ping(self, target, ok, avg_ms, loss, output):
        self._clear_results()
        row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row.pack(fill="both", expand=True, pady=4, padx=4)
        card = self._card(row, f"📡 Ping: {target}")

        latency = f"{avg_ms}ms" if avg_ms is not None else "<1ms"
        if ok:
            self._result_ok(card, "连接正常", f"延迟 {latency} · 丢包率 {loss}%")
        else:
            self._result_fail(card, "连接失败", f"丢包率 {loss}%")

        raw = tk.Text(card, font=("Consolas", 9), bg=COLORS["bg2"],
                      fg=COLORS["subtext"], relief="flat", bd=0,
                      height=min(12, max(5, len(output.split('\n')))))
        raw.pack(fill="x", padx=8, pady=4)
        raw.insert("1.0", output)
        raw.configure(state="disabled")

        self._set_running(False)
        self.diag_progress.configure(mode="determinate")

    # ---- 一键完整诊断 ----
    def _do_full_diagnostic(self):
        if self._running: return
        self._set_running(True)
        self.diag_progress.configure(mode="determinate")
        self.diag_progress["value"] = 0
        self._set_diag_status("⏳ 完整诊断中...", COLORS["green"])
        threading.Thread(target=self._thread_full_diagnostic, daemon=True).start()

    def _thread_full_diagnostic(self):
        diag = NetworkDiagnostic()

        def progress(pct, msg):
            self.after(0, lambda p=pct: self.diag_progress.configure(value=p))
            self.after(0, lambda m=msg: self._set_diag_status(f"⏳ {m}", COLORS["blue"]))

        try:
            results = diag.run_full_diagnostic(progress_callback=progress)
        except Exception as e:
            self.after(0, self._render_diag_error, str(e))
            return
        self._latest_results = results
        self.after(0, self._render_full_diagnostic, results)

    def _render_diag_error(self, err):
        self._set_diag_status(f"❌ 诊断失败: {err}", COLORS["red"])
        self._set_running(False)

    def _render_full_diagnostic(self, results):
        self._clear_results()
        CARD_BG = "#2a2a3e"

        # ---- 网络总览卡片 ----
        row0 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row0.pack(fill="x", pady=4, padx=4)
        card0 = self._card(row0, "📋 网络状态总览", bg=CARD_BG)
        overview = results.get('overview', [])
        if overview:
            for k, v in overview:
                self._result_info(card0, f"{k}:{v}")
        else:
            self._result_fail(card0, "无法获取网络信息")

        # ---- Ping 卡片 ----
        row1 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row1.pack(fill="x", pady=4, padx=4)
        card1 = self._card(row1, "📡 Ping 连通性测试", bg=CARD_BG)
        ping_results = results.get('ping', [])
        for p in ping_results:
            latency = f"{p['avg_ms']}ms" if p['avg_ms'] is not None else "<1ms"
            if p['ok']:
                self._result_ok(card1, f"{p['label']} ({p['target']})",
                                f"延迟 {latency} · 丢包 {p['loss']}%")
            else:
                self._result_fail(card1, f"{p['label']} ({p['target']})",
                                  f"丢包率 {p['loss']}%")

        # ---- DNS 卡片 ----
        row2 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row2.pack(fill="x", pady=4, padx=4)
        card2 = self._card(row2, "🔍 DNS 解析测试", bg=CARD_BG)
        dns_results = results.get('dns', [])
        for d in dns_results:
            if d['ok']:
                self._result_ok(card2, f"{d['label']} ({d['dns']})",
                                f"解析成功 → {d['ip']}")
            else:
                self._result_fail(card2, f"{d['label']} ({d['dns']})", "解析失败")

        # ---- 结论 ----
        row3 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row3.pack(fill="x", pady=4, padx=4)
        card3 = self._card(row3, "💡 诊断结论", bg=CARD_BG)

        all_ping_ok = all(p['ok'] for p in ping_results)
        all_dns_ok = all(d['ok'] for d in dns_results)

        if all_ping_ok and all_dns_ok:
            self._result_ok(card3, "网络状态正常", "所有目标连通,DNS 解析正常")
        elif all_ping_ok and not all_dns_ok:
            self._result_fail(card3, "DNS 异常", "Ping 正常但 DNS 解析失败,尝试清除 DNS 缓存")
        else:
            self._result_fail(card3, "网络连接异常", "部分目标不可达,建议使用「网络重置」标签修复")

        self._set_running(False)
        self.diag_progress.configure(value=100)
        self._set_diag_status("✅ 完整诊断完成", COLORS["green"])

    # ---- 网络测速 ----
    def _do_speed_test(self):
        if self._running: return
        self._set_running(True)
        self.diag_progress.configure(mode="determinate")
        self.diag_progress["value"] = 0
        self._set_diag_status("⚡ 测速中...", COLORS["green"])
        threading.Thread(target=self._thread_speed_test, daemon=True).start()

    def _thread_speed_test(self):
        from .core import SpeedTest

        def progress(pct, msg):
            self.after(0, lambda p=pct: self.diag_progress.configure(value=p))
            self.after(0, lambda m=msg: self._set_diag_status(f"⏳ {m}", COLORS["blue"]))

        def log_cb(msg):
            self.after(0, lambda m=msg: self._set_diag_status(m, COLORS["subtext"]))

        st = SpeedTest(log_callback=log_cb)
        download_results = st.run_download_test(progress_callback=progress)
        latency_results = st.run_latency_test()
        self.after(0, self._render_speed_test, download_results, latency_results)

    def _render_speed_test(self, download_results, latency_results):
        CARD_BG = "#2a2a3e"
        self._clear_results()

        # 下载测速卡片
        row0 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row0.pack(fill="x", pady=4, padx=4)
        card0 = self._card(row0, "⚡ 下载测速", bg=CARD_BG)

        best_name = None
        best_mbps = 0
        for name, mbps, mb_down, seconds in download_results:
            color = COLORS["green"] if mbps >= 50 else COLORS["yellow"] if mbps >= 10 else COLORS["red"]
            self._result_info(card0, f"{name}: {mbps} Mbps ({mb_down} MB / {seconds}s)")
            if mbps > best_mbps:
                best_mbps = mbps
                best_name = name

        if best_name:
            self._result_ok(card0, f"最快: {best_name}", f"{best_mbps} Mbps")

        # 延迟卡片
        row1 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row1.pack(fill="x", pady=4, padx=4)
        card1 = self._card(row1, "📡 延迟测试", bg=CARD_BG)

        for label, avg_ms in latency_results:
            if avg_ms is not None:
                color = COLORS["green"] if avg_ms < 50 else COLORS["yellow"] if avg_ms < 150 else COLORS["red"]
                self._result_ok(card1, f"{label}", f"平均延迟 {avg_ms}ms")
            else:
                self._result_fail(card1, f"{label}", "连接超时")

        # 结论
        row2 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row2.pack(fill="x", pady=4, padx=4)
        card2 = self._card(row2, "💡 测速结论", bg=CARD_BG)

        if best_mbps >= 50:
            self._result_ok(card2, "网速很快", f"最快 {best_mbps} Mbps,适合高清视频/大文件下载")
        elif best_mbps >= 10:
            self._result_ok(card2, "网速正常", f"最快 {best_mbps} Mbps,日常使用无压力")
        elif best_mbps > 0:
            self._result_fail(card2, "网速较慢", f"最快 {best_mbps} Mbps,建议检查网络或更换 DNS")
        else:
            self._result_fail(card2, "测速失败", "所有测速节点均无法连接,请检查网络")

        self._set_running(False)
        self.diag_progress.configure(value=100)
        self._set_diag_status("✅ 测速完成", COLORS["green"])

    # ---- 健康报告 ----
    def _do_health_report(self):
        if self._running: return
        self._set_running(True)
        self._set_diag_status("⏳ 生成健康报告...", COLORS["teal"])
        threading.Thread(target=self._thread_health_report, daemon=True).start()

    def _thread_health_report(self):
        try:
            results = NetworkDiagnostic().run_full_diagnostic()
        except Exception as e:
            self.after(0, self._render_diag_error, str(e))
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

        # 平均延迟(过滤 avg_ms 为 None 的记录,避免崩溃)
        avg_values = [p['avg_ms'] for p in ping_results
                      if p['ok'] and p['avg_ms'] is not None]
        avg_latency = round(sum(avg_values) / len(avg_values), 1) if avg_values else 0

        # 丢包率
        avg_loss = round(sum(p['loss'] for p in ping_results) / len(ping_results), 1) if ping_results else 100

        data = {
            'total': total,
            'ping_ok': ping_ok, 'ping_total': len(ping_results),
            'dns_ok': dns_ok, 'dns_total': len(dns_results),
            'cfg_score': cfg_score,
            'avg_latency': avg_latency,
            'avg_loss': avg_loss,
            'dns_server': next((v for k, v in overview if 'DNS' in k), "-"),
        }
        self.after(0, self._render_health_report, data)

    def _render_health_report(self, data):
        CARD_BG = "#2a2a3e"
        self._clear_results()

        total = data['total']
        if total >= 90:
            grade, grade_color = "优秀", COLORS["green"]
        elif total >= 70:
            grade, grade_color = "良好", COLORS["blue"]
        elif total >= 50:
            grade, grade_color = "一般", COLORS["yellow"]
        else:
            grade, grade_color = "较差", COLORS["red"]

        if total >= 90:
            advice_text = "网络状态优秀,所有检测通过,继续保持。"
        elif total >= 70:
            advice_text = "网络状态良好,个别指标待优化,可尝试 DNS 一键切换。"
        elif total >= 50:
            advice_text = "网络状态一般,建议执行「网络重置」修复潜在问题。"
        else:
            advice_text = "网络状态较差,建议立即执行「一键重置全部」修复网络。"

        def rc(parent, icon, title, value, sub=None, color=None):
            card = self._card(parent, icon + " " + title, bg=CARD_BG)
            if color is None:
                try:
                    num = float(str(value).rstrip('%'))
                    color = COLORS["green"] if num >= 80 else COLORS["yellow"] if num >= 50 else COLORS["red"]
                except (ValueError, TypeError):
                    color = COLORS["subtext"]
            tk.Label(card, text=value, font=("微软雅黑", 16, "bold"),
                     fg=color, bg=CARD_BG).pack(pady=(4, 0))
            if sub:
                tk.Label(card, text=sub, font=("微软雅黑", 8),
                         fg=COLORS["muted"], bg=CARD_BG).pack()

        # 顶部:总分 + 等级
        top = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        top.pack(fill="x", pady=4, padx=4)
        score_card = tk.Frame(top, bg=CARD_BG)
        score_card.pack(side="left", fill="both", expand=True, padx=(0, 4))
        tk.Label(score_card, text="网络健康评分", font=("微软雅黑", 10),
                 fg=COLORS["text"], bg=CARD_BG).pack(pady=(8, 0))
        tk.Label(score_card, text=f"{total}",
                 font=("微软雅黑", 36, "bold"), fg=grade_color, bg=CARD_BG).pack()
        tk.Label(score_card, text=grade, font=("微软雅黑", 11, "bold"),
                 fg=grade_color, bg=CARD_BG).pack(pady=(0, 8))

        # 等级说明
        advice_card = tk.Frame(top, bg=CARD_BG)
        advice_card.pack(side="right", fill="both", expand=True, padx=(4, 0))
        tk.Label(advice_card, text="💡 健康建议", font=("微软雅黑", 10, "bold"),
                 fg=COLORS["text"], bg=CARD_BG).pack(anchor="w", padx=10, pady=(8, 2))
        tk.Label(advice_card, text=advice_text, font=("微软雅黑", 9),
                 fg=COLORS["subtext"], bg=CARD_BG, wraplength=200,
                 justify="left", anchor="w").pack(anchor="w", padx=10, pady=(0, 8))

        # 维度卡片行
        row1 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row1.pack(fill="x", pady=4, padx=4)
        conn_pct = f"{round(data['ping_ok'] / max(data['ping_total'], 1) * 100)}%"
        dns_pct = f"{round(data['dns_ok'] / max(data['dns_total'], 1) * 100)}%"
        cfg_pct = f"{round(data['cfg_score'] / 30 * 100)}%"
        rc(row1, "📡", "连通性", conn_pct, f"{data['ping_ok']}/{data['ping_total']} 目标可达")
        rc(row1, "🔍", "DNS可用", dns_pct, f"{data['dns_ok']}/{data['dns_total']} DNS正常")
        rc(row1, "🔧", "配置完整", cfg_pct, "IP/网关/DNS状态")

        # 性能行
        row2 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        row2.pack(fill="x", pady=4, padx=4)
        lat, loss = data['avg_latency'], data['avg_loss']
        rc(row2, "⚡", "平均延迟", f"{lat}ms", "5个目标平均",
           COLORS["green"] if lat < 100 else COLORS["yellow"] if lat < 300 else COLORS["red"])
        rc(row2, "📉", "平均丢包", f"{loss}%", "5个目标平均",
           COLORS["green"] if loss == 0 else COLORS["yellow"] if loss < 20 else COLORS["red"])
        dns_svr = data['dns_server']
        rc(row2, "🌐", "当前DNS", dns_svr[:20] if len(dns_svr) > 20 else dns_svr, "当前使用")

        self._set_running(False)
        self.diag_progress.configure(value=100)
        self._set_diag_status(f"📊 健康报告: {total}分 {grade} | {advice_text[:20]}...",
                              grade_color)
