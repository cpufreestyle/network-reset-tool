# 交接文档 (Agent Handoff) — network-reset-tool

> ⚠️ 注意：本目录已推进到 **v4.6**（2026-09-26）——v4.5（F12 多语言）之后，
> v4.6 交付 **F13 插件式诊断项**（`plugins.py` 注册表，第三方可追加自己的检查），
> 冒烟测试 413 项、`--gui` 453 项全绿。
> **最新规划与已做工作以 `OPTIMIZATION_AND_FEATURES.md` 为准**
> （含 v3.3~v4.5 排期与 v4.5 交付记录）。
> 本文件下方 v3.3 阶段的修复背景与**通用约定（线程安全铁律/母亲节算法/平台分流/commit 需批准）仍适用**。

> 本文件为 AI agent 接手项目时准备，含项目状态、关键约定、已完成工作与待办。
> 纯交接用途，不需要提交到 git（如要清理可直接删除本文件）。

## 1. 项目概览

- **名称**：网络工具箱 (Network Reset Tool)
- **功能**：Windows/macOS 一键网络重置 + 网络诊断 + Clash/系统代理修复（外网连不上时排查）
- **形态**：Python 3 + Tkinter 单文件 GUI；PyInstaller 打包成 `dist/网络工具箱.exe`
- **当前版本**：v4.6.0（跨平台版，GUI 已实现 Windows + macOS 双端复用；7 个标签页 + 深浅主题切换 + 中英文切换 + `--cli` 命令行模式 + 插件式诊断项）

## 2. 仓库与运行状态

- **目录**：`c:/Users/michael/CodeBuddy/20260805151611/network-reset-tool/`
- **远程**：`origin` = `https://github.com/cpufreestyle/network-reset-tool.git`
- **分支**：`main`（本地与远程一致，无未提交改动，无分叉）
- **最近提交**（均已推送）：
  - `abac33e` fix: 工作线程直接创建 Tk 组件导致的随机 TclError 崩溃 + 死代码清理 + 减少重复目录探测
  - `b7843a6` chore: 版本号统一 v3.3 / 母亲节动态计算 / gitee token 环境变量化 / 新增 Clash 死节点自动切换 / 路径相对化
  - `8154a0e` docs: README 补充 macOS 使用/打包说明
  - `5179172` feat: 跨平台兼容(macOS)
- **Gitee**：README 中问题反馈链接指向 `gitee.com/cpufreestyle/network-reset-tool`，但**代码远程只有 GitHub**，无 Gitee remote。

## 3. 关键文件与职责

| 文件 | 职责 |
|---|---|
| `network_reset_gui.py` | 兼容入口（27 行）：`from network_toolbox import *` + `main()`；仍是 PyInstaller 的 Analysis 目标 |
| `network_toolbox/_shared.py` | 模块级函数/常量：`decode_output`/`is_valid_target`/`ui_sync`/单例/字体/按钮样式/版本号；`THEMES` 双主题配色表 + `current_theme`/`set_theme`/`toggle_theme`/`theme_path`（F11） |
| `network_toolbox/i18n.py` | **界面多语言（F12）**：`LANGS`/`tr()`/`tr_f()` + `lang_path()`/`current_lang()`/`set_lang()`；英文目录 `EN`（530 条）以中文串为 key，缺 key 回落中文 |
| `network_toolbox/cli.py` | **命令行模式（F10）**：argparse 子命令 + `_emit` 输出分流 + `CliError` 带退出码；只依赖 engine/report，**不 import ui_panels/app、不碰 Tk** |
| `network_toolbox/engine.py` | `NetworkResetTool`/`NetworkDiagnostic`/`ProxyRepairTool`/`HostsTool`/`PortTool`/`NetworkMonitor`/`SpeedTester`/`WifiTool` + `run_cmd_capture` |
| `network_toolbox/plugins.py` | **插件式诊断项（F13）**：`DiagnosticItem` + `register_item`/`unregister_item`/`diagnostic_items`/`custom_keys`/`reset_registry`/`run_diagnostics`；内置 overview/ping/dns 三项受 `BUILTIN_KEYS` 保护，只 import `i18n`（不 import engine，避免循环依赖） |
| `network_toolbox/report.py` | `compute_health`/`render_report`(HTML/TXT/MD) |
| `network_toolbox/ui_panels.py` | `ResetPanel`/`DiagnosticPanel`/`ProxyPanel`/`PortsPanel`/`MonitorPanel`/`SpeedPanel`/`WifiPanel` + 公共基类 `ResultPanel` |
| `network_toolbox/app.py` | 主窗口 `App`（7 个 tab + 检查更新 + 深浅主题切换）与 `main()` |
| `gen_version_info.py` | 从 `APP_VERSION` 生成 `version_info.txt`（打包前跑一次） |
| `network-reset.bat` | Windows 命令行启动菜单（需管理员） |
| `网络工具箱.spec` | PyInstaller 打包配置 |
| `gen_icon_bmp.py` | 生成 ICO 图标（依赖 `icon_preview.png` + Pillow；路径已相对化） |
| `gitee_upload.py` | 上传 `dist/网络工具箱.exe` 到 Gitee Release 679537 |
| `auto_updater.py` | 自动更新检查器（**当前未被主程序引用**，未集成） |
| `version_info.txt` | exe 版本资源（filevers/prodvers = 4.6.0.0，由 `gen_version_info.py` 生成） |
| `README.md` / `FIXES_v2.4.md` | 文档 |

## 4. 关键约定（必读，违反会引入 bug）

1. **线程安全（最重要）**：所有 UI 组件创建/销毁必须在**主线程**。耗时操作
   （ping / 诊断 / Clash HTTP API / 配置目录扫描）放 daemon 线程，线程里只采集数据，
   结果用 `self.after(0, lambda: self._render_xxx(data))` 回主线程渲染。
   —— 违反此约定正是 `test_err.txt` 中那个 `bad window path name` TclError 崩溃的根因，已修复。
2. **母亲节算法**：日期 = 每年 5 月第二个周日，`1 + ((6 - date(y,5,1).weekday()) % 7) + 7`。
   现已动态计算，非节日不弹窗（旧代码硬编码 `[9,10]` 只适配 2026，已修）。
3. **git 提交/推送需用户批准**：不要自动 commit/push，每次改动先告知用户。
   commit message 用**中文**。
4. **平台分流**：平台相关调用用 `IS_WINDOWS` / `IS_MAC`（`sys.platform`）分流，
   Windows 专属命令（Winsock/TCP-IP/DHCP）在 Mac 上禁用并提示，逻辑不可互相耦合。

## 5. 上次已修复的 Clash 外网问题（背景）

外网连不上的两类根因与对应修复：
- **Clash DNS 被关**（`dns.enable=false` + `enhanced-mode=fake-ip` → 解析超时）：
  `repair()` 步骤 2 开启并重启核心。
- **默认组选了死节点**（`delay=0`，如"新加坡1"）：`repair()` 步骤 3 通过 external-controller
  API (`GET /proxies` 查 dead 节点 → `PUT /proxies/{组}` 切到 URLTest 自动选择组)。
  相关方法：`repair_clash_selection` / `_find_dead_group` / `_find_auto_group` / `_clash_api_get` / `_clash_api_put`。

## 6. 待办 / 待确认事项（2026-09-23 v4.0 交付后更新）

- [x] ~~删除三个残留文件~~：`test.txt` / `test_err.txt` / 根目录 `network_reset_macos.py` 已删
      （`legacy/network_reset_macos.py` 为归档副本，无引用，不参与构建）。
- [x] ~~`auto_updater.py` 集成~~：标题栏「🔄 检查更新」已接入（仅 exe 模式，含 SHA256 校验）。
- [x] ~~`DiagnosticPanel`/`ProxyPanel` 抽 `ResultPanel` 基类~~（约 60 行重复已消除）。
- [x] ~~单例 socket 加 `SO_REUSEADDR`~~（避免 TIME_WAIT 时误判"已在运行"）。
- [x] ~~健康报告 `rc` 闭包~~ 已提为 `DiagnosticPanel._health_metric_card`。
- [ ] **安全提醒（仍待用户操作）**：`gitee_upload.py` 旧明文 token 可能已进入 git 历史，
      建议到 https://gitee.com/profile/personal_access_tokens 吊销；后续用
      `GITEE_TOKEN=<token> python gitee_upload.py` 运行（已支持命令行参数传 exe 路径/release_id）。
- [x] ~~**F7 定时自动体检 + 掉线记录**~~：`NetworkMonitor`（默认每 5 分钟 Ping 网关 + 223.5.5.5，
      保守判定防误报）落盘 `%LOCALAPPDATA%/NetworkResetTool/monitor/outages.json` +「📡 网络监控」标签页。
      顺带修掉真 bug：`on_event` 在锁内触发 → UI `summarize()` 抢同一把非重入锁 → 界面整体卡死
      （回调已挪到锁外，smoke_test 有回归用例）。
- [x] ~~**F9 DNS 测速排序**~~
- [x] ~~**F8 WiFi 信息管理**~~：`WifiTool`/`WifiPanel` 落地（详见第 9 节），bat 菜单 [7]，`--tab wifi`。
- [x] ~~**F6 网速测试**~~：`SpeedTester` 端点白名单(Cloudflare/CacheFly/OVH) + 12s/64MB 上限
      + fallback + 可停止(部分流量仍估算); 「⚡ 网速测试」标签页 + bat 菜单 [6] + `--tab speed`。
      顺手修掉手写码点把"宽"打成僻字 U+5BED 的界面怪字, 并加文案渲染守卫。：`benchmark_dns()` 各预设解析同域名 3 次取平均、排序显示，
      「⚡ DNS 测速排序」/「🏆 应用最快」按钮落在「🔄 网络重置」DNS 区。
- [x] ~~**CI 自动构建**~~：`.github/workflows/ci.yml` 已落地——smoke job 三平台
      (windows/ubuntu/macos) 跑 `compileall` + 冒烟测试；smoke-gui job 在 Windows 跑 `--gui`
      (tooltip 全遍历)；打 `v*` tag 时 build job 构建 Win x64 / Win7 x86 / macOS 三产物并上传 artifact。
      upx 尽力安装，镜像没有时自动退化为 upx=False 副本(upx 只影响体积)。
      **注意**：`网络工具箱.spec` 原先被 `.gitignore` 的 `*.spec` 忽略而未入 git，已加
      `!网络工具箱.spec` 例外——提交时务必把 spec 与 `gen_version_info.py` 一起 add，否则 CI 构建拿不到打包配置。
- [x] ~~**已知小瑕疵：裸 `self.after(0, ...)` 无兜底**~~：已根治——`_shared.py` 新增 `safe_after()`
      (窗口已销毁/关窗竞态时静默失败，不往 stderr 打 traceback)，`ui_panels.py` 68 处 + `app.py` 3 处
      全部替换；`ui_sync()` 内部也复用它(单一实现)。smoke_test 加了源码纪律守卫：
      任何裸 `.after(0,` 回投直接测失败(当前 218/232 项全绿)。

## 7. 如何构建 / 运行 / 发布

- **运行（开发）**：`python network_reset_gui.py`（网络重置需管理员；代理修复/诊断普通权限即可）
- **打包**：先 `python gen_version_info.py` 同步版本号，再 `pyinstaller 网络工具箱.spec` → 产物 `dist/网络工具箱.exe`
- **测试**：`python tests/smoke_test.py`（345 项）／`--gui` 追加 GUI 自检（合计 385 项）
- **CI**：`.github/workflows/ci.yml`（push/PR 跑三平台冒烟 + Windows GUI 自检；`v*` tag 触发三平台构建）
- **发布到 Gitee**：`GITEE_TOKEN=xxx python gitee_upload.py`（默认删旧 exe 并上传新 exe 到 Release 679537）
- **图标**：改完 `icon_preview.png` 后跑 `python gen_icon_bmp.py` 重新生成 ICO

## 8. 已知坑

- Windows 控制台 GBK 编码：输出含 emoji 的日志可能乱码（已在多处注意，新增脚本建议用
  `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")`）。
- Clash external-controller 端口默认 17650，secret 在 `config.yaml` 的 `secret` 字段；
  `read_clash_controller` 会读 `mixed-port`/`external-controller` 配置。

## 9. 2026-09-26 v4.2 交付记录（F8 WiFi 信息管理）

- **引擎层 `WifiTool`**（`engine.py`）：`parse_profiles` 兼容 netsh 输出简体/繁体/英文三套前缀
  并去重保序；`parse_profile_detail` 取密码（关键内容/金鑰內容/Key Content）与认证方式，
  并区分**拒绝访问 / wlansvc 未运行 / 找不到配置文件**三类故障。命令一律以 argv 列表执行
  （不经 shell），SSID 含空格/引号也不会注入；解析与执行分层，便于打桩测试。
- **界面层 `WifiPanel`**（`ui_panels.py`，第七个标签页）：表格展示 SSID/密码/认证方式；
  非管理员启动时顶部横幅提示"仍能列出已保存 WiFi，但读不出密码"；任务放 daemon 线程，
  结果经 `ui_sync` 回主线程（遵守线程安全铁律）；「💾 导出」写 UTF-8 txt 并弹明文密码警示。
- **接线**：`app.py` 七个标签页 + `--tab wifi` 白名单；`network-reset.bat` 新增
  「[7] WiFi 信息（已保存密码）」（exe→py→python 三级回退）；`__init__.py` 导出
  `WifiTool` / `WifiPanel`。
- **测试**：`t_wifi()` 新增 33 项断言（三语解析/去重/三类故障/打桩全流程/非 Windows 分支/
  导出）；`t_gui` 增加 WifiPanel 构造、表格列名与文案守卫。`--gui` 合计 286 项全部通过。
- **遗留（下轮可做）**：F13 插件式诊断项；`auto_updater.py` 仍未接入
  Release 版本号比对之外的自定义流程（保持现状即可）。
  Release 版本号比对之外的自定义流程（保持现状即可）。
- **CLI 注意事项**：`cli.py` 里 `IS_WINDOWS` / `is_admin` 是值导入，打桩测试要改
  `cli.IS_WINDOWS` 而不是 `_shared.IS_WINDOWS`（engine 同理，`t_wifi` 已用这套办法）。

---

## 10. 2026-09-26 v4.3 交付记录（F11 深色/浅色主题切换）

- **双主题配色表**（`_shared.py`）：`THEMES` 含深色 Catppuccin Mocha 与浅色 Catppuccin Latte
  两套，共 20 个语义键；新增 `card` / `warn_bg` / `warn_fg` 三个语义键，并清掉
  `ui_panels.py` 里 25 处写死的 hex 底色。`COLORS = dict(THEMES[DEFAULT_THEME])`，
  `set_theme()` 用 `clear()+update()` **就地覆写**，各模块持有的同一 dict 引用同步换色。
- **主题记忆**：`theme_path()` / `current_theme()` / `set_theme()` / `toggle_theme()`，
  偏好落盘 `%LOCALAPPDATA%/NetworkResetTool/theme.txt`；缺失/损坏/非法主题名都回落到
  默认深色，写失败不影响本次生效。`App.__init__` 在 `_build_ui()` 之前套用，首屏不闪默认色。
- **界面层**（`app.py`）：顶栏新增「🌙 深色 / ☀️ 浅色」按钮；`_toggle_theme()` → `_rebuild_ui()`
  销毁并重建整棵窗口树后切回原标签页；`MonitorPanel.destroy()` 停掉巡检线程避免重建后双线程空转；
  `_rebuild_ui()` 重设顶层窗口底色，避免边框残留旧主题颜色。
- **Treeview**：新增 `config_treeview_style(widget)`，端口 / 监控事件 / WiFi 三处表格统一切到
  主题化 ttk 样式；`tk.Scrollbar` 不吃 ttk style，另加 `theme_scrollbar()` 工厂给 5 处
  滚动条着色（原来退回 `SystemButtonFace`，深色界面里很扎眼）。
- **报告配色跟随主题**：`report.py` 的 HTML 报告原先写死一套 GitHub 浅色 CSS 变量，改为从
  `COLORS` 取；`@media print` 仍强制浅色，避免深色主题导出的报告打印一片黑。
- **顺手修正**：`DNS_PRESETS` 的颜色由 import 期固定色值改为语义键名，
  由 `_make_dns_btn` 构造时按当前主题解析；另修掉 `ui_panels.py` 里 6 处被写成
  字面量码点文本（`"U0001F4E1 网络监控"`）的 emoji，并补源码守卫防回归。
- **修换主题暴露的 TclError**：`safe_after()` 原本只兜住"调度失败"，兜不住
  "执行时控件已被 destroy"——换主题重建后旧面板线程回投会抛
  `TclError: invalid command name` 并往 stderr 打 traceback。现于回调外层补 TclError
  兜底（不能用 `winfo_exists()` 跳过，否则 `ui_sync` 的 Event 会白等 30s 超时）。
- **测试**：`t_theme()` 25 项（键集合一致 / 色值格式 / 源码无写死底色 / 源码无字面量 codepoint /
  theme.txt 读写与容错 / COLORS 不被重新绑定 / 跨模块引用同步 / toggle 往返 / DNS 语义键）；
  `t_gui` 追加 App 级切换自检与 MonitorPanel 文案守卫；结束时还原 `COLORS` 与用户 `theme.txt`。
  另加 `t_theme_widgets()` 控件级校验（深浅两套主题下真实构造 7 个面板，遍历每个控件的
  bg/fg 与色板比对），以及 HTML 报告配色跟随主题的回归断言。`--gui` 合计 336 项全绿。

---

## 11. 2026-09-26 v4.4 交付记录（F10 命令行模式）

GUI 之外补齐可脚本化的无界面入口，核心约束是**绝不碰 Tk**——
不起窗口、不弹对话框，没有桌面会话的服务器 / SSH / CI 里也能跑。

- **`network_toolbox/cli.py`（新增）**：12 个子命令复用既有引擎，不重写业务逻辑；
  `adapters` / `diagnose` / `reset` / `dns` / `proxy` / `ports` / `speed` / `wifi` /
  `monitor` / `snapshots` / `report` / `hosts`。
- **argparse 子命令式 help**：subparsers + parent parser 继承 `--adapter`/`--json`，
  `--cli dns --help` 只显示该命令用得到的参数。
- **`--json` 纯净输出**：stdout 只有一个 JSON 对象（`ok`/`command`/`data`/`warnings`），
  日志走 stderr，无 BOM，可直接 `jq` / `ConvertFrom-Json`。
- **退出码语义固定**：0 成功 / 1 操作失败 / 2 参数错误 / 3 需要管理员 /
  4 平台不支持 / 130 被 Ctrl+C 取消。`CliError` 带码抛出，`--json` 时把 `exit_code`
  写进 `data`，调用方不必解析 stderr。
- **权限闸门**：`reset` / `proxy --repair` / `ports --kill` / `hosts --fix` 先查管理员权限，
  不足即退 3，不会跑到一半才失败。
- **入口分流**：`network_reset_gui.py` 在 import 整个包**之前**判 `--cli`，
  不拖 Tk 依赖；`run_cli()` 显式 `_release_singleton()`，
  否则 CLI 占着端口会让随后启动的 GUI 误判"程序已在运行"。
- **踩坑**：最初丢了 `_cli_main()` 的返回值直接 `sys.exit(0)`，脚本永远判断成功；
  已改 `sys.exit(_cli_main())` 并加回归断言。
- **测试**：`t_cli()` 26 项断言；守卫做过反向验证（入口改回 exit(0)、cli.py 里
  import tkinter、去掉平台闸门，三者均被抓红）。`--gui` 合计 365 项全绿。
- **同轮补的编码修正**（真机跑 exe 时发现，与 F10 直接相关）：
  - engine 日志里有 ✓/✗/⚠/🎉/🔄，GBK 控制台 `print` 会抛
    `UnicodeEncodeError` 把整条命令炸掉；现由 `_lossy_streams()`
    把 stdout/stderr 的错误处理改成 `backslashreplace`，中文照常显示。
  - `--json` 原来走 `print`，控制台是 GBK 时中文 JSON 会变 GBK 字节，
    `jq` 直接报 invalid UTF-8；现由 `_emit()` 写 `sys.stdout.buffer` 强制 UTF-8。
  - `report --json` 不带 `--out` 时会把报告正文倒到 stdout，污染 JSON 流；
    现改为放进 `data.content`。
  - 回归测试打了 GBK `TextIOWrapper` 假流（2 项），`report --json` 用
    `C.render_report` 打桩（1 项）——注意 cli.py 是值导入，得打模块属性。
- **同轮修的测试污染**：`_walk_panel_colors` 切浅色主题后不还原，
  跑一次 `--gui` 就把用户的 `theme.txt` 改成 light；现已 backup/restore。

## 12. 2026-09-26 v4.5 交付记录（F12 多语言）

- **`network_toolbox/i18n.py`（新增）**：以中文字符串本身为 key 的轻量 i18n，
  `tr()` / `tr_f()` + `lang_path()` / `current_lang()` / `set_lang()`，
  偏好落盘 `%LOCALAPPDATA%/NetworkResetTool/lang.txt`（与 `theme.txt` 同模式）。
  `current_lang()` 带记忆缓存，测试里改完文件必须 `I._lang = None` 再读（已封装成 `_reread()`）。
- **英文目录 `EN` 530 条**：只写差异，缺 key 回落中文，永不 KeyError。
  刻意不翻译的：6 条正则 + netsh 简/繁解析标记 + 程序名。这批豁免在 `t_i18n()` 的豁免清单里
  用 `\uXXXX` 转义硬编码，**改那份清单别手打中文**，会被 shell here-string 改坏。
- **AST 自动包装**：把 5 个源文件里展示位的中文普通字面量包成 `tr(...)`。
  包装器安全规则（改代码前必读）：`ast.Constant.col_offset` 是 **UTF-8 字节偏移**，
  必须先换算成字符下标，否则中文一多就整体错位把文件改烂；跳过 dict key / 下标 / 比较运算两侧 /
  docstring / f-string(`JoinedStr`) 内部常量；只处理单行 token；包完必须 `compile()` 通过否则抛错。
- **界面**：`app.py` 启动时 `set_lang(current_lang())`；顶栏新增「🌐 中文 / 🌐 EN」按钮
  （在主题按钮左侧）；`_toggle_lang()` → `_rebuild_ui()` 保留当前 tab；
  主题按钮标签改 `tr(THEME_LABELS[...])`。
- **CLI**：`--lang {zh,en}` 挂在 common parent parser 上，`run_cli()` 里
  `if getattr(args, "lang", None): set_lang(args.lang)`；help/epilog 已 `tr(...)` 包裹
  （epilog 结尾是三个连续双引号加右括号，改的时候别数错括号）。
- **测试**：`t_i18n()` 新增 20 项断言，核心是 AST 扫 `tr("...")` 中文文案必须全部在 `EN` 目录里；
  `main()` 开头已 `set_lang("zh")`，保证用户切成英文时中文断言仍然成立。
- **验证**：`python tests/smoke_test.py` → 372 项；`--gui` → 412 项，全绿。
  英文模式实测构造 7 个面板遍历控件文案，93 条里 86 条已英化，余下为 f-string 运行时组合文案。

### 12.1 同日补修：F12 打包器带出来的三个真的 bug

- **解析标记被误翻译**（最严重）：`WifiTool` 的 `PROFILE_PREFIXES` / `KEY_LABELS` /
  `AUTH_LABELS` / `DENIED_MARKS` / `NOT_RUNNING_MARKS` / `NOT_FOUND_MARKS` 和
  `ProxyRepairTool._find_auto_group` 的候选组名都被包了 `tr()`。
  这些是拿来和 netsh / Clash 返回做匹配的。现象：中文系统上界面
  一切英文，WiFi 密码列全变「未取到」。已改回纯字面量。
- **`--lang` 只能写在子命令后面**：现在顶层 parser 也注册一份，
  子命令侧默认值改 `argparse.SUPPRESS`（不然顶层解析出的值会被覆盖）。
- **`--help` 不跟 `--lang`**：usage/epilog 在 `build_parser()` 就固化了，故改为
  `_peek_lang(argv)` 先拣语言、建 parser 之前 `set_lang(..., persist=False)`。
  `set_lang` 固定参数新增 `persist=False`：一次性命令不写 `lang.txt`。
- **评分卡配色失效**：`ui_panels` 的配色表键写死中文，切英文后全落灰色；
  抽成 `_grade_color()`，键与 grade 同走 `tr()`。
- **添加的回归守卫**：`t_i18n()` 新增"语言不得影响解析"——用真实的中文
  netsh 输出在 zh/en 两种语言下各跑一遍；`t_cli()` 新增 `--lang` 四种写法、
  975e法值拒绝、`--help` 语言跟随、`lang.txt` 不被写回。

**教训**：AST 打包只能自动识别"展示位"，识别不了"参与匹配的位"。
除了"\(tr\)文案必须有英文翻译"这条静态门闸，还得有"关键解析在两种语言下都对"这条行为门闸。


## 13. 2026-09-26 v4.6 交付记录（F13 插件式诊断项）

- **`network_toolbox/plugins.py`（新增）**：把"完整诊断"拆成一组可注册的诊断项。
  - `DiagnosticItem(key, run, title, fallback, builtin)`，`__slots__` 固定 5 个字段；
    构造时校验 key（ASCII 标识符，点号分段做命名空间）与 run（必须可调用）
  - `register_item()` 支持 `DiagnosticItem` 或 `(key, run, title=..., fallback=...)` 两种写法；
    内置 key / 同名重复注册都抛 `ValueError`
  - `unregister_item()` 对内置项和未注册 key 一律返回 False（不抛）
  - `diagnostic_items()` = 内置三项（按 `BUILTIN_KEYS` 序）+ 自定义项（按注册序）；
    `custom_keys()` 只列自定义项
  - `run_diagnostics(tool, progress_callback)` 逐项 `try/except`，失败写日志 + 换 `fallback`，
    最后统一 `progress_callback(100, tr("诊断完成"))`
  - 只 import `network_toolbox.i18n`，**不 import engine**（engine 反向 import 本模块）
- **`engine.py`**：`run_full_diagnostic()` 74 行内联逻辑 → 一行
  `return run_diagnostics(self, progress_callback)`；新增
  `from network_toolbox.plugins import run_diagnostics`。内置三个 run 函数按原样搬迁，
  日志文案与进度百分比（0 / 10~50 / 55~95 / 100）逐字保留。
- **`__init__.py`**：导出 `DiagnosticItem` / `register_item` / `unregister_item` /
  `diagnostic_items` / `custom_keys` / `run_diagnostics` / `reset_registry`，
  兼容入口 `network_reset_gui` 同样可见。
- **`cli.py`**：`diagnose` 子命令在跑诊断前打印 `自定义诊断项: ...`，
  `--json` 的 `data` 里新增 `custom_items` 字段。

### 13.1 顺手修掉的缺陷

- **空表除零**：原 `total_dns = len(self.DNS_TARGETS)`，`DNS_TARGETS` 为空时
  `i / total_dns` 直接 `ZeroDivisionError` 炸掉整轮诊断 → 改 `len(...) or 1`（ping 侧同样）
- **失败日志不跟随语言**：`获取网络状态失败` 原为裸中文字面量 → 改走 `tr()`，
  `EN` 目录同步补英文
- **日志回调不再能炸掉诊断**：新增 `_log()` 包装 `log_callback`，回调自身抛异常时静默

### 13.2 测试

- `t_plugins()` 新增 36 项断言：内置三项顺序/`builtin` 标记、自定义项参与诊断且排在内置项之后、
  单项崩溃只掉自己并进日志、7 种非法 key、`run` 不可调用、非 DiagnosticItem/str 入参、
  覆盖内置项 / 同名重复注册被拒、注销语义、`reset_registry()` 隔离
- engine 委托用**真实 `NetworkDiagnostic` 实例 + 打桩**验证，确认不是只剩一层空壳
- `t_i18n()` 的 AST 扫描清单加入 `plugins.py`（新增 `tr()` 中文文案必须补英文）
- **验证**：`python tests/smoke_test.py` → 413 项；`--gui` → 453 项，全绿
- **CLI 英化补鼓（F12 遗留）**：`cmd_diagnose` + 其余 7 个子命令里共 15 处
  `r.log(f"...中文...")` 全部改跟 `tr_f()`（f-string 是 AST 打包器的盲区，只能手动），
  并补 13 条英文翻译。现在 `--lang en` 下各子命令输出零中文残留。
- **修掉一个让测速功能完全失效的真 bug**：`SpeedTester._run_one` 把中文
  `User-Agent: 网络工具箱/v4.x` 写进请求头，urllib 以 latin-1 编码头，每次请求都抛
  `UnicodeEncodeError` → 三个端点全部 fallback 失败（和 v3.4 修过的自动更新同样的坑）。
  抽出 `_shared.http_user_agent()`（非 latin-1 字符按 UTF-8 percent-encode）并在 `t_speed()`
  新墟 3 项实际 `Request.headers` 断言。修复前 exe 测速=0，修复后 106.8 / 300.2 Mbps。
  **教训**：新功能加请求时一定要走 `http_user_agent()`，不要直接 f-string `APP_NAME`。

### 13.3 怎么加一个自己的诊断项

```python
from network_toolbox import register_item

register_item(
    "myplug.gateway",                      # key: ASCII 标识符，点号做命名空间
    lambda tool, progress=None: {          # run(tool, progress=None) -> 数据或 None
        "ok": bool(tool.get_overview()),
    },
    title="我的网关检查",                   # 只用于日志
    fallback={"ok": False},                # 抛异常时顶上来的值
)
```

跑一次诊断，结果字典里就会多一个 `myplug.gateway` 键；CLI 的 `diagnose` 也会把它列出来。
