@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title CellTracker v4 · Python 旧版

echo ============================================================
echo   🧬 CellTracker v4 · Python 旧版（仅用于对照）
echo ============================================================
echo.

set "PYTHON=.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [1/3] 创建 Python 虚拟环境...
    py -3 -m venv .venv 2>nul
    if not exist "%PYTHON%" python -m venv .venv 2>nul
)

if not exist "%PYTHON%" (
    echo 未创建虚拟环境，改用系统 Python。
    set "PYTHON=python"
)

"%PYTHON%" -c "import flask, openpyxl, waitress" >nul 2>nul
if errorlevel 1 (
    echo [1/3] 安装后端依赖...
    "%PYTHON%" -m pip install --upgrade pip
    "%PYTHON%" -m pip install -r backend\requirements.txt
    if errorlevel 1 (
        echo.
        echo 依赖安装失败。请确认已安装 Python 3.10+ 并且网络可用。
        pause
        exit /b 1
    )
) else (
    echo [1/3] 后端依赖已就绪。
)

if not exist "frontend\dist\index.html" (
    echo [2/3] 首次运行，构建前端页面...
    pushd frontend
    call npm install --no-audit --no-fund
    if errorlevel 1 ( popd & pause & exit /b 1 )
    call npm run build
    if errorlevel 1 ( popd & pause & exit /b 1 )
    popd
) else (
    echo [2/3] 前端页面已构建。
)

echo [3/3] 启动服务...
echo.
"%PYTHON%" -m backend.serve

echo.
echo 服务已停止。
pause
