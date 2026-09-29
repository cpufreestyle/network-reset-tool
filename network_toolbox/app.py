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

from network_toolbox.i18n import (
    LANG_LABELS,
    current_lang,
    set_lang,
    tr,
    tr_f,
)
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
    EXE_ASSET_NAME,
    GITEE_OWNER,
    GITEE_REPO,
    safe_after,
    current_theme,
    set_theme,
    toggle_theme,
    THEME_LABELS,
)
from network_toolbox.ui_panels import (
    ResetPanel, DiagnosticPanel, ProxyPanel, PortsPanel, MonitorPanel,
    SpeedPanel, WifiPanel,
)

class App(tk.Tk):
    def __init__(self, start_tab=None):
        super().__init__()

        # 检测系统字体（Win7 兼容）——复用主窗口，不再另建 Tk root
        _init_font(self)

        # 套用上次保存的主题(F11); 放在 _build_ui 之前, 首屏就不会闪一下默认色
        self._theme = set_theme(current_theme())

        # 套用上次保存的语言(F12); 同样要在 _build_ui 之前
        self._lang = set_lang(current_lang())

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
                messagebox.showinfo(tr("🌸 母亲节快乐 🌸"), (
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
        tk.Label(topbar, text=tr("🛠️  网络工具箱"),
                 font=(FONT_FAMILY, 14, "bold"), fg=COLORS["text"],
                 bg=COLORS["surface"]).pack(side="left")
        tk.Label(topbar, text=f"{APP_VERSION_SHORT}  ·  重置 + 诊断 + 代理修复",
                 font=(FONT_FAMILY, 9), fg=COLORS["pink"],
                 bg=COLORS["surface"]).pack(side="left", padx=10)

        # 右上角：检查更新（仅打包后的 exe 支持自动更新）
        self.update_btn = styled_btn(
            topbar, tr("🔄 检查更新"), self._check_update,
            COLORS["surface2"], fg=COLORS["muted"], font_size=9,
            tip="从 Gitee Release 检查新版本；\n"
                "仅打包后的 exe 支持自动下载安装(带 SHA256 校验)")
        self.update_btn.pack(side="right")

        # 右上角：界面语言切换（F12）
        self.lang_btn = styled_btn(
            topbar, LANG_LABELS[self._lang], self._toggle_lang,
            COLORS["surface2"], fg=COLORS["muted"], font_size=9,
            tip="在中文 / English 之间切换界面语言。\n"
                "选择会被记住, 下次启动自动套用。")
        self.lang_btn.pack(side="right", padx=(0, 6))

        # 右上角：深浅主题切换（F11）
        self.theme_btn = styled_btn(
            topbar, tr(THEME_LABELS[self._theme]), self._toggle_theme,
            COLORS["surface2"], fg=COLORS["muted"], font_size=9,
            tip="在深色/浅色配色之间切换。\n"
                "选择会被记住, 下次启动自动套用。")
        self.theme_btn.pack(side="right", padx=(0, 6))

        # Tab 控制
        tabbar = tk.Frame(self, bg=COLORS["surface2"], padx=15, pady=0)
        tabbar.pack(fill="x")
        self.tab_buttons = {}
        tabs = [
            ("reset",       tr("🔄 网络重置")),
            ("diagnostic",  tr("🔍 网络诊断")),
            ("proxy",       tr("🛡️ 代理修复")),
            ("ports",       tr("🔌 端口查看")),
            ("monitor",     tr("📡 网络监控")),
            ("speed",       tr("💨 网速测试")),
            ("wifi",        tr("📶 WiFi 信息")),
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
            "ports": "列出本机所有监听端口与对应进程，代理端口高亮；\n"
                     "可按端口/PID/进程名过滤，可结束问题进程。",
            "monitor": "定时自动体检（默认每 5 分钟 Ping 网关与外网），\n"
                       "掉线自动记录起止时间与时长，重启后仍可回看。",
            "speed": "从公开测速端点下载固定大小数据，实测下行带宽。\n"
                     "最多 12 秒 / 64MB，可提前停止；纯标准库，无第三方依赖。",
            "wifi": "列出本机已保存的 WiFi 并回读密码(netsh wlan)。\n"
                    "读取密码需要管理员权限；支持导出 txt，注意保管明文密码。",
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

        self.ports_panel = PortsPanel(self.content)
        self.ports_panel.pack(fill="both", expand=True)
        self.ports_panel.forget()  # hidden by default

        self.monitor_panel = MonitorPanel(self.content)
        self.monitor_panel.pack(fill="both", expand=True)
        self.monitor_panel.forget()  # hidden by default

        self.speed_panel = SpeedPanel(self.content)
        self.speed_panel.pack(fill="both", expand=True)
        self.speed_panel.forget()  # hidden by default

        self.wifi_panel = WifiPanel(self.content)
        self.wifi_panel.pack(fill="both", expand=True)
        self.wifi_panel.forget()  # hidden by default

        # 底部版本信息
        footer = tk.Frame(self, bg=COLORS["surface"], pady=4)
        footer.pack(fill="x")
        tk.Label(footer,
                 text=f"{APP_NAME} {APP_VERSION}  ·  {APP_AUTHOR}",
                 font=(FONT_FAMILY, 8), fg=COLORS["muted"], bg=COLORS["surface"]).pack(side="right", padx=10)

    def _toggle_theme(self):
        """切换深浅主题并重建界面(保留当前标签页)。"""
        tab = self._active_tab
        self._theme = toggle_theme()
        # 先换色再整树重建: 新控件构造时读到的就是新 COLORS
        self._rebuild_ui()
        if tab in self.tab_buttons:
            self._switch_tab(tab)

    def _toggle_lang(self):
        """切换界面语言并重建界面(保留当前标签页)。"""
        tab = self._active_tab
        self._lang = set_lang("en" if self._lang == "zh" else "zh")
        self._rebuild_ui()
        if tab in self.tab_buttons:
            self._switch_tab(tab)

    def _rebuild_ui(self):
        """换主题后重建整棵窗口树: 所有控件的 bg/fg 都是构造期定的, 只能重建。"""
        self.update_idletasks()
        for w in self.winfo_children():
            w.destroy()
        self.tab_buttons = {}
        # 顶层窗口自己的底色也是构造期定的, 不重设就会残留旧主题的一条边
        self.configure(bg=COLORS["bg"])
        self._build_ui()

    def _switch_tab(self, tid):
        if tid == self._active_tab:
            return
        # 更新按钮样式
        self.tab_buttons[self._active_tab].config(bg=COLORS["surface2"], fg=COLORS["muted"])
        self.tab_buttons[tid].config(bg=COLORS["surface"], fg=COLORS["green"])

        # 切换面板
        for p in (self.reset_panel, self.diag_panel, self.proxy_panel,
                  self.ports_panel, self.monitor_panel, self.speed_panel,
                  self.wifi_panel):
            p.forget()
        {
            "reset": self.reset_panel,
            "diagnostic": self.diag_panel,
            "proxy": self.proxy_panel,
            "ports": self.ports_panel,
            "monitor": self.monitor_panel,
            "speed": self.speed_panel,
            "wifi": self.wifi_panel,
        }[tid].pack(fill="both", expand=True)

        self._active_tab = tid

    # ---------- 检查更新 ----------
    def _check_update(self):
        """检查新版本（线程安全：网络操作放 daemon 线程，UI 回主线程）。"""
        if not getattr(sys, "frozen", False):
            messagebox.showinfo(
                tr("检查更新"),
                "当前是源码运行模式, 自动更新仅对打包后的 exe 生效。\n"
                "请通过 git pull 或到 Gitee Release 手动下载最新版本。",
                parent=self)
            return
        self.update_btn.config(state="disabled", text=tr("⏳ 检查中…"))
        threading.Thread(target=self._thread_check_update, daemon=True).start()

    def _thread_check_update(self):
        from auto_updater import AutoUpdater
        updater = None
        error = None
        new_ver = None
        try:
            updater = AutoUpdater(
                APP_NAME, APP_VERSION, GITEE_OWNER, GITEE_REPO,
                exe_pattern=EXE_ASSET_NAME, check_on_start=False, silent=True)
            new_ver = updater.check_update(force=True)
        except Exception as e:
            error = str(e)
        safe_after(self, lambda: self._update_checked(error, new_ver, updater))

    def _update_checked(self, error, new_ver, updater):
        self.update_btn.config(state="normal", text=tr("🔄 检查更新"))
        if error or updater is None:
            messagebox.showwarning(
                tr("检查更新"),
                f"检查失败: {error or '未知错误'}\n请检查网络连接, 或稍后再试。",
                parent=self)
            return
        if not new_ver:
            messagebox.showinfo(tr("检查更新"),
                                f"当前已是最新版本 {APP_VERSION_SHORT} 🎉",
                                parent=self)
            return
        if not messagebox.askyesno(
                tr("发现新版本"),
                f"发现新版本 v{new_ver}\n\n是否现在下载并安装?\n"
                f"(下载完成后应用会自动重启完成更新)", parent=self):
            return
        self._download_update(updater)

    def _download_update(self, updater):
        """后台下载, 按钮上实时显示进度。"""
        self.update_btn.config(state="disabled", text=tr("⏳ 下载中 0%"))

        def _progress(done, total):
            pct = int(done * 100 / total) if total else 0
            safe_after(self, lambda: self.update_btn.config(text=f"⏳ 下载中 {pct}%"))

        def _work():
            try:
                ok = updater.download_and_update(progress_callback=_progress)
            except Exception:
                ok = False
            safe_after(self, lambda: self._update_downloaded(ok, updater))

        threading.Thread(target=_work, daemon=True).start()

    def _update_downloaded(self, ok, updater):
        self.update_btn.config(state="normal", text=tr("🔄 检查更新"))
        if not ok:
            messagebox.showerror(
                tr("更新失败"),
                "下载或 SHA256 校验失败, 已中止更新。\n"
                "可稍后重试, 或到 Gitee Release 手动下载。",
                parent=self)
            return
        if updater.apply_update():
            messagebox.showinfo(tr("更新就绪"), tr("新版本已就绪, 应用即将重启完成更新。"),
                                parent=self)
            _release_singleton()
            self.destroy()

def main():
    """程序入口：单例检测 → 启动 GUI；异常时把 traceback 写到日志并弹窗。"""
    if not _am_first:
        root_temp = tk.Tk()
        root_temp.withdraw()
        root_temp.attributes("-topmost", True)
        messagebox.showwarning(tr("提示"), tr("程序已在运行!\n请先关闭旧窗口。"), parent=root_temp)
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
        if start_tab not in ("reset", "diagnostic", "proxy", "ports", "monitor",
                              "speed", "wifi"):
            start_tab = None

        app = App(start_tab=start_tab)
        app.protocol("WM_DELETE_WINDOW", lambda: (_release_singleton(), app.destroy()))
        app.mainloop()
    except Exception:
        import traceback
        error_msg = traceback.format_exc()
        # 崩溃日志写 %LOCALAPPDATA%/NetworkResetTool/crash.log（exe 目录可能不可写）
        try:
            log_path = os.path.join(_app_data_dir(), "crash.log")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"Crash at {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(error_msg)
        except Exception:
            log_path = tr("(无法写入日志文件)")
        try:
            root_err = tk.Tk()
            root_err.withdraw()
            messagebox.showerror(tr("程序错误"),
                                 f"{error_msg[:500]}\n\n日志已保存: {log_path}",
                                 parent=root_err)
            root_err.destroy()
        except Exception:
            pass
        sys.exit(1)
