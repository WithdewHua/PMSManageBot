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

B2 过渡基线以 `scripts/refactor/B2_BASE` 中的 B1 提交为来源。`tests/architecture/baseline.json` 当前封存 323 条跨域调用／导入、4 个仅存于旧路径的超预算文件；其中 271 条因接口机械搬迁才进入领域扫描范围，逐条记录 `b2_source_id`。`scripts/refactor/audit_b2_baseline.py` 将每个新增条目映射到 B1 源码单元并校验规范化 AST，拒绝无法溯源的调用、新增超预算文件和未经来源证明的 import-linter 豁免；`tests/architecture/test_b2_provenance.py` 在提交前和后续 hook 中持续执行此审计。

按清理责任分组的 323 条跨域条目：`promote-line-domains` 159、`promote-remaining-domains` 49、`promote-account-domains` 48、`promote-gift-pack-domain` 18、`make-credit-changes-atomic` 15、`promote-tg-rebind-domain` 15、`promote-activity-domains` 12、`promote-blackjack-domain` 4、`promote-reward-domains` 3。

B2 import-linter ignore 数：SQLAlchemy 范围 15、数据库引擎范围 17、模型范围 26、六层领域依赖 81、无环兄弟领域 20、领域内分层 7、入口不碰数据层 72；其余合约 0。新增豁免按精确导入边标有负责后续变更的注释，门面导入者按模块精确列出。B2 提交后基线严格只减不增：修复违规时须在同一提交删除对应豁免并下调封存数。B3 对剩余旧路径再次复核，封存最终基线。

## 部署回退

B3 起，部署回退时须先运行 `python -m scripts.refactor.rewrite_job_refs --reverse`，再回退镜像，否则持久化任务可能丢失。该脚本在 B3 中创建，此前不存在。

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
