# -*- coding: utf-8 -*-
"""主窗口 App 与程序入口。"""
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
    attach_tooltip,
    decode_output,
    is_admin,
    is_valid_target,
    make_btn_style,
    styled_btn,
    ui_sync,
)
from network_toolbox.ui_panels import (
    ResetPanel, DiagnosticPanel, ProxyPanel,
)

class App(tk.Tk):
    def __init__(self, start_tab=None):
        super().__init__()

        # 检测系统字体（Win7 兼容）——复用主窗口，不再另建 Tk root
        _init_font(self)

        # 关闭 PyInstaller 启动画面
        try:
            import pyi_splash
            pyi_splash.close()
        except Exception:
            pass

        self.title(f"{APP_NAME} {APP_VERSION_SHORT} ✨")
        self.geometry("780x640")
        self.minsize(720, 580)
        self.configure(bg=COLORS["bg"])

        # 先让窗口显示出来,再做后续初始化
        self.update_idletasks()

        # ===== 母亲节问候（动态计算"5月第二个周日"，不再写死日期）=====
        try:
            if _is_mothers_day():
                messagebox.showinfo("🌸 母亲节快乐 🌸", (
                    "🌷 母亲节快乐!🌷\n\n"
                    "祝天下所有妈妈:\n"
                    "健康平安,笑口常开!\n\n"
                    "❤️ 感谢您一直以来的付出 ❤️\n\n"
                    f"-- 您的{APP_NAME} {APP_VERSION_SHORT}"
                ))
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
        tk.Label(topbar, text=f"{APP_VERSION_SHORT}  ·  重置 + 诊断 + 代理修复",
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
        TAB_TIPS = {
            "reset": "重置网卡配置：Winsock / TCP/IP / DNS / ARP / DHCP，\n"
                     "含静态 IP 备份还原与配置快照回滚。需要管理员权限。",
            "diagnostic": "只读检测，不改任何配置：Ping / DNS 解析 / 路由追踪 /\n"
                          "网络总览 / 健康评分，报告可导出为 HTML。",
            "proxy": "排查代理导致的“外网全失败”：系统代理端口已死、\n"
                     "Clash DNS 被关闭。macOS 上这是主力标签页。",
        }
        for tid, label in tabs:
            btn = attach_tooltip(tk.Button(tab_btn_frame, text=label,
                            font=(FONT_FAMILY, 10, "bold"),
                            bg=COLORS["surface2"], fg=COLORS["muted"],
                            relief="flat", cursor="hand2", padx=15, pady=6,
                            command=lambda t=tid: self._switch_tab(t)),
                                 TAB_TIPS[tid])
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
        tk.Label(footer,
                 text=f"{APP_NAME} {APP_VERSION}  ·  {APP_AUTHOR}",
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