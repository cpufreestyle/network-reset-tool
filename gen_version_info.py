#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 network_toolbox._shared.APP_VERSION 生成 version_info.txt(版本号单一来源)。

用法:  python gen_version_info.py
版本号只改 _shared.py 的 APP_VERSION 一处, 打包前跑一次本脚本即可,
version_info.txt 不再手工维护, 避免版本号散落多处的漂移老问题。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from network_toolbox._shared import APP_NAME, APP_VERSION  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version_info.txt")


def main():
    parts = [int(x) for x in APP_VERSION.split(".") if x.isdigit()]
    while len(parts) < 4:
        parts.append(0)
    v = tuple(parts[:4])
    vstr = ".".join(str(x) for x in v)
    short = ".".join(str(x) for x in v[:2])
    lines = [
        "VSVersionInfo(",
        "  ffi=FixedFileInfo(",
        "    filevers=%s," % (v,),
        "    prodvers=%s," % (v,),
        "    mask=0x3f,",
        "    flags=0x0,",
        "    OS=0x40004,",
        "    fileType=0x1,",
        "    subtype=0x0,",
        "    date=(0, 0)",
        "  ),",
        "  kids=[",
        "    StringFileInfo(",
        "      [",
        "        StringTable(",
        "          u'080404B0',",
        "          [StringStruct(u'CompanyName', u'CPUFreeStyle'),",
        "          StringStruct(u'FileDescription', u'%s %s - 一键重置网络 (Win7 兼容版)')," % (APP_NAME, short),
        "          StringStruct(u'FileVersion', u'%s')," % vstr,
        "           StringStruct(u'InternalName', u'%s')," % APP_NAME,
        "           StringStruct(u'LegalCopyright', u'Copyright (C) 2026 CPUFreeStyle'),",
        "           StringStruct(u'OriginalFilename', u'%s.exe')," % APP_NAME,
        "           StringStruct(u'ProductName', u'%s')," % APP_NAME,
        "           StringStruct(u'ProductVersion', u'%s')])" % vstr,
        "      ]),",
        "    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])",
        "  ]",
        ")",
        "",
    ]
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("version_info.txt -> " + vstr)


if __name__ == "__main__":
    main()
