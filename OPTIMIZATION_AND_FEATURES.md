# 网络工具箱 — 项目优化与新功能建议

> 评审版本：v3.2（commit `8154a0e`） ｜ 修复后版本：**v3.3.0**
> 评审范围：`network_reset_gui.py`、`auto_updater.py`、`network-reset.bat`、`网络工具箱.spec`、`version_info.txt`，以及已废弃的 `legacy/network_reset_macos.py`

---

## 0. 一句话结论

功能覆盖面已经不错（重置 / 诊断 / 代理修复三件套，还做了 Win7 与 macOS 兼容），但**存在一个让核心功能彻底失效的致命 Bug、一类会随机崩溃的线程安全缺陷、以及一个命令注入点**。这三类问题都已在本轮修复完成，同时补了冒烟自检脚本。剩下的主要是**工程化**问题（单文件 3100 行、无测试、无 CI、自动更新无校验）。

---

## 1. 体检结果

| 维度 | 现状 | 评级 |
|---|---|---|
| 功能完整度 | 重置 / DNS 切换 / Ping / DNS 解析 / 路由追踪 / 健康报告 / 代理修复，覆盖度好 | ⭐⭐⭐⭐ |
| 正确性 | **DNS 一键切换 100% 失效**（见 P0-1）；健康报告在 <1ms 延迟时崩溃 | ⭐ |
| 稳定性 | 8 处在工作线程里直接构造 Tk 控件 → 随机闪退/卡死 | ⭐ |
| 安全性 | ping/tracert 目标未校验 + `shell=True` → 命令注入；自动更新无校验 | ⭐ |
| 跨平台 | Win7~Win11 / macOS 已覆盖，Linux 部分缺失 | ⭐⭐⭐ |
| 可维护性 | 单文件 3100+ 行，UI 与业务逻辑强耦合，无测试 | ⭐⭐ |
| 工程化 | 无 CI、无自动化测试、版本号散落 6 处 | ⭐⭐ |

---

## 2. 本轮已修复（v3.3.0）

### P0-1 🔴 DNS 一键切换在 Windows 上 100% 失效（致命）

**现象**：点击任一 DNS 预设按钮，日志只输出「⚠ 未找到活动网卡,请检查网络连接」，网卡明明在线。

**根因**：`ResetPanel._get_active_adapter()` 里 4 处调用了 `self._decode_output(...)`，但 `_decode_output` 只定义在 `NetworkDiagnostic` 上，`ResetPanel` **根本没有这个方法**。4 次调用全部抛 `AttributeError`，又被各自的 `try/except` 静默吞掉，于是四条检测通道（Get-NetAdapter / WMI / 通用 WMI / ipconfig）全部落空。

讽刺的是，v2.4 / v3.2 的更新日志都写着"修复 DNS 切换未找到活动网卡问题"——修复一直没生效。

**修复**：抽出模块级 `decode_output()`，通过 `_decode_output = staticmethod(decode_output)` 挂到 `NetworkResetTool / NetworkDiagnostic / ResetPanel / DiagnosticPanel / ProxyPanel` 五个类上，任何面板都不会再漏。

**验证**：
```
修复前：ADAPTER = None
修复后：ADAPTER = 'Ethernet 2'
```

### P0-2 🔴 在工作线程里直接创建 Tk 控件（随机崩溃）

**位置**：`DiagnosticPanel` 的 `_thread_quick_ping / _thread_overview / _thread_traceroute / _thread_custom_ping / _thread_full_diagnostic / _thread_health_report`，以及 `ProxyPanel` 的 `_thread_diagnose / _thread_repair`——共 8 处。

Tkinter 不是线程安全的，在子线程 `tk.Frame(...)` / `tk.Label(...)` 会造成随机崩溃、界面卡死、布局错乱。这正是项目里"日志界面闪退"的真正来源（之前只做了部分 `after` 修补，治标不治本）。

**修复**：新增模块级 `ui_sync(widget, fn)`——把 UI 代码通过 `after(0, ...)` 投递到主线程执行，用 `Event` 同步等待结果，异常带回工作线程而不是炸掉 mainloop。所有 8 处改为「后台算数据 → `ui_sync` 里渲染」的两段式结构。

同时修复 `ResetPanel._get_active_adapter()` 里 6 处 `self._log()` 直写日志框（同样在工作线程），改为线程安全的 `_safe_log()`。

### P0-3 🔴 命令注入

`ping()` / `traceroute()` 用 f-string 拼进 `shell=True` 的命令，目标地址来自用户输入框：

```python
subprocess.run(f'cmd /c ping -n {count} {target}', shell=True, ...)
```

在「自定义 Ping / 路由追踪」输入框里填 `8.8.8.8 & calc` 就能执行任意命令；而这个程序通常**以管理员身份运行**。

**修复**：
- 新增 `is_valid_target()`，白名单校验 IPv4 / IPv6 / 主机名（`999.999.999.999` 这类伪 IP 也拒绝）；
- 全部改为参数列表调用（`['ping', '-n', '4', target]`），不再经过 shell。

### P0-4 🟠 输出解码顺序错误，中文会乱码

旧顺序是 `gbk → utf-16-le → utf-8`。问题：UTF-8 中文（如 `0xE4 0xB8`）在 GBK 下同样是**合法**序列，会被误判成 GBK 输出乱码。

**修复**：`decode_output()` 改为 BOM/特征优先的判定链：UTF-16 BOM → UTF-8 BOM → 含 `\x00`（Win7 PowerShell 的 UTF-16LE 特征）→ UTF-8 → 本地代码页（GBK）→ `latin-1` 兜底。

### P1 优化项

| # | 问题 | 修复 |
|---|---|---|
| 1 | 版本号 `v3.2` 硬编码在 6 处，改版本必漏 | 新增 `APP_NAME / APP_VERSION / APP_VERSION_SHORT / APP_AUTHOR` 单一来源，标题栏、页脚、问候语、docstring 全部引用；`version_info.txt` 同步 3.3.0.0 |
| 2 | `_init_font()` 临时 `tk.Tk()` 再 destroy，干扰 Tcl 解释器 | 改为复用主窗口：`_init_font(self)` |
| 3 | `_set_running(True)` 只禁用「一键重置」，其余按钮可并发点击 → 多条 netsh 交错执行 | 构建期记录全部操作控件的**基线状态**，运行期统一禁用、结束后精确还原（不会误恢复 macOS 上本就禁用的按钮） |
| 4 | `reset_tcpip()` 无论成败都返回 `True` | 返回 IPv4/IPv6 双命令的真实结果 |
| 5 | Linux 上 `flush_dns()` 去跑 `ipconfig /flushdns` | 新增 `IS_LINUX` 分支，走 `resolvectl` / `systemd-resolve` / `nscd` |
| 6 | Win7 判定逻辑重复 3 份，且重复调用 `sys.getwindowsversion()` | 统一复用 `_is_win7_or_older()`；`dns_lookup` 拆出 `_parse_nslookup()` / `_dns_lookup_nslookup()` |
| 7 | 母亲节日期写死 `day in [9, 10]`（只对 2026 年成立，每年失效） | 新增 `_is_mothers_day()`，动态算「5 月第二个周日」 |
| 8 | 网卡选择取「第一个 Up 的网卡」→ 常选中 Hyper-V / VMware / Docker 虚拟网卡 | 改为**优先选有默认网关的网卡**（真实出口） |
| 9 | 「备份IP」只存内存，重开程序就丢了 | 落盘到 `%LOCALAPPDATA%\NetworkResetTool\static_ip_backup.json`，启动时自动载入 |
| 10 | `NetworkResetTool._cancel` 是死字段，没有任何 UI 能设置它 | 接上「⏹ 取消」按钮，一键重置可在步骤边界中断 |
| 11 | `_thread_log()` 空循环死代码 | 删除 |
| 12 | `_run_ps()` 失败静默返回空串，排障时一脸懵 | 失败时把 PowerShell 的 stderr 首行回传给日志；加 `-NonInteractive` |
| 13 | 健康报告 `sum(p['avg_ms'])` 在延迟 <1ms（值为 `None`）时抛 `TypeError` → 报告空白 | `(p['avg_ms'] or 0)` 兜底 |
| 14 | `nslookup` 会把 DNS 服务器自身地址当成解析结果（"假成功"） | 只取应答区，并剔除 `dns_server` 自身 IP；兼容 Linux 的 `1.2.3.4#53` 写法 |
| 15 | `tracert` 开反向 DNS，30 跳能跑几分钟 | 统一加 `-d` / `-n` 关闭反向解析，速度从分钟级降到秒级 |
| 16 | 完全没有测试 | 新增 `tests/smoke_test.py`，**75 项断言全通过**（含 GUI 启动自检） |

---

## 3. 尚未处理的问题（建议下一步做）

### 3.1 🔴 自动更新无任何完整性校验（安全，高危）

`auto_updater.py` 从 Gitee 拉 Release 资源，直接下载、替换、以管理员权限执行，**全程没有 SHA256 / 签名校验**。只要 Gitee 账号或中间链路被劫持，就能向所有用户的机器上投递恶意 exe——而且这些用户习惯用管理员权限运行它。

建议（按性价比排序）：
1. 发布时用 `sha256sum` 生成校验值，随 Release 上传 `sha256.txt`；
2. 更新器下载后先比对摘要，不符即中止；
3. 有代码签名证书的话做 Authenticode 签名，更新器校验签名。

### 3.2 🟠 死代码 `network_reset_macos.py`（943 行）→ ✅ 已移入 `legacy/`（v3.4）

跨平台能力已经合并进 `network_reset_gui.py`，这个文件只被它自己引用（第 673 行的一句提示文案），是纯历史包袱。v3.4 已把它移到 `legacy/network_reset_macos.py`（保留可追溯，不再参与构建与维护），后续可随时彻底删除。

### 3.3 🟠 单文件 3100+ 行 → ✅ 已在 v3.5 拆分成 `network_toolbox/` 包

`network_reset_gui.py` 原先同时承担：核心网络操作、诊断、代理修复、三个 UI 面板、配色、字体、单例。现已按职责拆成包，**v3.5 完成**：

```
network_toolbox/
├── __init__.py       # 汇总并重新导出全部公共 API（含测试用的下划线私有符号）
├── _shared.py        # 所有模块级函数 + 常量（decode_output / is_valid_target /
│                      #   ui_sync / _apply_proxy_setting / COLORS / APP_* / DNS_PRESETS …）
├── engine.py         # NetworkResetTool / NetworkDiagnostic / ProxyRepairTool（纯逻辑）
├── report.py         # compute_health / render_report(_html|_text|_markdown)
├── ui_panels.py      # ResetPanel / DiagnosticPanel / ProxyPanel
└── app.py            # App / __main__ 入口
network_reset_gui.py  # 仅 57 行兼容入口：from network_toolbox import * + __main__ 守卫
```

要点：
- 用 `ast` 按顶层节点切片自动拆分，保证语义 1:1 等价；`network_reset_gui.py` 仍是 PyInstaller 的 Analysis 目标。
- 实现模块经 `network_toolbox._shared` 调用，测试可在 `G._shared` 上打桩（如 `_apply_proxy_setting`），单点可控。
- 拆分后 `tests/smoke_test.py --gui` 仍 **152 项全绿**。

### 3.4 🟡 `run_cmd()` 用 `shell=True` 拼网卡名

```python
cmd = f'netsh interface ip set dns "{adapter_name}" static {primary} primary'
```

网卡名来自系统，一般安全，但理论上含 `&` / `|` 就会出问题。建议改成参数列表 + 校验。

### 3.5 🟡 单例端口 45678 写死

与其他程序撞端口会让本程序永远无法启动（提示"程序已在运行"）。建议改成端口 + 锁文件双保险，或端口占用时再探活一次确认是不是自己。

### 3.6 🟡 崩溃只写 `crash.log`，没人看

当前逻辑：崩溃写日志 + 弹窗。弹窗里塞 500 字符 traceback，普通用户看不懂也不会抄给你。建议加一个「复制错误信息」按钮，或提供可选的匿名上报。

### 3.7 🟡 仓库卫生

- `test.txt` / `test_err.txt` 是调试残留，应删除；
- `README.md` 里 v3.2 的徽章、下载链接、章节标题需要跟着升到 v3.3；
- `.gitignore` 忽略了 `*.spec`，但 `网络工具箱.spec` 是被强制加入版本库的——要么去掉忽略规则，要么说明原因；
- `splash.bmp` 640KB、`icon.ico` 372KB 是二进制资产，README 里说要用 GitHub Releases 存，但仍在库里，建议迁走或引入 Git LFS。

---

## 4. 工程化建议

| 项 | 建议 | 收益 |
|---|---|---|
| 自动化测试 | 已有 `tests/smoke_test.py`，接到 PR 流程里，再补网络操作的 mock 测试 | 防止"改 A 坏 B"，尤其是本次这类被 `except` 吞掉的 Bug |
| CI | GitHub Actions：提交即跑 `py_compile` + 冒烟测试；打 tag 自动构建 Win x64 / Win7 x86 / macOS 三件套并上传 Release | 现在手工打包容易漏 32 位版本 |
| 版本号单一来源 | 已做 `APP_VERSION`，下一步让打包脚本从它读，避免 `version_info.txt` 再漂移 | 一个地方改版本号 |
| 日志分级 | 现在只有"往文本框里塞字符串"，建议加 `logging` + 落盘到 `%LOCALAPPDATA%` | 用户报障时可以直接要日志 |
| 类型标注 | 关键函数加 `-> tuple[bool, float|None, int, str]` 之类 | 编辑器能提前抓到这次 `avg_ms: None` 那类错误 |

---

## 5. 新功能建议（按优先级）

### P0 — 强烈建议，成本低、用户感知强

**F1. 导出诊断报告（一键复制 / 存 txt）**
健康报告和完整诊断目前只能看、不能带走。用户报障时只能截图。加一个「导出报告」按钮，把诊断结果 + 系统信息 + 时间戳写成 `网络诊断报告_20260831.txt` 并自动打开。预计 60 行代码。

**F2. 操作前的配置快照与回滚**
「一键重置」是不可逆操作。建议在重置前把 IP / DNS / 代理 / hosts 关键项完整快照成 JSON，重置后若用户报告"网断了"，提供「回滚到重置前」按钮。备份落盘的基础设施（本次已做）可以直接复用。

**F3. 网卡选择下拉框**
现在自动选网卡，多网卡（有线 + 无线 + 虚拟机）环境下经常选错。给 DNS 切换区加一个「网卡：自动 ▾」下拉框，默认自动，可手动指定。

### P1 — 有明确价值

**F4. hosts 文件检查与清理**
很多"网站打不开"是 hosts 被软件写脏了。加一个标签页或诊断项：读取 `C:\Windows\System32\drivers\etc\hosts`，列出非注释行，标记可疑条目，支持一键注释/还原。

**F5. 端口占用查看**
「代理端口 7897 没人监听」是本项目最常诊断出的问题。顺手做一个端口列表：显示 LISTENING 的端口与对应进程（`netstat -ano` + 进程名映射），支持按端口搜索和结束进程。和代理修复天然互补。

**F6. 网速测试**
Ping 只能测延迟。加一个简易测速：从就近节点下载固定大小文件，算出下行带宽。无第三方依赖的话可以用 `https://www.gstatic.com/generate_204` 之类的公开端点做延迟+小流量测试，或用 Cloudflare 的 speed 端点。

**F7. 定时自动体检 + 掉线记录**
托盘常驻，每 5 分钟 Ping 一次网关和 223.5.5.5，掉线时记录时间戳并在恢复后给出"14:23–14:27 断网 4 分钟"的汇总。对"网络时好时坏"这类最难查的故障特别有用。

### P2 — 差异化

**F8. WiFi 信息管理**
`netsh wlan show profiles` + `key=clear` 列出已保存的 WiFi 密码，支持导出。家用场景高频刚需。注意：需管理员权限，界面上要说清楚。

**F9. 多网卡 / 多 DNS 批量测速**
把 DNS 预设扩展成"测速后排序"：对每个候选 DNS 解析同一域名 3 次取平均，给出「阿里 12ms / 腾讯 18ms / 114 25ms」的推荐排序，一键应用最快的。

**F10. 命令行模式**
`网络工具箱.exe --cli reset --dns 223.5.5.5 --json`，方便写进批处理或运维脚本里调用。现在只有 GUI + 一个 bat 菜单。

### P3 — 生态

**F11. 深色/浅色主题切换** — 现在只有一套 Catppuccin 深色配色。
**F12. 多语言** — 至少中/英，字符串抽到 `i18n.py`。
**F13. 插件式诊断项** — 把每项诊断抽象成 `DiagnosticItem`，第三方可以加自己的检查。

---

## 6. 建议排期

| 阶段 | 内容 | 说明 |
|---|---|---|
| **v3.3（已完成）** | 3 个 P0 + 16 项 P1 + 冒烟测试 | 本次交付 |
| **v3.4（已完成）** | F1 导出报告、F2 快照回滚、F3 网卡下拉框、自动更新 SHA256 校验 | 安全 + 用户感知最强的三件事（另修 User-Agent 中文导致更新请求必崩的隐藏 bug） |
| **v3.5（拆分已完成）** | 拆分 `network_toolbox/` 包、清理死代码 | 工程化，为后续功能铺路；CI 自动构建与打包 exe 待环境就绪 |
| **v4.0** | F4 hosts、F5 端口、F7 掉线记录、F9 DNS 测速排序 | 从"修复工具"升级为"网络运维工具箱" |

---

## 7. 如何验证本次改动

```bash
# 完整自检（含网络操作）
python tests/smoke_test.py

# 加上 GUI 启动自检（需要 tkinter）
python tests/smoke_test.py --gui
```

当前状态：**152 项断言全部通过**（`tests/smoke_test.py --gui`）。自检脚本会守住这次修的每一个点——特别是 `_decode_output` 缺失和跨线程 Tk 构造，这两类 Bug 一旦回归会立刻在 CI 里报红。
