#!/bin/bash
set -euo pipefail

# 默认执行构建
BUILD_FRONTEND=true

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-build|--no-build)
            BUILD_FRONTEND=false
            echo -e "⚠️  跳过前端构建"
            shift
            ;;
        -h|--help)
            echo "用法: $0 [选项]"
            echo "选项:"
            echo "  --skip-build, --no-build    跳过前端代码构建"
            echo "  -h, --help                  显示此帮助信息"
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            echo "使用 -h 或 --help 查看帮助"
            exit 1
            ;;
    esac
done

# 前端构建
if [ "$BUILD_FRONTEND" = true ]; then
    echo -e "▶️ 前端代码编译"
    cd webapp-frontend && npm run build
    echo -e "✌️ 前端代码编译成功"
else
    echo -e "⏭️  跳过前端代码编译"
fi

echo -e "▶️ 开始同步修改到服务器"
rsync -avP --partial --timeout=120 --delete \
    -e 'ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=20' \
    --include "webapp-frontend/.eslintrc.js" \
    --include ".dockerignore" \
    --exclude ".*" \
    --exclude "__pycache__" \
    --exclude "docker-compose.*" \
    --exclude "data" \
    --exclude "webapp-frontend/dist" \
    --exclude "webapp-frontend/node_modules" \
    ~/Documents/Projects/PMSManageBot/ quince:/opt/PMSManageBot/
echo -e "✌️ 同步到服务器成功"
