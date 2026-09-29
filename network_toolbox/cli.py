# -*- coding: utf-8 -*-
"""命令行模式（F10）。

给批处理 / 运维脚本 / 无人值守场景用的无界面入口：

    网络工具箱.exe --cli dns --preset "阿里 DNS" --json
    python network_reset_gui.py --cli diagnose
    python network_reset_gui.py --cli ports --kill 1234

设计约束（与 GUI 复用同一套引擎，但**绝不碰 Tk**）：
- 只 import engine/report，不构造任何 Tk 控件，不弹任何对话框，
  因此在没有桌面会话的服务器 / SSH / CI 里也能跑；
- 全程不调用 messagebox / filedialog，失败一律走退出码 + stderr；
- `--json` 时 stdout 只输出一个 JSON 对象，日志全部走 stderr，
  方便 `jq` / `ConvertFrom-Json` 直接消费；
- 退出码语义固定：0 成功 / 1 操作失败 / 2 参数错误 / 3 需要管理员 / 4 平台不支持。

本项目线程安全铁律只约束 GUI：CLI 是单线程同步执行，worker 回投那套
`ui_sync` / `safe_after` 机制在此完全不涉及，也不需要。
"""
import argparse
import json
import os
import sys
import time

from network_toolbox.i18n import LANGS, current_lang, set_lang, tr, tr_f
from network_toolbox.plugins import custom_keys
from network_toolbox._shared import (
    APP_NAME,
    APP_VERSION,
    APP_VERSION_SHORT,
    IS_WINDOWS,
    is_admin,
    _release_singleton,
)
from network_toolbox.engine import (
    DNS_PRESETS,
    HostsTool,
    NetworkDiagnostic,
    NetworkMonitor,
    NetworkResetTool,
    PortTool,
    ProxyRepairTool,
    SpeedTester,
    WifiTool,
)
from network_toolbox.report import compute_health, render_report

# 退出码
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_NEED_ADMIN = 3
EXIT_UNSUPPORTED = 4


class CliError(Exception):
    """带退出码的 CLI 失败。"""

    def __init__(self, message, code=EXIT_FAILED, **extra):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra or {}


class _Result:
    """一次命令执行的结果容器。

    `ok` 是否为真决定退出码是 0 还是 1；`warnings` 只影响人类可读输出，
    不算失败——例如"非管理员启动，密码读不到"这种能力降级。
    """

    def __init__(self, command):
        self.command = command
        self.ok = True
        self.data = {}
        self.warnings = []
        self.logs = []

    def warn(self, msg):
        self.warnings.append(msg)
        self.log(msg)

    def log(self, msg):
        self.logs.append(msg)


def _lossy_streams():
    """把 stdout/stderr 的编码错误处理改成 backslashreplace。

    日志里会出现 ✓/✗/⚠/🎉/🔄 这类符号，GBK 控制台编码不了，
    直接 print 会抛 UnicodeEncodeError 把整条命令炸掉。降级成转义文本
    总比崩掉好；改的是错误处理而不是编码，所以中文照常显示。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="backslashreplace")
        except Exception:
            pass


def _emit(result, as_json, stream=None):
    """按格式输出。JSON 模式下 stdout 只有一个对象，日志走 stderr。"""
    stream = stream or sys.stderr
    if as_json:
        for line in result.logs:
            print(line, file=stream)
        payload = json.dumps({
            "ok": bool(result.ok),
            "command": result.command,
            "data": result.data,
            "warnings": result.warnings,
        }, ensure_ascii=False, indent=2)
        out = sys.stdout
        # JSON 必须按 UTF-8 落字节流：GBK 控制台下走 print 会让中文变成
        # GBK 字节，jq / 其他语言的解析器会报 invalid UTF-8。
        if hasattr(out, "buffer") and out.buffer is not None:
            out.flush()
            out.buffer.write(payload.encode("utf-8") + b"\n")
            out.buffer.flush()
        else:
            print(payload)
    else:
        for line in result.logs:
            print(line)
    return EXIT_OK if result.ok else EXIT_FAILED


# ---------------------------------------------------------------- 各子命令

def _resolve_adapter(args):
    """把 --adapter 归一成引擎需要的值；None / ADAPTER_AUTO 表示自动检测。"""
    name = getattr(args, "adapter", None)
    if not name or name == "auto":
        return None
    return name


def cmd_adapters(args, r):
    tool = NetworkResetTool(log_callback=r.log)
    items = tool.list_adapters()
    r.data = {
        "adapters": items,
        "count": len(items),
    }
    if not items:
        r.warn(tr("没有枚举到网卡（可能是权限不足或平台不支持）"))
    for it in items:
        flag = tr("  [默认网关]") if it.get("gw") else ""
        r.log(f"  {it.get('name')}{flag}")
        if it.get("ip"):
            r.log(f"      IP: {it['ip']}")
    return r


def cmd_diagnose(args, r):
    diag = NetworkDiagnostic(log_callback=r.log)
    extra = custom_keys()
    if extra:
        r.log(tr("自定义诊断项: %s") % ", ".join(extra))
    results = diag.run_full_diagnostic(
        progress_callback=lambda pct, msg: r.log(f"  [{pct:>3}%] {msg}"))
    health = compute_health(results)
    r.data = {"results": results, "health": health,
              "custom_items": extra}
    r.log("")
    # 这三行是 f-string 组装的，AST 打包器覆盖不到，必须手动 tr_f。
    r.log(tr_f("健康评分: {total} / 100  ({grade})",
               total=health["total"], grade=health["grade"]))
    r.log(tr_f("结论: {text}", text=health["conclusion"]))
    if health["total"] < 70:
        r.warn(tr_f("评分偏低({total}), 建议按结论逐项排查", total=health["total"]))
    return r


def cmd_reset(args, r):
    if not IS_WINDOWS:
        raise CliError(tr("完整网络重置仅支持 Windows"), EXIT_UNSUPPORTED)
    if not is_admin():
        raise CliError(tr("完整网络重置需要管理员权限：请以管理员身份运行"),
                       EXIT_NEED_ADMIN)
    tool = NetworkResetTool(log_callback=r.log)
    adapter = _resolve_adapter(args)
    stages = [s.strip() for s in (args.stages or "").split(",") if s.strip()]
    r.log(tr("开始完整网络重置") + (f"(仅执行: {'/'.join(stages)})" if stages else ""))
    if adapter:
        r.log(tr_f("目标网卡: {name}", name=adapter))
    if adapter:
        # 指定网卡时只做 DNS 相关步骤，避免误伤其它网卡
        tool.switch_dns(args.preset or "", adapter) if args.preset else None
    else:
        tool.run_full_reset()
    r.data = {"stages": stages or ["winsock", "tcpip", "dns", "arp", "dhcp"],
              "adapter": adapter,
              "snapshots": [os.path.basename(p) for p, _t, _n
                            in NetworkResetTool.list_snapshots(limit=1)]}
    return r


def cmd_dns(args, r):
    if not IS_WINDOWS:
        raise CliError(tr("DNS 切换仅支持 Windows"), EXIT_UNSUPPORTED)
    tool = NetworkResetTool(log_callback=r.log)
    adapter = _resolve_adapter(args)
    if args.preset:
        if args.preset not in DNS_PRESETS:
            raise CliError(tr("未知 DNS 预设: %s（可用: %s）")
                           % (args.preset, "、".join(DNS_PRESETS)),
                           EXIT_USAGE)
        ok = tool.switch_dns(args.preset, adapter)
        cur, mode = tool.get_current_dns(adapter)
        r.data = {"preset": args.preset, "ok": bool(ok),
                  "adapter": adapter, "current": cur, "mode": mode}
        if not ok:
            raise CliError(tr("切换 DNS 失败"), EXIT_FAILED)
        return r
    if args.auto:
        ok = tool.set_dhcp_dns(adapter)
        r.data = {"mode_set": "dhcp", "ok": bool(ok), "adapter": adapter}
        if not ok:
            raise CliError(tr("切回自动获取(DHCP)失败"), EXIT_FAILED)
        return r
    if args.set:
        primary = args.set[0]
        secondary = args.set[1] if len(args.set) > 1 else None
        ok = tool.set_dns(adapter, primary, secondary)
        r.data = {"primary": primary, "secondary": secondary,
                  "ok": bool(ok), "adapter": adapter}
        if not ok:
            raise CliError(tr("设置自定义 DNS 失败"), EXIT_FAILED)
        return r
    cur, mode = tool.get_current_dns(adapter)
    r.data = {"adapter": adapter, "current": cur, "mode": mode,
              "presets": sorted(DNS_PRESETS)}
    _cur = ', '.join(cur) if cur else tr("未知")
    r.log(tr_f("当前 DNS: {dns} [{mode}]", dns=_cur, mode=mode))
    return r


def cmd_ports(args, r):
    tool = PortTool()
    items = tool.list_listening()
    if args.kill:
        if not (IS_WINDOWS or os.name == "posix"):
            raise CliError(tr("当前平台不支持结束进程"), EXIT_UNSUPPORTED)
        if not is_admin():
            raise CliError(tr("结束进程需要管理员权限：请以管理员身份运行"),
                           EXIT_NEED_ADMIN)
        ok, msg = tool.kill_process(args.kill)
        r.data = {"killed": args.kill, "ok": ok, "message": msg}
        if not ok:
            raise CliError(msg, EXIT_FAILED)
        r.log(msg)
        return r
    if args.filter:
        kw = args.filter.lower()
        items = [it for it in items if kw in str(it.get("port", ""))
                 or kw in str(it.get("pid") or "").lower()
                 or kw in str(it.get("process", "")).lower()]
    r.data = {"ports": items, "count": len(items)}
    for it in items:
        r.log(f"  {it['proto']:>4}  {it['addr']}:{it['port']}  "
              f"{it.get('process', '-')} (PID {it.get('pid')})")
    return r


def cmd_speed(args, r):
    tester = SpeedTester(log_callback=r.log)
    res = tester.test(max_seconds=args.max_seconds, max_mb=args.max_mb)
    r.data = {"result": res}
    if not res.get("ok"):
        r.warn(tr("测速失败: ") + str(res.get("error") or tr("未知原因")))
        return r
    r.log(tr_f("下行带宽: {mbps} Mbps", mbps=res.get('mbps')))
    return r


def cmd_wifi(args, r):
    tool = WifiTool(log_callback=r.log)
    if not IS_WINDOWS:
        raise CliError(tr("WiFi 信息查看仅支持 Windows (netsh wlan)"), EXIT_UNSUPPORTED)
    items, err = tool.list_wifi(progress_callback=lambda i, n: r.log(f"  {i}/{n}"))
    if err:
        r.data = {"items": [], "error": err}
        raise CliError(err, EXIT_FAILED)
    r.data = {"items": items, "count": len(items)}
    # 能不能读到密码要看 netsh 实际返回, 不是只看权限位: 部分系统上当前用户
    # 自己的配置文件不建权也能读。所以按"实际拿到几个密码"给提示, 别虚报。
    got = sum(1 for it in items if it.get("password"))
    if not is_admin():
        if got:
            r.log(tr_f("非管理员启动，但仍读到 {got}/{total} 个网络的密码",
                       got=got, total=len(items)))
        else:
            r.warn(tr("非管理员启动，未读到任何密码：请以管理员身份运行再试"))
    if args.export:
        path = os.path.abspath(args.export)
        with open(path, "w", encoding="utf-8") as f:
            f.write(tool.export_text(items))
        r.data["exported"] = path
        r.log(tr_f("已导出: {path}", path=path))
    return r


def cmd_monitor(args, r):
    mon = NetworkMonitor()
    if args.clear:
        mon.clear_events()
        r.data = {"cleared": True}
        r.log(tr("掉线记录已清空"))
        return r
    summary = mon.summarize()
    events = [NetworkMonitor.format_event(e) for e in mon.events]
    r.data = {"summary": summary, "events": mon.events, "formatted": events}
    for line in events:
        r.log("  " + line)
    if not events:
        r.log(tr("  暂无掉线记录"))
    return r


def cmd_snapshots(args, r):
    tool = NetworkResetTool(log_callback=r.log)
    if args.rollback:
        path = args.rollback
        if not os.path.exists(path):
            raise CliError(tr("快照文件不存在: ") + path, EXIT_USAGE)
        with open(path, "r", encoding="utf-8") as f:
            snap = json.load(f)
        if not is_admin():
            raise CliError(tr("回滚网络配置需要管理员权限"), EXIT_NEED_ADMIN)
        done, total = tool.rollback_snapshot(snap, restore_ip=args.restore_ip)
        r.data = {"rollback": path, "done": done, "total": total,
                  "restore_ip": bool(args.restore_ip)}
        if done < total:
            r.warn(tr_f("回滚部分失败: {done}/{total}", done=done, total=total))
        return r
    snaps = NetworkResetTool.list_snapshots(limit=args.limit)
    r.data = {"snapshots": [{"path": p, "time": t, "adapters": n} for p, t, n in snaps]}
    for p, t, n in snaps:
        r.log(tr_f("  {time}  网卡 {count} 个  {proc}", time=t, count=n, proc=p))
    if not snaps:
        r.log(tr("  暂无快照"))
    return r


def cmd_report(args, r):
    diag = NetworkDiagnostic(log_callback=r.log)
    results = diag.run_full_diagnostic(
        progress_callback=lambda pct, msg: r.log(f"  [{pct:>3}%] {msg}"))
    content, enc = render_report(results, args.format)
    r.data = {"format": args.format, "encoding": enc, "length": len(content)}
    if args.out:
        path = os.path.abspath(args.out)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        r.data["path"] = path
        r.log(tr_f("报告已写入: {path}", path=path))
    elif args.json:
        # 只有非 JSON 模式才允许把正文倒到 stdout，否则报告正文会污染 JSON 流
        r.log(tr("未指定 --out，报告正文已放入 JSON 的 data.content"))
        r.data["content"] = content
    else:
        _print_report_stdout(content)
    return r


def _print_report_stdout(content):
    """报告正文打到 stdout（仅在未指定 --out 且非 --json 时调用）。"""
    try:
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    except UnicodeEncodeError:
        # 极端代码页兜底：至少不让整条命令崩在这里
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe = content.encode(enc, "backslashreplace").decode(enc, "ignore")
        sys.stdout.write(safe)
        sys.stdout.write("\n")


def cmd_hosts(args, r):
    """检查 hosts 映射；--fix 一键注释可疑条目(需管理员)。

    read_entries() 已经带 suspicious/reason 字段, 不需要再单独判定一遍。
    comment_suspicious() 返回 (ok, 条数, 错误信息) 三元组。
    """
    tool = HostsTool()
    entries = tool.read_entries()
    suspicious = [e for e in entries if e.get("suspicious")]
    r.data = {"entries": len(entries), "suspicious": suspicious,
              "hosts_path": tool.path}
    for e in suspicious:
        r.log("  {}  {}  ({})".format(e['ip'], e['host'],
                                    e.get('reason') or tr("可疑")))
    if not suspicious:
        r.log(tr("未发现可疑 hosts 映射"))
        return r
    r.warn(tr_f("发现 {count} 条可疑 hosts 映射", count=len(suspicious)))
    if args.fix:
        if not is_admin():
            raise CliError(tr("修改 hosts 需要管理员权限：请以管理员身份运行"),
                           EXIT_NEED_ADMIN)
        ok, count, err = tool.comment_suspicious()
        r.data["fixed"] = bool(ok)
        r.data["commented"] = count
        r.log(tr_f("已注释 {count} 条（自动备份在 hosts_backups/）", count=count))
        if not ok:
            raise CliError(err or tr("注释 hosts 失败"), EXIT_FAILED)
    return r


# ---------------------------------------------------------------- argparse

def cmd_proxy(args, r):
    tool = ProxyRepairTool(log_callback=r.log)
    info = tool.diagnose()
    r.data = {"diagnosis": info}
    need_fix = any(d.get("issue") for d in (info.get("problems") or []))
    if not args.repair:
        if need_fix:
            r.warn(tr("诊断发现问题，加 --repair 可一键修复"))
        return r
    if not need_fix:
        r.log(tr("未发现需要修复的问题"))
        return r
    if not is_admin():
        raise CliError(tr("修复代理需要管理员权限：请以管理员身份运行"), EXIT_NEED_ADMIN)
    result = tool.repair()
    r.data["repair"] = result
    if not result:
        raise CliError(tr("修复失败"), EXIT_FAILED)
    return r


def build_parser():
    """搭 argparse。

    用子命令(subparsers)而不是一堆裸选项: 每个命令只暴露自己用得到的参数,
    `--cli dns --help` 就能查到该命令的完整用法, 不用在一屏无关选项里翻。
    共享参数(adapter/json)放 parent parser 里, 各子命令自动继承。
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--adapter", default=None, metavar="NAME",
                        help=tr("指定网卡名（默认自动检测；先跑 adapters 看可选值）"))
    common.add_argument("--json", action="store_true",
                        help=tr("机器可读输出：stdout 只打印一个 JSON 对象，日志走 stderr"))
    # default=SUPPRESS: 子命令不写回默认值，
    # 否则写在子命令之前的 `--lang en --cli adapters` 会被覆盖掉。
    common.add_argument("--lang", choices=sorted(LANGS),
                        default=argparse.SUPPRESS, metavar="LANG",
                        help=tr("界面语言(F12): zh / en, 缺省沿用上次保存的选择"))

    p = argparse.ArgumentParser(
        prog=tr("网络工具箱.exe --cli"),
        description=tr("%s %s 命令行模式（无界面，可脚本化）") % (APP_NAME, APP_VERSION),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=tr("""命令一览:
  adapters    列出本机网卡（只读）
  diagnose    完整网络诊断 + 健康评分
  reset       完整网络重置（需管理员，仅 Windows）
  dns         查看 / 切换 DNS（预设、自定义、回退 DHCP）
  proxy       代理诊断；加 --repair 一键修复
  ports       列出监听端口，可按端口/PID/进程名过滤
  speed       实测下行带宽
  wifi        列出已保存 WiFi 与密码（读密码需管理员）
  monitor     查看 / 清空掉线记录
  snapshots   列出 / 回滚网络配置快照
  report      生成诊断报告（html/txt/md）
  hosts       检查 hosts 映射，可一键注释可疑条目

示例:
  网络工具箱.exe --cli adapters
  网络工具箱.exe --cli diagnose --json
  网络工具箱.exe --cli dns --preset "阿里 DNS"
  网络工具箱.exe --cli dns --auto
  网络工具箱.exe --cli dns --set 223.5.5.5 223.6.6.6
  网络工具箱.exe --cli ports --filter 7890
  网络工具箱.exe --cli ports --kill 1234
  网络工具箱.exe --cli speed --max-seconds 8
  网络工具箱.exe --cli wifi --export wifi.txt
  网络工具箱.exe --cli monitor
  网络工具箱.exe --cli snapshots --rollback snap.json --restore-ip
  网络工具箱.exe --cli report --format html --out report.html
  网络工具箱.exe --cli hosts --fix
  网络工具箱.exe --cli proxy --repair

每个命令的详细参数: 网络工具箱.exe --cli <命令> --help

退出码:
  0  成功        1  操作失败      2  参数错误
  3  需要管理员  4  平台不支持    130  被 Ctrl+C 取消"""))

    # --cli 只在兼容入口里做人肉分流; 这里注册它是为了让 --help 不报错
    p.add_argument("--cli", action="store_true", help=argparse.SUPPRESS)
    # F12: 语言参数同样挂到顶层——人们自然会写
    # `--lang en --cli adapters`, 只放在子命令后面会让这种写法报参数错误。
    p.add_argument("--lang", choices=sorted(LANGS), default=None, metavar="LANG",
                   help=tr("界面语言(F12): zh / en, 缺省沿用上次保存的选择"))

    sub = p.add_subparsers(dest="command", metavar=tr("<命令>"))
    sub.required = True

    sp = sub.add_parser("adapters", parents=[common],
                        help=tr("列出本机网卡（只读）"))
    sp.set_defaults(func=cmd_adapters)

    sp = sub.add_parser("diagnose", parents=[common],
                        help=tr("完整网络诊断 + 健康评分"))
    sp.set_defaults(func=cmd_diagnose)

    sp = sub.add_parser("reset", parents=[common],
                        help=tr("完整网络重置（需管理员，仅 Windows）"))
    sp.add_argument("--stages", metavar="LIST",
                    help=tr("只执行指定阶段，逗号分隔，如 winsock,tcpip"))
    sp.set_defaults(func=cmd_reset)

    sp = sub.add_parser("dns", parents=[common], help=tr("查看 / 切换 DNS"))
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument("--preset", metavar="NAME",
                     help=tr("DNS 预设名，如 \"阿里 DNS\" / \"Cloudflare\""))
    grp.add_argument("--auto", action="store_true", help=tr("切回自动获取(DHCP)"))
    grp.add_argument("--set", nargs="+", metavar=("PRIMARY", "SECONDARY"),
                     help=tr("自定义 DNS，如 --set 223.5.5.5 223.6.6.6"))
    sp.set_defaults(func=cmd_dns)

    sp = sub.add_parser("proxy", parents=[common], help=tr("代理诊断 / 修复"))
    sp.add_argument("--repair", action="store_true",
                    help=tr("发现问题则一键修复（需管理员）"))
    sp.set_defaults(func=cmd_proxy)

    sp = sub.add_parser("ports", parents=[common], help=tr("列出监听端口"))
    sp.add_argument("--filter", metavar="KW", help=tr("按端口 / PID / 进程名过滤"))
    sp.add_argument("--kill", type=int, metavar="PID",
                    help=tr("结束指定 PID（需管理员）"))
    sp.set_defaults(func=cmd_ports)

    sp = sub.add_parser("speed", parents=[common], help=tr("实测下行带宽"))
    sp.add_argument("--max-seconds", type=int, default=12, help=tr("测速上限秒数"))
    sp.add_argument("--max-mb", type=int, default=64, help=tr("测速上限流量 MB"))
    sp.set_defaults(func=cmd_speed)

    sp = sub.add_parser("wifi", parents=[common], help=tr("列出已保存 WiFi 与密码"))
    sp.add_argument("--export", metavar="PATH", help=tr("把列表导出为 txt"))
    sp.set_defaults(func=cmd_wifi)

    sp = sub.add_parser("monitor", parents=[common], help=tr("查看 / 清空掉线记录"))
    sp.add_argument("--clear", action="store_true", help=tr("清空掉线记录"))
    sp.set_defaults(func=cmd_monitor)

    sp = sub.add_parser("snapshots", parents=[common], help=tr("列出 / 回滚配置快照"))
    sp.add_argument("--rollback", metavar="PATH", help=tr("按指定快照文件回滚"))
    sp.add_argument("--restore-ip", action="store_true",
                    help=tr("回滚时一并恢复静态 IP/掩码/网关（风险较高）"))
    sp.add_argument("--limit", type=int, default=20, help=tr("最多列出多少条快照"))
    sp.set_defaults(func=cmd_snapshots)

    sp = sub.add_parser("report", parents=[common], help=tr("生成诊断报告"))
    sp.add_argument("--format", default="html", choices=["html", "txt", "md"],
                    help=tr("报告格式"))
    sp.add_argument("--out", metavar="PATH", help=tr("报告输出路径（缺省打到 stdout）"))
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("hosts", parents=[common], help=tr("检查 hosts 映射"))
    sp.add_argument("--fix", action="store_true",
                    help=tr("注释可疑 hosts 条目（需管理员）"))
    sp.set_defaults(func=cmd_hosts)

    return p


def _peek_lang(argv):
    """从 argv 里先拣出 --lang 的值(支持 `--lang en` 与 `--lang=en`)。

    为什么要提前: argparse 的 help/epilog 是在 build_parser() 那一刻
    就被 tr() 固化掉的。等 parse 完再切语言, `--cli dns --help`
    打出来的还是旧语言——考虑到 help 本身就是给人看的,
    这一点很关键。
    """
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--lang="):
            return a.split("=", 1)[1]
    return None


def run_cli(argv=None):
    """命令行入口。argv 为 None 时取 sys.argv[1:]。返回进程退出码。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    # 语言必须在 build_parser() 之前定下来, 否则 help/epilog 还是旧语言。
    # persist=False: 一次性的命令不该善自改掉用户存的语言偏好。
    set_lang(_peek_lang(argv) or current_lang(), persist=False)
    parser = build_parser()
    args = parser.parse_args(argv)
    _lossy_streams()

    # CLI 不参与 GUI 单例：占着端口没意义，还会让随后启动的 GUI 误判"已在运行"
    _release_singleton()

    fn = args.func
    r = _Result(args.command)
    try:
        fn(args, r)
    except CliError as e:
        r.ok = False
        r.warn(e.message)
        r.data.setdefault("error", e.message)
        r.data["exit_code"] = e.code
        r.data.update(e.extra)
        if args.json:
            _emit(r, True)
        else:
            print(tr("错误: ") + e.message, file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        print(tr("\n已取消"), file=sys.stderr)
        return 130
    except Exception as e:
        # CLI 的异常一律转成退出码 + stderr，绝不去弹 GUI 错误框
        import traceback
        tb = traceback.format_exc()
        r.ok = False
        r.warn(tr_f("执行出错: {err}", err=e))
        r.data["error"] = str(e)
        r.data["traceback"] = tb
        _emit(r, args.json)
        print(tb, file=sys.stderr)
        return EXIT_FAILED
    return _emit(r, args.json)


def main(argv=None):
    return run_cli(argv)


if __name__ == "__main__":
    sys.exit(run_cli())
