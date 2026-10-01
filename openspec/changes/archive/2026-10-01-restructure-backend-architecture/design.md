# Design

## Context

动机见 proposal.md 的 Why。这里只列会影响做法的现状和约束。

- **`db` 门面的调用面很大**：687 处 `db.<method>()`，覆盖 216 个方法。测试直接对 `db` 实例和路由模块打 monkeypatch（`setattr(orm, …)` 12 处，`setattr(router, …)` 28 处）。任何改变调用方式的方案，都要同时改动这些地方。
- **`DatabaseORM` 适合拆成 mixin**：
  - 314 个方法里没有 async，没有 `super()`，也没有实例状态。唯一的实例属性属于要删除的 `_CurWrapper`。
  - 类里有 4 处 `DatabaseORM.<name>` 自引用，都出现在同一领域的 staticmethod 里（勋章 1 处，礼包 3 处）。
  - 类属性里有 21 点和礼包的常量。模块级还有 `DEFAULT_BLACKJACK_CONFIG`、`GIFT_PACK_REWARD_TYPES` 等常量，以及两个礼包辅助函数。
- **单进程运行**：bot 和调度器跑在同一个 asyncio 循环里。uvicorn 在子线程中以字符串目标 `"app.webapp:app"` 启动（`main.py:97`）。整个进程只有一个 SQLAlchemy engine。
- **调度器有两个 jobstore**：
  - `main.py` 注册的 32 个任务都放在内存 jobstore 里，每次启动用 `replace_existing=True` 重新注册。
  - 持久化 jobstore 只存两类一次性任务，记录里保存的是函数路径：
    - 21 点手牌超时：`app.webapp.routers.activities.blackjack:_settle_blackjack_hand_on_timeout`，锦标赛也复用它。
    - 夺宝自动开下一期：`app.webapp.routers.activities.treasure:_auto_create_next_treasure_issue_from`。
  - 竞拍结束任务放在内存 jobstore，启动时由 `restore_auction_schedules()` 重建。21 点超时也有 `restore_blackjack_timeouts()` 和一个兜底扫描任务。夺宝自动开期没有这类补救。
- **有不少隐式依赖**：
  - 95 处函数内的 `from app…` 导入，分布为 admin.py 27 处、db.py 15 处、prediction.py 11 处、main.py 8 处等。大多是为了绕开循环导入。静态检查看不到它们，执行到才会报错。
  - 字符串形式的路径也属于这一类：uvicorn 目标、测试里的 `patch("app.premium…")`、持久化任务的函数路径。
- **模型可以安全拆分**：31 个模型中，6 对 `relationship` 都在同一领域内。跨表外键都写成字符串，比如 `ForeignKey("statistics.tg_id")`。拆成多个文件后，只要求在配置 mapper 之前导入全部模型。
- **Bot 注册**：`main.py` 依次遍历 `rank`、`start`、`status`、`user` 四个模块，注册所有名字以 `_handler` 结尾的对象。
- **自动检查**：CI 只构建 Docker 镜像，不跑测试和 lint。pre-commit 是唯一的自动关口，所以架构检查必须快，并且要接进 pre-commit。
- **领域划分做过验证**：用 AST 统计了每个函数里的三类引用：`db.<method>` / `self.<method>` 调用、模型和列的引用、跨模块的函数调用。然后按 D2 的领域表归属，算出领域之间的依赖。做两处调整后，repository、service 和通知这几层之间的领域依赖没有环：
  - 把按用户存储的宽表单独拆成 `identity`。
  - 把少数函数挪到正确的领域。

  剩下的环都出在入口层（路由和任务），一共三处，见 D3。

## Goals / Non-Goals

**Goals：**

- 每段后端代码的位置由"领域 + 角色"唯一确定。人和 agent 不用搜索就能找到代码，也知道新代码该放哪里。
- 搬迁没有改变行为这一点可以用工具证明。搬迁过程可以在最新主干上重跑。
- 架构边界从第一天起就由机器检查。现存违规记入基线，基线只减不增。
- 搬迁完成后，后续每个 `promote-*` 变更的改动都集中在一个或一组领域，再加上它们在其他领域的调用点。

**Non-Goals：**

- 不重命名函数、类、常量，也不改签名。调用方式和导入风格保持不变：`db.xxx()` 保留，已有的按名导入也保留。
- 不拆宽表，不改表结构，也不改 Redis 键。
- B2 冻结提交中已存在的跨层调用和依赖环只登记并交给后续变更；B3 搬迁新增的依赖环不是现存债务，须在本变更内消除，不得列入 `Acyclic domain siblings` 的 ignore。去环仅限导致新增环的调用面，不顺带重构其他业务。
- 不引入运行时依赖。import-linter 只加进 test extra。

## Decisions

### D1 目录结构：按领域分包，领域内按角色分文件

```
src/app/
  main.py             process entry: init db, build bot, start api thread, start scheduler
  manage.py           manual operational CLI assembly: legacy sync, reports, TG rebind
  schedule.py         declarative job table: recurring jobs, named tasks, startup hooks
  model_registry.py   imports every models module; exposes metadata and init_db()
  core/               shared kernel, no business rules
  integrations/       external API clients, no database access
  api/                FastAPI assembly: app, middlewares, lifespan, static files
  bot/                Telegram assembly: handler list, command menu, /start
  domains/<name>/     business code, one package per domain (D2)
  databases/db.py     transitional facade: composes repository mixins, exposes `db`
```

领域内的文件如下，只建用得到的：

| 文件 | 放什么 | 可以依赖 |
|---|---|---|
| `router.py` / `admin_router.py` | 用户接口 / 管理员接口。来自 `admin.py` 的接口放进 `admin_router.py` | 本领域 service、schemas、exceptions；core |
| `bot.py` | Telegram 命令处理函数和 `*_handler` 对象 | 本领域 service；core |
| `jobs.py` | 调度器调用的入口函数 | 本领域 service、notifications；core |
| `service.py` | 用例编排：调用 repository，提交后执行副作用 | 本领域 repository、rules、notifications；其他领域的 service；integrations |
| `notifications.py` | 消息的格式化和发送 | rules、constants；core.telegram |
| `repository.py` | 本领域全部 SQLAlchemy 代码。每个公开函数是一个完整事务；`*_tx(session, …)` 供其他领域在同一事务内调用 | 本领域 models、rules；其他领域的 `*_tx`；core.db |
| `models.py` | 本领域的表 | core.db |
| `rules.py` | 纯计算，不做 I/O | constants、exceptions |
| `schemas.py` | Pydantic 请求/响应模型 | constants；core.schemas |
| `exceptions.py` / `constants.py` / `config.py` | 领域异常 / 枚举和常量 / 带类型的业务配置（C 阶段启用） | — |

B 阶段的过渡状态：入口和 service 仍通过 `db` 门面访问数据，repository 还是 mixin（D4）。表中的依赖方向从 A 阶段起就由 import-linter 检查（D10）。

几条配套约定：

- **角色文件太大时改成包**：角色文件超过 1,000 行，就改成同名的包，比如 `repository/`。包内按子主题分文件，对外暴露的名字不变。21 点和礼包的 repository 在 B 阶段直接按 db.py 现有的分节拆成包；21 点的路由也在 B 阶段拆成包，见 D6。
- **不保留兼容路径**：除 `app/databases/db.py` 外，旧模块全部删除，引用处由工具改写，不留转发模块。如果同一个东西能从两个路径导入，人和 agent 都会困惑该用哪个。门面是唯一例外，因为它有 687 处调用。

备选方案：

- **按层分目录**（`routers/`、`services/`、`repositories/`）：改一个功能要跨四个目录，和现状差别不大。
- **保留 `webapp/`，只拆 db.py**：解决不了路由里写业务编排、定时任务散落各处的问题。

### D2 领域划分与层级

领域分成六层。上层可以依赖下层；同层之间可以依赖，但不能成环。

| 层 | 领域 | 负责 |
|---|---|---|
| T5 读模型 | `rankings` | 所有排行榜查询，包括 bot 的排行命令 |
| | `reports` | 系统统计、周报、服务器状态、后台设置总览 |
| | `profile` | 用户信息总览（`/api/user/info`、`/info`） |
| T4 跨域策略 | `watch_rewards` | 按观看时长结算积分、幽灵会话补偿、会员流量扣费 |
| | `gift_pack` | 礼包的定义、领取条件、奖励和领取 |
| | `badge_awards` | 自动颁发勋章（游戏王、至尊贡献者） |
| | `tg_rebind` | TG 换绑：把媒体账号和名下数据从旧 TG ID 迁到新 TG ID，新 ID 已有数据时合并。由管理员手动执行 |
| T3 业务功能 | `accounts` | 媒体账号的绑定和解绑、注册开关、账号信息同步、Overseerr 账号 |
| | `invitation` | 邀请码的生成和兑换（包括凭码注册）、特权码 |
| | `premium` | 会员的开通和到期、会员线路、会员流量 |
| | `custom_lines` | 用户自建线路的申请、审核、上下线和流量结算 |
| | `donation` / `crypto_donation` | 捐赠登记和确认 / UPay 加密货币订单 |
| | `luckywheel` | 幸运大转盘，以及所有来源的免费次数账本 |
| | `treasure` / `prediction` / `auction` | 夺宝奇兵 / 大预言家 / 竞拍 |
| | `blackjack` | 21 点的牌局、奖池、留存和返水，以及锦标赛 |
| T2 共享能力 | `badges` | 勋章的定义、发放、兑换和加成查询 |
| | `lines` | 线路目录、线路绑定、线路调度、网关用户缓存 |
| | `traffic` | 流量记录、按日和按月聚合、流量上限 |
| | `media_access` | NSFW/全库和下载/同步权限的解锁，以及媒体服务器权限同步 |
| | `vaultwarden` | Vaultwarden 账号兑换 |
| T1 账本 | `credits` | 积分余额的查询、增减、转账，以及积分缓存 |
| T0 基础 | `identity` | 按用户存储的宽表（`statistics`、`plex_user`、`emby_user`、`overseerr`），以及按键查询和建档 |

几处划分的理由：

- **`identity` 单独成层**：宽表上的列分属多个领域（见 D3）。如果宽表的模型放在 `accounts`，就会出现这样的环：`credits` 要写 `plex_user.credits`，所以依赖 `accounts`；绑定账号时要合并积分，所以 `accounts` 又依赖 `credits`。把表和按键查询放在最底层以后，`accounts` 只保留账号生命周期的流程，放在 `credits` 之上。
- **`blackjack` 包括锦标赛**：两者互相调用 16 次，而且共用 `blackjack_hand` 表。分成两个领域只会多出一个环。
- **凭邀请码注册归 `invitation`**：它依赖 `accounts` 的建号和同步。这样做能保持原有 URL 前缀（`/api/invite/redeem/*`），也符合用户的认知："在邀请页兑换"。
- **T4 负责协调多个领域的业务操作**：T4 领域可以没有自己的表，比如 `badge_awards` 和 `tg_rebind`，它们通过下层领域的 service 或 `*_tx` 读写数据。跨领域编排在常见分层里属于"应用层"，本项目由 T4 承担，不再另设应用层目录，免得每写一个跨领域功能都要先判断放哪边。
- **TG 换绑单独成域，放在 T4**：换绑会改写 13 个领域的表，其中包括 `invitation`，而 `invitation` 依赖 `accounts`，所以它只能放在这些领域之上。
  - 目标形态是显式编排，由 `promote-tg-rebind-domain` 完成：
    - 各领域在自己的 repository 里提供 `reassign_tg_id_tx`，处理本领域的表和合并冲突。
    - `tg_rebind` 在一个事务里按固定顺序调用它们。
    - 架构测试保证每个存 TG ID 的列都被覆盖。

    这和 Discourse 的用户合并（`UserMerger`）是同一类做法。
  - 备选方案一：放进 `accounts`，由各领域把处理函数注册给它。这样能避开环，但要引入一套注册机制，改了哪些表也要到各个注册点拼起来看。
  - 备选方案二：放进 `identity`。最底层会依赖几乎所有领域。
  - 备选方案三：另设应用层目录，专门放跨领域用例。它和 T4 职责重叠，还要为"只有 repository 开事务"开例外。
- **读模型层可以直接读其他领域的表**：排行榜和统计需要连表查询，改成逐个调用各领域的 service 既慢又别扭。所以这一层是登记在案的例外，但只能读，不能写。凡是只被读模型使用的查询（比如各种 `get_*_rank`），都放在读模型领域。被多个领域共用的计数查询，留在数据所属的领域。
- **`SystemConfig` 归 `core/kv.py`**：它是通用的键值表，存放着多个领域的配置和任务游标，不属于任何一个业务领域。C 阶段的 `DomainConfig` 也建在它上面。

### D3 宽表的列归属，以及已知的环

宽表的模型在 `identity`，所有领域都可以读。写入只能由列组的所属领域在自己的 repository 里完成；其他领域要写，调用所属领域的 `*_tx`。以后新增的按用户状态，都建在本领域自己的表里（以 `tg_id` 为键），不再往宽表上加列。

| 表 | 列组 | 写入方 |
|---|---|---|
| `statistics` | `tg_id` | identity |
| | `credits` | credits |
| | `donation` | donation |
| | `tournament_wallet_credits`、`blackjack_lose_streak`、`blackjack_hands_since_freespin` | blackjack |
| `plex_user` / `emby_user` | 主键、`tg_id`、用户名、邮箱、`last_viewed_at` | identity（由 accounts、tg_rebind 调用） |
| | `credits` / `emby_credits`（尚未绑定 TG 时的积分） | credits |
| | `watched_time` / `emby_watched_time` | watch_rewards |
| | `all_lib`、`unlock_time` / `emby_is_unlock`、`emby_unlock_time`（NSFW）；`sync_unlocked`、`sync_unlock_time` / `download_unlocked`、`download_unlock_time` | media_access |
| | `plex_line` / `emby_line`、`line_schedule_unlocked`、`line_schedule_unlock_time` | lines |
| | `is_premium`、`premium_expiry_time`、`premium_status_updated_at`、`premium_traffic_debt_bytes`、`premium_traffic_debt_updated_date` | premium |
| `overseerr` | 全部 | identity |

列归属本变更不做机器检查，只写进 `docs/architecture.md`，在 review 时对照。

入口层还剩三处环，B 阶段原样保留，记入基线：

1. **勋章触发**：21 点、转盘、预言、夺宝、捐赠、加密货币捐赠会在操作后立即调用 `check_and_award_game_king_badge` / `check_and_award_supreme_contributor_badge`；而 `badge_awards` 又要读这些领域的数据。解法是让下层领域在提交后发出领域事件，由 `badge_awards` 订阅，处理函数在组装层注册。负责的变更：`promote-reward-domains`。
2. **账号同步和凭码注册**：`accounts` 的同步任务 `update_plex_info` 会顺带回填邀请记录的 `plex_id`；而 `invitation` 的兑换流程又调用这个同步函数。解法是把回填挪进 `invitation` 自己的步骤。负责的变更：`promote-account-domains`。
3. **转盘免费次数**：免费次数账本归 `luckywheel`，21 点通过它发放免费次数。但消耗 21 点来源的免费次数时，`luckywheel` 要读 21 点的配置。解法是在发放时把需要的参数存到账本行上，就像 21 点已经把配置快照存到手牌行上一样。负责的变更：`promote-blackjack-domain`。

需要"下层通知上层"时，统一用领域事件，而不是在下层直接调用上层。这条规则从 C 阶段开始执行，事件机制的具体形式见 Open Questions。

### D4 `DatabaseORM` 拆成各领域的 repository mixin，加一个过渡门面

```python
# app/domains/blackjack/repository/__init__.py
class BlackjackRepository(
    HandsRepository, JackpotRepository, RetentionRepository, TournamentRepository
):
    """Blackjack data access. Transitional mixin; composed by app.databases.db."""


# app/databases/db.py  -- transitional facade, add nothing here
class DatabaseORM(IdentityRepository, CreditsRepository, ..., SystemConfigRepository):
    """Removed by retire-legacy-db-facade."""


db = DatabaseORM()
```

- **方法原样搬走**：每个方法连同装饰器、前导注释和类属性常量，原样搬进所属领域的 `<Domain>Repository` 类。领域内再分文件时，由包的 `__init__` 组合子类。
- **mixin 的约束**：mixin 没有 `__init__`，也没有状态，所以 MRO 顺序无关紧要。由测试保证 mixin 之间没有重名。
- **跨领域调用照旧**：跨领域的 `self.xxx()` 调用经由组合后的类照常解析，行为不变。
- **自引用改写**：4 处 `DatabaseORM.<name>` 改成所在 mixin 的类名。它们都在同一个模块里，工具会确认这一点，不满足就报错。
- **B1 的 Premium 依赖桥接**：礼包 repository 的奖励发放需要 `premium.py` 中的三个同步函数。为避免搬迁后形成 `gift_pack.repository → premium → db facade → gift_pack.repository` 环，B1 同时把 `premium.py` 搬到 `domains/premium/service.py`，并把仅为避免导入环而存在的 `app.databases` 导入改为函数内延迟导入；调用时序和事务/外部副作用行为不变。`app.premium` 暂留仅含转发的兼容入口以维护持久化 APScheduler 函数路径，B3 调度迁移后删除。
- **B1 配置文件路径**：`Settings.DATA_PATH` 原先用 `Path(__file__).parents[2]` 定位项目的 `data/`。搬到 `core/config.py` 后该路径多一层目录；搬迁工具仅对这一处已审阅的表达式改为 `parents[3]`，保持实际数据路径不变，其他 `__file__` 依赖仍拒绝预检。
- **B1 模型注册**：`core.db.init_db()` 保留原来的 `Base.metadata.create_all()`，且不反向导入组装层；`main.py`、迁移脚本和其他入口统一调用 `model_registry.init_db()`，注册表先显式导入全部领域模型再下调 `core.db.init_db()`。逐项 AST 校验仍要求核心建表方法不变，测试验证完整 31 张表与 mapper 配置。
- **模块级内容按所属领域分开**：db.py 模块级的常量和函数分到各领域的 `constants.py`、`rules.py` 或 `repository.py`，比如礼包的特权码锁留在礼包 repository。
- **只删除 `_CurWrapper` / `cur` 兼容层**。其他零调用的方法照常搬迁，因为零调用不等于死代码：
  - `rebind_user_tg_id` 是管理员手动执行的 TG 换绑。它原样搬进 `tg_rebind` 的 repository mixin，B 阶段之后仍可通过 `db.rebind_user_tg_id(...)` 调用。
  - 它直接改写其他领域的表。这些违规记入基线，由 `promote-tg-rebind-domain` 负责。
  - 它目前会漏迁 2026 年 8–9 月新增的几张表。按零行为变更的原则，本变更原样搬迁，修复由 `promote-tg-rebind-domain` 负责。
  - 为了保证手动入口不会在搬迁中丢失，D11 的校验会对比门面上的公开方法清单。

门面只导出 `db` 和 `DatabaseORM`。`from app.databases import db` 的写法保持不变。

备选方案：

- **B 阶段直接把方法改成模块级函数**：要改 687 处调用和全部 monkeypatch，搬迁就不再是机械操作，也无法逐项做 AST 比对。
- **门面只转发（`__getattr__`）**：`self.` 跨领域调用会断，编辑器也无法跳转到定义。

### D5 models 拆分与 `model_registry`

- **`Base` 的位置**：`Base` 放在 `core/db.py`，和 engine、`get_session` 放在一起。每个领域的 `models.py` 只定义本领域的表，`SystemConfig` 放在 `core/kv.py`。
- **`app/model_registry.py` 显式导入全部模型**：它逐个导入每个 models 模块，不做自动发现，并提供 `metadata` 和 `init_db()`。
- **改为使用 `model_registry` 的地方**：
  - `alembic/env.py`
  - `main.py`
  - `scripts/migrate_database.py`
  - 测试的 conftest
- **注册完整性由测试保证**：
  - 扫描出的所有 `Base` 子类都已在 registry 中导入。
  - 单独导入任意一个领域的 models 并执行 `configure_mappers()` 不会报错。

备选方案：模型集中在 `models/` 包里按领域分文件。这样对 alembic 更省事，但改一个功能要跨两个目录，也和 FastAPI 社区的惯例不一致。

### D6 路由与 API 组装

- **`api/app.py` 负责组装**：它创建 FastAPI 应用，并保持以下内容与现在一致：
  - 中间件的注册顺序和参数
  - 每个路由的 `prefix`，包括活动路由在 include 时加的 `/api`
  - 路由的挂载顺序
  - 静态文件最后挂载
- **uvicorn 的目标改成 `"app.api.app:app"`**。
- **路由搬迁后 URL 不变**：
  - 每个领域的 `APIRouter` 沿用来源路由的全部构造参数（`prefix`、`tags`、`responses`）。比如 `user.py` 拆出去的各部分，都用 `prefix="/api/user", tags=["user"]`。
  - 21 点和锦标赛原来是两个前缀不同的路由，所以 `blackjack/router/` 做成一个包，包内有两个子路由，由 `router` 统一 include。
  - 拆开的来源路由，在原来的挂载位置上依次挂载拆出来的各个路由。
- **只挪 `admin.py` 的接口**：B 阶段只把 `admin.py` 的接口搬进各领域的 `admin_router.py`。其他路由里夹带的管理员接口留在原路由中，因为把它们拆到新路由会改变同一前缀下的匹配顺序。
- **领域路由要用的公共部件下沉到 core**：Telegram initData 校验、`get_telegram_user`、`require_telegram_auth`、`check_admin_permission`、`TelegramUser`、`BaseResponse` 这些部件放到 `core/auth.py` 和 `core/schemas.py`。领域路由依赖它们，所以它们必须在领域之下。`api/` 只负责组装。
- **删掉 schemas 的汇总模块**：`webapp/schemas/__init__.py` 这个汇总导出模块（含两处 `import *`）删除，引用改为指向定义所在的模块。

### D7 Bot 组装

- **处理函数放进领域**：命令处理函数和 `*_handler` 对象搬进所属领域的 `bot.py`。`/start` 不属于任何领域，放在 `bot/start.py`。
- **注册表显式列出**：`bot/app.py` 用显式列表注册 handler，顺序与现在遍历模块得到的顺序一致，不再靠扫描变量名。`set_bot_commands` 也搬到这里。
- **菜单保持原样**：命令菜单原样保留，包括没有对应 handler 的 `update_database`。

### D8 定时任务：声明式任务表和具名任务

`app/schedule.py` 集中声明调度器会运行的所有东西：

```python
RECURRING = [
    RecurringJob(
        id="check_premium_expiry",
        func=premium_jobs.check_premium_expiry,
        runner="sync",
        trigger="cron",
        trigger_args={...},
        first_run_delay=None,
    ),
    ...,  # 32 entries, same ids, triggers, options and log lines as main.py today
]
TASKS = {  # one-shot tasks, addressed by a stable name
    "blackjack.hand_timeout": blackjack_jobs._settle_blackjack_hand_on_timeout,
    "treasure.open_next_issue": treasure_jobs._auto_create_next_treasure_issue_from,
}
ON_STARTUP = [
    auction_jobs.restore_auction_schedules,
    blackjack_jobs.restore_blackjack_timeouts,
]
LEGACY_TASK_REFS = {  # old persisted func paths -> task name; removed by retire-legacy-db-facade
    "app.webapp.routers.activities.blackjack:_settle_blackjack_hand_on_timeout": "blackjack.hand_timeout",
    "app.webapp.routers.activities.treasure:_auto_create_next_treasure_issue_from": "treasure.open_next_issue",
}
```

- **任务函数的位置**：周期任务的函数放在各领域的 `jobs.py`。原来写在路由里的任务，比如 21 点超时扫描、礼包过期扫描，也都搬过去。
- **持久化任务改用任务名**：
  - `core/scheduler.py` 提供两个函数：`schedule_task(name, run_date=…, job_id=…, kwargs=…, **job_options)` 和分发函数 `run_task(name, /, **kwargs)`。
  - 持久化 jobstore 里记录的函数固定为 `app.core.scheduler:run_task`，任务名作为第一个参数传入。
  - 以后搬动或重命名任务函数，都不需要再迁移 jobstore。
  - `core/scheduler.py` 拒绝向持久化 jobstore 加入非具名任务，从机制上防止同样的问题再次出现。
- **启动时迁移已有记录**：
  - 在 `scheduler.start()` 之前，把 jobstore 里旧函数路径的记录改写为具名任务。
  - 改写只动 pickle 状态里的 `func`、`args` 和 `name`，`id`、触发时间、`misfire_grace_time`、`kwargs` 都不变。
  - 迁移是幂等的，会在日志里打印改写条数。
  - 反向改写由 `scripts/refactor/rewrite_job_refs.py --reverse --scheduler-stopped` 完成；脚本必须显式确认所有使用该 jobstore 的 B3 调度器进程已停止，否则拒绝执行。反向脚本完成后不得重新启动 B3 调度器，必须直接回退镜像并启动旧进程。
- **B 阶段只转换持久化任务**：竞拍结束任务在内存 jobstore 里，不受代码路径影响，本变更不做转换。

备选方案：

- **把任务函数搬到 `jobs.py`，只迁移一次路径**：做法更简单，但以后每次重命名或移动任务函数都要再迁移一次，C 阶段必然会碰到。
- **保留旧模块路径作为转发**：与"不保留兼容路径"的原则冲突，而且那些旧模块本身都要删除。

### D9 `core/` 与 `integrations/` 的归类

| 现在 | 去向 |
|---|---|
| `config.py`、`log.py`、`scheduler.py` | `core/config.py`、`core/log.py`、`core/scheduler.py`（加上 D8 的具名任务） |
| `databases/session.py` 与 `models.Base` | `core/db.py` |
| `databases/redis.py`、`databases/cache.py` | `core/redis.py`、`core/cache.py`。缓存实例继续集中定义，因为 `integrations/emby.py` 也在用 |
| `SystemConfig` 模型及其读写方法 | `core/kv.py` |
| `utils/utils.py` 中的通用部分 | `core/http.py`（HTTP 会话）、`core/telegram.py`（发消息、TG 用户信息缓存）、`core/formatting.py`、`core/singleton.py` |
| `utils/number.py`、`utils/system.py` | `core/number.py`、`core/system.py` |
| `webapp/auth.py`，以及 D6 列出的公共部件 | `core/auth.py`、`core/schemas.py` |
| `webapp/__init__.py`、`webapp/middlewares.py`（中间件类）、`webapp/startup/lifespan.py` | `api/app.py`、`api/middlewares.py`、`api/lifespan.py`、`api/static.py` |
| `modules/` 下的 plex、emby、tautulli、overseerr、upay、vaultwarden 客户端，以及 `utils/tautulli_history.py` | `integrations/`。`get_user_total_duration` 负责解析 Tautulli 的返回值，一起放进 `integrations/tautulli.py` |
| `modules/custom_line.py` | `domains/custom_lines/`。它读写数据库、调用线路逻辑，不是外部客户端 |
| `blackjack_engine.py` | `domains/blackjack/rules.py` |
| `premium.py`、`db_func.py`、`utils/report.py`、`utils/utils.py` 中的业务部分 | 按函数拆到所属领域的 service、jobs、notifications 或 rules。例如 `refresh_tg_user_info` 要查 `statistics`，所以放在 `accounts/jobs.py` |

`core/` 不导入领域、门面和 integrations。`integrations/` 只导入 `core/`。

### D10 用机器守住边界

import-linter 的配置写在 `pyproject.toml` 里（`root_packages = ["app"]`，开启 `include_external_packages`）：

| 合约 | 类型 | 内容 |
|---|---|---|
| 顶层分层 | layers | `main` > `api \| bot \| schedule \| model_registry` > `domains : databases` > `integrations` > `core` |
| 领域分层 | layers，`containers = ["app.domains"]`，`exhaustive = true` | 按 D2 的六层排列，同层领域之间用 `:` 分隔。新增领域必须先在这里定层，否则检查失败 |
| 领域无环 | acyclic_siblings，`ancestors = ["app.domains"]` | 同层领域之间也不能成环 |
| 领域内分层 | layers，`containers = ["app.domains.*"]`，各层可选 | `router \| admin_router \| jobs \| bot` > `service` > `notifications \| repository` > `models` |
| 入口不碰数据层 | forbidden | 入口和 notifications 不得导入 repository、models、`sqlalchemy`、`app.core.db` |
| SQLAlchemy 的使用范围 | forbidden | 只有 repository、models、`core/db.py`、`core/kv.py`、门面和 `model_registry` 可以导入 `sqlalchemy`、`app.core.db` 和各领域 models；另精确允许 `app.core.scheduler → app.core.db` 用于 jobstore 引用迁移的事务助手，不允许 `app.core.scheduler` 直接导入 `sqlalchemy` |
| rules 是纯函数 | forbidden | `rules` 不得导入数据库、网络、Telegram、Redis、调度器、integrations、门面和其他角色模块 |
| 外部客户端隔离 | forbidden | `integrations` 不得导入领域、门面、`api`、`bot` 和 `sqlalchemy` |
| 门面冻结 | protected | 只有现有模块可以导入 `app.databases`，新模块不行 |

调度器的持久化任务迁移只在 `core/scheduler.py` 编排 pickle 引用转换，SQL 查询、行锁和原子更新由 `core/db.py` 的专用 jobstore 基础设施助手执行。D10 的唯一新增基础设施导入者是 `app.core.scheduler`；不得借此开放领域 service、jobs 或其他 core 模块访问数据库引擎，合约和测试须验证此边界。

import-linter 表达不了的规则，放进 `tests/architecture/`，这些测试只做 AST 扫描：

- **跨领域的调用面**：
  - service 只能导入其他领域的 service、exceptions 和 constants。
  - repository 只能使用其他领域 repository 里的 `*_tx`，另外可以导入 `identity.models`；读模型层可以导入任意 models。
  - 入口不直接调用其他领域。
  - 跨领域的 `db.<method>` 调用（按方法所属的 mixin 判断）和 mixin 之间的非 `*_tx` 的 `self.<method>` 调用也算违规。门面在 import 图里藏住的依赖，靠这一项查出来。
- **单文件行数预算**：1,000 行。
- **模型注册完整**：见 D5。
- **mixin 不重名**。

门面把跨领域调用藏在 `db.`/`self.` 后面，import 图看不到它们，所以只能靠 AST 测试补上。领域分层合约同时忽略门面指向各 repository 的边，否则每个领域都会经由门面间接依赖所有领域。

基线的规则：

- **现存违规登记在两处**：import-linter 的违规写进各合约的 `ignore_imports`，AST 测试的违规写进 `tests/architecture/baseline.json`。
- **每条都标负责的变更**：`ignore_imports` 按负责变更分组，用注释标出；baseline.json 里直接记录负责变更。负责变更按领域对应，见 Migration Plan 之后的表。
- **B2 迁入旧违规的唯一例外**：原先位于 `webapp/`、`handlers/` 的接口搬到领域后，原来的 `db` 调用、SQL 查询和跨领域调用才进入领域扫描范围。B2 可增加基线条目，但每一条都必须绑定基准提交的来源模块/源码单元 ID、搬迁映射、目标位置及负责后续清理的变更；核对搬迁前后该调用的规范化 AST 一致。不能仅因条目落在新文件就视为旧债；找不到来源、修改了调用或新写的逻辑必须失败。禁止整领域/整目录豁免；迁入的门面导入只允许精确到导入者，`ignore_imports` 精确到实际导入边，条目必须登记负责变更并受 unmatched 检查。此例外不授权新代码调用门面。
- **只减不增**：
  - B2 完成逐条来源审计并重新封存后，新增违规会让检查失败；B2 审计期间也拒绝来源不明或调用发生变化的新增条目。
  - 违规修好后如果条目还留着，检查同样失败：import-linter 设 `unmatched_ignore_imports_alerting = "error"`，AST 测试也照此处理。
  - 各合约的 ignore 条数与 baseline.json 里封存的数字一致，所以修掉违规时要在同一个提交里下调封存数。
- **封存时机**：B1 保留既有封存数；B2 只对已审计的接口迁入旧违规重新封存；B3 以冻结的 B2 提交为来源，逐项审计 `db_func.py`、`modules/custom_line.py`、`utils/report.py` 和剩余工具函数机械迁入领域后才首次可见的旧 SQL、门面和跨域调用。每条 B3 新条目必须登记 B2 来源单元 ID、未变调用 AST、目标映射和负责后续清理的变更，import-linter 只允许与源导入绑定相符的精确豁免；不得把新增代码或改动调用混入基线，也不得修改 B2 来源提交来洗白违规。审计须从冻结提交读取真实来源单元，比较对应目标单元的调用 AST、导入路径及实际使用的绑定，并拒绝仅凭目标领域有候选映射就推定继承；对去环而改变的调用逐项记理由和行为等价测试，但不能标为未变旧债。B3 新增的领域环不得豁免；特别检查 `premium→lines`、`profile→accounts`、`traffic→custom_lines` 和 `traffic→lines` 四条新增循环边。B3 封存后最终基线严格只减不增。每一批仍要执行新增违规、伪造来源和已修复条目的拒绝测试。

两个本地 pre-commit hook 分别运行 `lint-imports` 和 `pytest tests/architecture`，都用项目虚拟环境。

备选方案：

- **只写文档，不做检查**：db.py 在 40 天里翻了一倍，说明仅靠约定守不住。
- **自己写全部检查**：分层和无环这类检查，import-linter 已经做得成熟。只有它表达不了的规则才自己写。

### D11 搬迁工具与等价性校验

`scripts/refactor/` 下的工具按以下步骤工作：

1. **清点**：列出源模块中每个顶层函数、类、类方法、类属性和模块级赋值，也清点模块文档字符串、全部顶层可执行语句（`if`、`try`、`with`、循环、表达式等）、导入语句，以及 `__init__.py` 的导出声明。每项记录原文件、精确源码范围（含装饰器和前导注释）、规范化 AST 和稳定 ID；内嵌类成员与父类范围的重叠关系也要记录。不能因为一个文件没有函数/类就认为它可直接删除。
2. **映射**：`mapping.toml` 为每个需要保留的项指定目标模块（mixin 方法还要指定目标类），可标记为删除并写明原因；不确定项标记 `TODO`。顶层可执行语句和包的导入/导出声明也必须有明确去向或保留在组装层，不得靠猜测分配。允许把一个类整体搬到一个目标；要按成员拆分时，父类必须显式标记为组装项，不得同时复制整类与其子项。例如 `DatabaseORM` 的组合类由 B1 的门面组装，旧方法各归 repository mixin。生成初稿后人工审阅；有未映射、未审阅的 `TODO`、冲突的父子目标或无理由删除时，搬迁工具拒绝执行。审阅映射表比审阅四万行的 diff 容易得多，它是这次搬迁的主要 review 对象。
3. **搬迁**：
    - 按源码行切片，连同装饰器和前导注释一起搬，不重排版。把顶层语句、模块文档字符串与包导出作为必须保留的单元处理，顺序和导入副作用不能凭空丢失；若一个语句或赋值同时牵涉多个目标且不能安全拆分，则拒绝执行。
    - 按每项用到的名字生成导入语句；模块内 `import *` 展开为显式导入，并检查别名与包导出。合并到已有目标模块时须在写入前拒绝定义重名、来源不同的同名导入绑定、重复可执行 AST 或导入副作用被改写；保留已有定义和新定义的执行顺序。检查目标模块内导入环和未解析的依赖，不能仅凭生成文件能通过语法检查就视为成功。
    - 按映射改写全仓库的导入语句和字符串引用，范围包括 `src`、`tests`、`scripts`、`alembic`，覆盖函数内导入、monkeypatch 目标、uvicorn 目标与持久化任务路径；不重写不相关的普通字符串。
    - 搬迁前先做完整性预检，并在任何文件写入前拒绝：未覆盖的源码单元、父子范围重复搬运、拆开了 `global` 重绑定的名字、拆分后出现导入环或不能无歧义改写的引用。B3 的四条新领域循环边不允许靠增加 `ignore_imports` 通过；逐条调整归属或调用后重新检查无环。`_get_line_monthly_traffic` 去环不得改变 B2 的查询结果、会话／事务边界、异常传播和副作用顺序；用同一份一次性数据库分别运行 B2 与 B3 代码比较。对失败的预检保持源文件和目标文件不变。
4. **校验**：对比搬迁前的基准提交和当前工作树，以下每一项都必须一致：
    - **逐项 AST 比对**：按审阅映射中的来源 ID 和目标模块逐一比对定义、类成员、顶层可执行语句与模块文档字符串；跨文件合并的导入项验证其名称或在映射中为该来源 ID 记录明确的重分配目标及理由。只允许经过审阅的导入路径、D4 自引用、D8 调度调用、B1 Premium 延迟导入和 `Settings.DATA_PATH` 相对层级修正。B2 因 Ruff 禁止可变默认值而将 Pydantic 字段的 `=[]` 改为 `Field(default=[])` 时，只允许针对审阅过的确切字段做 AST 规范化，并用构造/序列化测试证明等价。新写的组装代码（api、bot、schedule、registry、门面）由后面几项快照覆盖；`action = "assemble"` 仅适用于被组装替代的源单元，并保留来源与目标的审阅记录；`action = "delete"` 只适用于已从运行路径移除、确实获准删除的单元，不能用来绕过保留的源定义。迁入领域的模型、方法和路由函数不能因位于新目录，或来自整个 `webapp/handlers` 目录，而整体跳过。用故意修改目标函数体、删除导入绑定或错误标记保留定义为删除的反例测试确保校验失败。
   - **B2 持久化超时路径例外**：`app.webapp.routers.activities.blackjack:_schedule_blackjack_timeout` 搬入 `blackjack/jobs/` 后继续向 SQLAlchemy jobstore 提交原始 `app.webapp.routers.activities.blackjack:_settle_blackjack_hand_on_timeout` 字符串引用，不能产生新函数路径的记录；B3 在删除旧模块前按 D8 迁移。夺宝自动续期同理：`app.webapp.routers.activities.treasure:schedule_auto_reopen_treasure_issue` 继续持久化原始 `app.webapp.routers.activities.treasure:_auto_create_next_treasure_issue_from`，直至 B3 迁移。只对这两个明确列出的调度调用的 `func=` 参数允许“B1 可调用对象 → 完全相同的 B1 字符串路径”的 AST 规范化，路径必须逐字匹配；测试须覆盖正常目标、错误目标被拒绝及 APScheduler 可解析旧路径。
   - **手动入口组装**：`db_func.py` 与 `utils/report.py` 的两个 `if __name__ == "__main__"` 语句是获审阅的 CLI 组装单元，不可标记为无理由删除。B3 在 `app.manage` 中提供显式 `legacy-credit-sync` 与 `report` 子命令：前者按原顺序执行 Plex 积分更新、Plex 信息更新、Emby 积分更新；后者保留 `--days`、`--top`、`--stat`、`--refresh`、`--all_stats`、`--library_stats`、`--user_stats`、`--watched_stats`、`--emby` 的参数、默认值及不打印返回报表的原行为。旧模块路径按 D1 删除，但须记录新调用方式并在一次性环境中对比命令解析、调用顺序和副作用。仅这两个守卫可用带来源、目标和行为对比的手动组装标记；搬迁器跳过原守卫切片不等于等价性校验可跳过，不能用无审计的删除或整目录忽略取代。
   - **导入解析**：逐个导入所有模块。用 AST 找出全部函数内导入和字符串引用（uvicorn 目标、monkeypatch 目标、任务名），逐一解析。
   - **OpenAPI 文档完全一致**。
   - **路由表顺序**：只有互不重叠的路由可以调换顺序。判断方法是把路径参数当通配段，检查同一方法下两条路由能不能匹配同一个路径。
   - **模型元数据结构化导出后一致**。另外在一次性 PostgreSQL 上，用搬迁前的 metadata 执行 `create_all`，再用 alembic 的 `compare_metadata` 对比搬迁后的 metadata，差异必须为空。
   - **调度任务快照一致**：用一个记录用的假调度器，分别运行旧的 `add_init_scheduler_job()` 和新的 `schedule.register_all()`，对比每个任务的 id、触发器参数、选项、executor 和 jobstore。`next_run_time` 换算成相对启动时刻的偏移后再比。
   - **Bot 快照一致**：handler 的注册顺序、命令、回调，以及命令菜单。
   - **门面公开方法清单一致**：`db` 上的公开方法与基准相同，只减去映射里标为删除的项。没有调用方的手动运维入口靠这一项兜底。
   - **测试、ruff 和 import-linter 全部通过**。

导入风格保持原样：原来按名导入的，改完路径后仍按名导入；拆分时新增的导入也按名导入，这样函数体不用改动。改成按模块导入（`from app.domains.x import service as x_service`）会动到每个调用点，留给各领域的 promote 变更。拆分后如果某个 monkeypatch 目标失效，测试会失败，按新位置修正即可。

### D12 分三批搬迁

| 批次 | 内容 | 结束时 |
|---|---|---|
| B1 数据层 | `core/`、`model_registry`、各领域 `models.py`、db.py 拆成 mixin 加门面、`integrations/`、`blackjack/rules.py` | 路由仍在 `webapp/`，通过门面照常运行 |
| B2 接口层 | `webapp/` 和 `handlers/` 的全部内容，包括路由里夹带的任务和编排函数；`api/`、`bot/` 组装 | uvicorn 目标切换 |
| B3 编排层 | `db_func.py`、`premium.py`、`modules/custom_line.py`、`utils/` 的剩余部分；`schedule.py`、`manage.py` 手动子命令、具名任务、jobstore 迁移；删除旧包 | 来源审计后封存最终基线 |

每批都经过完整的校验再提交，提交后应用可以启动。

### D13 文档分工

- **AGENTS.md**：只写规则和"新代码放哪"清单，保持简短，因为它会进入每个 agent 的上下文。过渡期规则也写在这里：新的数据库操作写进所属领域的 repository mixin，并通过 `db` 调用；不得新增跨领域的 `db` 调用。原来的"业务逻辑放在 db.py 或 modules"一类约定全部删除。另外写明：没有调用方的函数不一定是死代码，删除前先查手动运维清单，并和维护者确认。
- **`docs/architecture.md`**：写给人看的参考资料，包括分层图、领域表、列归属表、例外清单（读模型读表、特权码提交前写 `.env`、门面）、手动运维操作清单（逐项记录 `manage.py` 的 TG 换绑、旧版积分／用户信息同步与报表子命令及原有调用路径）、配置分类、基线计数和各条目的负责变更。AGENTS.md 链接到这里。

## Risks / Trade-offs

- **[门面让跨领域调用在 import 图里不可见]** → 用跨领域调用面测试兜底。C 阶段每提升一个领域，就摘掉它的 mixin。
- **[一次改动几乎所有后端文件，和并行分支冲突]** → 搬迁期间冻结后端功能开发。搬迁由映射表驱动，出现冲突时在新主干上重跑工具，而不是手工合并。
- **[有些断裂只在运行时暴露]** → 导入解析覆盖函数内导入和字符串引用，再加上全量测试。每批结束后在一次性环境里启动应用，访问几个接口，并核对调度器的任务列表。
- **[拆分路由后匹配顺序变化]** → 路由顺序检查只放行不重叠的换序。非 `admin.py` 路由里的管理员接口，B 阶段不挪。
- **[按名导入加上拆模块，让 monkeypatch 失效]** → 测试会失败，按新位置修正 patch 目标。这属于允许的测试改动。
- **[jobstore 迁移出错，或回退后丢任务]** → 迁移是幂等的，在调度器启动前执行，并记录日志。回退必须先停止所有 B3 调度器，再以 `--scheduler-stopped` 运行反向脚本，确认完成后立即回退镜像；禁止让仍运行的 B3 进程加载已反向的旧路径。即使 21 点超时任务丢了，也会被启动恢复和兜底扫描补上；夺宝自动开期没有补救，所以这个停止—反向—回退顺序是硬性要求。
- **[列归属只靠文档约束]** → 本变更不做机器检查，review 时对照列归属表。以后可以按"对写入列名做 AST 检查"的思路补上。
- **[基线很长，看起来像默许违规]** → 每条都标了负责变更，`docs/architecture.md` 公布计数。每个 promote 变更的验收条件之一，是清空自己名下的条目。
- **[没有调用方的手动运维入口在搬迁中丢失]** → 门面公开方法清单纳入校验。B1 冒烟时在一次性库上执行一次 `db.rebind_user_tg_id`，数据变化与基准一致。
- **[过渡期有两种写法并存]** → AGENTS.md 写明过渡期规则。门面冻结合约阻止新模块导入门面，跨领域调用面测试阻止新增跨领域调用。

## Migration Plan

1. 完成并合入 A 阶段：`docs/architecture.md`、AGENTS.md、import-linter 与 pre-commit 配置、`tests/architecture/` 骨架、`scripts/refactor/` 工具。
2. 冻结后端功能开发。记录基准提交。
3. 依次完成 B1、B2、B3。每批的步骤是：生成并审阅映射 → 运行搬迁 → 运行校验 → 提交。B3 结束时封存基线。
4. 部署：正常发布镜像。`alembic upgrade head` 不执行任何迁移。应用启动时，在 `scheduler.start()` 之前改写持久化任务的引用，并在日志里打印条数。
5. 部署后检查：
   - 调度器任务列表和部署前一致。
   - 接口冒烟测试通过。
   - 等到一局 21 点超时、一期夺宝开奖，确认相应任务正常执行。
6. 回退（维护窗口）：停止所有 B3 调度器进程；运行 `python -m scripts.refactor.rewrite_job_refs --reverse --scheduler-stopped`；确认反向改写条数和日志后，不得启动 B3，直接回退镜像并启动旧版本。

基线条目按违规来源所在的领域，分派给负责提升该领域的后续变更。D3 列出的三处环例外，分别由 D3 中写明的变更负责。

| 后续变更 | 负责的领域或事项 |
|---|---|
| `make-credit-changes-atomic` | `credits`，以及所有直接写积分的代码 |
| `promote-blackjack-domain` | `blackjack` |
| `promote-gift-pack-domain` | `gift_pack` |
| `unify-business-configuration` | `core/config.py` 中的业务参数、各领域 `config.py` |
| `promote-activity-domains` | `luckywheel`、`treasure`、`prediction`、`auction` |
| `promote-account-domains` | `identity`、`accounts`、`invitation` |
| `move-privileged-codes-to-database` | 特权邀请码 |
| `promote-line-domains` | `lines`、`custom_lines`、`traffic`、`premium`、`media_access` |
| `move-line-catalog-to-database` | 线路目录 |
| `promote-reward-domains` | `badges`、`badge_awards`、`watch_rewards`，以及领域事件 |
| `promote-remaining-domains` | `donation`、`crypto_donation`、`vaultwarden`、`rankings`、`reports`、`profile` |
| `promote-tg-rebind-domain` | `tg_rebind`、各领域为换绑提供的 `reassign_tg_id_tx`，以及修复换绑漏迁 |
| `retire-legacy-db-facade` | 删除 `app/databases/`、`LEGACY_TASK_REFS` 和剩余的基线条目 |

## Open Questions

- **领域事件的具体形式**：采用同步回调还是调度任务，如何保证只在事务提交后触发，由第一个需要它的变更决定（`promote-account-domains` 或 `promote-reward-domains`）。本变更只确立"下层通知上层用事件"这条原则。
- **21 点和礼包 repository 包内怎么分文件**：审阅映射表时，按 db.py 现有的分节确定。
