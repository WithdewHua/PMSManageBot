# 后端架构

本文件是领域边界、数据归属和过渡期例外的参考资料；日常编码规则与命令见 [AGENTS.md](../AGENTS.md)。本次搬迁只改变代码位置，不改变接口、数据库结构或行为。后续 `promote-*` 变更逐步移除过渡例外。

## 分层与依赖方向

```text
main.py（进程入口）
  ↓
api/ · bot/ · schedule.py · model_registry.py（组装）
  ↓
domains/（业务领域；过渡期经 databases/db.py 门面）
  ↓
integrations/（外部 API 客户端）
  ↓
core/（公共设施）

领域内：router / admin_router / bot / jobs → service → repository / notifications → models
                                   ↘ rules / constants / exceptions / schemas
领域之间：T5 → T4 → T3 → T2 → T1 → T0；同层可依赖但不能成环。
```

`main.py` 仍是 `python -m app.main` 的入口。`api/` 只组装 FastAPI，`bot/` 只组装 Telegram Bot；`schedule.py` 声明任务，`model_registry.py` 显式导入全部模型。`core/` 不导入领域、门面或 integrations；integrations 只导入 core。除门面外，不保留旧模块的兼容导入路径。

| 领域内角色 | 职责及依赖方向 |
|---|---|
| `router.py` / `admin_router.py` | 用户 / 管理员 HTTP 入口，依赖本领域 service、schemas、exceptions 与 core；来自旧 admin 路由的入口放在 admin_router |
| `bot.py` / `jobs.py` | Bot 命令 / 定时任务入口，依赖本领域 service（jobs 也可依赖 notifications）和 core |
| `service.py` | 用例编排，依赖本领域 repository、rules、notifications，其他领域的 service 和 integrations；外部副作用在事务提交后执行 |
| `notifications.py` | 消息格式化与发送，依赖 rules、constants、core.telegram |
| `repository.py` | 唯一的业务 SQLAlchemy 查询和事务位置；对外提供完整事务操作，跨域同事务调用目标领域的 `*_tx(session, …)` |
| `models.py` | 本领域的 ORM 表，依赖 core.db；所有模型经 model_registry 注册 |
| `rules.py` | 不做 I/O 的纯逻辑，依赖 constants、exceptions、本领域 models（仅作类型注解）；由「Domain rules are pure value computations」合约禁止直接导入 `app.core.db`、`sqlalchemy`、repository/service/router/jobs/notifications，需要取数时由 repository 依据 `required_metrics(...)` 预取 |
| `schemas.py` | Pydantic 请求和响应模型，依赖 constants 和 core.schemas |
| `exceptions.py` / `constants.py` / `config.py` | 领域异常 / 常量 / 类型化业务配置 |

单个角色文件超过 1,000 行时改成同名包，按子主题分文件，包的公开接口保持不变。过渡期 repository 是组合到 `app.databases.db.DatabaseORM` 的 mixin，已有 `db.xxx()` 调用保持不变；新数据库操作进入所属领域的 repository，而不是添加到门面。

## 领域目录

每个领域在下表恰好列出一次；上层可依赖下层，同层依赖不得成环。T4 协调多领域用例，不另设应用层目录。

| 层级 | 领域（`app.domains.<name>`） | 职责 |
|---|---|---|
| T5 读模型 | `rankings` | 所有排行榜查询及 Bot 排行命令 |
| T5 读模型 | `reports` | 系统统计、周报、服务器状态与后台设置总览 |
| T5 读模型 | `profile` | 用户信息总览（`/api/user/info`、`/info`） |
| T4 跨域策略 | `watch_rewards` | 观看时长积分结算、幽灵会话补偿及会员流量扣费 |
| T4 跨域策略 | `gift_pack` | 礼包定义、领取条件、奖励与领取 |
| T4 跨域策略 | `badge_awards` | 自动颁发游戏王、至尊贡献者勋章 |
| T4 跨域策略 | `tg_rebind` | 管理员手动执行的 TG ID 换绑与数据合并 |
| T3 业务功能 | `accounts` | 媒体账号绑定、解绑、注册开关、信息同步及 Overseerr 账号 |
| T3 业务功能 | `invitation` | 邀请码生成、兑换、凭码注册及特权码 |
| T3 业务功能 | `premium` | 会员开通、到期、会员线路及会员流量 |
| T3 业务功能 | `custom_lines` | 用户自建线路申请、审核、上下线和流量结算 |
| T3 业务功能 | `donation` | 捐赠登记和确认 |
| T3 业务功能 | `crypto_donation` | UPay 加密货币订单 |
| T3 业务功能 | `luckywheel` | 幸运大转盘及所有来源的免费次数账本 |
| T3 业务功能 | `treasure` | 夺宝奇兵 |
| T3 业务功能 | `prediction` | 大预言家 |
| T3 业务功能 | `auction` | 竞拍 |
| T3 业务功能 | `blackjack` | 21 点牌局、奖池、留存、返水及锦标赛 |
| T2 共享能力 | `badges` | 勋章定义、发放、兑换和加成查询 |
| T2 共享能力 | `lines` | 线路目录、绑定、调度及网关用户缓存 |
| T2 共享能力 | `traffic` | 流量记录、按日按月聚合及上限 |
| T2 共享能力 | `media_access` | NSFW/全库、下载/同步权限解锁及媒体服务器权限同步 |
| T2 共享能力 | `vaultwarden` | Vaultwarden 账号兑换 |
| T1 账本 | `credits` | 积分余额查询、增减、转账及积分缓存 |
| T0 基础 | `identity` | `statistics`、`plex_user`、`emby_user`、`overseerr` 宽表及按键查询和建档 |

## 跨域导入规则

- 跨域调用只允许目标领域的 `service` 或 `*_tx` repository helper；不得导入外域的 models、routers、jobs、notifications。
- 共享词汇例外：`<domain>/types.py` 是纯值类型模块（`credits/types.py` 的 `CreditAccount`、`CreditMutation`、`CreditTransfer`），任何领域的任何角色都可以导入它。纯性由 import-linter 合约“Domain types are pure value modules”强制：types 不得导入本领域的 service/repository/models/config/exceptions，也不得导入 `app.core.db` 或 SQLAlchemy。
- AST 检查（`tests/architecture/checks.py`）把 `types` 与 `service`、`exceptions`、`constants` 并列视为可跨域导入的角色，其余角色仍然登记为基线债务。
- 积分写入的自登记：`credits.repository.add_tx` / `deduct_tx` / `move_tx` 在调用方 session 上按 cache key 登记提交后的缓存失效（`app.core.db.register_post_commit`，同一 key 幂等），所以调用方不需要记得失效缓存；显式的 `credits_service.register_cache_invalidation` 只为非由 mutation 推导的 key 保留，重复登记无副作用。

## 宽表列归属

宽表模型放在 identity，其他领域可读，写入只由列组所属领域的 repository 执行。跨域写入调用所属领域的 `*_tx`。新增用户状态应建在本领域自己的表中，以 `tg_id` 为键，不往宽表增加列。本次只用文档和 review 检查列归属。

| 表 | 列组 | 写入方 |
|---|---|---|
| `statistics` | `tg_id` | identity |
| `statistics` | `credits` | credits |
| `statistics` | `donation` | donation |
| `statistics` | `tournament_wallet_credits`、`blackjack_lose_streak`、`blackjack_hands_since_freespin` | blackjack |
| `plex_user` / `emby_user` | 主键、`tg_id`、用户名、邮箱、`last_viewed_at` | identity（由 accounts、tg_rebind 调用） |
| `plex_user` / `emby_user` | `credits` / `emby_credits`（未绑定 TG 时） | credits |
| `plex_user` / `emby_user` | `watched_time` / `emby_watched_time` | watch_rewards |
| `plex_user` / `emby_user` | `all_lib`、`unlock_time` / `emby_is_unlock`、`emby_unlock_time`；`sync_unlocked`、`sync_unlock_time` / `download_unlocked`、`download_unlock_time` | media_access |
| `plex_user` / `emby_user` | `plex_line` / `emby_line`、`line_schedule_unlocked`、`line_schedule_unlock_time` | lines |
| `plex_user` / `emby_user` | `is_premium`、`premium_expiry_time`、`premium_status_updated_at`、`premium_traffic_debt_bytes`、`premium_traffic_debt_updated_date` | premium |
| `overseerr` | 全部 | identity |

## 已知例外和清理责任

- **读模型直读跨域表**：T5 的 rankings、reports、profile repository 可以跨表只读聚合，不可写入其他领域的数据。后续 `promote-remaining-domains` 核对查询。
- **过渡门面**：`app.databases.db` 暂时组合 repository mixin，以保持旧调用面；门面文件本身不新增方法，新方法写入所属领域的 repository mixin，只允许本领域经 `db.xxx()` 调用，不新增跨域调用。`retire-legacy-db-facade` 删除它。旧的跨域 `db.xxx()` / `self.xxx()` 依赖登记在架构测试基线，按所属领域的提升变更清理。
- **特权邀请码 `.env` 写入**：唯一的提交前外部副作用例外，落在拥有该资源的 `invitation` 领域（`invitation.repository.persist_privileged_codes_tx`）：礼包在最后一次数据库 flush 之后、事务提交之前调用，写失败会恢复内存配置并回滚数据库领取；媒体权限同步仍在提交后进行。`move-privileged-codes-to-database` 将特权码移出 `.env`。
- **入口层现存环**：活动领域触发自动勋章、badge_awards 反读活动数据（`promote-reward-domains`：提交后领域事件）；accounts 同步回填 invitation 邀请记录、invitation 兑换反调同步（`promote-account-domains`：回填归 invitation）；luckywheel 消耗 blackjack 来源免费次数时反读 blackjack 配置（`promote-blackjack-domain`：发放时保存参数）。搬迁阶段仅登记，不改变行为。
- **TG 换绑跨域写入和漏迁**：当前实现原样搬迁，`promote-tg-rebind-domain` 会用各领域的 `reassign_tg_id_tx` 修复覆盖范围与写入边界。

需要下层通知上层时使用提交后的领域事件，不从下层直接导入上层；具体事件形式由首次需要它的后续变更确定。

## 手动运维操作

| 操作 | 入口及调用方式 | 保留理由 / 后续责任 |
|---|---|---|
| TG 用户换绑 | `db.rebind_user_tg_id(...)`，由管理员在运维 Python 环境手动调用；搬迁后仍由 `from app.databases import db` 获取门面 | 虽无代码调用方，但属于人工操作入口；现有漏迁问题由 `promote-tg-rebind-domain` 修复，删除前须与维护者确认 |

## 配置分类

- **基础设施与密钥**：系统环境 / `data/.env`，由 core.config 只读加载（如 Telegram token、数据库 URL、外部服务地址）。不在业务事务内更新。
- **运行时业务配置**：使用各领域带类型的 `DomainConfig`，持久化于 core.kv 的 `SystemConfig` 键值表；不向 `.env` 新增可变业务配置。现存业务配置由 `unify-business-configuration` 迁移。
- **遗留例外**：礼包特权码目前在 `.env`，见上文例外；线路目录迁移由 `move-line-catalog-to-database` 负责。

## 基线计数

B2 过渡基线以 `scripts/refactor/B2_BASE` 中的 B1 提交为来源。B3 机械搬迁以 `scripts/refactor/B3_BASE`（B2 提交 `1b49ea8273253ee7b1b35e13056ca047f9ce45bc`）为冻结来源。`tests/architecture/baseline.json` 当前封存 544 条跨域调用／导入，其中 56 条 B3 条目记录 `b3_source_id`；`scripts/refactor/audit_b3_baseline.py` 只接受冻结源码中的实际来源单元及逐项 `b3_key`，并拒绝仅凭目标领域候选、同名导入换目标或新增领域环封存。B3 为调度器去环及 CLI 组装登记的 AST 差异分别记录 `b3_ast_exception` 和实际存在的行为测试。

按清理责任分组的 B3 封存计数由 `audit_b3_baseline.py` 输出；当前 B3 provenance 封存 56 条，架构基线共 544 条，其中后续 credits 迁移条目由 `make-credit-changes-atomic` 负责，不冒充 B3 遗留债务。B3 条目只允许来源于 `db_func.py`、`premium.py`、`modules/custom_line.py`、`utils/report.py` 和 `utils/utils.py` 的冻结单元。

`promote-blackjack-domain` 摘除门面后基线严格下降（547 → 544 条，其中 B3 provenance 58 → 56 条），未新增任何条目；`import-linter` 只删除豁免（六层领域依赖 65 → 59、无环兄弟领域 19 → 18、领域内分层 8 → 7、入口不碰数据层 82 → 76，SQLAlchemy 范围 18、数据库引擎范围 19、模型范围 20 不变）。

当前 import-linter ignore 数：SQLAlchemy 范围 18、数据库引擎范围 19、模型范围 20、六层领域依赖 59、无环兄弟领域 18、领域内分层 7、入口不碰数据层 76；其余合约 0。B3 去环与 blackjack 提升都没有新增 `Acyclic domain siblings` 豁免；任何新增豁免必须有冻结来源单元和行为测试证明。

## 积分账本写入规则

`credits` 是 `statistics.credits`、未绑定 `plex_user.credits` 和未绑定 `emby_user.emby_credits` 的唯一增减入口。每个 delta 在锁定当前行后先按既有 Python 两位小数规则计算有效增量，再以 `column + effective_delta` 的 SQL 表达式写回，避免返回值与持久化值不一致。新代码不得读取余额后计算绝对值再写回，也不得调用已废弃的 `update_user_credits`；必须使用 credits repository 的 SQL 增量操作。跨领域事务必须传递调用方 session 使用 `*_tx`，不得为积分变更另开 session，以避免丢失更新和行锁死锁。转账按稳定的账户 ID 顺序锁定双方，缓存只在外层事务提交后失效。

`make-credit-changes-atomic` 的 AST inventory 保存在 `scripts/refactor/credit_inventory.json`；当前候选写入数为 0，说明所有已审阅的绝对值 writer、属性赋值和 `.values()` 写入均已迁移。`scripts/refactor/check_credit_migration.py` 与 `credit_migration.toml` 在严格模式下持续拒绝新 writer；inventory 是迁移清单，不把 `profile` 响应对象等非持久化候选直接视为数据库写入。旧的 58 条初始盘点可从 Git 历史恢复审计。

绑定 Plex/Emby 与余额转移现在由 accounts repository 在同一事务中完成；如果目标统计行、绑定写入或积分转移任一步失败，账户绑定和余额均回滚。捐赠倍率重算也在一个事务中处理全部用户，后续用户余额不足时不会留下前面用户的部分更新。转账费率额外拒绝负数和非有限值。

## 积分生产形态彩排证据

从 `quince` 加密流式导入了完整 `pmsmanagebot` PostgreSQL 副本到本地 PostgreSQL 18.3 隔离容器（33 张 public 表、224 条 `statistics` 记录），未写回 quince。使用 `app.api.app:app`、`--lifespan off` 和空外部配置进行只读 API 彩排：`/health=200`、`/openapi.json=200`、未认证 `/api/rankings/credits=401`；应用日志无数据库或启动错误。测试后容器、数据卷和临时配置全部删除。

## 积分并发验证证据

`scripts/refactor/smoke_credit_concurrency.py` 在一次性 PostgreSQL 16 容器中执行了 100 次竞争扣款、100 次并发增减、20 次相反方向转账以及 40 次未绑定 Plex/Emby 增量。结果为 `tg_1001=112.5`、转账账户合计 `1990.0`、Plex `20.0`、Emby `10.0`；未出现丢失更新、负余额或死锁。容器和数据库在验证后删除；pytest 通过 `CREDITS_TEST_DATABASE_URL` 可重复运行同一检查。

## 积分迁移人工操作审计

已审阅旧 `CreditsRepository.update_user_credits`：代码库和手工运维清单均无调用者，也没有对应的 `app.manage` 操作入口；该方法已删除，不保留兼容 wrapper。后续人工调整积分必须通过经过审计的 credits service/repository delta API，并记录事务所有者。

## 部署回退

B3 起，部署回退必须在维护窗口执行：停止所有 B3 调度器 → 运行 `python -m scripts.refactor.rewrite_job_refs --reverse --scheduler-stopped` → 不启动 B3，直接回退镜像并启动旧版本。脚本会拒绝未知格式、无停止确认或运行中回退，确保 jobstore 记录逐字节可恢复。

## B3 本地部署彩排证据

本轮按维护者批准的“仅本地彩排”范围完成验证，未在 `quince` 上更新镜像或启动 B3 调度器。通过 SSH 加密流从 `quince` 的 `pmsmanagebot` PostgreSQL 导出完整临时副本，导入仅绑定本机端口 `55432` 的 PostgreSQL 18.3 容器；应用使用隔离 `DATA_DIR`、空 Telegram token 和空外部服务配置，未加载生产 `.env`，通知函数在任务观察阶段显式替换为 no-op。验证结束后删除临时容器、匿名卷和数据目录。

记录的非敏感结果：

- 导入生产快照：33 张 public 表；迁移前持久化 jobstore 记录 4 条。
- B3 启动顺序 `register_all → migrate_persisted_jobs → scheduler.start` 成功，日志记录 `Persisted job reference migration: 4 rewritten`。
- 调度器启动并暂停后保留 32 条周期任务及原 4 条一次性任务；4 条均解析为 `app.core.scheduler:run_task` 的 `blackjack.hand_timeout`，任务 ID 未改变。
- API 彩排：`/health`、`/openapi.json` 返回 200，受保护的 `/api/rankings/credits` 在无认证时返回 401。
- 任务观察：临时手牌超时结算从进行中状态转为终态并记录 `outcome=win`；已结算夺宝期 59 自动创建第 63 期，奖项规格保持一致；Telegram 通知在隔离环境中被抑制。

这份证据只证明本地完整生产副本上的部署链路和任务行为；生产维护窗口中的实际部署、真实通知和真实开奖观察仍须由运维人员按回退步骤执行。

## 领域提升模板

`promote-blackjack-domain` 把“把一个领域从过渡门面里提升出来”的做法固化成可复用模板，后续 `promote-*` 变更按同一顺序执行：

1. **冻结表面**：为路由、OpenAPI path、调度任务 ID、公开门面方法与 ORM 表生成确定性快照夹具（`tests/refactor/fixtures/blackjack_surface.json`），并用 AST 清单（`scripts/refactor/blackjack_inventory.py` → `blackjack_inventory.json`）记录门面调用方、`ValueError` 抛出点与副作用位置及其目标角色。
2. **消除反向依赖**：领域间反向读取（luckywheel 消耗 blackjack 配置）改为在下游补齐自洽数据，而不是导入对方模型；本次在 `luckywheel_free_spins` 上落库消耗参数快照。
3. **抽取纯规则与类型化错误**：结算、奖池、赛制校验等计算进入 `rules.py`（零 I/O）；业务拒绝改抛 `DomainError` 子类（`BlackjackError` 同时继承 `ValueError` 以兼容未迁移调用方），路由不再匹配错误字符串。
4. **repository 模块级化**：repository 包对外暴露模块级函数与调用方持有的 `*_tx(session, ...)`；`*_tx` 一律以 `session` 为首参且不得自行 `get_session`/`commit`/`close`，`_tx` 集合与公开导出集合必须双向一致。
5. **工作流进 service**：多步事务编排、提交后的通知/群播报/勋章协调以及调度提交由 `service.py` 承担；jobs/notifications 退化为参数解析与调用适配。
6. **摘除门面**：删除 `DatabaseORM` 上该领域的 mixin 与方法，跨域调用方改用该领域 `service` 或 `*_tx`；随后按冻结来源逐项重封基线 provenance。
7. **交付验证**：接口迁移与快照回归、仓库级失败注入回滚、一次性 PostgreSQL 并发、脱敏生产副本彩排。

三条与代码形态有关的硬约束（`AGENTS.md` 的“Where new code goes”与本文同步）：

- **角色文件变包时按子主题拆**：repository 等角色模块超过 1,000 行或出现多个主题时，拆成同名包，包内按子主题命名（`hands.py`、`tournaments.py`），组合类与模块级包装 API 仍留在 `__init__.py`。逐符号目标登记在 `scripts/refactor/split_plans.toml`，并映射到 `mapping.toml` 的 `planned_target`；`tests/refactor/test_*_repository_split.py` 按登记锁定落点（`verify.py` 只能按包匹配）。
- **搬移与语义改造分开提交**：搬移提交只改文件位置、导入与基线键；语义改造提交不得与搬移混在同一提交里。基线键由 `scripts/refactor/rewrite_baseline_keys.py` 按搬移映射改写（`scripts/refactor/baseline_moves.toml`），校验“条目身份多重集不变”；同一目标的两处导入合并成一条边时用 `[[addition]]`／`[[removal]]` 逐条声明。
- **禁止序号模块**：`src/app/domains/**/repository/part_<数字>.py` 出现即失败（`tests/architecture` 的 `numbered_modules` 类别，只减不增）。现存的 `prediction/repository/part_1.py`、`part_2.py` 由 `promote-activity-domains` 负责清理；21 点与礼包的 repository 包已在本轮拆为子主题模块。

“快照先行、逐项 provenance、一次性容器验证”是三条硬约束：没有快照无法区分行为漂移与重构差异；没有逐项 provenance 无法证明新增基线条目属于旧债；没有一次性容器无法在真实数据形状上验证锁与迁移。

## blackjack 领域边界

- 配置默认值与常量在 `app.domains.blackjack.config`；只读聚合在 `repository/analytics.py`，对外只经 `service.py` 暴露。
- `DatabaseORM` 不含任何 blackjack 方法或 mixin，`BlackjackRepository` 类已删除；调用方使用模块级 repository 函数或 service。
- 领域外调用只允许 `app.domains.blackjack.service`（含 `*_tx` helper）。唯一现存例外是 `badge_awards` 的游戏王勾子里直接读 blackjack 配置与统计，由 `promote-reward-domains` 用提交后领域事件清理。
- repository 内不得出现 Telegram 发送、调度提交或通知模块导入；router 不直接发消息；`app.core.scheduler` 只由 `jobs/cash.py` 导入。静态护栏在 `tests/refactor/test_blackjack_side_effect_boundary.py`。
- 免费次数发放统一走 `luckywheel.repository.grant_free_spins_tx`；扣减与补偿只读发放时落库的 `cost_credits_snapshot`、`wheel_stats_source`。
- 持久化任务名保持 `blackjack.hand_timeout`（`app.core.scheduler:run_task`），超时任务 `misfire_grace_time=None`；启动恢复由 `ON_STARTUP` 的 `restore_blackjack_timeouts` 完成，命名任务先于 API 线程注册。

## blackjack 迁移、回填与彩排证据

- Alembic `c0d1e2f3a4b5`（add immutable free-spin consumption snapshots）在一次性 PostgreSQL 16 上完成 upgrade → downgrade → upgrade 往返，`compare_metadata` 两次 upgrade 后均为空；在脱敏生产副本（PostgreSQL 18.6）上从生产修订 `b9c0d1e2f3a4` 升到 head，1744 条既有免费次数全部回填（41 条 `blackjack → blackjack_free`、1703 条 `gift_pack → gift_pack_free`，`cost_credits_snapshot=0`）。
- 并发：`scripts/refactor/smoke_blackjack_concurrency.py` 在一次性 PostgreSQL 16 容器内用 6 线程做竞争结算（同一手牌停牌/超时竞争 12 次）、12 人抢 5 个名额、6 线程并发结算、并发免费次数发放；只结算一次、名额不超卖、报名费只扣一次、奖金总额等于积分增加额且名次唯一、每手恰好发放一次免费次数，无死锁与负余额。pytest 通过 `BLACKJACK_TEST_DATABASE_URL` 可复跑。
- 生产形态彩排：`scripts/refactor/rehearse_blackjack.py` 对脱敏副本运行，通知与缓存失效置为 no-op，副本内一次性关闭救济/返水/奖池以便精确对账：`/health=200`、`/openapi.json=200`（196 条 path）、未认证 `/api/rankings/credits=401`；`register_all → migrate_persisted_jobs → scheduler.start` 成功，32 条周期任务加命名任务 `blackjack.hand_timeout`／`treasure.open_next_issue` 注册完成，jobstore 迁移 0 条（生产 jobstore 为空）；真实用户手牌结算后积分严格等于 `结算前 − 押注 + 赔付`。本地容器与远程临时 dump 均已删除。
- 回退：本次不改变任务名，故不需要 jobstore 引用回写；回退即回滚镜像并执行 `alembic downgrade b9c0d1e2f3a4`，执行前先停调度器，避免继续写入新快照列。

## 后续变更与领域

| 后续变更 | 负责领域或事项 |
|---|---|
| `make-credit-changes-atomic` | credits 与所有直接写积分的调用方 |
| `promote-gift-pack-domain` | gift_pack；follows blackjack |
| `promote-gift-pack-domain` | gift_pack |
| `unify-business-configuration` | core.config 中业务配置和各领域 config |
| `promote-activity-domains` | luckywheel、treasure、prediction、auction |
| `promote-account-domains` | identity、accounts、invitation 及同步回填 |
| `move-privileged-codes-to-database` | 特权邀请码 |
| `promote-line-domains` | lines、custom_lines、traffic、premium、media_access |
| `move-line-catalog-to-database` | 线路目录 |
| `promote-reward-domains` | badges、badge_awards、watch_rewards 和领域事件 |
| `promote-remaining-domains` | donation、crypto_donation、vaultwarden、rankings、reports、profile |
| `promote-tg-rebind-domain` | tg_rebind、跨域换绑与漏迁修复 |
| `retire-legacy-db-facade` | 门面、遗留任务引用及剩余基线 |
