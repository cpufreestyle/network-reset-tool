## v4.6.1 — 诊断去黑框 · 提速至秒级 · 双击即提权

v4.6.0 的修复维护版：网络诊断中的命令子进程不再逐个闪出黑色控制台窗口，完整诊断耗时从约 77 秒降到约 5 秒。打包产物新增 Windows 管理员清单，双击自动触发 UAC，无需再右键“以管理员身份运行”。

### 主要改动

- 统一所有命令子进程走 `run_subprocess()`：Windows 下自动带 `CREATE_NO_WINDOW` 与 `STARTUPINFO(SW_HIDE)`，覆盖 `netsh` / `ping` / `nslookup` / `powershell` / `ipconfig` 等调用路径
- 网络总览优先使用 Win32 `GetAdaptersInfo` / `GetIpForwardTable` 直接读取，避开 `Get-NetAdapter` PowerShell 启动慢和常见 10 秒超时
- `ping` 缩短等待时间并补齐单包延迟解析；Windows 下 `nslookup` 使用 `-retry:0 -timeout:1`，不可达 DNS 不再拖慢整轮
- 为本地部署加入 `deploy.ps1` 和 `网络工具箱-admin.spec`：自检、打包、安装到 `%LOCALAPPDATA%`、创建桌面快捷方式一条命令完成
- 打包 exe 写入 `requireAdministrator` 清单，双击即请求管理员权限
- `version_info.txt` 由 `APP_VERSION` 生成，版本号升至 4.6.1

### 验证

- `python tests/smoke_test.py` → 413 项全绿
- `python tests/smoke_test.py --gui` → 453 项全绿
- 真机完整诊断：约 5 秒完成，无控制台窗口闪烁
- 打包产物包含 `requireAdministrator` 清单

### 下载与校验

| 文件 | 平台 | SHA256 |
|:---|:---|:---|
| `NetworkToolbox_x64.exe` | Windows 10/11 64-bit | `B870D1D06062900EC16B2C3604AE12E93992E8F136E9C9FA6F65B49B937CCED2` |
| `NetworkToolbox_win7_x86.exe` | Windows 7 32-bit | `5D8489AA27DF24DB47D8555C0EE4D6D969959B074EC66AB4D39474B3705B2BDD` |

```powershell
Get-FileHash -Algorithm SHA256 NetworkToolbox_x64.exe
Get-FileHash -Algorithm SHA256 NetworkToolbox_win7_x86.exe
```

> - 窗口标题显示完整版本号 `v4.6.1`。
> - Windows GUI 版需**以管理员身份运行**才能使用全部功能；x64 与 Win7 32-bit 版均已内嵌 `requireAdministrator` 清单，双击自动触发 UAC。
