#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nettoolbox.app - 主窗口与 Tab 切换
"""

import datetime
import os
import threading
import tkinter as tk
from tkinter import messagebox

from . import __version__, APP_NAME
from .ui import COLORS, ResetPanel, DiagnosticPanel


# Gitee Release 仓库配置(自动更新)
_GITEE_OWNER = "cpufreestyle"
_GITEE_REPO = "network-reset-tool"


def _release_singleton_and_quit():
    """释放单例并退出程序(供更新流程调用)"""
    try:
        import network_reset_gui
        network_reset_gui._release_singleton()
    except Exception:
        pass
    import sys
    sys.exit(0)


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

        # 启动后台更新检查(延迟 2 秒,避免与 GUI 初始化抢资源)
        self.after(2000, self._check_for_updates)

    def _check_for_updates(self):
        """后台检查 Gitee Release 是否有新版本"""
        def _worker():
            try:
                import sys
                sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))
                from auto_updater import check_update_background

                def _on_found(new_ver, updater):
                    # 回到主线程弹窗
                    self.after(0, self._show_update_dialog, new_ver, updater)

                check_update_background(
                    app_name=APP_NAME,
                    current_version=__version__,
                    gitee_owner=_GITEE_OWNER,
                    gitee_repo=_GITEE_REPO,
                    callback=_on_found,
                )
            except Exception:
                pass  # 更新检查失败不影响正常使用

        threading.Thread(target=_worker, daemon=True).start()

    def _show_update_dialog(self, new_ver, updater):
        """发现新版本时弹出更新提示框"""
        changelog = updater.get_changelog() or "暂无更新日志"
        # 截取 changelog 前 300 字符避免弹窗过长
        if len(changelog) > 300:
            changelog = changelog[:300] + "..."

        msg = (f"🎉 发现新版本 v{new_ver}!\n\n"
               f"当前版本: v{__version__}\n"
               f"最新版本: v{new_ver}\n\n"
               f"更新内容:\n{changelog}\n\n"
               f"是否立即下载更新?")

        if messagebox.askyesno("发现新版本", msg):
            self._start_download(updater)

    def _start_download(self, updater):
        """开始下载更新(后台线程)"""
        download_frame = tk.Frame(self, bg=COLORS["surface"], pady=4)
        download_frame.pack(fill="x", side="bottom")
        lbl = tk.Label(download_frame, text="⏳ 正在下载更新...",
                       font=("微软雅黑", 9), fg=COLORS["yellow"], bg=COLORS["surface"])
        lbl.pack(side="left", padx=10)

        def _download_worker():
            try:
                ok = updater.download_and_update()
                self.after(0, lambda: self._on_download_done(ok, download_frame, updater))
            except Exception as e:
                self.after(0, lambda: self._on_download_done(False, download_frame, updater, str(e)))

        threading.Thread(target=_download_worker, daemon=True).start()

    def _on_download_done(self, ok, frame, updater, err=None):
        """下载完成回调"""
        for w in frame.winfo_children():
            w.destroy()
        if ok:
            if messagebox.askyesno("更新就绪", "更新已下载完成!\n\n立即安装并重启?"):
                updater_ok = updater.apply_update()
                if updater_ok:
                    _release_singleton_and_quit()
                else:
                    messagebox.showerror("更新失败", "无法应用更新,请手动下载。")
        else:
            tk.Label(frame, text=f"❌ 下载失败: {err or '未知错误'}",
                     font=("微软雅黑", 9), fg=COLORS["red"], bg=COLORS["surface"]).pack(side="left", padx=10)

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
