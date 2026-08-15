#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows 网络工具箱 - GUI 入口 v3.2
模块结构:
  nettoolbox/core.py  网络重置与诊断核心逻辑(纯逻辑,可独立测试)
  nettoolbox/ui.py    重置/诊断面板(所有 Tk 操作在主线程)
  nettoolbox/app.py   主窗口与 Tab 切换
v3.2 修复:
  1. DNS 切换"未找到活动网卡"根因:ResetPanel 误引用 NetworkDiagnostic 的
     _decode_output 导致适配器检测必然失败 → 抽取为公共 decode_output()
  2. 工作线程直接创建 Tk 控件的线程安全问题 → 计算与渲染分离
  3. 自定义 Ping / Traceroute 目标未校验,存在命令注入风险 → validate_host()
  4. 重启按钮 Restart-Computer 参数错误导致不执行 → 改用 shutdown /r /t 5
  5. reset_tcpip 恒返回 True、无网关静态IP恢复命令语法错误、
     健康报告 avg_ms 为 None 崩溃、自定义 Ping 按钮未禁用、死代码清理
"""

import os
import sys
import time

# ===== 单例检测(socket方式) =====
import socket

_SINGLETON_PORT = 45678  # 固定端口
_SINGLETON_SOCKET = None


def _acquire_singleton():
    """使用socket端口绑定实现单例检测(Windows友好)"""
    global _SINGLETON_SOCKET
    try:
        _SINGLETON_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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


def main():
    from nettoolbox.app import App

    try:
        app = App()
        app.protocol("WM_DELETE_WINDOW", lambda: (_release_singleton(), app.destroy()))
        app.mainloop()
    except Exception:
        import traceback
        error_msg = traceback.format_exc()
        # 写入日志文件
        log_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'crash.log')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(f"Crash at {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(error_msg)
        # 如果是打包环境,显示错误弹窗
        try:
            import tkinter as tk_err
            from tkinter import messagebox as mb_err
            root_err = tk_err.Tk()
            root_err.withdraw()
            mb_err.showerror("程序错误", f"{error_msg[:500]}\n\n日志已保存: {log_path}", parent=root_err)
            root_err.destroy()
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    # 单例检测
    if not _am_first:
        import tkinter as tk_temp
        from tkinter import messagebox as mb_temp
        root_temp = tk_temp.Tk()
        root_temp.withdraw()
        root_temp.attributes("-topmost", True)
        mb_temp.showwarning("提示", "程序已在运行!\n请先关闭旧窗口。", parent=root_temp)
        root_temp.destroy()
        sys.exit(1)

    main()
