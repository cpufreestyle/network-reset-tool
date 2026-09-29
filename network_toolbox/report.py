# -*- coding: utf-8 -*-
"""诊断报告计算与渲染 (HTML / TXT / Markdown)。"""
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
    decode_output,
    is_admin,
    is_valid_target,
    make_btn_style,
    styled_btn,
    ui_sync,
)

def compute_health(results):
    """把诊断结果折算成健康评分。

    UI 的健康报告卡片与导出的报告共用这一份口径，避免两处算法各自漂移。
    返回一个纯数据字典（不含任何 Tk 对象，可在工作线程里安全调用）。
    """
    results = results or {}
    ping_results = results.get('ping') or []
    dns_results = results.get('dns') or []
    overview = results.get('overview') or []

    # 连通性 40 分：每个可达目标 8 分
    ping_ok = sum(1 for p in ping_results if p.get('ok'))
    conn_score = ping_ok * 8

    # DNS 30 分：每个可用 DNS 10 分
    dns_ok = sum(1 for d in dns_results if d.get('ok'))
    dns_score = dns_ok * 10

    # 配置完整性 30 分：IP / 网关 / DNS 各 10 分
    has_ip = has_gw = has_dns = False
    for k, _v in overview:
        if 'IP' in k:
            has_ip = True
        if '网关' in k:
            has_gw = True
        if 'DNS' in k:
            has_dns = True
    cfg_score = (10 if has_ip else 0) + (10 if has_gw else 0) + (10 if has_dns else 0)

    total = conn_score + dns_score + cfg_score

    if total >= 90:
        grade, advice = tr("优秀"), tr("网络状态优秀，所有检测通过，继续保持。")
    elif total >= 70:
        grade, advice = tr("良好"), tr("网络状态良好，个别指标待优化，可尝试 DNS 一键切换。")
    elif total >= 50:
        grade, advice = tr("一般"), tr("网络状态一般，建议执行「网络重置」修复潜在问题。")
    else:
        grade, advice = tr("较差"), tr("网络状态较差，建议立即执行「一键重置全部」修复网络。")

    # avg_ms 在 <1ms 时为 None，必须兜底，否则 sum() 抛 TypeError
    ok_pings = [p for p in ping_results if p.get('ok')]
    avg_latency = round(sum((p.get('avg_ms') or 0) for p in ok_pings) / len(ok_pings), 1) if ok_pings else 0
    avg_loss = round(sum(p.get('loss', 0) for p in ping_results) / len(ping_results), 1) if ping_results else 100

    if ping_results or dns_results:
        all_ping_ok = bool(ping_results) and all(p.get('ok') for p in ping_results)
        all_dns_ok = bool(dns_results) and all(d.get('ok') for d in dns_results)
        if all_ping_ok and all_dns_ok:
            conclusion = tr("网络状态正常：所有目标连通，DNS 解析正常。")
        elif all_ping_ok:
            conclusion = tr("DNS 异常：Ping 正常但 DNS 解析失败，建议清除 DNS 缓存或切换公共 DNS。")
        elif all_dns_ok:
            conclusion = tr("连通性异常：DNS 正常但目标不可达，请检查网关、防火墙或代理设置。")
        else:
            conclusion = tr("网络异常：连通性与 DNS 均有失败项，建议执行「一键重置全部」。")
    else:
        conclusion = tr("未采集到足够的诊断数据。")

    return {
        'total': total,
        'grade': grade,
        'advice': advice,
        'conclusion': conclusion,
        'conn_score': conn_score, 'ping_ok': ping_ok, 'ping_total': len(ping_results),
        'dns_score': dns_score, 'dns_ok': dns_ok, 'dns_total': len(dns_results),
        'cfg_score': cfg_score,
        'has_ip': has_ip, 'has_gw': has_gw, 'has_dns': has_dns,
        'avg_latency': avg_latency,
        'avg_loss': avg_loss,
    }

def collect_report_meta():
    """报告的元信息：生成时间、主机名、系统版本、是否管理员。"""
    try:
        host = socket.gethostname()
    except Exception:
        host = "-"
    try:
        os_info = f"{platform.system()} {platform.release()} ({platform.version()})"
    except Exception:
        os_info = platform.system() or "-"
    try:
        admin = tr("是") if is_admin() else tr("否")
    except Exception:
        admin = "-"
    return [
        (tr("生成时间"), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        (tr("计算机名"), host),
        (tr("操作系统"), os_info),
        (tr("系统架构"), platform.machine() or "-"),
        (tr("Python 版本"), platform.python_version()),
        (tr("以管理员运行"), admin),
        (tr("工具版本"), f"{APP_NAME} {APP_VERSION}"),
    ]

def _latency_text(p):
    if not p.get('ok'):
        return "-"
    return f"{p.get('avg_ms')}ms" if p.get('avg_ms') is not None else "<1ms"

def _report_css_vars():
    """HTML 报告的 CSS 变量取自当前主题(F11), 导出后与界面同色。

    深浅两套主题的语义键刚好对上报告里的这几个槽位。打印仍强制浅色,
    免得深色主题导出的报告打出来一片黑。
    """
    return {
        "fg": COLORS["text"],
        "muted": COLORS["muted"],
        "line": COLORS["surface2"],
        "bg": COLORS["surface"],
        "soft": COLORS["bg2"],
        "ok": COLORS["green"],
        "bad": COLORS["red"],
    }


def render_report_html(results):
    """渲染为单文件 HTML（浅色、可直接打印 / 发给 IT 或运营商）。"""
    h = compute_health(results)
    results = results or {}
    overview = results.get('overview') or []
    ping_results = results.get('ping') or []
    dns_results = results.get('dns') or []

    esc = lambda s: _html.escape("" if s is None else str(s))

    def kv_table(rows):
        return "".join(
            f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows
        )

    ping_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td class='{}'>{}</td><td>{}</td><td>{}</td></tr>".format(
            esc(p.get('label')), esc(p.get('target')),
            "ok" if p.get('ok') else "bad",
            tr("可达") if p.get('ok') else tr("不可达"),
            esc(_latency_text(p)), esc(p.get('loss', 0)) + "%")
        for p in ping_results
    ) or tr("<tr><td colspan='5'>无数据</td></tr>")

    dns_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td class='{}'>{}</td><td>{}</td></tr>".format(
            esc(d.get('label')), esc(d.get('dns')),
            "ok" if d.get('ok') else "bad",
            tr("正常") if d.get('ok') else tr("失败"),
            esc(d.get('ip') or "-"))
        for d in dns_results
    ) or tr("<tr><td colspan='4'>无数据</td></tr>")

    total = h['total']
    grade = esc(h['grade'])
    # 分档色走主题语义键, 深浅主题下都保证可读
    if total >= 90:
        score_color = COLORS["green"]
    elif total >= 70:
        score_color = COLORS["blue"]
    elif total >= 50:
        score_color = COLORS["yellow"]
    else:
        score_color = COLORS["red"]
    css = _report_css_vars()

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>网络诊断报告 - {esc(datetime.now().strftime('%Y-%m-%d %H-%M-%S'))}</title>
<style>
  :root {{
    --fg: {css['fg']}; --muted: {css['muted']}; --line: {css['line']}; --bg: {css['bg']};
    --soft: {css['soft']}; --ok: {css['ok']}; --bad: {css['bad']};
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 32px 20px 56px; background: var(--soft);
         color: var(--fg); font: 14px/1.6 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }}
  .wrap {{ max-width: 880px; margin: 0 auto; background: var(--bg);
           border: 1px solid var(--line); border-radius: 12px; padding: 32px 36px 28px; }}
  h1 {{ margin: 0 0 4px; font-size: 22px; }}
  .sub {{ color: var(--muted); font-size: 12px; margin-bottom: 24px; }}
  h2 {{ font-size: 15px; margin: 30px 0 10px; padding-bottom: 6px;
        border-bottom: 1px solid var(--line); }}
  .score {{ display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }}
  .score .num {{ font-size: 48px; font-weight: 700; color: {score_color}; line-height: 1; }}
  .score .grade {{ font-size: 18px; font-weight: 700; color: {score_color}; }}
  .score .advice {{ color: var(--muted); font-size: 13px; }}
  .metrics {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 18px; }}
  .metric {{ flex: 1 1 150px; background: var(--soft); border: 1px solid var(--line);
             border-radius: 8px; padding: 12px 14px; }}
  .metric .k {{ font-size: 12px; color: var(--muted); }}
  .metric .v {{ font-size: 20px; font-weight: 700; margin-top: 2px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line);
            vertical-align: top; word-break: break-all; }}
  th {{ width: 150px; color: var(--muted); font-weight: 600; background: var(--soft); }}
  thead th {{ width: auto; color: var(--fg); }}
  td.ok {{ color: var(--ok); font-weight: 600; }}
  td.bad {{ color: var(--bad); font-weight: 600; }}
  .conclusion {{ background: var(--soft); border-left: 4px solid {score_color};
                 padding: 12px 14px; border-radius: 0 8px 8px 0; }}
  footer {{ margin-top: 28px; color: var(--muted); font-size: 12px;
            border-top: 1px solid var(--line); padding-top: 12px; }}
  @media print {{ body {{ background: #fff; color: #1f2328; padding: 0; }}
    .wrap {{ background: #fff; border: 0; }}
    .metric, th, .conclusion {{ background: #f6f8fa; }} }}
</style>
</head>
<body>
<div class="wrap">
  <h1>网络诊断报告</h1>
  <div class="sub">由 {esc(APP_NAME)} {esc(APP_VERSION)} 生成</div>

  <h2>综合评分</h2>
  <div class="score">
    <div class="num">{total}</div>
    <div>
      <div class="grade">{grade}</div>
      <div class="advice">{esc(h['advice'])}</div>
    </div>
  </div>
  <div class="metrics">
    <div class="metric"><div class="k">连通性</div><div class="v">{h['ping_ok']}/{h['ping_total']}</div></div>
    <div class="metric"><div class="k">DNS 可用</div><div class="v">{h['dns_ok']}/{h['dns_total']}</div></div>
    <div class="metric"><div class="k">平均延迟</div><div class="v">{h['avg_latency']}ms</div></div>
    <div class="metric"><div class="k">平均丢包</div><div class="v">{h['avg_loss']}%</div></div>
  </div>

  <h2>结论</h2>
  <div class="conclusion">{esc(h['conclusion'])}</div>

  <h2>环境信息</h2>
  <table>{kv_table(collect_report_meta())}</table>

  <h2>网络状态总览</h2>
  <table>{kv_table(overview) or tr("<tr><td>无数据</td></tr>")}</table>

  <h2>Ping 连通性测试</h2>
  <table>
    <thead><tr><th>目标</th><th>地址</th><th>结果</th><th>平均延迟</th><th>丢包</th></tr></thead>
    <tbody>{ping_rows}</tbody>
  </table>

  <h2>DNS 解析测试</h2>
  <table>
    <thead><tr><th>服务器</th><th>地址</th><th>结果</th><th>解析 IP</th></tr></thead>
    <tbody>{dns_rows}</tbody>
  </table>

  <footer>本报告仅反映生成时刻的网络状态，供排查参考。</footer>
</div>
</body>
</html>
"""

def render_report_text(results):
    """渲染为纯文本（适合贴到工单 / 聊天窗口）。"""
    h = compute_health(results)
    results = results or {}
    overview = results.get('overview') or []
    ping_results = results.get('ping') or []
    dns_results = results.get('dns') or []

    def bar(title):
        return f"\n{'=' * 60}\n{title}\n{'=' * 60}"

    lines = []
    lines.append(tr("网络诊断报告"))
    lines.append(tr("由 %s %s 生成") % (APP_NAME, APP_VERSION))
    lines.append(bar(tr("综合评分")))
    lines.append(tr("总分: %d / 100   等级: %s") % (h['total'], h['grade']))
    lines.append(tr("建议: %s") % h['advice'])
    lines.append(tr("连通性: %d/%d    DNS: %d/%d    平均延迟: %sms    平均丢包: %s%%")
                 % (h['ping_ok'], h['ping_total'], h['dns_ok'], h['dns_total'],
                    h['avg_latency'], h['avg_loss']))
    lines.append(bar(tr("结论")))
    lines.append(h['conclusion'])
    lines.append(bar(tr("环境信息")))
    for k, v in collect_report_meta():
        lines.append("  %-14s %s" % (k, v))
    lines.append(bar(tr("网络状态总览")))
    if overview:
        for k, v in overview:
            lines.append("  %-14s %s" % (k, v))
    else:
        lines.append(tr("  无数据"))
    lines.append(bar(tr("Ping 连通性测试")))
    if ping_results:
        for p in ping_results:
            lines.append(tr("  [%s] %s (%s) 延迟=%s 丢包=%s%%")
                         % ("OK " if p.get('ok') else "FAIL",
                            p.get('label'), p.get('target'),
                            _latency_text(p), p.get('loss', 0)))
    else:
        lines.append(tr("  无数据"))
    lines.append(bar(tr("DNS 解析测试")))
    if dns_results:
        for d in dns_results:
            lines.append("  [%s] %s (%s) -> %s"
                         % ("OK " if d.get('ok') else "FAIL",
                            d.get('label'), d.get('dns'), d.get('ip') or "-"))
    else:
        lines.append(tr("  无数据"))
    lines.append("")
    return "\n".join(lines)

def render_report_markdown(results):
    """渲染为 Markdown（适合发到 GitHub Issue / 飞书 / 语雀）。"""
    h = compute_health(results)
    results = results or {}
    overview = results.get('overview') or []
    ping_results = results.get('ping') or []
    dns_results = results.get('dns') or []

    def cell(s):
        return str(s).replace("|", "\\|") if s is not None else "-"

    out = []
    out.append(tr("# 网络诊断报告"))
    out.append("")
    out.append(tr("> 由 %s %s 生成") % (APP_NAME, APP_VERSION))
    out.append("")
    out.append(tr("## 综合评分"))
    out.append("")
    out.append("**%d / 100** · %s" % (h['total'], h['grade']))
    out.append("")
    out.append("> %s" % h['advice'])
    out.append("")
    out.append(tr("| 指标 | 值 |"))
    out.append("| --- | --- |")
    out.append(tr("| 连通性 | %d/%d |") % (h['ping_ok'], h['ping_total']))
    out.append(tr("| DNS 可用 | %d/%d |") % (h['dns_ok'], h['dns_total']))
    out.append(tr("| 平均延迟 | %sms |") % h['avg_latency'])
    out.append(tr("| 平均丢包 | %s%% |") % h['avg_loss'])
    out.append("")
    out.append(tr("## 结论"))
    out.append("")
    out.append(h['conclusion'])
    out.append("")
    out.append(tr("## 环境信息"))
    out.append("")
    out.append(tr("| 项目 | 值 |"))
    out.append("| --- | --- |")
    for k, v in collect_report_meta():
        out.append("| %s | %s |" % (cell(k), cell(v)))
    out.append("")
    out.append(tr("## 网络状态总览"))
    out.append("")
    if overview:
        out.append(tr("| 项目 | 值 |"))
        out.append("| --- | --- |")
        for k, v in overview:
            out.append("| %s | %s |" % (cell(k), cell(v)))
    else:
        out.append(tr("无数据"))
    out.append("")
    out.append(tr("## Ping 连通性测试"))
    out.append("")
    if ping_results:
        out.append(tr("| 目标 | 地址 | 结果 | 平均延迟 | 丢包 |"))
        out.append("| --- | --- | --- | --- | --- |")
        for p in ping_results:
            out.append("| %s | %s | %s | %s | %s%% |"
                       % (cell(p.get('label')), cell(p.get('target')),
                          tr("可达") if p.get('ok') else tr("不可达"),
                          cell(_latency_text(p)), cell(p.get('loss', 0))))
    else:
        out.append(tr("无数据"))
    out.append("")
    out.append(tr("## DNS 解析测试"))
    out.append("")
    if dns_results:
        out.append(tr("| 服务器 | 地址 | 结果 | 解析 IP |"))
        out.append("| --- | --- | --- | --- |")
        for d in dns_results:
            out.append("| %s | %s | %s | %s |"
                       % (cell(d.get('label')), cell(d.get('dns')),
                          tr("正常") if d.get('ok') else tr("失败"), cell(d.get('ip') or "-")))
    else:
        out.append(tr("无数据"))
    out.append("")
    return "\n".join(out)

def render_report(results, fmt="html"):
    """按格式渲染报告文本。fmt: html / txt / md"""
    fmt = (fmt or "html").lower().lstrip(".")
    if fmt in ("txt", "text"):
        return render_report_text(results), "utf-8"
    if fmt in ("md", "markdown"):
        return render_report_markdown(results), "utf-8"
    return render_report_html(results), "utf-8"

def open_path(path):
    """用系统默认程序打开文件（跨平台）。"""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False