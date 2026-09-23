# 交接文档 (Agent Handoff) — network-reset-tool

> ⚠️ 注意：本目录并非 v3.3 基线空仓库，而是**已由另一 agent 推进到 v3.5**——
> 单文件已重构为 `network_toolbox/` 包、含 `tests/`、`legacy/`（归档旧 macOS 脚本）、
> 自动更新 SHA256 校验、导出报告/快照回滚/网卡下拉框等。
> **最新规划与已做工作以 `OPTIMIZATION_AND_FEATURES.md` 为准**（含 v3.3~v4.0 排期）。
> 本文件下方记录的是 v3.3 阶段的修复与**通用约定（线程安全铁律/母亲节算法/平台分流/commit 需批准）仍适用**。

> 本文件为 AI agent 接手项目时准备，含项目状态、关键约定、已完成工作与待办。
> 纯交接用途，不需要提交到 git（如要清理可直接删除本文件）。

## 1. 项目概览

- **名称**：网络工具箱 (Network Reset Tool)
- **功能**：Windows/macOS 一键网络重置 + 网络诊断 + Clash/系统代理修复（外网连不上时排查）
- **形态**：Python 3 + Tkinter 单文件 GUI；PyInstaller 打包成 `dist/网络工具箱.exe`
- **当前版本**：v3.3（跨平台版，GUI 已实现 Windows + macOS 双端复用）

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
| `network_reset_gui.py` | 主程序（约 2900 行）。含 `App` / `ResetPanel` / `DiagnosticPanel` / `ProxyPanel` 四个类，以及 `NetworkDiagnostic`、`ProxyRepairTool` 两个后端工具类 |
| `network-reset.bat` | Windows 命令行启动菜单（需管理员） |
| `网络工具箱.spec` | PyInstaller 打包配置 |
| `gen_icon_bmp.py` | 生成 ICO 图标（依赖 `icon_preview.png` + Pillow；路径已相对化） |
| `gitee_upload.py` | 上传 `dist/网络工具箱.exe` 到 Gitee Release 679537 |
| `auto_updater.py` | 自动更新检查器（**当前未被主程序引用**，未集成） |
| `version_info.txt` | exe 版本资源（filevers/prodvers = 3.3.0.0） |
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

## 6. 待办 / 待确认事项

- [ ] **删除三个残留文件**（delete_file 一直超时未授权）：`test.txt`(仅"test")、
      `test_err.txt`(调试错误日志)、`network_reset_macos.py`(已被跨平台 v3.3 取代，README 已不再引用)。
- [ ] **安全提醒**：`gitee_upload.py` 旧明文 token 已从代码移除，但可能已进入 git 历史，
      建议到 https://gitee.com/profile/personal_access_tokens 吊销该 token，
      后续用 `GITEE_TOKEN=<token> python gitee_upload.py` 运行（已支持命令行参数传 exe 路径/release_id）。
- [ ] **可选后续优化**（尚未做，仅供参考）：
      1. 抽取 `DiagnosticPanel` 与 `ProxyPanel` 的公共 `ResultPanel` 基类（仍重复 `_card`/`_result_*`/`canvas+scrollbar` 约 60 行）。
      2. 把 `auto_updater.py` 集成进 GUI（做"检查更新"按钮），或删除该未使用文件。
      3. 单例 socket 加 `SO_REUSEADDR`，避免 TIME_WAIT 时启动失败。
      4. 健康报告 (`_render_health_report`) 内 `rc` 闭包为嵌套函数，可考虑提为方法。

## 7. 如何构建 / 运行 / 发布

- **运行（开发）**：`python network_reset_gui.py`（网络重置需管理员；代理修复/诊断普通权限即可）
- **打包**：`pyinstaller 网络工具箱.spec` → 产物 `dist/网络工具箱.exe`
- **发布到 Gitee**：`GITEE_TOKEN=xxx python gitee_upload.py`（默认删旧 exe 并上传新 exe 到 Release 679537）
- **图标**：改完 `icon_preview.png` 后跑 `python gen_icon_bmp.py` 重新生成 ICO

## 8. 已知坑

- Windows 控制台 GBK 编码：输出含 emoji 的日志可能乱码（已在多处注意，新增脚本建议用
  `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")`）。
- Clash external-controller 端口默认 17650，secret 在 `config.yaml` 的 `secret` 字段；
  `read_clash_controller` 会读 `mixed-port`/`external-controller` 配置。
