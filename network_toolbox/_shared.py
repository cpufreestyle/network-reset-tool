# -*- coding: utf-8 -*-
"""网络工具箱内部共享模块。

存放所有模块级函数与常量; engine/report/ui_panels/app 通过显式
`from network_toolbox._shared import (...)` 引入所需符号(含下划线私有符号),
确保类体与运行时调用都能解析到名称, 且不存在包内循环依赖。
"""
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

_SINGLETON_PORT = 45678  # 固定端口

_SINGLETON_SOCKET = None

def _acquire_singleton():
    """使用socket端口绑定实现单例检测(Windows友好)"""
    global _SINGLETON_SOCKET
    try:
        _SINGLETON_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # SO_REUSEADDR: 避免上次 TIME_WAIT 残留导致重启时误判"已在运行"
        try:
            _SINGLETON_SOCKET.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            pass
        _SINGLETON_SOCKET.bind(('127.0.0.1', _SINGLETON_PORT))
        _SINGLETON_SOCKET.listen(1)
        return True  # 成功绑定 = 第一个实例
    except socket.error:
        return False  # 端口已被占用 = 已有实例运行

_am_first = _acquire_singleton()

def _release_singleton():
    """释放socket(程序退出时调用)"""
    global _SINGLETON_SOCKET
    if _SINGLETON_SOCKET:
        try:
            _SINGLETON_SOCKET.close()
        except Exception:
            pass

IS_WINDOWS = sys.platform.startswith("win")

IS_MAC = sys.platform == "darwin"

IS_LINUX = sys.platform.startswith("linux")

def is_admin():
    if IS_WINDOWS:
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            return False
    # macOS / Linux：root 用户视为拥有管理员权限
    try:
        return os.geteuid() == 0
    except Exception:
        return False

def _mac_primary_service():
    """返回 macOS 上当前用于默认路由的网络服务名(networksetup 需要服务名)。"""
    if not IS_MAC:
        return None
    try:
        # 取默认路由所用的接口(en0/en1...)
        out = subprocess.run(['route', '-n', 'get', '0.0.0.0'],
                             capture_output=True, text=True, timeout=8).stdout
        iface = None
        for line in out.splitlines():
            s = line.strip()
            if s.startswith('interface:'):
                iface = s.split(':', 1)[1].strip()
                break
        if not iface:
            return None
        # 列出所有服务 -> 找到包含该接口的那一行
        svcs = subprocess.run(['networksetup', '-listallnetworkservices'],
                              capture_output=True, text=True, timeout=8).stdout
        # 同时列出接口映射
        order = subprocess.run(['networksetup', '-listnetworkserviceorder'],
                               capture_output=True, text=True, timeout=8).stdout
        # 形如: (1) Wi-Fi, Device: en0
        import re as _re
        for line in order.splitlines():
            m = _re.search(r'Device:\s*(\S+)', line)
            if m and m.group(1) == iface:
                name = line.split(',', 1)[0].split(')', 1)[-1].strip()
                return name
        # 退回, 取第一个未禁用的服务
        for s in svcs.splitlines()[1:]:
            s = s.strip()
            if s and not s.startswith('*'):
                return s
    except Exception:
        pass
    return None

def _is_win7_or_older():
    """检测是否 Windows 7 或更早版本（Get-NetAdapter/Resolve-DnsName 等命令不可用）"""
    if not IS_WINDOWS:
        return False
    try:
        ver = sys.getwindowsversion()
        # Win7 = 6.1, Vista = 6.0, Win2k8 = 6.0, XP = 5.1
        return ver.major <= 5 or (ver.major == 6 and ver.minor <= 1)
    except Exception:
        return False

# 主题配色表（F11 深色/浅色切换）。语义键名如下：
#   bg/surface/surface2/bg2  由深到浅的界面层次；bg2 是结果区画布底色
#   text/subtext/muted       主文字/次要文字/弱化文字
#   green..mauve             功能强调色；card 是内容卡片底色
#   warn_bg/warn_fg          顶部警示横幅（权限不足/平台不支持）
THEMES = {
    "dark": {
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
        "mauve": "#b4befe",  # lavender，与 purple 区分，用于「导出报告」
        "card": "#2a2a3e",
        "warn_bg": "#3a2a2a",
        "warn_fg": "#ffb4a0",
    },
    "light": {
        "bg": "#eff1f5",
        "surface": "#e6e9ef",
        "surface2": "#dce0e8",
        "bg2": "#e6e9ef",
        "text": "#4c4f69",
        "subtext": "#5c5f77",
        "muted": "#7c7f93",
        "green": "#40a02b",
        "yellow": "#df8e1d",
        "red": "#d20f39",
        "blue": "#1e66f5",
        "purple": "#8839ef",
        "orange": "#fe640b",
        "teal": "#179299",
        "pink": "#ea76cb",
        "sky": "#04a5e5",
        "mauve": "#7287fd",
        "card": "#ffffff",
        "warn_bg": "#ffd9d2",
        "warn_fg": "#a11208",
    },
}

DEFAULT_THEME = "dark"
THEME_NAMES = ("dark", "light")
THEME_LABELS = {"dark": "🌙 深色", "light": "☀️ 浅色"}

# COLORS 是"当前生效"的字典: set_theme() 就地覆写它, 因此 ui_panels/app 里
# `from network_toolbox._shared import COLORS` 持有的同一对象会同步换色,
# 无需逐个模块改引用(避免 import 别名过期导致漏刷新)。
COLORS = dict(THEMES[DEFAULT_THEME])

APP_NAME = "网络工具箱"

APP_VERSION = "4.6.0"

APP_AUTHOR = "michaelqiu"

ADAPTER_AUTO = "自动检测（推荐）"   # 网卡下拉框的默认值

APP_VERSION_SHORT = "v" + ".".join(APP_VERSION.split(".")[:2])  # -> v3.3

# 发布渠道（Gitee Release；auto_updater 与 gitee_upload.py 共用：
GITEE_OWNER = "cpufreestyle"
GITEE_REPO = "network-reset-tool"
EXE_ASSET_NAME = "网络工具箱.exe"

def _app_data_dir():
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif IS_MAC:
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, "NetworkResetTool")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        path = os.path.dirname(os.path.abspath(sys.argv[0]))
    return path

def theme_path():
    """主题偏好文件路径(存放在应用数据目录, 与 monitor/ 等一致)。"""
    return os.path.join(_app_data_dir(), "theme.txt")


def current_theme():
    """读取持久化的主题名; 没有记录/读失败时回落到默认主题。"""
    try:
        with open(theme_path(), "r", encoding="utf-8") as f:
            name = f.read().strip().lower()
        if name in THEME_NAMES:
            return name
    except Exception:
        pass
    return DEFAULT_THEME


def set_theme(name):
    """切换主题并持久化; 返回实际生效的主题名。

    就地更新 COLORS(clear+update) 而不是重新赋值, 这样其他模块
    `from ... import COLORS` 拿到的同一 dict 引用也会跟着变。
    """
    if name not in THEME_NAMES:
        name = DEFAULT_THEME
    COLORS.clear()
    COLORS.update(THEMES[name])
    try:
        d = _app_data_dir()
        with open(os.path.join(d, "theme.txt"), "w", encoding="utf-8") as f:
            f.write(name)
    except Exception:
        pass  # 写不进去(只读目录/UAC)也不影响本次生效
    return name


def toggle_theme():
    """深浅主题来回切, 返回生效的主题名。"""
    return set_theme("light" if current_theme() == "dark" else "dark")


def decode_output(raw_bytes):
    """把子进程输出安全地解码为 str（跨平台 / 跨 Windows 代码页）。"""
    if raw_bytes is None:
        return ""
    if isinstance(raw_bytes, str):
        return raw_bytes
    if not raw_bytes:
        return ""
    # 1) BOM 探测
    if raw_bytes[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw_bytes.decode("utf-16", errors="replace").lstrip("\ufeff")
    if raw_bytes[:3] == b"\xef\xbb\xbf":          # UTF-8 BOM
        return raw_bytes.decode("utf-8", errors="replace").lstrip("\ufeff")
    # 2) UTF-16LE 特征：ASCII 字符后紧跨 NUL
    if b"\x00" in raw_bytes[:200]:
        try:
            return raw_bytes.decode("utf-16-le").lstrip("\ufeff")
        except (UnicodeDecodeError, LookupError):
            pass
    # 3) UTF-8（现代 PowerShell / macOS / Linux）
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # 4) 本地代码页（中文 Windows 的 GBK）
    for enc in ("gbk", "cp936", "mbcs", "latin-1"):
        try:
            return raw_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw_bytes.decode("utf-8", errors="replace")

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9\-_]{0,61}[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9\-_]{0,61}[A-Za-z0-9])?)*$"
)

_IPV4_RE = re.compile(r"^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$")

def http_user_agent(name, suffix=""):
    """ASCII 安全的 User-Agent。

    urllib 以 latin-1 编码 HTTP 请求头，所以中文 app_name 让每次请求都抛
    UnicodeEncodeError（自动更新在 v3.4 才修过，而 F6 测速又圽了同一个坑）。
    非 latin-1 可编码字符按 UTF-8 percent-encode，保证请求头始终合法。
    """
    out = []
    for ch in str(name):
        try:
            ch.encode('latin-1')
            out.append(ch)
        except UnicodeEncodeError:
            out.extend('%%%02X' % b for b in ch.encode('utf-8'))
    return ''.join(out) + suffix

def is_valid_target(target):
    """校验 ping / tracert / DNS 目标，杜绝 `8.8.8.8 & calc` 之类的注入。"""
    if not target or len(target) > 253:
        return False
    if _IPV4_RE.match(target):
        return True
    # 形如 IP 但不是合法 IPv4（如 999.999.999.999）必须拒绝，
    # 否则会被下面的主机名规则放行
    if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", target):
        return False
    # IPv6（含 :: 简写）
    if ":" in target and re.match(r"^[0-9A-Fa-f:.]+$", target) and ":::" not in target:
        return True
    return bool(_HOSTNAME_RE.match(target))

DNS_PRESETS = {
    "自动获取(DHCP)": {"mode": "dhcp", "primary": "", "secondary": "", "color": "muted",
                        "hint": "把 DNS 交回路由器自动下发，清掉之前手动填写的地址；怀疑手动 DNS 填错时点它"},
    "阿里 DNS":    {"mode": "static", "primary": "223.5.5.5",  "secondary": "223.6.6.6",  "color": "orange",
                     "hint": "阿里云公共 DNS，国内解析最快"},
    "Google DNS": {"mode": "static", "primary": "8.8.8.8",    "secondary": "8.8.4.4",    "color": "blue",
                    "hint": "全球通用，国内直连时常需配合代理"},
    "Cloudflare": {"mode": "static", "primary": "1.1.1.1",    "secondary": "1.0.0.1",    "color": "sky",
                    "hint": "速度快，官方声明不记录日志"},
    "114 DNS":    {"mode": "static", "primary": "114.114.114.114", "secondary": "114.114.115.115", "color": "pink",
                    "hint": "国内老牌运营商级 DNS，晚高峰偶有超时"},
}

# DNS 预设按钮的悬停说明。地址与 hint 都从 DNS_PRESETS 取，避免两处文案不同步。
def dns_preset_tip(cfg):
    scope = "只作用于上方下拉框选中的网卡，未指定时自动定位当前出口网卡。"
    if cfg["mode"] == "dhcp":
        return f"{cfg['hint']}。{scope}"
    servers = cfg["primary"] + (f" / {cfg['secondary']}" if cfg["secondary"] else "")
    return (f"{servers}\n{cfg['hint']}。\n"
            f"{scope}设置后立即生效并自动刷新 DNS 缓存。")

def _apply_proxy_setting(enabled, server):
    """应用系统代理设置（供快照回滚调用）。

    单独抽成模块级函数，是为了让「回滚」可被测试安全替换——否则每次回滚
    都会真的写注册表去改掉用户的代理配置。enabled 为 False 时明确关闭代理。
    """
    tool = ProxyRepairTool()
    if enabled and server:
        parsed = tool.parse_proxy_server(server)
        if parsed:
            _scheme, host, port = parsed[0]
            return tool.set_system_proxy(host, port, True)
        return False
    return tool.set_system_proxy('', '', False)

def make_btn_style():
    return {'relief': "flat", 'cursor': "hand2", 'padx': 15, 'pady': 6}

class ToolTip:
    """鼠标悬停说明：延时弹出一个无边框 Toplevel。

    控件处于 disabled 状态时不显示——否则「重启电脑」这类按钮会在不可点时
    给出「能点」的错觉。
    """

    _shown = None

    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.win = None
        self.job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._dismiss, add="+")
        widget.bind("<FocusOut>", self._dismiss, add="+")
        widget.bind("<ButtonPress>", self._dismiss, add="+")
        widget.bind("<MouseWheel>", self._dismiss, add="+")
        widget.bind("<Button-4>", self._dismiss, add="+")     # Linux 滚轮
        widget.bind("<Button-5>", self._dismiss, add="+")
        widget.bind("<Destroy>", self._on_destroy, add="+")

    def _schedule(self, _event=None):
        self._dismiss()
        try:
            if str(self.widget.cget("state")) != "normal":
                return
        except Exception:
            pass                       # 无 state 属性的控件照常显示
        try:
            self.job = self.widget.after(self.delay, self._show)
        except Exception:
            self.job = None

    def _show(self):
        self.job = None
        try:
            if not self.widget.winfo_exists():
                return
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 3
            root = self.widget.winfo_toplevel()
        except Exception:
            return

        if ToolTip._shown is not None and ToolTip._shown is not self:
            ToolTip._shown._dismiss()
        ToolTip._shown = self

        win = tk.Toplevel(root)
        win.wm_overrideredirect(True)
        win.withdraw()
        win.configure(bg=COLORS["surface2"])
        tk.Label(win, text=self.text, justify="left", anchor="w",
                 bg=COLORS["surface2"], fg=COLORS["text"], relief="solid",
                 borderwidth=1, highlightthickness=0, font=(FONT_FAMILY, 9),
                 padx=8, pady=5, wraplength=360).pack()
        self.win = win

        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = min(x, max(6, root.winfo_screenwidth() - w - 6))
        if y + h > root.winfo_screenheight() - 6:      # 贴屏幕底边时翻到上方
            y = max(6, self.widget.winfo_rooty() - h - 3)
        win.wm_geometry("+{}+{}".format(x, y))
        win.deiconify()

    def _dismiss(self, _event=None):
        if self.job is not None:
            try:
                self.widget.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
        win, self.win = self.win, None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        if ToolTip._shown is self:
            ToolTip._shown = None

    def _on_destroy(self, event):
        if event.widget is self.widget:
            self._dismiss()

def attach_tooltip(widget, text, delay=400):
    """给控件挂悬停说明；返回 widget 以便链式调用。"""
    if text:
        widget._tooltip = ToolTip(widget, text, delay)
    return widget

def styled_btn(parent, text, cmd, bg, fg=None, font_size=10, bold=False, tip=None, **kw):
    if fg is None:
        fg = COLORS["bg"]
    font_name = FONT_FAMILY
    font_weight = "bold" if bold else "normal"
    btn = tk.Button(parent, text=text, font=(font_name, font_size, font_weight),
                    bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
                    command=cmd, **make_btn_style(), **kw)
    return attach_tooltip(btn, tip)

def safe_after(widget, fn, delay_ms=0):
    """把 fn 投递到 Tk 主线程执行; 窗口已销毁/正在销毁时静默失败。

    工作线程收尾阶段调用 after() 会抛 RuntimeError/TclError(窗口没了),
    裸 after(0, ...) 调用没有兜底时会往 stderr 打一条 traceback
    (windowed 模式下表现为退出码非0/日志噪音)。统一走本函数消除该类问题。

    回调本身也要兜住: after() 只保证"调度成功", 不保证"执行时控件还在"。
    典型场景是换主题整树重建 / 关窗竞态——worker 线程排了队, 主线程先把旧面板
    destroy 了, 回调里 cget/config 就抛 TclError: invalid command name。
    所以执行阶段也要吞掉 TclError(注意: 不能在这里判 winfo_exists 后跳过 fn,
    否则 ui_sync 里等 Event 的工作线程会白等到超时)。

    返回值: after 的调度 id, 或 None(调度失败)。
    """
    def _run():
        try:
            fn()
        except tk.TclError:
            pass  # 窗口在"调度后、执行前"被销毁, 回调已无意义

    try:
        return widget.after(delay_ms, _run)
    except Exception:
        return None


def ui_sync(widget, fn, timeout=30):
    """从工作线程把一段 UI 代码投递到 Tk 主线程执行，并等待其完成。

    Tkinter 不是线程安全的：在子线程里直接创建/修改控件会造成随机崩溃、
    界面卡死、布局错乱（本项目"日志界面闪退"的根因）。
    本函数统一走 `after(0, ...)` 在主线程执行，再用 Event 同步等待结果。

    注意：调用方必须确保主线程仍在 mainloop 中，否则 after 会失败，
    这里做了兜底（Tk 已销毁时静默返回 None，不抛异常）。
    """
    if threading.current_thread() is threading.main_thread():
        return fn()
    done = threading.Event()
    box = {}

    def _run():
        try:
            box['value'] = fn()
        except Exception as e:      # 异常带回工作线程，不让它炸掉 mainloop
            box['error'] = e
        finally:
            done.set()

    if safe_after(widget, _run) is None:
        return None                 # 窗口已关闭
    if not done.wait(timeout=timeout):
        return None
    if 'error' in box:
        raise box['error']
    return box.get('value')

def _is_mothers_day(today=None):
    """判断今天是否为母亲节（5 月第二个周日）。

    旧实现把日期写死成 `[9, 10]`（仅 2026 年成立），每年都会失效。
    """
    import datetime
    d = today or datetime.date.today()
    if d.month != 5:
        return False
    # weekday(): Mon=0 ... Sun=6
    first_sunday = 1 + (6 - datetime.date(d.year, 5, 1).weekday()) % 7
    return d.day == first_sunday + 7

FONT_FAMILY = None  # will be set after Tk root init

FONT_MONO = "Consolas"

def _init_font(root=None):
    """检测系统字体。

    必须传入已存在的 Tk 根窗口：旧实现会临时 `tk.Tk()` 再造一个 root 再 destroy，
    在部分环境下会干扰 Tcl 解释器（随机字体失效 / 启动崩溃），这里直接复用主窗口。
    """
    global FONT_FAMILY, FONT_MONO
    import tkinter.font as tkfont
    try:
        available = list(tkfont.families(root)) if root is not None else list(tkfont.families())
    except Exception:
        available = []
    if not available:
        FONT_FAMILY = "Tahoma"
        return
    # 中文字体优选
    for name in ["微软雅黑", "Microsoft YaHei UI", "Microsoft YaHei",
                 "Segoe UI", "Tahoma", "Microsoft Sans Serif", "Arial"]:
        if name in available:
            FONT_FAMILY = name
            break
    else:
        FONT_FAMILY = "Tahoma"
    # 等宽字体
    for name in ["Consolas", "Lucida Console", "Courier New"]:
        if name in available:
            FONT_MONO = name
            break
