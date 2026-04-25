# 网络重置工具

Windows / macOS 网络重置工具，自动保留静态 IP 配置。

## 版本说明

| 版本 | 平台 | 说明 |
|------|------|------|
| v2.0+ | Windows | 图形界面版 (GUI) |
| v1.0 | Windows | 命令行脚本 (bat) |
| v2.0 | macOS | 图形界面版 (GUI) |

## 功能

- 重置 Winsock / 网络接口
- 重置 TCP/IP 协议栈
- 清除 DNS / ARP 缓存
- 刷新 DHCP
- **自动备份并恢复静态 IP 配置**

## Windows GUI 版 (v2.0+)

图形界面一键操作，无需命令行。提供单独操作按钮（Winsock、TCP/IP、DNS、ARP、DHCP）和一键重置全部功能。

- 以管理员身份运行
- 点击「一键重置全部」或单独操作
- 完成后建议重启电脑

## Windows 命令行版 (v1.0)

`atch
# 右键 → 以管理员身份运行
network-reset.bat
`

## macOS 版

`ash
sudo python3 network_reset_macos.py
`

## 兼容性

- Windows 7+ (32/64 位)
- macOS (需要 sudo 权限)

## License

MIT