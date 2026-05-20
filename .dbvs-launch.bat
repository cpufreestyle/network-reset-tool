@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo ========================================
echo   network-reset-tool
echo   echo 未检测到已知项目类型，请手动编辑此文件
echo ========================================
echo.
echo 未检测到已知项目类型，请手动编辑此文件
if %ERRORLEVEL% neq 0 (
    echo.
    echo [X] Exit code: %ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)
echo.
echo ========================================
echo   Done
echo ========================================
pause
