#!/bin/bash
cd "$(dirname "$0")" || exit 1

if [ -x "release/CellTracker-macos/CellTracker.app/Contents/MacOS/CellTracker" ]; then
    exec "release/CellTracker-macos/CellTracker.app/Contents/MacOS/CellTracker"
fi

if command -v go >/dev/null 2>&1; then
    exec go run ./cmd/celltracker
fi

echo "未找到 CellTracker.app，也没有安装 Go。"
echo "请解压 macOS 发布包，或安装 Go 1.26+ 后重试。"
read -n 1 -s -r -p "按任意键退出..."
