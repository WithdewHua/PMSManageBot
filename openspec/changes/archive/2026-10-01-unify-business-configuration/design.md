# Design

## Context

动机见 proposal.md 的 Why，对外行为见 `specs/business-configuration/spec.md`。以下事实以调研时的 HEAD（`495bd34`）为准。

**`Settings` 的构成与读写**

- `Settings` 共 74 个字段：
  - 12 个运行时开关和价格。
  - 6 个没有后台入口的业务参数。
  - 3 个不在本变更范围：线路目录两项，特权码一项。
  - 6 个边界项：`SITE_NAME`、`TG_GROUP`、`TG_CHANNEL`、`EMBY_USER_TEMPLATE`、`EMBY_USER_IS_HIDDEN`、`REDIS_LINE_TRAFFIC_STATS_HANDLE_SIZE`。
  - 其余是基础设施配置和密钥。
- 12 个开关分别由 7 个领域的 admin_router 修改，形态统一：
  - 接口：`POST /api/admin/settings/<slug>`。
  - 鉴权：`require_telegram_auth` 加 `check_admin_permission`。
  - 返回：`BaseResponse{success, message}`；校验失败和异常都返回 HTTP 200、`success=false`。
- 读取点共 68 处，其中设置总览（`reports/admin_router.py:16-50`）占 18 处。部分读取在导入时就固定了下来：
  - `reports/constants.py:16/23` 是模块级常量。
  - `integrations/emby.py:297/348` 把配置值用作函数的默认参数。
  - `traffic/jobs.py:105`。
  - `bot/app.py:39`：启动时生成命令菜单。
- 6 个无入口的参数只有读取，没有运行时写入。

**配置的加载**

- 加载顺序：pydantic-settings 先按"系统环境 > 工作目录 `.env` > 默认值"解析，然后 `_load_from_env_file` 逐行用 `data/.env` 覆盖。所以实际优先级是 `data/.env` > 系统环境 > 工作目录 `.env` > 默认值。
- 这个加载器遇到坏行就会中止，后面的键都不再加载。
- `data/.env` 的值还会被镜像进 `os.environ`；之后再实例化一次 `Settings()` 就会报错，因为逗号分隔的列表不是 JSON。
- 工作目录 `.env` 中出现未知键时，启动直接报 `extra_forbidden`。

**`SystemConfig` 里的配置与状态**

| 用途 | type/key | 现状 |
|---|---|---|
| 转盘配置 | `lucky_wheel/config` | Pydantic 补缺省值；解析失败返回默认值 |
| 转盘随机性 | `lucky_wheel/randomness_config` | 进程级类属性；PUT 合并任意键 |
| 21 点配置 | `blackjack/config` | 浅合并，`tournament_defaults` 整体替换；PUT 整体替换 |
| 勋章中心 | `badge_center/enabled`、`badge_center/message` | 两行，存 `"1"`/`"0"` 和原文；两次写入分属两个事务 |
| 状态和游标 | 21 点奖池与游标、预言奖池、幽灵会话游标、`gen_privileged_code` | 本变更不迁移 |
| 线路目录 | `line_tag/*`、`free_premium_line/*` | 不在范围 |

- `get_system_config` 吞掉异常并返回 `None`，转盘和 21 点会把它当成首次读取而写入默认值。
- `SystemConfigRepository` 被组合进门面：经 `db.` 调用 2 次，mixin 内经 `self.` 调用 17 次（luckywheel 2、blackjack 2、lines 9、badges 4）。

**测试**

- conftest 不隔离 settings，导入时就读了仓库里的 `data/.env`。
- 12 个设置接口都没有测试。
- 只有 `tests/test_gift_pack_rewards.py:279` 改了一个范围内的业务键（`EMBY_REGISTER`）。

**进程模型**

bot、调度器和 uvicorn 线程在同一个进程里；alembic、`app.manage` 和 scripts 是独立进程。现在所有的运行时配置写入，都发生在应用进程里。

## Goals / Non-Goals

**Goals：**

- 业务配置有类型、有归属领域、存在数据库里；读写经过同一个机制，修改立即生效、重启后保留。
- 迁移时每一项都取升级前实际生效的值，只写一次，不覆盖已有值；读取出错不会改写配置。
- 12 个现有接口、设置总览和 `/set_register` 保持对外格式不变；新增 6 个后台设置和对应的前端控件。
- 从门面摘除 `SystemConfigRepository`，并让测试不再依赖仓库里的 `data/.env`。

**Non-Goals：**

- 不迁移特权码和线路目录（`STREAM_BACKEND`、`PREMIUM_STREAM_BACKEND`、`line_tag`、`free_premium_line`）。不删除 `save_config_to_env_file`，它还剩 8 处调用。
- 不迁移存在 `SystemConfig` 里的状态和游标，包括奖池余额、结算游标和 `gen_privileged_code`。
- 不改基础设施配置的加载方式。`TG_ADMIN_CHAT_ID` 的解析问题、session 密钥字段名写错的问题，不在本变更修复，已单独登记。
- 捐赠倍率的修改不重算已有积分；NSFW 媒体库列表的修改不自动重新同步已有权限。

## Decisions

### D1 配置归属：一项只归一个领域，按分层方向确定

每项配置归实际拥有该业务规则的领域，而且它的读取方都必须位于同层或更高层。这样跨域读取只会向下，不会产生新的依赖环。写入接口可以留在原来的 admin_router，由它所在领域的 service 调用配置所属领域的 service 完成写入。

| 领域（层级） | 配置项 | 写入入口 |
|---|---|---|
| accounts（T3） | `plex_register`、`emby_register` | accounts admin_router；`/set_register` |
| invitation（T3） | `invitation_credits` | invitation admin_router |
| premium（T3） | `premium_unlock_enabled`、`premium_daily_credits`、`credits_cost_per_10gb` | premium admin_router（`credits_cost_per_10gb` 为新增） |
| donation（T3） | `donation_multiplier` | donation admin_router（新增） |
| crypto_donation（T3） | `upay_crypto_types` | 新增 crypto_donation `admin_router.py` |
| lines（T2） | `premium_free`、`line_schedule_unlock_credits` | `premium_free` 仍由 premium admin_router 写，经 premium.service 调用 lines.service |
| traffic（T2） | `user_traffic_limit`、`premium_user_traffic_limit` | 前者在 traffic admin_router；后者仍由 premium admin_router 写，经 service 调用 |
| media_access（T2） | `unlock_credits`、`download_unlock_credits`、`nsfw_libs` | media_access admin_router（`nsfw_libs` 为新增） |
| vaultwarden（T2） | `enabled`、`redeem_credits` | 新增 vaultwarden `admin_router.py` |
| credits（T1） | `transfer_enabled` | credits admin_router |
| luckywheel、blackjack、badges | 现有的转盘、随机性、21 点、勋章中心配置 | 原接口不变 |

几处取舍：

- **`premium_free` 归 lines**：它的主要读取方是 lines（7 处）。lines 在 T2，premium 在 T3；如果归 premium，lines 就要向上依赖 premium。
- **两个流量额度归 traffic**：D2 规定 traffic 负责"流量上限"，premium 从下层读取它们。
- **6 个边界项仍算部署配置，留在 `.env`**：站点名称、群组和频道链接、Emby 建号模板和隐藏开关、Redis 批处理大小。它们描述的是部署环境，不是业务规则。

### D2 `core/domain_config.py`

```python
class DomainConfig(Generic[M]):
    def __init__(
        self,
        name: str,
        model: type[M],
        storage: ConfigStorage,
        legacy: Mapping[str, LegacySource] = {},
        ttl_seconds: float = 30,
    ): ...
    def get(self) -> M: ...  # 冻结的模型实例
    def get_tx(
        self, session
    ) -> M: ...  # 在调用方事务里读取，缓存未命中时不另开 session
    def update(self, **changes: Any) -> M: ...  # 校验 → 事务内写入 → 提交后清缓存
    def seed(self) -> SeedReport: ...  # 只插入缺失项
```

- **模型**：用 Pydantic v2 冻结模型。数值字段用 `StrictInt` 加范围约束，从而拒绝 bool。开关字段的"按真值解释"放在接口层完成，模型里只存 bool，所以生效值和持久化值必然一致。
- **两种存储**：
  - `FieldRows`：每个字段一行，`config_type = "config.<domain>"`，`config_key = <字段名>`，值用 JSON 编码。新迁入的配置一律采用这种存储。
    - 每次修改只 upsert 一行，没有"读出—修改—写回"，所以在 SQLite 和 PostgreSQL 上并发修改不同字段都不会丢失。
    - 勋章中心沿用两行旧键，给每个字段声明各自的 `(type, key, codec)`，兼容 `"1"`/`"0"` 和原文。
  - `JsonDocument`：整个配置存为一行 JSON，用于转盘、随机性和 21 点。
    - 合并规则逐个声明，与现有行为逐字一致：21 点浅合并、`tournament_defaults` 整体替换；转盘由 Pydantic 补缺省值；随机性 PUT 合并任意键。
    - 需要合并的写入在 PostgreSQL 上先 `FOR UPDATE` 锁住这一行。
- **缓存**：
  - 进程内的字典，由锁保护。
  - 本进程的 `update()` 在提交后立即失效缓存，所以后台修改在下一次请求就生效。
  - 另设 30 秒 TTL 作为兜底，用来接住在进程外发生的修改，例如直接改库或回退脚本。bot、调度器和 uvicorn 线程共享同一份缓存。
- **错误语义**：
  - 读取时的数据库错误直接抛出，绝不当作"没有配置"。
  - 存储的内容无法解析时，返回默认值并记录 error，不改写原始数据。
  - 首次插入撞上唯一约束时，改为读取对方写入的值。
- **`get_tx`**：给 21 点这类在结算事务里读取配置的场景使用，缓存未命中时复用调用方的 session。

备选方案：

- **所有字段放进一个 JSON 文档**：每次修改都要读出、修改、写回。在 SQLite 上，`FOR UPDATE` 不起作用，并发修改不同字段会丢失其中一项。
- **用 Redis 共享缓存**：多出一个故障点；而目前所有写入都在同一个进程里，用不上跨进程失效。

### D3 `core/kv.py` 模块化并从门面摘除

- **新增模块级函数**：`get(type, key)`、`get_tx(session, type, key, *, for_update=False)`、`upsert_tx`、`insert_if_absent_tx`、`delete_tx`。这些函数都不吞异常。
- **保留旧函数签名**：`get_system_config` 和 `set_system_config` 暂时保留签名，但内部改调新函数，出错时照旧返回 `None`/`False`，直到调用方迁移完。
- **迁移调用方**：19 处调用（`db.` 2 处、`self.` 17 处）改为调用 `core.kv` 的模块函数。lines 的 9 处属于线路目录，只做这个机械替换，语义留给 `move-line-catalog-to-database`。
- **从门面摘除**：`DatabaseORM` 删除 `SystemConfigRepository`，同步删除对应的门面组合忽略项并下调封存计数。
- **状态行**：奖池、游标等状态行，仍由各领域 repository 读写。它们可以继续直接使用 `SystemConfig` 模型，也可以改用 `core.kv` 的 `*_tx`，本变更不强制。

### D4 初值迁移

- **种子来源**：先从 `core/config.py` 里抽出旧加载器的解析逻辑，逐字保留，作为 `LegacyEnvSource`，包括"遇到坏行就中止"、bool 和列表的解析规则、`TG_ADMIN_CHAT_ID` 的特殊处理，以及跳过 `WEBAPP_URL`。
  - 它只读取迁出的键，按"`data/.env` > 系统环境 > 工作目录 `.env` > 代码默认值"取值，与升级前该实例实际生效的值一致。
  - 为此写对比测试：给定同一份 `data/.env`、环境变量和工作目录 `.env`，旧 `Settings` 读出的值与种子值逐项相同，用例覆盖坏行中止和重复键。
- **写入时机**：
  - `main.py` 在初始化数据库之后、启动 bot、API 和调度器之前，调用一次 `domain_config.seed_all()`，日志记录每一项的来源和值；密钥不在范围内，不会打印。
  - `get()` 遇到缺失的项也会按同样规则插入，保证 `app.manage` 和测试等其他入口的行为一致。
- **`Settings` 的调整**：
  - 删除迁出的字段，并设置 `extra="ignore"`，这样旧键残留在工作目录 `.env` 或环境变量里也不会导致启动失败。
  - 启动时检查三个来源里是否还有迁出的键，有就记一条警告："已迁出，不再生效"。
  - `.env.example` 删除这些键，并加注释说明改到后台修改。

### D5 跨域读取与分层

- **只读**：service 和 repository 可以导入其他领域的 `config` 模块并调用 `.get()` / `.get_tx()`。`update()` 和 `seed()` 只允许配置所属领域自己调用。在 `tests/architecture/checks.py` 中加入这条规则，并配正反例测试。
- **不做 I/O 的代码改为传参**：
  - rules 不读配置，由 service 把配置值作为参数传入。例如 `premium/rules.py:20` 的 `CREDITS_COST_PER_10GB`。
  - integrations 不能导入领域，所以 `emby.py` 和 `plex.py` 里 NSFW 媒体库的默认参数改为由调用方显式传入。
- **导入时读取改为调用时读取**：`reports/constants.py:16/23` 和 `traffic/jobs.py:105` 改为在调用时读取。`bot/app.py:39` 的命令菜单本来就在启动时生成，改价格后要重启才会更新，这一点与现在相同，保持不变。

### D6 接口与前端

- **12 个现有接口**：路径、鉴权、请求字段、缺字段时的默认值、开关的真值解释、响应格式都不变；内部改为调用本领域的 service，由它完成写入。
  - 在现有校验之外，统一拒绝 bool 和负数。流量额度接口本来就拒绝 bool。
  - 写入失败时返回 `success=false`，内存值不变。现在是"内存已改、却返回成功"。
- **`/set_register`**：改为持久化。命令格式、权限检查和回复文案不变。
- **`/settings/emby-premium-free`**：补上缺失的 `background_tasks` 参数，行为与 `premium-free` 相同。
- **新增 6 个接口**：与现有接口同形。

| slug | 请求字段 | 约束 |
|---|---|---|
| `nsfw-libs` | `libs: list[str]` | 非空；去掉首尾空白后，每项非空且互不重复 |
| `donation-multiplier` | `multiplier: int` | ≥ 1 |
| `credits-cost-per-10gb` | `credits: int` | ≥ 0 |
| `vaultwarden-enabled` | `enabled` | 按真值解释 |
| `vaultwarden-redeem-credits` | `credits: int` | ≥ 0 |
| `upay-crypto-types` | `types: list[str]` | 非空；去掉首尾空白后，每项非空且互不重复 |

- **挂载**：新增的 `crypto_donation/admin_router.py` 和 `vaultwarden/admin_router.py` 挂载在各自领域原有路由之后。新路径与现有路径不重叠，OpenAPI 只增加这 6 个操作。
- **设置总览**：在原有的键之外，增加 `nsfw_libs`、`donation_multiplier`、`credits_cost_per_10gb`、`vaultwarden_enabled`、`vaultwarden_redeem_credits`、`upay_crypto_types`。
- **前端**：
  - `adminService.js` 新增 6 个调用。
  - `Management.vue` 的设置区新增控件：两个列表用可输入的多选 chips，三个数值用数字输入框，一个开关。
  - 保存失败时，用现有的 snackbar 显示 `message`，并回滚控件的值。

### D7 现有 `SystemConfig` 配置改为 `DomainConfig` 声明

| 配置 | 存储 | 迁移要点 |
|---|---|---|
| `luckywheel.config.wheel` | `JsonDocument("lucky_wheel", "config")` | `DEFAULT_WHEEL_CONFIG` 移入 `luckywheel/config.py` |
| `luckywheel.config.randomness` | `JsonDocument("lucky_wheel", "randomness_config")` | 进程级类属性 `RandomnessConfig` 改为读取模型 |
| `blackjack.config.game` | `JsonDocument("blackjack", "config")` | `promote-blackjack-domain` 建立的 `blackjack/config.py` 改为 `DomainConfig` 声明；奖池、游标等状态键常量移到 blackjack 的 repository 常量；原来吞异常后写入默认值的路径删除 |
| `badges.config.center` | `FieldRows`，每字段声明旧键和编解码 | 两次写入合并为一个事务 |

`gen_privileged_code` 属于状态，不属于配置，保持原样；它的读改写没有加锁，由 `promote-activity-domains` 处理。

### D8 测试隔离与夹具

- **隔离部署配置**：`tests/conftest.py` 在导入 `app` 之前，把 `DATA_DIR` 指向临时目录，并清除迁出键和列表键的环境变量；测试不再读取仓库里的 `data/.env`。
- **配置夹具**：新增 `business_config` 夹具，在测试数据库里写入并清空缓存。它替代 monkeypatch `settings.X`，也替代对 `get_blackjack_config_dict` 的 5 处 patch。
- **新增测试**：
  - 12 个现有接口和 6 个新接口的行为测试。
  - `/set_register` 的持久化测试。
  - D4 的种子对比测试。
  - 在一次性 PostgreSQL 上并发修改不同字段的测试。

### D9 `.env` 写入的剩余调用方与遗留函数

- **剩余调用**：本变更完成后，`save_config_to_env_file` 只剩线路目录 4 处、特权码 4 处，由两个后续变更各自移除。
- **零调用的遗留函数**：`save_current_config` 和 `get_saveable_config` 没有调用方，而且会把数据库密码等密钥写进 `.env`；敏感键名单也写错了。
  - 先查手动运维清单，并经维护者确认，再删除。
  - 如果确认要保留，就修正敏感键名单，并登记进手动运维清单。

## Risks / Trade-offs

- **[种子值与升级前实际生效的值不一致]** → 用逐字保留的旧解析逻辑加对比测试证明；在生产形态副本上逐项对比升级前后的生效值，再部署。
- **[回退后丢失后台修改]** → 提供只读脚本 `scripts/export_business_config.py`，把数据库中的业务配置导出为 `.env` 片段。回退前写回 `data/.env`，旧版本即可读到修改后的值。
- **[`extra="ignore"` 让部署配置的拼写错误不再报错]** → 迁出键会有明确的警告日志；基础设施键拼错时，会在第一次使用时暴露。以此换取"旧键残留不会导致启动失败"。
- **[进程外修改最长 30 秒才生效]** → 目前所有写入都在应用进程内，都是立即生效；TTL 只是兜底。
- **[68 处读取改动范围大]** → 按领域分批迁移，每批跑全量测试；用架构检查禁止再从 `settings` 读取迁出的字段：这些字段已经删除，残留的读取会在导入或测试时失败。
- **[`/set_register` 从临时改为持久化]** → 这是规格中明确的行为变化，在发布说明中告知管理员。
- **[前端改动没有自动化测试]** → 用 `npm run lint`、`npm run build`，并在本地逐项手动验证 6 个控件的保存、失败回滚和总览回显。

## Migration Plan

1. 实现 `core.kv` 的模块函数和 `DomainConfig`，并配单元测试。完成测试隔离。
2. 迁移 21 点、转盘、随机性、勋章中心这 4 个已有配置，确认读到的值与升级前逐字相同。
3. 按 D1 为各领域声明配置，实现种子逻辑和对比测试，逐个领域迁移读取点和接口。
4. 新增 6 个接口和前端控件，从 `Settings` 删除迁出的字段，从门面摘除 `SystemConfigRepository`。
5. 在生产形态副本上彩排：启动新版本，核对种子日志与旧版本的生效值；修改配置，确认立即生效且重启后保留。
6. 部署：新版本首次启动时自动写入初值。没有 schema 变更。
7. 回退：运行导出脚本，把导出的片段写回 `data/.env`，然后回退镜像。

## Open Questions

无。
