## 1. 配置与代码

- [x] 1.1 在 `src/app/config.py` 中：删除 `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DB` 五项配置及其「MySQL 配置」注释块
- [x] 1.2 修正 `DATABASE_TYPE` 字段注释：`# 数据库类型: sqlite, postgresql`（`config.py:129`）
- [x] 1.3 删除 `DB_URL` 属性中的 MySQL 分支（`config.py:209` 起的 `elif db_type == "mysql"` 整段）；`else` 回退 SQLite 分支保持原样，不新增校验

## 2. 依赖

- [x] 2.1 从 `pyproject.toml` 删除 `[project.optional-dependencies]` 下的 `mysql` 组
- [x] 2.2 同步 `uv.lock`（`uv lock` 或等价方式），确认 `pymysql` 相关条目（共 5 处引用）全部移除
- [x] 2.3 `Dockerfile:45` 安装命令由 `".[postgres,mysql]"` 改为 `".[postgres]"`

## 3. 文档

- [x] 3.1 `AGENTS.md:10` 数据库支持范围改为 SQLite/PostgreSQL；`AGENTS.md:21` 安装命令同步为 `.[postgres]`
- [x] 3.2 `.env.example`：删除 MySQL 配置段；`DATABASE_TYPE` 注释更正；在 `DATABASE_URL` 处补一行注释说明：可借此连接不受支持的数据库（如 `mysql+pymysql://`），但需自行安装驱动且不受项目保证

## 4. 验证

- [x] 4.1 `DATABASE_TYPE="sqlite"`（默认）与 `DATABASE_TYPE=""` 启动正常
- [x] 4.2 `DATABASE_TYPE="postgresql"` 的 URL 构建与改动前一致
- [x] 4.3 确认 `DATABASE_URL` 直接设置时正常连接（不受类型配置影响）
- [x] 4.4 `uv pip install ".[postgres]"` 安装成功；`ruff check src/` 通过
- [x] 4.5 全仓 grep 确认不再有 `mysql` / `pymysql` 残留（`uv.lock`、`pyproject.toml`、`config.py`、`Dockerfile`、文档）

## 设计说明

本变更未创建 design.md：不满足该文书的触发条件（无跨模块架构变化、无新依赖、无数据模型或安全/性能/迁移复杂度、无需要预先裁定的技术取舍）。唯一的取舍（不新增未识别类型校验、保持回退 SQLite 的既有行为）已记录于 proposal.md 的 What Changes 与风险节，不构成独立的实现决策。
