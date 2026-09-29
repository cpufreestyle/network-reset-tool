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

**F1. 导出诊断报告（一键复制 / 存 txt）** ✅ 已于 v3.4 交付
健康报告和完整诊断目前只能看、不能带走。用户报障时只能截图。加一个「导出报告」按钮，把诊断结果 + 系统信息 + 时间戳写成 `网络诊断报告_20260831.txt` 并自动打开。预计 60 行代码。

**F2. 操作前的配置快照与回滚** ✅ 已于 v3.4 交付
「一键重置」是不可逆操作。建议在重置前把 IP / DNS / 代理 / hosts 关键项完整快照成 JSON，重置后若用户报告"网断了"，提供「回滚到重置前」按钮。备份落盘的基础设施（本次已做）可以直接复用。

**F3. 网卡选择下拉框** ✅ 已于 v3.4 交付
现在自动选网卡，多网卡（有线 + 无线 + 虚拟机）环境下经常选错。给 DNS 切换区加一个「网卡：自动 ▾」下拉框，默认自动，可手动指定。

### P1 — 有明确价值

**F4. hosts 文件检查与清理** ✅ 已于 v3.6 交付
很多"网站打不开"是 hosts 被软件写脏了。加一个标签页或诊断项：读取 `C:\Windows\System32\drivers\etc\hosts`，列出非注释行，标记可疑条目，支持一键注释/还原。

**F5. 端口占用查看** ✅ 已于 v3.6 交付
「代理端口 7897 没人监听」是本项目最常诊断出的问题。顺手做一个端口列表：显示 LISTENING 的端口与对应进程（`netstat -ano` + 进程名映射），支持按端口搜索和结束进程。和代理修复天然互补。

**F6. 网速测试** ✅ 已于 v4.1 交付
Ping 只能测延迟。加一个简易测速：从就近节点下载固定大小文件，算出下行带宽。无第三方依赖的话可以用 `https://www.gstatic.com/generate_204` 之类的公开端点做延迟+小流量测试，或用 Cloudflare 的 speed 端点。

**F7. 定时自动体检 + 掉线记录** ✅ 已于 v4.0 交付
托盘常驻，每 5 分钟 Ping 一次网关和 223.5.5.5，掉线时记录时间戳并在恢复后给出"14:23–14:27 断网 4 分钟"的汇总。对"网络时好时坏"这类最难查的故障特别有用。

### P2 — 差异化

**F8. WiFi 信息管理** ✅ 已于 v4.2 交付
`netsh wlan show profiles` + `key=clear` 列出已保存的 WiFi 密码，支持导出。家用场景高频刚需。注意：需管理员权限，界面上要说清楚。

**F9. 多网卡 / 多 DNS 批量测速** ✅ 已于 v4.0 交付
把 DNS 预设扩展成"测速后排序"：对每个候选 DNS 解析同一域名 3 次取平均，给出「阿里 12ms / 腾讯 18ms / 114 25ms」的推荐排序，一键应用最快的。

**F10. 命令行模式** ✅ 已于 v4.4 交付
`--cli` 无界面子命令 + `--json` 机器可读 + 固定退出码语义(见第 13 节)。

### P3 — 生态

**F11. 深色/浅色主题切换** ✅ 已于 v4.3 交付
两套语义配色表 + 顶栏一键切换 + 主题记忆(见第 12 节)。

**F12. 多语言** ✅ 已于 v4.5 交付
中/英一键切换，以中文字符串本身为 key 的轻量 i18n（见第 14 节）。

**F13. 插件式诊断项** ✅ 已于 v4.6 交付
把每项诊断抽象成 `DiagnosticItem`，第三方可以加自己的检查（见第 15 节）。

---

## 6. 建议排期

| 阶段 | 内容 | 说明 |
|---|---|---|
| **v3.3（已完成）** | 3 个 P0 + 16 项 P1 + 冒烟测试 | 本次交付 |
| **v3.4（已完成）** | F1 导出报告、F2 快照回滚、F3 网卡下拉框、自动更新 SHA256 校验 | 安全 + 用户感知最强的三件事（另修 User-Agent 中文导致更新请求必崩的隐藏 bug） |
| **v3.5（拆分已完成）** | 拆分 `network_toolbox/` 包、清理死代码 | 工程化，为后续功能铺路；CI 自动构建与打包 exe 待环境就绪 |
| **v3.6（已完成 2026-09-23）** | F4 hosts 检查、F5 端口查看、检查更新接入 GUI、ResultPanel 基类、SO_REUSEADDR、版本号单一来源 | 拆分收尾（Clash 死节点切换移植回包、`network_reset_gui.py` 变 27 行兼容入口）；测试 191 项 |
| **v4.0（已完成 2026-09-23）** | F7 定时体检/掉线记录、F9 DNS 测速排序 | 从"修复工具"升级为"网络运维工具箱" |
| **v4.1（已完成 2026-09-24）** | F6 网速测试、safe_after 兜底、GitHub Actions CI | 最后一个 P1 能力补齐; 工程化收尾(线程安全/CI/版本治理) |
| **v4.2（已完成 2026-09-26）** | F8 WiFi 信息管理 | 家用高频刚需; netsh 三语解析/明文密码回读/权限提示/导出; bat 菜单 [7]; `--tab wifi` 直达 |
| **v4.3（已完成 2026-09-26）** | F11 深色/浅色主题切换 | THEMES 语义配色表(20 键, Mocha/Latte) + 就地换色 + 主题记忆 + Treeview/Scrollbar/报告配色统一 + safe_after 执行期兜底; bat 版本号同步; 测试 --gui 336 项 |
| **v4.4（已完成 2026-09-26）** | F10 命令行模式 | `--cli` 12 个子命令 + argparse 子命令式 help + `--json` 纯净输出 + 退出码语义 + 权限闸门; bat 版本号同步; 测试 --gui 365 项 |
| **v4.5（已完成 2026-09-26）** | F12 多语言（中/英） | `i18n.py` 以中文串为 key + `tr()`/`tr_f()` + `lang.txt` 持久化; AST 自动包装 5 个源文件的展示位文案; 顶栏语言按钮整树重建不丢 tab; CLI `--lang zh|en`; 测试 --gui 412 项 |
| **v4.6（已完成 2026-09-26）** | F13 插件式诊断项 | 新增 `plugins.py` 注册表: 内置三项不可覆盖/不可注销、单项崩溃只掉自己、ASCII key 校验; `run_full_diagnostic` 退化为一行委托; CLI `diagnose` 列出自定义项; 顺手修掉 DNS_TARGETS 空表除零; 测试 413 项 / --gui 453 项 |
---

## 7. 如何验证本次改动

```bash
# 完整自检（含网络操作）
python tests/smoke_test.py

# 加上 GUI 启动自检（需要 tkinter）
python tests/smoke_test.py --gui
```

当前状态：**412 项断言全部通过**（`tests/smoke_test.py --gui`，普通模式 372 项）。自检脚本会守住这次修的每一个点——特别是 `_decode_output` 缺失和跨线程 Tk 构造，这两类 Bug 一旦回归会立刻在 CI 里报红。

---

## 8. 2026-09-23 v3.6 交付记录

本仓库（D:\\ai sheare\\repo\\network-reset-tool）接手时处于"拆分包已落盘但兼容入口未切"的中间态，
`network_reset_gui.py` 仍是 2992 行 v3.3 单体、冒烟测试因缺 `APP_VERSION` 直接崩。本轮已收尾：

- **拆分收尾**：包内补回 v3.3 的 Clash 死节点自动切换（拆分时遗漏，`repair()` 少步骤 3）；
  `network_reset_gui.py` 重写为 27 行兼容入口（`from network_toolbox import *` + `main()`），
  PyInstaller spec 目标不变；消除约 2900 行重复代码。
- **F4 hosts 检查**：`HostsTool`（读取/可疑判定/备份/注释/还原，BOM 兼容）+ 诊断面板按钮。
- **F5 端口查看**：`PortTool`（netstat/tasklist/lsof 解析 + 结束进程）+ 新增「🔌 端口查看」标签页 + bat 菜单 [5]。
- **自动更新接入**：标题栏「🔄 检查更新」，仅 exe 模式可用；`auto_updater.py` 补齐 v3.4 设计中的
  SHA256/域名白名单/ASCII User-Agent/fail-closed（此前工作区里是旧版裸奔实现）。
- **P1 清理**：`ResultPanel` 基类消除诊断/代理面板约 60 行重复；健康报告 `rc` 闭包提为方法；
  单例 socket 加 `SO_REUSEADDR`；删除 `test.txt`/`test_err.txt`/根目录 `network_reset_macos.py`。
- **版本号治理**：`APP_VERSION=3.6.0` 单一来源，`version_info.txt` 由 `gen_version_info.py` 生成。
- **验证**：`python tests/smoke_test.py --gui` → 191 项全部通过；真实 mainloop 集成自检通过
  （端口扫描 375 条、过滤、结束进程对话框、hosts 渲染均正常）。

---

## 9. 2026-09-23 v4.0 交付记录

从"修复工具"升级为"网络运维工具箱"：新增两个后台/数据型能力，并把监控回调跨线程的
死锁隐患在集成自检里逼出来修掉。

- **F7 定时体检 + 掉线记录**：`NetworkMonitor`（engine 层，daemon 线程，默认每 5 分钟
  Ping 网关 + 223.5.5.5；任一目标通即在线，全失败才算掉线，单目标抖动不误报）；
  掉线事件（起止时间 + 持续时长）落盘 `%LOCALAPPDATA%/NetworkResetTool/monitor/outages.json`，
  重启可回看；恢复后给出「14:23–14:27 断网 4 分钟」式汇总。
  新增「📡 网络监控」标签页（间隔输入 / 开始 / 停止 / 汇总卡片 / 事件表格 / 清空记录）。
- **F9 多 DNS 批量测速**：`benchmark_dns()` 对每个静态预设解析同一域名 3 次取平均，
  按快慢排序（DHCP 预设跳过，全失败排最后）；诊断面板 DNS 区新增「⚡ DNS 测速排序」
  与「🏆 应用最快」一键切换。
- **修复跨线程死锁（关键）**：`check_once()` 原先在持有 `self._lock` 时触发 `on_event`，
  而 UI 刷新的 `summarize()` 也要拿同一把非重入锁 → 监控线程与主线程互等，界面整体卡死。
  回调改为锁外触发；smoke_test 增加 `on_event` 内读汇总的回归用例。
- **顺带修正**：`on_event` 此前从未被触发（存而不用，掉线记录只在磁盘里，界面不刷新）。
- **版本 4.0.0**：`APP_VERSION` 单一来源 bump，`version_info.txt` 重新生成，bat 六处版本号同步。
- **safe_after 兜底（收尾）**：worker 回投 UI 的 70 处裸 `self.after(0, ...)` 统一改走
  `_shared.safe_after()`（窗口销毁/关窗竞态时静默失败，不再往 stderr 打 traceback），
  `ui_sync()` 内部复用它；smoke_test 新增"无裸 after(0, ...)"源码纪律守卫。
- **CI**：`.github/workflows/ci.yml`——三平台冒烟 + Windows GUI 自检 + `v*` tag 三平台构建；
  `网络工具箱.spec` 解除 `*.spec` 忽略随仓库发布（此前未入 git，CI 构建会拿不到打包配置）。
- **验证**：`python tests/smoke_test.py` → 218 项；`--gui` → 232 项（含 44 按钮 tooltip 全遍历）；
  真实 mainloop 集成自检 24 项全过（监控开始/掉线/恢复/清空/切 tab）。

---

## 10. 2026-09-24 v4.1 交付记录

补齐最后一个 P1 能力, 并把 v4.0 遗留的两处工程化事项一次收尾:

- **F6 网速测试**: `SpeedTester`(engine) 从公开端点(Cloudflare/CacheFly/OVH 白名单,
  纯 urllib 标准库)流式下载固定大小数据测下行带宽; 上限保护(默认 12s/64MB, 先到先停),
  单端点失败自动 fallback, 可提前停止(部分流量仍估算)。新增「⚡ 网速测试」标签页
  (大数字 Mbps + 首包延迟/流量/耗时/端点详情 + 实时进度), bat 菜单新增 [6], `--tab speed` 直达。
- **safe_after 兜底(随 v4.0 收尾补记)**: 70 处裸 `self.after(0, ...)` 改走 `_shared.safe_after()`,
  `ui_sync()` 内部复用; smoke_test 增加"无裸 after(0, ...)"源码纪律守卫与行为用例。
- **CI**: `.github/workflows/ci.yml`——三平台冒烟 + Windows GUI 自检 + `v*` tag 三平台构建;
  `网络工具箱.spec` 解除 `*.spec` 忽略随仓库发布(此前未入 git, CI 构建拿不到打包配置)。
- **顺手修复**: 手写码点把"宽"误打成僻字 U+5BED(界面无报错但显示怪字), 已修正并加
  SpeedPanel 关键文案渲染守卫(t_gui), 该类问题不会再静默漏网。
- **验证**: `python tests/smoke_test.py` → 232 项; `--gui` → 248 项; 真实 mainloop 集成自检
  10/10(开始/实时进度/停止/部分流量估算/按钮状态复原); exe 重建后 `--tab speed` 运行无崩溃。


---

## 11. 2026-09-26 v4.2 交付记录（F8 WiFi 信息管理）

家用场景高频刚需落地, 同时把 `_shared.py` 的版本号单一来源机制真正跑通:

- **引擎层 `WifiTool`**(engine.py): `parse_profiles` 兼容 netsh 输出简体/繁体/英文三套
  前缀并去重保序; `parse_profile_detail` 取密码(关键内容/Key Content/金鑰內容)与认证方式,
  并能区分拒绝访问 / wlansvc 未运行 / 找不到配置文件三类故障。命令一律以 argv 列表执行
  (不经 shell), SSID 含空格或引号也不会注入; 解析与执行分层, 便于打桩测试。
- **界面层 `WifiPanel`**(ui_panels.py, 第七个标签页): 表格展示 SSID/密码/认证方式,
  非管理员启动时顶部横幅提示"仍能列出但读不出密码"; 任务放 daemon 线程, 结果经
  `ui_sync` 回主线程(遵守线程安全铁律); 「💾 导出」写 UTF-8 txt 并弹明文密码警示。
- **接线**: `app.py` 七个标签页 + `--tab wifi` 白名单; `network-reset.bat` 新增
  「[7] WiFi 信息(已保存密码)」菜单(exe→py→python 三级回退); `__init__.py` 导出
  `WifiTool` / `WifiPanel`。
- **测试**: `t_wifi()` 新增 33 项断言(三语解析/去重/三类故障/打桩全流程/非 Windows
  分支/导出), `t_gui` 增加 WifiPanel 构造与文案守卫; --gui 合计 286 项全部通过。
- **验证**: 源码模式与 exe 模式 `--tab wifi` 均无 crash.log; `gen_version_info.py`
  重新生成 version_info.txt(v4.2)。

---

## 12. 2026-09-26 v4.3 交付记录（F11 深色/浅色主题切换）

把"只有一套深色配色"补成用户可自选的双主题, 顺手把此前散落的写死底色收进语义配色表:

- **THEMES 语义配色表**(`_shared.py`): 深色沿用 Catppuccin Mocha, 浅色用 Catppuccin Latte,
  共 20 个语义键; 新增 3 个语义键 `card`(内容卡底色) / `warn_bg` / `warn_fg`(顶部警示横幅),
  并把 `ui_panels.py` 里 25 处写死的 hex(`#2a2a3e`/`#3a2a2a`/`#ffb4a0`)全部换成 `COLORS[...]`。
- **就地换色**: `COLORS` 改成 `dict(THEMES[DEFAULT_THEME])`, `set_theme()` 用
  `clear()+update()` 就地覆写而不是重新赋值——各模块 `from ... import COLORS` 持有的是
  同一个 dict 引用, 换主题后自动同步, 不需要逐个模块改 import。
- **主题记忆**: `theme_path()`/`current_theme()`/`set_theme()`/`toggle_theme()` 四个函数,
  偏好写入 `%LOCALAPPDATA%/NetworkResetTool/theme.txt`; 文件缺失、内容损坏或主题名非法
  一律回落到默认深色(fail-safe), 写不进去(只读目录/UAC)也不影响本次生效。
- **界面层**: `app.py` 顶栏新增「🌙 深色 / ☀️ 浅色」按钮 `_toggle_theme()` → `_rebuild_ui()`
  销毁并重建整棵窗口树(所有控件的 bg/fg 都是构造期定的, 只能重建), 重建后切回原标签页;
  `MonitorPanel` 覆写 `destroy()`, 重建时停掉巡检线程, 避免双线程空转。
  `_rebuild_ui()` 同时重设顶层窗口底色, 否则边框会残留旧主题颜色。
- **修换主题导致的 TclError(发现方式)**: 真实点一次主题切换时, 旧 ResetPanel 的
  DNS 探测线程排队回投, 而面板已被 destroy → 回调里 `config()` 抛
  `TclError: invalid command name`, Tk 往 stderr 打 traceback。根因是 `safe_after()`
  只兜住了"调度失败", 没兜住"执行时控件已没了"。修法是在回调外层再包一层
  TclError 兜底(注意不能改成判 `winfo_exists()` 后跳过——那会让 `ui_sync` 里
  等 Event 的工作线程白等到 30s 超时)。smoke_test 补了对应回归用例。
- **Treeview 样式统一**: `ui_panels.py` 新增模块级 `config_treeview_style(widget)`
  (`nice.Treeview`/`nice.Treeview.Heading`/`nice.Vertical.TScrollbar`), 端口 / 监控 / WiFi
  三处表格改用主题化样式, 浅色下不再是系统默认的白底黑字。同理 `tk.Scrollbar` 不吃 ttk
  style, 新增 `theme_scrollbar()` 工厂把 5 处滚动条也着色(否则退回 `SystemButtonFace`,
  深色界面里一条灰白滚动条非常扎眼)。
- **报告配色跟随主题**: `report.py` 的 HTML 报告原先写死一套 GitHub 浅色 CSS 变量, 深浅主题
  下都不搭; 改为从 `COLORS` 取 `--fg/--muted/--line/--bg/--soft/--ok/--bad` 与评分分档色,
  导出后与界面同色。`@media print` 仍强制浅色, 免得深色主题导出的报告打出来一片黑。
- **顺手修正**: `DNS_PRESETS` 的颜色原先在 import 期就取定成固定色值, 换主题后按钮颜色
  停留在旧主题; 改为存语义键名, 由 `_make_dns_btn` 在构造控件时解析。另修掉
  `ui_panels.py` 里 6 处被写成字面量码点文本(`"U0001F4E1 网络监控"`)的 emoji——渲染不报错
  但界面直接显示那串字符, 现补源码守卫 + MonitorPanel 文案守卫防回归。
- **测试**: `t_theme()` 新增 25 项断言(两套主题键集合一致/色值格式/语义键齐全/源码无写死底色/
  源码无字面量 codepoint/theme.txt 读写与容错/COLORS 不被重新绑定/跨模块引用同步/
  toggle 往返/持久化一致/DNS 语义键); 新增 `t_theme_widgets()`——**控件级校验**:
  在深/浅两套主题下真实构造全部 7 个面板, 遍历每个控件的 bg/fg 与主题色板比对,
  专门抓"源码里搜不到 hex 但界面还是旧色"这类 import 期固化问题(Scrollbar 就是这么抓出来的);
  `t_gui` 追加 App 级主题切换自检与 MonitorPanel 文案守卫; 测试结束还原 `COLORS`
  并恢复用户的 `theme.txt`。
- **验证**: `python tests/smoke_test.py` → 296 项; `--gui` → 336 项(含 51 个按钮 tooltip
  全遍历); 深浅两套主题真机截图核对; 运行时连续切两次主题无 traceback、当前 tab 不丢;
  exe 重建后启动无 crash.log。

---

---

## 13. 2026-09-26 v4.4 交付记录（F10 命令行模式）

GUI 之外补齐一条可脚本化的无界面入口。核心约束是**绝不碰 Tk**：
不起窗口、不弹对话框，因此在没有桌面会话的服务器 / SSH / CI 里同样能跑。

- **`network_toolbox/cli.py`（新增）**：12 个子命令 `adapters` / `diagnose` / `reset` /
  `dns` / `proxy` / `ports` / `speed` / `wifi` / `monitor` / `snapshots` / `report` / `hosts`，
  全部复用既有引擎（`NetworkResetTool`/`NetworkDiagnostic`/`ProxyRepairTool`/`PortTool`/
  `SpeedTester`/`WifiTool`/`NetworkMonitor`/`HostsTool`/`render_report`），不重写业务逻辑。
- **argparse 子命令式 help**：用 subparsers 而不是一堆裸选项，每个命令只暴露自己用得到的参数，
  `--cli dns --help` 就能查到完整用法；`--adapter` / `--json` 走 parent parser 全局继承。
- **`--json` 纯净输出**：stdout 只打印一个 JSON 对象（`ok`/`command`/`data`/`warnings`），
  日志全部走 stderr，无 BOM，可直接 `jq` / `ConvertFrom-Json` 消费。
- **退出码语义固定**：`0` 成功 / `1` 操作失败 / `2` 参数错误 / `3` 需要管理员 /
  `4` 平台不支持 / `130` 被 Ctrl+C 取消。`CliError` 带码抛出，`--json` 时还会把
  `exit_code` 写进 `data`，调用方不靠解析 stderr 也能判断失败原因。
- **权限闸门**：`reset` / `proxy --repair` / `ports --kill` / `hosts --fix` 在执行前检查
  管理员权限，不足则退出码 3 + 明确提示，不会跑到一半才失败。
- **入口分流**：`network_reset_gui.py` 在 `import` 整个包**之前**判断 `--cli`，
  因此不拖进 ui_panels/app 的 Tk 依赖，也不占用 GUI 的单例端口
  （`run_cli()` 里显式 `_release_singleton()`，否则 CLI 跑完不关端口，
  随后启动的 GUI 会误判"程序已在运行"）。
- **踩坑记录**：最初把 `_cli_main()` 的返回值丢了、直接 `sys.exit(0)`，
  导致脚本永远判断成功——已改为 `sys.exit(_cli_main())` 并加回归断言。
- **测试**：`t_cli()` 新增 26 项断言（子命令接线 / 互斥选项 / 共享选项继承 /
  退出码逐类验证 / JSON 纯净度与字段契约 / reset 失败带 exit_code / 非 Windows 平台闸门 /
  AST 级"CLI 不碰 Tk"守卫 / 入口分流顺序与退出码透传 / 单例释放）。
  守卫做过反向验证：故意把入口改回 `sys.exit(0)`、在 cli.py 里 `import tkinter`、
  去掉平台闸门，三者均被测试抓红。
- **验证**：`python tests/smoke_test.py` → 325 项；`--gui` → 365 项；真机跑通
  `adapters` / `dns` / `ports --filter` / `hosts` / `monitor` / `snapshots` /
  `wifi --json` / `report --format md`，退出码逐条核对；exe 重建后启动无 crash.log。

## 14. 2026-09-26 v4.5 交付记录（F12 多语言：中/英界面切换）

把「至少中/英」从待办划掉。核心设计取舍是**不引入 msgid/gettext，直接拿中文字符串本身当 key**——源码读起来依旧是中文，英文目录只写差异，漏翻译永远只是回落中文而不是 KeyError。

- **`network_toolbox/i18n.py`（新增）**：`LANGS={"zh","en"}`、`DEFAULT_LANG="zh"`、
  `LANG_LABELS`、`tr()` / `tr_f()`，以及沿用 `theme.txt` 同一套模式的
  `lang_path()` / `current_lang()` / `set_lang()`（`current_lang()` 带记忆缓存，避免每屏都读文件）。
  偏好落盘 `%LOCALAPPDATA%/NetworkResetTool/lang.txt`；文件缺失、内容损坏、语言名非法都安全回落中文，
  写失败也不影响本次生效。
- **幂等回落**：中文模式下 `tr()` 原样返回原文；英文模式查 `EN` 目录，缺 key 回落中文。
  因此「先上线中文界面、再逐步补英文」这种增量交付是安全的，不存在漏翻一片白屏。
- **`tr_f()` 管占位符**：`{name}` 形式的中英文模板一一对应，两边占位符集合不同会被自检抓红
  （`%s` / `%d` 同理），避免翻译后格式化串位。
- **英文目录 `EN` 收录 530 条**，覆盖 5 个源文件里所有展示位文案。
  刻意**不进目录**的只有三类：6 条正则串（如 `(?:Average|平均)\s*=\s*(\d+)ms`，翻译会改变匹配行为）、
  netsh 输出的简/繁解析标记（`所有用户配置文件`、`所有用户設定檔`、`金鑰內容`、`驗证`——后三条是港台系统回显的原样字）、
  以及程序名 `网络工具箱.exe --cli`。
- **AST 自动包装**：用 AST 把展示位的中文普通字面量统一包成 `tr(...)`，而不是人肉改几百处。
  包装器有 5 条安全规则（否则会把文件改烂）：`ast.Constant.col_offset` 是 **UTF-8 字节偏移**，
  中文一多就整体错位，必须先换算成字符下标；跳过 dict key / 下标 / 比较运算两侧；
  跳过 docstring（否则函数丢 `__doc__`）；跳过 f-string(`JoinedStr`) 内部常量（否则把 f-string 撕坏）；
  只处理单行 token，包完必须 `compile()` 通过否则抛错。
  f-string 内部的 4 处面板空态提示、WiFi 非管理员横幅、监控汇总行 `tr_f("共 {n} 次掉线 · 合计 {d}")`、
  DNS 预设按钮与 3 处 tooltip 另行手工包装。
- **界面接线**（`app.py`）：启动时 `set_lang(current_lang())`；顶栏新增语言按钮（排在主题按钮左侧）；
  `_toggle_lang()` 切语言后走 `_rebuild_ui()`，**当前标签页不丢**；
  主题按钮标签本身也走 `tr(THEME_LABELS[...])`。
- **CLI 接线**（`cli.py`）：common parent parser 增加 `--lang {zh,en}`，
  `run_cli()` 里 `if getattr(args, "lang", None): set_lang(args.lang)`；
  help/epilog 同样被 `tr(...)` 包裹，所以 `--cli --help` 的说明也跟着语言走。
- **测试**：新增 `t_i18n()` 20 项断言。其中最关键的一条是**硬门闩**——用 AST 扫 5 个源文件里
  所有 `tr("...")` 的中文文案，任何一条不在 `EN` 目录里就报红，因此以后新增界面文案忘了补翻译
  会立刻在 CI 挂掉。其余守住：无记录/乱写/大小写不敏感的回落、`set_lang` round-trip、
  `tr()` 在中文下原样返回、`%s`/`{name}` 占位符守恒、目录里不许混进正则/解析串、
  英文翻译不许照抄中文。
- **验证**：`python tests/smoke_test.py` → 372 项；`--gui` → 412 项。
  英文模式实测遍历 7 个面板的控件文案，93 条里 86 条已英化，余下为运行时组合而成的文案。

---

### 14.1 同日补修：F12 打包器带出来的三个真 bug

上面那版交付后真机抽查 + 冒烟测试先后炸出三个问题，根子是同一个：
**包装器按"这串中文是不是展示文案"来判断，而有些中文串虽然不是给人看的，却参与了匹配。**

1. **解析标记被误翻译**（最严重）。`WifiTool.PROFILE_PREFIXES` / `KEY_LABELS` /
   `AUTH_LABELS` / `DENIED_MARKS` / `NOT_RUNNING_MARKS` / `NOT_FOUND_MARKS`，以及
   `ProxyRepairTool._find_auto_group` 的候选组名，都被包进了 `tr()`。
   这些是拿来到 netsh / Clash API 返回里做 `in` / `==` 的，不该翻译。
   **现象**：中文系统上界面一切英文，WiFi 密码列全变「未取到」，Clash 死节点也修不了。
   已改回纯字面量；冒烟测试新增「语言不得影响解析」回归（中英两种语言下各跑一遍）。
2. **`--lang` 只能写在子命令后面**。`--lang en --cli adapters` 会被 argparse 判非法参数。
   原因是 `--lang` 只挂在 common parent parser 上。现在顶层 parser 也注册一份，
   同时把子命令侧的默认值改成 `argparse.SUPPRESS`，否则顶层解析出的 `en` 会被
   子命令的默认 `None` 覆盖掉。四种写法（`--lang en --cli x` / `--cli --lang en x` /
   `--cli x --lang en` / `--lang=en --cli x`）现在都认。
3. **`--help` 不跟随 `--lang`**。argparse 的 usage/epilog 在 `build_parser()` 那一刻
   就被 `tr()` 固化了，而原来是在 `parse_args()` 之后才 `set_lang()`，所以
   `--cli dns --help` 打出来的还是旧语言。已改为先用 `_peek_lang()` 从 argv 抠出语言、
   建 parser 之前就定下来。顺带把 `set_lang` 加了 `persist=False`：
   **一次性命令不该改掉用户存的语言偏好**。

另外修了一个同源的小毛病：`ui_panels` 里健康评分卡的颜色表键写死成中文，
切英文界面后评级全部落到灰色 fallback。抽出 `_grade_color()`，键和 grade 同走 `tr()`。

**根因教训**：AST 包装只能自动识别"展示位"，识别不了"参与匹配的位"。
所以除了"所有 `tr("...")` 中文文案都必须有英文翻译"这条门闩，还必须有
"关键解析在中英两种语言下都必须正确"这条门闩——后者是行为级的，抓得住前者漏掉的一切。


## 15. 2026-09-26 v4.6 交付记录（F13 插件式诊断项）

### 15.1 做了什么

- **`network_toolbox/plugins.py`（新增，F13 的核心）**：
  - `DiagnosticItem(key, run, title, fallback, builtin)`：`__slots__` 固定 5 个字段，
    构造时校验 key 与 run，非法直接抛 `ValueError` / `TypeError`
  - 注册表 API：`register_item()` / `unregister_item()` / `diagnostic_items()` /
    `custom_keys()` / `reset_registry()` / `run_diagnostics()`
  - 内置三项 `_run_overview` / `_run_ping` / `_run_dns` 从
    `NetworkDiagnostic.run_full_diagnostic` 原样搬迁，进度节奏（0 / 10~50 / 55~95 / 100）
    与失败兜底行为逐字保留
- **`engine.py`**：`run_full_diagnostic()` 从 74 行内联逻辑退化成一行
  `return run_diagnostics(self, progress_callback)`，并新增
  `from network_toolbox.plugins import run_diagnostics`
- **`__init__.py`**：导出 7 个插件 API（兼容入口 `network_reset_gui` 同样可见）
- **`cli.py`**：`diagnose` 子命令在跑诊断前打印 `自定义诊断项: ...`，
  `--json` 的 data 里也带 `custom_items`
- **测试**：`t_plugins()` 新增 36 项断言（另在 `t_cli()` 补 2 项 diagnose 英文模板门闸）；`t_i18n()` 的 AST 扫描清单加入 `plugins.py`

### 15.2 设计取舍

1. **内置项不可覆盖/不可注销**：UI（`ui_panels.py`）和报告（`report.py`）都是直接读
   `results['overview']` / `['ping']` / `['dns']`。任何一个插件把内置项盖掉，界面就会
   KeyError 或整块空白，所以这条不变量在注册表里强制，不靠文档约定。
2. **`run(tool, progress=None)` 收两个参数**：内置的 ping/dns 需要上报细粒度进度
   （每个目标一次），只传 tool 的话插件就拿不到进度条。给插件的 `progress` 允许为 None。
3. **key 限定 ASCII 标识符，点号做命名空间分段**：中文 key 会让 `--json` 输出在
   GBK 控制台里难以阅读，连字符/空格则容易和命令行参数搞混；点号分段让第三方可以用
   `myplug.check` 这种自带前缀的 key，天然降低撞名概率。
4. **返回 `None` = 这项没有数据**：结果字典里直接不出现该 key，比塞个空列表更诚实；
   失败兜底用 `fallback`（内置三项的 fallback 是 `[]`，与 v4.5 行为一致）。
5. **`plugins.py` 只 import `i18n`**：engine 要 import plugins，plugins 一旦 import engine
   就是循环依赖。内置 run 函数通过 `tool.PING_TARGETS` / `tool.DNS_TARGETS` 取值，
   不需要反向引用引擎类。

### 15.3 顺手修掉的真实缺陷

- **空表除零**：原 `run_full_diagnostic` 里 `total_dns = len(self.DNS_TARGETS)`，
  一旦 `DNS_TARGETS` 为空，`i / total_dns` 直接 `ZeroDivisionError` 把整轮诊断炸掉。
  搬迁时改成 `len(...) or 1`（ping 侧同样补上）。
- **失败日志不跟随语言**：`获取网络状态失败` 原本是裸中文字面量，英文界面下也显示中文；
  现走 `tr()`，并在 `EN` 目录补了对应英文。
- **日志回调不再能炸掉诊断**：新增 `_log()` 包装 `log_callback`，回调自身抛异常时静默吞掉。

- **测速功能实际完全不可用（真机验证抛出来的真 bug）**：`SpeedTester._run_one` 把
  `User-Agent: 网络工具箱/v4.x` 直接写进请求头，urllib 以 **latin-1** 编码 HTTP 头，
  中文名称让每次请求都抛 `UnicodeEncodeError`，三个端点全部 fallback 失败
  ——和 v3.4 修过的自动更新是同一个坑（那次修了 `auto_updater`，F6 新功能又圴了一次）。
  现抽出 `_shared.http_user_agent()`（非 latin-1 字符按 UTF-8 percent-encode），测速改用它；
  `t_speed()` 新墟 3 项断言（抓真实 `Request.headers` 验证可编码）。
  修复前 exe 实测测速=0 / 报 UnicodeEncodeError，修复后 106.8 与 300.2 Mbps。
- **CLI 剩余 12 处 f-string 不跟随 `--lang`**：`adapters/dns/ports/speed/wifi/snapshots/report/hosts`
  里的 `r.log(f"...中文...")` 全部改走 `tr_f()`，并补 13 条英文翻译；
  现在 `--lang en` 下各子命令输出零中文残留（已在 exe 上逐个验证）。

### 15.4 验证

- `python tests/smoke_test.py` → 413 项全绿；`--gui` → 453 项全绿
- `t_plugins()` 覆盖：内置三项顺序/不可覆盖、自定义项参与诊断、单项崩溃只掉自己、
  崩溃进日志、7 种非法 key、`run` 不可调用、注销语义、`reset_registry()` 隔离
- `engine` 委托用真实 `NetworkDiagnostic` 实例 + 打桩验证，确保不是空壳
