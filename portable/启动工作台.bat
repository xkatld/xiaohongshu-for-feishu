@echo off
chcp 65001 >nul
title 小红书笔记统计台
cd /d "%~dp0"

if not exist "python\python.exe" (
    echo.
    echo [错误] 未找到 python\python.exe
    echo 请确认压缩包已完整解压（不要直接在压缩包里运行）。
    echo.
    pause
    exit /b 1
)

if not exist "app\xhs_server.py" (
    echo.
    echo [错误] 未找到 app\xhs_server.py，文件可能不完整。
    echo.
    pause
    exit /b 1
)

echo.
echo   ============================================
echo      小红书笔记统计台  正在启动...
echo   ============================================
echo.
echo   浏览器会自动打开，若未打开请手动访问下面地址。
echo   使用过程中请保持本窗口开启；关闭本窗口即停止服务。
echo.

"python\python.exe" "app\xhs_server.py"

echo.
echo   服务已停止，可以关闭本窗口。
pause
