#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把刚打包好的 exe 指到桌面快捷方式上(不存在就新建, 存在就刷新)。

用法:
    python update_shortcut.py                # 刷新当前用户的桌面快捷方式
    python update_shortcut.py --all-users    # 同时刷新公用桌面
    python update_shortcut.py --exe <路径>    # 指定 exe(默认 dist/网络工具箱.exe)
    python update_shortcut.py --name <名字>   # .lnk 文件名(默认 网络工具箱.lnk)
    python update_shortcut.py --dry-run      # 只打印目标, 一个字节都不写

为什么需要它: .lnk 里存的是绝对路径。这个项目换过 workspace 目录
(.../dist_new -> .../dist), 桌面上那份快捷方式还指向旧目录里的老 exe,
双击跑起来的其实是旧版本。本脚本让"快捷方式指向哪"始终跟着当次构建产物走,
并把工作目录/图标/说明一并刷新。

只依赖标准库: 定位桌面用 SHGetFolderPathW, 写 .lnk 用
IShellLinkW + IPersistFile(ctypes 直接调 COM, 不引第三方依赖)。
"""
import argparse
import ctypes
import os
import sys
from ctypes import POINTER, byref, c_int, c_void_p, wintypes

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from network_toolbox._shared import APP_NAME, APP_VERSION, APP_VERSION_SHORT  # noqa: E402

DEFAULT_EXE = os.path.join(ROOT, "dist", APP_NAME + ".exe")
DEFAULT_LNK_NAME = APP_NAME + ".lnk"
DESCRIPTION = "%s %s - 网络重置/诊断/代理修复/工具箱" % (APP_NAME, APP_VERSION_SHORT)

CSIDL_DESKTOPDIRECTORY = 0x0010
CSIDL_COMMON_DESKTOPDIRECTORY = 0x0019
CLSCTX_INPROC_SERVER = 1
MAX_PATH = 260

    # IShellLinkW / IPersistFile 的 vtable 序号。前三个都是 IUnknown（因此 IShellLinkW 从 3 起算）； IPersistFile 还多继承了 IPersist.GetClassID，所以它从 4 起算。
SL_GET_PATH, SL_GET_DESC, SL_GET_WORKDIR, SL_GET_ICON, SL_GET_SHOWCMD = 3, 6, 8, 16, 14
SL_SET_PATH, SL_SET_DESC, SL_SET_WORKDIR, SL_SET_ICON, SL_SET_SHOWCMD = 20, 7, 9, 17, 15
SL_QI, PF_LOAD, PF_SAVE = 0, 5, 6


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid(d1, d2, d3, tail):
    return GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*tail))


_IID_TAIL = [0xC0, 0, 0, 0, 0, 0, 0, 0x46]
CLSID_ShellLink = _guid(0x00021401, 0x0000, 0x0000, _IID_TAIL)
IID_IShellLinkW = _guid(0x000214F9, 0x0000, 0x0000, _IID_TAIL)
IID_IPersistFile = _guid(0x0000010B, 0x0000, 0x0000, _IID_TAIL)


def _method(pobj, index, restype, argtypes):
    """取 COM 对象 vtable 里第 index 个方法, 包装成可调用对象。"""
    vtbl = ctypes.cast(ctypes.cast(pobj, POINTER(c_void_p))[0], POINTER(c_void_p))
    return ctypes.WINFUNCTYPE(restype, *argtypes)(vtbl[index])


def _check(hr, what):
    if hr < 0:
        raise OSError("%s 失败: 0x%08X" % (what, hr & 0xFFFFFFFF))


def _create_shell_link():
    ole32 = ctypes.windll.ole32
    ole32.CoCreateInstance.restype = ctypes.HRESULT
    ole32.CoCreateInstance.argtypes = [POINTER(GUID), c_void_p, wintypes.DWORD,
                                       POINTER(GUID), POINTER(c_void_p)]
    psl = c_void_p()
    hr = ole32.CoCreateInstance(byref(CLSID_ShellLink), None, CLSCTX_INPROC_SERVER,
                                byref(IID_IShellLinkW), byref(psl))
    _check(hr, "CoCreateInstance(IShellLinkW)")
    return psl


def _query_persist(psl):
    qi = _method(psl, SL_QI, ctypes.HRESULT,
                 [c_void_p, POINTER(GUID), POINTER(c_void_p)])
    pf = c_void_p()
    _check(qi(psl, byref(IID_IPersistFile), byref(pf)), "QueryInterface(IPersistFile)")
    return pf


def _desktop_dir(csidl):
    """定位桌面目录; 走 SHGetFolderPathW, 这样 OneDrive 改过的桌面也能找对。"""
    shell32 = ctypes.windll.shell32
    buf = ctypes.create_unicode_buffer(MAX_PATH)
    hr = shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    _check(hr, "SHGetFolderPathW")
    return buf.value


def _read_lnk(path):
    """读回一个 .lnk 的现状, 返回 dict; 不存在返回 None。"""
    if not os.path.isfile(path):
        return None
    psl = _create_shell_link()
    pf = _query_persist(psl)
    load = _method(pf, PF_LOAD, ctypes.HRESULT,
                   [c_void_p, wintypes.LPCWSTR, wintypes.DWORD])
    _check(load(pf, path, 0), "IPersistFile.Load")

    path_buf = ctypes.create_unicode_buffer(MAX_PATH)
    desc_buf = ctypes.create_unicode_buffer(MAX_PATH)
    work_buf = ctypes.create_unicode_buffer(MAX_PATH)
    icon_buf = ctypes.create_unicode_buffer(MAX_PATH)
    icon_idx = ctypes.c_int(0)
    showcmd = ctypes.c_int(0)

    get_path = _method(psl, SL_GET_PATH, ctypes.HRESULT,
                       [c_void_p, c_void_p, c_int, c_void_p, wintypes.DWORD])
    _check(get_path(psl, path_buf, MAX_PATH, None, 0), "GetPath")
    _check(_method(psl, SL_GET_DESC, ctypes.HRESULT,
                   [c_void_p, c_void_p, c_int])(psl, desc_buf, MAX_PATH),
           "GetDescription")
    _check(_method(psl, SL_GET_WORKDIR, ctypes.HRESULT,
                   [c_void_p, c_void_p, c_int])(psl, work_buf, MAX_PATH),
           "GetWorkingDirectory")
    _check(_method(psl, SL_GET_ICON, ctypes.HRESULT,
                   [c_void_p, c_void_p, c_int, POINTER(c_int)])(
               psl, icon_buf, MAX_PATH, byref(icon_idx)), "GetIconLocation")
    _check(_method(psl, SL_GET_SHOWCMD, ctypes.HRESULT,
                   [c_void_p, POINTER(c_int)])(psl, byref(showcmd)), "GetShowCmd")
    return {"target": path_buf.value, "description": desc_buf.value,
            "workdir": work_buf.value, "icon": icon_buf.value,
            "icon_index": icon_idx.value, "showcmd": showcmd.value}


def _write_lnk(lnk_path, exe_path, keep=None):
    """写/刷新快捷方式。keep 里带上原 showcmd 之类想保留的属性。"""
    keep = keep or {}
    workdir = os.path.dirname(exe_path)
    psl = _create_shell_link()
    pf = _query_persist(psl)
    _check(_method(psl, SL_SET_PATH, ctypes.HRESULT,
                   [c_void_p, wintypes.LPCWSTR])(psl, exe_path), "SetPath")
    _check(_method(psl, SL_SET_WORKDIR, ctypes.HRESULT,
                   [c_void_p, wintypes.LPCWSTR])(psl, workdir), "SetWorkingDirectory")
    _check(_method(psl, SL_SET_ICON, ctypes.HRESULT,
                   [c_void_p, wintypes.LPCWSTR, c_int])(psl, exe_path, 0),
           "SetIconLocation")
    _check(_method(psl, SL_SET_DESC, ctypes.HRESULT,
                   [c_void_p, wintypes.LPCWSTR])(psl, DESCRIPTION), "SetDescription")
    _check(_method(psl, SL_SET_SHOWCMD, ctypes.HRESULT,
                   [c_void_p, c_int])(psl, int(keep.get("showcmd", 1))), "SetShowCmd")
    save = _method(pf, PF_SAVE, ctypes.HRESULT,
                   [c_void_p, wintypes.LPCWSTR, wintypes.BOOL])
    _check(save(pf, lnk_path, True), "IPersistFile.Save")


def _exists_as_target(exe_path):
    return os.path.isfile(exe_path)


def main(argv=None):
    if not hasattr(ctypes, "windll"):
        print("[FAIL] 快捷方式只在 Windows 上有意义。")
        return 4

    ap = argparse.ArgumentParser(description="刷新桌面上的 %s 快捷方式" % APP_NAME)
    ap.add_argument("--exe", default=DEFAULT_EXE, help="要指向的 exe")
    ap.add_argument("--name", default=DEFAULT_LNK_NAME, help=".lnk 文件名")
    ap.add_argument("--all-users", action="store_true", help="同时刷新公用桌面")
    ap.add_argument("--dry-run", action="store_true", help="只打印, 不写文件")
    args = ap.parse_args(argv)

    exe = os.path.abspath(args.exe)
    if not _exists_as_target(exe):
        print("[FAIL] 找不到 exe: %s" % exe)
        return 1

    ctypes.windll.ole32.CoInitialize(None)
    targets = [("当前用户", _desktop_dir(CSIDL_DESKTOPDIRECTORY))]
    if args.all_users:
        targets.append(("所有用户", _desktop_dir(CSIDL_COMMON_DESKTOPDIRECTORY)))

    changed = 0
    pending = 0
    for label, desktop in targets:
        if not desktop or not os.path.isdir(desktop):
            print("[SKIP] %s桌面目录不存在: %s" % (label, desktop))
            continue
        lnk = os.path.join(desktop, args.name)
        old = _read_lnk(lnk)
        same = (old and os.path.abspath(old["target"]) == exe
                and old["description"] == DESCRIPTION
                and old["workdir"] == os.path.dirname(exe)
                and old["icon"] == exe)
        print("[%s] %s" % (label, lnk))
        if old:
            print("  原指向: %s" % old["target"])
            print("  原说明: %s" % old["description"])
        else:
            print("  原指向: (不存在, 将新建)")
        print("  新指向: %s" % exe)
        print("  新说明: %s" % DESCRIPTION)
        if same:
            print("  状态: 已是最新, 无需改动")
            continue
        if args.dry_run:
            print("  状态: dry-run, 不写入")
            pending += 1
            continue
        _write_lnk(lnk, exe, keep=old or {})
        changed += 1
        print("  状态: 已写入")

    ctypes.windll.ole32.CoUninitialize()
    if args.dry_run and pending:
        print("\n[DRY-RUN] %d 个快捷方式需要改动; 去掉 --dry-run 即可写入。" % pending)
    elif changed:
        print("\n[OK] 刷新 %d 个快捷方式, 现在指向 %s (v%s)"
              % (changed, exe, APP_VERSION))
    else:
        print("\n[OK] 没有需要改动的快捷方式。")
    return 0


if __name__ == "__main__":
    sys.exit(main())