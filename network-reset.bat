@echo off
chcp 65001 >nul 2>&1
title 网络重置工具 v1.0 - 保留静态IP配置
color 0A

net session >nul 2>&1
if %errorLevel% neq 0 (
    color 0C
    echo.
    echo  需要管理员权限！请右键选择以管理员身份运行
    echo.
    pause
    exit /b 1
)

setlocal enabledelayedexpansion

echo.
echo  ========================================
echo     网络重置工具 v1.0
echo     保留静态IP - 兼容 Win7 32位及以上
echo  ========================================
echo.

echo [阶段 1/6] 备份静态IP配置...
powershell -NoProfile -Command "$adapters = Get-WmiObject Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -and $_.DHCPEnabled -eq $false }; if ($adapters) { foreach ($a in $adapters) { $id = $a.SettingID; $name = (Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.GUID -eq $id }).NetConnectionID; $ip = $a.IPAddress -join ','; $mask = $a.IPSubnet -join ','; $gw = $a.DefaultIPGateway -join ','; $dns = $a.DNSServerSearchOrder -join ','; Write-Host ('  发现静态IP: ' + $name + ' - ' + $ip); Set-Content -Path ([System.IO.Path]::Combine($env:TEMP, 'static_' + $id + '.txt')) -Value ($name + '|' + $ip + '|' + $mask + '|' + $gw + '|' + $dns) } } else { Write-Host '  未发现静态IP配置' }"
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

echo [阶段 5/6] 重置 DHCP...
ipconfig /release >nul 2>&1
echo  已释放，正在续约...
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
echo  建议 restart 重启电脑使更改生效
echo.

set /p restart=是否立即重启？(Y/N): 
if /i "%restart%"=="Y" (
    shutdown /r /t 5
    echo  5秒后重启...
)

pause
endlocal