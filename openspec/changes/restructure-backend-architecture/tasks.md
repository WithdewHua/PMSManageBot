# Tasks

## 1. 架构章程（A 阶段）

- [x] 1.1 新建 `docs/architecture.md`。内容按 design D1–D3、D9、D13 编写：分层图、角色文件表、领域表（含六层归属）、宽表列归属表、例外清单、手动运维操作清单（目前只有 TG 换绑，写明调用方式）、配置分类、后续变更与领域的对应表，另留一节"基线计数"待 B3 填写。验证：D2 表中的每个领域在文档里恰好出现一次，并且都有层级和职责说明。
- [x] 1.2 重写 AGENTS.md 的架构部分：
  - 写入调用方向、SQLAlchemy 只在 repository、`*_tx`、提交后副作用、积分只用增量、不再往宽表加列、跨层按模块导入、下层通知上层用领域事件这几条规则。
  - 加一张"新代码放哪"清单，写明过渡期规则（D13）。清单里写明：需要协调多个领域的操作放在 T4 领域，不另设应用层。
  - 写明：没有调用方的函数不一定是死代码，删除前先查手动运维清单，并和维护者确认。
  - 在命令部分补上 `lint-imports` 和 `pytest tests/architecture`。
  - 删除"业务逻辑放 db.py 或 modules""所有数据库操作都在 DatabaseORM"等旧约定，并链接到 `docs/architecture.md`。

  验证：`grep` 找不到旧约定的原文，链接能打开。
- [x] 1.3 在 `pyproject.toml` 的 test extra 里加入 `import-linter`，并加入 `[tool.importlinter]` 根配置（`root_packages = ["app"]`、`include_external_packages = true`）。再加上顶层分层合约，各层都标为可选，这样在包出现之前不会报错。验证：`uv pip install ".[test]"` 成功，`.venv/bin/lint-imports` 在当前代码上通过。
- [x] 1.4 新建 `tests/architecture/`：
  - AST 扫描辅助函数和 `baseline.json` 的读写。
  - 四项检查：跨领域调用面、单文件行数预算（1,000 行）、模型注册完整、mixin 不重名，再加一项基线只减不增的检查。
  - 现存的超预算文件以当前行数写入基线，包括 `db.py`、`db_func.py`、`user.py`、`admin.py`、`models.py`、`blackjack_tournament.py`。

  验证：`pytest tests/architecture` 在当前代码上通过；把 `db.py` 加长一行后，行数预算检查失败。
- [x] 1.5 在 `.pre-commit-config.yaml` 里加两个本地 hook（`language: system`，使用项目虚拟环境）：`lint-imports` 和 `pytest tests/architecture -q`。验证：`pre-commit run --all-files` 通过。

## 2. 搬迁与校验工具

- [x] 2.1 编写 `scripts/refactor/inventory.py`：列出源模块中的每个顶层函数、类、类方法、类属性和模块级赋值，以及模块文档字符串、顶层可执行语句、导入语句和 `__init__.py` 的导出声明；记录源位置（包括装饰器和前导注释）、父子范围关系和规范化后的 AST；另外提供 `--coverage mapping.toml`，报告没有映射的项。验证：在当前代码上列出 `DatabaseORM` 的全部 314 个方法，且 `log.py` 的顶层 `while`、`databases/cache.py` 的顶层 `try`、仅含导入的包入口均有稳定记录；同一份代码连续运行两次，输出一致。
- [x] 2.2 编写 `scripts/refactor/seed_mapping.py`：根据命名规则、db.py 的分节注释和路由路径，生成 `scripts/refactor/mapping.toml` 初稿；为新增的顶层语句、文档字符串和包导入/导出明确记录目标或 `TODO`，为父类拆分标记组装而不重复复制整类，无法判断的项标为 `TODO`。验证：重新生成映射后覆盖检查中每一项要么有目标要么是 `TODO`；`log.py`、`cache.py` 和仅含导入的包入口没有漏项，已人工审阅的目标不会被重生成操作静默覆盖。
- [x] 2.3 编写 `scripts/refactor/relocate.py`：
  - 按源码行切片，连同装饰器和前导注释一起搬；顶层可执行语句、模块文档字符串和包导入/导出不得遗漏或重复，父类整体搬运与拆成员的组装动作互斥。
  - 按用到的名字生成导入，保留影响执行的导入顺序和副作用；遇到同一赋值语句跨不同目标、未审阅 `TODO`、无理由删除或不能解析的依赖时拒绝。
  - 改写 `src`、`tests`、`scripts`、`alembic` 里的顶层及函数内导入和经确认的字符串引用，包括 monkeypatch 目标、uvicorn 目标和持久化任务路径；普通非路径字符串保持原样。
  - 把 `import *` 改成显式导入，把 `DatabaseORM.<name>` 改成所在 mixin 的类名。
  - 在写入任何文件前预检：拆开了 `global` 重绑定的名字、父子范围重复搬运、未覆盖语句、歧义引用或拆分后出现导入环时拒绝执行；失败后源文件及目标文件不变。

  验证：`tests/refactor/` 用一个小型样例包覆盖每种改写和拒绝情况（包括 `log.py` 风格的 `while`、`cache.py` 风格的 `try` 和只有导入导出的 `__init__.py`），`pytest tests/refactor` 通过。
- [x] 2.4 编写 `scripts/refactor/snapshot.py`，输出 JSON 快照：
  - OpenAPI 文档和有序路由表。
  - 模型元数据的结构化导出：表、列、类型、默认值、索引、约束。
  - 调度任务：用记录用的假调度器拿到，`next_run_time` 换算成相对偏移。
  - Bot 的 handler 顺序和命令菜单。
  - 门面 `db` 上的公开方法清单。
  - 全部函数内导入和字符串引用的解析结果。

  验证：同一份代码连续运行两次，输出逐字节一致。
- [x] 2.5 编写 `scripts/refactor/verify.py --base <ref>`：
  - 在临时 worktree 里对基准提交生成快照，与当前工作树逐项比对。
  - 对清单中的每一项做 AST 比对，只放行 design D11 列出的三类改写。
  - 检查路由换序时路径是否重叠：路径参数视为通配段，只允许不重叠的路由换序。

  验证：在未改动的代码上报告零差异；在样例中分别制造一种差异（改函数体、换序后路由重叠、少一张表、少一个任务），每种都能报出。
- [x] 2.6 编写 `scripts/refactor/check_metadata_pg.py`：在一次性 PostgreSQL 上，用基准的 metadata 执行 `create_all`，再用 alembic 的 `compare_metadata` 对比当前 metadata。验证：在未改动的代码上差异为空。

## 3. B1 数据层

- [ ] 3.1 冻结后端功能开发，把基准提交记录到 `scripts/refactor/BASE`。验证：`git status` 干净，`BASE` 指向当前主干。
- [ ] 3.2 审阅 core 和 integrations 的映射（design D9）：
  - `config`、`log`、`scheduler`、`session` 加 `Base` → `core/db.py`，`redis`、`cache`、`utils` 的通用部分、`number`、`system` 也进入 `core/`。
  - `SystemConfig` 模型及其读写方法 → `core/kv.py`，读写方法组成 `SystemConfigRepository` mixin。
  - `modules/` 下的外部客户端、`tautulli_history`、`get_user_total_duration` → `integrations/`。

  验证：覆盖检查中，这些来源没有 `TODO`。
- [ ] 3.3 审阅 31 个模型的映射，按 design D2/D3 放进各领域的 `models.py`。验证：每个模型都有归属，并与 `docs/architecture.md` 的领域表一致。
- [ ] 3.4 审阅 `DatabaseORM` 全部成员和 db.py 模块级内容的映射：
  - 21 点和礼包的 repository 按 db.py 现有分节拆成包。
  - 读模型专用的查询归读模型领域，比如各个 `get_*_rank`。
  - 转盘免费次数的消耗、释放和汇总归 `luckywheel`。
  - `_CurWrapper`/`cur` 标为删除，并写明原因。
  - `rebind_user_tg_id` 映射到 `domains/tg_rebind/repository.py`。

  验证：覆盖检查通过，没有未映射的成员。
- [ ] 3.5 把 `blackjack_engine.py` 映射为 `domains/blackjack/rules.py`。验证：覆盖检查通过。
- [ ] 3.6 编写过渡门面 `app/databases/db.py`：组合全部 mixin，只导出 `db` 和 `DatabaseORM`。编写 `app/model_registry.py`：逐个显式导入 models 模块，提供 `metadata` 和 `init_db()`。把 `alembic/env.py`、`main.py`、`scripts/migrate_database.py`、`tests/conftest.py` 改为使用 `model_registry`。验证：元数据快照与基准一致。
- [ ] 3.7 运行 B1 搬迁并完成校验：`verify.py --base` 零差异，`check_metadata_pg.py` 差异为空，`pytest`、`ruff check src/`、`ruff format --check src/` 全部通过。
- [ ] 3.8 加入此时已经能检查的合约：SQLAlchemy 使用范围、外部客户端隔离、领域分层、领域无环、门面冻结，其中领域分层要忽略门面指向各 repository 的边。然后生成各合约的 `ignore_imports` 和 `baseline.json`，每条都标上负责的变更。验证：`lint-imports` 和 `pytest tests/architecture` 通过。
- [ ] 3.9 冒烟检查：在一次性环境里用 uvicorn 单独启动 API（不连接 Telegram），对同一份测试数据库请求一组只读接口，返回结果与基准一致。另外在一次性库上分别执行一次 `db.rebind_user_tg_id`（换到新 ID、合并到已有 ID），数据变化与基准一致。
- [ ] 3.10 提交 B1。验证：提交后 `pre-commit run --all-files` 通过。

## 4. B2 接口层

- [ ] 4.1 审阅路由的映射：
  - `user.py` 和 `admin.py` 按接口逐个分到所属领域。
  - 其余路由整体归属。
  - 路由里夹带的任务、编排和通知函数，按角色放进 `jobs.py`、`service.py`、`notifications.py`。
  - 其他路由里的管理员接口留在原路由中。
  - 21 点路由做成包。
  - 凭码注册和注册状态接口留在 `invitation`。

  验证：覆盖检查中，`webapp/routers/` 没有 `TODO`。
- [ ] 4.2 审阅 schemas 和鉴权部件的映射：各领域的 `schemas.py`；`TelegramUser`、`BaseResponse` → `core/schemas.py`；`verify_telegram_data`、`get_telegram_user`、`require_telegram_auth`、`check_admin_permission` → `core/auth.py`；删除 schemas 的汇总模块。验证：覆盖检查通过。
- [ ] 4.3 审阅 Bot 命令的映射：`handlers/*.py` → 各领域的 `bot.py`，`/start` → `bot/start.py`。验证：覆盖检查通过。
- [ ] 4.4 编写 API 和 Bot 的组装代码：
  - `api/app.py`：中间件顺序、挂载顺序和 `/api` 前缀与原来一致，静态文件最后挂载。
  - `api/middlewares.py`、`api/lifespan.py`、`api/static.py`。
  - `bot/app.py`：显式列出 handler，顺序与原来一致，加上 `set_bot_commands`。
  - 把 `main.py` 的 uvicorn 目标改成 `"app.api.app:app"`，handler 注册改为读取 `bot/app.py`。

  验证：OpenAPI、路由和 Bot 快照都与基准一致。
- [ ] 4.5 运行 B2 搬迁并完成校验：`verify.py --base` 零差异，包括路由换序重叠检查和 Bot 快照。失效的 monkeypatch 目标按新位置修正。验证：`pytest` 和 `ruff` 通过。
- [ ] 4.6 加入领域内分层合约和"入口不碰数据层"合约，重新生成 ignore 列表和基线。验证：`lint-imports` 和 `pytest tests/architecture` 通过。
- [ ] 4.7 冒烟检查：用 `uvicorn app.api.app:app` 启动，对同一份测试数据库请求一组接口，包括需要 initData 的用户接口和管理员接口，返回结果与基准一致。
- [ ] 4.8 提交 B2。验证：`pre-commit run --all-files` 通过。

## 5. B3 编排层

- [ ] 5.1 审阅 `db_func.py`、`premium.py`、`modules/custom_line.py`、`utils/report.py` 和 `utils/utils.py` 剩余部分的映射（design D9），比如 `refresh_tg_user_info` → `accounts/jobs.py`，`caculate_credits_fund` → `media_access/rules.py`。验证：覆盖检查中，这些来源没有 `TODO`。
- [ ] 5.2 在 `core/scheduler.py` 里实现具名任务：任务注册表、`schedule_task(name, …)`、分发函数 `run_task(name, /, **kwargs)`，以及拒绝向持久化 jobstore 加入非具名任务的检查。验证：单元测试覆盖注册、分发、未注册任务报错，以及非具名任务被拒绝。
- [ ] 5.3 实现持久化任务引用的迁移：在 `core/scheduler.py` 里实现正向和反向改写，`scripts/refactor/rewrite_job_refs.py` 封装同一套逻辑，供手工和回退时使用。验证：测试先在 SQLite jobstore 里写入两条旧格式记录，迁移后由调度器加载，确认 `func` 解析到 `run_task`，任务名、`id`、`kwargs`、`next_run_time` 和 `misfire_grace_time` 都不变；重复迁移不产生变化；反向改写后与原始记录逐字节一致。
- [ ] 5.4 编写 `app/schedule.py`：32 个周期任务、`TASKS`、`ON_STARTUP`、`LEGACY_TASK_REFS` 和 `register_all()`。`main.py` 改为在 `scheduler.start()` 之前迁移任务引用并注册任务。21 点和夺宝的调度调用改为 `schedule_task`。验证：调度任务快照与基准一致（id、触发器、选项、executor、jobstore、相对 `next_run_time`），任务日志的文案不变。
- [ ] 5.5 运行 B3 搬迁并完成校验，然后删除旧模块：`webapp/`、`handlers/`、`modules/`、`utils/`、`models/`、`premium.py`、`config.py`、`log.py`、`scheduler.py`、`blackjack_engine.py`，以及 `databases/` 下除门面以外的文件。验证：`verify.py --base` 零差异，`src/app` 的顶层只剩 design D1 列出的条目。
- [ ] 5.6 加入 rules 纯函数合约，把领域分层合约改为 `exhaustive = true`。重新生成并封存基线：`ignore_imports` 按负责变更分组并加注释，`baseline.json` 记录负责变更和封存计数。验证：`lint-imports` 和 `pytest tests/architecture` 通过；删掉任意一条仍在生效的 ignore 会让检查失败；故意加入一个新违规也会失败。
- [ ] 5.7 在 `docs/architecture.md` 里填入按负责变更统计的基线计数，并写明回退步骤：先运行反向脚本，再回退镜像。验证：文档中的计数与 `baseline.json` 一致。
- [ ] 5.8 从最初的基准提交开始做端到端校验：`verify.py --base "$(cat scripts/refactor/BASE)"` 零差异，`check_metadata_pg.py` 差异为空，`pytest`、`ruff`、`lint-imports`、`pre-commit run --all-files` 全部通过。
- [ ] 5.9 冒烟检查持久化任务：在一次性环境的 jobstore 里预置旧格式的 21 点超时和夺宝开期记录，启动调度器。验证：日志打印出正确的迁移条数，任务按原定时间触发，并调用了正确的函数。
- [ ] 5.10 提交 B3。验证：`pre-commit run --all-files` 通过。

## 6. 部署与收尾

- [ ] 6.1 部署。验证：
  - 启动日志里有 jobstore 迁移条数。
  - 调度器的任务列表与部署前一致。
  - 接口冒烟测试通过。
  - 观察到一局 21 点超时和一期夺宝开奖正常执行。
- [ ] 6.2 解除后端功能开发的冻结。验证：AGENTS.md 和 `docs/architecture.md` 已合入主干，后续变更 `make-credit-changes-atomic` 可以开始。
