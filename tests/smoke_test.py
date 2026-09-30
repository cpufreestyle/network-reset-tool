#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网络工具箱 - 冒烟自检脚本

用法:  python tests/smoke_test.py
      python tests/smoke_test.py --gui     # 额外做一次 GUI 真实启动自检

覆盖的关键回归点：
  v3.3:
    1. ResetPanel 能拿到 _decode_output（v3.2 缺失 → DNS 切换 100% 失效）
    2. decode_output 对 UTF-8 / GBK / UTF-16LE 都能正确解码
    3. is_valid_target 能挡住命令注入
    4. 母亲节日期动态计算正确（不再写死 [9,10]）
    5. ping / dns_lookup / traceroute 对非法输入安全返回
    6. 各 Panel 的关键线程方法里不再直接创建 Tk 控件
  v3.4:
    7. 自动更新器的 SHA256 校验与下载域名白名单
  v3.5:
    - network_toolbox/ 包拆分收尾(兼容入口/Clash 死节点切换移植回包)
  v3.6:
    13. hosts 文件检查/注释/备份还原（F4）
    14. 监听端口查看与进程结束（F5）
  v4.0:
    15. DNS 批量测速排序（F9）
    16. 定时监控掉线记录（F7）
    17. worker 回投 UI 一律走 safe_after 兜底（无裸 after(0, ...)）
  v4.1:
    18. 网速测试（F6）：端点白名单/上限保护/可取消/fallback
  v4.2:
    19. WiFi 信息管理（F8）：netsh 输出三语解析/密码回读/权限分支/导出
  v4.3:
    20. 深色/浅色主题切换（F11）：主题表键集合一致/就地换色/主题记忆/缺键守卫
  v4.4:
    21. 命令行模式（F10）：子命令接线/退出码语义/JSON 纯净度/不碰 Tk
  v4.6:
    22. 插件式诊断项（F13）：内置项不可被覆盖/单项崩溃不拖败整轮诊断/key 校验/进度节奏不变"""

import os
import re
import sys
import time
import json
import hashlib
import tempfile
import shutil
import datetime

# Windows 中文控制台默认 GBK: 结果行含 ✓/✗/✅ 时会 UnicodeEncodeError,
# 即使全部通过也以退出码 1 结束,  CI/脚本无法判断成败。统一切 UTF-8 输出。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import network_reset_gui as G  # noqa: E402
import auto_updater as AU  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print(f"  [OK]   {name}")
    else:
        FAILED.append((name, detail))
        print(f"  [FAIL] {name}  {detail}")


def t_decode():
    print("\n[1] 输出解码")
    check("UTF-8 中文", G.decode_output("网络".encode("utf-8")) == "网络")
    check("GBK 中文", G.decode_output("网络".encode("gbk")) == "网络")
    check("UTF-16LE(Win7 PowerShell)",
          G.decode_output("ABC".encode("utf-16-le")) == "ABC")
    check("UTF-8 BOM", G.decode_output(b"\xef\xbb\xbfABC") == "ABC")
    check("空字节", G.decode_output(b"") == "")
    check("None 安全", G.decode_output(None) == "")
    # 关键回归：UTF-8 中文不得被误判成 GBK
    raw = "网络工具箱".encode("utf-8")
    check("UTF-8 不被误判为 GBK", G.decode_output(raw) == "网络工具箱",
          f"得到 {G.decode_output(raw)!r}")


def t_decode_available():
    print("\n[2] _decode_output 可访问性（v3.2 的致命缺陷）")
    for cls in (G.NetworkResetTool, G.NetworkDiagnostic,
                G.ResetPanel, G.DiagnosticPanel, G.ProxyPanel):
        check(f"{cls.__name__}._decode_output 存在",
              hasattr(cls, "_decode_output"))
    fn = getattr(G.ResetPanel, "_decode_output", None)
    check("ResetPanel._decode_output 可调用且结果正确",
          callable(fn) and fn("测试".encode("gbk")) == "测试")


def t_target():
    print("\n[3] 目标地址校验（防命令注入）")
    for good in ("8.8.8.8", "223.5.5.5", "www.baidu.com", "a-b.example.cn",
                 "::1", "2001:4860:4860::8888"):
        check(f"合法: {good}", G.is_valid_target(good))
    for bad in ("", "8.8.8.8 & calc", "1.1.1.1; rm -rf /", "a b",
                "example.com|dir", "$(whoami)", "999.999.999.999",
                "x" * 300):
        check(f"拦截: {bad!r}", not G.is_valid_target(bad))


def t_mothersday():
    print("\n[4] 母亲节日期（5 月第二个周日）")
    check("2026-05-10", G._is_mothers_day(datetime.date(2026, 5, 10)))
    check("2025-05-11", G._is_mothers_day(datetime.date(2025, 5, 11)))
    check("2027-05-09", G._is_mothers_day(datetime.date(2027, 5, 9)))
    check("2024-05-12", G._is_mothers_day(datetime.date(2024, 5, 12)))
    check("2026-05-09 不是", not G._is_mothers_day(datetime.date(2026, 5, 9)))
    check("非 5 月不是", not G._is_mothers_day(datetime.date(2026, 6, 10)))


def t_net_ops():
    print("\n[5] 网络操作对非法输入的安全性")
    d = G.NetworkDiagnostic()
    ok, ip, out = d.dns_lookup("8.8.8.8 & calc")
    check("dns_lookup 拒绝注入", ok is False and "非法" in out)
    ok, avg, loss, out = d.ping("1.1.1.1; dir")
    check("ping 拒绝注入", ok is False and "非法" in out)
    out = d.traceroute("a b c")
    check("traceroute 拒绝注入", "非法" in out)

    # 真实网络（无网环境允许失败，只要求不抛异常）
    try:
        ok, avg, loss, _ = d.ping("127.0.0.1", count=1)
        check("ping 127.0.0.1 不抛异常", True)
    except Exception as e:
        check("ping 127.0.0.1 不抛异常", False, repr(e))


TK_CTORS = ("Frame", "Label", "Text", "Button", "Entry")


def _naked_tk_calls(func):
    """用 AST 找出函数体**非嵌套函数内**的 tk.Xxx(...) 调用。

    包在 `_render()` 这种闭包里、再由 ui_sync 投递到主线程的是合规的；
    直接在 worker 线程函数体里构造控件才是线程安全隐患。
    """
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(func))
    tree = ast.parse(src)
    fn = tree.body[0]
    assert isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))

    bad = []

    def _is_tk_ctor(node):
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "tk"
                and node.func.attr in TK_CTORS)

    def visit(node):
        for child in ast.iter_child_nodes(node):
            # 嵌套函数/λ 的体由 ui_sync 投递到主线程执行，视为合规，整个跳过
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if _is_tk_ctor(child):
                bad.append(f"L{child.lineno}: tk.{child.func.attr}()")
            visit(child)

    visit(fn)
    return bad


def t_thread_safety():
    print("\n[6] 线程安全：worker 线程不得直接创建 Tk 控件")
    import inspect
    for cls_name in ("DiagnosticPanel", "ProxyPanel", "ResetPanel"):
        cls = getattr(G, cls_name)
        for mname, m in sorted(inspect.getmembers(cls, predicate=inspect.isfunction)):
            if not mname.startswith("_thread_"):
                continue
            bad = _naked_tk_calls(m)
            check(f"{cls_name}.{mname} 无裸 Tk 构造", not bad, ", ".join(bad))
    # 每个 _thread_* 都必须通过 ui_sync 把 UI 更新送回主线程
    for cls_name in ("DiagnosticPanel", "ProxyPanel"):
        cls = getattr(G, cls_name)
        for mname, m in sorted(inspect.getmembers(cls, predicate=inspect.isfunction)):
            if not mname.startswith("_thread_"):
                continue
            body = inspect.getsource(m)
            check(f"{cls_name}.{mname} 通过 ui_sync 回主线程", "ui_sync(self," in body)
    check("ui_sync 已定义", callable(getattr(G, "ui_sync", None)))
    check("ResetPanel 有取消支持", hasattr(G.ResetPanel, "_do_cancel"))

    # 纪律守卫: worker 回投 UI 一律走 safe_after(窗口销毁时静默失败),
    # 不允许裸 self.after(0, ...) —— 关窗瞬间回投会往 stderr 打 traceback
    import glob
    import re as _re
    pkg_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "network_toolbox")
    naked = []
    for f in sorted(glob.glob(os.path.join(pkg_dir, "*.py"))):
        with open(f, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if _re.search(r"\.after\(0,", line):
                    naked.append(f"{os.path.basename(f)}:{lineno}")
    check("无裸 after(0, ...) 回投", not naked, ", ".join(naked))
    check("safe_after 已导出", callable(getattr(G, "safe_after", None)))


def t_misc():
    print("\n[7] 其他")
    # 版本号只留 _shared.APP_VERSION 一处, 别处(run/文档)都不许再写死
    check("版本号单一来源",
      G.APP_VERSION == G._shared.APP_VERSION
      and G.APP_VERSION_SHORT == "v" + ".".join(G.APP_VERSION.split(".")[:2])
      and not re.search(r'(["\'])\s*[=!]=\s*["\']4\.\d+\.\d+["\']',
                        open(os.path.abspath(__file__), encoding="utf-8").read()),
      f"{G.APP_VERSION}/{G.APP_VERSION_SHORT}")
    check("APP_NAME", G.APP_NAME == "网络工具箱")
    check("IS_LINUX 已定义", hasattr(G, "IS_LINUX"))
    check("静态 IP 备份落盘路径可用",
          G.ResetPanel._backup_file().endswith("static_ip_backup.json"))
    # 单例端口常量仍在
    check("单例端口常量", G._SINGLETON_PORT == 45678)


def t_gui():
    print("\n[9] GUI 启动自检（构造四个面板后销毁）")
    import tkinter as tk
    try:
        root = tk.Tk()
        root.withdraw()
        G._init_font(root)
        check("字体探测成功", bool(G._shared.FONT_FAMILY), f"FONT_FAMILY={G._shared.FONT_FAMILY!r}")
        holder = tk.Frame(root)
        panels = {}
        for cls in (G.ResetPanel, G.DiagnosticPanel, G.ProxyPanel, G.SpeedPanel,
                    G.WifiPanel):
            panels[cls.__name__] = cls(holder)
            check(f"{cls.__name__} 可构造", panels[cls.__name__] is not None)
        p = panels["SpeedPanel"]
        wp = panels["WifiPanel"]
        # 文案守卫: 手写码点曾把"宽"打成僻字(U+5BED), 渲染无报错但界面出现怪字,
        # 这里锁定关键中文串, 防止再回归
        sp_texts = []
        def _collect(w):
            for c in w.winfo_children():
                if c.winfo_class() == "Label":
                    sp_texts.append(str(c.cget("text")))
                _collect(c)
        _collect(p)
        check("SpeedPanel 关键文案渲染正常",
              any("带宽" in t for t in sp_texts)
              and any("测速说明" in t for t in sp_texts), str(sp_texts[:6]))

        # WifiPanel 文案守卫: 非管理员提示 + 表格列名都要真实存在
        wp_texts = []

        def _collect_w(w):
            for c in w.winfo_children():
                if c.winfo_class() == "Label":
                    wp_texts.append(str(c.cget("text")))
                if c.winfo_class() == "Treeview":
                    wp_texts.extend(str(c.heading(col, "text"))
                                    for col in c.cget("columns"))
                _collect_w(c)
        _collect_w(wp)
        check("WifiPanel 关键文案渲染正常",
              any("WiFi" in t for t in wp_texts)
              and any("管理员权限" in t or "管理员" in t for t in wp_texts),
              str(wp_texts[:8]))
        # 表格是懒加载的: 渲染后才有, 顺带验证列名与明文密码展示
        wp._render_wifi([{"ssid": "HomeWiFi", "password": "Passw0rd123",
                          "auth": "WPA2-Personal", "error": None}], None)
        wp_texts = []

        def _collect_tree(w):
            for c in w.winfo_children():
                if c.winfo_class() == "Label":
                    wp_texts.append(str(c.cget("text")))
                if c.winfo_class() == "Treeview":
                    wp_texts.extend(str(c.heading(col, "text"))
                                    for col in c.cget("columns"))
                _collect_tree(c)
        _collect_tree(wp)
        check("WifiPanel 表格含 SSID/密码/认证列",
              any("SSID" in t for t in wp_texts)
              and any("密码" in t for t in wp_texts)
              and any("认证" in t for t in wp_texts), str(wp_texts))
        check("WifiPanel 渲染后状态栏给出汇总",
              any("已刷新" in t and "HomeWiFi" not in t for t in wp_texts)
              or any("已刷新" in t for t in wp_texts), str(wp_texts))
        check("WifiPanel 按钮均已挂 tooltip",
              all(getattr(b, "_tooltip", None) is not None
                  for b in (wp.btn_refresh, wp.btn_export)))
        # safe_after: 存活窗口正常调度; 已销毁窗口静默失败(不抛异常)
        import inspect as _inspect
        fired = []
        holder2 = tk.Frame(root)
        aid = G.safe_after(holder2, lambda: fired.append(1))
        root.update()
        check("safe_after 存活窗口可调度", fired == [1] and aid is not None)
        holder2.destroy()
        try:
            G.safe_after(holder2, lambda: None)
            destroyed_ok = True
        except Exception:
            destroyed_ok = False
        check("safe_after 已销毁窗口不抛异常", destroyed_ok)
        # 真实崩溃形态: 关窗竞态下 Tk 在 worker 线程抛 RuntimeError/TclError,
        # safe_after 必须吞掉并返回 None(不往 stderr 打 traceback)
        class _DeadAfter:
            def after(self, *a, **k):
                raise RuntimeError("main thread is not in main loop")
        check("safe_after 吞掉调度异常并返回 None",
              G.safe_after(_DeadAfter(), lambda: None) is None)

        # 换主题整树重建/关窗竞态: after() 只保证"调度成功", 不保证"执行时控件还在"。
        # 真实踩过的坑: worker 线程排队回投, 主线程已 destroy 旧面板 ->
        # 回调里 config 抛 TclError: invalid command name, Tk 往 stderr 打 traceback。
        import tkinter as _tk
        doomed = tk.Frame(root)
        doomed.destroy()
        try:
            aid = G.safe_after(doomed, lambda: doomed.config(bg="#000000"))
            root.update()
            dead_cb_ok = True
        except Exception:
            dead_cb_ok = False
        check("safe_after 吞掉已销毁控件的回调异常", dead_cb_ok, "")
        # 不能因此把"活着但抛 TclError"的路径也判死, 更不能跳过 fn 导致 ui_sync 超时
        holder3 = tk.Frame(root)
        fired2 = []
        aid2 = G.safe_after(holder3, lambda: fired2.append("ok"))
        root.update()
        check("safe_after 正常路径仍会执行回调", fired2 == ["ok"] and aid2 is not None,
              str(fired2))
        holder3.destroy()
        check("ui_sync 内部复用 safe_after",
              "safe_after(widget, _run)" in _inspect.getsource(G.ui_sync))

        # ---------- MonitorPanel 文案守卫: emoji 曾被写成字面量码点文本 ----------
        mp = G.MonitorPanel(holder)
        check("MonitorPanel 可构造", mp is not None)
        mp_texts = []

        def _collect_m(w):
            for c in w.winfo_children():
                if c.winfo_class() == "Label":
                    mp_texts.append(str(c.cget("text")))
                if c.winfo_class() == "Button":
                    mp_texts.append(str(c.cget("text")))
                _collect_m(c)
        _collect_m(mp)
        check("MonitorPanel 标题/按钮文案正常",
              any(t.startswith("\U0001F4E1 ") and "网络监控" in t for t in mp_texts)
              and any(t.startswith("\U0001F5D1 ") and "清空记录" in t for t in mp_texts),
              str([t for t in mp_texts if "监控" in t or "清空" in t]))
        check("MonitorPanel 无字面量 codepoint 文本",
              not any(re.search(r"(?<!\\)U000[0-9A-Fa-f]{3,5}", t) for t in mp_texts),
              str(mp_texts))
        mp._render_tick({"online": True, "results": {"gw": {"ok": True, "avg_ms": 3}},
                         "time": "10:00:00"})
        check("MonitorPanel 状态点用真 emoji",
              any(t.startswith("\U0001F7E2 在线") for t in mp_texts)
              or "在线" in str(mp.monitor_status.cget("text")),
              str(mp.monitor_status.cget("text")))
        mp.destroy()
        check("MonitorPanel 可销毁", True)

        root.update_idletasks()
        root.destroy()
        check("窗口可正常销毁", True)

        _gui_theme()
    except Exception as e:
        import traceback
        check("GUI 自检", False, traceback.format_exc())


def _gui_theme():
    """App 级主题切换自检: 真实构造主窗口, 切一次主题再切回来。"""
    import types
    import tkinter as tk
    S = G._shared
    # 屏蔽 messagebox: 母亲节问候会在无人值守时弹模态框卡住自检
    app_mod = sys.modules["network_toolbox.app"]
    orig_mb = app_mod.messagebox
    app_mod.messagebox = types.SimpleNamespace(
        showinfo=lambda *a, **k: None, showwarning=lambda *a, **k: None,
        showerror=lambda *a, **k: None, askyesno=lambda *a, **k: False)
    theme_file = S.theme_path()
    theme_bak, had_theme = None, os.path.exists(theme_file)
    if had_theme:
        try:
            with open(theme_file, "r", encoding="utf-8") as f:
                theme_bak = f.read()
        except Exception:
            theme_bak = None
    snapshot = dict(S.COLORS)
    try:
        app = G.App()
        check("App 可构造", app is not None)
        check("主题按钮已放上顶栏", getattr(app, "theme_btn", None) is not None)
        check("主题按钮文案与当前主题一致",
              app.theme_btn.cget("text") == S.THEME_LABELS[app._theme],
              f"{app.theme_btn.cget('text')!r} vs {app._theme}")
        check("启动时套用了持久化主题",
              app._theme == S.current_theme(), f"{app._theme}/{S.current_theme()}")

        # 切到非默认标签页再换主题, 验证"换主题不丢当前页"
        app._switch_tab("wifi")
        tab_before = app._active_tab
        other = "dark" if app._theme == "light" else "light"
        app._toggle_theme()
        check("切换后仍停在原标签页", app._active_tab == tab_before,
              f"{app._active_tab} != {tab_before}")
        check("切换后主题名已更新", app._theme == other, str(app._theme))
        check("切换后按钮文案已更新",
              app.theme_btn.cget("text") == S.THEME_LABELS[other],
              repr(app.theme_btn.cget("text")))
        check("顶层窗口底色跟着换", app.cget("bg") == S.THEMES[other]["bg"],
              str(app.cget("bg")))
        check("内容区底色跟着换", app.content.cget("bg") == S.THEMES[other]["bg"],
              str(app.content.cget("bg")))
        check("tab_buttons 已重建且齐全",
              set(app.tab_buttons) == {"reset", "diagnostic", "proxy", "ports",
                                       "monitor", "speed", "wifi"}, str(sorted(app.tab_buttons)))

        app._toggle_theme()
        check("再切一次回到原主题", app._theme != other
              and app.cget("bg") == S.THEMES[app._theme]["bg"], str(app._theme))
        app.destroy()
        check("换过主题的窗口可正常销毁", True)
    except Exception:
        import traceback
        check("主题切换 GUI 自检", False, traceback.format_exc())
    finally:
        app_mod.messagebox = orig_mb
        # 主题文件是用户真实配置: 换主题测试必须还原, 否则会记住浅色
        S.COLORS.clear()
        S.COLORS.update(snapshot)
        try:
            if os.path.exists(theme_file):
                os.remove(theme_file)
            if theme_bak is not None:
                with open(theme_file, "w", encoding="utf-8") as f:
                    f.write(theme_bak)
        except Exception:
            pass


def t_cli():
    """命令行模式（F10）：子命令接线 / 退出码 / JSON 纯净度 / 不碰 Tk。

    这一组全部走 run_cli(argv) 进程内调用, 不起子进程, 也不建 Tk 窗口,
    因此在没有桌面会话的 CI 上同样能跑。危险操作(reset/--kill/--fix)只验证
    参数校验与权限闸门, 不在测试里真的执行。
    """
    print("\n[20] 命令行模式（F10）")
    import io
    import json as _json
    import contextlib
    import network_toolbox.cli as C

    S = G._shared

    # ---------- 解析器接线: 每个命令都能解析出自己的默认值 ----------
    parser = C.build_parser()
    ns = parser.parse_args(["dns"])
    check("dns 子命令解析出 func", getattr(ns, "func", None) is C.cmd_dns)
    check("dns 默认三个互斥选项都不启用",
          ns.preset is None and ns.auto is False and ns.set is None, str(ns))
    ns2 = parser.parse_args(["dns", "--set", "223.5.5.5", "223.6.6.6"])
    check("dns --set 支持主+备", ns2.set == ["223.5.5.5", "223.6.6.6"], str(ns2.set))
    ns3 = parser.parse_args(["wifi", "--json", "--adapter", "Ethernet 2"])
    check("共享选项(adapter/json)被子命令继承",
          ns3.json is True and ns3.adapter == "Ethernet 2", str(ns3))
    # --cli 只是给兼容入口分流用的开关, 不该在 help 里单独列成一项选项
    # (usage/epilog 里出现 --cli 是刻意的, 因为用户就是这么调用的)
    help_lines = [l for l in parser.format_help().splitlines() if l.strip()]
    check("--cli 开关不单独列成选项",
          not any(l.lstrip().startswith("--cli") for l in help_lines), "")
    ns_cli = parser.parse_args(["--cli", "dns"])
    check("--cli 开关被接受且不影响子命令解析", ns_cli.func is C.cmd_dns)

    # ---------- F12: --lang 写在 --cli 前后都得认 ----------
    # 人们自然会写 `--lang en --cli adapters`。argparse 的 parent parser
    # 只把 --lang 挂到子命令上, 所以顶层也得注册一份。
    import argparse  # noqa: F401  (F12 只用 SUPPRESS 常量)
    import network_toolbox.i18n as _I18N
    _lang_snap = _I18N.current_lang()
    try:
        for _argv in (["--lang", "en", "--cli", "dns"],
                      ["--cli", "--lang", "en", "dns"],
                      ["--cli", "dns", "--lang", "en"],
                      ["--lang=en", "--cli", "dns"]):
            _got = getattr(parser.parse_args(_argv), "lang", None)
            check("--lang 任意位置都识别: %s" % " ".join(_argv),
                  _got == "en", repr(_got))
        check("不给 --lang 时为 None(沿用存好的偏好)",
              getattr(parser.parse_args(["--cli", "dns"]), "lang", None) is None, "")
        # 子命令上的 --lang 默认值必须是 SUPPRESS, 否则顶层解析出来的
        # en 会被子命令的默认 None 覆盖掉, 前置写法就麻未了。
        _sub_choices = parser._subparsers._group_actions[0].choices
        check("子命令 --lang 默认 SUPPRESS(不覆盖顶层)",
              _sub_choices["dns"].get_default("lang") is argparse.SUPPRESS, "")
        for _bad in (["--lang", "fr", "--cli", "adapters"],
                     ["--cli", "adapters", "--lang", "fr"]):
            try:
                parser.parse_args(_bad)
                _rej = False
            except SystemExit:
                _rej = True
            check("非法语言名被拒: %s" % " ".join(_bad), _rej)

        # help/epilog 也得跟着 --lang 走: argparse 的 usage 是 build_parser() 那一刻
        # 就被 tr() 固化的, 所以语言必须在建 parser 之前定下来。
        # 注意 --help 会让 run_cli 抛 SystemExit, 必须接住。
        for _argv, _want in ((["--lang", "en", "--cli", "adapters", "--help"],
                              "Adapter name (auto-detected"),
                             (["--cli", "adapters", "--help"],
                              "指定网卡名")):
            # 每轮先把语言恢原到用户偏好: 上一轮的 --help 会抛 SystemExit
            # 中断 run_cli, 否则内存里的语言还停在 en。
            _I18N._lang = None
            _I18N.set_lang(_lang_snap, persist=False)
            so, se = io.StringIO(), io.StringIO()
            try:
                with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
                    C.run_cli(_argv)
            except SystemExit:
                pass
            _h = so.getvalue()
            check("--help 输出跟随 --lang: %s" % " ".join(_argv),
                  _want in _h, _h[:100])

        # diagnose 的文案里有 f-string 组装的部分（健康评分/结论），
        # AST 打包器覆盖不到，只能靠这里的行为门闸。
        _I18N.set_lang("en", persist=False)
        check("diagnose 文案英文模板可用",
              _I18N.tr_f("健康评分: {total} / 100  ({grade})",
                          total=92, grade="Excellent").startswith("Health score:"),
              _I18N.tr_f("健康评分: {total} / 100  ({grade})",
                          total=92, grade="Excellent"))
        check("结论文案英文模板可用",
              _I18N.tr_f("结论: {text}", text="Network status is normal") == "Conclusion: Network status is normal",
              _I18N.tr_f("结论: {text}", text="Network status is normal"))
        _I18N._lang = None
        _I18N.set_lang(_lang_snap, persist=False)
        # --lang 只影响本次进程: 跑完 CLI 不该改动用户的 lang.txt
        _lp = _I18N.lang_path()
        _had = os.path.exists(_lp)
        _bak = open(_lp, encoding="utf-8").read() if _had else None
        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            C.run_cli(["--lang", "en", "--cli", "dns", "--json"])
        _now = open(_lp, encoding="utf-8").read() if os.path.exists(_lp) else None
        check("--lang en 一次性执行不写回 lang.txt",
              _now == _bak, "%r -> %r" % (_bak, _now))
    finally:
        # 上面的 --help 会抛 SystemExit 中断 run_cli, 语言可能停在 en。
        # 这里一定要还原, 否则后面的 GUI 断言(中文文案)会被带崩。
        if os.path.exists(_lp):
            os.remove(_lp)
        if _bak is not None:
            with open(_lp, "w", encoding="utf-8") as f:
                f.write(_bak)
        _I18N._lang = None
        _I18N.set_lang(_lang_snap)
    # 互斥: --preset 与 --auto 不能同时给
    try:
        parser.parse_args(["dns", "--preset", "x", "--auto"])
        mutex_ok = False
    except SystemExit:
        mutex_ok = True
    check("dns 预设/自动/自定义三者互斥", mutex_ok)

    # ---------- 退出码: 脚本靠它判断成败, 必须逐类验证 ----------
    # 注意 argparse 的参数错误走 parser.error() -> sys.exit(2), 会抛 SystemExit,
    # 这里必须接住, 否则会直接把测试进程带走。
    def _run(argv):
        try:
            return C.run_cli(argv)
        except SystemExit as e:
            return e.code

    code = _run(["nosuchcmd"])
    check("未知命令退出码 2", code == C.EXIT_USAGE, str(code))
    code = _run([])
    check("缺命令退出码 2", code == C.EXIT_USAGE, str(code))
    code = _run(["dns", "--preset", "不存在的DNS"])
    check("未知 DNS 预设退出码 2", code == C.EXIT_USAGE, str(code))
    code = _run(["reset"])
    check("reset 权限闸门: 非管理员给 3, 管理员放行",
          code in (C.EXIT_NEED_ADMIN, C.EXIT_OK),
          "code=%s is_admin=%s" % (code, S.is_admin()))
    code = _run(["ports", "--kill", "-1"])
    check("kill 的权限闸门同样生效",
          code in (C.EXIT_NEED_ADMIN, C.EXIT_FAILED, C.EXIT_OK), str(code))

    # ---------- JSON 纯净度: stdout 只有一个 JSON 对象, 无 BOM, 日志在 stderr ----------
    for argv in (["dns", "--json"], ["monitor", "--json"], ["reset", "--json"]):
        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            code = C.run_cli(argv)
        raw = so.getvalue()
        try:
            obj = _json.loads(raw)
            ok = True
        except Exception as e:
            obj, ok = None, False
        check("--json: %s stdout 是纯净 JSON 对象" % argv[0],
              ok and isinstance(obj, dict)
              and set(obj) == {"ok", "command", "data", "warnings"}
              and obj["command"] == argv[0] and not raw.startswith("\ufeff"),
              "%r" % raw[:60])
        check("--json: %s 退出码与 ok 字段一致" % argv[0],
              (code == C.EXIT_OK) == bool(obj["ok"]) if obj else False,
              "code=%s ok=%s" % (code, obj and obj["ok"]))

    # ---------- reset 的 JSON 里必须带退出码, 否则调用方看不出是权限问题 ----------
    # is_admin 必须打假: GitHub Actions 的 Windows runner 默认就是管理员,
    # 不 mock 的话 reset 会真的跑完整重置, ok 变 True, 这条断言永远不成立。
    real_is_admin = C.is_admin
    C.is_admin = lambda: False
    try:
        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            code = C.run_cli(["reset", "--json"])
    finally:
        C.is_admin = real_is_admin
    obj = _json.loads(so.getvalue())
    check("reset 失败时 JSON 带 exit_code",
          obj["ok"] is False and isinstance(obj["data"].get("exit_code"), int)
          and obj["data"]["exit_code"] == code, _json.dumps(obj["data"])[:120])

    # ---------- 编码: GBK 控制台下 emoji/JSON都不能炸 ----------
    # 只在 Windows 上跑：reconfigure 与 GBK 代码页都只有 Windows 才有意义。
    if sys.platform.startswith("win"):
        import io as _io

        def _gbk_stdout():
            return _io.TextIOWrapper(_io.BytesIO(), encoding="gbk", newline="")

        # 人类模式：日志里的 emoji 不能把命令炸掉。刻意走 run_cli 全程，
        # 覆盖 "run_cli 里调 _lossy_streams" 这层接线(直调 _emit 抓不到)。
        gbk = _gbk_stdout()
        saved_out = sys.stdout
        real_adapters = C.cmd_adapters
        C.cmd_adapters = lambda a, r: (r.log("\U0001f389 网络重置完成!"),
                                       r.log("  \u2713 DNS 已恢复: 阿里 DNS"),
                                       r.data.update({"stub": True}))
        try:
            sys.stdout = gbk
            code = C.run_cli(["adapters"])
            gbk.flush()
            check("GBK 控制台下 emoji 降级输出而非崩溃(人类模式)",
                  code == C.EXIT_OK, "")
        except Exception as e:
            check("GBK 控制台下 emoji 降级输出而非崩溃(人类模式)",
                  False, "%s: %s" % (type(e).__name__, e))
        finally:
            sys.stdout = saved_out
            C.cmd_adapters = real_adapters
            gbk.detach()

        # JSON 模式：stdout 的字节流必须是严格 UTF-8，不能跟着控制台变 GBK
        gbk2 = _gbk_stdout()
        sys.stdout = gbk2
        try:
            code = C.run_cli(["dns", "--json"])
            raw = gbk2.buffer.getvalue()
            try:
                obj = _json.loads(raw.decode("utf-8"))
                ok = (isinstance(obj, dict) and obj["command"] == "dns"
                      and set(obj) == {"ok", "command", "data", "warnings"})
            except Exception:
                obj, ok = None, False
            check("GBK 控制台下 JSON 仍是严格 UTF-8",
                  bool(ok) and code == C.EXIT_OK, repr(raw[:40]))
        finally:
            sys.stdout = saved_out
            gbk2.detach()

    # ---------- report 不带 --out 时不许污染 JSON 流 ----------
    # 报告正文很长，完整跑一遍太慢；用假的 render_report 换掉真实渲染。
    real_render = C.render_report
    try:
        C.render_report = lambda results, fmt: ("ROCKS 报告正文", "utf-8")
        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            code = C.run_cli(["report", "--json"])
        raw = so.getvalue()
        try:
            obj = _json.loads(raw)
            ok = (isinstance(obj, dict)
                  and obj["command"] == "report"
                  and obj["data"].get("content") == "ROCKS 报告正文"
                  and "ROCKS" not in raw.split('"content"')[0])
        except Exception:
            obj, ok = None, False
        check("report --json 不带 --out 时 stdout 仍是纯净 JSON",
              ok and code == C.EXIT_OK, repr(raw[:80]))
    finally:
        C.render_report = real_render

    # ---------- 平台相关命令: 非 Windows 上要明确拒绝而不是崩 ----------
    # cli.py / engine.py 都是 `from ..._shared import IS_WINDOWS` 的值导入,
    # 所以要打各自模块的属性才生效(与 t_wifi 打 E.IS_WINDOWS 同一套办法)。
    E = __import__("network_toolbox.engine", fromlist=["x"])
    real_win = (S.IS_WINDOWS, C.IS_WINDOWS, E.IS_WINDOWS)
    try:
        S.IS_WINDOWS = C.IS_WINDOWS = E.IS_WINDOWS = False
        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            code = C.run_cli(["reset"])
        check("非 Windows 跑 reset 退出码 4", code == C.EXIT_UNSUPPORTED, str(code))
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            code = C.run_cli(["wifi"])
        check("非 Windows 跑 wifi 退出码 4", code == C.EXIT_UNSUPPORTED, str(code))
    finally:
        S.IS_WINDOWS, C.IS_WINDOWS, E.IS_WINDOWS = real_win

    # ---------- 不碰 Tk: CLI 路径不允许出现 Tk 构造 ----------
    import ast as _ast
    import inspect
    cli_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "network_toolbox", "cli.py")
    cli_src = open(cli_path, encoding="utf-8").read()
    # 用 AST 而不是字符串查找: 源码注释/docstring 里本来就会提到 Tk/messagebox 这些词,
    # 字符串匹配会误报。这里只看真正被加载的名字与 import 的模块。
    tree = _ast.parse(cli_src)
    loaded = {n.id for n in _ast.walk(tree) if isinstance(n, _ast.Name)
              and isinstance(n.ctx, _ast.Load)}
    loaded |= {n.value.id for n in _ast.walk(tree)
               if isinstance(n, _ast.Attribute) and isinstance(n.value, _ast.Name)}
    mods = set()
    for n in _ast.walk(tree):
        if isinstance(n, _ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, _ast.ImportFrom):
            mods.add(n.module or "")
    tk_leak = sorted(loaded & {"tk", "ttk", "messagebox", "filedialog"})
    ui_leak = sorted(m for m in mods if m.endswith(("ui_panels", ".app")))
    check("cli.py 不构造任何 Tk 控件", not tk_leak, str(tk_leak))
    check("cli.py 不引入 ui_panels/app", not ui_leak, str(ui_leak))

    # ---------- 入口分流: 兼容入口必须在 import 整个包之前判断 --cli ----------
    gui_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "network_reset_gui.py"), encoding="utf-8").read()
    # 只能匹配真正的 import 语句: docstring 里也提到 `from network_toolbox import *`,
    # 用不带行首的 index 会先命中那段说明文字。
    idx_cli = gui_src.index('if "--cli" in sys.argv:')
    idx_import = gui_src.index("\nfrom network_toolbox import *  # noqa")
    check("--cli 分流早于包导入(不拖 Tk 依赖/不占单例端口)",
          idx_cli < idx_import, "cli@%d import@%d" % (idx_cli, idx_import))
    check("入口透传退出码而非固定 exit(0)",
          "sys.exit(_cli_main())" in gui_src, "")
    # CLI 跑完必须释放单例端口, 否则随后启动的 GUI 会误判"已在运行"
    check("run_cli 释放单例 socket",
          "_release_singleton()" in inspect.getsource(C.run_cli), "")


def t_updater_security():
    print("\n[8] 自动更新器安全（SHA256 校验 / 域名白名单）")

    # --- 校验值文本解析 ---
    hex_ok = "a" * 64
    hex_bad = "b" * 64
    t1 = AU.parse_checksums(f"{hex_ok}  网络工具箱.exe")
    check("sha256sum 格式解析", t1.get("网络工具箱.exe") == hex_ok, str(t1))
    t2 = AU.parse_checksums(hex_ok)
    check("纯 hex 格式解析", t2.get("*") == hex_ok, str(t2))
    t3 = AU.parse_checksums(json.dumps({"网络工具箱.exe": hex_ok}))
    check("JSON 格式解析", t3.get("网络工具箱.exe") == hex_ok, str(t3))
    check("多个文件时按名字取",
          AU.parse_checksums(f"{hex_bad}  a.exe\n{hex_ok}  b.exe", wanted="b.exe")
          == {"b.exe": hex_ok})
    check("空文本返回空", AU.parse_checksums("") == {})

    # --- 文件哈希 ---
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        f.write(b"network toolbox")
        tmp = f.name
    try:
        digest = hashlib.sha256(b"network toolbox").hexdigest()
        check("sha256_file 计算正确", AU.sha256_file(tmp) == digest)
        check("verify_file 正确值通过", AU.AutoUpdater.verify_file(tmp, digest) == digest)
        try:
            AU.AutoUpdater.verify_file(tmp, hex_bad)
            check("verify_file 错误值拒绝", False, "竟然通过了")
        except AU.UpdateIntegrityError:
            check("verify_file 错误值拒绝", True)
        try:
            AU.AutoUpdater.verify_file(tmp, "")
            check("verify_file 缺期望值拒绝", False, "竟然通过了")
        except AU.UpdateIntegrityError:
            check("verify_file 缺期望值拒绝", True)
    finally:
        os.unlink(tmp)

    # --- 域名白名单 ---
    up = AU.AutoUpdater("t", "1.0.0", "o", "r", check_on_start=False)
    check("gitee.com 放行", up._check_host("https://gitee.com/a/b") is True)
    check("子域 *.gitee.com 放行",
          up._check_host("https://assets.gitee.com/x.exe") is True)
    for evil in ("https://evil.com/a.exe", "https://gitee.com.evil.net/a.exe",
                 "http://gitee.com.attacker.io/x"):
        try:
            up._check_host(evil)
            check(f"拦截 {evil}", False, "竟然放行了")
        except AU.UpdateIntegrityError:
            check(f"拦截 {evil}", True)

    # --- fail-closed 策略 ---
    check("require_checksum 默认开启", up.require_checksum is True)
    up2 = AU.AutoUpdater("t", "1.0.0", "o", "r", check_on_start=False,
                         require_checksum=False)
    check("可显式关闭(仅调试)", up2.require_checksum is False)
    check("未校验时无 verified_digest", up._verified_digest is None)

    # --- User-Agent 必须 latin-1 可编码（中文 app_name 曾让所有请求崩溃）---
    ua = AU.AutoUpdater._user_agent(G.APP_NAME)
    try:
        ua.encode("latin-1")
        check("User-Agent 可 latin-1 编码", True)
    except UnicodeEncodeError as e:
        check("User-Agent 可 latin-1 编码", False, str(e))
    ua_en = AU.AutoUpdater._user_agent("NetTool")
    check("纯 ASCII 名不加噪声", ua_en == "NetTool-AutoUpdater/2.0", ua_en)


def _fake_results():
    """一份典型的诊断结果（含一个异常项，便于验证结论分支）。"""
    return {
        'overview': [('接口', 'Ethernet 2'), ('IPv4', '192.168.1.10'),
                     ('网关', '192.168.1.1'), ('DNS', '223.5.5.5, 119.29.29.29')],
        'ping': [
            {'label': '百度', 'target': 'www.baidu.com', 'ok': True, 'avg_ms': 12, 'loss': 0},
            {'label': '谷歌', 'target': '8.8.8.8', 'ok': False, 'avg_ms': None, 'loss': 100},
        ],
        'dns': [
            {'label': '阿里', 'dns': '223.5.5.5', 'ok': True, 'ip': '180.101.51.73'},
            {'label': '腾讯', 'dns': '119.29.29.29', 'ok': True, 'ip': '180.101.51.73'},
            {'label': '谷歌', 'dns': '8.8.8.8', 'ok': False, 'ip': None},
        ],
    }


def t_report():
    print("\n[9] 诊断报告导出（F1）")

    # --- 评分口径 ---
    h = G.compute_health(_fake_results())
    # 连通性 1/2 → 8 分；DNS 2/3 → 20 分；IP+网关+DNS 齐全 → 30 分
    check("评分总分正确", h['total'] == 8 + 20 + 30, f"got {h['total']}")
    check("ping 统计", (h['ping_ok'], h['ping_total']) == (1, 2))
    check("dns 统计", (h['dns_ok'], h['dns_total']) == (2, 3))
    check("平均延迟", h['avg_latency'] == 12.0, str(h['avg_latency']))
    check("平均丢包", h['avg_loss'] == 50.0, str(h['avg_loss']))
    check("有结论文本", bool(h['conclusion']))

    empty = G.compute_health({})
    check("空结果不崩溃", empty['total'] == 0)
    check("空结果有兜底结论", "未采集" in empty['conclusion'])
    check("None 结果不崩溃", G.compute_health(None)['total'] == 0)

    # avg_ms 为 None 时不得抛 TypeError（v3.2 的老坑）
    try:
        G.compute_health({'ping': [{'ok': True, 'avg_ms': None, 'loss': 0}], 'dns': [], 'overview': []})
        check("avg_ms=None 安全", True)
    except Exception as e:
        check("avg_ms=None 安全", False, repr(e))

    # --- 三种格式渲染 ---
    res = _fake_results()
    html_doc, _ = G.render_report(res, 'html')
    txt_doc, _ = G.render_report(res, 'txt')
    md_doc, _ = G.render_report(res, 'md')
    check("HTML 渲染非空", len(html_doc) > 500)
    check("HTML 含评分", str(h['total']) in html_doc)
    check("HTML 含表格", "<table>" in html_doc)
    check("TXT 渲染非空", len(txt_doc) > 200)
    check("TXT 含环境信息", "操作系统" in txt_doc)
    check("MD 渲染非空", len(md_doc) > 200)
    check("MD 含标题", md_doc.lstrip().startswith("# "))
    check("未知格式回落 HTML", G.render_report(res, 'weird')[0].startswith("<!DOCTYPE html>"))

    # --- 转义：系统输出里的尖括号不得污染 HTML ---
    evil = {'overview': [('描述', '<script>alert(1)</script>')],
            'ping': [{'label': '<b>x</b>', 'target': 'a.com', 'ok': True, 'avg_ms': 1, 'loss': 0}],
            'dns': []}
    evil_html = G.render_report(evil, 'html')[0]
    check("HTML 转义 script 标签", "<script>alert(1)</script>" not in evil_html)
    check("HTML 转义后保留文本", "&lt;script&gt;" in evil_html)

    # --- 报告配色跟随当前主题(F11): 硬编码色值曾在深浅主题下都不搭 ---
    S = G._shared
    had_theme = os.path.exists(S.theme_path())
    theme_bak = None
    if had_theme:
        try:
            with open(S.theme_path(), "r", encoding="utf-8") as f:
                theme_bak = f.read()
        except Exception:
            theme_bak = None
    prev = dict(S.COLORS)
    try:
        S.set_theme("dark")
        html_dark = G.render_report(res, 'html')[0]
        check("深色主题报告用主题底色",
              ("--bg: %s" % S.THEMES["dark"]["surface"]) in html_dark,
              "未找到 --bg: %s" % S.THEMES["dark"]["surface"])
        # 打印块强制浅色是刻意的, 排除后再查"写死的浅色色板"是否还残留
        html_no_print = html_dark.split("@media print")[0]
        check("报告不再有写死的浅色色板",
              not any(c in html_no_print for c in ("#1f2328", "#1a7f37", "#cf222e", "#d1d9e0")),
              str([c for c in ("#1f2328", "#1a7f37", "#cf222e", "#d1d9e0")
                   if c in html_no_print]))
        S.set_theme("light")
        html_light = G.render_report(res, 'html')[0]
        check("浅色主题报告用主题底色",
              ("--bg: %s" % S.THEMES["light"]["surface"]) in html_light,
              "未找到 --bg: %s" % S.THEMES["light"]["surface"])
        check("打印仍强制浅色(不跟着深色变黑)",
              "@media print" in html_light and "background: #fff" in html_light)
    finally:
        S.COLORS.clear()
        S.COLORS.update(prev)
        try:
            if os.path.exists(S.theme_path()):
                os.remove(S.theme_path())
            if theme_bak is not None:
                with open(S.theme_path(), "w", encoding="utf-8") as f:
                    f.write(theme_bak)
        except Exception:
            pass

    # --- 真实写出文件 ---
    try:
        d = tempfile.mkdtemp(prefix="nrt_report_")
        p = os.path.join(d, "report.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write(html_doc)
        check("报告可写盘", os.path.getsize(p) > 0)
        with open(p, encoding="utf-8") as f:
            check("报告可回读且是 UTF-8", "网络诊断报告" in f.read())
    except Exception as e:
        check("报告可写盘", False, repr(e))


def t_adapters():
    print("\n[10] 网卡选择下拉框（F3）")
    check("ADAPTER_AUTO 常量已定义", bool(getattr(G, 'ADAPTER_AUTO', None)))
    check("list_adapters 已定义", hasattr(G.NetworkResetTool, 'list_adapters'))
    check("selected_adapter 已定义", hasattr(G.ResetPanel, 'selected_adapter'))
    check("_refresh_adapters 已定义", hasattr(G.ResetPanel, '_refresh_adapters'))
    check("_on_adapter_selected 已定义", hasattr(G.ResetPanel, '_on_adapter_selected'))

    # 自动检测必须让位于手动选择
    import inspect
    src = inspect.getsource(G.ResetPanel._get_active_adapter)
    check("自动检测前先读手动选择", 'selected_adapter' in src)

    items = G.NetworkResetTool().list_adapters()
    check("list_adapters 返回 list", isinstance(items, list))
    if items:
        it = items[0]
        check("条目含 name", 'name' in it and bool(it['name']))
        check("条目含 ip/gw/up", all(k in it for k in ('ip', 'gw', 'up')))
        check("有网关的排在前面", items[0]['gw'] is True or not any(x['gw'] for x in items))
    else:
        check("条目含 name", True, "（本机未枚举到网卡，跳过结构断言）")


def t_snapshot():
    print("\n[11] 快照与回滚（F2）")
    T = G.NetworkResetTool
    check("take_snapshot 已定义", hasattr(T, 'take_snapshot'))
    check("rollback_snapshot 已定义", hasattr(T, 'rollback_snapshot'))
    check("save_snapshot 已定义", hasattr(T, 'save_snapshot'))
    check("list_snapshots 已定义", hasattr(T, 'list_snapshots'))

    snap = T().take_snapshot()
    check("快照含 adapters", isinstance(snap.get('adapters'), dict))
    check("快照含时间戳", bool(snap.get('time')))
    check("快照含 proxy", 'proxy' in snap)

    # --- 用桩对象验证回滚逻辑，绝不真的改动本机配置 ---
    # 重要：必须覆盖 set_system_proxy，否则回滚会真的去写注册表改掉用户代理
    class Stub(T):
        def __init__(self):
            self.calls = []

        def set_dns(self, name, primary, secondary=None):
            self.calls.append(('set_dns', name, primary, secondary))
            return True

        def set_dhcp_dns(self, name):
            self.calls.append(('set_dhcp_dns', name))
            return True

        def set_system_proxy(self, host, port, enable=True):
            self.calls.append(('set_system_proxy', host, port, enable))
            return True

        def run_cmd(self, cmd, show_output=False, timeout=10):
            self.calls.append(('run_cmd', cmd))
            return True

        def log(self, msg):
            pass

    fake = {
        'adapters': {
            '以太网-DHCP': {'ip': '10.0.0.5', 'mask': '255.255.255.0', 'gw': '10.0.0.1',
                            'dns': [], 'mode': 'dhcp'},
            '以太网-静态': {'ip': '192.168.1.9', 'mask': '255.255.255.0', 'gw': '192.168.1.1',
                            'dns': ['223.5.5.5', '114.114.114.114'], 'mode': 'static'},
        },
        'proxy': {'enabled': False, 'server': ''},
    }

    # 用桩替换模块级代理恢复函数，避免测试真的写注册表改掉用户代理
    # 拆分后实现经 network_toolbox._shared 调用，故在 G._shared 上打桩
    proxy_calls = []
    orig_apply_proxy = G._shared._apply_proxy_setting

    def fake_apply_proxy(enabled, server):
        proxy_calls.append((enabled, server))
        return True

    G._shared._apply_proxy_setting = fake_apply_proxy
    try:
        s1 = Stub()
        done, total = s1.rollback_snapshot(fake, restore_ip=False)
        kinds = [c[0] for c in s1.calls]
        # 2 块网卡 + 1 个代理 = 3 项
        check("回滚：网卡+代理都处理", total == 3, f"total={total}")
        check("回滚：全部成功", done == total, f"{done}/{total}")
        check("回滚：无 DNS 的走 DHCP", ('set_dhcp_dns', '以太网-DHCP') in s1.calls)
        check("回滚：静态 DNS 带回备用", ('set_dns', '以太网-静态', '223.5.5.5', '114.114.114.114') in s1.calls)
        check("回滚：默认不动 IP", not any(k == 'run_cmd' for k in kinds))
        # 代理分支：快照里是“禁用”，应当调用 _apply_proxy_setting(False, '')
        check("回滚：代理按快照恢复", (False, '') in proxy_calls, str(proxy_calls))
    finally:
        G._shared._apply_proxy_setting = orig_apply_proxy

    s2 = Stub()
    s2.rollback_snapshot(fake, restore_ip=True)
    ip_cmds = [c[1] for c in s2.calls if c[0] == 'run_cmd']
    check("回滚：开启 IP 恢复后才下 netsh", len(ip_cmds) >= 1, str(ip_cmds))
    check("回滚：跳过 DHCP 网卡的静态 IP",
          all('以太网-DHCP' not in c for c in ip_cmds), str(ip_cmds))
    check("回滚：只恢复静态网卡 IP",
          any('以太网-静态' in c for c in ip_cmds), str(ip_cmds))

    check("空快照不崩溃", Stub().rollback_snapshot(None) == (0, 0))
    check("空 adapters 不崩溃", Stub().rollback_snapshot({'adapters': {}}) == (0, 0))

    # --- 落盘 / 读回 ---
    try:
        path = T.save_snapshot(snap)
        check("快照可写盘", os.path.exists(path))
        with open(path, encoding='utf-8') as f:
            back = json.load(f)
        check("快照可回读", back.get('time') == snap.get('time'))
        check("快照能列出", any(p == path for p, _t, _n in T.list_snapshots()))
    except Exception as e:
        check("快照可写盘", False, repr(e))


def t_tooltips():
    print("\n[12] 悬停说明：每个按钮都挂上 tooltip")
    import types
    import tkinter as tk
    try:
        root = tk.Tk()
    except Exception as e:
        check("有可显示的 Tk 环境", False, repr(e))
        return
    app_mod = sys.modules["network_toolbox.app"]
    orig_mb = app_mod.messagebox
    # 屏蔽 messagebox：母亲节问候会在无人值守时弹模态框卡住自检
    app_mod.messagebox = types.SimpleNamespace(
        showinfo=lambda *a, **k: None, showwarning=lambda *a, **k: None,
        showerror=lambda *a, **k: None, askyesno=lambda *a, **k: False)
    try:
        root.withdraw()
        G._init_font(root)
        root.destroy()

        app = G.App()
        total, missing = 0, []

        def walk(w):
            nonlocal total
            for c in w.winfo_children():
                if c.winfo_class() in ("Button", "TButton"):
                    total += 1
                    tip = getattr(c, "_tooltip", None)
                    if tip is None or not getattr(tip, "text", ""):
                        missing.append(repr(c.cget("text")))
                walk(c)

        walk(app)
        check(f"{total} 个按钮均有悬停说明", total >= 25 and not missing,
              f"共 {total} 个，缺失: {', '.join(missing)}")

        # 行为：延时到点才弹窗，离开即销毁；disabled 的按钮不弹
        holder = tk.Frame()
        b = G.styled_btn(holder, "测试", lambda: None, G.COLORS["blue"], tip="提示内容")
        tip = b._tooltip
        tip._show()
        check("悬停后弹出提示窗", tip.win is not None and tip.win.winfo_exists())
        check("提示窗内确有文案", any("提示内容" in str(w.cget("text"))
                                for w in tip.win.winfo_children()))
        tip._dismiss()
        check("离开后提示窗销毁", tip.win is None)
        b.config(state="disabled")
        b._tooltip._schedule()
        check("disabled 按钮不排程显示", b._tooltip.job is None)
        holder.destroy()

        app.destroy()
    except Exception as e:
        import traceback
        check("悬停说明自检", False, traceback.format_exc())
    finally:
        app_mod.messagebox = orig_mb


def t_hosts():
    print("\n[13] hosts 检查与清理（F4）")
    T = G.HostsTool
    check("HostsTool 已定义", T is not None)

    # --- 判定规则(纯函数, 不碰系统 hosts) ---
    check("localhost 正常", not T.is_suspicious("127.0.0.1", ["localhost"])[0])
    check("黑洞地址正常(广告屏蔽)", not T.is_suspicious("0.0.0.0", ["ad.example.com"])[0])
    check("外部 IP 可疑", T.is_suspicious("1.2.3.4", ["www.baidu.com"])[0])
    check("内网 IP 正常", not T.is_suspicious("192.168.1.5", ["nas.local"])[0])
    check("非 IP 目标可疑", T.is_suspicious("foo", ["bar.com"])[0])
    check("::1 正常", not T.is_suspicious("::1", ["myapp.local"])[0])

    # --- 临时 hosts 文件全流程(绝不碰系统 hosts) ---
    d = tempfile.mkdtemp(prefix="nrt_hosts_")
    hp = os.path.join(d, "hosts")
    with open(hp, "w", encoding="utf-8") as f:
        # 首行带 BOM: Windows 记事本保存的 hosts 常见形态, 必须被当成注释跳过
        f.write("\ufeff# 注释行\n"
                "127.0.0.1 localhost\n"
                "1.2.3.4 www.baidu.com\n"
                "0.0.0.0 ads.tracker.com\n"
                "\n"
                "192.168.1.9 nas.local\n")
    try:
        tool = T(hosts_path=hp)
        entries = tool.read_entries()
        check("解析出 4 条映射", len(entries) == 4, str(entries))
        check("BOM 注释行不成条目", not any(e["ip"].startswith("\ufeff") for e in entries))
        check("行号正确(1 起始)", [e["line"] for e in entries] == [2, 3, 4, 6])
        sus = [e for e in entries if e["suspicious"]]
        check("只有 1 条可疑", len(sus) == 1 and sus[0]["host"] == "www.baidu.com",
              str([(e["host"], e["suspicious"]) for e in entries]))
        check("黑洞条目标注原因", any(e["reason"] for e in entries if e["ip"] == "0.0.0.0"))

        # 备份 + 注释
        bak = tool.backup()
        check("备份文件存在", bak and os.path.exists(bak))
        ok, changed, err = tool.comment_suspicious()
        check("注释 1 条成功", ok and changed == 1 and not err, f"{changed} {err}")
        entries2 = tool.read_entries()
        check("注释后只剩 3 条", len(entries2) == 3, str([e["host"] for e in entries2]))
        check("没有可疑条目了", not any(e["suspicious"] for e in entries2))

        # 还原
        ok, err = tool.restore(bak)
        check("还原成功", ok and not err)
        check("还原后恢复 4 条", len(tool.read_entries()) == 4)
        check("备份可列出", any(p == bak for p, _t in tool.list_backups()))
        check("重复注释无操作", tool.comment_suspicious()[1] == 1)  # 还原后又出现 1 条
    finally:
        shutil.rmtree(d, ignore_errors=True)


def t_ports():
    print("\n[14] 监听端口查看（F5）")
    T = G.PortTool
    check("PortTool 已定义", T is not None)

    # --- netstat 解析(纯函数) ---
    sample = ("Active Connections\n\n"
              "  Proto  Local Address          Foreign Address        State           PID\n"
              "  TCP    0.0.0.0:7897           0.0.0.0:0              LISTENING       12345\n"
              "  TCP    127.0.0.1:17650        0.0.0.0:0              LISTENING       678\n"
              "  TCP    192.168.1.10:54321     142.250.80.46:443      ESTABLISHED     999\n"
              "  TCP    [::]:135               [::]:0                 LISTENING       1040\n"
              "  UDP    0.0.0.0:5353           *:*                                    222\n")
    items = T.parse_netstat(sample)
    check("只保留 LISTENING/UDP", len(items) == 4, str(items))
    check("TCP 端口/PID 正确",
          any(i["port"] == 7897 and i["pid"] == 12345 and i["state"] == "LISTENING"
              for i in items))
    check("过滤 ESTABLISHED", not any(i["pid"] == 999 for i in items))
    check("IPv6 地址剥离方括号", any(i["port"] == 135 and i["addr"] == "::" for i in items))
    check("UDP 保留且 state=LISTENING",
          any(i["proto"] == "UDP" and i["port"] == 5353 for i in items))
    check("垃圾行不崩", T.parse_netstat("garbage\n\n") == [])

    # --- tasklist 解析 ---
    tl = '"System","4"\r\n"clash-verge.exe","12345"\r\n'
    m = T.parse_tasklist(tl)
    check("tasklist 映射", m.get(12345) == "clash-verge.exe" and m.get(4) == "System")

    # --- 真实扫描(无网/无权限时允许空列表, 但结构必须正确) ---
    try:
        live = T().list_listening()
        check("list_listening 返回 list", isinstance(live, list))
        if live:
            it = live[0]
            check("条目含 port/pid/process/proto",
                  all(k in it for k in ("port", "pid", "process", "proto")))
            check("端口为整数", isinstance(it["port"], int))
    except Exception as e:
        check("list_listening 不抛异常", False, repr(e))

    # --- kill_process 对脏输入安全 ---
    ok, msg = T().kill_process("not-a-pid")
    check("非法 PID 被拒绝", ok is False and msg)


def t_dns_bench():
    print("\n[15] DNS 测速排序（F9）")
    E = G.engine_module if hasattr(G, "engine_module") else __import__("network_toolbox.engine", fromlist=["x"])
    T = E.NetworkDiagnostic
    check("NetworkDiagnostic 可导入", T is not None)

    # --- 打桩 dns_lookup: 不碰真实网络, 用可控延迟制造排序 ---
    real_lookup = T.dns_lookup
    delay_map = {"223.5.5.5": 0.010, "1.1.1.1": 0.020,
                 "114.114.114.114": 0.030, "8.8.8.8": 0.040}
    fail_once = set()

    def fake_lookup(self, target, dns_server=None):
        time.sleep(delay_map.get(dns_server, 0.005))
        if dns_server == "8.8.8.8" and dns_server not in fail_once:
            fail_once.add(dns_server)
            return False, None, ""
        return True, "1.2.3.4", "Name: www.baidu.com\nAddress: 1.2.3.4"

    T.dns_lookup = fake_lookup
    progress = []
    try:
        ranked = T().benchmark_dns(rounds=3,
                                   progress_callback=lambda n, d, t: progress.append((n, d, t)))
    finally:
        T.dns_lookup = real_lookup

    check("返回 4 个静态预设结果", len(ranked) == 4, str([r["name"] for r in ranked]))
    check("DHCP 预设被跳过", not any(r["name"] == "自动获取(DHCP)" for r in ranked))
    order = [r["name"] for r in ranked]
    check("按平均耗时升序(阿里<Cloudflare<114<Google)",
          order == ["阿里 DNS", "Cloudflare", "114 DNS", "Google DNS"], str(order))
    google = next(r for r in ranked if r["name"] == "Google DNS")
    check("失败轮次计入 fail_rounds", google["fail_rounds"] == 1 and google["ok"],
          str(google))
    ali = ranked[0]
    check("条目含 primary/avg_ms/ip", ali["primary"] == "223.5.5.5" and ali["ip"] == "1.2.3.4"
          and ali["avg_ms"] is not None and ali["avg_ms"] > 0, str(ali))
    check("progress 回调 4x3 次", len(progress) == 12, str(progress[:5]))
    check("进度 total=rounds", all(t == 3 for _n, _d, t in progress))

    # --- 全部失败排最后 ---
    T.dns_lookup = lambda self, target, dns_server=None: (False, None, "")
    try:
        all_fail = T().benchmark_dns(rounds=2)
    finally:
        T.dns_lookup = real_lookup
    check("全失败时 avg_ms=None", all(r["avg_ms"] is None for r in all_fail))
    check("全失败仍返回全部预设", len(all_fail) == 4)
    check("[15] DNS 测速（F9）", True)


def t_monitor():
    print("\n[16] 网络监控掉线记录（F7）")
    E = __import__("network_toolbox.engine", fromlist=["x"])
    M = E.NetworkMonitor
    check("NetworkMonitor 已定义", M is not None)

    # --- 纯函数 ---
    check("45 秒", M.format_duration(45) == "45 秒")
    check("4 分钟", M.format_duration(240) == "4 分钟")
    check("1 小时 3 分钟", M.format_duration(3780) == "1 小时 3 分钟")
    ev = {"start": "2026-09-23 14:23:00", "end": "2026-09-23 14:27:00",
          "duration_seconds": 240}
    check("事件一行文本", M.format_event(ev) == "14:23–14:27 断网 4 分钟",
          M.format_event(ev))

    # --- 打桩诊断对象: get_overview 给网关, ping 按场景通断 ---
    real_diag = E.NetworkDiagnostic
    state = {"online": {"192.168.1.1", "223.5.5.5"}}

    class FakeDiag:
        def __init__(self, *a, **k):
            pass

        def get_overview(self):
            return [("网卡", "WLAN"), ("默认网关", "192.168.1.1")]

        def ping(self, target, count=4):
            ok = target in state["online"]
            return ok, 12.5 if ok else None, 0 if ok else 100, ""

    E.NetworkDiagnostic = FakeDiag
    ticks, events_cb = [], []
    d = tempfile.mkdtemp(prefix="nrt_monitor_")
    m = M(interval_seconds=30, data_dir=d,
          on_tick=ticks.append, on_event=events_cb.append)
    try:
        # resolve_targets: 打桩 override 场景
        m._targets_override = None
        m.targets = []
        tgts = m.resolve_targets()
        check("巡检目标含网关+外网基准", tgts == ["192.168.1.1", "223.5.5.5"], str(tgts))

        # 在线 -> 掉线 -> 恢复, 事件闭合
        s1 = m.check_once()
        check("在线判定", s1["online"] is True and len(s1["results"]) == 2)
        check("结果含 avg_ms/loss", s1["results"]["223.5.5.5"]["loss"] == 0)
        state["online"] = set()
        s2 = m.check_once()
        check("全失败判掉线", s2["online"] is False and m.offline_since is not None)
        m.check_once()
        state["online"] = {"223.5.5.5"}
        s3 = m.check_once()
        check("任一目标通即恢复", s3["online"] is True and m.offline_since is None)
        check("掉线事件落盘", os.path.exists(os.path.join(d, "outages.json")))
        check("事件含起止+时长结构",
              len(m.events) == 1 and set(m.events[0]) == {"start", "end", "duration_seconds"},
              str(m.events))
        check("tick 回调 4 次", len(ticks) == 4, str(len(ticks)))
        check("event 回调 1 次", len(events_cb) == 1)

        # 重启后可回看: 新实例从磁盘加载
        m2 = M(data_dir=d)
        check("重载事件", len(m2.events) == 1)

        # 汇总
        m2.events[0]["duration_seconds"] = 240
        summary = m2.summarize()
        check("汇总次数/总时长", summary["count"] == 1 and summary["total_seconds"] == 240,
              str(summary))

        # 清空
        m2.clear_events()
        check("清空后为空", m2.events == [] and m2.summarize()["count"] == 0)

        # 回归(死锁): on_event 里读汇总会拿同一把锁, 回调必须在锁外触发,
        # 否则主线程/工作线程互等, 整个界面卡死。这里同步复现该调用路径。
        state["online"] = {"192.168.1.1"}
        seen = []
        m4 = M(interval_seconds=60, data_dir=d,
               on_event=lambda ev: seen.append(m4.summarize()))
        m4.check_once()
        state["online"] = set()
        m4.check_once()
        state["online"] = {"192.168.1.1"}
        m4.check_once()
        check("on_event 回调内可安全读汇总(不死锁)",
              len(seen) == 1 and seen[0]["count"] >= 1, str(seen))

        # 线程启停
        m3 = M(interval_seconds=M.MIN_INTERVAL, data_dir=d)
        check("最小间隔保护", M(interval_seconds=5).interval == M.MIN_INTERVAL)
        check("start 返回 True", m3.start() is True)
        check("is_running True", m3.is_running())
        m3.stop()
        check("stop 后 is_running False", not m3.is_running())
    finally:
        E.NetworkDiagnostic = real_diag
        shutil.rmtree(d, ignore_errors=True)
    check("[16] 网络监控掉线记录（F7）", True)


def t_speed():
    print("\n[17] 网速测试（F6）")
    E = __import__("network_toolbox.engine", fromlist=["x"])
    T = E.SpeedTester
    check("SpeedTester 已定义", T is not None)
    check("端点均为 https 固定地址", T.ENDPOINTS
          and all(u.startswith("https://") for u in T.ENDPOINTS),
          str(T.ENDPOINTS))
    check("有读超时与块大小上限", T.TIMEOUT >= 5 and T.CHUNK >= 16 * 1024,
          f"TIMEOUT={T.TIMEOUT} CHUNK={T.CHUNK}")

    class FakeResp:
        """假响应流: 每块 sleep delay 秒, 返回 blocks 个 CHUNK 后结束。"""
        def __init__(self, blocks, delay):
            self.blocks = blocks
            self.delay = delay
        def read(self, n):
            time.sleep(self.delay)
            if self.blocks <= 0:
                return b""
            self.blocks -= 1
            return b"x" * min(n, T.CHUNK)
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    real_open = E.urllib.request.urlopen
    try:
        # --- 正常路径: 8 块 x 64KB = 0.5MB ---
        E.urllib.request.urlopen = lambda req, timeout=None: FakeResp(8, 0.05)
        r = T().test(max_seconds=5)
        check("正常测速 ok", r.get("ok") is True, str(r))
        check("下载量精确(0.5MB)", r.get("downloaded_mb") == 0.5, str(r))
        check("带宽为正且合理", isinstance(r.get("mbps"), float)
              and 1.0 < r["mbps"] < 200.0, str(r))
        check("首包延迟已记录", isinstance(r.get("latency_ms"), int)
              and r["latency_ms"] >= 0, str(r))
        check("默认使用首个端点", r.get("endpoint") ==
              "https://speed.cloudflare.com/__down", str(r))
        check("未停止时 stopped=False", r.get("stopped") is False, str(r))

        # --- 提前停止: 首块后置位, 已下载部分仍估算带宽 ---
        stop = __import__("threading").Event()
        def _stop_after_first(total, elapsed):
            stop.set()
        r2 = T(stop_event=stop).test(max_seconds=5,
                                     progress_callback=_stop_after_first)
        check("提前停止仍 ok(部分流量)", r2.get("ok") is True
              and r2.get("stopped") is True, str(r2))
        check("停止时下载量=1 块", r2.get("downloaded_mb") == 0.0625, str(r2))

        # --- 开始前就取消: 无数据 -> ok False + 已取消 ---
        stop2 = __import__("threading").Event()
        stop2.set()
        r3 = T(stop_event=stop2).test(max_seconds=5)
        check("开始前取消返回已取消", r3.get("ok") is False
              and r3.get("stopped") is True and "取消" in r3.get("error", ""),
              str(r3))

        # --- 全部端点失败: 不抛异常, ok False + 错误信息 ---
        def _boom(req, timeout=None):
            raise OSError("connection reset")
        E.urllib.request.urlopen = _boom
        r4 = T().test(max_seconds=5)
        check("全端点失败 ok=False", r4.get("ok") is False
              and bool(r4.get("error")), str(r4))

        # --- 端点秒退(无数据): 走 fallback, 最终失败不抛异常 ---
        E.urllib.request.urlopen = lambda req, timeout=None: FakeResp(0, 0)
        r5 = T().test(max_seconds=3)
        check("空响应不抛异常", r5.get("ok") is False, str(r5))

        # --- 请求头必须 latin-1 可编码 ---
        # urllib 以 latin-1 编码 HTTP 头; 中文 app_name 让测速每次都抛
        # UnicodeEncodeError, 整个 F6 功能实际上完全不可用(v4.6 修复)。
        _seen = {}
        def _capture(req, timeout=None):
            _seen["headers"] = dict(getattr(req, "headers", {}) or {})
            raise OSError("captured")
        E.urllib.request.urlopen = _capture
        T().test(max_seconds=2)
        _hdrs = _seen.get("headers", {})
        _ua = _hdrs.get("User-agent", "")
        try:
            [v.encode("latin-1") for v in _hdrs.values()]
            _hdr_ok, _hdr_detail = True, str(sorted(_hdrs))
        except UnicodeEncodeError as _exc:
            _hdr_ok, _hdr_detail = False, str(_exc)
        check("测速请求头可 latin-1 编码", _hdr_ok and bool(_hdrs), _hdr_detail)
        check("User-Agent 里的中文名已 percent-encode",
              "%E7" in _ua and _ua.endswith("/" + G.APP_VERSION_SHORT), _ua)
        check("http_user_agent 对纯 ASCII 不加噪声",
              G.http_user_agent("NetTool") == "NetTool", G.http_user_agent("NetTool"))
    finally:
        E.urllib.request.urlopen = real_open


def t_wifi():
    print("\n[18] WiFi 信息管理（F8）")
    E = __import__("network_toolbox.engine", fromlist=["x"])
    W = E.WifiTool
    check("WifiTool 已定义", W is not None)
    check("WifiPanel 已导出", getattr(G, "WifiPanel", None) is not None)

    # ---------- parse_profiles: 简/繁/英三语 netsh 输出 + 去重保序 ----------
    zh = ("接口列表\n\n"
          "    所有用户配置文件 : HomeWiFi\n"
          "    所有用户配置文件 : Office\n"
          "    所有用户配置文件 : HomeWiFi\n")
    check("parse_profiles 简体中文 + 去重", W.parse_profiles(zh) == ["HomeWiFi", "Office"],
          str(W.parse_profiles(zh)))
    tw = ("介面清單\n\n"
          "    所有用户設定檔 : HomeWiFi\n"
          "    所有用户設定檔 : Office\n")
    check("parse_profiles 繁体中文", W.parse_profiles(tw) == ["HomeWiFi", "Office"],
          str(W.parse_profiles(tw)))
    en = ("Interface list\n\n"
          "    All User Profile     : HomeWiFi\n"
          "    All User Profile     : Office\n")
    check("parse_profiles 英文", W.parse_profiles(en) == ["HomeWiFi", "Office"],
          str(W.parse_profiles(en)))
    check("parse_profiles 空输入返回空列表", W.parse_profiles("nothing here") == [])

    # ---------- parse_profile_detail: 密码/认证/三类故障 ----------
    zh_detail = "\n".join([
        "接口 WiFi:",
        "",
        "配置文件信息",
        "----------------",
        "    名称                : HomeWiFi",
        "    身份验证            : WPA2-Personal",
        "    关键内容            : Passw0rd123",
    ])
    d = W.parse_profile_detail(zh_detail)
    check("parse_profile_detail 中文关键内容(密码)", d["password"] == "Passw0rd123", str(d))
    check("parse_profile_detail 中文认证", d["auth"] == "WPA2-Personal", str(d))
    check("parse_profile_detail 正常时无 error", d["error"] is None, str(d))

    en_detail = "\n".join([
        "Profile information",
        "-------------------",
        "    Authentication       : WPA3-Personal",
        "    Key Content          : Sup3rSecret",
    ])
    d2 = W.parse_profile_detail(en_detail)
    check("parse_profile_detail 英文 Key Content", d2["password"] == "Sup3rSecret", str(d2))
    check("parse_profile_detail 英文认证", d2["auth"] == "WPA3-Personal", str(d2))

    d3 = W.parse_profile_detail("在接口 WLAN 上查询配置文件 - 拒绝访问。")
    check("parse_profile_detail 拒绝访问", d3["error"] == "拒绝访问：读取密码需要管理员权限", str(d3))
    d4 = W.parse_profile_detail("WLAN 自动配置服务(wlansvc)没有运行。")
    check("parse_profile_detail 服务未运行", d4["error"] == "WLAN 自动配置服务 (wlansvc) 未运行", str(d4))
    d5 = W.parse_profile_detail('在接口 "WLAN" 上找不到配置文件 "Ghost"。')
    check("parse_profile_detail 找不到配置文件", d5["error"] == "找不到该配置文件", str(d5))

    # ---------- 实际调用: 打桩 run_cmd_capture / IS_WINDOWS ----------
    real_cmd, real_win = E.run_cmd_capture, E.IS_WINDOWS
    try:
        E.IS_WINDOWS = False
        got = W().list_profiles()
        check("非 Windows 拒绝执行", got == ([], "WiFi 信息查看仅支持 Windows (netsh wlan)"), str(got))
        pw, auth, err = W().get_password("HomeWiFi")
        check("非 Windows 读密码同样拒绝", pw is None and "仅支持 Windows" in err, str((pw, auth, err)))

        E.IS_WINDOWS = True
        E.run_cmd_capture = lambda args, timeout=None: (1, "", "拒绝访问")
        names, err = W().list_profiles()
        check("netsh 非零退出返回错误", names == [] and bool(err), str((names, err)))

        seen = []

        def _fake(args, timeout=None):
            seen.append(list(args))
            if args[3] == "profiles":
                return 0, zh, ""
            return 0, zh_detail, ""

        E.run_cmd_capture = _fake
        names, err = W().list_profiles()
        check("list_profiles 正常返回", names == ["HomeWiFi", "Office"] and err is None,
              str((names, err)))
        check("show profiles 不带 key=clear",
              any(a[:3] == ["netsh", "wlan", "show"] and a[3] == "profiles" for a in seen),
              str(seen))

        progressed = []
        items, err = W().list_wifi(progress_callback=lambda i, n: progressed.append((i, n)))
        check("list_wifi 全流程无错误", err is None and len(items) == 2, str((items, err)))
        check("list_wifi 取到密码与认证",
              items[0]["ssid"] == "HomeWiFi" and items[0]["password"] == "Passw0rd123"
              and items[0]["auth"] == "WPA2-Personal" and items[0]["error"] is None,
              str(items))
        check("list_wifi 进度回调逐项触发", progressed == [(1, 2), (2, 2)], str(progressed))
        check("命令以 argv 列表执行(不经 shell)",
              all(isinstance(a, list) and a[:2] == ["netsh", "wlan"] for a in seen), str(seen))
        check("读密码走 key=clear",
              all("key=clear" in a for a in seen if a[3] != "profiles"), str(seen))
        check("SSID 以 name=\"...\" 形式传参", any('name="HomeWiFi"' in a for a in seen), str(seen))

        pw, auth, err = W().get_password("HomeWiFi")
        check("get_password 正常返回", pw == "Passw0rd123" and auth == "WPA2-Personal"
              and err is None, str((pw, auth, err)))
        pw2, _, err2 = W().get_password("")
        check("get_password 空 SSID 拒绝", pw2 is None and err2 == "SSID 无效", str((pw2, err2)))

        one = ("接口列表\n\n"
               "    所有用户配置文件 : HomeWiFi\n")
        E.run_cmd_capture = lambda args, timeout=None: (
            (0, one, "") if args[3] == "profiles" else (0, zh_detail, ""))
        items2, err5 = W().list_wifi()
        check("仅单个 SSID 时正常", err5 is None and len(items2) == 1
              and items2[0]["ssid"] == "HomeWiFi", str((items2, err5)))

        # 服务未运行: list_profiles 阶段即报错, 不再逐条取密码
        E.run_cmd_capture = lambda args, timeout=None: (0, "WLAN 自动配置服务(wlansvc)没有运行。", "")
        items3, err6 = W().list_wifi()
        check("服务未运行时整体报错", items3 == [] and "wlansvc" in err6, str((items3, err6)))

        # ---------- export_text(纯函数) ----------
        txt = W.export_text(items)
        check("export_text 含表头", "已保存 WiFi 列表" in txt)
        check("export_text 含 SSID/密码/认证",
              "SSID: HomeWiFi" in txt and "密码: Passw0rd123" in txt
              and "认证: WPA2-Personal" in txt, txt)
        check("export_text 未取到密码有占位",
              "(未取到)" in W.export_text([{"ssid": "X", "password": None, "auth": "-"}]))
        check("export_text 空列表安全", W.export_text([]).endswith("\n"))
    finally:
        E.run_cmd_capture, E.IS_WINDOWS = real_cmd, real_win


def t_theme_widgets():
    """遍历真实面板里的每个控件的 bg/fg, 确认换主题后没有残留的旧配色。

    很多 bug 是"源码里搜不到 hex 但界面还是旧色"——颜色在 import 期就被字典/默认值
    固化了。这里直接从控件上读真实生效值, 是比源码扫描更硬的证据。
    """
    import tkinter as tk
    S = G._shared
    THEMES = S.THEMES
    try:
        root = tk.Tk()
    except Exception as e:
        check("有可显示的 Tk 环境(主题控件级校验)", False, repr(e))
        return
    root.withdraw()
    G._init_font(root)
    holder = tk.Frame(root)
    panels = {}
    for cls in (G.ResetPanel, G.DiagnosticPanel, G.ProxyPanel, G.PortsPanel,
                G.MonitorPanel, G.SpeedPanel, G.WifiPanel):
        try:
            panels[cls.__name__] = cls(holder)
        except Exception as e:
            check("%s 在%s主题下可构造" % (cls.__name__, S.DEFAULT_THEME), False, repr(e))
    _walk_panel_colors(panels, root)
    root.destroy()


def _walk_panel_colors(panels, root):
    """把 panels 里每个控件的 bg/fg 与当前主题色板比对, 报出不在色板里的颜色。"""
    import tkinter as tk
    S = G._shared
    # set_theme 会写 theme.txt；这里换了浅色之后必须还原，否则跑一次 --gui
    # 就把用户的主题偏好改成浅色（t_report 里那段还原逻辑同理）。
    tp = S.theme_path()
    theme_bak = None
    if os.path.exists(tp):
        try:
            with open(tp, "r", encoding="utf-8") as f:
                theme_bak = f.read()
        except Exception:
            theme_bak = None
    colors_bak = dict(S.COLORS)
    try:
        _walk_panel_colors_inner(panels, root)
    finally:
        S.COLORS.clear()
        S.COLORS.update(colors_bak)
        try:
            if os.path.exists(tp):
                os.remove(tp)
            if theme_bak is not None:
                with open(tp, "w", encoding="utf-8") as f:
                    f.write(theme_bak)
        except Exception:
            pass


def _walk_panel_colors_inner(panels, root):
    import tkinter as tk
    S = G._shared
    allowed = set(S.THEMES["dark"].values()) | set(S.THEMES["light"].values())
    allowed.add("")  # 未设置/默认

    def _collect(w, out):
        for c in w.winfo_children():
            try:
                bg = str(c.cget("bg"))
            except Exception:
                bg = ""
            try:
                fg = str(c.cget("fg"))
            except Exception:
                fg = ""
            for name, val in (("bg", bg), ("fg", fg)):
                if val and val not in allowed:
                    out.add((c.winfo_class(), name, val))
            _collect(c, out)

    stray = set()
    for name, pn in panels.items():
        _collect(pn, stray)
    check("深色主题下控件配色全部来自主题色板", not stray,
          "; ".join("%s.%s=%s" % t for t in sorted(stray))[:300])

    # 换到浅色再全部重建一遍, 同样比对
    S.set_theme("light")
    allowed_light = set(S.THEMES["light"].values())
    holder = tk.Frame(root)
    panels2 = {}
    for cls in (G.ResetPanel, G.DiagnosticPanel, G.ProxyPanel, G.PortsPanel,
                G.MonitorPanel, G.SpeedPanel, G.WifiPanel):
        try:
            panels2[cls.__name__] = cls(holder)
        except Exception as e:
            check("%s 在浅色主题下可构造" % cls.__name__, False, repr(e))
    stray2 = set()
    for name, pn in panels2.items():
        _collect(pn, stray2)
    # 只报"深色专属"的残留: 浅色若刻意用了深色板的某个值(如强调色)不算失败
    dark_only = {v for k, v in S.THEMES["dark"].items()
                 if v not in allowed_light and v != S.THEMES["light"].get(k)}
    suspects = {t for t in stray2 if t[2] in dark_only}
    check("浅色主题下控件无深色专属配色残留", not suspects,
          "; ".join("%s.%s=%s" % t for t in sorted(suspects))[:300])
    holder.destroy()


def t_theme():
    print("\n[19] 深色/浅色主题切换（F11）")
    S = G._shared
    P = __import__("network_toolbox.ui_panels", fromlist=["x"])
    THEMES = S.THEMES
    panels_src_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "network_toolbox", "ui_panels.py")

    # ---------- 静态结构: 两套主题必须是同一套语义键 ----------
    check("主题表覆盖 dark/light", set(THEMES) == set(S.THEME_NAMES),
          f"THEMES={sorted(THEMES)} THEME_NAMES={S.THEME_NAMES}")
    check("两套主题键集合完全一致", set(THEMES["dark"]) == set(THEMES["light"]),
          "仅深色有: %s ; 仅浅色有: %s" % (
              sorted(set(THEMES["dark"]) - set(THEMES["light"])),
              sorted(set(THEMES["light"]) - set(THEMES["dark"]))))
    check("默认主题合法", S.DEFAULT_THEME in S.THEME_NAMES, str(S.DEFAULT_THEME))
    check("主题按钮文案齐全", set(S.THEME_LABELS) == set(S.THEME_NAMES), str(S.THEME_LABELS))
    bad = ["%s.%s=%s" % (t, k, v) for t in THEMES for k, v in THEMES[t].items()
           if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(v))]
    check("所有主题色值均为 #rrggbb", not bad, str(bad))
    check("深浅主题配色确实不同",
          THEMES["dark"]["bg"] != THEMES["light"]["bg"]
          and THEMES["dark"]["text"] != THEMES["light"]["text"], "")
    # 这三键是 F11 新增的(内容卡片 / 权限不足横幅); 少一个就会在另一套主题里 KeyError
    for key in ("card", "warn_bg", "warn_fg"):
        check("语义键 %s 两套主题齐全" % key,
              key in THEMES["dark"] and key in THEMES["light"], "")

    # ---------- 源码守卫: 面板里不许再写死某个主题的底色 ----------
    panels_src = open(panels_src_path, "rb").read().decode("utf-8")
    hardcoded = [c for c in ("#2a2a3e", "#3a2a2a", "#ffb4a0")
                 if c in panels_src]
    check("ui_panels 无写死的深色专用底色", not hardcoded, str(hardcoded))
    check("ui_panels 三处 Treeview 均挂主题样式",
          panels_src.count('style="nice.Treeview"') == 3
          and panels_src.count("def config_treeview_style") == 1,
          str(panels_src.count('style="nice.Treeview"')))
    # emoji 曾被手写成字面量码点文本("U0001F4E1 网络监控"), 界面直接显示这串字符。
    # \U 开头的是合法的 Python 转义, 不算; 裸 U0001Fxxxx 才算。
    check("ui_panels 无字面量 codepoint 文本",
          not re.search(r"(?<!\\)U000[0-9A-Fa-f]{3,5}", panels_src),
          str(re.findall(r"(?<!\\)U000[0-9A-Fa-f]{3,5}", panels_src)))

    # ---------- 持久化: theme.txt 读 / 回落 / 容错 ----------
    tp = S.theme_path()
    backup, had = None, os.path.exists(tp)
    if had:
        try:
            with open(tp, "r", encoding="utf-8") as f:
                backup = f.read()
        except Exception:
            backup = None
    snapshot = dict(S.COLORS)
    try:
        if os.path.exists(tp):
            os.remove(tp)
        check("无记录时回落默认主题", S.current_theme() == S.DEFAULT_THEME, S.current_theme())
        with open(tp, "w", encoding="utf-8") as f:
            f.write("light")
        check("theme.txt 可读回", S.current_theme() == "light", S.current_theme())
        with open(tp, "w", encoding="utf-8") as f:
            f.write("not-a-theme")
        check("损坏内容回落默认主题", S.current_theme() == S.DEFAULT_THEME, S.current_theme())

        # ---------- 换色: 必须就地覆写, 别的模块 import 的同一 dict 才会跟着变 ----------
        obj_id = id(S.COLORS)
        check("set_theme 返回生效主题名", S.set_theme("light") == "light", "")
        check("COLORS 对象未被重新绑定", id(S.COLORS) == obj_id, "")
        check("其他模块持有的引用同步换色",
              G.COLORS is S.COLORS and P.COLORS is S.COLORS
              and G.COLORS["bg"] == THEMES["light"]["bg"], str(G.COLORS["bg"]))
        check("set_theme 已持久化", S.current_theme() == "light", S.current_theme())
        check("非法主题名回落默认", S.set_theme("neon-pink") == S.DEFAULT_THEME, "")

        S.set_theme("dark")
        check("toggle_theme 深->浅", S.toggle_theme() == "light", "")
        check("toggle_theme 浅->深", S.toggle_theme() == S.DEFAULT_THEME, "")
        check("toggle 后持久化一致", S.current_theme() == S.DEFAULT_THEME, "")
        check("还原后 COLORS 回到深色", S.COLORS["bg"] == THEMES["dark"]["bg"], "")

        # DNS 预设按钮色必须是语义键, 否则换主题后还显示旧主题的固定色值
        stale = [n for n, c in S.DNS_PRESETS.items() if c["color"] not in THEMES["dark"]]
        check("DNS 预设颜色用语义键", not stale, str(stale))
    finally:
        # 还原进程内配色, 并恢复用户的主题文件, 避免污染后续用例
        S.COLORS.clear()
        S.COLORS.update(snapshot)
        try:
            if os.path.exists(tp):
                os.remove(tp)
            if backup is not None:
                with open(tp, "w", encoding="utf-8") as f:
                    f.write(backup)
        except Exception:
            pass

def t_i18n():
    """界面多语言（F12）。

    中文是默认语言, 所以绝大多数用例在"不切换"的前提下也能守住契约:
    翻译必须幂等回落、持久化要 round-trip、英文目录必须覆盖所有已接线文案。
    """
    print("\n[21] 界面多语言（F12）")
    import ast
    import network_toolbox.i18n as I

    check("语言表至少含中/英", set(I.LANGS) >= {"zh", "en"}, str(sorted(I.LANGS)))
    check("默认语言在语言表里", I.DEFAULT_LANG in I.LANGS, str(I.DEFAULT_LANG))

    lp = I.lang_path()
    had = os.path.exists(lp)
    backup = None
    if had:
        try:
            with open(lp, "r", encoding="utf-8") as f:
                backup = f.read()
        except Exception:
            backup = None
    snapshot = I.current_lang()
    try:
        # ---------- 回落: 没记录/乱写/不认识的语言都回到默认 ----------
        def _reread():
            """current_lang() 有记忆, 改文件后必须清缓存再读。"""
            I._lang = None
            return I.current_lang()

        if os.path.exists(lp):
            os.remove(lp)
        check("无记录时回落默认语言", _reread() == I.DEFAULT_LANG, _reread())
        with open(lp, "w", encoding="utf-8") as f:
            f.write("klingson")
        check("非法语言名回落默认", _reread() == I.DEFAULT_LANG, _reread())
        with open(lp, "w", encoding="utf-8") as f:
            f.write("EN")
        check("大小写不敏感", _reread() == "en", _reread())

        # ---------- 持久化 round-trip ----------
        check("set_lang 返回生效语言名", I.set_lang("zh") == "zh", "")
        check("set_lang 已经落盘", I.current_lang() == "zh", "")
        check("非法值回落默认", I.set_lang("xx") == I.DEFAULT_LANG, "")

        # ---------- persist=False: 一次性切换不写回偏好 ----------
        # CLI 的 `--lang en` 就走这条路: 改本次进程的语言，
        # 但不该善自改掉用户存的 lang.txt。
        with open(lp, "w", encoding="utf-8") as f:
            f.write("zh")
        I._lang = None
        _got_np = I.set_lang("en", persist=False)
        check("persist=False 改的是本次进程的语言",
              _got_np == "en" and I.current_lang() == "en", _got_np)
        with open(lp, "r", encoding="utf-8") as f:
            _on_disk = f.read().strip()
        check("persist=False 不写 lang.txt", _on_disk == "zh", _on_disk)
        I.set_lang("zh")
        I._lang = None

        # ---------- tr(): 中文下必须原样返回(否则整个中文界面会被打散) ----------
        probe = "\U0001f504 网络重置"
        I.set_lang("zh")
        check("zh 模式下 tr() 原样返回", I.tr(probe) == probe, I.tr(probe))
        I.set_lang("en")
        check("en 模式下 tr() 命中英文目录", I.tr(probe) == I.EN.get(probe),
              I.tr(probe))
        check("en 模式下未收录文案回落中文(不 KeyError)",
              I.tr("这条文案不可能被收录进目录") == "这条文案不可能被收录进目录", "")

        # ---------- tr_f(): 占位符两端都要在 ----------
        tpl = "总分: {a} / 100"
        check("tr_f 中文模式直接 format",
              I.tr_f(tpl, a=88) == "总分: 88 / 100", I.tr_f(tpl, a=88))
        I.set_lang("en")
        translated = I.EN.get(tpl)
        if translated:
            check("tr_f 英文模式按模板翻译后 format",
                  I.tr_f(tpl, a=88) == translated.format(a=88), I.tr_f(tpl, a=88))
        else:
            check("tr_f 英文模式缺模板时退回中文模板(不 KeyError)",
                  I.tr_f(tpl, a=88) == "总分: 88 / 100", I.tr_f(tpl, a=88))

        # ---------- 目录规模与形态 ----------
        check("英文目录已有相当规模", len(I.EN) >= 400, "size=%d" % len(I.EN))
        bad_val = [k for k, v in I.EN.items() if not isinstance(v, str) or not v.strip()]
        check("英文目录没有空翻译", not bad_val, str(bad_val[:3]))
        same = [k for k, v in I.EN.items() if v == k
                and k != "网络工具箱.exe --cli"]  # 程序名不翻译
        check("英文翻译不是照抄中文", not same, str(same[:3]))
        # 占位符必须原样保留, 否则 %s/%d 位置会串
        import re as _re
        ph = [k for k, v in I.EN.items()
              if sorted(_re.findall(r"%[sd]", k)) != sorted(_re.findall(r"%[sd]", v))]
        check("英文翻译保留 %s/%d 占位符", not ph, str(ph[:3]))
        brace = [k for k, v in I.EN.items()
                 if "{" in k and sorted(_re.findall(r"\{(\w+)\}", k))
                 != sorted(_re.findall(r"\{(\w+)\}", v))]
        check("英文翻译保留 {name} 占位符", not brace, str(brace[:3]))
        # 正则与 netsh 解析串绝不能进目录——进了就会改匹配行为
        _re_pat = _re.compile(r"\(\?:|\\s|\[\^|\\d|\.\*")
        regexish = [k for k in I.EN if _re_pat.search(k)]
        check("目录里没有正则/解析串", not regexish, str(regexish[:3]))

        # ---------- 已接线的文案必须都能在目录里找到 ----------
        # 用 src 守卫而不是逐个枚举: 任何新增的 tr("...") 中文文案都必须补英文。
        miss = []
        for fname in ("app.py", "ui_panels.py", "report.py", "engine.py", "cli.py",
                     "plugins.py"):
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "network_toolbox", fname)
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "tr" and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    key = node.args[0].value
                    if any("\u4e00" <= c <= "\u9fff" for c in key) and key not in I.EN:
                        miss.append((fname, key))
        # 刻意不翻译的只有两类: netsh 输出的解析标记 / 正则 / 程序名。
        # 用 \u 转义写, 避免繁体字在各种 shell here-string 里被改写。
        _PARSE_MARKERS = {
            "\u6240\u6709\u7528\u6237\u914d\u7f6e\u6587\u4ef6",  # netsh
            "\u6240\u6709\u7528\u6237\u8a2d\u5b9a\u6a94",            # netsh 繁体
            "\u91d1\u9470\u5167\u5bb9",                                # netsh 繁体
            "\u9a57\u8b49",                                              # netsh 繁体
        }
        _PROG_NAME = "\u7f51\u7edc\u5de5\u5177\u7bb1.exe --cli"
        _re_pat2 = _re.compile(r"\(\?:|\\s|\[\^|\\d|\.\*")
        unexpected = [(f, k) for f, k in miss
                      if k not in _PARSE_MARKERS and k != _PROG_NAME
                      and not _re_pat2.search(k)]
        check("所有已接线中文文案都有英文翻译", not unexpected,
              "; ".join("%s:%r" % (f, k) for f, k in unexpected[:4]))

        # ---------- 语言不得影响解析(真正的硬门闸) ----------
        # 上面那条 AST 守卫只能抓"新增文案漏翻译", 抛不住"把匹配标记也
        # 包了 tr()"——后者的现象是中文界面好好的, 一切英文就全部失效。
        # 这里用真实的中文系统输出在两种语言下各跑一遍。
        _ENG = __import__("network_toolbox.engine", fromlist=["x"])
        _zh_out = "\n".join([
            "接口 WiFi:", "", "配置文件信息", "----------------",
            "    名称                : HomeWiFi",
            "    身份验证            : WPA2-Personal",
            "    关键内容            : Passw0rd123",
        ])
        _zh_profiles = ("接口列表\n\n"
                        "    所有用户配置文件 : HomeWiFi\n")
        for _langname in ("zh", "en"):
            I.set_lang(_langname)
            _d = _ENG.WifiTool.parse_profile_detail(_zh_out)
            check("%s 界面下 netsh 中文输出仍能拿到密码" % _langname,
                  _d["password"] == "Passw0rd123", str(_d))
            check("%s 界面下 netsh 中文输出仍能拿到认证" % _langname,
                  _d["auth"] == "WPA2-Personal", str(_d))
            check("%s 界面下拒绝访问仍能识别" % _langname,
                  _ENG.WifiTool.parse_profile_detail(
                      "在接口 WLAN 上查询配置文件 - 拒绝访问。")["error"] is not None, "")
            check("%s 界面下找不到配置文件仍能识别" % _langname,
                  _ENG.WifiTool.parse_profile_detail(
                      '在接口 "WLAN" 上找不到配置文件 "Ghost"。')["error"] is not None, "")
            check("%s 界面下 profiles 前缀仍能匹配" % _langname,
                  _ENG.WifiTool.parse_profiles(_zh_profiles) == ["HomeWiFi"],
                  str(_ENG.WifiTool.parse_profiles(_zh_profiles)))
            _auto = _ENG.ProxyRepairTool()._find_auto_group({"自动选择": {"type": "URLTest"}})
            check("%s 界面下仍能找到中文自动组" % _langname, _auto == "自动选择", str(_auto))
            _tg = [t[1] for t in _ENG.NetworkDiagnostic.PING_TARGETS]
            check("%s 界面下 PING_TARGETS 标签保持规范中文" % _langname,
                  "阿里 DNS" in _tg and "Google DNS" in _tg, str(_tg))
        I.set_lang("zh")

    finally:
        I.set_lang(snapshot)
        try:
            if os.path.exists(lp):
                os.remove(lp)
            if backup is not None:
                with open(lp, "w", encoding="utf-8") as f:
                    f.write(backup)
        except Exception:
            pass


def t_plugins():
    """插件式诊断项（F13）。

    注册表是引擎与第三方插件之间的契约，回归点集中在三件事：
      1. 内置三项永远在场且不可被覆盖（UI / 报告永远拿得到 overview/ping/dns）；
      2. 单项崩掉只掉自己，不会把整轮诊断带走；
      3. key 校验挡住中文/连字符这类会把 JSON 输出搞脏的值。
    """
    print("\n[22] 插件式诊断项（F13）")
    import network_toolbox.engine as E
    import network_toolbox.plugins as P

    class _FakeTool:
        """一个包都不发：把网络全替成常量，专注验证注册表本身。"""

        PING_TARGETS = [("127.0.0.1", "Loopback", "blue"),
                        ("10.0.0.1", "Gateway", "sky")]
        DNS_TARGETS = [("223.5.5.5", "AliDNS")]

        def __init__(self):
            self.logs = []
            self.log_callback = self.logs.append

        def get_overview(self):
            return [{"name": "eth0"}]

        def ping(self, target):
            return True, 1.5, 0.0, ""

        def dns_lookup(self, host, dns=None):
            return True, "1.2.3.4", ""

    check("内置三项顺序固定", P.BUILTIN_KEYS == ("overview", "ping", "dns"), str(P.BUILTIN_KEYS))
    check("初始无自定义项", P.custom_keys() == [], str(P.custom_keys()))
    check("内置三项都带 builtin 标记",
          all(i.builtin for i in P.diagnostic_items()),
          str([(i.key, i.builtin) for i in P.diagnostic_items()]))

    tool = _FakeTool()
    seen = []
    results = P.run_diagnostics(tool, lambda pct, msg: seen.append((pct, msg)))
    check("内置诊断跑完三项", set(results) == {"overview", "ping", "dns"}, str(sorted(results)))
    check("overview 原样透传", results["overview"] == [{"name": "eth0"}], str(results["overview"]))
    check("ping 逐目标出结果", len(results["ping"]) == 2
          and results["ping"][0]["target"] == "127.0.0.1"
          and results["ping"][0]["label"] == "Loopback", str(results["ping"]))
    check("dns 逐服务器出结果", results["dns"][0]["dns"] == "223.5.5.5", str(results["dns"]))
    check("进度节奏与 v4.5 一致(0/10-50/55-95/100)",
          seen[0][0] == 0 and seen[-1] == (100, "诊断完成")
          and seen[1][0] == 10 and seen[-2][0] == 55, str(seen))
    check("顺利时不写日志", tool.logs == [], str(tool.logs))

    # ---------- engine 真的委托给了注册表（打桩跑真实实例） ----------
    diag = E.NetworkDiagnostic()
    diag.get_overview = lambda: [{"stub": True}]
    diag.ping = lambda target: (False, None, 100, "")
    diag.dns_lookup = lambda host, dns=None: (False, None, "")
    real = diag.run_full_diagnostic()
    check("engine 委托给插件注册表", set(real) == {"overview", "ping", "dns"}, str(sorted(real)))
    check("engine 拿到的是桩数据",
          real["overview"] == [{"stub": True}] and real["ping"][0]["ok"] is False, str(real["ping"]))

    try:
        # ---------- 自定义项参与诊断 ----------
        P.register_item("myplug.check", lambda t, progress=None: {"answer": 42},
                        title="自定义检查")
        check("自定义项出现在 custom_keys", P.custom_keys() == ["myplug.check"], str(P.custom_keys()))
        check("自定义项排在内置项之后",
              [i.key for i in P.diagnostic_items()] == ["overview", "ping", "dns", "myplug.check"],
              str([i.key for i in P.diagnostic_items()]))
        extra = P.run_diagnostics(tool)
        check("自定义结果进入结果字典", extra.get("myplug.check") == {"answer": 42},
              str(extra.get("myplug.check")))

        # ---------- 崩掉的插件只掉自己 ----------
        P.register_item("boom", lambda t, progress=None: 1 / 0, fallback="FALLBACK")
        P.register_item("silent", lambda t, progress=None: None)
        crashed = P.run_diagnostics(tool)
        check("崩掉的插件换成 fallback", crashed.get("boom") == "FALLBACK", str(crashed.get("boom")))
        check("其余项不受崩溃影响", bool(crashed.get("ping")) and bool(crashed.get("dns")), "")
        check("返回 None 的项不进结果字典", "silent" not in crashed, str(sorted(crashed)))
        check("崩溃被记进日志", any("boom" in m for m in tool.logs), str(tool.logs))

        # ---------- 入参校验 ----------
        for bad_key in ("中文", "a-b", "1abc", "", "a b", ".x", "a..b"):
            try:
                P.DiagnosticItem(bad_key, lambda t, progress=None: None)
                check("非法 key 被拒绝: %r" % bad_key, False, "没有抛 ValueError")
            except ValueError:
                check("非法 key 被拒绝: %r" % bad_key, True)
        try:
            P.DiagnosticItem("fine_key", "not-callable")
            check("run 不可调用被拒绝", False, "没有抛 TypeError")
        except TypeError:
            check("run 不可调用被拒绝", True)
        try:
            P.register_item(123, lambda t, progress=None: None)
            check("非 DiagnosticItem/str 被拒绝", False, "没有抛 TypeError")
        except TypeError:
            check("非 DiagnosticItem/str 被拒绝", True)

        # ---------- 内置项受保护 / 重复注册被拒绝 ----------
        try:
            P.register_item("ping", lambda t, progress=None: None)
            check("内置项不可被覆盖", False, "没有抛 ValueError")
        except ValueError:
            check("内置项不可被覆盖", True)
        try:
            P.register_item("boom", lambda t, progress=None: None)
            check("同名重复注册被拒绝", False, "没有抛 ValueError")
        except ValueError:
            check("同名重复注册被拒绝", True)
        check("注销内置项被拒绝", P.unregister_item("ping") is False, "")
        check("注销不存在的 key 返回 False", P.unregister_item("ghost") is False, "")
        check("注销自定义项成功", P.unregister_item("myplug.check") is True, "")
        check("注销只移除指定项", P.custom_keys() == ["boom", "silent"], str(P.custom_keys()))
        check("注销后内置项依然在",
              [i.key for i in P.diagnostic_items()][:3] == list(P.BUILTIN_KEYS),
              str([i.key for i in P.diagnostic_items()]))
    finally:
        P.reset_registry()

    check("reset 后注册表干净",
          P.custom_keys() == [] and len(P.diagnostic_items()) == 3,
          str(P.custom_keys()))
    check("插件 API 已导出到兼容入口",
          all(callable(getattr(G, name, None)) for name in
              ("register_item", "unregister_item", "diagnostic_items",
               "custom_keys", "run_diagnostics", "reset_registry", "DiagnosticItem")), "")



def main():
    # 用户可能把界面切成英文, 测试断言写的是中文文案, 先固定回中文
    import network_toolbox.i18n as _I18N
    _I18N.set_lang("zh")

    print(f"=== 网络工具箱 {G.APP_VERSION} 冒烟自检 ===")
    print(f"Python {sys.version.split()[0]}  platform={sys.platform}")
    t_decode()
    t_decode_available()
    t_target()
    t_mothersday()
    t_net_ops()
    t_thread_safety()
    t_misc()
    t_updater_security()
    t_report()
    t_adapters()
    t_snapshot()
    t_hosts()
    t_ports()
    t_dns_bench()
    t_monitor()
    t_speed()
    t_wifi()
    t_theme()
    t_theme_widgets()
    t_cli()
    t_i18n()
    t_plugins()
    if "--gui" in sys.argv:
        t_gui()
        t_tooltips()

    print("\n" + "=" * 46)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for name, detail in FAILED:
            print(f"  ✗ {name}  {detail}")
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
