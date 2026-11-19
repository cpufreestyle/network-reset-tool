<#
.SYNOPSIS
    从源码部署网络工具箱：建虚拟环境、跑自检、PyInstaller 打包、装到 %LOCALAPPDATA% 并建桌面快捷方式。
.EXAMPLE
    pwsh ./deploy.ps1
    pwsh ./deploy.ps1 -SkipTests -Clean
    pwsh ./deploy.ps1 -NoDesktop
#>
param(
    [switch]$SkipTests,
    [switch]$Clean,
    [switch]$NoDesktop
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$venv = Join-Path $PSScriptRoot '.venv'
$python = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host '[1/4] 创建虚拟环境 .venv'
    python -m venv $venv
}

Write-Host '[2/5] 安装 PyInstaller'
& $python -m pip install --disable-pip-version-check -q pyinstaller

if (-not $SkipTests) {
    Write-Host '[3/5] 冒烟自检'
    & $python tests\smoke_test.py
    if ($LASTEXITCODE -ne 0) { throw '冒烟自检失败，已中止打包。' }
}
else {
    Write-Host '[3/5] 跳过自检 (-SkipTests)'
}

$buildArgs = @('网络工具箱-admin.spec', '--noconfirm')
if ($Clean) { $buildArgs += '--clean' }
Write-Host '[4/5] PyInstaller 打包(需管理员清单)'
& $python -m PyInstaller @buildArgs
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 打包失败。' }

$exe = Join-Path $PSScriptRoot 'dist\网络工具箱.exe'
if (-not [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($exe)).Contains('requireAdministrator')) {
    throw '打包结果缺少 requireAdministrator 清单，请检查 网络工具箱-admin.spec。'
}

if (-not $NoDesktop) {
    Write-Host '[5/5] 安装到 %LOCALAPPDATA%\NetworkToolbox 并创建桌面快捷方式'
    $installDir = Join-Path $env:LOCALAPPDATA 'NetworkToolbox'
    New-Item -ItemType Directory -Force -Path $installDir | Out-Null
    $installed = Join-Path $installDir 'NetworkToolbox.exe'
    Copy-Item -LiteralPath $exe -Destination $installed -Force
    & $python update_shortcut.py --exe $installed --name '网络工具箱.lnk'
    if ($LASTEXITCODE -ne 0) { throw '创建桌面快捷方式失败。' }
}
else {
    Write-Host '[5/5] 跳过安装与快捷方式 (-NoDesktop)'
}

$hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash
Write-Host ''
Write-Host "完成: $exe"
Write-Host "大小: $([math]::Round((Get-Item -LiteralPath $exe).Length / 1MB, 2)) MB"
Write-Host "SHA256: $hash"
Write-Host '启动: 双击桌面「网络工具箱」（会自动请求管理员权限）'
