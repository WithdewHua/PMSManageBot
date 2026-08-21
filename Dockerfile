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

# 设置环境变量
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# 安装编译依赖和 uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 复制依赖文件
COPY pyproject.toml ./
COPY README.md ./
# 复制源码目录
COPY src/ ./src/

# 使用 uv 安装依赖（包括所有可选依赖）
RUN uv pip install --system --no-cache ".[postgres]"

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

# 复制 Alembic 配置和迁移文件
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/

# 复制启动脚本
COPY start.sh ./start.sh
RUN chmod +x ./start.sh

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 6000

# 启动命令
CMD ["./start.sh"]
