# Design

## Context

本变更依赖 `restructure-backend-architecture` 与 `make-credit-changes-atomic` 已完成的领域目录、事务边界和积分 delta API。当前 21 点代码已经拆成 `models.py`、`rules.py`、`router/`、`jobs/`、`notifications/` 和 `repository/part_*.py`，但 repository 仍由 `BlackjackRepository` mixin 组合，并通过 `DatabaseORM` facade 暴露；路由和任务仍直接调用 facade，部分结算、配置校验和锦标赛错误仍以 `ValueError` 字符串区分。

当前现金局结算会直接操作 `LuckywheelFreeSpin` 模型，幸运转盘又在消费路径中按 21 点来源解释免费机会。这违反了跨领域只能通过 service 或 `*_tx` helper 通信的约束，也使免费机会消费所需的 `cost_override` 和参与记录来源没有在发放时形成不可变快照。

本设计只描述如何完成 proposal 中的提升，不改变既有 HTTP 路径、请求/响应 JSON、调度 ID、积分规则或游戏规则。

## Goals / Non-Goals

**Goals:**

- 将 blackjack repository 改为模块级 repository API；`DatabaseORM` 不再承载 blackjack 方法。
- 建立 `blackjack.service` 作为 router、bot、jobs 与 repository 之间的事务编排边界，并让纯结算/赔付/奖池/返水/留存计算集中在 `rules.py`。
- 用 `DomainError` 及稳定的错误码替代 blackjack 路径中的异常字符串分支，同时由 API 层统一保留现有状态码和中文错误文案。
- 通过 `luckywheel.repository.grant_free_spins_tx(session, ...)` 发放免费机会；blackjack 不直接导入 luckywheel model。
- 在 `luckywheel_free_spins` 中保存发放时的消费参数快照：发放来源、消费费用和 `wheel_stats` 来源，使后续配置变化不改变既有机会的审计语义。
- 清理 blackjack 名下的 architecture baseline 条目，并用行为、事务回滚、schema parity 和 API snapshot 验证迁移等价性。

**Non-Goals:**

- 不重写 blackjack 的牌靴、策略表、赔率、抽水、奖池触发条件、锦标赛赛制或留存预算。
- 不把 luckywheel 整体提升为本变更的一部分；只新增其免费机会的最小 repository transaction helper 和消费字段读取。
- 不将通知、Telegram 网络调用或 APScheduler 注册放入 repository transaction。
- 不修改前端协议、既有持久化 job callable 兼容策略或生产数据的历史游戏记录。
- 不把本变更中发现的其他领域遗留 facade 调用顺手重构；只修改 blackjack 与其必要的 luckywheel/API 接口。

## Decisions

### D1. 保留拆分文件，移除 mixin 作为公开边界

在现有 `repository/part_*.py` 的基础上，把每个公开数据库操作改成接收显式参数、返回明确结果的模块级函数；`repository/__init__.py` 负责稳定导出。纯查询函数可以打开 repository-owned session，跨领域或需要和手牌/赛事记录同事务的函数必须提供 `*_tx(session, ...)` 版本。

`BlackjackRepository` 和 `DatabaseORM` 中的 blackjack mixin 方法不再作为业务入口。这样保留现有文件拆分和 git 迁移可审计性，又避免一次性把 4,000 行代码重写成一个新文件。

备选方案是保留 mixin、只让 service 包装它；否决理由是这会继续允许新代码绕过 service 调用 facade，无法完成 proposal 要求的 facade removal，也无法清空 blackjack 的架构基线。

### D2. Service 负责事务编排，rules 只做纯计算

按以下方向整理调用：

```text
router / bot / jobs -> blackjack.service -> blackjack.repository -> models
                                      -> blackjack.rules
```

- `rules.py` 接收普通值和配置快照，返回牌局结果、赔付、抽水、奖池、返水、救济和留存发放计划；不导入 SQLAlchemy、session、Telegram、scheduler 或其他领域。
- `repository.py` 负责锁、查询、写入和 `*_tx`；不会发送通知或调用外部媒体/Telegram API。
- `service.py` 在一个事务内调用 repository 和 credits/luckywheel 的 `*_tx` helper，提交后再执行通知和调度等副作用。
- 现有超时、周期任务和持久化 job 的函数名保留为 jobs 层适配器；它们只解析任务参数并调用 service。

结算迁移先以行为测试冻结现有顺序，再逐步拆分，避免把「积分已入账」「手牌已终态」「免费次数已发放」的顺序改变。

### D3. 统一 DomainError，同时保留现有外部文案

新增 `app.core.errors.DomainError`，至少携带 `code`、`status_code`、`payload` 和可供日志使用的内部信息。blackjack 在业务拒绝处使用稳定的领域错误子类或稳定 code，例如：

- `blackjack_disabled`
- `invalid_bet`
- `hand_not_found`
- `hand_not_owned`
- `invalid_action`
- `tournament_registration_closed`
- `tournament_full`
- `insufficient_credits`

`api.app` 注册全局 exception handler，将 `DomainError` 转成既有 endpoint 当前返回的 HTTP 状态和中文 detail；未知异常仍按现有 500 处理。router 不再依赖 `str(ValueError)` 来判断业务分支。内部 jobs/service 若捕获错误，只记录 code 与结构化 payload，不吞掉需要回滚的异常。

备选方案是让每个 router 继续捕获 `ValueError`；否决理由是字符串不是稳定协议，且同一错误在现金局和锦标赛中的状态码容易漂移。

### D4. 免费机会由 luckywheel 提供最小事务接口

新增 `luckywheel.repository.grant_free_spins_tx(session, tg_id, count, *, source, expires_at_ms, cost_credits=0, wheel_stats_source)`。该 helper 只插入 `LuckywheelFreeSpin` 行并返回创建的 ID/快照，不打开新 session，不读取 blackjack 配置，也不发送通知。

blackjack 结算在锁住用户 statistics 行、更新手数进度的同一 session 内调用此 helper；礼包等现有发放方也改用相同 helper。消费端 `consume_*` 公开 wrapper 继续保持兼容，但内部返回行上保存的快照，而不是从 `source` 通过硬编码映射推导。

`source` 表示发放领域（`blackjack`、`gift_pack`）；新增字段：

- `cost_credits_snapshot`：发放时允许的参与费用，免费机会默认 `0.00`；
- `wheel_stats_source`：消费后写入 `wheel_stats.source` 的值，例如 `blackjack_free` 或 `gift_pack_free`。

两列均带安全默认值以兼容旧数据。旧行回填为 `cost_credits_snapshot=0`，并依据既有 `source` 回填 `wheel_stats_source`；未知/NULL 来源按历史 blackjack 语义回填 `blackjack_free`，但不改变原始 `source`。消费路由把快照传给转盘执行函数，移除对 blackjack 常量的依赖。十连抽和机会优先级规则保持不变。

### D5. 数据库迁移采用可回滚的增量 schema 变更

Alembic migration 只新增两列、默认值、必要索引/约束和历史行回填，不删除旧列或重写游戏数据。迁移前后在 disposable PostgreSQL 上执行 upgrade-downgrade-upgrade，并用 production-shaped schema 检查 SQLAlchemy metadata parity。

部署顺序为：先应用迁移，再部署包含新代码的应用；回滚时旧代码能够读取默认值，且旧 jobstore callable 路径不变。若回滚代码版本，不反向删除新列，避免旧机会行无法读取。

### D6. 用 mapping 和 baseline 证明迁移而不是扩大豁免

所有从 `DatabaseORM` 移出的 blackjack 方法、跨域 import 和 deliberate AST 差异都在 `scripts/refactor/mapping.toml` 中逐项登记。禁止用目录级 skip 或新增未审计的 import-linter ignore 来通过检查。blackjack baseline 条目只能减少；新出现的跨域调用必须在源方法、目标 helper 和行为测试之间有可追踪证明。

## Risks / Trade-offs

- **[Risk] 结算路径拆分可能改变数据库写入顺序。** → 先为现金局、超时、锦标赛报名/结算和免费机会发放建立事务行为测试；每次拆分后运行 rollback/failure-injection 测试，确认积分、手牌、赛事和免费机会同生共死。
- **[Risk] 旧的 `luckywheel_free_spins` 行缺少新快照字段。** → migration 使用确定性默认值和来源回填；消费端对 NULL/历史值保留兼容 fallback，并用真实生产形态副本验证。
- **[Risk] DomainError handler 改变 OpenAPI 或错误响应。** → handler 只改变内部异常转换路径，响应 body、状态码和 detail 使用现有 endpoint snapshot 固定；增加旧/新 app 的 OpenAPI 与 HTTP smoke diff。
- **[Risk] 删除 facade 方法暴露隐藏的脚本或手工入口。** → 在删除前扫描运行时代码、scripts、scheduler job refs、手工操作清单和测试；零 caller 的方法必须先得到 manual-ops 判断。
- **[Risk] 服务层提交后通知失败导致用户看不到结果。** → 通知保持 best-effort，记录结构化错误并不回滚已提交的权威游戏状态；需要重试的任务通过现有 scheduler 注册机制处理。
- **[Risk] PostgreSQL 与 SQLite 的锁/数值行为不同。** → SQLite 只用于快速单元测试；行锁、并发、迁移链和回滚验收以 disposable PostgreSQL 为准。

## Migration Plan

1. 冻结现有 route/OpenAPI、scheduler、bot、数据库 metadata 和关键游戏行为快照。
2. 新增 `DomainError` 基类及 API handler，并先用单元测试证明未改变现有异常响应。
3. 新增 luckywheel 快照字段、repository `grant_free_spins_tx` 和 Alembic migration；在 PostgreSQL 执行 upgrade/backfill/upgrade 验证。
4. 将 blackjack 的纯计算提取到 rules，建立 service façade，再逐组迁移现金局、锦标赛、jobs、notifications 和 admin 路由。
5. 将 blackjack 结算中的免费机会发放改为 `grant_free_spins_tx`，将礼包路径同步到该 helper，切换消费端读取快照字段。
6. 逐项删除 facade mixin 方法和旧调用，更新 mapping、baseline、snapshot 与手工操作审计。
7. 执行全量测试、architecture/import-linter、PostgreSQL metadata parity、并发/回滚测试和生产形态本地彩排。
8. 部署采用先迁移后应用的顺序。出现业务回归时关闭 blackjack 配置开关并回退应用镜像；保留新增列，不反向执行破坏性 schema downgrade。

## Open Questions

无。字段语义、历史回填、错误映射和回滚边界在实施前已确定。
