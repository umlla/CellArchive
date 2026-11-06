#!/bin/bash
cd "$(dirname "$0")" || exit 1

if command -v go >/dev/null 2>&1; then
    exec go run ./cmd/celltracker
fi

echo "未找到 Go。请安装 Go 1.26+ 后重试。"
read -n 1 -s -r -p "按任意键退出..."
