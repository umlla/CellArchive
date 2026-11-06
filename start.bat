@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title CellTracker v4 · 细胞培养追踪

echo ============================================================
echo   🧬 CellTracker v4 · 细胞培养追踪系统
echo ============================================================
echo.

if exist "CellTracker.exe" (
    echo 启动 CellTracker.exe ...
    "CellTracker.exe"
    exit /b %errorlevel%
)

where go >nul 2>nul
if errorlevel 1 (
    echo 未找到 CellTracker.exe，也没有安装 Go。
    echo.
    echo 普通用户请解压发布包，直接双击 CellTracker.exe。
    echo 开发者请安装 Go 1.26+ 后重新运行本脚本。
    pause
    exit /b 1
)

echo 未找到已编译程序，使用 Go 直接运行（首次会编译，稍等）...
echo.
go run ./cmd/celltracker
echo.
echo 服务已停止。
pause
