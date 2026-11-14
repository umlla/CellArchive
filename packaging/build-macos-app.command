#!/bin/bash
# 细胞档案 CellArchive v4 · 内测版
# macOS 一键打包脚本：在 Mac 上运行，生成可双击的 .app
#
# 用法（二选一）：
#   1) 双击本文件
#   2) 终端执行：./packaging/build-macos-app.command
#
# 产物：release/CellArchive.app

cd "$(dirname "$0")/.." || exit 1

BOLD=$'\033[1m'
RED=$'\033[31m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
RESET=$'\033[0m'

fail() {
  echo
  echo "${RED}${BOLD}打包失败：${RESET}$1"
  echo
  if [ -n "$2" ]; then
    echo "$2"
    echo
  fi
  read -r -p "按回车键关闭窗口..." _
  exit 1
}

ok()   { echo "${GREEN}  ✓${RESET} $1"; }
step() { echo; echo "${BOLD}[$1/6]${RESET} $2"; }

APP_NAME="CellArchive"
VERSION="4.0.0"
BUNDLE_ID="com.celltracker.archive"

echo "============================================================"
echo "  ${BOLD}细胞档案 CellArchive v$VERSION${RESET} · macOS 打包"
echo "============================================================"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# ---------------------------------------------------------------- 1. 环境检查
step 1 "检查打包环境..."

if [ "$(uname -s)" != "Darwin" ]; then
  fail "本脚本只能在 macOS 上运行。" "（.app 必须在 Mac 上打包，Windows/Linux 无法生成）"
fi

PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      PYTHON_BIN="$candidate"
      break
    fi
  fi
done
[ -z "$PYTHON_BIN" ] && fail "没有找到 Python 3.10 或更高版本。" "请到 https://www.python.org/downloads/macos/ 安装后重试。"
ok "Python：$("$PYTHON_BIN" -V 2>&1)"

command -v npm >/dev/null 2>&1 || fail "缺少 Node.js，无法构建前端。" "请到 https://nodejs.org/zh-cn 安装 LTS 版本后重试。"
ok "Node.js：$(node -v 2>/dev/null)"

ARCH=$(uname -m)
ok "系统架构：$ARCH"

# ---------------------------------------------------------------- 2. 依赖
step 2 "准备打包用虚拟环境..."

BUILD_VENV=".venv-build"
BUILD_PY="$BUILD_VENV/bin/python"

if [ ! -x "$BUILD_PY" ]; then
  "$PYTHON_BIN" -m venv "$BUILD_VENV" || fail "无法创建虚拟环境。"
fi

"$BUILD_PY" -m pip install --upgrade pip --quiet --disable-pip-version-check 2>/dev/null
if ! "$BUILD_PY" -m pip install -r backend/requirements.txt pyinstaller --disable-pip-version-check; then
  fail "安装打包依赖失败。" "可以改用国内镜像：
  $BUILD_PY -m pip install -r backend/requirements.txt pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple"
fi
ok "依赖已就绪（含 PyInstaller）"

# ---------------------------------------------------------------- 3. 前端
step 3 "构建前端页面..."

(
  cd frontend || exit 1
  npm install --no-audit --no-fund || exit 1
  npm run build || exit 1
)
[ -f "frontend/dist/index.html" ] || fail "前端构建失败。"
ok "前端页面构建完成"

# ---------------------------------------------------------------- 4. PyInstaller
step 4 "打包 Python 程序（约 1-3 分钟）..."

WORK=".build/pyinstaller"
rm -rf "$WORK"
mkdir -p "$WORK"

# 入口脚本：启动时把资源目录设为打包内的 frontend/dist
cat > "$WORK/entry.py" <<'PYEOF'
import os
import sys
from pathlib import Path

# PyInstaller 解包后的资源根目录（onedir 时就是程序目录）
base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

from backend import create_app
from backend.config import Config
from backend import serve

# 用户数据目录：~/Library/Application Support/CellArchive
home = Path(os.environ.get("CELLARCHIVE_HOME")
            or Path.home() / "Library" / "Application Support" / "CellArchive")
home.mkdir(parents=True, exist_ok=True)

# 配置文件也放在用户目录，这样用户可以自己改端口等设置
config_file = home / "config.json"
config = Config.load(config_file) if config_file.exists() else Config.load("/nonexistent")

# 数据库、备份、前端资源一律以打包内/用户目录为准，忽略项目内的相对路径
config.db_path = home / "cell_data.db"
config.backup_dir = home / "backups"
config.frontend_dist = base / "frontend" / "dist"
config.config_path = config_file

app = create_app(config)
sys.exit(serve.run_server(app, config))
PYEOF

"$BUILD_PY" -m PyInstaller \
  --noconfirm --clean --onedir --console \
  --name "$APP_NAME" \
  --add-data "frontend/dist:frontend/dist" \
  --hidden-import "backend.services.experiments" \
  --hidden-import "backend.services.todos" \
  --hidden-import "gunicorn" \
  --collect-submodules "gunicorn" \
  --distpath "$WORK/dist" \
  --workpath "$WORK/work" \
  --specpath "$WORK" \
  "$WORK/entry.py" > "$WORK/pyinstaller.log" 2>&1 || {
    echo
    tail -n 30 "$WORK/pyinstaller.log"
    fail "PyInstaller 打包失败。" "完整日志：$WORK/pyinstaller.log"
  }
ok "Python 程序打包完成"

# ---------------------------------------------------------------- 5. 组装 .app
step 5 "组装 .app 应用包..."

APP_DIR="release/$APP_NAME.app"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

cp -R "$WORK/dist/$APP_NAME/"* "$APP_DIR/Contents/MacOS/"

cat > "$APP_DIR/Contents/Info.plist" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>细胞档案</string>
    <key>CFBundleDisplayName</key>
    <string>细胞档案</string>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>$BUNDLE_ID</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLISTEOF

chmod +x "$APP_DIR/Contents/MacOS/$APP_NAME" 2>/dev/null
ok "应用包已生成"

# ---------------------------------------------------------------- 6. 压缩
step 6 "压缩为分发文件..."

cd release || fail "无法进入 release 目录。"
rm -f "$APP_NAME-macOS-$ARCH.zip"
# 用 ditto 保留可执行权限与符号链接（zip 会破坏 .app 的权限）
if ditto -c -k --sequesterRsrc --keepParent "$APP_NAME.app" "$APP_NAME-macOS-$ARCH.zip"; then
  ok "已生成：release/$APP_NAME-macOS-$ARCH.zip"
else
  fail "压缩失败。"
fi
cd .. || exit 1

echo
echo "============================================================"
echo "${GREEN}${BOLD} 打包完成${RESET}"
echo "============================================================"
echo "  应用：release/$APP_NAME.app"
echo "  分发：release/$APP_NAME-macOS-$ARCH.zip"
echo
echo "${YELLOW}${BOLD} 重要：未签名的应用在别人电脑上会被系统拦截${RESET}"
echo "  同事第一次打开时如果提示「无法验证开发者」，请："
echo "    1. 在应用图标上 ${BOLD}右键 → 打开${RESET}"
echo "    2. 弹窗里再点 ${BOLD}打开${RESET}"
echo "  或者：系统设置 → 隐私与安全性 → 底部点「仍要打开」"
echo
echo "  数据保存在：~/Library/Application Support/CellArchive"
echo "  （双击 .app 时会自动打开浏览器，关闭浏览器标签不会退出程序，"
echo "    需要退出请按 Cmd+Q 或在 Dock 上右键退出）"
echo
read -r -p "按回车键关闭窗口..." _
