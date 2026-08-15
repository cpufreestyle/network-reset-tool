#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nettoolbox.app - 主窗口与 Tab 切换
"""

import datetime
import tkinter as tk
from tkinter import messagebox

from . import __version__, APP_NAME
from .ui import COLORS, ResetPanel, DiagnosticPanel


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        # 关闭 PyInstaller 启动画面
        try:
            import pyi_splash
            pyi_splash.close()
        except Exception:
            pass

        self.title(f"{APP_NAME} v{__version__} ✨")
        self.geometry("780x640")
        self.minsize(720, 580)
        self.configure(bg=COLORS["bg"])

        # 先让窗口显示出来,再做后续初始化
        self.update_idletasks()

        self._maybe_show_mothers_day_msg()
        self._build_ui()

    def _maybe_show_mothers_day_msg(self):
        """母亲节(5月第二个周日前后)温馨问候"""
        try:
            today = datetime.datetime.now()
            if today.month == 5 and today.day in (9, 10, 11):
                messagebox.showinfo(
                    "🌸 母亲节快乐 🌸",
                    "🌷 母亲节快乐!🌷\n\n"
                    "祝天下所有妈妈:\n健康平安,笑口常开!\n\n"
                    "❤️ 感谢您一直以来的付出 ❤️\n\n"
                    f"-- 您的网络工具箱 v{__version__}"
                )
        except Exception:
            pass  # 静默忽略任何节日弹窗错误

    def _build_ui(self):
        # 顶部标题栏
        topbar = tk.Frame(self, bg=COLORS["surface"], pady=8, padx=15)
        topbar.pack(fill="x")
        tk.Label(topbar, text="🛠️  网络工具箱",
                 font=("微软雅黑", 14, "bold"), fg=COLORS["text"],
                 bg=COLORS["surface"]).pack(side="left")
        tk.Label(topbar, text=f"v{__version__}  ·  重置 + 诊断",
                 font=("微软雅黑", 9), fg=COLORS["subtext"],
                 bg=COLORS["surface"]).pack(side="left", padx=10)

        # Tab 控制
        tabbar = tk.Frame(self, bg=COLORS["surface2"], padx=15, pady=0)
        tabbar.pack(fill="x")
        self.tab_buttons = {}
        tabs = [
            ("reset",       "🔄 网络重置"),
            ("diagnostic",  "🔍 网络诊断"),
        ]
        tab_btn_frame = tk.Frame(tabbar, bg=COLORS["surface2"])
        tab_btn_frame.pack(side="left")

        self._active_tab = "reset"
        for tid, label in tabs:
            btn = tk.Button(tab_btn_frame, text=label,
                            font=("微软雅黑", 10, "bold"),
                            bg=COLORS["surface2"], fg=COLORS["muted"],
                            relief="flat", cursor="hand2", padx=15, pady=6,
                            command=lambda t=tid: self._switch_tab(t))
            btn.pack(side="left", padx=(0, 2))
            self.tab_buttons[tid] = btn

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

        # 底部版本信息
        footer = tk.Frame(self, bg=COLORS["surface"], pady=4)
        footer.pack(fill="x")
        tk.Label(footer, text=f"Network Reset Tool v{__version__}  ·  michaelqiu",
                 font=("微软雅黑", 8), fg=COLORS["muted"], bg=COLORS["surface"]).pack(side="right", padx=10)

    def _switch_tab(self, tid):
        if tid == self._active_tab:
            return
        # 更新按钮样式
        self.tab_buttons[self._active_tab].config(bg=COLORS["surface2"], fg=COLORS["muted"])
        self.tab_buttons[tid].config(bg=COLORS["surface"], fg=COLORS["green"])

        # 切换面板
        if tid == "reset":
            self.diag_panel.forget()
            self.reset_panel.pack(fill="both", expand=True)
        else:
            self.reset_panel.forget()
            self.diag_panel.pack(fill="both", expand=True)

        self._active_tab = tid
