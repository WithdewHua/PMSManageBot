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
| `rules.py` | 不做 I/O 的纯逻辑，依赖 constants 和 exceptions |
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
- **特权邀请码 `.env` 写入**：礼包领取目前有提交前写配置的明确例外，失败时回滚数据库领取；媒体权限同步仍在提交后进行。`move-privileged-codes-to-database` 将特权码移出 `.env`。
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

B2 过渡基线以 `scripts/refactor/B2_BASE` 中的 B1 提交为来源。B3 机械搬迁以 `scripts/refactor/B3_BASE`（B2 提交 `1b49ea8273253ee7b1b35e13056ca047f9ce45bc`）为冻结来源。`tests/architecture/baseline.json` 当前封存 419 条跨域调用／导入，全部新增条目记录 `b3_source_id`；`scripts/refactor/audit_b3_baseline.py` 只接受冻结源码中的实际来源单元及逐项 `b3_key`，并拒绝仅凭目标领域候选、同名导入换目标或新增领域环封存。B3 为调度器去环及 CLI 组装登记的 AST 差异分别记录 `b3_ast_exception` 和实际存在的行为测试。

按清理责任分组的 B3 封存计数由 `audit_b3_baseline.py` 输出；B3 新增 3 条，当前总数 419 条。B3 新增条目只允许来源于 `db_func.py`、`premium.py`、`modules/custom_line.py`、`utils/report.py` 和 `utils/utils.py` 的冻结单元。

当前 import-linter ignore 数：SQLAlchemy 范围 24、数据库引擎范围 26、模型范围 29、六层领域依赖 67、无环兄弟领域 20、领域内分层 8、入口不碰数据层 83；其余合约 0。B3 去环没有新增 `Acyclic domain siblings` 豁免；任何新增豁免必须有冻结来源单元和行为测试证明。

## 积分账本写入规则

`credits` 是 `statistics.credits`、未绑定 `plex_user.credits` 和未绑定 `emby_user.emby_credits` 的唯一增减入口。新代码不得读取余额后计算绝对值再写回，也不得调用已废弃的 `update_user_credits`；必须使用 credits repository 的 SQL 增量操作。跨领域事务必须传递调用方 session 使用 `*_tx`，不得为积分变更另开 session，以避免丢失更新和行锁死锁。转账按稳定的账户 ID 顺序锁定双方，缓存只在外层事务提交后失效。

`make-credit-changes-atomic` 的初始 AST inventory 保存在 `scripts/refactor/credit_inventory.json`，当前记录 58 个候选写入点（30 个绝对值 facade 调用、15 个属性赋值、1 个增量属性赋值、12 个 `.values()` 写入）。`scripts/refactor/check_credit_migration.py` 与 `credit_migration.toml` 要求每个候选都有事务所有者、缓存键和替代方案；严格模式在任一旧写入未迁移时失败。inventory 是迁移清单，不把 `profile` 响应对象等非持久化候选直接视为数据库写入，须在逐项审阅中标记。

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

## 后续变更与领域

| 后续变更 | 负责领域或事项 |
|---|---|
| `make-credit-changes-atomic` | credits 与所有直接写积分的调用方 |
| `promote-blackjack-domain` | blackjack；转盘免费次数的反向依赖 |
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
