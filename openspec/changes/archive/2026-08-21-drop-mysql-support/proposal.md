## Why

项目对外声称支持 MySQL——`AGENTS.md` 写「SQLite/PostgreSQL/MySQL」、`pyproject.toml` 提供 `[mysql]` extra、`config.py` 有完整的 `MYSQL_*` 配置与 URL 构建分支、`Dockerfile` 默认安装 `pymysql`。但该路径从未被测试过，项目也没有测试套件可以为其背书。

声称支持而实际未验证，比明确不支持更糟：用户按文档配了 MySQL，遇到问题时无从判断是自己配错还是项目本就跑不通；而维护者也不得不在每次涉及数据库的改动中顺带考虑一个从未运行过的目标。移除这个声明让支持范围与实际验证过的范围一致。

## What Changes

- **BREAKING**：移除 MySQL 作为受支持的数据库类型，`DATABASE_TYPE="mysql"` 不再有专门的处理分支
- 移除 `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DB` 五项配置
- 移除 `pyproject.toml` 的 `[mysql]` optional-dependency 与 `pymysql` 依赖，并同步 `uv.lock`
- `Dockerfile` 的安装命令由 `".[postgres,mysql]"` 改为 `".[postgres]"`
- 文档（`AGENTS.md`、`.env.example`）中的数据库支持范围更正为 SQLite 与 PostgreSQL

本变更是纯粹的移除，**不引入新的配置校验**。`DB_URL` 中「未识别类型回退 SQLite」的既有行为保持不动——收紧它属于另一件事，与本次「不再宣称支持」的目标无关。

### 迁移出路

`DATABASE_URL` 优先级最高且不受 `DATABASE_TYPE` 影响（`config.py:199`）。仍需连 MySQL 的用户可以直接设 `DATABASE_URL="mysql+pymysql://..."` 并自行安装 `pymysql`——**这条路径继续可用，但不受支持、不作保证**。这一点会在 `.env.example` 中写明，使「移除支持声明」与「主动阻断」区分开。

## Capabilities

### New Capabilities

- `database-configuration`: 数据库连接的配置契约——受支持的数据库类型、配置项优先级、不受支持连接方式的边界，以及依赖范围与支持声明的一致性

### Modified Capabilities

无。

## Impact

### 修改

- `src/app/config.py`：`DATABASE_TYPE` 注释、删除五项 `MYSQL_*` 配置、`DB_URL` 删除 MySQL 分支（`config.py:209`）
- `pyproject.toml`：删除 `[project.optional-dependencies]` 下的 `mysql` 组
- `uv.lock`：同步锁文件，移除 `pymysql` 条目（5 处引用）
- `Dockerfile:45`：安装 extra 由 `".[postgres,mysql]"` 改为 `".[postgres]"`
- `AGENTS.md:10`：数据库支持范围改为 SQLite/PostgreSQL；`AGENTS.md:21` 安装命令同步
- `.env.example`：删除 MySQL 配置段、更正 `DATABASE_TYPE` 注释、补充 `DATABASE_URL` 可用于不受支持数据库的说明

### 不受影响

- 前端与管理接口：`DATABASE_TYPE` / `DATABASE_URL` 从未通过 API 暴露，`Management.vue` 中的 `mdi-database` 图标与数据库配置无关
- `alembic/env.py`：通过 `settings.DB_URL` 取连接串（`alembic/env.py:15`），无需改动
- `deploy.sh` / `start.sh` / `docker-compose.yaml`：不含数据库类型相关内容
- `DB_CONNECT_ARGS`（`config.py:220`）：仅对 sqlite 特判，其余返回空字典，逻辑无需调整
- `DB_URL` 的 `else` 回退分支：保持原样

### 风险

- 现有若配了 `DATABASE_TYPE="mysql"` 的部署，升级后会按既有回退行为连上 SQLite。本变更不为此增加校验，但 `.env.example` 中会给出 `DATABASE_URL` 的迁移写法。考虑到该路径从未被测试、实际存在此类部署的可能性极低，不为其增加代码复杂度
