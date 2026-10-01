# 后端架构

本文件是领域边界、数据归属和架构规则的参考资料；日常编码规则与命令见 [AGENTS.md](../AGENTS.md)。

## 分层与依赖方向

```text
main.py（进程入口）
  ↓
api/ · bot/ · schedule.py · model_registry.py（组装）
  ↓
domains/（业务领域）
  ↓
transport/（HTTP、Telegram 管理员投递等边界适配器）
  ↓
integrations/（外部 API 客户端）
  ↓
core/（公共设施）

领域内：router / admin_router / bot / jobs → service → repository / notifications → models
                                   ↘ rules / constants / exceptions / schemas
领域之间：T5 → T4 → T3 → T2 → T1 → T0；同层可依赖但不能成环。
```

`main.py` 仍是 `python -m app.main` 的入口。`api/` 只组装 FastAPI，`bot/` 只组装 Telegram Bot；`schedule.py` 声明任务，`model_registry.py` 显式导入全部模型。`core/` 不导入领域或 integrations；integrations 只导入 core。不保留旧模块的兼容导入路径。

| 领域内角色 | 职责及依赖方向 |
|---|---|
| `router.py` / `admin_router.py` | 用户 / 管理员 HTTP 入口，依赖本领域 service、schemas、exceptions 与 core；来自旧 admin 路由的入口放在 admin_router |
| `bot.py` / `jobs.py` | Bot 命令 / 定时任务入口，依赖本领域 service（jobs 也可依赖 notifications）和 core |
| `service.py` | 用例编排，依赖本领域 repository、rules、notifications，其他领域的 service 和 integrations；外部副作用在事务提交后执行 |
| `notifications.py` | 消息格式化与发送，依赖 rules、constants、integrations.telegram 或 transport.telegram.admin |
| `repository.py` | 唯一的业务 SQLAlchemy 查询和事务位置；对外提供完整事务操作，跨域同事务调用目标领域的 `*_tx(session, …)` |
| `models.py` | 本领域的 ORM 表，依赖 core.db；所有模型经 model_registry 注册 |
| `rules.py` | 不做 I/O 的纯逻辑，依赖 constants、exceptions、本领域 models（仅作类型注解）；由「Domain rules are pure value computations」合约禁止直接导入 `app.core.db`、`sqlalchemy`、repository/service/router/jobs/notifications，需要取数时由 repository 依据 `required_metrics(...)` 预取 |
| `schemas.py` | 领域 Pydantic 请求和响应模型；HTTP 认证用户与通用响应模型属于 `transport.http.schemas` |
| `exceptions.py` / `constants.py` / `config.py` | 领域异常 / 常量 / 类型化业务配置 |

单个角色文件超过 1,000 行时改成同名包，按子主题分文件，包的公开接口保持不变。新数据库操作进入所属领域的 repository。

### Service 接口粒度：按业务用例组织，不复制外域 API

依赖方向约束回答“谁可以调用谁”，不意味着每经过一层都必须增加一个转发方法。领域 service 是该领域的业务接口，不是所有外部能力的镜像门面。

- **跨域协调留在本领域用例内**：入口调用所属领域的 service，由用例按需调用其他领域 service，组织业务校验、数据和结果。例如勋章页面使用 `badges.service.get_badge_center(tg_id)`，兑换使用 `redeem_from_center(tg_id, badge_id)`；不为页面零散取数新增 `badges.get_user_credits`、`badges.get_user_name` 等仅转发外域查询的公开 API。
- **不复制能力归属**：通用余额、身份、会员等能力仍由 credits、identity、premium 提供。其他领域需要它们时，在自己的用例中直接依赖其公开 service；不得层层转发成 `A.service → B.service → C.service`，除非 B 确实承担自己的业务策略、契约转换或稳定的集成边界。
- **允许本领域的简单委托**：`badges.service.get_badge_by_id → badges.repository.get_badge_by_id` 可以是薄方法，它公开的是本领域能力，并隐藏存储边界；不要求每个 service 方法都包含复杂逻辑。
- **按用例聚合，不按页面堆成大方法**：只组合该用例需要且相互关联的数据与操作；不为了减少方法数把无关查询、写入或副作用绑定在一起。不为每个 endpoint 强制新建一个方法，已有语义匹配的领域接口应直接复用。只服务于一个用例的细节优先保留为局部逻辑；多个用例共享的内部步骤可提取私有函数。
- **业务结果与 HTTP 表达分开**：service 返回领域值、明确的用例结果或抛出领域异常；router 负责认证、参数和响应转换、HTTP 状态码，不把业务编排留在 router，也不把 Request、HTTPException 或 transport schemas 下沉到 service。
- **聚合不等于事务**：多个 service 查询依次执行，并不提供一致性快照；若用例要求一致读或原子写，应由所属 repository 明确持有事务，通过其他领域的 `*_tx(session, …)` 协作。网络、通知等副作用仍在提交后执行。

评审新增公开 service 方法时，检查：它是否代表本领域能力或用例？是否只是把外域 API 改名再导出？调用方是否仍在拼装完整业务流程？是否存在无需保留的多层委托？不要仅凭函数行数、方法数量或“一行 return”做机械判定，也不要为消除转发而新增跨层导入豁免。

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
- HTTP 入口通过 `transport.http.auth` 与 `transport.http.schemas` 使用认证/传输模型；领域的 service、repository、rules、types 不得反向依赖 transport。
- 共享词汇例外：`<domain>/types.py` 是纯值类型模块（`credits/types.py` 的 `CreditAccount`、`CreditMutation`、`CreditTransfer`），任何领域的任何角色都可以导入它。纯性由 import-linter 合约“Domain types are pure value modules”强制：types 不得导入本领域的 service/repository/models/config/exceptions，也不得导入 `app.core.db` 或 SQLAlchemy。
- AST 检查（`tests/architecture/checks.py`）把 `types` 与 `service`、`exceptions`、`constants` 并列视为可跨域导入的角色，其余角色仍然登记为基线债务。
- `types.py` 必须无 I/O、无 settings、无领域依赖；例如 `identity.types.get_service_label` 只承载媒体服务显示值。
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

## 已知例外

- **读模型直读跨域表**：T5 的 rankings、reports、profile repository 只能直接执行不包含业务规则的只读聚合，例如对原始列计数、求和、排序、过滤；不得构造领域模型、写入数据或管理业务变更。涉及奖品类别、奖金口径、有效邀请去重、线路分类、Premium 欠额等业务规则时，通过拥有该规则的领域 service 提供的只读分析能力获取数据，再由读模型 service 组织展示。不能因为查询只有读模型调用，就把规则复制到读模型。`tests/architecture/test_read_model_readonly.py` 对写操作、模型构造和属性赋值进行正反例检查。

需要下层通知上层时使用提交后的领域事件，不从下层直接导入上层。`core.events.publish(session, event)` 在成功提交后分发，回滚不分发；已提交且不持有 session 的入口调用 `emit(event)`。组装层使用 `subscribe` 注册同步处理函数，使用 `subscribe_async` 注册异步处理函数。PTB 初始化时通过 `bind_main_loop` 绑定主事件循环：当前线程有循环时创建并保留任务，无循环时提交到绑定循环，CLI 无绑定循环时同步运行异步处理函数。处理失败只记录日志，不影响已提交事务；测试使用 `await events.drain()` 等待保留的任务。同步数据库操作由异步业务处理函数通过 `asyncio.to_thread` 调用，避免阻塞事件循环。

## 手动运维操作

| 操作 | 入口及调用方式 | 保留理由 / 后续责任 |
|---|---|---|
| TG 用户换绑 | `python -m app.manage rebind-tg-id --to <NEW_ID> (--from <OLD_ID> \| --plex-email <EMAIL> \| --emby-username <NAME>) [--dry-run]` | 原子迁移全部领域数据；冲突清单或 21 点在途状态整体拒绝，旧管理员 ID 完成后仍需人工更新部署配置。不同媒体账号冲突、同勋章/礼包/赛事/返水冲突按命令输出逐项处理后重试 |
| 旧版积分同步 | `python -m app.manage legacy-credit-sync` | 保留历史运维顺序：Plex 积分、Plex 用户信息、Emby 积分 |
| 统计报告 | `python -m app.manage report [options]` | 保留历史报告参数和输出 |
| 捐赠倍率重算 | `from app.domains.donation import service; service.update_donation_credits(old_multiplier, new_multiplier)`，仅由维护者在运维 Python 环境显式调用 | 历史捐赠积分的人工调整工具；无日常代码调用方不代表可删除。必须先审查旧/新倍率与目标数据库，并遵循积分领域事务接口 |
| 过期下载权限清单 | `scripts/list_expired_download_holders.py`；默认只读，确认名单后用 `--apply --input <json>` 仅撤销名单项 | `scripts/sync_download_permissions.py` 是单向同步脚本，不能用于对账或撤销，也不得代替本清单脚本 |
| 历史流量月度迁移 | `scripts/migrate_line_traffic_stats.py` | 历史月度流量数据批量聚合与清理工具；调用 `app.domains.traffic.service` 聚合与清理接口，支持按月范围或自动检测最早月份逐月确认/批量处理 |
| Redis 配置历史迁移 | `scripts/migrate_redis_to_database.py` | 历史 Redis 配置（免费高级线路、线路标签、大转盘配置）向数据库单向迁移工具；调用 `app.domains.lines.catalog` 和 `app.domains.luckywheel.service` 接口 |

## Core 与 transport 边界

- `core/` 只保留公共机制：配置、数据库会话、缓存机制、HTTP session、日志、调度器、KV 与纯字节格式化；不放 HTTP 认证、Telegram 客户端、通用 API schemas 或业务缓存实例。
- `transport/http/` 负责 HTTP middleware、DomainError adapter、认证依赖和通用 `TelegramUser`/`BaseResponse`；认证纯校验位于 `integrations.telegram.init_data`，接收显式 token、有效期和当前时间，不读取 settings。
- `integrations/telegram/` 按 profile cache、profile client、messaging 拆分；`transport/telegram/admin.py` 只负责按部署管理员列表顺序投递，不包含业务条件。
- 各领域的 Redis 实例和失效函数由领域 `cache.py` 拥有，`core.cache` 仅提供 Redis/Lua 通用机制。
- `core.system`、`core.singleton`、`core.formatting`、`core.number`、`core.auth`、`core.schemas`、`core.telegram` 已删除，不保留转发 shim。

## 配置分类

- **基础设施与密钥**：系统环境 / `data/.env`，由 core.config 只读加载（如 Telegram token、数据库 URL、外部服务地址）。不在业务事务内更新。
- **运行时业务配置与数据**：使用各领域带类型的 `DomainConfig`，持久化于 core.kv 的 `SystemConfig` 键值表；线路目录存放在 `line_catalog` 数据库表。运行时业务数据一律存在数据库，`.env` 只存放只读的部署配置。

### 业务配置归属（D1）

| 领域 | 配置项 |
|---|---|
| `accounts` | `plex_register`、`emby_register` |
| `invitation` | `invitation_credits` |
| `premium` | `premium_unlock_enabled`、`premium_daily_credits`、`credits_cost_per_10gb` |
| `donation` | `donation_multiplier` |
| `crypto_donation` | `upay_crypto_types` |
| `lines` | `premium_free`、`line_schedule_unlock_credits` |
| `traffic` | `user_traffic_limit`、`premium_user_traffic_limit` |
| `media_access` | `unlock_credits`、`download_unlock_credits`、`nsfw_libs` |
| `vaultwarden` | `enabled`、`redeem_credits` |
| `credits` | `transfer_enabled` |
| `luckywheel` / `blackjack` / `badges` | Existing domain-owned configuration documents and rows |
- **已迁移的遗留配置**：特权邀请码存储于 `invitation.is_privileged`，线路目录存储于 `line_catalog`。升级启动仅一次读取旧配置导入数据库；导入完成后残留 `.env` 键不再控制业务。礼包不再有提交前写 `.env` 的例外。

## 积分账本写入规则

`credits` 是 `statistics.credits`、未绑定 `plex_user.credits` 和未绑定 `emby_user.emby_credits` 的唯一增减入口。每个 delta 在锁定当前行后先按既有 Python 两位小数规则计算有效增量，再以 `column + effective_delta` 的 SQL 表达式写回，避免返回值与持久化值不一致。新代码不得读取余额后计算绝对值再写回，也不得调用已废弃的 `update_user_credits`；必须使用 credits repository 的 SQL 增量操作。跨领域事务必须传递调用方 session 使用 `*_tx`，不得为积分变更另开 session，以避免丢失更新和行锁死锁。转账按稳定的账户 ID 顺序锁定双方，缓存只在外层事务提交后失效。

绑定 Plex/Emby 与余额转移现在由 accounts repository 在同一事务中完成；如果目标统计行、绑定写入或积分转移任一步失败，账户绑定和余额均回滚。捐赠倍率重算也在一个事务中处理全部用户，后续用户余额不足时不会留下前面用户的部分更新。转账费率额外拒绝负数和非有限值。

## 部署回退与任务引用迁移

从旧版本升级时，如果数据库中存在旧格式的持久化任务引用，先在维护窗口停止应用与调度器，再运行独立迁移脚本：

```bash
python -m scripts.migrate_legacy_job_refs
```

迁移完成后再启动应用。应用在 `scheduler.start()` 前会只读检查 jobstore；发现未迁移且无法解析的旧引用时，会记录迁移命令并以非 0 状态退出，避免 APScheduler 静默删除任务记录。表不存在或记录已经是具名任务格式时检查通过。

如需回退到旧版本镜像：

1. 停止所有运行中的应用与调度器实例。
2. 执行逐字节反向恢复，并显式确认调度器已停止：
   ```bash
   python -m scripts.migrate_legacy_job_refs --reverse --scheduler-stopped
   ```
3. 启动旧版本镜像。

## accounts / identity / invitation 提升证据

`promote-account-domains` 已将 `identity` 的 SQL 查询和事务写入收拢到模块级 `repository`，由 `identity.service` 暴露类型化数据类。Plex、Emby、Statistics 和 Overseerr 的建档统一经过 `identity.repository.ensure_statistics_tx`（需要 Telegram 统计行时），缓存写入登记在事务提交后的 callback 中。

本次已核对并删除四个无调用方入口：`IdentityRepository.get_plex_info_by_plex_username`、`IdentityRepository.get_emby_info_by_emby_id`、`IdentityRepository.update_user_tg_id` 和 `accounts.service.add_all_plex_user`；它们不在手动运维清单中。

账号绑定和凭码注册由 `accounts.service` / `invitation.service` 编排，写入由各自 repository 在调用方事务中完成。`PlexUserIdResolved` 通过 `app.core.events` 在提交后分发，由 `app.subscriptions` 注册 invitation handler；具名任务 `invitation.resolve_plex_id` 在内存 jobstore 使用 interval + `end_date`，任务成功后自行删除。

账号绑定和凭码注册由 `accounts.service` / `invitation.service` 编排，写入由各自 repository 在调用方事务中完成。`PlexUserIdResolved` 通过 `app.core.events` 在提交后分发，由 `app.subscriptions` 注册 invitation handler；具名任务 `invitation.resolve_plex_id` 在内存 jobstore 使用 interval + `end_date`，任务成功后自行删除。

## 领域提升模板

`promote-blackjack-domain` 把领域提升的做法固化成可复用模板，后续变更按同一顺序执行：

1. **冻结表面**：为路由、OpenAPI path、调度任务 ID、公开 repository/service 导出与 ORM 表生成确定性快照夹具，并用 AST 清单记录 `ValueError` 抛出点与副作用位置及其目标角色。
2. **消除反向依赖**：领域间反向读取（luckywheel 消耗 blackjack 配置）改为在下游补齐自洽数据，而不是导入对方模型；本次在 `luckywheel_free_spins` 上落库消耗参数快照。
3. **抽取纯规则与类型化错误**：结算、奖池、赛制校验等计算进入 `rules.py`（零 I/O）；业务拒绝改抛 `DomainError` 子类（`BlackjackError` 同时继承 `ValueError` 以兼容未迁移调用方），路由不再匹配错误字符串。
4. **repository 模块级化**：repository 包对外暴露模块级函数与调用方持有的 `*_tx(session, ...)`；`*_tx` 一律以 `session` 为首参且不得自行 `get_session`/`commit`/`close`，`_tx` 集合与公开导出集合必须双向一致。
5. **工作流进 service**：多步事务编排、提交后的通知/群播报/勋章协调以及调度提交由 `service.py` 承担；jobs/notifications 退化为参数解析与调用适配。
6. **移除旧实现**：删除该领域旧的模块级实现，跨域调用方改用该领域 `service` 或 `*_tx`。
7. **交付验证**：接口迁移与快照回归、仓库级失败注入回滚、一次性 PostgreSQL 并发、脱敏生产副本彩排。

三条与代码形态有关的硬约束（`AGENTS.md` 的“Where new code goes”与本文同步）：

- **角色文件变包时按子主题拆**：repository 等角色模块超过 1,000 行或出现多个主题时，拆成同名包，包内按子主题命名（`hands.py`、`tournaments.py`），模块级包装 API 仍留在 `__init__.py`。
- **搬移与语义改造分开提交**：文件位置调整提交与业务语义改造提交分开，避免重构与行为变化混杂。
- **禁止序号模块**：`src/app/domains/**/repository/part_<数字>.py` 出现即失败（`tests/architecture` 的 `numbered_modules` 类别，只减不增）。现存模块已全部拆为子主题包。

“快照先行、逐项 provenance、一次性容器验证”是三条硬约束：没有快照无法区分行为漂移与重构差异；没有逐项 provenance 无法证明新增基线条目属于旧债；没有一次性容器无法在真实数据形状上验证锁与迁移。

## blackjack 领域边界

- 配置默认值与常量在 `app.domains.blackjack.config`；只读聚合在 `repository/analytics.py`，对外只经 `service.py` 暴露。
- Blackjack 领域不暴露门面 mixin，调用方使用模块级 repository 函数或 service。
- 领域外调用只允许 `app.domains.blackjack.service`（含 `*_tx` helper）。
- repository 内不得出现 Telegram 发送、调度提交或通知模块导入；router 不直接发消息；`app.core.scheduler` 只由 `jobs/cash.py` 导入。
- 免费次数发放统一走 `luckywheel.repository.grant_free_spins_tx`；扣减与补偿只读发放时落库的 `cost_credits_snapshot`、`wheel_stats_source`。
- 持久化任务名保持 `blackjack.hand_timeout`（`app.core.scheduler:run_task`），超时任务 `misfire_grace_time=None`；启动恢复由 `ON_STARTUP` 的 `restore_blackjack_timeouts` 完成，命名任务先于 API 线程注册。

## blackjack 迁移、回填与彩排证据

- Alembic `c0d1e2f3a4b5`（add immutable free-spin consumption snapshots）在一次性 PostgreSQL 16 上完成 upgrade → downgrade → upgrade 往返，`compare_metadata` 两次 upgrade 后均为空；在脱敏生产副本（PostgreSQL 18.6）上从生产修订 `b9c0d1e2f3a4` 升到 head，1744 条既有免费次数全部回填（41 条 `blackjack → blackjack_free`、1703 条 `gift_pack → gift_pack_free`，`cost_credits_snapshot=0`）。
- 并发：在一次性 PostgreSQL 16 容器内用 6 线程做竞争结算（同一手牌停牌/超时竞争 12 次）、12 人抢 5 个名额、6 线程并发结算、并发免费次数发放；只结算一次、名额不超卖、报名费只扣一次、奖金总额等于积分增加额且名次唯一、每手恰好发放一次免费次数，无死锁与负余额。
- 生产形态彩排：对脱敏副本运行，通知与缓存失效置为 no-op，副本内一次性关闭救济/返水/奖池以便精确对账：`/health=200`、`/openapi.json=200`（196 条 path）、未认证 `/api/rankings/credits=401`；`register_all → migrate_persisted_jobs → scheduler.start` 成功，32 条周期任务加命名任务 `blackjack.hand_timeout`／`treasure.open_next_issue` 注册完成，jobstore 迁移 0 条（生产 jobstore 为空）；真实用户手牌结算后积分严格等于 `结算前 − 押注 + 赔付`。本地容器与远程临时 dump 均已删除。
- 回退：本次不改变任务名，故不需要 jobstore 引用回写；回退即回滚镜像并执行 `alembic downgrade b9c0d1e2f3a4`，执行前先停调度器，避免继续写入新快照列。

## gift_pack 领域边界

- 纯计算全部在 `app.domains.gift_pack.rules`：奖励登记表与文案、条件解析（旧格式与新格式两套合并为一）、生命周期与 `phase_ref`、余量、受众规模、自动补绑定条件、开始后编辑校验，以及 `required_metrics` / `evaluate`（求值只读预取好的计数，窗口未开始时按 0 计，不产生查询）。规则模块由 import-linter「Domain rules are pure value computations」守住，只允许为类型注解导入本领域模型。
- repository 拆成五个子主题模块：`conditions.py`、`rewards.py`、`packs.py`、`claims.py`、`notices.py`。`repository/__init__.py` 暴露模块级函数，不暴露门面 mixin。
- 领取事务固定加锁顺序：锁礼包行 → 锁领取状态行 → 按 `required_metrics` 预取计数 → 纯计算求值 → 依 `statistics` → `plex_user` → `emby_user` 预锁本次要写的行（`_prelock_gift_pack_reward_rows_tx`）→ 按礼包 JSON 顺序发放 → 计数与领取状态 → 特权码持久化放在最后 → 提交。奖励顺序因此不会造成 ABBA 死锁。
- 跨域写入一律经目标领域的 `*_tx`：积分 `credits.repository.add_tx`（提交后缓存失效已由该 helper 自行登记）、转盘次数 `luckywheel.repository.grant_free_spins_tx`、会员天数 `premium.repository.grant_premium_days_tx`、争霸赛余额 `blackjack.repository.credit_tournament_wallet_tx`、线路调度解锁 `lines.repository.unlock_line_schedule_tx`、下载解锁 `media_access.repository.unlock_download_tx`、邀请码与特权码 `invitation.repository.issue_codes_tx` / `persist_privileged_codes_tx`；条件计数委托各领域的 `count_*_tx`。礼包代码不再导入外域 models。
- 提交后的副作用由 `service.py` 执行，顺序为：积分缓存失效（已登记在 session 上）、媒体权限同步、通知。`notifications.py` 不读数据，文案所需的礼包标题由 service 传入；`_notify_detached` 同时支持事件循环线程（直接建任务）与线程池（`run_coroutine_threadsafe` 提交到主循环），无事件循环时退化为 `asyncio.run`。
- 错误契约：`gift_pack/exceptions.py` 提供 `GiftPackError(DomainError, ValueError)` 与携带逐项进度的 `ConditionsNotMet`；router 只读结构化状态码与 `payload["detail"]`，不做子串匹配。

## gift_pack 迁移、验证与彩排证据

- 一次性 PostgreSQL 16 并发验证：验证最后一份不超发、同一用户并发只成功一次，并复现「领取与线路解锁加锁顺序相反」的 ABBA 死锁；固定加锁顺序后该场景稳定通过。
- 元数据：`scripts/verify/check_metadata_pg.py` 比较元数据无新增表或列差异。
- 生产形态彩排：在 quince 生产库的本地副本（PostgreSQL 18）上领取含全部奖励类型的礼包，通知与媒体同步置为 no-op 并记录调用参数：`ok=true`、3 轮全部检查通过——逐项发放快照与持久化的 `GiftPackUserState.reward_snapshot` 一致、`claimed_count` 自增、积分与争霸赛余额按金额增加、邀请码落库、线路/下载解锁标记写入、Premium 到期时间延长、免费次数入账、积分缓存失效已登记、下载与权限同步的 `(tg_id, service)` 参数与固定顺序一致、无特权码写入、售罄通知恰好派发一次、日志无异常。副本与临时 dump 已删除，生产容器未重启。
- 彩排发现的真实缺陷（已修）：`blackjack.repository.credit_tournament_wallet_tx` 曾用 `round(double precision, integer)` 写争霸赛余额，PostgreSQL 没有该重载（`UndefinedFunction`），而 SQLite 的宽松 `round` 让单测全绿。现改为 `round(CAST(col + delta AS NUMERIC), 2)`，并加回归守卫 `tests/test_blackjack_wallet.py::test_wallet_update_compiles_to_a_numeric_round_on_postgresql`（按 PostgreSQL 方言编译 SQL 断言必须出现 `ROUND(CAST(... AS NUMERIC)`）。
- 回退：本轮无 schema 变更，回退即回滚镜像；领取的加锁顺序改动只影响并发路径，不改变对外响应。

### 剩余领域提升边界

`donation`、`crypto_donation`、`rankings`、`reports` 的操作通过领域 service 和模块级 repository 实现。`profile` 的个人信息/转账收件人列表通过只读 repository 与所属领域的 service 组合，积分转账请求/响应模型归属 `credits.schemas`，缓存重写任务的查询也归属 credits repository。TG 换绑已迁移到 `python -m app.manage rebind-tg-id`。

#### 剩余领域提升验证记录

- 在一次性本地 PostgreSQL 生产副本上验证：44 项排行、统计、个人信息、Bot 与周报对比全部一致；固定时钟与外部服务替身，使用 FastAPI 的 `jsonable_encoder` 比较实际响应类型。
- 彩排只接受本机指定端口、`pms_test_remaining_compare_` 前缀数据库，禁止连接参数覆盖目标，强制只读；逐表指纹验证运行前后数据不变。真实用户 ID 在运行时从本地副本选择，不写入脚本。原始差异报告保留在本地临时目录；已修复转盘/夺宝字段命名、观看/邀请榜多余标识字段和周报任务返回值偏差。
- `tests/test_remaining_postgres.py` 在独立 schema 中以 8 路并发验证捐赠审批和支付回调均只入账一次。捐赠批准事件由 service 在成功提交后发出，拒绝、回滚与 Bot 人工录入路径不发出该事件。
- 清除剩余领域 52 条及 credits 14 条架构遗留。
- 审查发现订单列表查询残留 `self` 导致参数错位，已修复并增加跨用户隔离、状态分页和模块级函数签名检查。所有公共路由顺序、OpenAPI、Bot 注册和调度入口保持冻结。
