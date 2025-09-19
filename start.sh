#!/bin/bash

# 设置默认值
WEBAPP_URL=${WEBAPP_URL:-"http://localhost:6000"}

# 替换前端构建文件中的 API URL
if [ -d "/app/webapp-frontend/dist" ]; then
    echo "正在更新前端 API URL 为: $WEBAPP_URL"
        
    # 如果有其他可能的默认值，也替换
    find /app/webapp-frontend/dist -name "*.js" -exec sed -i "s|http://localhost:6000|$WEBAPP_URL|g" {} +
    
    echo "前端配置更新完成"
fi

# 启动 Python 应用
echo "启动应用..."
exec python3 -m app.main
