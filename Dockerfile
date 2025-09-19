# 编译前端资源
FROM node:18-alpine AS frontend-builder

WORKDIR /app/webapp-frontend

# 复制前端项目文件
COPY webapp-frontend/package*.json ./

# 安装依赖 (只安装生产依赖)
RUN npm install

# 复制源代码并构建
COPY webapp-frontend/ ./
RUN npm run build && \
    # 清理 node_modules 减少层大小
    rm -rf node_modules

# Python 依赖构建
FROM python:3.11-slim AS deps-builder

# 设置环境变量优化 pip
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100

# 安装编译依赖和构建工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir hatchling

WORKDIR /app

# 复制依赖文件
COPY pyproject.toml ./
COPY README.md ./
# 复制源码目录
COPY src/ ./src/

# 安装 Python 依赖到根目录
RUN pip install --no-warn-script-location .

# 最终运行镜像
FROM python:3.11-slim AS runtime

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app/src"

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 从依赖构建层复制 Python 包
COPY --from=deps-builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps-builder /usr/local/bin /usr/local/bin

# 从前端构建层复制编译后的静态文件
COPY --from=frontend-builder /app/webapp-frontend/dist ./webapp-frontend/dist

# 复制应用程序源代码
COPY src/ ./src/
COPY scripts ./scripts

# 复制启动脚本
COPY start.sh ./start.sh
RUN chmod +x ./start.sh

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 6000

# 启动命令
CMD ["./start.sh"]
