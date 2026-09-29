# -*- coding: utf-8 -*-
"""插件式诊断项（F13）。

把"完整诊断"拆成一组可注册的诊断项：内置 overview / ping / dns 三项由本模块提供，
`NetworkDiagnostic.run_full_diagnostic` 只负责按注册顺序驱动它们。
第三方（或后续版本）只要 `register_item()` 追加自己的检查，不用改 engine.py。

协议（故意保持极简，方便第三方照抄）：
  * `run(tool, progress=None)`：tool 是 NetworkDiagnostic 实例；
    progress 是 `progress(pct, msg) -> None`，也可能是 None。
  * 返回 None = 这项没有数据，结果字典里不出现该 key；
    返回其它任意可 JSON 化的值都会写进 results[item.key]。
  * run 抛异常不会炸掉整轮诊断：记一条日志，用该项的 fallback 顶上。

两条写死的不变量（UI / 报告生成器依赖它们，所以在这里强制）：
  * 内置项 key（BUILTIN_KEYS）不允许被插件覆盖或注销，诊断结果永远带
    overview / ping / dns 三个字段；
  * key 必须是 ASCII 标识符（可用点号分段做命名空间，如 myplug.check），
    既不会和内置项撞名，也让 JSON / 命令行输出安全。

本模块只依赖 network_toolbox.i18n，不 import engine —— 否则 engine 反过来
import 本模块就成循环依赖了。
"""
import re

from network_toolbox.i18n import tr

#: 内置诊断项的顺序即它们在结果字典 / 报告里的展示顺序。
BUILTIN_KEYS = ("overview", "ping", "dns")

# 点号允许做命名空间(myplug.check), 每段仍需是 ASCII 标识符；中文/连字符/空格全部拒绝。
_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


class DiagnosticItem(object):
    """一条诊断项。

    - key:      结果字典里的键，ASCII 标识符（点号分段）
    - run:       `run(tool, progress=None)`，返回该项数据（None = 无数据）
    - title:     给人看的名字（日志里会走 tr()，所以照中文原文写即可）
    - fallback:  run 抛异常时顶上的值
    - builtin:   是否内置项（内置项不可覆盖、不可注销）
    """

    __slots__ = ("key", "run", "title", "fallback", "builtin")

    def __init__(self, key, run, title="", fallback=None, builtin=False):
        if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
            raise ValueError(
                "诊断项 key 必须是 ASCII 标识符(字母/下划线开头, 点号分段): %r" % (key,))
        if not callable(run):
            raise TypeError("诊断项 %r 的 run 必须可调用: %r" % (key, run))
        self.key = key
        self.run = run
        self.title = title or key
        self.fallback = fallback
        self.builtin = bool(builtin)

    def __repr__(self):
        return "<DiagnosticItem %s%s>" % (self.key, " (builtin)" if self.builtin else "")


_REGISTRY = []       # 自定义诊断项，按注册顺序
_BUILTIN_ITEMS = {}  # key -> DiagnosticItem，内置项只读，插件碰不到


def _log(tool, msg):
    """往工具实例的日志回调写一行；没有回调或回调自己炸了都不影响诊断。"""
    callback = getattr(tool, "log_callback", None)
    if not callback:
        return
    try:
        callback(msg)
    except Exception:
        pass


def register_item(item, run=None, title="", fallback=None):
    """注册一条诊断项，返回注册后的 DiagnosticItem。

    `item` 既可以是 DiagnosticItem，也可以是字符串 key（此时必须给 run，
    等价于 `register_item(DiagnosticItem(key, run, title=title,
    fallback=fallback))`）。重复注册同名项、或企图覆盖内置项都抛 ValueError。
    """
    if isinstance(item, str):
        item = DiagnosticItem(item, run, title=title, fallback=fallback)
    if not isinstance(item, DiagnosticItem):
        raise TypeError("register_item() 需要 DiagnosticItem 或字符串 key: %r" % (item,))
    if item.key in BUILTIN_KEYS or item.key in _BUILTIN_ITEMS:
        raise ValueError("内置诊断项 %r 不允许覆盖或重复注册" % item.key)
    for existing in _REGISTRY:
        if existing.key == item.key:
            raise ValueError("诊断项 %r 已经注册过了" % item.key)
    _REGISTRY.append(item)
    return item


def unregister_item(key):
    """注销一条自定义诊断项；内置项受保护，返回 False。未注册的 key 也返回 False。"""
    if key in BUILTIN_KEYS or key in _BUILTIN_ITEMS:
        return False
    for index, item in enumerate(_REGISTRY):
        if item.key == key:
            del _REGISTRY[index]
            return True
    return False


def diagnostic_items():
    """所有生效的诊断项：内置三项在前，自定义项按注册顺序在后。"""
    items = [_BUILTIN_ITEMS[k] for k in BUILTIN_KEYS if k in _BUILTIN_ITEMS]
    items.extend(_REGISTRY)
    return items


def custom_keys():
    """自定义（第三方/插件）诊断项的 key，按注册顺序。"""
    return [item.key for item in _REGISTRY]


def reset_registry():
    """清空自定义诊断项（内置项不受影响）。测试用它隔离用例。"""
    del _REGISTRY[:]


def run_diagnostics(tool, progress_callback=None):
    """按注册顺序跑完所有诊断项，返回 {key: 结果}。

    单项抛异常不会中断整轮诊断：写一条日志并用该项的 fallback 顶上 ——
    第三方插件写得再糙，也不会让"诊断"按钮整体失灵。
    """
    results = {}
    for item in diagnostic_items():
        try:
            value = item.run(tool, progress_callback)
        except Exception as exc:
            _log(tool, tr("诊断项 %s 失败: %s") % (tr(item.title), exc))
            value = item.fallback
        if value is not None:
            results[item.key] = value
    if progress_callback:
        progress_callback(100, tr("诊断完成"))
    return results


def _run_overview(tool, progress=None):
    """内置项 overview：网络状态总览。失败返回 []，与 v4.5 及以前一致。"""
    if progress:
        progress(0, tr("获取网络状态..."))
    try:
        return tool.get_overview()
    except Exception as exc:
        _log(tool, tr("获取网络状态失败: %s") % exc)
        return []


def _run_ping(tool, progress=None):
    """内置项 ping：对 PING_TARGETS 逐个 ping，进度占 10%~50%。"""
    rows = []
    targets = tool.PING_TARGETS
    total = len(targets) or 1
    for i, (target, label, color) in enumerate(targets):
        label = tr(label)
        if progress:
            progress(int((i / total) * 40) + 10, "Ping %s..." % label)
        try:
            ok, avg_ms, loss, _ = tool.ping(target)
            rows.append({
                'target': target,
                'label': label,
                'color': color,
                'ok': ok,
                'avg_ms': avg_ms,
                'loss': loss,
            })
        except Exception as exc:
            rows.append({
                'target': target,
                'label': label,
                'color': color,
                'ok': False,
                'avg_ms': None,
                'loss': 100,
            })
            _log(tool, "Ping %s 失败: %s" % (label, exc))
    return rows


def _run_dns(tool, progress=None):
    """内置项 dns：各 DNS 服务器解析同一域名，进度占 55%~95%。"""
    rows = []
    test_host = "www.baidu.com"
    targets = tool.DNS_TARGETS
    total = len(targets) or 1
    for i, (dns, label) in enumerate(targets):
        label = tr(label)
        if progress:
            progress(55 + int((i / total) * 40), "DNS %s..." % label)
        try:
            ok, ip, _ = tool.dns_lookup(test_host, dns)
            rows.append({'dns': dns, 'label': label, 'ok': ok, 'ip': ip})
        except Exception as exc:
            rows.append({'dns': dns, 'label': label, 'ok': False, 'ip': None})
            _log(tool, "DNS %s 解析失败: %s" % (label, exc))
    return rows


# 内置三项：key 受 BUILTIN_KEYS 保护，插件永远盖不掉。
_BUILTIN_ITEMS.update({
    "overview": DiagnosticItem(
        "overview", _run_overview, title="📋 网络状态总览",
        fallback=[], builtin=True),
    "ping": DiagnosticItem(
        "ping", _run_ping, title="📡 Ping 连通性测试",
        fallback=[], builtin=True),
    "dns": DiagnosticItem(
        "dns", _run_dns, title="DNS 解析测试",
        fallback=[], builtin=True),
})
