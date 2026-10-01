# Tasks

## 1. 前置核对

- [x] 1.1 编写并运行盘点脚本，确认三点：`baseline.json` 中除 `line_budgets` 外的类别都为空；import-linter 中只剩门面组合边的忽略项；`src` 中只有 `app/databases` 自身导入 `app.databases`（用 AST 和 grimp 核对）。把结果记录进本变更。验证：三项检查都通过；如果不通过，列出遗留项及其负责变更，停止实施。

## 2. 删除门面与收敛检查

- [x] 2.1 删除 `app/databases/`，包括两个兼容层；改写 import-linter 配置：删除门面冻结合约；删除 SQLAlchemy、引擎合约中的过时放行项；删除外部隔离、入口合约中的过时禁止项；顶层合约改为 `(app.domains)`；删除全部组合边忽略项；六层合约改为 `exhaustive = true`。验证：`PYTHONPATH=src .venv/bin/lint-imports --no-cache` 通过；新增的测试断言所有合约都没有 `ignore_imports`；一个探针领域如果没有在合约中定层，检查会失败。
- [x] 2.2 按 design D3 收敛架构测试：删除门面和 mixin 的扫描，以及 `facade_call`、`self_call`、`mixin_duplicates` 三个类别；`baseline.json` 只保留 `line_budgets`；删除 `test_b2_provenance.py`；改写 `test_scheduler_jobstore_boundary.py`；把积分写入检查改为常驻测试。验证：`pytest tests/architecture` 通过；每个保留的检查都有负向探针用例证明它仍然有效，包括跨域导入、行数预算、模型注册、序号模块、换绑覆盖、读模型只读、配置跨域只读和积分绝对值写入。
- [x] 2.3 删除 `tests/conftest.py` 中的 `DatabaseORM` 和 `orm` 夹具，以及所有测试中对门面的导入和 patch。验证：`grep` 确认 `tests` 中没有 `app.databases` 和 `DatabaseORM`；全量测试通过。

## 3. 任务引用迁移移出应用

- [x] 3.1 新增独立脚本 `scripts/migrate_legacy_job_refs.py`：原样迁入正向和反向改写逻辑，不导入 `app`，保留 `--reverse --scheduler-stopped` 的确认。然后删除 `LEGACY_TASK_REFS`、`migrate_persisted_jobs`、`core/scheduler.py` 中的改写助手和过渡开关、`core/db.py` 中的 `rewrite_scheduler_rows`，以及 `core.scheduler` 对 `core.db` 的例外放行。验证：原 `test_job_references.py` 的场景改为针对脚本运行，全部通过，包括逐字节反向恢复和缺少停止确认时拒绝；`app` 中不再出现 `LEGACY_TASK_REFS`。
- [x] 3.2 新增启动守卫 `assert_no_legacy_job_refs`，在 `scheduler.start()` 之前运行；在 `docs/architecture.md` 的部署回退一节和发布说明中写明升级步骤。验证：
  - 在一次性环境中预置两条旧格式记录后启动，进程以非 0 状态退出，日志给出脚本的用法，记录不被改动。
  - 运行脚本后启动正常，任务按原定时间触发。
  - 表不存在时正常启动。

## 4. 工具、测试与脚本精简

- [x] 4.1 把 `snapshot.py` 和 `check_metadata_pg.py` 移到 `scripts/verify/`，去掉门面方法清单、BASE 回退和字符串引用解析；删除 `main.py` 中的兼容垫片；更新对应的测试。验证：连续生成两次快照，输出逐字节一致；与改动前的快照相比，只少了被删除的那几项。
- [x] 4.2 删除 `scripts/refactor/` 中其余的脚本和数据文件，以及 21 点试点的冻结夹具和测试；把 `tests/refactor/` 中测试生产代码的 5 个文件移到 `tests/`，然后删除 `tests/refactor/`。验证：全量测试通过；`scripts/refactor/` 和 `tests/refactor/` 都不存在；`pre-commit run --all-files` 通过，而且不再创建 git worktree。
- [x] 4.3 对 `migrate_redis_to_database.py` 和 `migrate_line_traffic_stats.py`，核对手动运维清单并请维护者逐个确认：保留的改用领域 API，并登记进清单；不需要的删除。验证：确认结论记录在本变更中；`scripts` 中不再导入 `app.databases`。

## 5. 文档与集成验证

- [x] 5.1 按 design D7 更新 AGENTS.md 和 `docs/architecture.md`。验证：两份文档中都不再出现 `app.databases`、`DatabaseORM`、`db_func`、`app.log`、`app/config.py`、`app/models/models.py` 和"过渡"字样的规则；文中的命令都能按原样执行。
- [x] 5.2 在干净环境中运行全部校验：新的 worktree，editable 安装，没有 `__pycache__`。校验项包括 `pytest tests/`、`ruff check`、`ruff format --check`、`lint-imports`、`pre-commit run --all-files` 和 `scripts/verify/check_metadata_pg.py`；并新增测试，断言导入 `app.databases`、`app.webapp`、`app.models` 会抛出 `ModuleNotFoundError`。验证：全部通过；元数据没有差异。证据：detached clean worktree（共享 editable `.venv` symlink）中 `1006 passed, 5 skipped`，11 个 import-linter 合约、Ruff、pre-commit 和工具 CLI 均通过。
- [x] 5.3 运行 `openspec validate retire-legacy-db-facade --strict`。验证：校验通过；工作区干净。
