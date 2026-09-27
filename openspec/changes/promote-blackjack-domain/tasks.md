# Tasks

## 1. Baseline and Error Boundary

- [x] 1.1 Freeze blackjack behavior surfaces (route/OpenAPI order, scheduler task IDs, bot handlers, repository method inventory, and representative cash/tournament response fixtures) and verify the snapshot is deterministic across two runs.
- [x] 1.2 Add `app.core.errors.DomainError` with stable code, HTTP status, payload, and cause support; add unit tests for serialization and unknown-error fallback.
- [x] 1.3 Register the API-level `DomainError` handler without changing existing response bodies or status codes; verify old/new error fixtures and OpenAPI output are identical.
- [x] 1.4 Inventory every blackjack facade caller, direct model import, `ValueError` branch, and external side effect; record reviewed destinations in `scripts/refactor/mapping.toml` and verify no unreviewed unit is omitted.

## 2. Luckywheel Free-Spin Boundary

- [x] 2.1 Add `cost_credits_snapshot` and `wheel_stats_source` to `LuckywheelFreeSpin`, update model registry, and create an Alembic migration with safe defaults and historical backfill; verify upgrade-downgrade-upgrade and metadata parity on disposable PostgreSQL.
- [x] 2.2 Implement `luckywheel.repository.grant_free_spins_tx(session, ...)` and a repository-owned wrapper; verify it uses the caller session, returns created ledger rows, rejects invalid source/count/expiry inputs, and rolls back with the caller transaction.
- [x] 2.3 Update all free-spin issuers (blackjack and gift pack) to use the transaction helper and populate immutable consumption snapshots; verify no issuer directly constructs `LuckywheelFreeSpin` outside luckywheel repository.
- [x] 2.4 Update luckywheel consumption and compensation paths to read the stored snapshots rather than infer blackjack semantics from source; verify free-spin priority, zero-cost behavior, source-specific `wheel_stats`, rollback release, and ten-spin behavior.
- [x] 2.5 Add migration and free-spin regression tests covering legacy rows, blackjack rows, gift-pack rows, unknown/null source fallback, and configuration changes after issuance; verify all cases with focused pytest tests.

## 3. Blackjack Pure Rules and Typed Errors

- [x] 3.1 Extract cash settlement calculations (hand outcome, payout, rake, jackpot, relief, cashback inputs, and balance deltas) into pure `blackjack.rules` functions; verify rules have no SQLAlchemy/session/external imports and match frozen examples.
- [x] 3.2 Extract tournament validation, payout, deadline, and entrant calculations into pure rules functions; verify invalid configurations and boundary cases return the existing business outcomes through focused tests.
- [x] 3.3 Define blackjack `DomainError` codes/subclasses and replace business `ValueError` raises in cash and tournament repository/service paths; verify each former user-facing message maps to the same HTTP status/detail.
- [x] 3.4 Add rules and typed-error tests for disabled game, invalid bets/actions, ownership, timeout, registration/full tournament, payout configuration, and insufficient credits; verify no string-matching branches remain in routers.

## 4. Repository Promotion

- [x] 4.1 Convert the split blackjack repository implementation to module-level query/write functions with explicit parameters and stable exports; verify public functions have no dependency on `BlackjackRepository` instances.
- [x] 4.2 Provide caller-owned `*_tx(session, ...)` functions for hand lifecycle, settlement, tournament registration/actions/settlement, configuration, statistics, and retention records; verify all multi-write operations reuse one session and lock rows before calculating deltas.
- [x] 4.3 Move blackjack-specific model/config constants to explicit repository or rules modules as appropriate, preserving import paths needed by scheduler/jobstore compatibility; verify all 21-point modules import successfully.
- [x] 4.4 Migrate cross-domain blackjack callers (credits, luckywheel, badges, rankings, gift pack, and account/profile consumers) to module/service/`*_tx` APIs; verify no new direct foreign-model or facade import is introduced.
- [x] 4.5 Remove blackjack methods and mixin inheritance from `DatabaseORM` only after all callers migrate; verify facade introspection contains no blackjack operations and manual-operation review has no deleted entry point.
- [x] 4.6 Update mapping/provenance and architecture baseline entries item-by-item, then verify blackjack violations strictly decrease without adding broad import-linter exemptions.
- [x] 4.7 Add repository transaction/failure-injection tests for cash settlement, timeout settlement, tournament registration, tournament settlement, and free-spin issuance; verify balances, hands, entries, and awards roll back together.

## 5. Service and Side-Effect Orchestration

- [x] 5.1 Implement `blackjack.service` for cash hand workflows, delegating calculations to rules and writes to repository; verify routers/jobs can execute the workflow without importing repository implementation parts or external clients.
  - 验证方式：`tests/refactor/test_blackjack_service_boundary.py`——接口模块零导入 `blackjack.repository*`/`app.databases`/`app.core.db`/`sqlalchemy`，跨领域导入只允许 service 或类型模块。
  - 逐项例外：`blackjack/router/cash.py` 仍导入 `badge_awards.jobs.check_and_award_game_king_badge`（该领域无 service，且其内部已反向依赖 `blackjack.service`，搬到 blackjack.service 会形成环）。已按行号固定为唯一条目，责任变更：promote-reward-domains。
- [x] 5.2 Implement tournament service workflows for registration, player actions, ticking, settlement, and champion award coordination; verify buy-in split, payout, badge award, and state transitions preserve existing results.
  - 报名/行动/结算原有 service 入口不变；tick 三阶段（`_tick_registration_deadlines`/`_tick_completion_reminders`/`_tick_play_deadlines`）与每周自动开赛工作流从 `jobs/tournament.py` 搬入 `service.py`（`tick_tournaments`/`create_weekly_tournament`），jobs 只保留同名任务适配入口。
  - 验证：`tests/test_blackjack_tournament_settle.py`（含冠军勋章 `award_awaited_once_with(1)`）、`tests/test_blackjack_tournament_auto_create.py`、`tests/test_blackjack_retention.py`（报名钱包/积分拆分）全通过。
- [x] 5.3 Move post-commit Telegram notifications, group broadcasts, badge notifications, and scheduler submissions behind service/job boundaries; verify repository transactions contain no network, notification, or scheduler side effects.
  - 验证方式：`tests/refactor/test_blackjack_side_effect_boundary.py`——repository 零副作用导入/调用，router 不直接发消息，`app.core.scheduler` 仅由 `jobs/cash` 导入，tick 工作流中通知调用行号晚于落库调用。
  - 锦标赛全部通知已随 5.2 进入 service（repository 返回后执行）；现金局奖池/免费次数播报仍由 jobs/notifications 的游标任务负责。
- [x] 5.4 Update blackjack jobs and notification modules to call services while preserving task IDs, persisted callable compatibility, execution order, and best-effort notification behavior; verify schedule registry snapshots remain unchanged.
  - `jobs/cash.py`、`jobs/tournament.py`、`notifications/*` 均已只调 service / 纯通知格式化；任务入口名未变。
  - 验证：`tests/refactor/test_schedule_registry.py`（32 个周期任务 ID 与顺序不变、命名任务集合不变）、`tests/refactor/test_job_references.py`（持久化任务引用兼容）、`tests/refactor/test_b2_assembly.py`、新增 tick 阶段顺序断言。
- [x] 5.5 Add service tests for successful workflows, post-commit side-effect failure, retry-safe notification behavior, and scheduler invocation; verify committed game state is not rolled back by notification failures.
  - 验证方式：`tests/test_blackjack_service_workflows.py`——赛果通知失败仍已派奖、开赛通知失败仍是 RUNNING、单场失败不影响其他场、通知关闭仍推进去重游标（重试安全）、拉列表失败不抛出。

## 6. Interface Migration and Compatibility

- [x] 6.1 Migrate cash, tournament, and tournament-admin routers to service APIs and typed errors, preserving paths, parameters, status codes, response schemas, and Chinese detail messages; verify route behavior against the frozen HTTP fixtures.
  - 验证：`tests/refactor/fixtures/blackjack_surface.json`（28 条路由 + 27 条 OpenAPI path 冻结）、`tests/refactor/test_blackjack_baseline.py`、`tests/test_blackjack_errors.py`（状态码/中文 detail 与无字符串匹配）、`tests/refactor/test_blackjack_service_boundary.py`（三个 router 只调 service）。
- [x] 6.2 Migrate blackjack bot handlers and admin/config endpoints to service/module imports; verify handler registration order, command signatures, and admin authorization remain unchanged.
  - 本领域无 Telegram bot 命令处理器（bot 层无 blackjack 引用），无需迁移；管理/配置端点已全部走 `blackjack_service`。
  - 验证：`tests/refactor/test_blackjack_side_effect_boundary.py::test_tournament_admin_endpoints_keep_auth_and_admin_checks`（每个管理端点保留 `@require_telegram_auth` 与 `check_admin_permission`）；`tests/refactor/test_schedule_registry.py` 覆盖 bot 注册顺序快照。
- [x] 6.3 Remove direct `app.databases` and foreign model imports from blackjack interface modules; verify `PYTHONPATH=src .venv/bin/lint-imports --no-cache` and the domain interface AST check pass.
  - 验证：接口模块零 `app.databases`/`app.core.db`/`sqlalchemy`/`blackjack.repository*` 导入；`lint-imports` 10/10 通过（忽略项计数未增加）。
- [x] 6.4 Verify persisted scheduler references and startup recovery after repository/service relocation; verify no unresolved legacy job is deleted and all named tasks remain registered before API startup.
  - 验证：`tests/refactor/test_job_references.py`（字节级迁移/回滚）、`tests/test_blackjack_startup_recovery.py`（活跃手牌重建 `blackjack.hand_timeout`，`misfire_grace_time=None`，过期手牌交由兜底）、`tests/refactor/test_schedule_registry.py`（`register_tasks` 先于 API 线程与 bot 启动）。

## 7. Integration and Release Verification

- [x] 7.1 Run the full blackjack regression suite plus architecture/refactoring tests, and fix all behavior/snapshot differences before changing task status; verify no route, OpenAPI, scheduler, ORM, or bot drift.
  - 验证：`pytest tests/`全绿；`tests/refactor/fixtures/blackjack_surface.json`（路由/OpenAPI path/调度任务 ID/ORM 表）与 `blackjack_inventory.json` 在 7.x 期间的漂移均已同步，无未审阅的快照差异。
- [x] 7.2 Run disposable PostgreSQL concurrency and rollback tests for blackjack settlement, competing actions, credits, tournament payout, and free-spin issuance; verify no lost updates, negative balances, deadlocks, or partial records.
  - 验证：`scripts/refactor/smoke_blackjack_concurrency.py`（一次性 PostgreSQL 16 容器；pytest 入口 `tests/refactor/test_blackjack_concurrency.py`，由 `BLACKJACK_TEST_DATABASE_URL` 开启）+ `tests/test_blackjack_repository_rollback.py`（结算/超时/报名/派奖/免费次数失败注入回滚）。
- [x] 7.3 Run Alembic metadata comparison and production-shaped local rehearsal using a sanitized quince database copy with external notifications mocked; verify API health, protected-route auth, scheduler startup, and representative blackjack settlement.
  - 验证：一次性 PostgreSQL 16 上的 upgrade/downgrade/upgrade + `compare_metadata` 空 diff；一次性 PostgreSQL 18.6 上导入脱敏 quince 副本（33 张表、225 条 statistics、1744 条免费次数），升到 head 完成回填；`scripts/refactor/rehearse_blackjack.py`（pytest 入口 `tests/refactor/test_blackjack_rehearsal.py`，由 `BLACKJACK_REHEARSAL_DATABASE_URL` 开启）全部检查通过。
- [x] 7.4 Update `docs/architecture.md` with the promotion template, blackjack ownership/boundary rules, migration/backfill/rollback evidence, and final baseline/provenance counts; verify documentation commands are reproducible.
  - 已在 `docs/architecture.md` 新增「领域提升模板」「blackjack 领域边界」「blackjack 迁移、回填与彩排证据」三节，并把基线计数更新为 544 条 / B3 provenance 56 条，忽略项计数同步为 18/19/20/59/18/7/76。
- [ ] 7.5 Run pre-commit, full backend tests, import-linter, architecture baseline, OpenSpec validation, and `git diff --check`; verify the worktree is clean before marking the change complete.
