#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网络工具箱 - 兼容入口（v4.4；v3.5 拆分后的唯一入口）。

实现已全部拆分至 network_toolbox/ 包：
  - network_toolbox/_shared.py    模块级函数与常量（解码/校验/单例/字体/按钮样式）
  - network_toolbox/engine.py     网络重置 / 诊断 / 代理修复引擎（纯逻辑）
  - network_toolbox/report.py     诊断报告渲染（HTML/TXT/MD）
  - network_toolbox/ui_panels.py  重置 / 诊断 / 代理修复 / 端口 / 监控 / 测速 / WiFi 面板
  - network_toolbox/app.py        主窗口 App 与 main() 入口

本文件保留兼容职责：
  - 全部公共 API 经 `from network_toolbox import *` 重新导出（测试与旧脚本仍可
    `import network_reset_gui as G` 使用 G.decode_output / G.App 等符号）；
  - PyInstaller 的 网络工具箱.spec 仍以本文件为 Analysis 目标；
  - 直接运行 `python network_reset_gui.py` 即启动 GUI
    （--tab <reset|diagnostic|proxy|ports|monitor|speed|wifi>）
  - `--cli <命令>` 进入命令行模式（F10，无界面、可脚本化，详见
    `network_toolbox/cli.py` 的 argparse epilog）
"""
import sys  # noqa: E402  命令行分流必须先于包导入, 否则拿不到 sys.argv

# 命令行模式必须在 import 整个包之前分流: --cli 只需要 engine/report,
# 不必拖进 ui_panels/app 那一堆 Tk 依赖, 也不该占用 GUI 的单例端口。
if "--cli" in sys.argv:
    from network_toolbox.cli import main as _cli_main
    # 必须透传退出码: 脚本靠它判断成功/失败/需要提权, 统统 exit(0) 就没法用了
    sys.exit(_cli_main())

from network_toolbox import *  # noqa: F401,F403
from network_toolbox import _shared  # noqa: F401  （测试在 G._shared 上打桩）
from network_toolbox.app import App, main  # noqa: F401

__all__ = ["App", "main"]


if __name__ == "__main__":
    main()
