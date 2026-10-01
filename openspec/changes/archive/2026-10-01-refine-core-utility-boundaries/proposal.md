# Proposal

## Why

`restructure-backend-architecture` 将旧公共工具迁入 `app.core`，解决了目录与向下依赖问题，但没有完全解决职责归属。当前 `core` 同时容纳通用连接机制、HTTP 认证与响应模型、Telegram 资料及网络请求、夺宝随机数规则、媒体展示词汇、具体 Redis 缓存实例，以及旧业务配置默认值。只把这些文件重命名为 `runtime`、`database_values`、`http_schemas`、`telegram_profile`，会把原来的杂物箱变成数个较小的杂物箱。

需要按“谁拥有语义、谁决定变化”重划边界，而不是按“是否共享、是否本地 I/O”归类。目标不是把 core 清空，而是让它只提供可复用机制，并用可执行的准入与依赖规则防止业务策略再次下沉。

## What Changes

- 为现有每个 core 模块建立明确的保留、迁出或私有化决定；新增模块必须登记职责、公开能力、允许依赖和消费者，禁止通过增加 ignore 或通配白名单绕过边界。
- 保留数据库/Redis/HTTP 连接、通用缓存算法、调度、日志、通用配置存储、共享错误基类等基础机制；具体业务缓存、键空间及失效策略回到拥有者。
- 拆掉 `core.formatting`：通用字节格式化成为 `core.byte_size.format_bytes`；Plex/Emby 展示词汇归 `identity.rules`，通过 `identity.service` 提供给外域。只有一个消费者的容器检测和单例元类分别私有化到 config 与 scheduler。
- 将随机数 B 的低 63 位映射归还 `treasure.rules`；ETH RPC 接口提供原始区块哈希整数，调用端负责业务映射。允许修改内部函数契约，冻结最终 B、存储值和开奖结果。
- 将 Telegram 接入整体归入 `integrations.telegram`，在包内隔离请求、消息投递、资料刷新与本地资料缓存。缓存读取永不隐式联网，也不因超过 24 小时而丢弃旧值。覆盖现存单用户和批量两套刷新流程，不暗中统一不同的失败语义。
- 新增边界受限的 `transport.http`，承接 HTTP 认证适配、用户/响应模型、中间件及错误转换；`api` 仍只负责应用装配。服务层改用领域参数和结果，不再接收 HTTP 用户模型或返回 HTTP 响应包装。
- 将管理员收件人选择放在 `transport.telegram` 的部署级通知适配中，Telegram 客户端只执行投递；业务通知条件与文案留在领域 notifications。
- 将业务 Redis 实例按实际职责分别归入 lines、traffic、credits、identity，以及媒体 token 集成缓存；跨域访问通过 service，禁止直接操作别人的实例。保留 Redis DB、前缀、JSON、TTL、大小写和外部网关协议。
- 从 `core.legacy_env` 移除具体业务键及默认值，由领域 config 声明、`app.business_config` 汇总注入通用读取器；保留旧配置来源优先级、顺序解析和已存在数据库配置不被覆盖的行为。
- 移出 repository 中的 Telegram 缓存读取：返回数据库事实，在 service/notifications 补充名称和头像；用户名解析等需要结合数据库和缓存的流程，先由 service 读取缓存，再将普通值快照传入 repository。
- 同步架构文档、导入合约、AST 检查与冻结快照。每一阶段先刻画行为，再迁移和验证；不创建旧路径转发层，不顺带重写所有领域。

### Compatibility boundary

这是架构重构，不是新业务功能。HTTP/Bot 响应、OpenAPI、认证策略、数据库结构、Redis 对外格式、Telegram 请求与重试、缓存读取/刷新行为、随机数计算结果和配置优先级保持不变。内部模块路径、参数/返回类型、辅助函数命名和启动注入方式可以调整；诊断日志可使用稳定的 `tg_id` 代替为日志额外读取缓存。

认证部分以 `fix-webapp-auth-bypass` 在当前分支完成的安全修复为前置基线，不把现有绕过问题冻结为目标行为，不把安全修复夹进机械搬迁。已知刷新错误、事务内缓存写等独立行为缺陷不在本变更中静默修复，详见 design 的交接与限制。

## Capabilities

### New Capabilities

<!-- 无新增外部能力；公共设施边界由 design 和架构回归检查约束。 -->

### Modified Capabilities

<!-- 现有外部需求不变，继续使用 skip_specs: true。若实施中需要改变错误策略或外部契约，暂停并单独规划，不通过更新快照掩盖变化。 -->

## Impact

- 修改 `src/app/core/` 中 auth、schemas、telegram、formatting、number、system、singleton、cache、legacy_env，以及通用配置注入接缝。
- 新增 `src/app/transport/` 和 `src/app/integrations/telegram/`；调整 API 装配、ETH RPC 和媒体 token 缓存调用。
- 影响 identity、lines、traffic、credits、treasure、profile 及现有认证/通知/资料查询消费者；新增必要的窄 service API，不删除整个 DatabaseORM 门面。
- 调整 `app.business_config` 与相关启动/CLI 装配、领域配置声明、架构合约和测试、冻结行为/源码快照、`docs/architecture.md` 与 `AGENTS.md`。
- 与 `fix-webapp-auth-bypass`、`fix-live-defects`、`unify-business-configuration` 以及后续领域提升共享文件；按 design 的阶段前置条件串行处理重叠部分。
- 无数据库迁移、Redis 数据搬迁、前端功能改动或新配置开关；不新增依赖注入框架、事件总线、通用 shared/common 包。
