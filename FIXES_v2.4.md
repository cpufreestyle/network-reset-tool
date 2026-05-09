# Network Reset Tool v2.4 - Bug Fixes

## 修复的问题

### 1. DNS一键切换"未找到活动网卡"问题

**根本原因:**
- `_get_active_adapter()` 方法只使用 `Get-NetAdapter` 命令，该命令在某些旧版Windows或权限不足时会失败
- 没有备选方案，导致无法获取网卡名称

**修复方案:**
- 增加多个备选方法获取活动网卡:
  1. `Get-NetAdapter` (Windows 8/Server 2012+)
  2. `Get-WmiObject Win32_NetworkAdapter` (兼容性更好)
  3. `ipconfig` 解析 (最后备选)
- 添加详细错误日志，方便排查问题

### 2. 日志界面闪退问题

**根本原因:**
- Lambda 捕获bug: `lambda m: self._log(m)` 中的 `m` 被所有回调共享，导致日志内容混乱
- 多线程同时访问 `self.log_box` 导致 Tkinter 崩溃
- `tool.log_callback` 在多线程环境下直接调用 UI 更新方法

**修复方案:**
- 使用 `functools.partial` 替代 lambda，避免变量捕获问题
- 创建 `_safe_log()` 方法，确保日志更新通过 `after()` 在主线程执行
- 所有日志回调统一使用 `functools.partial(self._safe_log)`

### 3. 网络诊断无法完成问题

**根本原因:**
- `run_full_diagnostic()` 中的异常没有正确处理
- PowerShell 命令执行超时或失败时，整个诊断流程中断

**修复方案:**
- 为每个诊断步骤添加 `try-except` 错误处理
- 单个目标失败不影响整体诊断流程
- 添加详细错误日志输出

## 主要代码变更

### ResetPanel 类

```python
# 修复前
tool = NetworkResetTool(log_callback=lambda m: self.after(0, lambda: self._log(m)))

# 修复后
tool = NetworkResetTool(log_callback=functools.partial(self._safe_log))
```

### _get_active_adapter() 方法

```python
# 修复前 - 只有一种方法
ps1 = 'Get-NetAdapter | Where-Object { $_.Status -eq "Up" }...'

# 修复后 - 三种备选方法
def _get_active_adapter(self):
    # 方法1: Get-NetAdapter
    try:
        result = subprocess.run(['powershell', '-NoProfile', '-Command', ps1], ...)
        if result.stdout.strip():
            return result.stdout.strip()
    except: pass

    # 方法2: WMI
    try:
        result = subprocess.run(['powershell', '-NoProfile', '-Command', ps2], ...)
        if result.stdout.strip():
            return result.stdout.strip()
    except: pass

    # 方法3: ipconfig 解析
    ...

    return None
```

### 线程安全日志

```python
def _safe_log(self, msg):
    """线程安全的日志输出"""
    self.after(0, functools.partial(self._log, msg))
```

## 文件清单

- `network_reset_gui_v2.4.py` - 修复后的主程序
- `FIXES_v2.4.md` - 本说明文档

## 测试建议

1. 在无管理员权限下测试
2. 在无线网络、有线网络环境下分别测试
3. 测试 DNS 切换功能
4. 测试网络诊断功能
5. 观察是否还有闪退现象

## 下一步

- 编译为 .exe (使用 PyInstaller)
- 创建 GitHub/Gitee Release v2.4
- 更新 README.md
