# Design

## Context

动机见 proposal.md。本设计假定其余 13 个后续变更都已完成：所有领域都已提升，门面只组合 identity 和 invitation 的兼容层，而它们已经没有调用方（由 `promote-remaining-domains` 确认）。

以下现状以调研时的 `3f27100` 为准。实施时要重新盘点，因为各个 promote 变更一直在改基线和放行名单。

**门面**

- `app/databases/` 下只有 `__init__.py` 和 `db.py`。
- 调研时有 46 个模块导入门面，其中 `premium/service.py` 有 4 处函数内的延迟导入。
- 门面冻结合约的 `allowed_importers` 有 50 项，其中 4 项已经失效：`app.main`、`app.schedule`、`blackjack.service`、`custom_lines.service`。

**import-linter 中专为门面或过渡而设的配置**

| 合约 | 相关内容 | 门面删除后 |
|---|---|---|
| Top-level | `(app.domains) : (app.databases)` | 改为 `(app.domains)` |
| External isolation | 禁止导入 `app.databases` | 缺失的禁止项会被跳过，成为陈旧配置；删除 |
| Facade freeze | 整个合约 | protected 合约遇到缺失模块会抛 `ModuleNotPresent`，必须删除 |
| SQLAlchemy scope | 放行 `app.databases.db` | 同样会抛 `ModuleNotPresent`，必须删除 |
| Engine scope | 放行 `app.models`（B3 起已不存在） | 删除 |
| Six-tier / Acyclic | 门面组合边的忽略项；Six-tier 为 `exhaustive = false` | 删除忽略项；改为 `exhaustive = true` |
| Entry points | 禁止导入 `app.databases` | 删除 |

**`tests/architecture`**

- 门面和 mixin 专用的扫描：`LEGACY_DATABASE_MODULE`、`db` 别名的收集、`facade_call`、`self_call`、`scan_mixin_duplicates`。
- `test_b2_provenance.py`：会执行 `git worktree add`，依赖 B2、B3 冻结提交和审计脚本，并在 pre-commit 中运行。
- `test_scheduler_jobstore_boundary.py`：从 `B3_BASE` 取出当时的 pyproject 做比较。
- `helpers.py` 要求 `baseline.json` 包含四个类别；`promote-gift-pack-domain` 又加了 `numbered_modules`。

**调度**

- 过渡代码包括：`LEGACY_TASK_REFS`、`migrate_persisted_jobs`、`core/scheduler.py` 中的 pickle 改写助手、`named_persistent_only` 开关，以及 `core/db.py` 中的 `rewrite_scheduler_rows`。
- APScheduler 加载无法解析的任务时，会删除这条记录。
- 生产环境尚未部署 B3，README 引导他人使用 GHCR 镜像。

**`scripts/refactor/`**

- 22 个脚本。按用途分：
  - 搬迁：relocate、rewrite_refs、seed_mapping、relocation_refs、split_repository、cycles。
  - 审计：audit_b2、audit_b3。
  - 冒烟：smoke_b1、smoke_b2、smoke_b3_decycles、smoke_b3_jobs。
  - 回退：rewrite_job_refs。
  - 积分：credit_inventory、check_credit_migration、smoke_credit_concurrency。
  - 21 点试点：blackjack_inventory、blackjack_snapshot。
  - 校验：inventory、snapshot、verify、check_metadata_pg。
- 数据文件：`mapping.toml`、三个 BASE 文件、若干 inventory JSON。
- snapshot 和 verify 与门面、BASE、`mapping.toml`，以及 `main.py` 的兼容垫片（`add_init_scheduler_job`、`set_bot_commands`）耦合在一起。

**`tests/refactor/`**

其中 `test_manage_cli`、`test_model_registry`、`test_named_scheduler`、`test_schedule_registry`、`test_b2_assembly` 测试的是生产代码，不是工具。

**导入门面的其他脚本**

`backfill_invitation_ids.py` 和 `backfill_invitation_service.py` 已由 `promote-account-domains` 改用新 API。`migrate_redis_to_database.py` 和 `migrate_line_traffic_stats.py` 仍然导入门面。

**文档**

- AGENTS.md 里有 Transition 段，以及一些过时的路径：`app.databases.session`、`app.log`、`app/config.py`、`app/models/models.py`，还有"DomainError 尚未引入"。
- `docs/architecture.md` 里有过渡门面、基线计数、B3 彩排和部署回退等章节。

**本地残留**

只剩 `__pycache__` 的目录会被解析成命名空间包；`.venv` 里还有一份旧的非 editable 安装。两者都可能掩盖"模块已被删除"的错误。

## Goals / Non-Goals

**Goals：**

- 仓库中不再有门面、过渡合约、过渡测试和一次性工具；架构检查以终态规则运行，不带任何豁免。
- 还没迁移任务引用的实例不会因为升级而静默丢失任务，而是在启动时明确失败，并给出操作指引。
- 仍然有用的快照和元数据比对工具继续可用，供以后的变更使用。

**Non-Goals：**

- 不改任何业务行为、接口或 schema。
- 不在本变更中清理其他变更遗留的基线条目。实施前发现遗留条目，就退回给对应的负责变更处理；只有与门面删除直接相关的机械修改，才在本变更内完成。
- 不追溯改写已归档变更文档中的历史描述。

## Decisions

### D1 前置核对

实施前运行一次盘点脚本，确认以下全部成立，否则停止：

- `baseline.json` 的 `cross_domain_calls`、`numbered_modules`、`model_registry` 都为空。
- import-linter 中除门面组合边以外没有任何 `ignore_imports`。
- 用 AST 和 grimp 确认，`src` 中导入 `app.databases` 的只有 `app/databases` 自身。

盘点结果写进本变更的任务记录。

### D2 删除门面与改写合约

- **删除 `app/databases/`**：删除整个目录，包括两个兼容层。
- **改写合约**：按 Context 中的表格修改。门面冻结合约和 SQLAlchemy 合约的放行项必须在同一提交中删除，否则 lint 会直接报错。六层合约改为 `exhaustive = true`，这样新增领域时必须先在合约中定层。
- **封存计数**：`contract_ignore_counts` 全部为 0，然后删除这一项。以后合约中不允许 `ignore_imports`，由一个测试断言所有合约都没有 `ignore_imports`。

### D3 架构测试收敛到终态

- **删除过时的扫描**：`checks.py` 中门面、mixin、`self_call` 和 `DatabaseORM` 的分支；`scan_mixin_duplicates`，这时已经没有 mixin；`facade_call` 这一类别。
- **保留的检查**：跨域的 import 与调用规则、单文件行数预算、模型注册完整、序号模块、换绑覆盖、读模型只读，以及配置跨域只读。
- **简化 `baseline.json`**：只保留 `line_budgets`，只列仍然超预算的文件；为空时也保留这个键。`helpers.py` 同步调整。
- **删除过渡测试**：删除 `test_b2_provenance.py`。`test_scheduler_jobstore_boundary.py` 改为直接断言当前合约，不再读取 B3 提交。
- **积分写入检查常驻**：把 `check_credit_migration` 的逻辑改写为 `tests/architecture` 中的常驻测试。它的规则就是 `docs/architecture.md` 中"积分只用增量"那一条，所以不能随工具一起删除。

### D4 任务引用：独立迁移脚本与启动守卫

- **删除过渡代码**：`LEGACY_TASK_REFS`、`migrate_persisted_jobs`、`core/scheduler.py` 中的 pickle 改写助手和 `named_persistent_only` 开关（持久化任务必须是具名任务的检查改为始终开启）、`core/db.py` 中的 `rewrite_scheduler_rows`，以及 `core.scheduler` 对 `app.core.db` 的例外放行。
- **独立迁移脚本**：新增 `scripts/migrate_legacy_job_refs.py`：
  - 自带正向和反向两套改写逻辑，从原来的实现原样迁移，包括逐字节的恢复。
  - 直接用 SQLAlchemy 连接 jobstore，不导入 `app` 包。
  - 保留 `--reverse --scheduler-stopped` 的安全确认。
- **启动守卫**：新增 `core.scheduler.assert_no_legacy_job_refs(jobstore)`，在 `scheduler.start()` 之前运行：
  - 只读查询 `apscheduler_jobs`，对每条记录 `pickle.loads` 后检查 `func` 字符串。这个检查不会导入任务函数。
  - 发现不是 `app.core.scheduler:run_task`、而且无法解析的旧引用时，记录 critical 日志，给出脚本的用法，然后让进程以非 0 状态退出，不启动调度器。
  - 表不存在时视为通过。
- **文档**：`docs/architecture.md` 的部署回退一节改为使用这个脚本；发布说明写明"从 B3 之前的版本升级，需要先运行一次迁移脚本"。

备选方案：

- **按原计划直接删除迁移**：没有迁移过的实例启动时会静默丢失夺宝的自动开期任务，而且无法察觉。
- **在应用中永久保留迁移**：过渡代码会一直留在 `core`，与本变更的目的相悖。

### D5 快照工具与 refactor 目录

- **保留并改写**：`snapshot.py` 和 `check_metadata_pg.py` 移到 `scripts/verify/`：
  - 快照保留 OpenAPI 与路由顺序、调度任务、Bot handler 与命令菜单、模型元数据；删除门面方法清单、BASE 回退逻辑和字符串引用解析。
  - 删除 `main.py` 中仅为快照比对存在的兼容垫片，快照直接调用 `schedule.register_all` 和 `bot.app` 的注册函数。
  - 更新对应的测试。
- **删除**：其余脚本、`mapping.toml`、三个 BASE 文件、inventory JSON，以及 21 点试点的冻结夹具和对应测试。夹具只在试点期间有意义，而这时 21 点早已完成提升。
- **生产代码测试迁移**：`tests/refactor/` 中测试生产代码的 5 个文件移到 `tests/`，然后删除 `tests/refactor/`。
- **pre-commit**：保留 `lint-imports` 和 `pytest tests/architecture` 两个 hook。它们不再依赖 git worktree 或历史提交，执行时间会缩短。

### D6 仍然导入门面的手动脚本

`migrate_redis_to_database.py` 和 `migrate_line_traffic_stats.py` 属于历史数据迁移。先查手动运维清单，并请维护者逐个确认：

- 保留的：改用领域 API，并登记进手动运维清单。
- 不再需要的：删除。

### D7 文档终态

- **AGENTS.md**：
  - 删除 Transition 段，以及以 `DatabaseORM`、`db_func.py` 为例的内容。
  - 修正过时路径：`app.databases.session`、`app.log`、`app/config.py`、`app/models/models.py`。
  - 修正"DomainError 尚未引入"的说法。
  - 删除"新数据库操作写进 mixin 并经 `db` 调用"这条过渡规则。
- **`docs/architecture.md`**：
  - 分层图和领域内分层去掉门面。
  - 删除以下章节：过渡门面、基线计数、B3 彩排证据、积分彩排证据、后续变更表。
  - 部署回退一节改写为 D4 的做法。
  - "已知例外"一节只保留读模型规则。
  - 手动运维清单以 `app.manage` 的各个子命令为准。

### D8 本地残留与验证环境

- **在干净环境中验证**：在一个全新的 worktree 或 CI 式的环境中运行全部校验，不带 `__pycache__`，并以 editable 方式安装，避免残留的命名空间包或旧安装掩盖导入错误。
- **新增测试**：导入 `app.databases`、`app.webapp`、`app.models` 都必须抛出 `ModuleNotFoundError`。

## Risks / Trade-offs

- **[还有未迁移的实例]** → 启动守卫让问题显式暴露；独立脚本提供迁移和回退手段；发布说明写明升级步骤。
- **[删除测试和工具时，误删了仍在保护规则的检查]** → D3 逐项列出保留的检查；积分写入检查改为常驻测试；删除前用负向探针验证每个保留的检查仍然有效。
- **[其他变更遗留的基线条目]** → D1 的前置核对不通过就停止，交回对应的负责变更，不在本变更中放宽规则。
- **[`exhaustive = true` 让新增领域的步骤变多]** → 这正是 D10 当初的意图；在 AGENTS.md 的"新代码放哪"清单中写明"新领域先在合约中定层"。

## Migration Plan

1. 前置核对（D1）。
2. 删除门面，改写合约和架构测试（D2、D3）。
3. 迁出任务引用迁移，加入启动守卫（D4），并在一次性环境中验证三种情况：预置旧记录时拒绝启动；运行脚本后正常启动；反向脚本能逐字节恢复。
4. 精简工具和测试，处理手动脚本，更新文档（D5–D7）。
5. 在干净环境中运行全量校验（D8）。
6. 部署：没有 schema 变更。发布说明写明升级步骤。

## Open Questions

无。
