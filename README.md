# Network Reset Tool

**一键重置网络配置，自动保留静态 IP**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-lightgrey.svg)]()
[![Python](https://img.shields.io/badge/Python-3.6%2B-green.svg)]()
[![Version](https://img.shields.io/badge/Version-v2.2-orange.svg)]()

修复网络连接问题 · 重置 Winsock/TCP/IP · 清除 DNS/ARP 缓存 · 网络诊断（Ping/DNS/Traceroute）

[下载 exe](https://gitee.com/cpufreestyle/network-reset-tool/releases/tag/v2.2) · [报告问题](https://gitee.com/cpufreestyle/network-reset-tool/issues) · [使用说明](#使用方法)

---

## 功能亮点

| 功能 | 说明 |
|:---:|:---|
|  网络重置 | Winsock / TCP/IP / DNS / ARP / DHCP 全部搞定 |
|  静态 IP 保护 | 自动备份并恢复，无需手动记录 |
|  图形界面 | Windows GUI 版，无需命令行 |
|  网络诊断 | Ping 测试 / DNS 解析 / Traceroute / 网络总览 |
|  macOS 支持 | 完整的 macOS 网络重置工具 |
|  命令行版 | 轻量批处理脚本，兼容 Win7+ |

## 下载

| 版本 | 平台 | 文件 | 说明 |
|:---:|:---:|:---:|:---|
| v2.2 | Windows | [NetworkReset.exe](https://gitee.com/cpufreestyle/network-reset-tool/releases/download/v2.2/NetworkReset.exe) | GUI 图形界面版（免安装） |
| v1.0 | Windows | network-reset.bat | 命令行脚本版（需管理员权限） |
| v2.0 | macOS | network_reset_macos.py | GUI 图形界面版（需 sudo） |

> Windows GUI 版需 **以管理员身份运行** 才能正常使用全部功能。

## 新功能 (v2.2)

### Tab 布局重构

左侧 **网络重置** | 右侧 **网络诊断**，一工具两用

### 新增：网络诊断面板

- **一键完整诊断**：自动运行所有检测，给出结论和建议
- **Ping 连通性测试**：5 个目标（Google DNS / Cloudflare / 阿里 DNS / 百度 / 腾讯），实时显示延迟和丢包率
- **DNS 解析测试**：测试各 DNS 服务器（阿里/Google/Cloudflare）的解析能力
- **网络状态总览**：显示当前 IP / 网关 / DNS / MAC / 网卡名 / 连接速度
- **Traceroute**：追踪本机到目标的网络路由路径
- **快速 Ping / 自定义 Ping**：一键检测，自定义目标地址
- **颜色反馈**：绿色=正常 / 红色=故障，一目了然

## 使用方法

### Windows GUI 版（推荐）

1. 下载 [NetworkReset.exe](https://gitee.com/cpufreestyle/network-reset-tool/releases/download/v2.2/NetworkReset.exe)
2. 右键选择 **以管理员身份运行**
3. 切换到 **网络诊断** 标签，先诊断问题
4. 或切换到 **网络重置** 标签，点击 **一键重置全部**
5. 重启电脑使设置生效

### Windows 命令行版

`cmd
:: 右键以管理员身份运行
network-reset.bat
`

### macOS 版

`ash
sudo python3 network_reset_macos.py
`

## 项目结构

`
network-reset-tool/
  network_reset_gui.py      # Windows GUI 源码 (v2.2)
  network_reset_macos.py    # macOS GUI 源码 (v2.0)
  network-reset.bat         # Windows 命令行版 (v1.0)
  .gitignore
  LICENSE
  README.md
`

## 技术栈

- **Windows GUI**: Python 3 + Tkinter + ctypes
- **macOS GUI**: Python 3 + Tkinter + networksetup
- **CLI**: Windows Batch + PowerShell

## 常见问题

<details>
<summary>为什么要重置网络？</summary>

网络突然无法连接、DNS 解析失败、VPN 重新连接后恢复不了等，通常可以通过重置网络配置解决。
</details>

<details>
<summary>静态 IP 会被清除吗？</summary>

不会。工具会在重置前自动备份所有静态 IP 配置，重置后自动恢复。
</details>

<details>
<summary>需要重启吗？</summary>

- Winsock 重置：建议重启
- TCP/IP 重置：必须重启
- DNS/ARP/DHCP 刷新：通常不需要
- 一键重置全部：建议重启
</details>

## License

[MIT License](LICENSE) - 2024
