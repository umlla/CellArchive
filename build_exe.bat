@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo  CellTracker - build Windows application
echo ============================================================

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run start.bat once, or create a virtual environment first.
    pause
    exit /b 1
)

if not exist "frontend\dist\index.html" (
    echo [1/3] Building frontend...
    pushd frontend
    if not exist "node_modules" call npm install
    call npm run build
    if errorlevel 1 (
        popd
        echo [ERROR] Frontend build failed.
        pause
        exit /b 1
    )
    popd
) else (
    echo [1/3] Frontend build found: frontend\dist
)

echo [2/3] Checking PyInstaller...
".venv\Scripts\python.exe" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo       Installing PyInstaller...
    ".venv\Scripts\python.exe" -m ensurepip --upgrade >nul 2>nul
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller.
        pause
        exit /b 1
    )
)

rem 重新打包会覆盖 dist\CellTracker，先保留现有数据和配置
if exist "dist\CellTracker\data" (
    echo       Backing up data folder...
    if exist "dist\_keep_data" rmdir /s /q "dist\_keep_data"
    xcopy "dist\CellTracker\data" "dist\_keep_data" /E /I /Y >nul
)
if exist "dist\CellTracker\config.json" copy /Y "dist\CellTracker\config.json" "dist\_keep_config.json" >nul

echo [3/3] Packaging...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean CellTracker.spec
if errorlevel 1 (
    echo [ERROR] Packaging failed.
    pause
    exit /b 1
)

if exist "dist\_keep_data" (
    if exist "dist\CellTracker\data" rmdir /s /q "dist\CellTracker\data"
    move "dist\_keep_data" "dist\CellTracker\data" >nul
)
if exist "dist\_keep_config.json" (
    copy /Y "dist\_keep_config.json" "dist\CellTracker\config.json" >nul
    del "dist\_keep_config.json"
) else (
    copy /Y "config.example.json" "dist\CellTracker\config.json" >nul
)
copy /Y "packaging\使用说明.txt" "dist\CellTracker\使用说明.txt" >nul
copy /Y "packaging\launch.ps1" "dist\CellTracker\launch.ps1" >nul
copy /Y "packaging\start-celltracker.bat" "dist\CellTracker\start-celltracker.bat" >nul
copy /Y "packaging\启动 CellTracker.bat" "dist\CellTracker\启动 CellTracker.bat" >nul

echo.
echo Done: dist\CellTracker\CellTracker.exe
echo.
pause
