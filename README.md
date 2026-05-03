<div align="center">

# 🌐 Network Reset Tool

**一键重置网络配置，自动保留静态 IP**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-lightgrey.svg)]()
[![Python](https://img.shields.io/badge/Python-3.6%2B-green.svg)]()
[![Version](https://img.shields.io/badge/Version-v2.1-orange.svg)]()

修复网络连接问题 · 重置 Winsock/TCP/IP · 清除 DNS/ARP 缓存

[下载 exe](https://gitee.com/cpufreestyle/network-reset-tool/releases/tag/v2.1) · [报告问题](https://gitee.com/cpufreestyle/network-reset-tool/issues) · [使用说明](#使用方法)

</div>

---

## ✨ 功能亮点

| 功能 | 说明 |
|:---:|:---|
| 🚀 一键重置 | Winsock / TCP/IP / DNS / ARP / DHCP 全部搞定 |
| 💾 静态 IP 保护 | 自动备份并恢复，无需手动记录 |
| 🖥️ 图形界面 | Windows GUI 版，无需命令行 |
| 🍎 macOS 支持 | 完整的 macOS 网络重置工具 |
| 📋 命令行版 | 轻量批处理脚本，兼容 Win7+ |

## 📦 下载

| 版本 | 平台 | 文件 | 说明 |
|:---:|:---:|:---:|:---|
| v2.1 | Windows | [NetworkReset.exe](https://gitee.com/cpufreestyle/network-reset-tool/releases/download/v2.1/NetworkReset.exe) | GUI 图形界面版（免安装） |
| v1.0 | Windows | `network-reset.bat` | 命令行脚本版（需管理员权限） |
| v2.0 | macOS | `network_reset_macos.py` | GUI 图形界面版（需 sudo） |

> ⚠️ Windows GUI 版需 **以管理员身份运行** 才能正常使用全部功能。

## 🖼️ 截图

### Windows GUI 版 v2.1

![Windows GUI](https://gitee.com/cpufreestyle/network-reset-tool/attached_images/screenshot.png)

> 界面采用 Catppuccin Mocha 配色方案，支持一键重置和单独操作。

## 使用方法

### Windows GUI 版（推荐）

1. 下载 [NetworkReset.exe](https://gitee.com/cpufreestyle/network-reset-tool/releases/download/v2.1/NetworkReset.exe)
2. 右键 → **以管理员身份运行**
3. 点击 **🚀 一键重置全部**
4. 重启电脑使设置生效

### Windows 命令行版

```cmd
:: 右键以管理员身份运行
network-reset.bat
```

### macOS 版

```bash
sudo python3 network_reset_macos.py
```

## 📁 项目结构

```
network-reset-tool/
├── network_reset_gui.py      # Windows GUI 版源码 (v2.1)
├── network_reset_macos.py    # macOS GUI 版源码 (v2.0)
├── network-reset.bat         # Windows 命令行版 (v1.0)
├── .gitignore
├── LICENSE
└── README.md
```

## 🔧 技术栈

- **Windows GUI**: Python 3 + Tkinter + ctypes
- **macOS GUI**: Python 3 + Tkinter + networksetup
- **CLI**: Windows Batch + PowerShell

## ❓ 常见问题

<details>
<summary><b>为什么要重置网络？</b></summary>

网络突然无法连接、DNS 解析失败、VPN 断连后恢复不了等问题，通常可以通过重置网络配置解决。
</details>

<details>
<summary><b>静态 IP 会被清除吗？</b></summary>

不会。工具会在重置前自动备份所有静态 IP 配置，重置后自动恢复。
</details>

<details>
<summary><b>需要重启吗？</b></summary>

- Winsock 重置：建议重启
- TCP/IP 重置：必须重启
- DNS/ARP/DHCP 刷新：通常不需要
- 一键重置全部：建议重启
</details>

<details>
<summary><b>安全吗？</b></summary>

完全离线运行，不联网、不上传任何数据。仅调用 Windows/macOS 自带的网络管理命令。
</details>

## 📄 License

[MIT License](LICENSE) © 2024