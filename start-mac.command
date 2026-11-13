#!/bin/bash
# CellTracker 启动脚本（macOS / Linux）
# 双击或在终端执行：./start-mac.command

cd "$(dirname "$0")" || exit 1

echo "============================================================"
echo " 🧬 CellTracker v4 · 细胞培养追踪系统"
echo "============================================================"
echo ""

PYTHON_BIN=""

# 找一个可用的 python3
for candidate in python3 python3.12 python3.11 python3.10 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "未找到 Python 3.10 或更高版本。"
    echo ""
    echo "请先安装 Python："
    echo "  macOS：打开 https://www.python.org/downloads/ 下载安装，"
    echo "         或在终端执行：brew install python"
    echo "  Linux：sudo apt install python3 python3-venv"
    echo ""
    read -n 1 -s -r -p "按任意键退出..."
    exit 1
fi

echo "[1/3] Python：$("$PYTHON_BIN" --version 2>&1)"

# 虚拟环境：不存在就创建
if [ ! -x ".venv/bin/python" ]; then
    echo "[1/3] 首次运行，创建虚拟环境..."
    if ! "$PYTHON_BIN" -m venv .venv; then
        echo ""
        echo "创建虚拟环境失败。Linux 上可能需要先安装："
        echo "  sudo apt install python3-venv"
        echo ""
        read -n 1 -s -r -p "按任意键退出..."
        exit 1
    fi
fi

VENV_PY=".venv/bin/python"

# 依赖检查
if ! "$VENV_PY" -c "import flask, openpyxl, waitress" >/dev/null 2>&1; then
    echo "[1/3] 安装后端依赖（首次需要联网，稍等）..."
    "$VENV_PY" -m pip install --upgrade pip >/dev/null 2>&1
    if ! "$VENV_PY" -m pip install -r backend/requirements.txt; then
        echo ""
        echo "依赖安装失败。请确认网络可用后重试。"
        echo "也可以手动执行：$VENV_PY -m pip install -r backend/requirements.txt"
        echo ""
        read -n 1 -s -r -p "按任意键退出..."
        exit 1
    fi
else
    echo "[1/3] 后端依赖已就绪。"
fi

# 前端页面：没有构建产物就构建
if [ ! -f "frontend/dist/index.html" ]; then
    if command -v npm >/dev/null 2>&1; then
        echo "[2/3] 首次运行，构建前端页面（需要几分钟）..."
        pushd frontend >/dev/null || exit 1
        if ! npm install --no-audit --no-fund; then
            popd >/dev/null
            echo "前端依赖安装失败，请检查网络后重试。"
            read -n 1 -s -r -p "按任意键退出..."
            exit 1
        fi
        if ! npm run build; then
            popd >/dev/null
            echo "前端构建失败。"
            read -n 1 -s -r -p "按任意键退出..."
            exit 1
        fi
        popd >/dev/null
    else
        echo "[2/3] 未找到 Node.js / npm，无法构建前端页面。"
        echo ""
        echo "请先安装 Node.js 18+（https://nodejs.org/），然后重新运行本脚本。"
        echo ""
        read -n 1 -s -r -p "按任意键退出..."
        exit 1
    fi
else
    echo "[2/3] 前端页面已构建。"
fi

echo "[3/3] 启动服务..."
echo ""
exec "$VENV_PY" -m backend.serve
