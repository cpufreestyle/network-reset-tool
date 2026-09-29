# -*- coding: utf-8 -*-
"""UI 面板: 重置 / 诊断 / 代理修复 / 端口 / 监控 / 测速 / WiFi 信息。"""
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

from network_toolbox.i18n import tr, tr_f
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
    dns_preset_tip,
    is_admin,
    is_valid_target,
    make_btn_style,
    safe_after,
    styled_btn,
    ui_sync,
)
from network_toolbox.engine import (
    NetworkResetTool, NetworkDiagnostic, ProxyRepairTool,
    HostsTool, PortTool, NetworkMonitor, SpeedTester, WifiTool,
)
from network_toolbox.report import (
    compute_health, render_report, render_report_html, render_report_text, render_report_markdown, open_path,
)

class ResetPanel(tk.Frame):
    """左侧"网络重置"标签页"""

    # 关键修复：v3.2 中本类缺少 _decode_output，_get_active_adapter() 里
    # 4 处调用全部抛 AttributeError 并被 except 吞掉 → 永远"未找到活动网卡"
    # → DNS 一键切换在 Windows 上 100% 失效。
    _decode_output = staticmethod(decode_output)

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        self._running = False
        self._static_configs = []
        self._current_tool = None     # 当前正在执行任务的核心对象，用于「取消」
        self._build_ui()

    def _build_ui(self):
        # 标题
        header = tk.Frame(self, bg=COLORS["surface"], pady=12)
        header.pack(fill="x")
        header_title = tr("🌐 Windows 网络重置工具") if IS_WINDOWS else tr("🌐 网络重置工具")
        tk.Label(header, text=header_title, font=(FONT_FAMILY, 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text=tr("重置网络配置 · 修复网络问题 · 保留静态IP"),
                 font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        # 非 Windows 平台提示横幅 + 禁用 Windows 专属按钮
        if not IS_WINDOWS:
            banner = tk.Frame(self, bg=COLORS["warn_bg"], padx=12, pady=8)
            banner.pack(fill="x", padx=20, pady=(0, 6))
            plat = "macOS" if IS_MAC else tr("当前平台")
            tk.Label(banner,
                     text=tr_f("⚠ 此标签页的完整网络重置(Winsock/TCP-IP/DHCP/静态IP)仅支持 Windows。\n"
                          "   {plat} 上请使用「🛡️ 代理修复」标签页修复代理与 DNS。", plat=plat),                     font=(FONT_FAMILY, 9), fg=COLORS["warn_fg"], bg=COLORS["warn_bg"], justify="left").pack(anchor="w")

        # 按钮区
        btn_area = tk.Frame(self, bg=self["bg"], pady=12)
        btn_area.pack(fill="x", padx=20)

        # 一键重置
        self.btn_all = styled_btn(btn_area, tr("🚀 一键重置全部"),
                                  self._do_all_reset, COLORS["green"],
                                  font_size=13, bold=True,
                                  tip="按顺序执行：建快照 → 备份静态 IP → 重置 Winsock → 重置 TCP/IP\n"
                                      "→ 清 DNS/ARP 缓存 → 刷新 DHCP → 还原静态 IP。\n"
                                      "需要管理员权限；跑完必须重启电脑才生效，上不了网可用「⏪ 回滚」还原。")
        self.btn_all.pack(fill="x", pady=(0, 10))

        tk.Frame(btn_area, bg=COLORS["surface2"], height=1).pack(fill="x", pady=5)
        tk.Label(btn_area, text=tr("- 单独操作 -"), font=(FONT_FAMILY, 9),
                 fg=COLORS["muted"], bg=self["bg"]).pack(pady=3)

        # 2行 x 3列按钮
        row1 = tk.Frame(btn_area, bg=self["bg"])
        row1.pack(fill="x", pady=3)
        row2 = tk.Frame(btn_area, bg=self["bg"])
        row2.pack(fill="x", pady=3)
        row3 = tk.Frame(btn_area, bg=self["bg"])
        row3.pack(fill="x", pady=3)

        self._make_btn(row1, tr("🔄 重置 Winsock"), self._do_winsock, COLORS["blue"],
                       "netsh winsock reset：重建网络协议栈目录。\n"
                       "修「能连上却上不了网」、第三方加速/LSP 残留。\n"
                       "需要管理员权限，执行后建议重启电脑。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row1, tr("🔄 重置 TCP/IP"), self._do_tcpip, COLORS["purple"],
                       "netsh int ip reset：把 IP 栈配置写回系统默认值。\n"
                       "会抹掉当前静态 IP / 路由设置，建议先「备份IP」或「建快照」。\n"
                       "执行后必须重启电脑才生效。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row1, tr("🧹 清除 DNS"),    self._do_dns,    COLORS["orange"],
                       "ipconfig /flushdns：清掉本机 DNS 缓存。\n"
                       "域名解析到旧地址、刚改过 DNS 却不生效时先点它。\n"
                       "无风险、不影响网页内容，可随时执行。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row2, tr("📋 清除 ARP"),   self._do_arp,    COLORS["teal"],
                       "arp -d *：清空 ARP 缓存(IP 与网关 MAC 的对应表)。\n"
                       "换过路由器、局域网改过 IP 后点一下即可。\n"
                       "无风险，缓存会自动重新学习。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row2, tr("🔄 刷新 DHCP"),  self._do_dhcp,   COLORS["pink"],
                       "ipconfig /release + /renew：向路由器重新要一次 IP。\n"
                       "IP 冲突、拿到 169.254.x.x 段的地址时点它。\n"
                       "过程中会断网几秒。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row2, tr("💾 备份IP"),      self._do_backup, COLORS["yellow"],
                       "读取并保存当前所有网卡的静态 IP / 子网掩码 / 网关\n"
                       "(存到本机文件，重开程序也在)。\n"
                       "重置 TCP/IP 之前先点它，之后可用「还原IP」找回。").pack(side="left", expand=True, fill="x", padx=3)

        self._make_btn(row3, tr("📥 还原IP"),      self._do_restore, COLORS["sky"],
                       "把上一次「备份IP」保存的静态 IP / 掩码 / 网关写回网卡。\n"
                       "没有备份时只提示、不改动任何配置。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row3, tr("📸 建快照"),      self._do_snapshot, COLORS["mauve"],
                       "把当前 DNS、系统代理、静态 IP 存成一个带时间戳的快照文件，\n"
                       "随时可用「⏪ 回滚」还原。\n"
                       "「一键重置全部」也会自动先建一份，手动点可多留几个历史点。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row3, tr("⏪ 回滚"),        self._do_rollback, COLORS["pink"],
                       "用最近一次快照还原 DNS 与系统代理，弹窗可额外选择是否连静态 IP 一起还原\n"
                       "(DHCP 网络建议选「否」)。重置后反而上不了网时优先用它。").pack(side="left", expand=True, fill="x", padx=3)

        # ===== 网卡选择 (F3) =====
        tk.Frame(btn_area, bg=COLORS["surface2"], height=1).pack(fill="x", pady=(8, 3))
        nic_row = tk.Frame(btn_area, bg=self["bg"])
        nic_row.pack(fill="x", pady=(0, 4))
        tk.Label(nic_row, text=tr("网卡:"), font=(FONT_FAMILY, 9),
                 fg=COLORS["subtext"], bg=self["bg"]).pack(side="left", padx=(3, 4))

        self.adapter_var = tk.StringVar(value=ADAPTER_AUTO)
        self._adapter_map = {ADAPTER_AUTO: None}   # 显示文本 -> 真实网卡名
        self.adapter_combo = ttk.Combobox(
            nic_row, textvariable=self.adapter_var, values=[ADAPTER_AUTO],
            state="readonly", width=26, font=(FONT_FAMILY, 9), style="nic.TCombobox")
        self.adapter_combo.pack(side="left", fill="x", expand=True)
        self.adapter_combo.bind("<<ComboboxSelected>>", self._on_adapter_selected)
        self.btn_refresh_nic = styled_btn(nic_row, tr("🔄 刷新"), self._refresh_adapters,
                                          COLORS["surface2"], COLORS["text"], font_size=9,
                                          tip=tr("重新枚举本机网卡并刷新左边的下拉列表。\n"
                                              "后台执行，网卡多时可能要几秒。"))
        self.btn_refresh_nic.pack(side="left", padx=(6, 3))

        # ===== DNS 一键切换 =====
        tk.Frame(btn_area, bg=COLORS["surface2"], height=1).pack(fill="x", pady=(8, 3))
        dns_header = tk.Frame(btn_area, bg=self["bg"])
        dns_header.pack(fill="x", pady=(0, 4))
        tk.Label(dns_header, text=tr("- DNS 一键切换 -"), font=(FONT_FAMILY, 9),
                 fg=COLORS["muted"], bg=self["bg"]).pack(side="left")
        self.dns_current_label = tk.Label(dns_header, text="", font=(FONT_FAMILY, 9),
                                          fg=COLORS["yellow"], bg=self["bg"])
        self.dns_current_label.pack(side="right")

        # DNS 预设按钮行
        dns_row1 = tk.Frame(btn_area, bg=self["bg"])
        dns_row1.pack(fill="x", pady=2)
        dns_row2 = tk.Frame(btn_area, bg=self["bg"])
        dns_row2.pack(fill="x", pady=2)

        for i, (name, cfg) in enumerate(DNS_PRESETS.items()):
            row = dns_row1 if i < 3 else dns_row2
            self._make_dns_btn(row, name, cfg).pack(side="left", expand=True, fill="x", padx=3)

        # 自定义 DNS 输入行
        dns_custom_row = tk.Frame(btn_area, bg=self["bg"])
        dns_custom_row.pack(fill="x", pady=(2, 0))
        tk.Label(dns_custom_row, text=tr("自定义:"), font=(FONT_FAMILY, 9),
                 fg=COLORS["subtext"], bg=self["bg"]).pack(side="left", padx=(3, 4))
        self.dns_primary_entry = tk.Entry(dns_custom_row, font=(FONT_MONO, 9),
                                           bg=COLORS["surface"], fg=COLORS["text"],
                                           insertbackground=COLORS["text"],
                                           relief="flat", bd=0, width=14)
        self.dns_primary_entry.pack(side="left", padx=2)
        self.dns_primary_entry.insert(0, "")
        tk.Label(dns_custom_row, text=tr("备用:"), font=(FONT_FAMILY, 9),
                 fg=COLORS["subtext"], bg=self["bg"]).pack(side="left", padx=(6, 4))
        self.dns_secondary_entry = tk.Entry(dns_custom_row, font=(FONT_MONO, 9),
                                            bg=COLORS["surface"], fg=COLORS["text"],
                                            insertbackground=COLORS["text"],
                                            relief="flat", bd=0, width=14)
        self.dns_secondary_entry.pack(side="left", padx=2)
        styled_btn(dns_custom_row, tr("应用"), self._do_custom_dns,
                   COLORS["green"], font_size=9,
                   tip=tr("把左边两个输入框填的地址设为本机网卡的 DNS(备用可留空)，\n"
                       "填完会顺带刷新 DNS 缓存。\n"
                       "填错会导致域名解析失败，可用上方「自动获取(DHCP)」救回。")).pack(side="left", padx=6)

        # DNS 测速排序(F9)
        dns_bench_row = tk.Frame(btn_area, bg=self["bg"])
        dns_bench_row.pack(fill="x", pady=(4, 0))
        self.btn_dns_bench = styled_btn(
            dns_bench_row, tr("⚡ DNS 测速排序"), self._do_dns_bench,
            COLORS["teal"], font_size=9,
            tip=tr("对每个 DNS 预设解析 www.baidu.com 各 3 次取平均耗时，\n"
                "按快慢排序显示(约 15~40 秒)。只测速，不改任何设置。"))
        self.btn_dns_bench.pack(side="left")
        self.btn_apply_fastest = styled_btn(
            dns_bench_row, tr("🏆 应用最快"), self._do_apply_fastest,
            COLORS["green"], font_size=9,
            tip="把测速结果里最快的 DNS 一键设到当前网卡。\n"
                "需要先跑一次「⚡ DNS 测速排序」。")
        self.btn_apply_fastest.pack(side="left", padx=6)
        self.btn_apply_fastest.config(state="disabled")
        self._fastest_preset = None
        self.dns_bench_label = tk.Label(dns_bench_row, text="", font=(FONT_FAMILY, 9),
                                        fg=COLORS["subtext"], bg=self["bg"])
        self.dns_bench_label.pack(side="left", padx=8)

        # 状态 + 进度
        self.status_label = tk.Label(self, text=tr("就绪"), font=(FONT_FAMILY, 10),
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
        tk.Label(log_header, text=tr("📋 执行日志"), font=(FONT_FAMILY, 10, "bold"),
                 fg=COLORS["text"], bg=self["bg"]).pack(side="left")
        attach_tooltip(tk.Button(log_header, text=tr("清空"), font=(FONT_FAMILY, 9),
                  bg=COLORS["surface2"], fg=COLORS["text"], relief="flat",
                  command=self._clear_log, cursor="hand2"),
                     tr("清空上方执行日志。\n只清显示内容，不影响任何已生效的网络配置与快照。")).pack(side="right")

        log_container = tk.Frame(log_frame, bg=COLORS["bg2"])
        log_container.pack(fill="both", expand=True, pady=5)

        scrollbar = theme_scrollbar(log_container, None)
        scrollbar.pack(side="right", fill="y")
        self.log_box = tk.Text(log_container, font=(FONT_MONO, 10),
                               bg=COLORS["bg2"], fg=COLORS["text"],
                               insertbackground=COLORS["text"], relief="flat", bd=0,
                               state="disabled", yscrollcommand=scrollbar.set)
        self.log_box.pack(fill="both", expand=True, padx=5, pady=5)
        scrollbar.config(command=self.log_box.yview)

        # 底部按钮
        bottom = tk.Frame(self, bg=self["bg"], pady=10)
        bottom.pack(fill="x", padx=20)

        self.hint_label = tk.Label(bottom, text="", font=(FONT_FAMILY, 9),
                                    fg=COLORS["muted"], bg=self["bg"], anchor="w")
        self.hint_label.pack(side="left")

        btn_group = tk.Frame(bottom, bg=self["bg"])
        btn_group.pack(side="right")
        self.btn_cancel = styled_btn(btn_group, tr("⏹ 取消"), self._do_cancel,
                                      COLORS["surface2"], COLORS["text"], state="disabled",
                                      tip="中断正在执行的任务，在下一个步骤边界生效——已经发出的\n"
                                          "系统命令会跑完，不会强行掐断。\n"
                                          "只在「一键重置全部」期间可点，其它操作本来就很短。")
        self.btn_cancel.pack(side="left", padx=5)
        self.btn_restart = styled_btn(btn_group, tr("🔁 重启电脑"), self._restart,
                                       COLORS["yellow"], state="disabled",
                                       tip="5 秒后强制重启 Windows，让 Winsock / TCP-IP 重置真正生效。\n"
                                           "未保存的内容会被丢弃，执行 shutdown /a 可取消。")
        self.btn_restart.pack(side="left", padx=5)
        styled_btn(btn_group, tr("✕ 退出"), self._quit, COLORS["red"],
                   tip="关闭程序(会二次确认)。\n"
                       "已生效的网络配置、IP 备份与快照文件都会保留。").pack(side="left", padx=5)

        # 样式
        # 注意：theme_use() 会重置已有 style，Combobox 的配色必须放在它之后配置
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("green.Horizontal.TProgressbar",
                        troughcolor=COLORS["surface"], background=COLORS["green"], thickness=8)

        style.configure("nic.TCombobox",
                        fieldbackground=COLORS["surface"], background=COLORS["surface"],
                        foreground=COLORS["text"], arrowcolor=COLORS["subtext"],
                        bordercolor=COLORS["surface2"], lightcolor=COLORS["surface"],
                        darkcolor=COLORS["surface"], padding=(4, 2))
        style.map("nic.TCombobox",
                  fieldbackground=[("readonly", COLORS["surface"])],
                  foreground=[("readonly", COLORS["text"])],
                  selectbackground=[("readonly", COLORS["surface"])],
                  selectforeground=[("readonly", COLORS["text"])])
        # 下拉弹窗里的列表框是原生 Listbox，只能通过 option 数据库上色
        top = self.winfo_toplevel()
        for opt, val in (("*TCombobox*Listbox.background", COLORS["surface"]),
                         ("*TCombobox*Listbox.foreground", COLORS["text"]),
                         ("*TCombobox*Listbox.selectBackground", COLORS["blue"]),
                         ("*TCombobox*Listbox.selectForeground", COLORS["bg"]),
                         ("*TCombobox*Listbox.borderWidth", "0")):
            try:
                top.option_add(opt, val)
            except Exception:
                pass

        # 启动后异步枚举一次网卡（静默，不打扰用户）
        safe_after(self, lambda: self._refresh_adapters(silent=True), 600)

        # 管理员检查
        if not is_admin():
            self._log(tr("⚠ 警告: 未以管理员身份运行,部分功能可能受限"))
            self._log(tr("  → 右键选择 [以管理员身份运行] 获得完整功能"))

        self._log(tr("✅ 程序已就绪,请选择操作..."))

        # 非 Windows: 禁用 Windows 专属的重置按钮(系统代理/恢复等仍可用)
        if not IS_WINDOWS:
            for w in btn_area.winfo_children():
                self._disable_widget_tree(w)
            # 自定义 DNS 应用按钮在 macOS 上仍可用(走 networksetup)
            if IS_MAC:
                self._enable_widget(dns_custom_row)

        # 记录所有可操作控件的"基线可用状态":
        # 运行任务时统一禁用(防止并发点击),结束后精确还原(不会把 macOS 上
        # 本就禁用的按钮误恢复成可用)。
        self._action_widgets = []
        self._baseline_state = {}

        def _collect(w):
            try:
                if w.winfo_class() in ("TButton", "Button", "Entry", "TEntry", "TCombobox"):
                    self._action_widgets.append(w)
            except Exception:
                pass
            try:
                for c in w.winfo_children():
                    _collect(c)
            except Exception:
                pass

        _collect(btn_area)
        for w in self._action_widgets:
            try:
                self._baseline_state[w] = str(w.cget("state"))
            except Exception:
                pass

        # 载入上次持久化的静态 IP 备份（原先只在内存里，重开程序就丢了）
        saved = self._load_backup()
        if saved:
            self._static_configs = saved
            self._log(f"📂 已载入上次的 IP 备份({len(saved)} 条),可直接点「还原IP」")

        # 刷新当前 DNS 状态
        safe_after(self, self._refresh_dns_status, 500)

    def _make_btn(self, parent, text, cmd, color, tip):
        return styled_btn(parent, text, cmd, color, font_size=10, bold=True, tip=tip)

    @staticmethod
    def _disable_widget_tree(widget):
        """递归禁用某个容器内的所有按钮/输入框"""
        try:
            widget.configure(state="disabled")
        except Exception:
            pass
        for child in widget.winfo_children():
            ResetPanel._disable_widget_tree(child)

    @staticmethod
    def _enable_widget(widget):
        try:
            widget.configure(state="normal")
        except Exception:
            pass
        for child in widget.winfo_children():
            ResetPanel._enable_widget(child)

    # ----- 静态 IP 备份持久化 -----
    @staticmethod
    def _backup_file():
        return os.path.join(_app_data_dir(), "static_ip_backup.json")

    def _load_backup(self):
        """从磁盘读取上次备份的静态 IP 配置（重启程序后仍可「还原IP」）。"""
        try:
            with open(self._backup_file(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [c for c in data if isinstance(c, dict) and c.get("name")]
        except Exception:
            pass
        return []

    def _save_backup(self, configs):
        try:
            with open(self._backup_file(), "w", encoding="utf-8") as f:
                json.dump(configs, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            self._log(f"  ⚠ 备份写入失败: {e}")
            return False

    # ----- 网卡选择 (F3) -----
    def selected_adapter(self):
        """返回下拉框里手动指定的网卡名；仍是「自动检测」则返回 None。"""
        try:
            val = (self.adapter_var.get() or "").strip()
        except Exception:
            return None
        if not val or val == ADAPTER_AUTO:
            return None
        return self._adapter_map.get(val, val)

    def _on_adapter_selected(self, _event=None):
        name = self.selected_adapter()
        if name:
            self._log(f"🎯 已指定网卡: {name}（后续 DNS 操作将只作用于它）")
            self._set_status(f"已选择网卡: {name}", COLORS["blue"])
        else:
            self._log(tr("🔎 网卡: 恢复自动检测"))
        self._refresh_dns_status()

    def _refresh_adapters(self, silent=False):
        """后台枚举网卡并刷新下拉框（PowerShell 查询较慢，不能放在主线程）。"""
        if self._running:
            return
        if not silent:
            self._set_status(tr("⏳ 正在枚举网卡..."), COLORS["blue"])
        try:
            self.btn_refresh_nic.config(state="disabled")
        except Exception:
            pass
        threading.Thread(target=self._thread_refresh_adapters,
                         args=(silent,), daemon=True).start()

    def _thread_refresh_adapters(self, silent=False):
        try:
            items = NetworkResetTool().list_adapters()
        except Exception as e:
            items = []
            safe_after(self, lambda: self._log(f"  ⚠ 枚举网卡失败: {e}"))

        def _render():
            try:
                if not self.winfo_exists():
                    return
            except Exception:
                return
            previous = self.selected_adapter()

            labels = [ADAPTER_AUTO]
            mapping = {ADAPTER_AUTO: None}
            for it in items:
                label = it['name']
                if it.get('ip'):
                    label += f"  ·  {it['ip']}"
                if it.get('gw'):
                    label += "  ★"          # ★ = 有默认网关，通常是真正的出口
                labels.append(label)
                mapping[label] = it['name']

            self._adapter_map = mapping
            self.adapter_combo.configure(values=labels)
            # 保持用户之前的选择；若网卡已消失则退回自动检测
            if previous and previous in mapping.values():
                label = next(k for k, v in mapping.items() if v == previous)
                self.adapter_var.set(label)
            else:
                self.adapter_var.set(ADAPTER_AUTO)

            self.btn_refresh_nic.config(state="normal")
            if items:
                self._set_status(f"✅ 检测到 {len(items)} 块网卡", COLORS["green"])
                if not silent:
                    self._log(f"🔎 检测到 {len(items)} 块网卡：")
                    for it in items:
                        self._log(f"    - {it['name']}"
                                  + (f" ({it['ip']})" if it.get('ip') else "")
                                  + (tr("  ★出口") if it.get('gw') else ""))
            elif not silent:
                self._set_status(tr("⚠ 未检测到网卡"), COLORS["yellow"])

        ui_sync(self, _render)

    def _get_active_adapter(self):
        """获取网卡名称 - 优先用户手动指定，其次自动检测（Win7 兼容）"""
        manual = self.selected_adapter()
        if manual:
            self._safe_log(f"  ✓ 使用手动指定的网卡: {manual}")
            return manual
        if IS_MAC:
            name = _mac_primary_service()
            if name:
                self._safe_log(f"  ✓ 检测到网络服务(macOS): {name}")
            return name
        # Win7: 先试 WMI（更可靠）
        if _is_win7_or_older():
            try:
                ps_wmi = '''
$cfgs = Get-WmiObject Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -eq $true }
$pick = $null
foreach ($c in $cfgs) { if ($c.DefaultIPGateway) { $pick = $c; break } }
if (-not $pick) { $pick = $cfgs | Select-Object -First 1 }
if ($pick) {
    $adapter = Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.GUID -eq $pick.SettingID } | Select-Object -First 1
    if ($adapter) { Write-Output $adapter.NetConnectionID }
}
'''
                result = subprocess.run(['powershell', '-NoProfile', '-Command', ps_wmi],
                                       capture_output=True, timeout=5)
                name = self._decode_output(result.stdout).strip()
                if name:
                    self._safe_log(f"  ✓ 检测到网卡(WMI): {name}")
                    return name
            except Exception:
                pass
        else:
            # Win8+: 先试 Get-NetAdapter
            try:
                ps1 = '''
$best = $null
foreach ($a in (Get-NetAdapter | Where-Object { $_.Status -eq 'Up' })) {
    $c = Get-NetIPConfiguration -InterfaceIndex $a.ifIndex -ErrorAction SilentlyContinue
    if ($c -and $c.IPv4DefaultGateway) { $best = $a; break }
    if (-not $best) { $best = $a }
}
if ($best) { Write-Output $best.NetConnectionID }
'''
                result = subprocess.run(['powershell', '-NoProfile', '-Command', ps1],
                                       capture_output=True, timeout=5)
                name = self._decode_output(result.stdout).strip()
                if name:
                    return name
            except Exception as e:
                self._safe_log(f"Get-NetAdapter 失败: {e}")

        # 通用备选: WMI (Win7/Win8+ 均可)
        try:
            ps2 = '''
$cfgs = Get-WmiObject Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -eq $true }
$pick = $null
foreach ($c in $cfgs) { if ($c.DefaultIPGateway) { $pick = $c; break } }
if (-not $pick) { $pick = $cfgs | Select-Object -First 1 }
if ($pick) {
    $adapter = Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.GUID -eq $pick.SettingID } | Select-Object -First 1
    if ($adapter) { Write-Output $adapter.NetConnectionID }
}
'''
            result = subprocess.run(['powershell', '-NoProfile', '-Command', ps2],
                                   capture_output=True, timeout=5)
            name = self._decode_output(result.stdout).strip()
            if name:
                return name
        except Exception as e:
            self._safe_log(f"WMI 查询失败: {e}")

        # ipconfig 解析
        try:
            result = subprocess.run(['ipconfig'], capture_output=True, timeout=5)
            output = self._decode_output(result.stdout)
            # 查找 "适配器 xxx:" 段落后有 IPv4 地址
            in_adapter = False
            for line in output.split('\n'):
                if '适配器' in line or 'adapter' in line.lower():
                    in_adapter = True
                    m = re.match(tr(r'.*(?:适配器|adapter)\s+(.+?):'), line)
                    current_name = m.group(1).strip() if m else None
                elif in_adapter and 'IPv4' in line:
                    if current_name:
                        self._safe_log(f"  ✓ 检测到网卡(ipconfig): {current_name}")
                        return current_name
        except Exception:
            pass

        self._safe_log(tr("  ⚠ 未找到活动网卡"))
        return None

    def _make_dns_btn(self, parent, name, cfg):
        # color 存的是语义键名(见 _shared.DNS_PRESETS), 这里按当前主题解析,
        # 否则深浅主题切换后按钮仍停留在旧主题的固定色值。
        accent = COLORS[cfg['color']]
        btn = tk.Button(parent, text=tr(name), font=(FONT_FAMILY, 9, "bold"),
                        bg=accent, fg=COLORS["bg"],
                        activebackground=accent, activeforeground=COLORS["bg"],
                        relief="flat", cursor="hand2", padx=5, pady=4,
                        command=lambda n=name: self._do_dns_switch(n))
        return attach_tooltip(btn, dns_preset_tip(cfg))

    def _do_dns_switch(self, preset_name):
        if self._running:
            return
        self._set_running(True, f"切换 DNS 到 {preset_name}")
        threading.Thread(target=self._thread_dns_switch,
                        args=(preset_name,), daemon=True).start()

    def _thread_dns_switch(self, preset_name):
        """修复: 使用默认参数避免lambda捕获bug"""
        adapter = self._get_active_adapter()
        if not adapter:
            # 修复: 使用after和默认参数
            safe_after(self, functools.partial(self._log, tr("⚠ 未找到活动网卡,请检查网络连接")))
            safe_after(self, functools.partial(self._set_running, False, ""))
            safe_after(self, functools.partial(self._set_status, tr("⚠ 未找到活动网卡"), COLORS["orange"]))
            return
        # 修复: 使用functools.partial避免lambda捕获问题
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.switch_dns(preset_name, adapter)
        safe_after(self, functools.partial(self._set_running, False, ""))
        safe_after(self, functools.partial(self._set_status, f"✅ DNS 已切换到 {preset_name}", COLORS["green"]))
        safe_after(self, self._refresh_dns_status)

    def _safe_log(self, msg):
        """线程安全的日志输出"""
        safe_after(self, functools.partial(self._log, msg))

    # ----- DNS 测速排序(F9) -----
    def _do_dns_bench(self):
        if self._running:
            return
        self._set_running(True, tr("DNS 测速排序"))
        self.dns_bench_label.config(text=tr("⏳ 测速中..."), fg=COLORS["muted"])
        self._fastest_preset = None
        threading.Thread(target=self._thread_dns_bench, daemon=True).start()

    def _thread_dns_bench(self):
        diag = NetworkDiagnostic()

        def _progress(name, done, total):
            safe_after(self, functools.partial(
                self._set_status, f"⏳ DNS 测速: {name} {done}/{total}"))

        try:
            ranked = diag.benchmark_dns(rounds=3, progress_callback=_progress)
        except Exception as e:
            safe_after(self, functools.partial(self._set_running, False, ""))
            safe_after(self, functools.partial(
                self._set_status, f"❌ DNS 测速失败: {e}", COLORS["red"]))
            return
        safe_after(self, functools.partial(self._render_dns_bench, ranked))

    def _render_dns_bench(self, ranked):
        lines = []
        fastest = None
        for idx, r in enumerate(ranked, 1):
            if r["avg_ms"] is None:
                lines.append(f"  {idx}. {r['name']}({r['primary']}) → 全部失败")
            else:
                fail = f" (失败 {r['fail_rounds']} 次)" if r["fail_rounds"] else ""
                lines.append(f"  {idx}. {r['name']}({r['primary']}) → {r['avg_ms']}ms{fail}")
                if fastest is None:
                    fastest = r["name"]
        self._log(tr("⚡ DNS 测速排序(www.baidu.com 各 3 次取平均):"))
        for line in lines:
            self._log(line)
        # 先解除运行态(会按基线还原按钮), 再单独放开"应用最快"
        self._set_running(False, "")
        self._fastest_preset = fastest
        if fastest:
            self.btn_apply_fastest.config(state="normal")
            self.dns_bench_label.config(text=f"🏆 最快: {fastest}", fg=COLORS["green"])
            self._log(f"🏆 最快: {fastest}，点「🏆 应用最快」一键切换")
        else:
            self.btn_apply_fastest.config(state="disabled")
            self.dns_bench_label.config(text=tr("全部 DNS 均失败"), fg=COLORS["red"])

    def _do_apply_fastest(self):
        name = getattr(self, "_fastest_preset", None)
        if not name:
            self._set_status(tr("⚠ 请先点「⚡ DNS 测速排序」"), COLORS["orange"])
            return
        self._do_dns_switch(name)

    def _do_custom_dns(self):
        if self._running:
            return
        primary = self.dns_primary_entry.get().strip()
        if not primary:
            self._set_status(tr("⚠ 请输入主 DNS 地址"), COLORS["orange"])
            return
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', primary):
            self._set_status(tr("⚠ DNS 地址格式不正确"), COLORS["red"])
            return
        secondary = self.dns_secondary_entry.get().strip()
        self._set_running(True, f"设置自定义 DNS: {primary}")
        threading.Thread(target=self._thread_custom_dns,
                        args=(primary, secondary), daemon=True).start()

    def _thread_custom_dns(self, primary, secondary):
        adapter = self._get_active_adapter()
        if not adapter:
            safe_after(self, functools.partial(self._log, tr("⚠ 未找到活动网卡")))
            safe_after(self, functools.partial(self._set_running, False, ""))
            return
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.log(f"[DNS] 自定义 DNS: {primary}")
        ok = tool.set_dns(adapter, primary, secondary if secondary else None)
        tool.flush_dns()
        safe_after(self, functools.partial(self._set_running, False, ""))
        safe_after(self, functools.partial(self._set_status,
            f"✅ 自定义 DNS 设置成功" if ok else tr("❌ DNS 设置失败"),
            COLORS["green"] if ok else COLORS["red"]))
        safe_after(self, self._refresh_dns_status)

    def _refresh_dns_status(self):
        """刷新当前 DNS 显示(异步,不阻塞主线程)"""
        self.dns_current_label.config(text=tr("当前: 获取中..."))

        # 在主线程把选择读出来，避免工作线程访问 Tk 变量
        adapter = self.selected_adapter()

        def _worker():
            tool = NetworkResetTool()
            dns_list, mode = tool.get_current_dns(adapter)
            if dns_list:
                mode_text = tr("自动") if mode == "dhcp" else tr("手动")
                text = f"当前: {', '.join(dns_list)} [{mode_text}]"
            else:
                text = tr("当前: 未知")
            safe_after(self, lambda: self.dns_current_label.config(text=text))

        threading.Thread(target=_worker, daemon=True).start()

    def _log(self, msg):
        """修复: 确保线程安全"""
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

    def _set_running(self, running, task="", cancellable=False):
        # 运行期间禁用全部操作控件（原来只禁用了"一键重置"，其余按钮可并发点击
        # → 多条 netsh 命令交错执行，是配置被改乱的隐患），结束后按基线精确还原。
        self._running = running
        for w, base in getattr(self, "_baseline_state", {}).items():
            try:
                w.config(state="disabled" if running else base)
            except Exception:
                pass
        # 「取消」只在可中断的长任务(一键重置)期间可用
        try:
            self.btn_cancel.config(state="normal" if (running and cancellable) else "disabled")
        except Exception:
            pass
        if task:
            self._set_status(f"⏳ 正在执行: {task}...")
            self.progress.start(10)
        else:
            self._set_status(tr("✅ 操作完成"), COLORS["green"])
            self.progress.stop()

    # ----- 单独操作 -----
    def _do_winsock(self):
        if self._running: return
        self._set_running(True, tr("重置 Winsock"))
        threading.Thread(target=self._thread_winsock, daemon=True).start()

    def _thread_winsock(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        ok = tool.reset_winsock()
        safe_after(self, functools.partial(self._set_running, False, ""))
        safe_after(self, functools.partial(self._set_status,
            tr("✅ Winsock 重置完成") if ok else tr("❌ 操作失败"),
            COLORS["green"] if ok else COLORS["red"]))
        safe_after(self, functools.partial(self._log, tr("\n⚠ 可能需要重启电脑使设置生效")))

    def _do_tcpip(self):
        if self._running: return
        self._set_running(True, tr("重置 TCP/IP"))
        threading.Thread(target=self._thread_tcpip, daemon=True).start()

    def _thread_tcpip(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.reset_tcpip()
        safe_after(self, functools.partial(self._set_running, False, ""))
        safe_after(self, functools.partial(self._set_status, tr("✅ TCP/IP 重置完成"), COLORS["green"]))
        safe_after(self, functools.partial(self._log, tr("\n⚠ 必须重启电脑使设置生效")))

    def _do_dns(self):
        if self._running: return
        self._set_running(True, tr("清除 DNS 缓存"))
        threading.Thread(target=self._thread_dns, daemon=True).start()

    def _thread_dns(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        ok = tool.flush_dns()
        safe_after(self, functools.partial(self._set_running, False, ""))
        safe_after(self, functools.partial(self._set_status,
            tr("✅ DNS 缓存已清除") if ok else tr("❌ 操作失败"),
            COLORS["green"] if ok else COLORS["red"]))

    def _do_arp(self):
        if self._running: return
        self._set_running(True, tr("清除 ARP 缓存"))
        threading.Thread(target=self._thread_arp, daemon=True).start()

    def _thread_arp(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        ok = tool.flush_arp()
        safe_after(self, functools.partial(self._set_running, False, ""))
        safe_after(self, functools.partial(self._set_status,
            tr("✅ ARP 缓存已清除") if ok else tr("❌ 操作失败"),
            COLORS["green"] if ok else COLORS["red"]))

    def _do_dhcp(self):
        if self._running: return
        self._set_running(True, tr("刷新 DHCP"))
        threading.Thread(target=self._thread_dhcp, daemon=True).start()

    def _thread_dhcp(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.renew_dhcp()
        safe_after(self, functools.partial(self._set_running, False, ""))
        safe_after(self, functools.partial(self._set_status, tr("✅ DHCP 已刷新"), COLORS["green"]))

    def _do_backup(self):
        if self._running: return
        self._set_running(True, tr("备份 IP 配置"))
        threading.Thread(target=self._thread_backup, daemon=True).start()

    def _thread_backup(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.backup_static_ip()
        self._static_configs = tool.static_configs
        if tool.static_configs:
            self._save_backup(tool.static_configs)
        safe_after(self, functools.partial(self._set_running, False, ""))
        safe_after(self, functools.partial(self._set_status, tr("✅ IP 配置备份完成"), COLORS["green"]))

    def _do_restore(self):
        if self._running: return
        if not self._static_configs:
            self._static_configs = self._load_backup()   # 重开程序后也能还原
        if not self._static_configs:
            self._log(tr("⚠ 请先点击「备份IP」按钮"))
            self._set_status(tr("⚠ 请先备份IP"), COLORS["orange"])
            return
        self._set_running(True, tr("还原 IP 配置"))
        threading.Thread(target=self._thread_restore, daemon=True).start()

    def _thread_restore(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.static_configs = self._static_configs
        tool.restore_static_ip()
        safe_after(self, functools.partial(self._set_running, False, ""))
        safe_after(self, functools.partial(self._set_status, tr("✅ IP 配置已还原"), COLORS["green"]))

    # ----- 配置快照与回滚 (F2) -----
    def _do_snapshot(self):
        if self._running:
            return
        self._set_running(True, tr("建立配置快照"))
        threading.Thread(target=self._thread_snapshot, daemon=True).start()

    def _thread_snapshot(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        try:
            snap = tool.take_snapshot()
            path = NetworkResetTool.save_snapshot(snap)
            n = len(snap.get('adapters') or {})
            safe_after(self, functools.partial(self._set_status,
                                            f"✅ 快照已保存（{n} 块网卡）", COLORS["green"]))
            safe_after(self, functools.partial(self._safe_log, f"📸 快照已保存: {path}"))
        except Exception as e:
            safe_after(self, functools.partial(self._set_status,
                                            f"❌ 快照失败: {e}", COLORS["red"]))
        finally:
            safe_after(self, functools.partial(self._set_running, False, ""))

    def _do_rollback(self):
        if self._running:
            return
        snaps = NetworkResetTool.list_snapshots()
        if not snaps:
            messagebox.showinfo(tr("没有快照"), "还没有任何配置快照。\n\n"
                                            "建议先点「📸 建快照」，或在「一键重置全部」时自动创建。")
            return
        path, ts, n = snaps[0]
        others = len(snaps) - 1
        extra = f"\n（另有 {others} 个历史快照，回滚默认使用最新一个）" if others else ""
        restore_ip = messagebox.askyesno(
            tr("回滚确认"),
            f"将把网络配置恢复到快照时间：\n  {ts}\n  包含 {n} 块网卡的配置{extra}\n\n"
            f"● 恢复各网卡的 DNS 设置\n● 恢复系统代理设置\n\n"
            f"是否同时恢复静态 IP / 子网掩码 / 网关？（DHCP 网络请选择「否」）")
        self._set_running(True, tr("回滚网络配置"))
        threading.Thread(target=self._thread_rollback, args=(path, restore_ip), daemon=True).start()

    def _thread_rollback(self, path, restore_ip=False):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        try:
            with open(path, encoding='utf-8') as f:
                snap = json.load(f)
            safe_after(self, functools.partial(
                self._safe_log, f"⏪ 开始回滚到 {snap.get('time', '未知时间')} 的快照..."))
            done, total = tool.rollback_snapshot(snap, restore_ip=restore_ip)
            if total == 0:
                safe_after(self, functools.partial(self._set_status,
                                                tr("⚠ 快照里没有可恢复项"), COLORS["orange"]))
            elif done == total:
                safe_after(self, functools.partial(self._set_status,
                                                f"✅ 回滚完成（{done}/{total}）", COLORS["green"]))
            else:
                safe_after(self, functools.partial(self._set_status,
                                                f"⚠ 回滚部分成功（{done}/{total}）", COLORS["orange"]))
        except Exception as e:
            safe_after(self, functools.partial(self._set_status,
                                            f"❌ 回滚失败: {e}", COLORS["red"]))
        finally:
            safe_after(self, functools.partial(self._set_running, False, ""))
            safe_after(self, self._refresh_dns_status)

    # ----- 一键重置 -----
    def _do_all_reset(self):
        if self._running: return
        if not messagebox.askyesno(tr("确认"), "将执行完整网络重置:\n\n"
                               "0. 自动建立配置快照(可用「⏪ 回滚」还原)\n"
                               "1. 备份静态IP配置\n"
                               "2. 重置 Winsock\n"
                               "3. 重置 TCP/IP\n"
                               "4. 清除 DNS/ARP 缓存\n"
                               "5. 刷新 DHCP\n"
                               "6. 恢复静态IP(如有)\n\n"
                               "确定要继续吗?"):
            return
        self._set_running(True, tr("一键重置全部"), cancellable=True)
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        threading.Thread(target=self._thread_all_reset, daemon=True).start()

    def _thread_all_reset(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        self._current_tool = tool
        try:
            # 重置前自动建快照：万一重置后上不了网，还能用「⏪ 回滚」还原
            try:
                path = NetworkResetTool.save_snapshot(tool.take_snapshot())
                safe_after(self, functools.partial(self._safe_log, f"📸 重置前已自动建立快照: {path}"))
            except Exception as e:
                safe_after(self, functools.partial(
                    self._safe_log, f"⚠ 自动快照失败（不影响重置）: {e}"))
            tool.run_full_reset()
        finally:
            self._current_tool = None
        safe_after(self, functools.partial(self._set_running, False, ""))
        safe_after(self, lambda: self.btn_restart.config(state="normal"))

    def _do_cancel(self):
        """请求中断当前任务（在下一个步骤边界生效，不会强行杀掉系统命令）。"""
        if self._current_tool:
            self._current_tool._cancel = True
            self._log(tr("⏹ 已请求取消,将在当前步骤结束后停止..."))
            self._set_status(tr("⏹ 取消中..."), COLORS["orange"])

    def _restart(self):
        if messagebox.askyesno(tr("确认重启"), tr("网络重置后需要重启电脑才能生效\n\n确定要立即重启吗?")):
            # 使用 shutdown.exe 替代 Restart-Computer（Win7 兼容）
            try:
                subprocess.run(['shutdown', '/r', '/f', '/t', '5', '/c', tr('网络重置后系统将重启')])
                self._log(tr("5秒后重启电脑..."))
            except Exception as e:
                self._log(f"重启失败: {e}")

    def _quit(self):
        if messagebox.askyesno(tr("确认退出"), tr("确定要退出程序吗?")):
            self.destroy()

def theme_scrollbar(parent, command, **kw):
    """造一个跟当前主题同色的 tk.Scrollbar(F11)。

    tk.Scrollbar 不支持 ttk style, 不显式传色就会退回系统配色
    (SystemButtonFace), 深色界面里一条灰白滚动条非常扎眼。
    """
    return tk.Scrollbar(parent, command=command,
                        bg=COLORS["surface2"], troughcolor=COLORS["bg2"],
                        activebackground=COLORS["surface"],
                        highlightthickness=0, bd=0, **kw)


def config_treeview_style(widget):
    """让 ttk.Treeview/滚动条跟上当前主题配色(F11)。

    ttk 控件不吃 tk 的 bg/fg 关键字, 必须显式配 style; 主题切换时面板会整体重建,
    本函数随之重跑, 所以样式永远跟随 COLORS。失败(旧 Tk 缺样式)时静默降级。
    """
    try:
        style = ttk.Style(widget)
        style.theme_use("default")
        style.configure("nice.Treeview",
                        background=COLORS["bg2"], fieldbackground=COLORS["bg2"],
                        foreground=COLORS["text"], borderwidth=0, rowheight=22)
        style.configure("nice.Treeview.Heading",
                        background=COLORS["surface2"], foreground=COLORS["text"],
                        relief="flat", padding=(4, 4))
        style.map("nice.Treeview.Heading",
                  background=[("active", COLORS["surface"]),
                              ("pressed", COLORS["surface"])])
        style.map("nice.Treeview",
                  background=[("selected", COLORS["blue"])],
                  foreground=[("selected", COLORS["bg"])])
        style.configure("nice.Vertical.TScrollbar",
                        background=COLORS["surface2"], troughcolor=COLORS["bg2"],
                        borderwidth=0, arrowcolor=COLORS["subtext"])
        return style
    except Exception:
        return None


def _grade_color(grade):
    """健康评分 -> 主题色。

    键必须和 compute_health 返回的 grade 同源: 那边给的就是
    tr(优秀/良好/一般/较差)。这里若写死中文键, 切到英文界面时
    就会全部落到 subtext(灰色), 评分卡片就没带色了。
    """
    return {tr("优秀"): COLORS["green"],
            tr("良好"): COLORS["blue"],
            tr("一般"): COLORS["yellow"],
            tr("较差"): COLORS["red"]}.get(grade, COLORS["subtext"])


class ResultPanel(tk.Frame):
    """DiagnosticPanel / ProxyPanel 的公共基类（v4.0 抽取，消除约 60 行重复）。

    负责结果区的 canvas+scrollbar 骨架, 以及 `_card` / `_result_ok|fail|info` /
    `_clear_results` 这些渲染组件; 子类在自己的 `_build_ui()` 里调
    `self._build_results(self)` 搭结果区, 并实现各自文案的 `_show_hint()`。
    """

    _decode_output = staticmethod(decode_output)

    def __init__(self, parent, bg=None):
        super().__init__(parent, bg=bg or COLORS["bg"])
        self._running = False

    def _build_results(self, parent_widget):
        """在 parent_widget 内创建 canvas+scrollbar 结果区, 填充 self.results_inner。"""
        result_frame = tk.Frame(parent_widget, bg=COLORS["bg"])
        result_frame.pack(fill="both", expand=True, padx=20, pady=8)
        canvas = tk.Canvas(result_frame, bg=COLORS["bg2"], highlightthickness=0)
        scrollbar = theme_scrollbar(result_frame, canvas.yview, orient="vertical")
        self.results_inner = tk.Frame(canvas, bg=COLORS["bg2"])
        self.results_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.results_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return self.results_inner

    def _clear_results(self):
        for w in self.results_inner.winfo_children():
            w.destroy()

    # ---- 结果区复用组件 ----
    def _card(self, parent, title, bg=None):
        bg = COLORS["surface"] if bg is None else bg
        f = tk.Frame(parent, bg=bg, padx=12, pady=8)
        f.pack(fill="x", pady=2)
        tk.Label(f, text=title, font=(FONT_FAMILY, 10, "bold"),
                 fg=COLORS["text"], bg=bg).pack(anchor="w")
        return f

    def _result_ok(self, parent, text, sub=""):
        tk.Label(parent, text=f"  ✅ {text}", font=(FONT_FAMILY, 10),
                 fg=COLORS["green"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)
        if sub:
            tk.Label(parent, text=f"      {sub}", font=(FONT_FAMILY, 9),
                     fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    def _result_fail(self, parent, text, sub=""):
        tk.Label(parent, text=f"  ❌ {text}", font=(FONT_FAMILY, 10),
                 fg=COLORS["red"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)
        if sub:
            tk.Label(parent, text=f"      {sub}", font=(FONT_FAMILY, 9),
                     fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    def _result_info(self, parent, text):
        tk.Label(parent, text=f"  {text}", font=(FONT_FAMILY, 9),
                 fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    def _show_hint(self):
        raise NotImplementedError  # 子类提供各自文案


class DiagnosticPanel(ResultPanel):
    """右侧"网络诊断"标签页"""

    _decode_output = staticmethod(decode_output)

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        self._latest_results = None
        self._build_ui()

    def _build_ui(self):
        # 标题
        header = tk.Frame(self, bg=COLORS["surface"], pady=12)
        header.pack(fill="x")
        tk.Label(header, text=tr("🔍 网络诊断工具"), font=(FONT_FAMILY, 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text=tr("一键检测网络状态 · Ping / DNS / 路由追踪"),
                 font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        # 按钮行
        ctrl = tk.Frame(self, bg=self["bg"], pady=10, padx=20)
        ctrl.pack(fill="x")

        self.btn_all_diag = styled_btn(ctrl, tr("🚀 一键完整诊断"), self._do_full_diagnostic,
                                        COLORS["green"], font_size=12, bold=True,
                                        tip="依次跑网络总览 + 多个目标 Ping + 多组 DNS 解析，\n"
                                            "给出连通性结论与评分。全程约 30~60 秒，可点「导出报告」存档。")
        self.btn_all_diag.pack(side="left", padx=(0, 8))

        self.btn_quick = styled_btn(ctrl, tr("⚡ 快速 Ping"), self._do_quick_ping,
                                     COLORS["blue"], font_size=11,
                                     tip="Ping 网关、常用公网与 DNS，判断本机到外网通不通。\n"
                                         "只看连通性，几秒出结果，不改动任何配置。")
        self.btn_quick.pack(side="left", padx=4)

        self.btn_overview = styled_btn(ctrl, tr("📋 网络总览"), self._do_overview,
                                        COLORS["sky"], font_size=11,
                                        tip="显示当前网卡的接口状态、IPv4/掩码、默认网关、\n"
                                            "MAC、DNS 服务器与 DHCP 状态。只读，不改配置。")
        self.btn_overview.pack(side="left", padx=4)

        self.btn_traceroute = styled_btn(ctrl, "🛤️ Traceroute", self._do_traceroute,
                                          COLORS["purple"], font_size=11,
                                          tip="逐跳追踪到右侧输入框目标的路由，看在哪一跳断流。\n"
                                              "目标越远越慢，境外地址可能要几分钟。")
        self.btn_traceroute.pack(side="left", padx=4)

        self.btn_health = styled_btn(ctrl, tr("📊 健康报告"), self._do_health_report,
                                      COLORS["teal"], font_size=11,
                                      tip="重新完整诊断一次，再按连通性 / DNS / 配置完整度 /\n"
                                          "平均延迟 / 丢包打分，给出等级与整改建议。")
        self.btn_health.pack(side="left", padx=4)

        self.btn_export = styled_btn(ctrl, tr("📄 导出报告"), self._do_export,
                                      COLORS["mauve"], font_size=11,
                                      tip="把最近一次诊断结果另存为 HTML(可打印)/ Markdown / TXT，\n"
                                          "便于留档或发给别人排查。\n"
                                          "还没有数据时会先自动跑一次完整诊断。")
        self.btn_export.pack(side="left", padx=4)

        self.btn_hosts = styled_btn(ctrl, tr("🧹 hosts 检查"), self._do_hosts,
                                    COLORS["yellow"], font_size=11,
                                    tip="检查 hosts 文件里被写脏的条目(指向外部 IP 的域名映射)。\n"
                                        "支持一键注释可疑条目, 改动前会自动备份, 可随时还原。\n"
                                        "写入需要管理员权限。")
        self.btn_hosts.pack(side="left", padx=4)

        # 自定义 Ping 输入
        self.custom_target = tk.StringVar(value="www.baidu.com")
        tk.Entry(ctrl, textvariable=self.custom_target, font=(FONT_MONO, 10),
                 bg=COLORS["surface"], fg=COLORS["text"], insertbackground=COLORS["text"],
                 relief="flat", bd=0, width=14).pack(side="left", padx=(10, 4))
        self.btn_custom_ping = styled_btn(ctrl, "Ping", self._do_custom_ping, COLORS["orange"], font_size=11,
                                          tip="只 Ping 左边输入框里的目标(4 个包)并显示原始输出。\n"
                                              "支持域名或 IPv4/IPv6 地址。")
        self.btn_custom_ping.pack(side="left")

        # 进度条
        self.diag_progress = ttk.Progressbar(self, mode="determinate",
                                              style="diag.Horizontal.TProgressbar")
        self.diag_progress.pack(fill="x", padx=20, pady=(0, 5))

        self.diag_status = tk.Label(self, text=tr("就绪"), font=(FONT_FAMILY, 9),
                                     fg=COLORS["muted"], bg=self["bg"], anchor="w")
        self.diag_status.pack(fill="x", padx=20)

        # 结果区域(Canvas + Scrollbar) —— 骨架由 ResultPanel 提供
        self._build_results(self)

        # 样式
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("diag.Horizontal.TProgressbar",
                        troughcolor=COLORS["surface"], background=COLORS["blue"], thickness=6)

        # 欢迎提示
        self._show_hint()

    def _show_hint(self):
        for w in self.results_inner.winfo_children():
            w.destroy()
        hint = tk.Label(self.results_inner,
                        text=tr("点击上方按钮开始诊断\n\n📡 Ping 测试:检测到目标的网络延迟和连通性\n"
                             "🔍 DNS 解析:测试各 DNS 服务器解析是否正常\n"
                             "🛤️ Traceroute:追踪本机到目标的网络路由路径\n"
                             "📋 网络总览:显示当前 IP/网关/DNS 等信息"),
                        font=(FONT_FAMILY, 11), fg=COLORS["muted"], bg=COLORS["bg2"],
                        justify="left", padx=20, pady=30)
        hint.pack(fill="both", expand=True)

    def _set_diag_status(self, msg, color=None):
        if color is None:
            color = COLORS["muted"]
        self.diag_status.config(text=msg, fg=color)

    def _set_running(self, running):
        self._running = running
        state = "disabled" if running else "normal"
        for btn in [self.btn_all_diag, self.btn_quick, self.btn_overview,
                    self.btn_traceroute, self.btn_health, self.btn_export,
                    self.btn_hosts]:
            btn.config(state=state)
        if running:
            self.diag_progress.start(8)
        else:
            self.diag_progress.stop()

    # ---- 快速 Ping ----
    def _do_quick_ping(self):
        if self._running: return
        self._set_running(True)
        self.diag_progress.configure(mode="indeterminate")
        self.diag_progress.start(8)
        self._set_diag_status(tr("⏳ Ping 测试中..."), COLORS["blue"])
        self._clear_results()
        threading.Thread(target=self._thread_quick_ping, daemon=True).start()

    def _thread_quick_ping(self):
        diag = NetworkDiagnostic()
        results = []
        for target, label, _color in NetworkDiagnostic.PING_TARGETS:
            ok, avg_ms, loss, _ = diag.ping(target)
            label = tr(label)  # 规范中文存储, 展示时才翻译
            results.append((target, label, ok, avg_ms, loss))

        def _render():
            self._clear_results()
            row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            row.pack(fill="x", pady=4, padx=4)
            card = self._card(row, tr("📡 Ping 连通性测试"))

            all_ok = True
            for target, label, ok, avg_ms, loss in results:
                # avg_ms 在 <1ms 时为 None，需兜底
                latency_str = f"{avg_ms}ms" if avg_ms is not None else "<1ms"
                if ok:
                    self._result_ok(card, f"{label} ({target})",
                                    f"延迟 {latency_str} · 丢包率 {loss}%")
                else:
                    all_ok = False
                    self._result_fail(card, f"{label} ({target})", f"丢包率 {loss}%")

            self._set_running(False)
            self.diag_progress.stop()
            self.diag_progress.configure(mode="determinate")
            if all_ok:
                self._set_diag_status(tr("✅ 所有目标 Ping 正常"), COLORS["green"])
            else:
                self._set_diag_status(tr("⚠ 部分目标连接异常,可尝试网络重置"), COLORS["yellow"])

        ui_sync(self, _render)

    # ---- 网络总览 ----
    def _do_overview(self):
        if self._running: return
        self._set_running(True)
        self._clear_results()
        self._set_diag_status(tr("⏳ 读取网络信息..."), COLORS["sky"])
        threading.Thread(target=self._thread_overview, daemon=True).start()

    def _thread_overview(self):
        diag = NetworkDiagnostic()
        overview = diag.get_overview()

        def _render():
            self._clear_results()
            row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            row.pack(fill="x", pady=4, padx=4)
            card = self._card(row, tr("📋 网络状态总览"))

            if overview:
                label_map = {
                    "状态": tr("接口状态"),
                    "接口": tr("网卡名称"),
                    "描述": tr("网卡描述"),
                    "MAC": tr("MAC 地址"),
                    "速度": tr("连接速度"),
                    "IPv4": tr("IPv4 地址"),
                    "网关": tr("默认网关"),
                    "DNS": tr("DNS 服务器"),
                    "DHCP": tr("DHCP 状态"),
                }
                for k, v in overview:
                    label = label_map.get(k, k)
                    self._result_info(card, f"{label}:{v}")
            else:
                self._result_fail(card, tr("无法获取网络信息"))

            self._set_running(False)
            self._set_diag_status(tr("✅ 网络总览完成"), COLORS["green"])

        ui_sync(self, _render)

    # ---- Traceroute ----
    def _do_traceroute(self):
        if self._running: return
        target = self.custom_target.get().strip()
        if not target:
            self._set_diag_status(tr("⚠ 请输入目标地址"), COLORS["orange"])
            return
        if not is_valid_target(target):
            self._set_diag_status(f"⚠ 目标地址不合法: {target}", COLORS["red"])
            return
        self._set_running(True)
        self._clear_results()
        self._set_diag_status(f"⏳ 追踪路由到 {target}...", COLORS["purple"])
        threading.Thread(target=self._thread_traceroute, args=(target,), daemon=True).start()

    def _thread_traceroute(self, target):
        diag = NetworkDiagnostic()
        output = diag.traceroute(target)

        def _render():
            self._clear_results()
            row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            row.pack(fill="both", expand=True, pady=4, padx=4)
            card = self._card(row, f"🛤️ 路由追踪: {target}")

            text_widget = tk.Text(card, font=(FONT_MONO, 9), bg=COLORS["bg2"],
                                  fg=COLORS["subtext"], relief="flat", bd=0,
                                  height=min(20, max(10, len(output.split('\n')))))
            text_widget.pack(fill="x", padx=8, pady=4)
            text_widget.insert("1.0", output)
            text_widget.configure(state="disabled")

            def copy_trace():
                self.clipboard_clear()
                self.clipboard_append(output)
                self._set_diag_status(tr("✅ 路由追踪结果已复制"), COLORS["green"])

            attach_tooltip(tk.Button(card, text=tr("📋 复制结果"), font=(FONT_FAMILY, 9),
                      bg=COLORS["surface"], fg=COLORS["text"],
                      relief="flat", cursor="hand2",
                      command=copy_trace),
                        tr("把上面的路由追踪原始文本复制到剪贴板，便于粘贴到反馈里。")).pack(anchor="e", padx=10, pady=4)

            self._set_running(False)
            self._set_diag_status(tr("✅ 追踪完成"), COLORS["green"])

        ui_sync(self, _render)

    # ---- 自定义 Ping ----
    def _do_custom_ping(self):
        if self._running: return
        target = self.custom_target.get().strip()
        if not target:
            self._set_diag_status(tr("⚠ 请输入目标地址"), COLORS["orange"])
            return
        if not is_valid_target(target):
            self._set_diag_status(f"⚠ 目标地址不合法: {target}", COLORS["red"])
            return
        self._set_running(True)
        self.diag_progress.configure(mode="indeterminate")
        self.diag_progress.start(8)
        self._clear_results()
        self._set_diag_status(f"⏳ Ping {target}...", COLORS["orange"])
        threading.Thread(target=self._thread_custom_ping, args=(target,), daemon=True).start()

    def _thread_custom_ping(self, target):
        diag = NetworkDiagnostic()
        ok, avg_ms, loss, output = diag.ping(target, count=4)

        def _render():
            self._clear_results()
            row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            row.pack(fill="both", expand=True, pady=4, padx=4)
            card = self._card(row, f"📡 Ping: {target}")

            latency_str = f"{avg_ms}ms" if avg_ms is not None else "<1ms"
            if ok:
                self._result_ok(card, tr("连接正常"), f"延迟 {latency_str} · 丢包率 {loss}%")
            else:
                self._result_fail(card, tr("连接失败"), f"丢包率 {loss}%")

            raw = tk.Text(card, font=(FONT_MONO, 9), bg=COLORS["bg2"],
                          fg=COLORS["subtext"], relief="flat", bd=0,
                          height=min(12, max(5, len(output.split('\n')))))
            raw.pack(fill="x", padx=8, pady=4)
            raw.insert("1.0", output)
            raw.configure(state="disabled")

            self._set_running(False)
            self.diag_progress.stop()
            self.diag_progress.configure(mode="determinate")

        ui_sync(self, _render)

    # ---- 一键完整诊断 ----
    def _do_full_diagnostic(self):
        if self._running: return

        self._set_running(True)
        self.diag_progress.configure(mode="determinate")
        self.diag_progress["value"] = 0
        self._clear_results()
        self._set_diag_status(tr("⏳ 完整诊断中..."), COLORS["green"])
        threading.Thread(target=self._thread_full_diagnostic, daemon=True).start()

    def _thread_full_diagnostic(self):
        diag = NetworkDiagnostic()

        def progress(pct, msg):
            safe_after(self, lambda: self.diag_progress.configure(value=pct))
            safe_after(self, lambda: self._set_diag_status(f"⏳ {msg}", COLORS["blue"]))

        try:
            results = diag.run_full_diagnostic(progress_callback=progress)
        except Exception as e:
            safe_after(self, lambda: self._set_diag_status(f"❌ 诊断失败: {e}", COLORS["red"]))
            safe_after(self, lambda: self._set_running(False))
            return

        self._latest_results = results

        def _render():
            self._clear_results()

            def _add_row(title, bg=COLORS["card"], fill="x"):
                row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
                row.pack(fill=fill, pady=4, padx=4)
                return self._card(row, title, bg=bg)

            # ---- 网络总览卡片 ----
            card0 = _add_row(tr("📋 网络状态总览"))
            overview = results.get('overview', [])
            if overview:
                for k, v in overview:
                    self._result_info(card0, f"{k}:{v}")
            else:
                self._result_fail(card0, tr("无法获取网络信息"))

            # ---- Ping 卡片 ----
            card1 = _add_row(tr("📡 Ping 连通性测试"))
            ping_results = results.get('ping', [])
            for p in ping_results:
                latency_str = f"{p['avg_ms']}ms" if p['avg_ms'] is not None else "<1ms"
                if p['ok']:
                    self._result_ok(card1, f"{p['label']} ({p['target']})",
                                    f"延迟 {latency_str} · 丢包 {p['loss']}%")
                else:
                    self._result_fail(card1, f"{p['label']} ({p['target']})",
                                      f"丢包率 {p['loss']}%")

            # ---- DNS 卡片 ----
            card2 = _add_row(tr("🔍 DNS 解析测试"))
            dns_results = results.get('dns', [])
            for d in dns_results:
                if d['ok']:
                    self._result_ok(card2, f"{d['label']} ({d['dns']})",
                                    f"解析成功 → {d['ip']}")
                else:
                    self._result_fail(card2, f"{d['label']} ({d['dns']})", tr("解析失败"))

            # ---- 结论 ----
            # 结论口径统一走 compute_health，与导出的报告保持一致
            card3 = _add_row(tr("💡 诊断结论"))
            health = compute_health(results)
            all_ping_ok = health['ping_ok'] == health['ping_total'] and health['ping_total'] > 0
            all_dns_ok = health['dns_ok'] == health['dns_total'] and health['dns_total'] > 0

            if all_ping_ok and all_dns_ok:
                self._result_ok(card3, tr("网络状态正常"), tr("所有目标连通,DNS 解析正常"))
            elif all_ping_ok and not all_dns_ok:
                self._result_fail(card3, tr("DNS 异常"), tr("Ping 正常但 DNS 解析失败,尝试清除 DNS 缓存"))
            elif all_dns_ok and not all_ping_ok:
                self._result_fail(card3, tr("连通性异常"), tr("DNS 正常但目标不可达,检查网关/防火墙/代理"))
            else:
                self._result_fail(card3, tr("网络连接异常"), tr("部分项目失败,建议使用「网络重置」标签修复"))

            self._set_running(False)
            self.diag_progress.configure(value=100)
            self._set_diag_status(tr("✅ 完整诊断完成"), COLORS["green"])

        ui_sync(self, _render)

    # ---- 健康报告 ----
    def _do_health_report(self):
        if self._running:
            return
        self._set_running(True)
        safe_after(self, self._clear_results)
        self._set_diag_status(tr("⏳ 生成健康报告..."), COLORS["teal"])
        threading.Thread(target=self._thread_health_report, daemon=True).start()

    def _health_metric_card(self, parent, icon, title, value, sub=None, color=None):
        """健康报告维度卡片（由 rc 闭包提取为方法, 便于复用与测试）。"""
        card = self._card(parent, icon + " " + title, bg=COLORS["card"])
        if color:
            vc = color
        else:
            try:
                num = float(str(value).rstrip('%'))
                vc = (COLORS["green"] if num >= 80
                      else COLORS["yellow"] if num >= 50 else COLORS["red"])
            except (ValueError, TypeError, AttributeError):
                vc = COLORS["subtext"]
        tk.Label(card, text=value, font=(FONT_FAMILY, 16, "bold"),
                 fg=vc, bg=COLORS["card"]).pack(pady=(4, 0))
        if sub:
            tk.Label(card, text=sub, font=(FONT_FAMILY, 8),
                     fg=COLORS["muted"], bg=COLORS["card"]).pack()

    def _thread_health_report(self):
        diag = NetworkDiagnostic()
        try:
            results = diag.run_full_diagnostic()
        except Exception as e:
            safe_after(self, lambda: self._set_diag_status(f"❌ 健康报告生成失败: {e}", COLORS["red"]))
            safe_after(self, lambda: self._set_running(False))
            return

        self._latest_results = results

        ping_results = results.get('ping', [])
        dns_results = results.get('dns', [])
        overview = results.get('overview', [])

        # 评分口径统一走 compute_health（与导出的报告完全一致）
        health = compute_health(results)
        total = health['total']
        grade = health['grade']
        ping_ok = health['ping_ok']
        dns_ok = health['dns_ok']
        cfg_score = health['cfg_score']
        avg_latency = health['avg_latency']
        avg_loss = health['avg_loss']

        grade_color = _grade_color(grade)

        def _render():
            self._clear_results()

            # 顶部:总分 + 等级
            top = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            top.pack(fill="x", pady=4, padx=4)
            score_card = tk.Frame(top, bg=COLORS["card"])
            score_card.pack(side="left", fill="both", expand=True, padx=(0, 4))
            tk.Label(score_card, text=tr("网络健康评分"), font=(FONT_FAMILY, 10),
                     fg=COLORS["text"], bg=COLORS["card"]).pack(pady=(8, 0))
            tk.Label(score_card, text=f"{total}", font=(FONT_FAMILY, 36, "bold"),
                     fg=grade_color, bg=COLORS["card"]).pack()
            tk.Label(score_card, text=f"{grade}", font=(FONT_FAMILY, 11, "bold"),
                     fg=grade_color, bg=COLORS["card"]).pack(pady=(0, 8))

            # 等级说明
            advice_card = tk.Frame(top, bg=COLORS["card"])
            advice_card.pack(side="right", fill="both", expand=True, padx=(4, 0))
            tk.Label(advice_card, text=tr("💡 健康建议"), font=(FONT_FAMILY, 10, "bold"),
                     fg=COLORS["text"], bg=COLORS["card"]).pack(anchor="w", padx=10, pady=(8, 2))
            advice_text = health['advice']
            tk.Label(advice_card, text=advice_text, font=(FONT_FAMILY, 9),
                     fg=COLORS["subtext"], bg=COLORS["card"], wraplength=200,
                     justify="left", anchor="w").pack(anchor="w", padx=10, pady=(0, 8))

            # 维度卡片行
            row1 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            row1.pack(fill="x", pady=4, padx=4)
            conn_pct = f"{round(ping_ok / max(len(ping_results), 1) * 100)}%"
            dns_pct = f"{round(dns_ok / max(len(dns_results), 1) * 100)}%"
            cfg_pct = f"{round(cfg_score / 30 * 100)}%"
            self._health_metric_card(row1, "📡", tr("连通性"), conn_pct, f"{ping_ok}/{len(ping_results)} 目标可达")
            self._health_metric_card(row1, "🔍", tr("DNS可用"), dns_pct, f"{dns_ok}/{len(dns_results)} DNS正常")
            self._health_metric_card(row1, "🔧", tr("配置完整"), cfg_pct, tr("IP/网关/DNS状态"))

            # 性能行
            row2 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            row2.pack(fill="x", pady=4, padx=4)
            self._health_metric_card(row2, "⚡", tr("平均延迟"), f"{avg_latency}ms", tr("5个目标平均"),
               COLORS["green"] if avg_latency < 100
               else COLORS["yellow"] if avg_latency < 300 else COLORS["red"])
            self._health_metric_card(row2, "📉", tr("平均丢包"), f"{avg_loss}%", tr("5个目标平均"),
               COLORS["green"] if avg_loss == 0
               else COLORS["yellow"] if avg_loss < 20 else COLORS["red"])
            dns_svr = next((v for k, v in overview if 'DNS' in k), "-")
            self._health_metric_card(row2, "🌐", tr("当前DNS"), dns_svr[:20] if len(dns_svr) > 20 else dns_svr, tr("当前使用"))

            self._set_running(False)
            self.diag_progress.configure(value=100)
            self._set_diag_status(
                f"📊 健康报告: {total}分 {grade} | {advice_text[:20]}...", grade_color)

        ui_sync(self, _render)

    # ---- 导出诊断报告 (F1) ----
    def _do_export(self):
        """点击「导出报告」。没有数据时先跑一次完整诊断。"""
        if self._running:
            return
        if not self._latest_results:
            if not messagebox.askyesno(
                    tr("导出诊断报告"),
                    tr("还没有诊断数据。\n\n是否立即运行一次完整诊断，完成后再导出？")):
                return
            self._set_running(True)
            self.diag_progress.configure(mode="determinate")
            self.diag_progress["value"] = 0
            self._set_diag_status(tr("⏳ 诊断中（导出前需先采集数据）..."), COLORS["mauve"])
            threading.Thread(target=self._thread_export_after_diag, daemon=True).start()
            return
        self._ask_save_path()

    def _thread_export_after_diag(self):
        diag = NetworkDiagnostic()

        def progress(pct, msg):
            safe_after(self, lambda: self.diag_progress.configure(value=pct))
            safe_after(self, lambda: self._set_diag_status(f"⏳ {msg}", COLORS["blue"]))

        try:
            self._latest_results = diag.run_full_diagnostic(progress_callback=progress)
        except Exception as e:
            safe_after(self, lambda: self._set_diag_status(f"❌ 诊断失败: {e}", COLORS["red"]))
            safe_after(self, lambda: self._set_running(False))
            return

        # 保存对话框必须在主线程弹出
        ui_sync(self, lambda: (self._set_running(False), self._ask_save_path()))

    def _ask_save_path(self):
        """弹出另存为对话框并写出报告。必须在主线程调用。"""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            parent=self,
            title=tr("导出诊断报告"),
            defaultextension=".html",
            initialfile=f"网络诊断报告_{stamp}.html",
            filetypes=[(tr("HTML 报告（推荐，可直接打印）"), "*.html"),
                       (tr("Markdown 报告"), "*.md"),
                       (tr("纯文本报告"), "*.txt")],
        )
        if not path:
            self._set_diag_status(tr("已取消导出"), COLORS["muted"])
            return

        ext = os.path.splitext(path)[1].lower().lstrip(".") or "html"
        try:
            content, enc = render_report(self._latest_results, ext)
            with open(path, "w", encoding=enc) as f:
                f.write(content)
        except Exception as e:
            messagebox.showerror(tr("导出失败"), f"写入报告时出错：\n{e}", parent=self)
            self._set_diag_status(f"❌ 导出失败: {e}", COLORS["red"])
            return

        self._set_diag_status(f"✅ 报告已导出: {path}", COLORS["green"])
        if messagebox.askyesno(tr("导出成功"), f"报告已保存到：\n\n{path}\n\n是否立即打开？", parent=self):
            if not open_path(path):
                messagebox.showinfo(tr("提示"), f"已保存到：\n{path}", parent=self)

    # ---- hosts 检查与清理 (F4) ----
    def _do_hosts(self):
        if self._running:
            return
        self._set_running(True)
        self._clear_results()
        self._set_diag_status(tr("⏳ 检查 hosts 中..."), COLORS["green"])
        threading.Thread(target=self._thread_hosts, daemon=True).start()

    def _thread_hosts(self):
        tool = HostsTool()
        try:
            entries = tool.read_entries()
            path = tool.path
            writable = os.access(path, os.W_OK)
        except Exception as e:
            safe_after(self, lambda: self._set_diag_status(f"❌ hosts 检查失败: {e}", COLORS["red"]))
            safe_after(self, lambda: self._set_running(False))
            return
        ui_sync(self, lambda: self._render_hosts(entries, path, writable, tool))

    def _render_hosts(self, entries, path, writable, tool):
        self._clear_results()
        head = tk.Label(self.results_inner,
                        text=f"📄 hosts 文件: {path}",
                        font=(FONT_FAMILY, 10, "bold"), fg=COLORS["text"],
                        bg=COLORS["bg2"], anchor="w")
        head.pack(fill="x", padx=10, pady=(8, 2))

        if not entries:
            tk.Label(self.results_inner, text=tr("✅ hosts 没有自定义映射条目(全部为注释/空行)"),
                     font=(FONT_FAMILY, 10), fg=COLORS["green"],
                     bg=COLORS["bg2"], anchor="w").pack(anchor="w", padx=20, pady=8)
        else:
            suspicious = [e for e in entries if e["suspicious"]]
            summary = tk.Label(
                self.results_inner,
                text=f"共 {len(entries)} 条映射, 其中 {len(suspicious)} 条可疑",
                font=(FONT_FAMILY, 9), fg=COLORS["yellow"] if suspicious else COLORS["green"],
                bg=COLORS["bg2"], anchor="w")
            summary.pack(fill="x", padx=10)
            for e in entries:
                if e["suspicious"]:
                    self._result_fail(self.results_inner,
                                      f"{e['host']}  →  {e['ip']}  (第 {e['line']} 行)",
                                      sub=e["reason"])
                else:
                    self._result_ok(self.results_inner,
                                    f"{e['host']}  →  {e['ip']}  (第 {e['line']} 行)",
                                    sub=e["reason"] or tr("常规映射"))

        # 操作按钮行
        ops = tk.Frame(self.results_inner, bg=COLORS["bg2"])
        ops.pack(fill="x", padx=10, pady=10)
        if not writable:
            tk.Label(ops, text=tr("⚠ hosts 当前不可写(注释/还原需要以管理员身份运行)"),
                     font=(FONT_FAMILY, 9), fg=COLORS["red"], bg=COLORS["bg2"]).pack(anchor="w")
        styled_btn(ops, tr("🚿 注释可疑条目"), lambda: self._hosts_comment_suspicious(tool),
                   COLORS["orange"], font_size=10,
                   tip=tr("备份后把所有可疑条目前加 # 注释; 原始内容保留, 可随时还原。")).pack(side="left", padx=(0, 8))
        styled_btn(ops, tr("♻️ 从备份还原"), lambda: self._hosts_restore(tool),
                   COLORS["sky"], font_size=10,
                   tip=tr("用最近一次自动备份覆盖还原 hosts(注释/replace 前都会自动备份)。")).pack(side="left")

        self._set_running(False)
        self.diag_progress.configure(value=100)
        self._set_diag_status(tr("🧹 hosts 检查完成"), COLORS["green"])

    def _hosts_comment_suspicious(self, tool):
        if not messagebox.askyesno(
                tr("注释 hosts 可疑条目"),
                tr("将先自动备份 hosts, 再把所有可疑条目前加 # 注释。\n确定继续?"),
                parent=self):
            return
        backup = tool.backup()
        ok, changed, err = tool.comment_suspicious()
        if not ok:
            messagebox.showerror(tr("注释失败"), err, parent=self)
            return
        if changed == 0:
            messagebox.showinfo(tr("无需处理"), tr("没有发现可疑条目。"), parent=self)
        else:
            messagebox.showinfo(
                tr("已注释"),
                f"已注释 {changed} 条可疑映射。\n备份: {backup}\n\n"
                f"如果某些网站因此打不开, 可用「从备份还原」恢复。", parent=self)
        self._do_hosts()

    def _hosts_restore(self, tool):
        backups = tool.list_backups()
        if not backups:
            messagebox.showinfo(tr("没有备份"), tr("尚未创建过 hosts 备份。"), parent=self)
            return
        path, _mt = backups[0]
        if not messagebox.askyesno(
                tr("还原 hosts"),
                f"将用最近一次备份覆盖当前 hosts:\n{path}\n\n确定继续?",
                parent=self):
            return
        ok, err = tool.restore(path)
        if not ok:
            messagebox.showerror(tr("还原失败"), err, parent=self)
            return
        messagebox.showinfo(tr("已还原"), tr("hosts 已从备份还原。"), parent=self)
        self._do_hosts()


class ProxyPanel(ResultPanel):
    """第三个标签页:代理诊断与修复"""

    _decode_output = staticmethod(decode_output)

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=COLORS["surface"], pady=12)
        header.pack(fill="x")
        tk.Label(header, text=tr("🛡️ 代理诊断与修复"), font=(FONT_FAMILY, 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text=tr("检测系统代理 / Clash 端口与 DNS · 一键修复外网连不上"),
                 font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        ctrl = tk.Frame(self, bg=self["bg"], pady=10, padx=20)
        ctrl.pack(fill="x")
        self.btn_diag = styled_btn(ctrl, tr("🔍 诊断代理"), self._do_diagnose,
                                   COLORS["green"], font_size=12, bold=True,
                                   tip="检查系统代理指向的端口还有没有服务在听、本机是否在跑\n"
                                       "Clash/mihomo、其配置里 dns.enable 有没有被关掉。\n"
                                       "只读检测，不会改动任何设置。")
        self.btn_diag.pack(side="left", padx=(0, 8))
        self.btn_repair = styled_btn(ctrl, tr("🔧 一键修复"), self._do_repair,
                                     COLORS["orange"], font_size=12, bold=True,
                                     tip="自动处理诊断出的问题：关闭指向死端口的系统代理、\n"
                                         "打开 Clash 配置的 dns.enable(改之前会先备份原文件)。\n"
                                         "修复后需重开浏览器/相关程序才生效。")
        self.btn_repair.pack(side="left", padx=4)

        self.proxy_progress = ttk.Progressbar(self, mode="indeterminate")
        self.proxy_progress.pack(fill="x", padx=20, pady=(0, 5))
        self.proxy_status = tk.Label(self, text=tr("就绪"), font=(FONT_FAMILY, 9),
                                     fg=COLORS["muted"], bg=self["bg"], anchor="w")
        self.proxy_status.pack(fill="x", padx=20)

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("HP.Horizontal.TProgressbar",
                        troughcolor=COLORS["surface"], background=COLORS["orange"], thickness=6)

        # 结果区域(Canvas + Scrollbar) —— 骨架由 ResultPanel 提供
        self._build_results(self)

        self._show_hint()

    def _show_hint(self):
        for w in self.results_inner.winfo_children():
            w.destroy()
        tk.Label(self.results_inner,
                 text=tr("点击「诊断代理」检测以下问题:\n\n"
                      "🔌 系统代理是否指向已宕机的端口(外网会全部失败)\n"
                      "🛡️ 是否发现正在运行的 Clash / mihomo 代理核心\n"
                      "🌐 Clash 的 dns.enable 是否被关掉(导致域名解析超时)\n\n"
                      "发现问题后点「一键修复」自动处理。"),
                 font=(FONT_FAMILY, 11), fg=COLORS["muted"], bg=COLORS["bg2"],
                 justify="left", padx=20, pady=30).pack(fill="both", expand=True)

    def _set_status(self, msg, color=None):
        self.proxy_status.config(text=msg, fg=color or COLORS["muted"])

    def _set_running(self, running):
        self._running = running
        state = "disabled" if running else "normal"
        self.btn_diag.config(state=state)
        self.btn_repair.config(state=state)
        if running:
            self.proxy_progress.start(8)
        else:
            self.proxy_progress.stop()

    # ---- 诊断 ----
    def _do_diagnose(self):
        if self._running:
            return
        self._set_running(True)
        self._clear_results()
        self._set_status(tr("⏳ 诊断代理中..."), COLORS["green"])
        threading.Thread(target=self._thread_diagnose, daemon=True).start()

    def _thread_diagnose(self):
        res = ProxyRepairTool().diagnose()

        def _render():
            self._clear_results()

            def _row():
                r = tk.Frame(self.results_inner, bg=COLORS["bg2"])
                r.pack(fill="x", pady=4, padx=4)
                return r

            card = self._card(_row(), tr("🔌 系统代理"), bg=COLORS["card"])
            if res['proxy_enabled']:
                self._result_info(card, f"已启用,地址: {res['proxy_server'] or '(空)'}")
            else:
                self._result_info(card, tr("未启用系统代理"))
            if res['proxy_ports']:
                if res['proxy_alive']:
                    self._result_ok(card, tr("代理端口可连通"), tr("外网出口正常"))
                else:
                    self._result_fail(card, tr("代理端口无服务监听"), tr("外网会全部失败!"))

            card2 = self._card(_row(), tr("🛡️ 代理核心"), bg=COLORS["card"])
            core = res['clash_core']
            if core:
                pp = res.get('clash_proxy_port')
                if pp:
                    self._result_ok(card2, f"发现 {core['process']} (代理端口 {pp})")
                else:
                    self._result_ok(card2, f"发现 {core['process']} 在端口 {core['port']} 运行")
            else:
                self._result_info(card2, tr("未发现 Clash/mihomo 核心"))

            card3 = self._card(_row(), "🌐 Clash DNS", bg=COLORS["card"])
            dns = res['clash_dns']
            if dns is True:
                self._result_ok(card3, "dns.enable = true", tr("DNS 模块正常"))
            elif dns is False:
                self._result_fail(card3, "dns.enable = false", tr("fake-ip 模式下会导致解析超时!"))
            else:
                self._result_info(card3, tr("未找到 Clash 配置,无法检测"))

            card4 = self._card(_row(), tr("💡 诊断结论"), bg=COLORS["card"])
            if res['issues']:
                for issue in res['issues']:
                    self._result_fail(card4, issue)
                self._result_info(card4, tr("建议点击「一键修复」自动处理"))
                self._set_status(tr("⚠ 发现代理问题,可一键修复"), COLORS["yellow"])
            else:
                self._result_ok(card4, tr("未发现明显代理问题"))
                self._set_status(tr("✅ 代理诊断正常"), COLORS["green"])

            self._set_running(False)

        ui_sync(self, _render)

    # ---- 修复 ----
    def _do_repair(self):
        if self._running:
            return
        self._set_running(True)
        self._clear_results()
        self._set_status(tr("⏳ 正在修复..."), COLORS["orange"])
        threading.Thread(target=self._thread_repair, daemon=True).start()

    def _thread_repair(self):
        tool = ProxyRepairTool(log_callback=self._safe_log)
        ok, actions = tool.repair()

        def _render():
            self._clear_results()
            row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            row.pack(fill="x", pady=4, padx=4)
            card = self._card(row, tr("🔧 修复结果"), bg=COLORS["card"])
            if not actions:
                self._result_info(card, tr("无需修复,或请先点「诊断代理」"))
            for a in actions:
                self._result_info(card, "• " + a)
            if ok:
                self._result_ok(card, tr("修复完成!"), tr("建议重开浏览器/相关程序使代理生效"))
                self._set_status(tr("✅ 代理修复完成"), COLORS["green"])
            else:
                self._result_fail(card, tr("部分修复失败"), tr("请查看上方信息/手动处理"))
                self._set_status(tr("⚠ 修复未完全成功"), COLORS["yellow"])
            self._set_running(False)

        ui_sync(self, _render)

    def _safe_log(self, msg, color=None):
        safe_after(self, lambda m=msg: self._set_status(tr("修复中: ") + m[:60], COLORS["orange"]))

class PortsPanel(ResultPanel):
    """第四个标签页: 监听端口查看 (F5)。

    列出本机 LISTENING 端口与对应进程, 支持按端口/PID/进程名过滤;
    代理端口(Clash/V2Ray 常用口)高亮, Windows 上可结束进程。
    """

    _decode_output = staticmethod(decode_output)
    PROXY_PORTS = {7890, 7891, 7897, 1080, 10808, 10809, 9090, 17650}

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        self._tool = PortTool()
        self._all_items = []
        self.port_tree = None
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=COLORS["surface"], pady=12)
        header.pack(fill="x")
        tk.Label(header, text=tr("🔌 监听端口查看"), font=(FONT_FAMILY, 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text=tr("查找端口占用 · 定位代理端口是否真的在监听"),
                 font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        ctrl = tk.Frame(self, bg=self["bg"], pady=10, padx=20)
        ctrl.pack(fill="x")
        self.btn_refresh = styled_btn(ctrl, tr("🔄 刷新"), self._do_refresh,
                                      COLORS["green"], font_size=11,
                                      tip=tr("重新扫描本机所有 LISTENING 端口及对应进程。"))
        self.btn_refresh.pack(side="left", padx=(0, 8))
        self.btn_kill = styled_btn(ctrl, tr("⛔ 结束进程"), self._do_kill,
                                   COLORS["red"], font_size=11,
                                   tip="结束列表中选中端口对应的进程(Windows: taskkill /F)。\n"
                                       "误杀系统进程会导致不稳定, 请确认后再操作。")
        self.btn_kill.pack(side="left", padx=4)

        tk.Label(ctrl, text=tr("过滤:"), font=(FONT_FAMILY, 9), fg=COLORS["subtext"],
                 bg=self["bg"]).pack(side="left", padx=(16, 4))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
        tk.Entry(ctrl, textvariable=self.filter_var, font=(FONT_MONO, 10),
                 bg=COLORS["surface"], fg=COLORS["text"], insertbackground=COLORS["text"],
                 relief="flat", bd=0, width=16).pack(side="left")

        self.port_status = tk.Label(self, text=tr("就绪"), font=(FONT_FAMILY, 9),
                                    fg=COLORS["muted"], bg=self["bg"], anchor="w")
        self.port_status.pack(fill="x", padx=20)

        # 结果区域(Canvas + Scrollbar) —— 骨架由 ResultPanel 提供
        self._build_results(self)
        self._show_hint()

    def _show_hint(self):
        for w in self.results_inner.winfo_children():
            w.destroy()
        tk.Label(self.results_inner,
                 text=tr("点击「刷新」列出本机所有监听中的端口\n\n"
                      "🔌 代理端口(7890/7897/10809 等)会高亮显示\n"
                      "🔍 支持按端口号 / PID / 进程名过滤\n"
                      "⛔ 选中一行后可用「结束进程」强杀对应进程\n\n"
                      "典型用途: 代理软件端口没人监听时, 在这里一眼看出端口归属。"),
                 font=(FONT_FAMILY, 11), fg=COLORS["muted"], bg=COLORS["bg2"],
                 justify="left", padx=20, pady=30).pack(fill="both", expand=True)

    def _set_status(self, msg, color=None):
        self.port_status.config(text=msg, fg=color or COLORS["muted"])

    def _set_running(self, running):
        self._running = running
        state = "disabled" if running else "normal"
        for btn in (self.btn_refresh, self.btn_kill):
            btn.config(state=state)

    def _apply_filter(self):
        if self._all_items:
            self._render_ports()

    def _do_refresh(self):
        if self._running:
            return
        self._set_running(True)
        self._clear_results()
        self._set_status(tr("⏳ 扫描监听端口..."), COLORS["green"])
        threading.Thread(target=self._thread_refresh, daemon=True).start()

    def _thread_refresh(self):
        try:
            items = self._tool.list_listening()
        except Exception as e:
            safe_after(self, lambda: self._set_status(f"❌ 扫描失败: {e}", COLORS["red"]))
            safe_after(self, lambda: self._set_running(False))
            return
        self._all_items = items
        ui_sync(self, self._render_ports)

    def _render_ports(self):
        self._clear_results()
        kw = (self.filter_var.get() or "").strip().lower()
        items = self._all_items
        if kw:
            items = [it for it in items
                     if kw in str(it["port"])
                     or kw in str(it.get("pid") or "")
                     or kw in str(it.get("process") or "").lower()]

        cols = ("port", "proto", "addr", "pid", "process", "state")
        config_treeview_style(self)
        tree = ttk.Treeview(self.results_inner, columns=cols, show="headings",
                            height=20, style="nice.Treeview")
        for cid, title, width in (("port", tr("端口"), 80), ("proto", tr("协议"), 70),
                                  ("addr", tr("监听地址"), 170), ("pid", "PID", 80),
                                  ("process", tr("进程"), 180), ("state", tr("状态"), 100)):
            tree.heading(cid, text=title)
            tree.column(cid, width=width, anchor="w")
        tree.tag_configure("proxy", background=COLORS["surface2"])
        for it in items:
            values = (it["port"], it["proto"], it["addr"],
                      it["pid"] if it["pid"] is not None else "-",
                      it.get("process") or "-", it["state"])
            tags = ("proxy") if it["port"] in self.PROXY_PORTS else ()
            # iid 不指定: 同一端口可能有 0.0.0.0/[::] 多条, pid 也可能为 None
            tree.insert("", "end", values=values, tags=tags)
        scrollbar = theme_scrollbar(self.results_inner, tree.yview, orient="vertical")
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.port_tree = tree

        self._set_running(False)
        self._set_status(f"✅ {len(items)} 个监听端口"
                         + (f"(已过滤, 共 {len(self._all_items)} 个)" if kw else ""))

    def _do_kill(self):
        tree = self.port_tree
        if not tree or not tree.selection():
            messagebox.showinfo(tr("结束进程"), tr("请先在列表中选中一行。"), parent=self)
            return
        iid = tree.selection()[0]
        values = tree.item(iid, "values")
        port, _proto, _addr, pid, process = values[:5]
        if pid in (None, "", "-"):
            messagebox.showwarning(tr("结束进程"), tr("该条目的 PID 未知, 无法结束。"), parent=self)
            return
        if not messagebox.askyesno(
                tr("结束进程"),
                f"确定要强制结束进程吗?\n\n端口: {port}\nPID: {pid}\n进程: {process}\n\n"
                f"误杀系统进程可能导致不稳定。",
                parent=self):
            return
        ok, msg = self._tool.kill_process(pid)
        if ok:
            messagebox.showinfo(tr("结束进程"), msg, parent=self)
        else:
            messagebox.showerror(tr("结束进程"), msg, parent=self)
        self._do_refresh()


class MonitorPanel(ResultPanel):
    """第五个标签页: 定时网络监控 + 掉线记录 (F7)。

    周期性 Ping 网关与外网基准(默认每 5 分钟), 判定掉线/恢复,
    记录断线事件的起止时间与持续时长并落盘 JSON, 重启后仍可回看。
    监控跑在 daemon 线程, 回调只带数据, UI 刷新全部经 ui_sync
    投递回主线程(遵守线程安全铁律)。
    """

    _decode_output = staticmethod(decode_output)

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        # 只加载历史记录, 不启动线程; 点"开始监控"时才真正跑起来
        self._monitor = NetworkMonitor()
        self._build_ui()

    def destroy(self):
        """窗口销毁(含换主题整树重建)时停掉巡检线程。

        否则旧面板没了但 daemon 线程还在空转, 重建后的新面板再点"开始监控"
        就会出现两个线程同时 Ping; safe_after 只会把它的回投静默丢掉。
        """
        try:
            if self._monitor is not None and self._monitor.is_running():
                self._monitor.stop()
        except Exception:
            pass
        super().destroy()

    def _build_ui(self):
        header = tk.Frame(self, bg=COLORS["surface"], pady=12)
        header.pack(fill="x")
        tk.Label(header, text=tr("📡 网络监控"), font=(FONT_FAMILY, 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text=tr("定时自动体检 · 掉线自动记时 · 重启后可回看"),
                 font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        ctrl = tk.Frame(self, bg=self["bg"], pady=10, padx=20)
        ctrl.pack(fill="x")
        tk.Label(ctrl, text=tr("巡检间隔:"), font=(FONT_FAMILY, 9), fg=COLORS["subtext"],
                 bg=self["bg"]).pack(side="left")
        self.interval_var = tk.StringVar(value="5")
        self.interval_spin = tk.Spinbox(ctrl, from_=1, to=1440,
                                       textvariable=self.interval_var, width=5,
                                       font=(FONT_MONO, 10), bg=COLORS["surface"],
                                       fg=COLORS["text"], buttonbackground=COLORS["surface2"],
                                       relief="flat", bd=0)
        self.interval_spin.pack(side="left", padx=4)
        tk.Label(ctrl, text=tr("分钟"), font=(FONT_FAMILY, 9), fg=COLORS["subtext"],
                 bg=self["bg"]).pack(side="left")

        self.btn_start = styled_btn(ctrl, tr("▶ 开始监控"), self._do_start,
                                   COLORS["green"], font_size=10,
                                   tip="按上方间隔定时 Ping 网关与 223.5.5.5。\n"
                                       "持续不通记为掉线并落盘保存，恢复后自动给出时长。\n"
                                       "关掉程序记录也不会丢。")
        self.btn_start.pack(side="left", padx=(16, 4))
        self.btn_stop = styled_btn(ctrl, tr("⏹ 停止"), self._do_stop,
                                  COLORS["red"], font_size=10, state="disabled",
                                  tip="停止定时巡检。\n"
                                      "已记录的掉线事件仍会保留，可随时回看。")
        self.btn_stop.pack(side="left", padx=4)
        self.btn_clear = styled_btn(ctrl, tr("🗑 清空记录"), self._do_clear,
                                   COLORS["surface2"], COLORS["text"], font_size=10,
                                   tip="删除全部掉线记录(需二次确认)。\n"
                                       "只清记录，不影响监控的运行状态。")
        self.btn_clear.pack(side="left", padx=4)

        self.monitor_status = tk.Label(self, text=tr("未启动"), font=(FONT_FAMILY, 10),
                                      fg=COLORS["muted"], bg=self["bg"], anchor="w")
        self.monitor_status.pack(fill="x", padx=20)

        # 结果区: 汇总卡片 + 掉线事件表
        self._build_results(self)
        self._refresh_events()

        # 窗口关闭时停掉后台线程
        self.bind("<Destroy>", lambda e: self._teardown())

    def _show_hint(self):
        self._refresh_events()

    # ---------- 监控启停 ----------
    def _read_interval(self):
        try:
            minutes = int(str(self.interval_var.get()).strip())
        except (ValueError, AttributeError, tk.TclError):
            minutes = 5
        return max(1, min(1440, minutes))

    def _do_start(self):
        if self._monitor is not None and self._monitor.is_running():
            return
        monitor = NetworkMonitor(interval_seconds=self._read_interval() * 60,
                                 on_tick=self._on_tick, on_event=self._on_event)
        self._monitor = monitor
        monitor.start()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.interval_spin.config(state="disabled")
        targets = " / ".join(monitor.targets) or "-"
        self.monitor_status.config(
            text=f"⏱ 监控中 · 每 {self._read_interval()} 分钟 · 目标: {targets}",
            fg=COLORS["green"])
        self._refresh_events()

    def _do_stop(self):
        if self._monitor is not None:
            self._monitor.stop()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.interval_spin.config(state="normal")
        self.monitor_status.config(text=tr("⏸ 已停止"), fg=COLORS["muted"])
        self._refresh_events()

    def _do_clear(self):
        events = list(getattr(self._monitor, "events", []))
        if not events:
            messagebox.showinfo(tr("清空记录"), tr("当前没有掉线记录。"), parent=self)
            return
        if not messagebox.askyesno(
                tr("清空记录"),
                f"确定要删除全部 {len(events)} 条掉线记录吗？\n"
                f"此操作不可恢复。", parent=self):
            return
        self._monitor.clear_events()
        self._refresh_events()
        self.monitor_status.config(text=tr("🗑 记录已清空"), fg=COLORS["muted"])

    def _teardown(self):
        monitor = self._monitor
        if monitor is not None:
            monitor.stop()

    # ---------- 监控线程回调(只带数据) ----------
    def _on_tick(self, status):
        ui_sync(self, lambda: self._render_tick(status))

    def _render_tick(self, status):
        if not status:
            return
        online = status.get("online")
        results = status.get("results") or {}
        ms = [r.get("avg_ms") for r in results.values()
              if r.get("ok") and r.get("avg_ms") is not None]
        detail = f"平均 {int(sum(ms) / len(ms))}ms" if ms else tr("无响应")
        dot = "🟢" if online else "🔴"
        state = tr("在线") if online else tr("掉线")
        self.monitor_status.config(
            text=f"{dot} {state} · {detail} · 检查于 {status.get('time', '')}",
            fg=COLORS["green"] if online else COLORS["red"])

    def _on_event(self, event):
        ui_sync(self, self._refresh_events)

    # ---------- 结果渲染 ----------
    def _refresh_events(self):
        if not self.winfo_exists():
            return
        self._clear_results()
        events = list(getattr(self._monitor, "events", []))
        summary = (self._monitor.summarize() if self._monitor is not None
                   else {"count": 0, "total_seconds": 0, "latest": None,
                         "ongoing": False})

        sum_card = self._card(self.results_inner, tr("📊 汇总"))
        self._result_info(sum_card,
                          tr_f('共 {n} 次掉线 · 合计 {d}',
                                                         n=summary["count"],
                                                         d=NetworkMonitor.format_duration(
                                                             summary["total_seconds"])))
        if summary.get("latest"):
            self._result_info(sum_card,
                              tr("最近: ") + NetworkMonitor.format_event(summary["latest"]))
        if summary.get("ongoing"):
            self._result_info(sum_card, tr("⏳ 当前疑似断网，正在计时…"))

        ev_card = self._card(self.results_inner, tr("🕘 掉线记录"))
        if not events:
            self._result_info(ev_card, tr("暂无掉线记录"))
            return
        cols = ("start", "end", "duration")
        config_treeview_style(self)
        tree = ttk.Treeview(ev_card, columns=cols, show="headings",
                            height=8, style="nice.Treeview")
        for cid, title, width in (("start", tr("开始"), 170),
                                  ("end", tr("恢复"), 170),
                                  ("duration", tr("持续"), 120)):
            tree.heading(cid, text=title)
            tree.column(cid, width=width, anchor="w")
        for ev in events[-50:]:
            tree.insert("", "end", values=(
                ev.get("start", ""), ev.get("end", ""),
                NetworkMonitor.format_duration(ev.get("duration_seconds", 0))))
        scrollbar = theme_scrollbar(ev_card, tree.yview, orient="vertical")
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")


class SpeedPanel(ResultPanel):
    """第六个标签页: 网速测试 (F6)。

    从公开测速端点流式下载固定大小数据, 计算下行带宽; 纯标准库, 无第三方依赖。
    测速放 daemon 线程, 进度/结果经 ui_sync 回主线程(遵守线程安全铁律)。
    """

    _decode_output = staticmethod(decode_output)

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        self._stop = threading.Event()
        self._tool = SpeedTester(stop_event=self._stop)
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=COLORS["surface"], pady=12)
        header.pack(fill="x")
        tk.Label(header, text=tr("⚡ 网速测试"), font=(FONT_FAMILY, 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text=tr("下载带宽实测 · 数据仅来自公开测速端点 · 纯标准库无依赖"),
                 font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        ctrl = tk.Frame(self, bg=self["bg"], pady=10, padx=20)
        ctrl.pack(fill="x")
        self.btn_start = styled_btn(ctrl, tr("🚀 开始测速"), self._do_start,
                                   COLORS["green"], font_size=10,
                                   tip="从公开测速端点下载固定大小数据测量下行带宽。\n"
                                       "最多 12 秒 / 64MB，先到先停，不会挂死。")
        self.btn_start.pack(side="left", padx=(0, 8))
        self.btn_stop = styled_btn(ctrl, tr("⏹ 停止"), self._do_stop,
                                  COLORS["red"], font_size=10, state="disabled",
                                  tip="提前结束测速。\n"
                                      "已下载的流量仍然有效，会按实测窗口估算带宽。")
        self.btn_stop.pack(side="left", padx=4)

        self.speed_status = tk.Label(self, text=tr("就绪"), font=(FONT_FAMILY, 10),
                                     fg=COLORS["muted"], bg=self["bg"], anchor="w")
        self.speed_status.pack(fill="x", padx=20)

        self.progress = ttk.Progressbar(self, mode="indeterminate",
                                        style="green.Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=20, pady=6)

        self.live_label = tk.Label(self, text="", font=(FONT_FAMILY, 10),
                                   fg=COLORS["subtext"], bg=self["bg"], anchor="w")
        self.live_label.pack(fill="x", padx=20)

        self._build_results(self)
        self._show_hint()

    def _show_hint(self):
        self._clear_results()
        card = self._card(self.results_inner, tr("⚡ 测速说明"))
        self._result_info(card, tr("Ping 只能看延迟；这里测真实下行带宽。"))
        self._result_info(card, tr("端点: Cloudflare / CacheFly / OVH 公开测速文件，按序自动试。"))
        self._result_info(card, tr("结果受服务端/共享网络影响，多测几次取般而论。"))

    def _set_status(self, msg, color=None):
        self.speed_status.config(text=msg, fg=color or COLORS["muted"])

    def _set_running(self, running):
        self._running = running
        state = "disabled" if running else "normal"
        self.btn_start.config(state=state)
        self.btn_stop.config(state="normal" if running else "disabled")

    # ---------- 测速流程 ----------
    def _do_start(self):
        if self._running:
            return
        self._stop.clear()
        self._tool = SpeedTester(stop_event=self._stop)
        self._set_running(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start(8)
        self.live_label.config(text="")
        self._set_status(tr("⏳ 测速中..."), COLORS["blue"])
        self._clear_results()
        threading.Thread(target=self._thread_test, daemon=True).start()

    def _do_stop(self):
        self._stop.set()

    def _thread_test(self):
        def progress(total, elapsed):
            # worker 线程: 节流后只把数据交给主线程渲染
            now = time.perf_counter()
            if now - getattr(self, "_last_emit", 0.0) < 0.25:
                return
            self._last_emit = now
            ui_sync(self, lambda: self._render_live(total, elapsed))

        result = self._tool.test(progress_callback=progress)
        ui_sync(self, lambda: self._render_result(result))

    def _render_live(self, total, elapsed):
        mb = total / 1048576
        mbps = total * 8 / (elapsed * 1_000_000) if elapsed > 0.2 else 0
        self.live_label.config(
            text=f"已下载 {mb:.1f} MB · 当前 {mbps:.0f} Mbps")

    def _render_result(self, r):
        self._clear_results()
        self._set_running(False)
        self.progress.stop()
        self.progress.configure(mode="determinate")

        if not r.get("ok"):
            card = self._card(self.results_inner, tr("❌ 测速失败"))
            self._result_fail(card, tr("无法完成测速"),
                              f"原因: {r.get('error', '')}")
            self._result_info(card, tr("可检查网络连接/代理设置后重试。"))
            self._set_status(f"❌ 测速失败: {r.get('error', '')}", COLORS["red"])
            self.live_label.config(text="")
            return

        big = self._card(self.results_inner, tr("⬇️ 下行带宽"))
        tk.Label(big, text=f"{r['mbps']}", font=(FONT_FAMILY, 30, "bold"),
                 fg=COLORS["green"], bg=COLORS["surface"]).pack(side="left", padx=10)
        tk.Label(big, text="Mbps", font=(FONT_FAMILY, 12),
                 fg=COLORS["subtext"], bg=COLORS["surface"]).pack(side="left")

        detail = self._card(self.results_inner, tr("📊 详情"))
        lat = f"{r['latency_ms']}ms" if r.get("latency_ms") is not None else "-"
        self._result_info(detail, f"首包延迟: {lat}")
        self._result_info(detail, f"下载流量: {r['downloaded_mb']} MB")
        self._result_info(detail, f"耗时: {r['seconds']} 秒")
        self._result_info(detail, f"端点: {r.get('endpoint', '-')}")
        if r.get("stopped"):
            self._result_info(detail, tr("已提前停止(按已下载流量估算)"))

        self._set_status(tr("✅ 测速完成"), COLORS["green"])
        self.live_label.config(text="")


class WifiPanel(ResultPanel):
    """第七个标签页: WiFi 信息管理 (F8)。

    netsh wlan 列出本机已保存 WiFi 与密码; 读取密码需要管理员权限, 界面有明确提示。
    任务放 daemon 线程, 结果经 ui_sync 回主线程(遵守线程安全铁律)。
    """

    _decode_output = staticmethod(decode_output)

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        self._tool = WifiTool()
        self._items = []
        self.wifi_tree = None
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=COLORS["surface"], pady=12)
        header.pack(fill="x")
        tk.Label(header, text=tr("📶 WiFi 信息"), font=(FONT_FAMILY, 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text=tr("已保存 WiFi 密码查看 · 数据仅来自本机 netsh · 读密码需管理员权限"),
                 font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        if not IS_WINDOWS:
            banner = tk.Frame(self, bg=COLORS["warn_bg"], padx=12, pady=8)
            banner.pack(fill="x", padx=20, pady=(0, 6))
            plat = "macOS" if IS_MAC else tr("当前平台")
            tk.Label(banner,
                     text=tr("⚠ WiFi 信息查看基于 Windows 的 netsh wlan, ")
                          + plat + "上暂不支持。\n"
                          "   可使用「🔍 网络诊断」标签页查看网络状态。",
                     font=(FONT_FAMILY, 9), fg=COLORS["warn_fg"], bg=COLORS["warn_bg"],
                     justify="left").pack(anchor="w")
        elif not is_admin():
            banner = tk.Frame(self, bg=COLORS["warn_bg"], padx=12, pady=8)
            banner.pack(fill="x", padx=20, pady=(0, 6))
            tk.Label(banner,
                     text=tr("⚠ 当前不是管理员权限: 仍能列出已保存的 WiFi, 但读不出密码。\n"
                          "   请右键「以管理员身份运行」程序或 network-reset.bat。"),
                     font=(FONT_FAMILY, 9), fg=COLORS["warn_fg"], bg=COLORS["warn_bg"],
                     justify="left").pack(anchor="w")

        ctrl = tk.Frame(self, bg=self["bg"], pady=10, padx=20)
        ctrl.pack(fill="x")
        self.btn_refresh = styled_btn(
            ctrl, tr("🔄 刷新列表"), self._do_refresh,
            COLORS["green"], font_size=10,
            tip="列出本机已保存的所有 WiFi 及其密码(netsh wlan)。\n"
                "读取密码需要管理员权限; 密码仅在本机显示, 不会外传。")
        self.btn_refresh.pack(side="left", padx=(0, 8))
        self.btn_export = styled_btn(
            ctrl, tr("💾 导出"), self._do_export,
            COLORS["blue"], font_size=10,
            tip="把列表(SSID/密码/认证)导出为 txt 文件。\n"
                "文件含明文密码, 请妥善保管, 不要发给别人。")
        self.btn_export.pack(side="left", padx=4)

        self.wifi_status = tk.Label(self, text=tr("就绪"), font=(FONT_FAMILY, 10),
                                    fg=COLORS["muted"], bg=self["bg"], anchor="w")
        self.wifi_status.pack(fill="x", padx=20)

        self._build_results(self)
        self._show_hint()

    def _show_hint(self):
        self._clear_results()
        card = self._card(self.results_inner, tr("📶 WiFi 信息说明"))
        self._result_info(card, tr("列出本机保存过的 WiFi(自己/家人/旧手机连过的), 并回读密码。"))
        self._result_info(card, tr("读取密码需要管理员权限; 非管理员启动时密码列显示「未取到」。"))
        self._result_info(card, tr("密码只在本机显示与导出, 不联网、不上传任何数据。"))
        self._result_info(card, tr("换路由器改密码后刷新一次, 可核对是否存下了新密码。"))

    def _set_status(self, msg, color=None):
        self.wifi_status.config(text=msg, fg=color or COLORS["muted"])

    def _set_running(self, running):
        self._running = running
        state = "disabled" if running else "normal"
        for btn in (self.btn_refresh, self.btn_export):
            btn.config(state=state)

    # ---------- 刷新流程 ----------
    def _do_refresh(self):
        if self._running:
            return
        self._set_running(True)
        self._clear_results()
        self._set_status(tr("⏳ 正在读取已保存 WiFi..."), COLORS["blue"])
        threading.Thread(target=self._thread_refresh, daemon=True).start()

    def _thread_refresh(self):
        try:
            items, error = self._tool.list_wifi()
        except Exception as e:
            safe_after(self, lambda: self._set_status(
                f"❌ 读取失败: {e}", COLORS["red"]))
            safe_after(self, lambda: self._set_running(False))
            return
        self._items = items
        ui_sync(self, lambda: self._render_wifi(items, error))

    def _render_wifi(self, items, error):
        self._clear_results()
        self._set_running(False)

        if error:
            card = self._card(self.results_inner, tr("❌ 读取失败"))
            self._result_fail(card, tr("无法列出已保存 WiFi"), f"原因: {error}")
            self._result_info(card, tr("Windows 上请确认 WLAN 服务已启动; 其余平台暂不支持。"))
            self._set_status(f"❌ {error}", COLORS["red"])
            return

        if not items:
            card = self._card(self.results_inner, tr("📶 没有已保存的 WiFi"))
            self._result_info(card, tr("本机没有保存过任何 WiFi(无线网卡不可用时也会这样)。"))
            self._set_status(tr("✅ 已刷新: 0 个已保存 WiFi"))
            return

        found = sum(1 for it in items if it.get("password"))
        cols = ("ssid", "password", "auth")
        config_treeview_style(self)
        tree = ttk.Treeview(self.results_inner, columns=cols,
                            show="headings", height=16, style="nice.Treeview")
        for cid, title, width in (("ssid", "SSID", 220),
                                  ("password", tr("密码"), 240),
                                  ("auth", tr("认证方式"), 140)):
            tree.heading(cid, text=title)
            tree.column(cid, width=width, anchor="w")
        tree.tag_configure("nopass", foreground=COLORS["muted"])
        for it in items:
            pwd = str(it["password"]) if it.get("password") else tr("(未取到)")
            tags = () if it.get("password") else ("nopass"),
            tree.insert("", "end",
                        values=(str(it["ssid"]), pwd,
                                str(it.get("auth") or "-")),
                        tags=tags)
        scrollbar = theme_scrollbar(self.results_inner, tree.yview, orient="vertical")
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.wifi_tree = tree

        note = self._card(self.results_inner, tr("📊 汇总"))
        self._result_info(note, f"共 {len(items)} 个已保存 WiFi, 取到密码 {found} 个。")
        if found < len(items):
            self._result_info(note, tr("未取到密码的条目多为开放网络(无密码)或权限不足。"))
        self._set_status(
            f"✅ 已刷新: {len(items)} 个 WiFi(取到密码 {found} 个)",
            COLORS["green"])

    # ---------- 导出 ----------
    def _do_export(self):
        if not self._items:
            messagebox.showinfo(tr("导出"), tr("请先点「刷新列表」读取数据。"), parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title=tr("导出 WiFi 列表"),
            defaultextension=".txt",
            initialfile="wifi_profiles.txt",
            filetypes=[(tr("文本文件"), "*.txt"), (tr("所有文件"), "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(WifiTool.export_text(self._items))
        except Exception as e:
            messagebox.showerror(tr("导出失败"),
                                 f"写入文件失败:\n{e}", parent=self)
            return
        messagebox.showinfo(
            tr("导出完成"),
            f"已导出 {len(self._items)} 条 WiFi 记录到:\n{path}\n\n"
            f"文件含明文密码, 请妥善保管。", parent=self)
