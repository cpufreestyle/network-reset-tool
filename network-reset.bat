@echo off
chcp 65001 >nul 2>&1
title 网络工具箱 v3.2 - 网络重置工具
color 0A

net session >nul 2>&1
if %errorLevel% neq 0 (
    color 0C
    echo.
    echo  需要管理员权限，请右键选择"以管理员身份运行"此文件
    echo.
    pause
    exit /b 1
)

setlocal enabledelayedexpansion

:MENU
cls
echo.
echo  ========================================
echo     网络工具箱 v3.2
echo     网络重置 + DNS切换 + 诊断
echo  ========================================
echo.
echo  [1] 完整网络重置（6阶段）
echo  [2] 快速DNS切换
echo  [3] 网络诊断
echo  [4] 退出
echo.
set /p choice=请选择 (1-4): 

if "%choice%"=="1" goto FULL_RESET
if "%choice%"=="2" goto DNS_SWITCH
if "%choice%"=="3" goto DIAGNOSTIC
if "%choice%"=="4" exit /b 0
goto MENU

:: ============================================================
::  完整网络重置
:: ============================================================
:FULL_RESET
cls
echo.
echo  ========================================
echo     网络工具箱 v3.2 - 完整网络重置
echo  ========================================
echo.

echo [阶段 1/6] 备份静态IP配置...
powershell -NoProfile -Command "$adapters = Get-WmiObject Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -and $_.DHCPEnabled -eq $false }; if ($adapters) { foreach ($a in $adapters) { $id = $a.SettingID; $name = (Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.GUID -eq $id }).NetConnectionID; $ip = $a.IPAddress -join ','; $mask = $a.IPSubnet -join ','; $gw = $a.DefaultIPGateway -join ','; $dns = $a.DNSServerSearchOrder -join ','; Write-Host ('  备份静态IP: ' + $name + ' - ' + $ip); Set-Content -Path ([System.IO.Path]::Combine($env:TEMP, 'static_' + $id + '.txt')) -Value ($name + '|' + $ip + '|' + $mask + '|' + $gw + '|' + $dns) } } else { Write-Host '  未发现静态IP配置' }"
echo.

echo [阶段 2/6] 重置 Winsock...
netsh winsock reset >nul 2>&1
echo  完成

echo [阶段 3/6] 重置 TCP/IP 协议栈...
netsh int ip reset >nul 2>&1
netsh int ipv6 reset >nul 2>&1
echo  完成

echo [阶段 4/6] 清除缓存...
ipconfig /flushdns >nul 2>&1
netsh interface ip delete arpcache >nul 2>&1
echo  完成

echo [阶段 5/6] 刷新 DHCP...
ipconfig /release >nul 2>&1
echo  已释放，正在重新获取...
ipconfig /renew >nul 2>&1
echo  完成

echo [阶段 6/6] 恢复静态IP配置...
for %%f in (%TEMP%\static_*.txt) do (
    for /f "usebackq tokens=1-5 delims=|" %%a in ("%%f") do (
        set adapter=%%a
        set ipaddr=%%b
        set subnet=%%c
        set gateway=%%d
        set dnsserv=%%e
        echo  恢复: !adapter!
        if not "!ipaddr!"=="" (
            netsh interface ip set address "!adapter!" static !ipaddr! !subnet! !gateway! 1 >nul 2>&1
            echo    IP: !ipaddr!
        )
        if not "!dnsserv!"=="" (
            for /f "tokens=1 delims=," %%d in ("!dnsserv!") do netsh interface ip set dns "!adapter!" static %%d primary >nul 2>&1
        )
    )
    del "%%f" >nul 2>&1
)

echo.
echo  ========================================
echo          网络重置完成！
echo  ========================================
echo.
echo  建议重启计算机以使更改生效
echo.

set /p restart=是否重启计算机?(Y/N): 
if /i "%restart%"=="Y" (
    shutdown /r /t 5
    echo  5秒后重启...
    timeout /t 5 >nul
)
pause
goto MENU

:: ============================================================
::  DNS 快速切换
:: ============================================================
:DNS_SWITCH
cls
echo.
echo  ========================================
echo     网络工具箱 v3.2 - DNS 快速切换
echo  ========================================
echo.

:: 获取活动网卡名称
set "ADAPTER="
for /f "delims=" %%a in ('powershell -NoProfile -Command "($adapter = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | Select-Object -First 1).NetConnectionID; if ($adapter) { Write-Output $adapter }"') do set "ADAPTER=%%a"

if "%ADAPTER%"=="" (
    echo  未检测到活动网卡！
    pause
    goto MENU
)
echo  当前活动网卡: %ADAPTER%
echo.

:: 显示当前DNS
echo  当前 DNS 配置:
powershell -NoProfile -Command "Get-DnsClientServerAddress -InterfaceAlias '%ADAPTER%' -AddressFamily IPv4 | ForEach-Object { Write-Host ('  ' + $_.ServerAddresses -join ', ') }"
echo.

echo  DNS 预设:
echo  [1] 自动获取 (DHCP)
echo  [2] 阿里 DNS    223.5.5.5 / 223.6.6.6
echo  [3] Google DNS  8.8.8.8 / 8.8.4.4
echo  [4] Cloudflare  1.1.1.1 / 1.0.0.1
echo  [5] 114 DNS     114.114.114.114 / 114.114.115.115
echo  [0] 返回主菜单
echo.
set /p dns_choice=请选择 DNS (0-5): 

if "%dns_choice%"=="0" goto MENU
if "%dns_choice%"=="1" (
    netsh interface ip set dns "%ADAPTER%" dhcp >nul 2>&1
    echo.
    echo  已切换为 DHCP 自动获取 DNS
)
if "%dns_choice%"=="2" (
    netsh interface ip set dns "%ADAPTER%" static 223.5.5.5 primary >nul 2>&1
    netsh interface ip add dns "%ADAPTER%" 223.6.6.6 index=2 >nul 2>&1
    echo.
    echo  已切换为阿里 DNS (223.5.5.5 / 223.6.6.6)
)
if "%dns_choice%"=="3" (
    netsh interface ip set dns "%ADAPTER%" static 8.8.8.8 primary >nul 2>&1
    netsh interface ip add dns "%ADAPTER%" 8.8.4.4 index=2 >nul 2>&1
    echo.
    echo  已切换为 Google DNS (8.8.8.8 / 8.8.4.4)
)
if "%dns_choice%"=="4" (
    netsh interface ip set dns "%ADAPTER%" static 1.1.1.1 primary >nul 2>&1
    netsh interface ip add dns "%ADAPTER%" 1.0.0.1 index=2 >nul 2>&1
    echo.
    echo  已切换为 Cloudflare DNS (1.1.1.1 / 1.0.0.1)
)
if "%dns_choice%"=="5" (
    netsh interface ip set dns "%ADAPTER%" static 114.114.114.114 primary >nul 2>&1
    netsh interface ip add dns "%ADAPTER%" 114.114.115.115 index=2 >nul 2>&1
    echo.
    echo  已切换为 114 DNS (114.114.114.114 / 114.114.115.115)
)

echo  刷新 DNS 缓存...
ipconfig /flushdns >nul 2>&1
echo  完成！
echo.
pause
goto MENU

:: ============================================================
::  网络诊断
:: ============================================================
:DIAGNOSTIC
cls
echo.
echo  ========================================
echo     网络工具箱 v3.2 - 网络诊断
echo  ========================================
echo.

:: 概览
echo  --- 网络概览 ---
echo.

:: IP 配置
echo  [IP 配置]
ipconfig | findstr /i "IPv4 子网掩码 Subnet 默认网关 Default"
echo.

:: 连接测试
echo  [连接测试]
echo  正在 ping baidu.com ...
ping -n 2 baidu.com >nul 2>&1
if %errorLevel%==0 (
    echo  baidu.com ......... 正常 ✓
) else (
    echo  baidu.com ......... 失败 ✗
)

echo  正在 ping 8.8.8.8 ...
ping -n 2 8.8.8.8 >nul 2>&1
if %errorLevel%==0 (
    echo  8.8.8.8 ........... 正常 ✓
) else (
    echo  8.8.8.8 ........... 失败 ✗
)

echo  正在 ping 114.114.114.114 ...
ping -n 2 114.114.114.114 >nul 2>&1
if %errorLevel%==0 (
    echo  114.114.114.114 ... 正常 ✓
) else (
    echo  114.114.114.114 ... 失败 ✗
)
echo.

:: DNS 解析
echo  [DNS 解析]
echo  正在解析 baidu.com ...
nslookup baidu.com >nul 2>&1
if %errorLevel%==0 (
    echo  baidu.com 解析 ..... 正常 ✓
) else (
    echo  baidu.com 解析 ..... 失败 ✗
)
echo.

:: DNS 缓存
echo  [DNS 缓存状态]
ipconfig /displaydns | findstr /i "记录数 Record" >nul 2>&1
echo  DNS 缓存已显示
echo.

:: 默认网关
echo  [默认网关]
for /f "tokens=2 delims=:" %%g in ('ipconfig ^| findstr /i "Default 默认网关" ^| findstr /r "[0-9]"') do (
    set gw=%%g
    set gw=!gw: =!
    echo  网关: !gw!
    ping -n 1 !gw! >nul 2>&1
    if !errorLevel!==0 (
        echo  网关连接 ......... 正常 ✓
    ) else (
        echo  网关连接 ......... 失败 ✗
    )
)
echo.

echo  ========================================
echo          诊断完成！
echo  ========================================
echo.
echo  提示: 如果外网 ping 失败但网关正常，
echo  可能是 DNS 问题，请尝试切换 DNS
echo.
pause
goto MENU
