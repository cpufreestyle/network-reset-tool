# 网络工具箱 v4.6

<p align="center">
  <img src="https://gitee.com/cpufreestyle/network-reset-tool/releases/download/v3.1/cover.png" width="800" alt="网络工具箱" />
</p>

**一键重置网络配置，自动保留静态 IP · 智能网络诊断 · Windows 7 兼容**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%207%2B%20%7C%20macOS-lightgrey.svg)]()
[![Python](https://img.shields.io/badge/Python-3.11-green.svg)]()
[![Version](https://img.shields.io/badge/Version-v4.6-orange.svg)]()

修复网络连接问题 · 重置 Winsock/TCP/IP · 清除 DNS/ARP 缓存 · 网络诊断（Ping/DNS/Traceroute）

[下载 exe](#下载) · [GitHub Release v4.6.0](https://github.com/cpufreestyle/network-reset-tool/releases/tag/v4.6.0) · [报告问题](https://gitee.com/cpufreestyle/network-reset-tool/issues) · [使用说明](#使用方法)

---

## 功能亮点

| 功能 | 说明 |
|:---:|:---|
|  网络重置 | Winsock / TCP/IP / DNS / ARP / DHCP 全部搞定 |
|  静态 IP 保护 | 自动备份并恢复，无需手动记录 |
|  图形界面 | Windows GUI 版，无需命令行 |
|  网络诊断 | Ping 测试 / DNS 解析 / Traceroute / 网络总览 |
|  Windows 7 支持 | 全面兼容 32/64 位 Windows 7+ |
|  macOS 支持 | 跨平台 GUI：代理修复 + DNS 刷新（完整重置仅 Windows） |
|  命令行版 | 轻量批处理脚本，兼容 Win7+ |
|  🛡️ 代理修复 | 诊断/修复系统代理指向宕机端口、Clash DNS 关闭导致的外网连不上 |
|  🧹 hosts 检查 | 揪出被写脏的 hosts 映射（指向外部 IP），一键注释、自动备份可还原 |
|  🔌 端口查看 | 列出全部监听端口与对应进程，代理端口高亮，支持过滤与结束进程 |
|  📡 网络监控 | 定时自动体检（默认 5 分钟），掉线自动记时，重启后可回看 |
|  ⚡ DNS 测速 | 对每个 DNS 预设解析同一域名取平均耗时，排序显示，一键应用最快 |
|  💨 网速测试 | 从公开测速端点实测下行带宽（Mbps），可提前停止，纯标准库无依赖 |
|  📶 WiFi 信息 | netsh 列出本机已保存 WiFi 与密码，支持导出，权限不足时明确提示 |
|  🌗 深浅主题 | 顶栏一键切换深色 / 浅色（Catppuccin Mocha / Latte），选择自动记住 |
|  ⌨️ 命令行模式 | `--cli` 无界面子命令，可脚本化 / 进批处理 / CI，`--json` 机器可读 |
|  🔄 自动更新 | 检查新版本并下载安装（仅 exe），全程 SHA256 校验 + 下载域名白名单 |

## 下载

| 版本 | 平台 | 文件 | 说明 |
|:---:|:---:|:---:|:---|
| v4.6.0 | Windows 10/11 64-bit | [NetworkToolbox_x64.exe](https://github.com/cpufreestyle/network-reset-tool/releases/download/v4.6.0/NetworkToolbox_x64.exe) | GUI + CLI 一体（免安装，需管理员运行） |
| v4.6.0 | Windows 7 32-bit | [NetworkToolbox_win7_x86.exe](https://github.com/cpufreestyle/network-reset-tool/releases/download/v4.6.0/NetworkToolbox_win7_x86.exe) | GUI + CLI 一体（Win7 兼容、免安装） |
| v3.2 | Windows 10/11 64-bit | [NetworkToolbox_x64.exe](https://github.com/cpufreestyle/network-reset-tool/releases/download/v3.2/NetworkToolbox_x64.exe) | GUI 图形界面版（免安装） |
| v3.2 | Windows 7 32-bit | [网络工具箱_win7_x86.exe](https://github.com/cpufreestyle/network-reset-tool/releases/download/v3.2/NetworkToolbox_win7_x86.exe) | GUI 图形界面版（Win7 兼容、免安装） |
| v3.1.1 | Windows 7/8/10 32-bit | NetworkResetTool_v3_0_win7.exe | GUI 图形界面版（Win7 兼容、免安装） |
| v3.1 | Windows 8/10 64-bit | [网络工具箱.exe](https://gitee.com/cpufreestyle/network-reset-tool/releases/download/v3.1/网络工具箱.exe) | GUI 图形界面版（免安装） |
| v1.0 | Windows | network-reset.bat | 命令行脚本版（需管理员权限） |
| v3.3 | macOS (源码运行) | network_reset_gui.py | 跨平台 GUI（代理修复 + DNS 刷新，需 sudo） |
> v4.6.0 校验和（SHA256）：`90A5629E1B4B526E49737925BC662E8C137C7F3689C0CFCBEC90CFCFCEF1B5C4`、`755F3A9DCC6E080408E5D7292D192F76DDCBA70E7E5A4A40E64B4E36C8FC922E` —— Release 内附 `sha256sums.txt`（两行），下载后可用 `Get-FileHash -Algorithm SHA256 NetworkToolbox_x64.exe`、`Get-FileHash -Algorithm SHA256 NetworkToolbox_win7_x86.exe` 逐个核对。

> Windows GUI 版需 **以管理员身份运行** 才能正常使用全部功能。

## 新功能 (v3.6) - hosts 检查 / 端口查看 / 自动更新

### 🧹 hosts 检查（「🔍 网络诊断」标签页）

- 逐条列出 hosts 里的域名映射，**指向外部 IP** 的一律标红（解析可能被劫持）
- `0.0.0.0` / `127.0.0.1` / 内网地址视为正常（本地开发或广告屏蔽）
- 「🚿 注释可疑条目」：**先自动备份**再注释，原始内容保留
- 「♻️ 从备份还原」：随时回滚到备份（备份在 `%LOCALAPPDATA%/NetworkResetTool/hosts_backups/`）
- 写入需要管理员权限，只读检查不需要

### 🔌 端口查看（新增「🔌 端口查看」标签页）

- 列出本机所有 **LISTENING** 端口、协议、监听地址、PID 与进程名
- 代理端口（7890/7891/7897/10809/9090 等）高亮，排查"代理软件端口没人听"一眼定位
- 支持按端口 / PID / 进程名实时过滤
- 「⛔ 结束进程」强杀选中进程（Windows `taskkill /F`，macOS `kill -9`）
- 命令行菜单同步新增「[5] 端口查看」

### 🔄 检查更新（标题栏右侧）

- 点击「🔄 检查更新」从 Gitee Release 拉取最新版本，发现新版本可一键下载安装
- 下载走 **SHA256 校验**（校验文件缺失或不匹配一律中止，fail-closed），只允许 gitee.com 域名
- 仅打包后的 exe 支持自动更新；源码运行会提示用 git pull

### 工程化

- 单文件拆分为 `network_toolbox/` 包（_shared / engine / report / ui_panels / app），`network_reset_gui.py` 变为 27 行兼容入口
- `version_info.txt` 改由 `python gen_version_info.py` 从 `APP_VERSION` 生成，版本号单一来源
- 冒烟自检扩充到 191 项（`python tests/smoke_test.py --gui`）

## 命令行模式（F10）— `--cli`

GUI 之外另给一条无界面入口，给批处理、运维脚本和无人值守场景用。**不建窗口、不弹对话框**，
没有桌面会话的服务器 / SSH / CI 里同样能跑；所有结果走退出码 + stderr，绝不用弹窗汇报失败。

```cmd
网络工具箱.exe --cli <命令> [--adapter NAME] [--lang zh|en] [--json]
```

| 命令 | 作用 |
|:---|:---|
| `adapters` | 列出本机网卡（只读，先跑它拿 `--adapter` 的可选值） |
| `diagnose` | 完整网络诊断 + 健康评分 |
| `reset` | 完整网络重置（需管理员，仅 Windows） |
| `dns` | 查看 / 切换 DNS：`--preset` / `--auto` / `--set 主 备` |
| `proxy` | 代理诊断，加 `--repair` 一键修复 |
| `ports` | 列出监听端口，`--filter` 过滤，`--kill PID` 结束进程 |
| `speed` | 实测下行带宽，`--max-seconds` / `--max-mb` 设上限 |
| `wifi` | 列出已保存 WiFi 与密码，`--export` 导出 txt |
| `monitor` | 查看 / `--clear` 清空掉线记录 |
| `snapshots` | 列出快照，`--rollback` 回滚（`--restore-ip` 才恢复静态 IP） |
| `report` | 生成诊断报告（`--format html/txt/md`，`--out` 指定路径） |
| `hosts` | 检查 hosts 映射，`--fix` 一键注释可疑条目 |

- **`--json`**：stdout 只打印一个 JSON 对象（`ok` / `command` / `data` / `warnings`），
  日志全走 stderr，可以直接 `... --json | jq` / `ConvertFrom-Json` 消费，无 BOM。
- **`--lang zh|en`**：切换界面/命令行输出语言（默认中文）。缺省读 `%LOCALAPPDATA%/NetworkResetTool/lang.txt`，
  本次参数只影响本次进程，不会改写你保存的语言偏好。
- **退出码**：`0` 成功 / `1` 操作失败 / `2` 参数错误 / `3` 需要管理员 / `4` 平台不支持 / `130` 被 Ctrl+C 取消。
- 每个命令的详细参数：`网络工具箱.exe --cli <命令> --help`。
- 命令行模式**不占用 GUI 的单例端口**，跑 CLI 不会阻塞随后启动的图形界面。

> Windows 控制台默认 GBK，中文输出的脚本建议先 `chcp 65001`，或直接加 `--json` 规避编码问题。

## 新功能 (v4.5) - 中英文界面切换

### 🌐 多语言（顶栏「🌐 中文 / 🌐 EN」按钮，F12）

- 顶栏新增语言按钮（在主题按钮左侧），一键在**中文 / English** 之间切换；切换后整树重建界面，**当前标签页不丢**
- 设计上**以中文字符串本身作为 key**：源码里写的是什么，中文界面就显示什么，`i18n.py` 的英文目录只写差异
- 英文目录缺失时自动回落中文，**永远不会因为漏翻译而 KeyError**——新文案忘了翻译也只是显示中文，不会崩
- 正则与 netsh 输出的解析标记（简体/繁体的「所有用户配置文件」「金钥内容」等）**刻意不进目录**，避免翻译改变匹配行为；程序名同样不翻译
- 语言偏好持久化到 `%LOCALAPPDATA%/NetworkResetTool/lang.txt`，与 `theme.txt` 同一套模式：缺失 / 损坏 / 非法值都安全回落中文，写失败也不影响本次生效
- GUI 与 CLI 双向打通：`网络工具箱.exe --lang en --cli adapters` 可让命令行也输出英文，`--cli --help` 的说明同样跟随语言
- 冒烟自检守住硬门闩：**任何新增的 `tr("...")` 中文文案都必须有英文翻译**，漏一条立刻报红

## 新功能 (v4.6) - 插件式诊断项

### 🧩 插件式诊断（F13）

- 完整诊断被拆成一组**可注册的诊断项**：内置 `overview` / `ping` / `dns` 三项照旧，第三方可以用一行代码追加自己的检查
- API 只有 5 个函数：`DiagnosticItem(key, run, title, fallback)` + `register_item()` / `unregister_item()` / `diagnostic_items()` / `custom_keys()`；引擎的 `run_full_diagnostic()` 只负责按注册顺序驱动
- **单个插件抛异常只掉自己**（换成 `fallback`），不会再把「诊断」按钮整体拖死
- 内置三项**不可被覆盖或注销**，UI 与报告永远拿得到 `overview` / `ping` / `dns` 三段数据
- key 限定为 ASCII 标识符（可用点号做命名空间，如 `myplug.check`）；中文/连字符一律拒绝，JSON 与命令行输出不会被搞脏
- 顶库一并修好两件 F6/F12 遗留：测速的 User-Agent 带中文名称，urllib 以 latin-1 编码请求头
  导致每次请求直接抛异常（功能实际上完全不可用）；另外把 CLI 剩余的 f-string 中文改跟 `tr_f()`，
  现在 `--lang en` 下各子命令输出零中文残留
- 诊断进度节奏与 v4.5 **完全一致**（0% -> 10~50% -> 55~95% -> 100%），界面零变化

## 新功能 (v4.3) - 深色/浅色主题切换

### 🌗 深浅主题（标题栏右侧，F11）

- 顶栏新增「🌙 深色 / ☀️ 浅色」按钮，一键整套换色，**当前标签页不丢**
- 配色为两套语义化主题表：深色 Catppuccin Mocha、浅色 Catppuccin Latte，
  共 20 个语义键（`bg`/`surface`/`surface2`/`bg2`/`text`/`subtext`/`muted`/
  12 个强调色 + `card` 内容卡底色 + `warn_bg`/`warn_fg` 警示横幅）
- **选择会被记住**：写入 `%LOCALAPPDATA%/NetworkResetTool/theme.txt`，下次启动自动套用；
  文件缺失或内容损坏时安全回落到深色，不会开不了机
- 换色采用「就地覆写 `COLORS` + 整树重建」：UI 里 `from ... import COLORS` 拿到的是
  同一个 dict 引用，换主题后所有面板同步变色，不存在漏刷新的模块
- 三处表格（端口 / 监控事件 / WiFi）与 5 处滚动条统一切到主题化样式，浅色下不再是"白底黑字"的违和感；导出的 HTML 诊断报告也跟随当前主题
- 冒烟自检守住两点：**两套主题的语义键集合必须完全一致**（少一个键换主题就 KeyError）、
  `ui_panels.py` 不许再出现写死的主题专属底色

## 新功能 (v4.2) - WiFi 信息管理

### 📶 WiFi 信息（新增「📶 WiFi 信息」标签页，F8）

- 列出**本机保存过的所有 WiFi**（自己 / 家人 / 旧手机连过的），表格展示 SSID / 密码 / 认证方式
- 密码通过 `netsh wlan show profile ... key=clear` 回读；**读取密码需要管理员权限**，非管理员启动时界面顶部给出醒目提示，密码列显示「未取到」
- 逐个条目汇总（「共 N 个已保存 WiFi，取到密码 M 个」），未取到的多为开放网络或权限不足
- 「💾 导出」把列表写成 txt（含明文密码，导出前弹窗警示妥善保管）
- 命令全部以参数列表执行（不经 shell），SSID 含空格/引号也不会注入；netsh 输出兼容**简体 / 繁体 / 英文**三套系统语言
- 非 Windows 平台自动提示改用「🔍 网络诊断」标签页；服务未启动 / 拒绝访问 / 配置文件不存在各有明确报错
- 启动参数直达：`网络工具箱.exe --tab wifi`；命令行菜单同步新增「[7] WiFi 信息（已保存密码）」

## 新功能 (v4.1) - 网速测试

### 💨 网速测试（新增「💨 网速测试」标签页，F6）

- 从公开测速端点（Cloudflare / CacheFly / OVH）下载固定大小数据，**实测下行带宽**（大数字 + Mbps）
- 同时给出首包延迟、下载流量、耗时与所用端点；**最多 12 秒 / 64MB，先到先停**，不会挂死
- 测速中实时显示「已下载 X MB · 当前 Y Mbps」；随时可「⏹ 停止」——已下载部分仍按实测窗口估算
- 全部端点失败时给出明确原因（网络/代理/防火墙），不抛异常、不卡界面
- 纯标准库 urllib 实现，无第三方依赖；命令行菜单同步新增「[6] 网速测试」
- 启动参数直达：`网络工具箱.exe --tab speed`

## 新功能 (v4.0) - 定时网络监控 / DNS 批量测速

### 📡 网络监控（新增「📡 网络监控」标签页，F7）

- 周期性 Ping **默认网关 + 223.5.5.5**（默认每 5 分钟，间隔 1~1440 分钟可调）
- 判定保守：**任一目标通即在线**，全部不通才算掉线——单目标抖动不误报
- 掉线事件（开始/恢复时间 + 持续时长）落盘 `%LOCALAPPDATA%/NetworkResetTool/monitor/outages.json`，**重启后可回看**
- 恢复后给出汇总，例如「14:23–14:27 断网 4 分钟」；汇总卡片显示次数/合计时长/最近一次
- 停止监控只停巡检，历史记录保留；「🗑 清空记录」需二次确认
- 命令行可用 `网络工具箱.exe --tab monitor` 直接打开该标签页

### ⚡ DNS 批量测速（「🔄 网络重置」标签页 DNS 区，F9）

- 对每个静态 DNS 预设解析同一域名（www.baidu.com）**各 3 次取平均耗时**
- 按快慢排序显示（阿里 12ms / Cloudflare 18ms / 114 25ms…），全程只测速、不改设置
- 「🏆 应用最快」一键把最快的 DNS 设到当前网卡
- 部分轮次失败会标注失败次数；某 DNS 全部失败排到最后

### 工程化

- 引擎层 `NetworkMonitor`（线程安全：worker 只采数据，UI 刷新走 `ui_sync` 回主线程）
- 修复监控回调在锁内触发导致 `on_event` → `summarize()` 互等死锁的隐患（界面整体卡死）
- 冒烟自检扩充到 232 项（`python tests/smoke_test.py --gui`）

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

## 新功能 (v3.2) - 代理修复（针对"外网连不上"）

新增第三个标签页 **🛡️ 代理修复**，专门解决两类最常见的"能上网但外网连不上"根因：

### 能诊断的问题
- **系统代理指向已宕机的端口**：例如浏览器/系统走 `127.0.0.1:7897`，但该端口没有任何服务在监听，导致外网全部失败（常见于 Comet、Chrome 等被写死代理端口的浏览器）。
- **Clash(mihomo) 的 DNS 被关闭**：订阅里 `dns.enable: false` 却配了 `enhanced-mode: fake-ip`，互相矛盾，导致所有域名解析 `i/o timeout`。
- **代理核心端口探测**：自动发现正在运行的 Clash / mihomo 核心，并读取其真正的代理端口（`mixed-port`）。

### 一键修复
- 系统代理端口死了 → 自动把系统代理重新指向正在工作的 Clash 代理端口。
- Clash DNS 被关 → 自动把 `clash-config.yaml` 与 `clash-guard-overrides.yaml` 的 `dns.enable` 改为 `true`（guard 覆盖确保订阅更新后不回退），并通过外部控制接口重启核心使其生效。

> 修复逻辑在 `ProxyRepairTool` 类中，UI 在 `ProxyPanel` 标签页中。Clash 配置目录会自动按优先级探测常见位置（`%LOCALAPPDATA%/moe.elaina.clash.nyanpasu/.config/clash-verge` 等），无需手动指定。

### 构建产物（两版并存）

- `网络工具箱.exe` —— 64-bit（PE x64），适用于 Windows 10/11。
- `网络工具箱_win7_x86.exe` —— 32-bit（PE i386），使用 Python 3.11.9 32-bit + PyInstaller 6.20 编译，兼容 Windows 7 32 位。

> 编译命令（32 位）：`py -3.11-32 -m PyInstaller 网络工具箱.spec --distpath dist32`

---

## 新功能 (v3.3) - 跨平台（macOS）支持

GUI 源码现在跨平台，同一份 `network_reset_gui.py` 可在 **Windows** 与 **macOS** 上运行。

### macOS 上支持的能力

| 功能 | macOS 实现 |
|:---:|:---|
| 🛡️ 代理修复（诊断/一键修复） | Clash 控制器 HTTP + 配置（纯文件/HTTP，两端复用） |
| Clash 死节点自动切换 | 检测当前选中节点 delay=0，自动切到 URLTest 自动选择组 |
| 系统代理读取/设置 | `networksetup -getwebproxy / -setwebproxy` |
| DNS 刷新 | `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder` |
| DNS 设置/切换 | `networksetup -setdnsservers`（"网络重置"标签页里的自定义 DNS 按钮在 Mac 上保留可用） |
| ARP 清除 | `sudo arp -ad` |
| 代理核心发现 | `lsof -iTCP -sTCP:LISTEN` |
| Clash 配置目录探测 | `~/Library/Application Support/clash-verge-rev/config`、`~/.config/...` |

### macOS 上不支持（自动禁用并提示）

- 完整网络重置：Winsock / TCP-IP / DHCP / 静态 IP 备份恢复（这些是 Windows 专属命令，macOS 无等价物）。
- 对应 GUI 按钮在 macOS 上会被禁用，并弹出横幅提示改用「🛡️ 代理修复」标签页。

### 技术实现

- 新增 `IS_WINDOWS` / `IS_MAC` 平台常量，`is_admin()` 在 macOS 下用 `os.geteuid()==0` 判断。
- 所有平台相关调用（代理/端口发现/Clash 目录/DNS/ARP）均按 `sys.platform` 分流，Windows 路径完全不变。

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
5. 若"外网连不上"但本地网络正常，切换到 **🛡️ 代理修复** 标签，先 **诊断代理** 再 **一键修复**
6. 重启电脑使设置生效

### Windows 命令行版

```cmd
:: 右键以管理员身份运行
network-reset.bat
```

启动后菜单：

1. 完整网络重置（6阶段）
2. 快速 DNS 切换
3. 网络诊断
4. **代理修复** —— 一键打开 GUI 并直接定位到「🛡️ 代理修复」标签页（优先用 `网络工具箱.exe`，Win7 32 位回退到 `网络工具箱_win7_x86.exe`，均无则回退到 `python network_reset_gui.py --tab proxy`）
5. 退出

> 也可直接用 GUI 启动参数打开指定标签页：`--tab` 支持 `reset` / `diagnostic` / `proxy` / `ports` / `monitor` / `speed` / `wifi`

### macOS 版（源码运行）

本工具的 GUI 源码（`network_reset_gui.py`）已跨平台，macOS 上可直接用同一份源码运行：

```bash
# 需 Python 3.11 + Tkinter（brew install python-tk）
sudo python3 network_reset_gui.py
```

> 代理修复 / 系统代理设置 / DNS 刷新等需要管理员权限，请用 `sudo` 运行。
> 「网络重置」标签页里的完整重置（Winsock/TCP-IP/DHCP/静态IP）仅支持 Windows，
> 在 macOS 上会自动禁用并提示改用「🛡️ 代理修复」标签页。

#### macOS 打包成 .app（在 Mac 上执行）

```bash
# 1. 安装依赖
brew install python-tk
python3 -m pip install pyinstaller

# 2. 打包（spec 已兼容 macOS）
python3 -m PyInstaller 网络工具箱.spec --name "网络工具箱"

# 3. 产出 dist/网络工具箱.app，拖进 /Applications 即可双击运行
```

> 注意：`sudo` 设置的代理可能需要授权，首次运行系统会弹出"终端/网络设置"权限请求，允许即可。

## 项目结构

```
network-reset-tool/
  network_reset_gui.py      # GUI 兼容入口(27 行, PyInstaller 打包目标)
  network_toolbox/          # 实现包(v3.5 拆分)
    _shared.py              #   模块级函数/常量: 解码/校验/单例/字体/按钮/ASCII User-Agent
    i18n.py                 #   界面多语言: 中/英切换 + 英文翻译目录(F12)
    engine.py               #   引擎: 重置/诊断/代理修复/hosts/端口/监控/测速/WiFi
    plugins.py              #   插件式诊断项注册表: 内置三项 + 第三方可扩展(F13)
    report.py               #   诊断报告渲染(HTML/TXT/MD)
    ui_panels.py            #   面板: 重置/诊断/代理/端口/监控/测速/WiFi(ResultPanel)
    app.py                  #   主窗口 App 与 main() 入口
  auto_updater.py           # 自动更新(SHA256 + 域名白名单)
  network-reset.bat         # Windows 命令行版(含端口查看 / WiFi 信息菜单)
  gen_version_info.py       # 从 APP_VERSION 生成 version_info.txt
  update_shortcut.py        # 刷新桌面快捷方式, 指向 dist/ 里最新的 exe
  gen_icon.py               # 生成应用图标 icon.ico(圆角蓝底+地球网+健康徽标, 7 种尺寸)
  网络工具箱.spec           # PyInstaller 打包配置
  tests/smoke_test.py       # 冒烟自棅(413 项; --gui 合计 453 项)
  .github/workflows/ci.yml  # CI: 三平台 compileall + Windows 冒烟 / GUI 自检 + tag 构建三平台产物
  legacy/                   # 归档: 旧 macOS 单文件脚本
  .gitignore
  LICENSE
  README.md
```

## 技术栈

- **Windows GUI**: Python 3.11 + Tkinter + ctypes
- **macOS GUI**: Python 3.11 + Tkinter + networksetup
- **CLI**: Python 3.11（argparse，`--json` 机器可读输出）+ Batch 菜单脚本
- **打包**: PyInstaller（`网络工具箱.spec` 入 git）+ 自定义图标 `gen_icon.py`（圆角蓝底 + 地球网 + 健康徽标，7 种尺寸）
- **测试**: `tests/smoke_test.py` 冒烟自检 413 项，`--gui` 合计 453 项

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
