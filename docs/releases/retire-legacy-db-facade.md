# 门面退役与调度器启动守卫发布说明

## 升级步骤

从 B3 之前的版本升级时，请注意以下事项：

1. **任务引用迁移移出应用**：
   应用启动时不再自动在内存中静默尝试改写旧任务引用，而是通过启动守卫 `assert_no_legacy_job_refs` 进行检查。
2. **启动守卫**：
   若数据库的 `apscheduler_jobs` 表中存在未迁移或无法解析的旧格式任务引用（如旧模块路径 `app.webapp.routers.activities.*`），应用会输出 CRITICAL 日志并以非 0 状态退出，以防止 APScheduler 启动时因无法解析模块而静默删除持久化任务记录。
3. **升级前迁移**：
   从 B3 之前版本升级到本版本时，请先在维护窗口停止调度器并执行一次迁移脚本：
   ```bash
   python -m scripts.migrate_legacy_job_refs
   ```
   迁移脚本会原子性改写所有旧任务引用为具名任务（`app.core.scheduler:run_task`）。执行完成后即可正常启动新版本应用。如果数据库尚无任务表或已迁移完成，启动守卫会自动通过，无需额外操作。

## 部署回退步骤

若需要从本版本回退到 B3 之前的镜像版本：

1. 停止所有运行中的调度器进程。
2. 运行反向恢复脚本以逐字节恢复旧版本所需的引用格式（必须显式传入 `--reverse --scheduler-stopped` 确认标志）：
   ```bash
   python -m scripts.migrate_legacy_job_refs --reverse --scheduler-stopped
   ```
3. 不启动新版本，直接回退镜像并启动旧版本服务。

## 1.0.0 实际发布记录（quince，2026-10-01）

本版本已在 quince 的 PostgreSQL 18.3 生产环境完成发布。发布前生成并校验了 PostgreSQL custom-format 备份，同时保留部署前 `data/.env` 备份；生产 compose 使用本地构建的 `pmsmanagebot:dev`，未被同步脚本覆盖。

- Alembic：`b9c0d1e2f3a4` → `b5c6d7e8f9a0`。
- `line_catalog` 首次导入完成：普通线路 7 条、高级线路 2 条；`lines/catalog_imported` marker 已写入。
- 特权码首次导入完成；`invitation/privileged_codes_imported` marker 已写入。
- 旧持久化任务引用迁移结果为 `rewritten=0`，启动 guard 通过。
- Redis 只读审计通过；旧 Redis 配置键不存在，因此未执行 `scripts/migrate_redis_to_database.py`，也未清空 DB 0、DB 2 或 DB 15。
- 最终容器包版本为 `1.0.0`，health 200，OpenAPI 200，未认证保护路由 401，重启次数 0。

`data/.env` 中已迁移到 `SystemConfig`/`line_catalog` 的业务配置已删除；`WEBAPP_SESSION_SECRET_KEY` 已迁移为持久化 `SESSION_SECRET_KEY`。任何后续从更早版本升级的部署，仍必须先按本文件的任务引用迁移步骤执行，不能仅依据本次 quince 的 `rewritten=0` 省略审计。
