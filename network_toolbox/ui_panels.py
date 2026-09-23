# -*- coding: utf-8 -*-
"""UI 面板: 重置 / 诊断 / 代理修复。"""
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
    dns_preset_tip,
    is_admin,
    is_valid_target,
    make_btn_style,
    styled_btn,
    ui_sync,
)
from network_toolbox.engine import (
    NetworkResetTool, NetworkDiagnostic, ProxyRepairTool,
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
        header_title = "🌐 Windows 网络重置工具" if IS_WINDOWS else "🌐 网络重置工具"
        tk.Label(header, text=header_title, font=(FONT_FAMILY, 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text="重置网络配置 · 修复网络问题 · 保留静态IP",
                 font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        # 非 Windows 平台提示横幅 + 禁用 Windows 专属按钮
        if not IS_WINDOWS:
            banner = tk.Frame(self, bg="#3a2a2a", padx=12, pady=8)
            banner.pack(fill="x", padx=20, pady=(0, 6))
            plat = "macOS" if IS_MAC else "当前平台"
            tk.Label(banner,
                     text=f"⚠ 此标签页的完整网络重置(Winsock/TCP-IP/DHCP/静态IP)仅支持 Windows。\n"
                          f"   {plat} 上请使用「🛡️ 代理修复」标签页修复代理与 DNS。",
                     font=(FONT_FAMILY, 9), fg="#ffb4a0", bg="#3a2a2a", justify="left").pack(anchor="w")

        # 按钮区
        btn_area = tk.Frame(self, bg=self["bg"], pady=12)
        btn_area.pack(fill="x", padx=20)

        # 一键重置
        self.btn_all = styled_btn(btn_area, "🚀 一键重置全部",
                                  self._do_all_reset, COLORS["green"],
                                  font_size=13, bold=True,
                                  tip="按顺序执行：建快照 → 备份静态 IP → 重置 Winsock → 重置 TCP/IP\n"
                                      "→ 清 DNS/ARP 缓存 → 刷新 DHCP → 还原静态 IP。\n"
                                      "需要管理员权限；跑完必须重启电脑才生效，上不了网可用「⏪ 回滚」还原。")
        self.btn_all.pack(fill="x", pady=(0, 10))

        tk.Frame(btn_area, bg=COLORS["surface2"], height=1).pack(fill="x", pady=5)
        tk.Label(btn_area, text="- 单独操作 -", font=(FONT_FAMILY, 9),
                 fg=COLORS["muted"], bg=self["bg"]).pack(pady=3)

        # 2行 x 3列按钮
        row1 = tk.Frame(btn_area, bg=self["bg"])
        row1.pack(fill="x", pady=3)
        row2 = tk.Frame(btn_area, bg=self["bg"])
        row2.pack(fill="x", pady=3)
        row3 = tk.Frame(btn_area, bg=self["bg"])
        row3.pack(fill="x", pady=3)

        self._make_btn(row1, "🔄 重置 Winsock", self._do_winsock, COLORS["blue"],
                       "netsh winsock reset：重建网络协议栈目录。\n"
                       "修「能连上却上不了网」、第三方加速/LSP 残留。\n"
                       "需要管理员权限，执行后建议重启电脑。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row1, "🔄 重置 TCP/IP", self._do_tcpip, COLORS["purple"],
                       "netsh int ip reset：把 IP 栈配置写回系统默认值。\n"
                       "会抹掉当前静态 IP / 路由设置，建议先「备份IP」或「建快照」。\n"
                       "执行后必须重启电脑才生效。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row1, "🧹 清除 DNS",    self._do_dns,    COLORS["orange"],
                       "ipconfig /flushdns：清掉本机 DNS 缓存。\n"
                       "域名解析到旧地址、刚改过 DNS 却不生效时先点它。\n"
                       "无风险、不影响网页内容，可随时执行。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row2, "📋 清除 ARP",   self._do_arp,    COLORS["teal"],
                       "arp -d *：清空 ARP 缓存(IP 与网关 MAC 的对应表)。\n"
                       "换过路由器、局域网改过 IP 后点一下即可。\n"
                       "无风险，缓存会自动重新学习。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row2, "🔄 刷新 DHCP",  self._do_dhcp,   COLORS["pink"],
                       "ipconfig /release + /renew：向路由器重新要一次 IP。\n"
                       "IP 冲突、拿到 169.254.x.x 段的地址时点它。\n"
                       "过程中会断网几秒。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row2, "💾 备份IP",      self._do_backup, COLORS["yellow"],
                       "读取并保存当前所有网卡的静态 IP / 子网掩码 / 网关\n"
                       "(存到本机文件，重开程序也在)。\n"
                       "重置 TCP/IP 之前先点它，之后可用「还原IP」找回。").pack(side="left", expand=True, fill="x", padx=3)

        self._make_btn(row3, "📥 还原IP",      self._do_restore, COLORS["sky"],
                       "把上一次「备份IP」保存的静态 IP / 掩码 / 网关写回网卡。\n"
                       "没有备份时只提示、不改动任何配置。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row3, "📸 建快照",      self._do_snapshot, COLORS["mauve"],
                       "把当前 DNS、系统代理、静态 IP 存成一个带时间戳的快照文件，\n"
                       "随时可用「⏪ 回滚」还原。\n"
                       "「一键重置全部」也会自动先建一份，手动点可多留几个历史点。").pack(side="left", expand=True, fill="x", padx=3)
        self._make_btn(row3, "⏪ 回滚",        self._do_rollback, COLORS["pink"],
                       "用最近一次快照还原 DNS 与系统代理，弹窗可额外选择是否连静态 IP 一起还原\n"
                       "(DHCP 网络建议选「否」)。重置后反而上不了网时优先用它。").pack(side="left", expand=True, fill="x", padx=3)

        # ===== 网卡选择 (F3) =====
        tk.Frame(btn_area, bg=COLORS["surface2"], height=1).pack(fill="x", pady=(8, 3))
        nic_row = tk.Frame(btn_area, bg=self["bg"])
        nic_row.pack(fill="x", pady=(0, 4))
        tk.Label(nic_row, text="网卡:", font=(FONT_FAMILY, 9),
                 fg=COLORS["subtext"], bg=self["bg"]).pack(side="left", padx=(3, 4))

        self.adapter_var = tk.StringVar(value=ADAPTER_AUTO)
        self._adapter_map = {ADAPTER_AUTO: None}   # 显示文本 -> 真实网卡名
        self.adapter_combo = ttk.Combobox(
            nic_row, textvariable=self.adapter_var, values=[ADAPTER_AUTO],
            state="readonly", width=26, font=(FONT_FAMILY, 9), style="nic.TCombobox")
        self.adapter_combo.pack(side="left", fill="x", expand=True)
        self.adapter_combo.bind("<<ComboboxSelected>>", self._on_adapter_selected)
        self.btn_refresh_nic = styled_btn(nic_row, "🔄 刷新", self._refresh_adapters,
                                          COLORS["surface2"], COLORS["text"], font_size=9,
                                          tip="重新枚举本机网卡并刷新左边的下拉列表。\n"
                                              "后台执行，网卡多时可能要几秒。")
        self.btn_refresh_nic.pack(side="left", padx=(6, 3))

        # ===== DNS 一键切换 =====
        tk.Frame(btn_area, bg=COLORS["surface2"], height=1).pack(fill="x", pady=(8, 3))
        dns_header = tk.Frame(btn_area, bg=self["bg"])
        dns_header.pack(fill="x", pady=(0, 4))
        tk.Label(dns_header, text="- DNS 一键切换 -", font=(FONT_FAMILY, 9),
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
        tk.Label(dns_custom_row, text="自定义:", font=(FONT_FAMILY, 9),
                 fg=COLORS["subtext"], bg=self["bg"]).pack(side="left", padx=(3, 4))
        self.dns_primary_entry = tk.Entry(dns_custom_row, font=(FONT_MONO, 9),
                                           bg=COLORS["surface"], fg=COLORS["text"],
                                           insertbackground=COLORS["text"],
                                           relief="flat", bd=0, width=14)
        self.dns_primary_entry.pack(side="left", padx=2)
        self.dns_primary_entry.insert(0, "")
        tk.Label(dns_custom_row, text="备用:", font=(FONT_FAMILY, 9),
                 fg=COLORS["subtext"], bg=self["bg"]).pack(side="left", padx=(6, 4))
        self.dns_secondary_entry = tk.Entry(dns_custom_row, font=(FONT_MONO, 9),
                                            bg=COLORS["surface"], fg=COLORS["text"],
                                            insertbackground=COLORS["text"],
                                            relief="flat", bd=0, width=14)
        self.dns_secondary_entry.pack(side="left", padx=2)
        styled_btn(dns_custom_row, "应用", self._do_custom_dns,
                   COLORS["green"], font_size=9,
                   tip="把左边两个输入框填的地址设为本机网卡的 DNS(备用可留空)，\n"
                       "填完会顺带刷新 DNS 缓存。\n"
                       "填错会导致域名解析失败，可用上方「自动获取(DHCP)」救回。").pack(side="left", padx=6)

        # 状态 + 进度
        self.status_label = tk.Label(self, text="就绪", font=(FONT_FAMILY, 10),
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
        tk.Label(log_header, text="📋 执行日志", font=(FONT_FAMILY, 10, "bold"),
                 fg=COLORS["text"], bg=self["bg"]).pack(side="left")
        attach_tooltip(tk.Button(log_header, text="清空", font=(FONT_FAMILY, 9),
                  bg=COLORS["surface2"], fg=COLORS["text"], relief="flat",
                  command=self._clear_log, cursor="hand2"),
                     "清空上方执行日志。\n只清显示内容，不影响任何已生效的网络配置与快照。").pack(side="right")

        log_container = tk.Frame(log_frame, bg=COLORS["bg2"])
        log_container.pack(fill="both", expand=True, pady=5)

        scrollbar = tk.Scrollbar(log_container)
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
        self.btn_cancel = styled_btn(btn_group, "⏹ 取消", self._do_cancel,
                                      COLORS["surface2"], COLORS["text"], state="disabled",
                                      tip="中断正在执行的任务，在下一个步骤边界生效——已经发出的\n"
                                          "系统命令会跑完，不会强行掐断。\n"
                                          "只在「一键重置全部」期间可点，其它操作本来就很短。")
        self.btn_cancel.pack(side="left", padx=5)
        self.btn_restart = styled_btn(btn_group, "🔁 重启电脑", self._restart,
                                       COLORS["yellow"], state="disabled",
                                       tip="5 秒后强制重启 Windows，让 Winsock / TCP-IP 重置真正生效。\n"
                                           "未保存的内容会被丢弃，执行 shutdown /a 可取消。")
        self.btn_restart.pack(side="left", padx=5)
        styled_btn(btn_group, "✕ 退出", self._quit, COLORS["red"],
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
        self.after(600, lambda: self._refresh_adapters(silent=True))

        # 管理员检查
        if not is_admin():
            self._log("⚠ 警告: 未以管理员身份运行,部分功能可能受限")
            self._log("  → 右键选择 [以管理员身份运行] 获得完整功能")

        self._log("✅ 程序已就绪,请选择操作...")

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
        self.after(500, self._refresh_dns_status)

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
            self._log("🔎 网卡: 恢复自动检测")
        self._refresh_dns_status()

    def _refresh_adapters(self, silent=False):
        """后台枚举网卡并刷新下拉框（PowerShell 查询较慢，不能放在主线程）。"""
        if self._running:
            return
        if not silent:
            self._set_status("⏳ 正在枚举网卡...", COLORS["blue"])
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
            self.after(0, lambda: self._log(f"  ⚠ 枚举网卡失败: {e}"))

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
                                  + ("  ★出口" if it.get('gw') else ""))
            elif not silent:
                self._set_status("⚠ 未检测到网卡", COLORS["yellow"])

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
                    m = re.match(r'.*(?:适配器|adapter)\s+(.+?):', line)
                    current_name = m.group(1).strip() if m else None
                elif in_adapter and 'IPv4' in line:
                    if current_name:
                        self._safe_log(f"  ✓ 检测到网卡(ipconfig): {current_name}")
                        return current_name
        except Exception:
            pass

        self._safe_log("  ⚠ 未找到活动网卡")
        return None

    def _make_dns_btn(self, parent, name, cfg):
        btn = tk.Button(parent, text=name, font=(FONT_FAMILY, 9, "bold"),
                        bg=cfg['color'], fg=COLORS["bg"],
                        activebackground=cfg['color'], activeforeground=COLORS["bg"],
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
            self.after(0, functools.partial(self._log, "⚠ 未找到活动网卡,请检查网络连接"))
            self.after(0, functools.partial(self._set_running, False, ""))
            self.after(0, functools.partial(self._set_status, "⚠ 未找到活动网卡", COLORS["orange"]))
            return
        # 修复: 使用functools.partial避免lambda捕获问题
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.switch_dns(preset_name, adapter)
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status, f"✅ DNS 已切换到 {preset_name}", COLORS["green"]))
        self.after(0, self._refresh_dns_status)

    def _safe_log(self, msg):
        """线程安全的日志输出"""
        self.after(0, functools.partial(self._log, msg))

    def _do_custom_dns(self):
        if self._running:
            return
        primary = self.dns_primary_entry.get().strip()
        if not primary:
            self._set_status("⚠ 请输入主 DNS 地址", COLORS["orange"])
            return
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', primary):
            self._set_status("⚠ DNS 地址格式不正确", COLORS["red"])
            return
        secondary = self.dns_secondary_entry.get().strip()
        self._set_running(True, f"设置自定义 DNS: {primary}")
        threading.Thread(target=self._thread_custom_dns,
                        args=(primary, secondary), daemon=True).start()

    def _thread_custom_dns(self, primary, secondary):
        adapter = self._get_active_adapter()
        if not adapter:
            self.after(0, functools.partial(self._log, "⚠ 未找到活动网卡"))
            self.after(0, functools.partial(self._set_running, False, ""))
            return
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.log(f"[DNS] 自定义 DNS: {primary}")
        ok = tool.set_dns(adapter, primary, secondary if secondary else None)
        tool.flush_dns()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status,
            f"✅ 自定义 DNS 设置成功" if ok else "❌ DNS 设置失败",
            COLORS["green"] if ok else COLORS["red"]))
        self.after(0, self._refresh_dns_status)

    def _refresh_dns_status(self):
        """刷新当前 DNS 显示(异步,不阻塞主线程)"""
        self.dns_current_label.config(text="当前: 获取中...")

        # 在主线程把选择读出来，避免工作线程访问 Tk 变量
        adapter = self.selected_adapter()

        def _worker():
            tool = NetworkResetTool()
            dns_list, mode = tool.get_current_dns(adapter)
            if dns_list:
                mode_text = "自动" if mode == "dhcp" else "手动"
                text = f"当前: {', '.join(dns_list)} [{mode_text}]"
            else:
                text = "当前: 未知"
            self.after(0, lambda: self.dns_current_label.config(text=text))

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
            self._set_status("✅ 操作完成", COLORS["green"])
            self.progress.stop()

    # ----- 单独操作 -----
    def _do_winsock(self):
        if self._running: return
        self._set_running(True, "重置 Winsock")
        threading.Thread(target=self._thread_winsock, daemon=True).start()

    def _thread_winsock(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        ok = tool.reset_winsock()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status,
            "✅ Winsock 重置完成" if ok else "❌ 操作失败",
            COLORS["green"] if ok else COLORS["red"]))
        self.after(0, functools.partial(self._log, "\n⚠ 可能需要重启电脑使设置生效"))

    def _do_tcpip(self):
        if self._running: return
        self._set_running(True, "重置 TCP/IP")
        threading.Thread(target=self._thread_tcpip, daemon=True).start()

    def _thread_tcpip(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.reset_tcpip()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status, "✅ TCP/IP 重置完成", COLORS["green"]))
        self.after(0, functools.partial(self._log, "\n⚠ 必须重启电脑使设置生效"))

    def _do_dns(self):
        if self._running: return
        self._set_running(True, "清除 DNS 缓存")
        threading.Thread(target=self._thread_dns, daemon=True).start()

    def _thread_dns(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        ok = tool.flush_dns()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status,
            "✅ DNS 缓存已清除" if ok else "❌ 操作失败",
            COLORS["green"] if ok else COLORS["red"]))

    def _do_arp(self):
        if self._running: return
        self._set_running(True, "清除 ARP 缓存")
        threading.Thread(target=self._thread_arp, daemon=True).start()

    def _thread_arp(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        ok = tool.flush_arp()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status,
            "✅ ARP 缓存已清除" if ok else "❌ 操作失败",
            COLORS["green"] if ok else COLORS["red"]))

    def _do_dhcp(self):
        if self._running: return
        self._set_running(True, "刷新 DHCP")
        threading.Thread(target=self._thread_dhcp, daemon=True).start()

    def _thread_dhcp(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.renew_dhcp()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status, "✅ DHCP 已刷新", COLORS["green"]))

    def _do_backup(self):
        if self._running: return
        self._set_running(True, "备份 IP 配置")
        threading.Thread(target=self._thread_backup, daemon=True).start()

    def _thread_backup(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.backup_static_ip()
        self._static_configs = tool.static_configs
        if tool.static_configs:
            self._save_backup(tool.static_configs)
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status, "✅ IP 配置备份完成", COLORS["green"]))

    def _do_restore(self):
        if self._running: return
        if not self._static_configs:
            self._static_configs = self._load_backup()   # 重开程序后也能还原
        if not self._static_configs:
            self._log("⚠ 请先点击「备份IP」按钮")
            self._set_status("⚠ 请先备份IP", COLORS["orange"])
            return
        self._set_running(True, "还原 IP 配置")
        threading.Thread(target=self._thread_restore, daemon=True).start()

    def _thread_restore(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        tool.static_configs = self._static_configs
        tool.restore_static_ip()
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, functools.partial(self._set_status, "✅ IP 配置已还原", COLORS["green"]))

    # ----- 配置快照与回滚 (F2) -----
    def _do_snapshot(self):
        if self._running:
            return
        self._set_running(True, "建立配置快照")
        threading.Thread(target=self._thread_snapshot, daemon=True).start()

    def _thread_snapshot(self):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        try:
            snap = tool.take_snapshot()
            path = NetworkResetTool.save_snapshot(snap)
            n = len(snap.get('adapters') or {})
            self.after(0, functools.partial(self._set_status,
                                            f"✅ 快照已保存（{n} 块网卡）", COLORS["green"]))
            self.after(0, functools.partial(self._safe_log, f"📸 快照已保存: {path}"))
        except Exception as e:
            self.after(0, functools.partial(self._set_status,
                                            f"❌ 快照失败: {e}", COLORS["red"]))
        finally:
            self.after(0, functools.partial(self._set_running, False, ""))

    def _do_rollback(self):
        if self._running:
            return
        snaps = NetworkResetTool.list_snapshots()
        if not snaps:
            messagebox.showinfo("没有快照", "还没有任何配置快照。\n\n"
                                            "建议先点「📸 建快照」，或在「一键重置全部」时自动创建。")
            return
        path, ts, n = snaps[0]
        others = len(snaps) - 1
        extra = f"\n（另有 {others} 个历史快照，回滚默认使用最新一个）" if others else ""
        restore_ip = messagebox.askyesno(
            "回滚确认",
            f"将把网络配置恢复到快照时间：\n  {ts}\n  包含 {n} 块网卡的配置{extra}\n\n"
            f"● 恢复各网卡的 DNS 设置\n● 恢复系统代理设置\n\n"
            f"是否同时恢复静态 IP / 子网掩码 / 网关？（DHCP 网络请选择「否」）")
        self._set_running(True, "回滚网络配置")
        threading.Thread(target=self._thread_rollback, args=(path, restore_ip), daemon=True).start()

    def _thread_rollback(self, path, restore_ip=False):
        tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
        try:
            with open(path, encoding='utf-8') as f:
                snap = json.load(f)
            self.after(0, functools.partial(
                self._safe_log, f"⏪ 开始回滚到 {snap.get('time', '未知时间')} 的快照..."))
            done, total = tool.rollback_snapshot(snap, restore_ip=restore_ip)
            if total == 0:
                self.after(0, functools.partial(self._set_status,
                                                "⚠ 快照里没有可恢复项", COLORS["orange"]))
            elif done == total:
                self.after(0, functools.partial(self._set_status,
                                                f"✅ 回滚完成（{done}/{total}）", COLORS["green"]))
            else:
                self.after(0, functools.partial(self._set_status,
                                                f"⚠ 回滚部分成功（{done}/{total}）", COLORS["orange"]))
        except Exception as e:
            self.after(0, functools.partial(self._set_status,
                                            f"❌ 回滚失败: {e}", COLORS["red"]))
        finally:
            self.after(0, functools.partial(self._set_running, False, ""))
            self.after(0, self._refresh_dns_status)

    # ----- 一键重置 -----
    def _do_all_reset(self):
        if self._running: return
        if not messagebox.askyesno("确认", "将执行完整网络重置:\n\n"
                               "0. 自动建立配置快照(可用「⏪ 回滚」还原)\n"
                               "1. 备份静态IP配置\n"
                               "2. 重置 Winsock\n"
                               "3. 重置 TCP/IP\n"
                               "4. 清除 DNS/ARP 缓存\n"
                               "5. 刷新 DHCP\n"
                               "6. 恢复静态IP(如有)\n\n"
                               "确定要继续吗?"):
            return
        self._set_running(True, "一键重置全部", cancellable=True)
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
                self.after(0, functools.partial(self._safe_log, f"📸 重置前已自动建立快照: {path}"))
            except Exception as e:
                self.after(0, functools.partial(
                    self._safe_log, f"⚠ 自动快照失败（不影响重置）: {e}"))
            tool.run_full_reset()
        finally:
            self._current_tool = None
        self.after(0, functools.partial(self._set_running, False, ""))
        self.after(0, lambda: self.btn_restart.config(state="normal"))

    def _do_cancel(self):
        """请求中断当前任务（在下一个步骤边界生效，不会强行杀掉系统命令）。"""
        if self._current_tool:
            self._current_tool._cancel = True
            self._log("⏹ 已请求取消,将在当前步骤结束后停止...")
            self._set_status("⏹ 取消中...", COLORS["orange"])

    def _restart(self):
        if messagebox.askyesno("确认重启", "网络重置后需要重启电脑才能生效\n\n确定要立即重启吗?"):
            # 使用 shutdown.exe 替代 Restart-Computer（Win7 兼容）
            try:
                subprocess.run(['shutdown', '/r', '/f', '/t', '5', '/c', '网络重置后系统将重启'])
                self._log("5秒后重启电脑...")
            except Exception as e:
                self._log(f"重启失败: {e}")

    def _quit(self):
        if messagebox.askyesno("确认退出", "确定要退出程序吗?"):
            self.destroy()

class DiagnosticPanel(tk.Frame):
    """右侧"网络诊断"标签页"""

    _decode_output = staticmethod(decode_output)

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        self._running = False
        self._latest_results = None
        self._build_ui()

    def _build_ui(self):
        # 标题
        header = tk.Frame(self, bg=COLORS["surface"], pady=12)
        header.pack(fill="x")
        tk.Label(header, text="🔍 网络诊断工具", font=(FONT_FAMILY, 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text="一键检测网络状态 · Ping / DNS / 路由追踪",
                 font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        # 按钮行
        ctrl = tk.Frame(self, bg=self["bg"], pady=10, padx=20)
        ctrl.pack(fill="x")

        self.btn_all_diag = styled_btn(ctrl, "🚀 一键完整诊断", self._do_full_diagnostic,
                                        COLORS["green"], font_size=12, bold=True,
                                        tip="依次跑网络总览 + 多个目标 Ping + 多组 DNS 解析，\n"
                                            "给出连通性结论与评分。全程约 30~60 秒，可点「导出报告」存档。")
        self.btn_all_diag.pack(side="left", padx=(0, 8))

        self.btn_quick = styled_btn(ctrl, "⚡ 快速 Ping", self._do_quick_ping,
                                     COLORS["blue"], font_size=11,
                                     tip="Ping 网关、常用公网与 DNS，判断本机到外网通不通。\n"
                                         "只看连通性，几秒出结果，不改动任何配置。")
        self.btn_quick.pack(side="left", padx=4)

        self.btn_overview = styled_btn(ctrl, "📋 网络总览", self._do_overview,
                                        COLORS["sky"], font_size=11,
                                        tip="显示当前网卡的接口状态、IPv4/掩码、默认网关、\n"
                                            "MAC、DNS 服务器与 DHCP 状态。只读，不改配置。")
        self.btn_overview.pack(side="left", padx=4)

        self.btn_traceroute = styled_btn(ctrl, "🛤️ Traceroute", self._do_traceroute,
                                          COLORS["purple"], font_size=11,
                                          tip="逐跳追踪到右侧输入框目标的路由，看在哪一跳断流。\n"
                                              "目标越远越慢，境外地址可能要几分钟。")
        self.btn_traceroute.pack(side="left", padx=4)

        self.btn_health = styled_btn(ctrl, "📊 健康报告", self._do_health_report,
                                      COLORS["teal"], font_size=11,
                                      tip="重新完整诊断一次，再按连通性 / DNS / 配置完整度 /\n"
                                          "平均延迟 / 丢包打分，给出等级与整改建议。")
        self.btn_health.pack(side="left", padx=4)

        self.btn_export = styled_btn(ctrl, "📄 导出报告", self._do_export,
                                      COLORS["mauve"], font_size=11,
                                      tip="把最近一次诊断结果另存为 HTML(可打印)/ Markdown / TXT，\n"
                                          "便于留档或发给别人排查。\n"
                                          "还没有数据时会先自动跑一次完整诊断。")
        self.btn_export.pack(side="left", padx=4)

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

        self.diag_status = tk.Label(self, text="就绪", font=(FONT_FAMILY, 9),
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

        # 欢迎提示
        self._show_hint()

    def _show_hint(self):
        for w in self.results_inner.winfo_children():
            w.destroy()
        hint = tk.Label(self.results_inner,
                        text="点击上方按钮开始诊断\n\n📡 Ping 测试:检测到目标的网络延迟和连通性\n"
                             "🔍 DNS 解析:测试各 DNS 服务器解析是否正常\n"
                             "🛤️ Traceroute:追踪本机到目标的网络路由路径\n"
                             "📋 网络总览:显示当前 IP/网关/DNS 等信息",
                        font=(FONT_FAMILY, 11), fg=COLORS["muted"], bg=COLORS["bg2"],
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
        for btn in [self.btn_all_diag, self.btn_quick, self.btn_overview,
                    self.btn_traceroute, self.btn_health, self.btn_export]:
            btn.config(state=state)
        if running:
            self.diag_progress.start(8)
        else:
            self.diag_progress.stop()

    # ---- 单个诊断卡片 ----
    def _card(self, parent, title, bg=COLORS["surface"]):
        f = tk.Frame(parent, bg=bg, padx=12, pady=8)
        f.pack(fill="x", pady=2)
        tk.Label(f, text=title, font=(FONT_FAMILY, 10, "bold"),
                 fg=COLORS["text"], bg=bg).pack(anchor="w")
        return f

    def _result_ok(self, parent, text, sub=""):
        color = COLORS["green"]
        icon = "✅"
        tk.Label(parent, text=f"  {icon} {text}", font=(FONT_FAMILY, 10),
                 fg=color, bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)
        if sub:
            tk.Label(parent, text=f"      {sub}", font=(FONT_FAMILY, 9),
                     fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    def _result_fail(self, parent, text, sub=""):
        color = COLORS["red"]
        icon = "❌"
        tk.Label(parent, text=f"  {icon} {text}", font=(FONT_FAMILY, 10),
                 fg=color, bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)
        if sub:
            tk.Label(parent, text=f"      {sub}", font=(FONT_FAMILY, 9),
                     fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    def _result_info(self, parent, text):
        tk.Label(parent, text=f"  {text}", font=(FONT_FAMILY, 9),
                 fg=COLORS["subtext"], bg=parent["bg"], anchor="w").pack(anchor="w", padx=10)

    # ---- 快速 Ping ----
    def _do_quick_ping(self):
        if self._running: return
        self._set_running(True)
        self.diag_progress.configure(mode="indeterminate")
        self.diag_progress.start(8)
        self._set_diag_status("⏳ Ping 测试中...", COLORS["blue"])
        self._clear_results()
        threading.Thread(target=self._thread_quick_ping, daemon=True).start()

    def _thread_quick_ping(self):
        diag = NetworkDiagnostic()
        results = []
        for target, label, _color in NetworkDiagnostic.PING_TARGETS:
            ok, avg_ms, loss, _ = diag.ping(target)
            results.append((target, label, ok, avg_ms, loss))

        def _render():
            self._clear_results()
            row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            row.pack(fill="x", pady=4, padx=4)
            card = self._card(row, "📡 Ping 连通性测试")

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
                self._set_diag_status("✅ 所有目标 Ping 正常", COLORS["green"])
            else:
                self._set_diag_status("⚠ 部分目标连接异常,可尝试网络重置", COLORS["yellow"])

        ui_sync(self, _render)

    # ---- 网络总览 ----
    def _do_overview(self):
        if self._running: return
        self._set_running(True)
        self._clear_results()
        self._set_diag_status("⏳ 读取网络信息...", COLORS["sky"])
        threading.Thread(target=self._thread_overview, daemon=True).start()

    def _thread_overview(self):
        diag = NetworkDiagnostic()
        overview = diag.get_overview()

        def _render():
            self._clear_results()
            row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            row.pack(fill="x", pady=4, padx=4)
            card = self._card(row, "📋 网络状态总览")

            if overview:
                label_map = {
                    "状态": "接口状态",
                    "接口": "网卡名称",
                    "描述": "网卡描述",
                    "MAC": "MAC 地址",
                    "速度": "连接速度",
                    "IPv4": "IPv4 地址",
                    "网关": "默认网关",
                    "DNS": "DNS 服务器",
                    "DHCP": "DHCP 状态",
                }
                for k, v in overview:
                    label = label_map.get(k, k)
                    self._result_info(card, f"{label}:{v}")
            else:
                self._result_fail(card, "无法获取网络信息")

            self._set_running(False)
            self._set_diag_status("✅ 网络总览完成", COLORS["green"])

        ui_sync(self, _render)

    # ---- Traceroute ----
    def _do_traceroute(self):
        if self._running: return
        target = self.custom_target.get().strip()
        if not target:
            self._set_diag_status("⚠ 请输入目标地址", COLORS["orange"])
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
                self._set_diag_status("✅ 路由追踪结果已复制", COLORS["green"])

            attach_tooltip(tk.Button(card, text="📋 复制结果", font=(FONT_FAMILY, 9),
                      bg=COLORS["surface"], fg=COLORS["text"],
                      relief="flat", cursor="hand2",
                      command=copy_trace),
                        "把上面的路由追踪原始文本复制到剪贴板，便于粘贴到反馈里。").pack(anchor="e", padx=10, pady=4)

            self._set_running(False)
            self._set_diag_status("✅ 追踪完成", COLORS["green"])

        ui_sync(self, _render)

    # ---- 自定义 Ping ----
    def _do_custom_ping(self):
        if self._running: return
        target = self.custom_target.get().strip()
        if not target:
            self._set_diag_status("⚠ 请输入目标地址", COLORS["orange"])
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
                self._result_ok(card, "连接正常", f"延迟 {latency_str} · 丢包率 {loss}%")
            else:
                self._result_fail(card, "连接失败", f"丢包率 {loss}%")

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
        self._set_diag_status("⏳ 完整诊断中...", COLORS["green"])
        threading.Thread(target=self._thread_full_diagnostic, daemon=True).start()

    def _thread_full_diagnostic(self):
        diag = NetworkDiagnostic()

        def progress(pct, msg):
            self.after(0, lambda: self.diag_progress.configure(value=pct))
            self.after(0, lambda: self._set_diag_status(f"⏳ {msg}", COLORS["blue"]))

        try:
            results = diag.run_full_diagnostic(progress_callback=progress)
        except Exception as e:
            self.after(0, lambda: self._set_diag_status(f"❌ 诊断失败: {e}", COLORS["red"]))
            self.after(0, lambda: self._set_running(False))
            return

        self._latest_results = results

        def _render():
            self._clear_results()

            def _add_row(title, bg="#2a2a3e", fill="x"):
                row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
                row.pack(fill=fill, pady=4, padx=4)
                return self._card(row, title, bg=bg)

            # ---- 网络总览卡片 ----
            card0 = _add_row("📋 网络状态总览")
            overview = results.get('overview', [])
            if overview:
                for k, v in overview:
                    self._result_info(card0, f"{k}:{v}")
            else:
                self._result_fail(card0, "无法获取网络信息")

            # ---- Ping 卡片 ----
            card1 = _add_row("📡 Ping 连通性测试")
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
            card2 = _add_row("🔍 DNS 解析测试")
            dns_results = results.get('dns', [])
            for d in dns_results:
                if d['ok']:
                    self._result_ok(card2, f"{d['label']} ({d['dns']})",
                                    f"解析成功 → {d['ip']}")
                else:
                    self._result_fail(card2, f"{d['label']} ({d['dns']})", "解析失败")

            # ---- 结论 ----
            # 结论口径统一走 compute_health，与导出的报告保持一致
            card3 = _add_row("💡 诊断结论")
            health = compute_health(results)
            all_ping_ok = health['ping_ok'] == health['ping_total'] and health['ping_total'] > 0
            all_dns_ok = health['dns_ok'] == health['dns_total'] and health['dns_total'] > 0

            if all_ping_ok and all_dns_ok:
                self._result_ok(card3, "网络状态正常", "所有目标连通,DNS 解析正常")
            elif all_ping_ok and not all_dns_ok:
                self._result_fail(card3, "DNS 异常", "Ping 正常但 DNS 解析失败,尝试清除 DNS 缓存")
            elif all_dns_ok and not all_ping_ok:
                self._result_fail(card3, "连通性异常", "DNS 正常但目标不可达,检查网关/防火墙/代理")
            else:
                self._result_fail(card3, "网络连接异常", "部分项目失败,建议使用「网络重置」标签修复")

            self._set_running(False)
            self.diag_progress.configure(value=100)
            self._set_diag_status("✅ 完整诊断完成", COLORS["green"])

        ui_sync(self, _render)

    # ---- 健康报告 ----
    def _do_health_report(self):
        if self._running:
            return
        self._set_running(True)
        self.after(0, self._clear_results)
        self._set_diag_status("⏳ 生成健康报告...", COLORS["teal"])
        threading.Thread(target=self._thread_health_report, daemon=True).start()

    def _thread_health_report(self):
        diag = NetworkDiagnostic()
        try:
            results = diag.run_full_diagnostic()
        except Exception as e:
            self.after(0, lambda: self._set_diag_status(f"❌ 健康报告生成失败: {e}", COLORS["red"]))
            self.after(0, lambda: self._set_running(False))
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

        grade_color = {"优秀": COLORS["green"], "良好": COLORS["blue"],
                       "一般": COLORS["yellow"], "较差": COLORS["red"]}.get(grade, COLORS["subtext"])

        def _render():
            def rc(parent, icon, title, value, sub=None, color=None):
                card = self._card(parent, icon + " " + title, bg="#2a2a3e")
                if color:
                    vc = color
                else:
                    try:
                        num = float(value.rstrip('%'))
                        vc = (COLORS["green"] if num >= 80
                              else COLORS["yellow"] if num >= 50 else COLORS["red"])
                    except (ValueError, TypeError, AttributeError):
                        vc = COLORS["subtext"]
                tk.Label(card, text=value, font=(FONT_FAMILY, 16, "bold"),
                         fg=vc, bg="#2a2a3e").pack(pady=(4, 0))
                if sub:
                    tk.Label(card, text=sub, font=(FONT_FAMILY, 8),
                             fg=COLORS["muted"], bg="#2a2a3e").pack()

            self._clear_results()

            # 顶部:总分 + 等级
            top = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            top.pack(fill="x", pady=4, padx=4)
            score_card = tk.Frame(top, bg="#2a2a3e")
            score_card.pack(side="left", fill="both", expand=True, padx=(0, 4))
            tk.Label(score_card, text="网络健康评分", font=(FONT_FAMILY, 10),
                     fg=COLORS["text"], bg="#2a2a3e").pack(pady=(8, 0))
            tk.Label(score_card, text=f"{total}", font=(FONT_FAMILY, 36, "bold"),
                     fg=grade_color, bg="#2a2a3e").pack()
            tk.Label(score_card, text=f"{grade}", font=(FONT_FAMILY, 11, "bold"),
                     fg=grade_color, bg="#2a2a3e").pack(pady=(0, 8))

            # 等级说明
            advice_card = tk.Frame(top, bg="#2a2a3e")
            advice_card.pack(side="right", fill="both", expand=True, padx=(4, 0))
            tk.Label(advice_card, text="💡 健康建议", font=(FONT_FAMILY, 10, "bold"),
                     fg=COLORS["text"], bg="#2a2a3e").pack(anchor="w", padx=10, pady=(8, 2))
            advice_text = health['advice']
            tk.Label(advice_card, text=advice_text, font=(FONT_FAMILY, 9),
                     fg=COLORS["subtext"], bg="#2a2a3e", wraplength=200,
                     justify="left", anchor="w").pack(anchor="w", padx=10, pady=(0, 8))

            # 维度卡片行
            row1 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            row1.pack(fill="x", pady=4, padx=4)
            conn_pct = f"{round(ping_ok / max(len(ping_results), 1) * 100)}%"
            dns_pct = f"{round(dns_ok / max(len(dns_results), 1) * 100)}%"
            cfg_pct = f"{round(cfg_score / 30 * 100)}%"
            rc(row1, "📡", "连通性", conn_pct, f"{ping_ok}/{len(ping_results)} 目标可达")
            rc(row1, "🔍", "DNS可用", dns_pct, f"{dns_ok}/{len(dns_results)} DNS正常")
            rc(row1, "🔧", "配置完整", cfg_pct, "IP/网关/DNS状态")

            # 性能行
            row2 = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            row2.pack(fill="x", pady=4, padx=4)
            rc(row2, "⚡", "平均延迟", f"{avg_latency}ms", "5个目标平均",
               COLORS["green"] if avg_latency < 100
               else COLORS["yellow"] if avg_latency < 300 else COLORS["red"])
            rc(row2, "📉", "平均丢包", f"{avg_loss}%", "5个目标平均",
               COLORS["green"] if avg_loss == 0
               else COLORS["yellow"] if avg_loss < 20 else COLORS["red"])
            dns_svr = next((v for k, v in overview if 'DNS' in k), "-")
            rc(row2, "🌐", "当前DNS", dns_svr[:20] if len(dns_svr) > 20 else dns_svr, "当前使用")

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
                    "导出诊断报告",
                    "还没有诊断数据。\n\n是否立即运行一次完整诊断，完成后再导出？"):
                return
            self._set_running(True)
            self.diag_progress.configure(mode="determinate")
            self.diag_progress["value"] = 0
            self._set_diag_status("⏳ 诊断中（导出前需先采集数据）...", COLORS["mauve"])
            threading.Thread(target=self._thread_export_after_diag, daemon=True).start()
            return
        self._ask_save_path()

    def _thread_export_after_diag(self):
        diag = NetworkDiagnostic()

        def progress(pct, msg):
            self.after(0, lambda: self.diag_progress.configure(value=pct))
            self.after(0, lambda: self._set_diag_status(f"⏳ {msg}", COLORS["blue"]))

        try:
            self._latest_results = diag.run_full_diagnostic(progress_callback=progress)
        except Exception as e:
            self.after(0, lambda: self._set_diag_status(f"❌ 诊断失败: {e}", COLORS["red"]))
            self.after(0, lambda: self._set_running(False))
            return

        # 保存对话框必须在主线程弹出
        ui_sync(self, lambda: (self._set_running(False), self._ask_save_path()))

    def _ask_save_path(self):
        """弹出另存为对话框并写出报告。必须在主线程调用。"""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出诊断报告",
            defaultextension=".html",
            initialfile=f"网络诊断报告_{stamp}.html",
            filetypes=[("HTML 报告（推荐，可直接打印）", "*.html"),
                       ("Markdown 报告", "*.md"),
                       ("纯文本报告", "*.txt")],
        )
        if not path:
            self._set_diag_status("已取消导出", COLORS["muted"])
            return

        ext = os.path.splitext(path)[1].lower().lstrip(".") or "html"
        try:
            content, enc = render_report(self._latest_results, ext)
            with open(path, "w", encoding=enc) as f:
                f.write(content)
        except Exception as e:
            messagebox.showerror("导出失败", f"写入报告时出错：\n{e}", parent=self)
            self._set_diag_status(f"❌ 导出失败: {e}", COLORS["red"])
            return

        self._set_diag_status(f"✅ 报告已导出: {path}", COLORS["green"])
        if messagebox.askyesno("导出成功", f"报告已保存到：\n\n{path}\n\n是否立即打开？", parent=self):
            if not open_path(path):
                messagebox.showinfo("提示", f"已保存到：\n{path}", parent=self)

class ProxyPanel(tk.Frame):
    """第三个标签页:代理诊断与修复"""

    _decode_output = staticmethod(decode_output)

    def __init__(self, parent):
        super().__init__(parent, bg=COLORS["bg"])
        self._running = False
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=COLORS["surface"], pady=12)
        header.pack(fill="x")
        tk.Label(header, text="🛡️ 代理诊断与修复", font=(FONT_FAMILY, 16, "bold"),
                 fg=COLORS["text"], bg=COLORS["surface"]).pack()
        tk.Label(header, text="检测系统代理 / Clash 端口与 DNS · 一键修复外网连不上",
                 font=(FONT_FAMILY, 9), fg=COLORS["muted"], bg=COLORS["surface"]).pack()

        ctrl = tk.Frame(self, bg=self["bg"], pady=10, padx=20)
        ctrl.pack(fill="x")
        self.btn_diag = styled_btn(ctrl, "🔍 诊断代理", self._do_diagnose,
                                   COLORS["green"], font_size=12, bold=True,
                                   tip="检查系统代理指向的端口还有没有服务在听、本机是否在跑\n"
                                       "Clash/mihomo、其配置里 dns.enable 有没有被关掉。\n"
                                       "只读检测，不会改动任何设置。")
        self.btn_diag.pack(side="left", padx=(0, 8))
        self.btn_repair = styled_btn(ctrl, "🔧 一键修复", self._do_repair,
                                     COLORS["orange"], font_size=12, bold=True,
                                     tip="自动处理诊断出的问题：关闭指向死端口的系统代理、\n"
                                         "打开 Clash 配置的 dns.enable(改之前会先备份原文件)。\n"
                                         "修复后需重开浏览器/相关程序才生效。")
        self.btn_repair.pack(side="left", padx=4)

        self.proxy_progress = ttk.Progressbar(self, mode="indeterminate")
        self.proxy_progress.pack(fill="x", padx=20, pady=(0, 5))
        self.proxy_status = tk.Label(self, text="就绪", font=(FONT_FAMILY, 9),
                                     fg=COLORS["muted"], bg=self["bg"], anchor="w")
        self.proxy_status.pack(fill="x", padx=20)

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("HP.Horizontal.TProgressbar",
                        troughcolor=COLORS["surface"], background=COLORS["orange"], thickness=6)

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

        self._show_hint()

    def _show_hint(self):
        for w in self.results_inner.winfo_children():
            w.destroy()
        tk.Label(self.results_inner,
                 text="点击「诊断代理」检测以下问题:\n\n"
                      "🔌 系统代理是否指向已宕机的端口(外网会全部失败)\n"
                      "🛡️ 是否发现正在运行的 Clash / mihomo 代理核心\n"
                      "🌐 Clash 的 dns.enable 是否被关掉(导致域名解析超时)\n\n"
                      "发现问题后点「一键修复」自动处理。",
                 font=(FONT_FAMILY, 11), fg=COLORS["muted"], bg=COLORS["bg2"],
                 justify="left", padx=20, pady=30).pack(fill="both", expand=True)

    def _clear_results(self):
        for w in self.results_inner.winfo_children():
            w.destroy()

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

    def _card(self, parent, title, bg="#2a2a3e"):
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

    # ---- 诊断 ----
    def _do_diagnose(self):
        if self._running:
            return
        self._set_running(True)
        self._clear_results()
        self._set_status("⏳ 诊断代理中...", COLORS["green"])
        threading.Thread(target=self._thread_diagnose, daemon=True).start()

    def _thread_diagnose(self):
        res = ProxyRepairTool().diagnose()

        def _render():
            self._clear_results()

            def _row():
                r = tk.Frame(self.results_inner, bg=COLORS["bg2"])
                r.pack(fill="x", pady=4, padx=4)
                return r

            card = self._card(_row(), "🔌 系统代理", bg="#2a2a3e")
            if res['proxy_enabled']:
                self._result_info(card, f"已启用,地址: {res['proxy_server'] or '(空)'}")
            else:
                self._result_info(card, "未启用系统代理")
            if res['proxy_ports']:
                if res['proxy_alive']:
                    self._result_ok(card, "代理端口可连通", "外网出口正常")
                else:
                    self._result_fail(card, "代理端口无服务监听", "外网会全部失败!")

            card2 = self._card(_row(), "🛡️ 代理核心", bg="#2a2a3e")
            core = res['clash_core']
            if core:
                pp = res.get('clash_proxy_port')
                if pp:
                    self._result_ok(card2, f"发现 {core['process']} (代理端口 {pp})")
                else:
                    self._result_ok(card2, f"发现 {core['process']} 在端口 {core['port']} 运行")
            else:
                self._result_info(card2, "未发现 Clash/mihomo 核心")

            card3 = self._card(_row(), "🌐 Clash DNS", bg="#2a2a3e")
            dns = res['clash_dns']
            if dns is True:
                self._result_ok(card3, "dns.enable = true", "DNS 模块正常")
            elif dns is False:
                self._result_fail(card3, "dns.enable = false", "fake-ip 模式下会导致解析超时!")
            else:
                self._result_info(card3, "未找到 Clash 配置,无法检测")

            card4 = self._card(_row(), "💡 诊断结论", bg="#2a2a3e")
            if res['issues']:
                for issue in res['issues']:
                    self._result_fail(card4, issue)
                self._result_info(card4, "建议点击「一键修复」自动处理")
                self._set_status("⚠ 发现代理问题,可一键修复", COLORS["yellow"])
            else:
                self._result_ok(card4, "未发现明显代理问题")
                self._set_status("✅ 代理诊断正常", COLORS["green"])

            self._set_running(False)

        ui_sync(self, _render)

    # ---- 修复 ----
    def _do_repair(self):
        if self._running:
            return
        self._set_running(True)
        self._clear_results()
        self._set_status("⏳ 正在修复...", COLORS["orange"])
        threading.Thread(target=self._thread_repair, daemon=True).start()

    def _thread_repair(self):
        tool = ProxyRepairTool(log_callback=self._safe_log)
        ok, actions = tool.repair()

        def _render():
            self._clear_results()
            row = tk.Frame(self.results_inner, bg=COLORS["bg2"])
            row.pack(fill="x", pady=4, padx=4)
            card = self._card(row, "🔧 修复结果", bg="#2a2a3e")
            if not actions:
                self._result_info(card, "无需修复,或请先点「诊断代理」")
            for a in actions:
                self._result_info(card, "• " + a)
            if ok:
                self._result_ok(card, "修复完成!", "建议重开浏览器/相关程序使代理生效")
                self._set_status("✅ 代理修复完成", COLORS["green"])
            else:
                self._result_fail(card, "部分修复失败", "请查看上方信息/手动处理")
                self._set_status("⚠ 修复未完全成功", COLORS["yellow"])
            self._set_running(False)

        ui_sync(self, _render)

    def _safe_log(self, msg, color=None):
        self.after(0, lambda m=msg: self._set_status("修复中: " + m[:60], COLORS["orange"]))