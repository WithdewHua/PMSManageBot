# Design

## Context

本变更从“工具文件重命名”调整为“公共设施职责收敛”。范围可以跨多个目录，但不把所有领域提升、历史错误修复或数据库迁移合并进来。

现场依据：

- `core/formatting.py` 同时包含纯字节显示和 Plex/Emby 名称、图标选择；前者被 premium、watch_rewards 使用，后者被 lines、media_access、premium 使用。
- `core/number.py` 的 `normalize_external_random_b` 实际执行 `int(value) & ((1 << 63) - 1)`，不是通用 BIGINT 校验。ETH RPC 的生产调用者是 treasure。
- `core/telegram.py` 包含 HTTP/Bot 投递、管理员收件人、pickle 缓存和单用户刷新；`domains/profile/service.py` 又有完整的单用户/全量刷新实现。
- `core/cache.py` 不仅有 RedisCache，还实例化了九个具体缓存，并提供积分失效函数。Emby 集成、traffic、accounts 等共享媒体 token 缓存，不能把这些实例一律放到高层 accounts。
- `core/legacy_env.py` 有业务默认值总表和具体键特判；领域 config 已有对应配置声明，`app.business_config` 已是统一装配入口。
- `core/auth.py` 是 FastAPI 适配而不是通用设施；`lines/service.py` 还接收 TelegramUser、返回 BaseResponse。
- 若把 Telegram 缓存简单迁到 integrations，treasure、donation、lines、media_access、gift_pack 等 repository 会继续依赖外部文件查询。只修改导入路径不足以消除这个职责问题。

## Goals / Non-Goals

### Goals

1. core 只拥有通用机制、基础运行配置和明确登记的纯基础值操作，不拥有业务实例、产品展示策略或供应商资料工作流。
2. 同一能力按语义内聚：Telegram 的缓存与网络在同一 integration 内分模块，不按本地/远程 I/O 切割所有权。
3. 为 HTTP/Bot 接入提供受限的 transport 支持，避免把 API 装配层当公共库，也避免让 HTTP 模型渗入服务层。
4. 允许调整内部接口，保持外部契约；先刻画，再迁移，验证不能靠重生成输出快照消除差异。
5. 将职责准入、调用方向、模块内部隔离和例外上限落实为可执行测试，而不只是文档说明。

### Non-Goals

- 不新增 shared/common/utils 大包，不引入 DI 框架、插件系统、通用事件总线或新的应用用例层。
- 不替换 pickle、不引入缓存回源/自动刷新、不改变 Redis 协议、TTL、重试和连接生命周期，不统一原本不同的失败策略。
- 不修复认证绕过、Telegram 刷新失败、Redis 事务一致性等行为缺陷；安全修复必须先建立自己的基线。
- 不删除整个数据库门面，不批量改写所有 ORM 会话或所有历史通知位置，不删除未确认的手动运维入口。
- 不修改数据库 schema、前端功能、线路目录/特权码的数据存储方案。

## Decisions

### D1. 先确定准入条件，再确定目录

一个能力进入 core，必须同时满足：

- 是通用技术机制或基础值操作，不表达 Plex/Emby 展示规则、用户积分/线路业务、Telegram 资料格式、活动随机规则或业务默认值。
- 没有向 domains、integrations、transport 或装配层的依赖；基础连接可以读基础设施配置。
- 有明确且窄的输入/输出、错误与生命周期契约；“多人使用”不是充分条件。
- 单消费者实现默认私有化；存在真正独立消费者时才提取公共模块。
- 注册到模块职责清单，声明存在理由、公开符号、依赖及消费范围。新模块/公开能力要评审，不能仅更新一条白名单即视为语义正确。

core 不是纯函数包：数据库引擎、Redis 连接、HTTP session 可以保留。反过来，没有 I/O 的业务规则也不因此属于 core。

### D2. 目标模块与职责清单

| 当前能力 | 最终位置 | 决定 |
|---|---|---|
| `core.config.Settings` | 原位 | 基础设施配置与路径保留；`_is_container` 私有化；残余业务配置例外见 D11 |
| `core.system.SystemUtils` | `core.config._is_container` | 删除类与旧模块，保留检测次序 |
| `core.singleton.SingletonMeta` | `core.scheduler._SchedulerSingletonMeta` | 单消费者私有化；Scheduler 类及实例身份、线程行为不变 |
| `core.db` | 原位 | 引擎、session、提交后回调机制；不放业务查询 |
| `core.redis` | 原位 | Redis 连接与连接池机制 |
| `core.cache.RedisCache`、Lua 脚本 | 原位 | 通用缓存机制，不实例化领域缓存 |
| `core.cache` 的九个实例、积分失效 | D6 所列拥有者 | 键空间、序列化、失效归拥有者 |
| `core.http` | 原位 | 通用出站 session/连接池；不承载入站 HTTP 模型或认证 |
| `core.log` | 原位 | 日志基础设施 |
| `core.scheduler` | 原位 | 调度机制，沿用已有 jobstore 例外，不增加领域/供应商知识 |
| `core.kv`、`core.domain_config` | 原位 | 通用配置存储、验证、缓存；保持既有合法 DB 访问边界 |
| `core.legacy_env` | 原位但去策略 | 只保留参数化读取器；业务默认值和旧键描述移到领域 config |
| `core.errors.DomainError` | 原位 | 共享错误基类，HTTP 转换迁到 transport；不在本次重设计异常协议 |
| `format_traffic_size` | `core.byte_size.format_bytes` | 通用字节显示，纯计算；不加入领域术语或读取配置 |
| `get_service_label` | `identity.rules`，经 `identity.service.get_service_label` 暴露 | 媒体身份展示词汇归 identity，不向下塞进 core |
| `core.number` | `treasure.rules` | 业务随机数映射；删除旧模块，不建立 database_values |
| `core.schemas` | `transport.http.schemas` | TelegramUser、BaseResponse 保持 HTTP 契约 |
| `core.auth` | `transport.http.auth` + `integrations.telegram.init_data` | HTTP 适配与 Telegram 协议校验分开 |
| `api.middlewares`、`api.errors` | `transport.http.middleware`、`transport.http.errors` | API 层只安装中间件和注册错误转换 |
| `core.telegram` | `integrations.telegram` + `transport.telegram.admin` | 见 D4、D5；不保留 core.telegram_profile |
| `core.__init__` | 原位 | 不聚合导出所有公共能力，不做初始化 |

目标结构示意（省略不变模块）：

```text
app/
├── api/                         # FastAPI 装配、路由顺序、lifespan、静态挂载
├── bot/                         # Telegram Bot 装配
├── business_config.py           # 领域配置及 legacy reader 装配
├── domains/
│   ├── identity/{service,rules,cache,config...}
│   ├── lines/{service,cache,types...}
│   ├── traffic/{service,cache...}
│   ├── credits/{service,repository,cache...}
│   └── treasure/{service,repository,rules...}
├── transport/
│   ├── http/{auth,schemas,middleware,errors}.py
│   └── telegram/admin.py        # 部署管理员收件人适配
├── integrations/
│   ├── telegram/
│   │   ├── client.py            # 资料/文件 API 请求和下载原语
│   │   ├── messaging.py         # Bot-context 与 Bot API 投递，保留各自重试
│   │   ├── profiles.py          # 单用户/批量刷新编排
│   │   ├── profile_cache.py     # 本地存取和显示名/头像查询
│   │   └── init_data.py         # 无 I/O 的 Telegram 签名/时间协议校验
│   ├── media_tokens.py          # Plex/Emby token→username 缓存适配
│   └── eth_rpc.py               # 返回原始哈希整数
└── core/
    ├── byte_size.py             # 只有字节单位显示
    ├── cache.py                 # 只有通用 RedisCache 机制
    └── ...                     # D2 明确保留的基础机制
```

所有新包有 `__init__.py`，不得通过包初始化导入客户端、启动网络/调度或聚合成新的万能 facade。

### D3. 调用矩阵，而不只是增加一层名字

粗粒度导入层级为装配 → domains → transport → integrations → core；再以角色规则约束具体消费。`app.business_config` 等既有装配模块纳入装配检查，不能只检查 `app.api`。

| 消费者 | 允许的新依赖 | 禁止 |
|---|---|---|
| API/Bot/启动装配 | 领域入口、transport、必要基础设施 | 从下层反向导入装配 |
| 领域 router/admin_router、HTTP schemas | `transport.http` 的认证/模型 | repository 或 rules 通过它取得 HTTP 对象 |
| 领域 bot/notifications | `transport.telegram.admin`、Telegram messaging、只读资料查询 | 把业务文案/业务受众判断放进通用 transport |
| 领域 service/jobs | integrations 的明确操作、领域 service、领域自有缓存 API | `transport.http`；service 直接使用部署群发适配改由本领域 notifications 包装 |
| 领域 repository | 数据库事实、领域规则、既有事务 helper、登记的提交后缓存回调 | Telegram 文件缓存、网络资料查询、HTTP/Bot transport |
| 领域 rules/types | 纯值依赖，如 byte_size（确有需要时） | transport、integration I/O、缓存、配置读取和网络库 |
| transport | integrations、core；HTTP 和 Telegram 支持模块各自内聚 | domains、api、bot、DatabaseORM、SQLAlchemy、core.db/kv |
| integrations | core、无环的内部 integration 模块 | domains、transport、应用装配、SQLAlchemy |
| core | 已批准的 core 依赖、相应基础库 | domains、transport、integrations、应用装配 |

HTTP schema 只允许本领域入口/schema 模块消费。`lines.service` 的绑定结果改为 `lines.types` 的纯结果值（保留 success/message 信息），router 转换成 BaseResponse；未使用的 TelegramUser 参数删除，真正需要的用户标识以普通参数传入。不为此推广全局 Result 类。

新 transport 是技术接入支持，不是新应用层：不能导入领域 service、不能协调交易、不能选择业务通知对象。

### D4. Telegram 整体归属、内部隔离

- `profile_cache` 保留原路径、锁文件、pickle 格式和读写实现，不导入 HTTP、Bot SDK、client、profiles 或 messaging。读取不会执行刷新。资料查询仍保留单条/批量各自的异常和类型语义。
- `client` 提供资料/头像/文件请求原语；`messaging` 保留当前 context 发送和 URL 发送的不同超时、返回值与重试，不为“统一客户端”改变行为。
- `profiles` 组合 client 与 profile_cache，承接 core 的单用户刷新及 profile.service 的批量刷新；不得自行查询身份数据库。`profile.service` 通过 identity.service 取得用户 ID 集合后传入。
- `init_data` 只做 Telegram 协议校验，显式接收 secret、now、有效期等参数，不读取 settings、不抛 HTTPException。HTTP 层负责提取 Request、开发开关、错误到 HTTP 的转换与部署管理员判断。
- 显示名是 Telegram 外部资料的只读表示，可在 integration 内提供；本项目的媒体类别图标不是 Telegram 协议的一部分，不能放进此包。

**24 小时只属于刷新跳过条件**。旧缓存即使超过 24 小时，查询仍返回；缺失缓存仍走原先 fallback。单条名称可能回退为 int，批量名称返回 str；不得在搬迁时统一类型。

两套刷新流程不能直接相互替代。当前单用户版本初始化 `result = {}`，批量版本的非 200 分支可能使用未赋值或上一轮的 result；两者还有缺文件和异常范围差异。先分别刻画 HTTP 非 200、网络重试耗尽、损坏缓存、头像下载失败、跨用户失败的结果与继续/终止行为。提取共同请求/存储原语，但保留两个具名编排函数及各自控制流，不加入抽象策略框架或一堆兼容 flags。已知错误作为明确后续缺陷处理，本变更不能把“顺手修复”伪装为等价迁移。

该拆分无需让缓存测试 mock HTTP：profile_cache 可独立导入，测试可禁止网络调用以证明隔离。

### D5. 消息策略与 repository 资料读取

`transport.telegram.admin.notify_admins_by_url` 只负责从部署配置取得管理员并顺序投递，保留继续/失败日志行为。它不是业务通知中心；收到完整文本，不判断积分、会员、活动状态。普通指定收件人的发送直接使用 integrations.telegram.messaging。

领域 notifications 决定业务文案和业务受众；调用 service 的地方保持提交后副作用约定。本次只迁移受影响的调用路径，不把所有旧领域提升一遍。

repository 的 Telegram 读取分三类处理：

1. **返回值展示补充**：repository 返回 tg_id 和数据库事实，service 查询缓存并补齐旧名称/头像字段；保证排序、分页、空值、数字/字符串 fallback 及原错误边界不变。
2. **gift_pack 等用户名解析**：service 先读资料快照，传入普通 dict/值对象；repository 在原事务中组合快照与数据库事实。不往 repository 注入一个可执行 I/O 的回调，也不把 SQL 搬进 service。
3. **仅为日志读取名字**：repository 使用稳定 tg_id，不再为日志执行文件 I/O。允许该类诊断日志变更，不改用户通知文案。

需清点所有直接、局部、别名和包内 repository 导入；已有例子不是完整白名单。迁移后的守卫对 Telegram cache/client 的 repository 导入为零。若旧 facade 调用者依赖富化结果，改为 owning service 的窄入口；不在 facade 增加方法，不留下会间接导回 service 的循环。

### D6. Redis：机制留 core，实例归拥有者

| 现有实例 | Redis DB / 前缀 | 拥有者与访问边界 |
|---|---|---|
| emby_user_defined_line_cache | 2 / `emby_user_defined_line:` | `lines.cache`，外域经 lines.service |
| emby_last_user_defined_line_cache | 2 / `emby_last_user_defined_line:` | 同上 |
| plex_user_defined_line_cache | 2 / `plex_user_defined_line:` | 同上 |
| plex_last_user_defined_line_cache | 2 / `plex_last_user_defined_line:` | 同上 |
| stream_traffic_cache | 15 / 空前缀 | `traffic.cache`，经 traffic.service 编排消费 |
| user_credits_cache | 0 / `user_credits:` | `credits.cache`；失效函数也归 credits；repository 继续登记提交后回调 |
| user_info_cache | 2 / `user_info:` | `identity.cache`，外域发布用户快照经 identity.service |
| emby_api_key_cache | 3 / `emby_api_key:` | `integrations.media_tokens` |
| plex_token_cache | 3 / `plex_token_cache:` | 同上 |

user_info 的 JSON 是用户身份/会员快照；线路选择存储在另外四个缓存中。不要因为当前周期任务在 lines 就把用户缓存归 lines，导致 identity(T0) 向上依赖。lines 的现有周期入口可以暂留，调用 identity.service 发布用户快照、lines 自己发布线路；涉及的取数留在对应 repository。已有定时 ID、节奏和入口引用不因这次所有权调整而改动。

媒体 token 缓存对外只暴露带 backend 的查询、登记和按用户名失效等窄操作，不暴露 RedisCache/连接实例。Emby 集成与 accounts/traffic 调用同一 adapter，禁止 integrations 向上导入 accounts。保留 traffic 当前逐 token 查询顺序，不借机改成 MGET 或全表扫描。

同一键空间只实例化一次；移入拥有者不意味着另建一套缓存或改前缀。冻结 DB、TTL、容量、usage tracking、大小写、JSON 字段、错误处理和网络重试。`credits` 的自登记失效、callback key 去重、提交/回滚语义必须继续有效。

这不是缓存一致性修复：identity 现有建档中的事务内 Redis 写入仍按已有调用点冻结为遗留例外，交由 `promote-account-domains` 处理。不得新增此类调用或在本次改变失败时数据库结果；不得声称移动实例已消除了该债务。其他已是提交后执行的路径不得退回事务内。

### D7. formatting、runtime 与随机数规则

**字节格式化**：保留纯通用能力，不建立 formatting 总入口。`format_bytes` 精确保留 1024 进位、B/KB/MB/GB/TB 文本、精度、零值、负值和超 TB 时的现有输出。迁移当前全部消费者，但不把告警/通知文本改成另一套格式。禁止向 byte_size 加入用户/会员、限额判断、媒体标签或配置依赖。

**媒体标签**：identity 拥有媒体身份词汇。`identity.rules.get_service_label(service: str)` 保留旧输入和 fallback，`identity.service` 暴露纯委托。不要借机把任意字符串改成严格枚举而拒绝旧输入，也不让其他领域直接导入 identity.rules。纯共享类型确实需要时可放 types，不把展示 helper 隐藏成 types 工具箱。

**私有化**：容器检测保持 `/.dockerenv` 优先、其次 `container == podman`。单例元类移入 scheduler，不修改其现有并发特性，不重建 Scheduler 实例，不改任何持久化 callable 路径。

**随机数**：`eth_rpc.latest_block_hash_int()` 保留函数名但内部契约改为原始完整 hash 整数，HTTP 超时/请求/错误不变。`treasure.rules.normalize_external_random_b` 保留掩码语义；service 在 RPC/fallback 后映射，repository 使用同一规则保护存储路径。提取 `_fallback_external_random_b` 的纯计算时显式传入 secret，不让 rules 读取 settings。

验收不仅是“在 BIGINT 范围”：对完整 256 位哈希、2^63 边界、负数、零、None、default 原样返回、HMAC fallback，比对迁移前后的最终 B、取模结果、中奖号码和入库存储。不得改成 clamp、abs、随机重取或另一种有符号转换。旧 RPC 内部返回值的改变是明确允许的内部契约变更，调用者与测试一起更新。

### D8. HTTP 适配与认证前置条件

`transport.http.schemas` 保留 TelegramUser/BaseResponse 名称、字段、Pydantic 验证与 JSON；domain schemas 的继承仍合法。不得把 HTTP Request、用户模型或 BaseResponse 放进 service/types/repository。

将中间件与 DomainError→HTTP 转换从 api 移入 transport，api 保持注册顺序、路由顺序、生命周期和静态文件设置。core.http 的出站连接与 transport.http 的入站适配是两种不同职责。

**认证迁移前置条件**：`fix-webapp-auth-bypass` 的当前分支 D1–D5 实现和测试通过后，再冻结并迁移认证代码。无需等待生产 hotfix 发布，但不能冻结当前模拟 hash 和硬编码管理员绕过。若修复尚未落地，可做其他阶段，HTTP/auth 阶段保持阻塞。

签名比较、auth_date、开发开关、负数管理员 ID、状态码与日志脱敏都以已修复版本为准。分离 pure init_data 校验不能丢失失败原因或重新引入配置分叉；不在本变更自行选择另一套有效期或开发规则。该前置条件必须有实际提交/测试证据，不能依据 OpenSpec artifact 的 done 状态推断实现完成。

### D9. legacy 配置：领域提供数据，core 提供读取机制

删除 core 中的 `MIGRATED_ENV_DEFAULTS` 业务总表、具体业务键分支和持有这张表的 `LEGACY_ENV` 实例。保留参数化 LegacyEnvSource，要求显式传入默认值和必要 codec；不要另建一个高层业务总表让 core 反向导入。

每个 owning domain 的 config 声明其旧键、旧默认值、codec 和目标字段。`app.business_config` 从 CONFIGS 收集完整描述，检测重复/冲突键，构造一个通用 legacy source，并在默认值读取/seed 前绑定到领域配置。核心依赖的是读取协议，不知道配置来自哪些领域。允许调整 LegacySource/DomainConfig 的内部注入接口，不引入 DI 框架。

必须先汇总全部声明再解析：旧解析器在某个已知键格式错误时停止继续解析，按领域各自读取会改变其他领域的结果。还要保留 data/.env → 进程环境 → 工作目录 .env → 旧默认值的优先级、逐行覆盖、错误停止、环境快照时机，以及“数据库已有值不被 seed 覆盖”。不能把旧默认值直接替换成新 Pydantic 默认值而未经等价核对。

所有运行入口和相关 CLI 在首次读取领域配置前完成绑定；测试可显式提供假 source。禁止未绑定时静默以新默认值播种。对非启动入口的现有合法用法完整盘点、迁移，禁止靠 service 向上导入 business_config 自动补初始化。只搬迁旧来源的依赖注入，不改变运行时业务配置读写语义。

### D10. 以可执行守卫防止再次退化

在 `tests/architecture/` 增加职责清单（例如 `core_ownership.toml`）与对应 AST/import-linter 测试。它是评审用数据，不在生产运行时动态发现/注册模块。

最低检查集合：

1. core 模块集合与清单双向一致；列出保留理由、公开符号和具体例外。禁止新增 business RedisCache/DomainConfig 实例、业务默认值表或万能 re-export。
2. 更新顶层层级，单独检查 transport 的下游依赖和领域角色消费矩阵；覆盖包子模块、局部/别名导入、动态导入字符串及 re-export 绕行。
3. profile_cache 不得导入 client/profiles/messaging、HTTP/Telegram 网络库；导入和查询测试禁止网络；写入 API 只供 profiles/受控测试使用。
4. repository 不依赖 Telegram cache/client/transport；rules/types 的 I/O 禁令补充 core.cache/redis/http 和 integrations/transport，不能仅禁止 SQLAlchemy。
5. 跨域不得导入另一域 cache 或直接操作实例；外部消费者经 service；媒体 token adapter 不向上导入领域。
6. core.byte_size 与 integrations.telegram.init_data 是纯模块；treasure 数值映射不再存在于 core/ETH RPC，ETH RPC 返回原始值。
7. 新职责检查零违规；既有 architecture baseline 和 contract_ignore_counts 只减不增。单独记录尚未处理的已知债务，不用一个新通配 ignore 隐藏它。
8. 守卫自身有负向 fixture：故意放入错误依赖必须被捕获。函数名/业务语义不能完全由 AST 自动证明，清单更新必须附归属理由和人工评审。

### D11. 与其他变更的交接、剩余例外

| 相关变更/现存问题 | 本变更边界 |
|---|---|
| unify-business-configuration | 以其已实现机制为基线，仅调整 legacy source 的所有权与注入，不重做配置迁移 |
| fix-webapp-auth-bypass | 认证阶段先等当前分支 D1–D5；修复拥有安全策略，本变更拥有最终路径 |
| fix-live-defects | 保留其业务错误修复；重叠文件分阶段 rebase，迁移其测试与符号路径，不夹带修复 |
| promote-account/line/remaining/reward 等 | 本变更提供缓存/资料/transport 新路径及窄 service 接口；完整领域提升仍由原变更完成 |
| move-line-catalog-to-database | STREAM_BACKEND/PREMIUM_STREAM_BACKEND 等旧目录配置仍是冻结例外；不在此迁数据库 |
| move-privileged-codes-to-database | PRIVILEGED_CODES 及已记录的 invitation 预提交 .env 写仍由该变更处理 |
| identity 建档事务内 Redis 写 | 冻结已有两处行为，不新增；由 promote-account-domains 收敛提交后一致性 |
| Telegram 两套刷新错误差异 | 保留已刻画行为；后续单独修复，不能以“去重”名义改变结果 |

core 清单必须显式列出仍保留的基础设施 settings 和上述业务配置例外；不能把“core 已纯化”理解为本次消灭了所有数据库迁移前的兼容行为。新增业务配置仍只能进领域 config。

实施收尾时更新架构文档与受影响的未实施变更引用/交接表；已归档的历史提案、历史 provenance 证据不全局改写。当前规划更新只修改本变更的三个文档。

## Alternatives considered

- **仅重命名为 database_values/http_schemas/telegram_profile**：不接受；没有解决策略归属或消费范围。
- **全部扔进 integrations 一个文件**：不接受；正确做法是供应商能力整体归属、内部模块隔离，而不是网络与缓存一起暴露。
- **新增通用 shared/common/presentation.utils**：不接受；只是移动杂物箱。字节显示有独立通用输入，媒体标签有真实领域拥有者。
- **所有 formatter 都移到 traffic 或 HTTP 层**：不接受；纯字节格式化也服务日志和 Bot，不应迫使其他领域依赖流量业务或 HTTP。
- **HTTP 模型放 api**：不接受；会反向依赖组装层。transport 不拥有业务用例。
- **所有 token 缓存放 accounts**：不接受；Emby integration 会向上依赖领域。供应商 token 映射是外部集成适配。
- **为每个文件加 Protocol/容器**：不接受；模块函数、普通值参数和必要的启动注入已经足够。
- **以“改动大”为由一次重写所有错误/缓存策略**：不接受；可以广泛调整结构，但不能失去可对照的行为边界。

## Risks / Trade-offs

- **迁移面广**：分阶段、每阶段闭合调用链并通过测试；不允许新旧两套同前缀缓存并存。
- **两套刷新与缓存读取 fallback 不一致**：特征测试分别覆盖，不以统一抽象掩盖差异。
- **服务富化改变旧 repository 的错误边界**：对损坏缓存、空数据和逐行失败建立调用链级回归，不只比较成功 JSON。
- **Redis 被仓库外网关消费**：用旧 DB/前缀/JSON 协议 fixture 校验，不改 key 或依赖实际生产网关验证。
- **配置注入次序影响首次 seed**：完整键集合、环境快照时机、多入口启动及已有 DB 值必须测试；未准备好的入口阻止该阶段完成。
- **OpenAPI 组件名随模型位置变化**：冻结并比较文档；若发现差异先修复模型引用/命名，不直接接受新快照。
- **新 transport 变成第二个 core**：禁止领域依赖、列出公开能力、按 HTTP/Bot 分模块；不接收任意业务 helper。
- **安全修复被重构回退覆盖**：安全提交在结构提交之前且独立；只回退本次结构提交，不回退安全基线。

## Migration Plan

1. 冻结当前源树、调用清单、外部输出和数据协议；记录安全阶段所需的独立前置条件。只保留路径映射用于源码快照归一化，不预先覆盖行为证据。
2. 建立职责清单与守卫负向测试；先实现 byte_size、私有 helper、identity 标签、treasure 原始 hash→业务映射这些低耦合切片。
3. 分别迁移 Redis 实例及 legacy config 注入；每个切片关闭所有调用者，不留双实例/旧转发模块。
4. 迁移 Telegram 内部分层与两套资料编排，再消除 repository 资料 I/O；保持调度入口和周期不变。
5. 在安全前置条件满足后迁移 HTTP/auth/middleware/errors、服务层结果和管理员投递适配。
6. 删除全部废弃路径；更新文档、未实施提案的交接引用、源码 provenance 的确定性路径映射。行为 fixture 不能因搬迁被重写。
7. 全量验证、预提交检查，记录所有例外和阻塞。每阶段可独立提交，但发布必须是依赖闭合且全部验收通过的集合。

无 schema/Redis 格式迁移，回退采用按依赖逆序回退本变更提交或回退到已含安全修复的前一镜像。不能承诺只需一个 Git revert；不能回退独立安全修复、修改历史迁移或清空缓存。若库存清点发现持久化 callable 指向被搬辅助函数，暂停该切片并制定显式 jobstore 引用迁移，不直接删除入口。

## Verification strategy

- 基础值测试：容器检测、单例身份、字节格式化所有边界、媒体标签任意旧输入、随机 B 的端到端等价。
- Telegram：context/URL 发送、429/client/server/network 分支、精确 retry/sleep、缓存缺失/损坏/锁/读写、单条与批量 fallback、过期读取、两套刷新流程与头像下载失败。
- Redis：九个实例的 DB/前缀/options 快照，用户 JSON、大小写、失效顺序、每 token 读取方式、callback 提交/回滚与不重复实例化。
- 配置：完整 legacy key/default/codec 清单、跨域错误停止、来源优先级、环境捕获、多入口绑定、seed 幂等和既有 DB 值保持。
- HTTP：已修复认证矩阵、原 JSON/状态码/响应模型/OpenAPI、中间件顺序和不依赖 HTTP 的 service 返回值。
- 架构：`PYTHONPATH=src .venv/bin/lint-imports --no-cache`、`.venv/bin/python -m pytest tests/architecture tests/refactor`，所有新守卫负向测试通过，baseline/ignore 不增加。
- 全量：`.venv/bin/python -m pytest tests/`、`ruff check src/ tests/`、`ruff format --check src/ tests/`、`pre-commit run --all-files`、`git diff --check`。外部服务全部替身，不触碰生产库、Redis 或 Telegram。
