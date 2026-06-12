# 网络工具箱 v3.1.1

<p align="center">
  <img src="https://gitee.com/cpufreestyle/network-reset-tool/releases/download/v3.1/cover.png" width="800" alt="网络工具箱" />
</p>

**一键重置网络配置，自动保留静态 IP · 智能网络诊断 · Windows 7 兼容**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%207%2B-lightgrey.svg)]()
[![Python](https://img.shields.io/badge/Python-3.11-green.svg)]()
[![Version](https://img.shields.io/badge/Version-v3.1.1-orange.svg)]()

修复网络连接问题 · 重置 Winsock/TCP/IP · 清除 DNS/ARP 缓存 · 网络诊断（Ping/DNS/Traceroute）

[下载 exe](#下载) · [报告问题](https://gitee.com/cpufreestyle/network-reset-tool/issues) · [使用说明](#使用方法)

---

## 功能亮点

| 功能 | 说明 |
|:---:|:---|
|  网络重置 | Winsock / TCP/IP / DNS / ARP / DHCP 全部搞定 |
|  静态 IP 保护 | 自动备份并恢复，无需手动记录 |
|  图形界面 | Windows GUI 版，无需命令行 |
|  网络诊断 | Ping 测试 / DNS 解析 / Traceroute / 网络总览 |
|  Windows 7 支持 | 全面兼容 32/64 位 Windows 7+ |
|  macOS 支持 | 完整的 macOS 网络重置工具 |
|  命令行版 | 轻量批处理脚本，兼容 Win7+ |

## 下载

| 版本 | 平台 | 文件 | 说明 |
|:---:|:---:|:---:|:---|
| v3.1.1 | Windows 7/8/10 32-bit | NetworkResetTool_v3_0_win7.exe | GUI 图形界面版（Win7 兼容、免安装） |
| v3.1 | Windows 8/10 64-bit | [网络工具箱.exe](https://gitee.com/cpufreestyle/network-reset-tool/releases/download/v3.1/网络工具箱.exe) | GUI 图形界面版（免安装） |
| v1.0 | Windows | network-reset.bat | 命令行脚本版（需管理员权限） |
| v2.0 | macOS | network_reset_macos.py | GUI 图形界面版（需 sudo） |

> Windows GUI 版需 **以管理员身份运行** 才能正常使用全部功能。

## 新功能 (v3.1.1) - Windows 7 兼容版

### Windows 7 32-bit 全面支持

- **新增字体检测**：`_init_font()` 自动检测系统可用字体，Win7 下首选 Tahoma，替代默认的"微软雅黑"（Win7 SP1 需安装 Microsoft YaHei 补丁）
- **Win7 WMI 回退**：网络状态总览/网卡检测自动使用 WMI（Get-WmiObject）而非 Get-NetAdapter cmdlet
- **DNS 查询回退**：自动使用 nslookup 替代 PowerShell Resolve-DnsName（PS 3.0+ cmdlet，Win7 PowerShell 2.0 不支持）
- **路由追踪回退**：自动使用 tracert.exe 替代 PowerShell Test-NetConnection（PS 4.0+ cmdlet）
- **重启回退**：使用 shutdown.exe 替代 Restart-Computer（更好地兼容各类 Win7 环境）
- **编码兼容**：`_decode_output()` 支持 UTF-16LE 解码（Win7 PowerShell 默认输出编码）
- **32-bit 编译**：使用 Python 3.11.9 32-bit + PyInstaller 6.20 编译，PE 架构 i386
- **UPX 禁用**：避免 32-bit UPX 兼容性问题，EXE 体积约 9.5 MB

### 修复：网络状态总览乱码问题

- **根因**：PowerShell 输出编码与 Python 解码不匹配，导致中文显示为乱码或报错
- **修复**：`_run_ps()` 改为获取原始字节流，自动尝试 UTF-16LE/UTF-8/GBK 解码
- **效果**：网络总览、网卡信息等功能现在可以正确显示中文

### 修复：网络诊断面板多处 Bug

- 修复 Lambda 闭包变量捕获问题（`_thread_quick_ping`、`_thread_overview`、`_thread_full_diagnostic`）
- 修复 `float()` 转换错误（`rc()` 函数遇到非数字值崩溃）
- 修复自定义 Ping 按钮未加入禁用列表的问题
- 修复 `_do_health_report` 调用 `_set_running` 参数错误

### 其他改进

- 改进版本号管理（`__version__` 统一管理）
- 清理无用 exe 文件，减少 Release 附件混乱

---

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

1. 下载对应的 EXE 文件
2. 右键选择 **以管理员身份运行**
3. 切换到 **网络诊断** 标签，先诊断问题
4. 或切换到 **网络重置** 标签，点击 **一键重置全部**
5. 重启电脑使设置生效

### Windows 命令行版

```cmd
:: 右键以管理员身份运行
network-reset.bat
```

### macOS 版

```bash
sudo python3 network_reset_macos.py
```

## 项目结构

```
network-reset-tool/
  network_reset_gui.py      # Windows GUI 源码 (v3.1.1)
  network_reset_macos.py    # macOS GUI 源码 (v2.0)
  network-reset.bat         # Windows 命令行版 (v1.0)
  .gitignore
  LICENSE
  README.md
```

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

<details>
<summary>Win7 下界面字体异常怎么办？</summary>

Win7 SP1 默认不含"微软雅黑"字体。工具会自动检测并回退到 Tahoma。如果仍想使用雅黑字体，可以安装 KB2755131 补丁。
</details>

<details>
<summary>Win7 下某些功能无法使用？</summary>

Win7 上的 PowerShell 版本较旧（2.0），工具已做全面回退处理。如果仍有异常，请确认以管理员身份运行。
</details>

## License

[MIT License](LICENSE) - 2024
