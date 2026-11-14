#!/bin/bash
# 细胞档案 CellArchive v4 · 细胞培养与实验管理
# macOS 一键启动脚本：双击即可运行。
# 首次运行会自动准备 Python 环境并安装依赖，需要联网，约 2-5 分钟。

cd "$(dirname "$0")" || exit 1

BOLD=$'\033[1m'
RED=$'\033[31m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
RESET=$'\033[0m'

# 出错时停住，让双击打开的用户能看清提示（窗口关掉就看不到原因了）
fail() {
  echo
  echo "${RED}${BOLD}启动失败：${RESET}$1"
  echo
  if [ -n "$2" ]; then
    echo "$2"
    echo
  fi
  echo "你可以把上面的内容截图发给管理员。"
  echo
  read -r -p "按回车键关闭窗口..." _
  exit 1
}

ok()   { echo "${GREEN}  ✓${RESET} $1"; }
step() { echo "${BOLD}[$1/4]${RESET} $2"; }

echo "============================================================"
echo "  ${BOLD}细胞档案 CellArchive v4${RESET} · 细胞培养与实验管理"
echo "============================================================"
echo

# ---------------------------------------------------------------- 1. 环境检查
step 1 "检查运行环境..."

# 双击 .command 时，系统默认用 /bin/bash，PATH 可能缺少 Homebrew 的目录
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    # 必须是 3.10 及以上
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      PYTHON_BIN="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  fail "没有找到 Python 3.10 或更高版本。" \
"请先安装 Python：
  1. 打开 https://www.python.org/downloads/macos/
  2. 下载并安装最新的 macOS 安装包（Python 3.12 或更高）
  3. 安装完成后，重新双击本文件"
fi
ok "Python：$("$PYTHON_BIN" -V 2>&1)"

# ---------------------------------------------------------------- 2. 后端依赖
step 2 "准备 Python 环境..."

VENV_PY=".venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
  echo "  首次运行，正在创建虚拟环境..."
  # 如果 .venv 是 Windows 版残留（从 Windows 拷过来的），先清掉
  if [ -d ".venv" ] && [ ! -d ".venv/bin" ]; then
    echo "  检测到 Windows 版的 .venv，正在重建..."
    rm -rf .venv
  fi
  "$PYTHON_BIN" -m venv .venv 2>/dev/null
fi

if [ ! -x "$VENV_PY" ]; then
  # 某些系统缺少 venv 模块时，退回使用系统 Python
  echo "  ${YELLOW}无法创建虚拟环境，改用系统 Python（可能需要在系统范围内安装依赖）${RESET}"
  VENV_PY="$PYTHON_BIN"
fi

if ! "$VENV_PY" -c 'import flask, openpyxl' >/dev/null 2>&1; then
  echo "  正在安装依赖（需要联网，约 1-3 分钟）..."
  "$VENV_PY" -m pip install --upgrade pip --quiet --disable-pip-version-check 2>/dev/null
  if ! "$VENV_PY" -m pip install -r backend/requirements.txt --disable-pip-version-check; then
    fail "依赖安装失败（通常是网络问题）。" \
"可以尝试：
  - 检查网络是否可用
  - 使用国内镜像：
    .venv/bin/python -m pip install -r backend/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"
  fi
fi
ok "依赖已就绪"

# ---------------------------------------------------------------- 3. 前端页面
step 3 "检查前端页面..."

if [ -f "frontend/dist/index.html" ]; then
  ok "前端页面已就绪"
else
  echo "  首次运行，正在构建前端页面（需要联网，约 2-5 分钟）..."
  if ! command -v npm >/dev/null 2>&1; then
    fail "缺少 Node.js，无法构建前端页面。" \
"请先安装 Node.js：
  1. 打开 https://nodejs.org/zh-cn 下载 LTS 版本并安装
  2. 安装完成后，重新双击本文件"
  fi
  (
    cd frontend || exit 1
    npm install --no-audit --no-fund && npm run build
  )
  if [ ! -f "frontend/dist/index.html" ]; then
    fail "前端构建失败。" "请在网络正常的情况下重试，或把 Windows 版里的 frontend/dist 目录整个复制过来。"
  fi
  ok "前端页面构建完成"
fi

# ---------------------------------------------------------------- 4. 启动
step 4 "启动服务..."
echo
echo "  启动后请按提示在浏览器里手动打开地址。"
echo "  使用期间请保持这个窗口开着；关掉窗口就是退出程序。"
echo "  按 ${BOLD}Ctrl+C${RESET} 也可以停止服务。"
echo

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

"$VENV_PY" -m backend.serve
EXIT_CODE=$?

echo
if [ $EXIT_CODE -ne 0 ]; then
  echo "${YELLOW}服务已退出（代码 $EXIT_CODE）。${RESET}"
  echo "如果是端口被占用，请修改 config.json 里的 port 后重新运行。"
else
  echo "服务已停止。"
fi
read -r -p "按回车键关闭窗口..." _
