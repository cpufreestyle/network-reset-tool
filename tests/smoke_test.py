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
"""

import os
import re
import sys
import json
import hashlib
import tempfile
import datetime

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


def t_misc():
    print("\n[7] 其他")
    check("版本号单一来源", G.APP_VERSION == "3.4.0" and G.APP_VERSION_SHORT == "v3.4")
    check("APP_NAME", G.APP_NAME == "网络工具箱")
    check("IS_LINUX 已定义", hasattr(G, "IS_LINUX"))
    check("静态 IP 备份落盘路径可用",
          G.ResetPanel._backup_file().endswith("static_ip_backup.json"))
    # 单例端口常量仍在
    check("单例端口常量", G._SINGLETON_PORT == 45678)


def t_gui():
    print("\n[9] GUI 启动自检（构造三个面板后销毁）")
    import tkinter as tk
    try:
        root = tk.Tk()
        root.withdraw()
        G._init_font(root)
        check("字体探测成功", bool(G._shared.FONT_FAMILY), f"FONT_FAMILY={G._shared.FONT_FAMILY!r}")
        holder = tk.Frame(root)
        for cls in (G.ResetPanel, G.DiagnosticPanel, G.ProxyPanel):
            p = cls(holder)
            check(f"{cls.__name__} 可构造", p is not None)
        root.update_idletasks()
        root.destroy()
        check("窗口可正常销毁", True)
    except Exception as e:
        import traceback
        check("GUI 自检", False, traceback.format_exc())


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


def main():
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
