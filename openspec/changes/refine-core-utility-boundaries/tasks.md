# Tasks

本清单实施 design D1–D11 的完整职责收敛方案，不是简单路径替换。所有任务初始未完成；外部行为以冻结证据为准，内部接口允许按设计调整。每阶段关闭其全部调用链并验证后再提交，不并行修改正在冻结/审核的同一范围。

## 1. 基线、调用者和阶段前置条件

- [x] 1.1 记录实施基线提交、相关变更落地情况和完整 AST/import 清单，覆盖 core 全模块、局部/别名/动态导入、source/tests/scripts、manual operations、scheduler callable；记录每个旧符号的消费者、目标与契约。验证：`core_utility_inventory.json` 覆盖 18 个 core 模块、828 条直接导入和 782 条动态引用；D2 每项均有处置条目，手动入口/持久化 callable 复核见 `core_utility_handoff.json`。
- [x] 1.2 在旧实现上建立行为基线：字节/标签/容器/单例、随机 B、九个 Redis 实例及 JSON 协议、legacy 配置、Telegram 两套刷新/发送/缓存、repository 富化的成功和失败边界。验证：`tests/refactor/test_core_utility_baseline.py` 的 20 个特征测试通过；Telegram/Redis/legacy 行为均使用替身或本地临时文件，已知 legacy `.env` 首个坏值停止解析行为被明确断言。
- [x] 1.3 冻结 HTTP/Bot 输出、OpenAPI、调度表、Redis 选项/前缀及源码 surface/provenance。验证：`core_utility_behavior_baseline.json` 与 `core_utility_provenance_baseline.json` 分离生成；前者冻结运行时输出，后者仅承载源码引用。
- [x] 1.4 建立与其他变更的实施交接表，明确 HTTP 阶段等待 fix-webapp-auth-bypass 当前分支 D1–D5 的提交和测试证据，其他阶段可独立推进。验证：`core_utility_handoff.json` 明确 HTTP 阶段仍阻塞、当前无实现 commit/测试证据，且 core/domain 阶段可独立推进。

## 2. 职责清单和边界守卫骨架（D1–D3、D10）

- [x] 2.1 增加 tests/architecture/core_ownership.toml 或等效职责清单，覆盖保留/迁出/私有化、公开符号、允许依赖及有限遗留例外。验证：`test_core_ownership.py` 对 18 个 live core 模块做双向比对，并对未登记模块/业务实例执行负向断言；清单仅作为测试输入，不参与运行时注册。
- [x] 2.2 为 transport、域内 cache 角色、Telegram 子模块、跨域缓存和 rules/types 纯性编写边界检查及负向 fixture；补齐包子模块、局部/别名导入和 re-export 检查。验证：`test_core_ownership.py` 覆盖 core 上层依赖、transport/integration 合成违规、业务实例注册和 `core.__init__` re-export；当前迁移前状态不提前启用尚未闭合切片的零违规断言。

## 3. 基础值与单消费者私有化（D2、D7）

- [x] 3.1 将 SystemUtils.is_container 私有化到 core.config，将 SingletonMeta 私有化到 core.scheduler；迁移全部消费者并删除旧模块。验证：`test_core_utility_baseline.py` 覆盖容器优先级与 Scheduler 单例身份，scheduler/schedule 回归 8 passed，`src/app/core/system.py` 与 `singleton.py` 已删除且持久化任务引用未变化。
- [x] 3.2 创建 core.byte_size.format_bytes，迁移所有 format_traffic_size 消费者。验证：20 个 core baseline 测试覆盖 0、负数、1024、超 TB 和文案；premium/watch_rewards 已迁移，`core.byte_size` 无配置/领域/网络导入。
- [x] 3.3 将 get_service_label 放到 identity.rules 并经 identity.service 暴露；迁移 lines/media_access/premium 等消费者，删除 core.formatting。验证：identity rules 保留旧字符串/大小写/icon fallback，lines/media_access/premium 通过 `identity.service` 调用，`core/formatting.py` 已删除且无运行时转发层。

## 4. 夺宝规则回归领域（D7）

- [x] 4.1 将 normalize_external_random_b 和边界常量移到 treasure.rules；必要时将 fallback 纯计算移入 rules 并显式传入 secret。验证：`test_treasure_random_rules.py` 覆盖 None/default、负值、低 63 位及完整 256-bit 输入；fallback 只接收显式 secret，rules 不读 settings。
- [x] 4.2 让 eth_rpc.latest_block_hash_int 返回原始完整哈希整数；迁移 treasure service/repository 的业务映射并删除 core.number。验证：service 在 repository 前完成完整哈希映射，treasure repository 使用领域 rules，RPC 源码回归确认返回原始整数；`core/number.py` 已删除且无 live import。

## 5. Redis 实例所有权（D6）

- [x] 5.1 将四个线路缓存迁入 lines.cache、stream_traffic_cache 迁入 traffic.cache，提供所需窄 service API 并迁移 premium/jobs/router 等调用者。验证：四个线路实例位于 `lines.cache`，traffic 实例位于 `traffic.cache`，premium 通过窄 service API，原 DB/前缀/options 由 `test_cache_ownership.py` 对照冻结清单。
- [x] 5.2 将 user_credits_cache 与 invalidate_user_credits 迁入 credits.cache，迁移 service/repository/jobs。验证：credits repository 回归与 `test_credit_repository.py` 的提交/回滚/去重用例通过，cache ownership 测试确认只有一份实例。
- [x] 5.3 将 user_info_cache 迁入 identity.cache，提供 identity.service 的快照发布接口；迁移 lines 周期写入，拆清用户 JSON 与线路缓存职责。验证：`identity.service.publish_user_info_snapshot` 保持原 JSON 序列化，lines job 不再导入 identity cache 实例，线路缓存与用户 JSON 已分离。
- [x] 5.4 将 Emby API key/Plex token 缓存迁入 integrations.media_tokens，提供查询、登记、失效等窄 API，迁移 Emby/accounts/traffic。验证：`media_tokens` 仅暴露查询/登记/失效函数，accounts/traffic/Emby 已迁移，DB3 键前缀和逐 token 查询顺序由 ownership baseline 覆盖。
- [x] 5.5 清理 core.cache 的全部具体实例与业务失效函数，仅保留 RedisCache/Lua 等机制。验证：`core/cache.py` 不再实例化 RedisCache 或声明业务键，`test_cache_ownership.py` 确认九个键空间各只有一个拥有者；现有 Redis 外部协议未改写。

## 6. 业务默认值与 legacy source 注入（D9）

- [x] 6.1 将业务旧键/默认值/codec/字段映射声明迁到各领域 config；core.legacy_env 改为必须显式传入数据的通用读取器，去掉业务总表、具体键分支及全局业务实例。验证：`core_legacy_defaults_baseline.json` 与 14 个 domain config 的 18 个旧键逐键相等；core 源码无业务 registry/global instance。
- [x] 6.2 调整 LegacySource/DomainConfig 内部注入接缝，由 app.business_config 汇总完整键集合、检测冲突并在读取/seed 前绑定；迁移所有实际启动、CLI、脚本和测试入口。验证：`test_legacy_config_ownership.py` 覆盖冲突拒绝、未绑定 seed 拒绝、单一 source 绑定；main/rehearsal/snapshot/test 入口改从 `app.business_config` 获取装配实例。
- [x] 6.3 对完整配置加载链做回归。验证：`tests/test_legacy_env.py`、`tests/test_business_config.py`、`tests/test_domain_config.py`、`tests/test_config_isolation.py` 共 17 个配置回归通过，覆盖优先级、逐行覆盖/坏值停止、已有 DB 值、幂等 seed 与缓存失效。

## 7. Telegram 内聚与内部隔离（D4）

- [x] 7.1 创建 integrations.telegram 包及独立 profile_cache，迁移本地读写/显示名/头像查询。验证：`test_core_utility_baseline.py` 与 `test_telegram_boundaries.py` 保持 pickle/lock、int/str fallback、缺文件行为；profile_cache 无网络客户端导入。
- [x] 7.2 创建 client 和 messaging，迁移资料/头像/下载原语、context 发送、URL 发送。验证：Telegram URL sender 的 payload、非法输入、终止状态与 429 retry/sleep 特征测试通过；client/messaging 不在导入时初始化网络连接。
- [x] 7.3 将 core 单用户刷新和 profile.service 的批量刷新迁入 profiles，保留两个具名编排函数；profile.service 只准备用户 ID 并调用。验证：单用户/批量具名函数均保留，`test_telegram_boundaries.py` 确认 profile service 只准备 ID 并委托，profile 基线覆盖 24 小时与本地缓存边界。
- [x] 7.4 迁移服务、路由、jobs、通知的资料消费者，保留现有 profile jobs/调度注册入口；暂未闭合的 repository/管理员发送调用由第 8、9 组完成。验证：src 下无可执行 `app.core.telegram` import，profile/notification/route/job 消费者已按 profiles/messaging/admin 分流。

## 8. repository 退出 Telegram 资料 I/O（D5）

- [x] 8.1 按完整清单处理返回值富化（至少 treasure、donation）：repository 返回事实，service 读取资料并还原展示字段；旧 facade 消费者转向 owning service。验证：treasure participation、prediction bets、donation registration 的展示字段由 service 富化；相关流程套件通过，service 未执行 SQL。
- [x] 8.2 处理 gift_pack 用户解析等需要资料与数据库联合匹配的操作：service 预读普通值快照，repository 在原事务内使用该快照。验证：`gift_pack.service.admin_resolve_users` 读取普通 dict 快照后传入 repository；混合 ID/media/Telegram 用户名解析与歧义测试通过，repository 不导入 profile cache。
- [x] 8.3 处理 lines/media_access 等只为日志取名字的路径，改用稳定 tg_id；删除其余 repository Telegram 依赖。验证：`test_repository_telegram_boundary.py` 覆盖单文件和 repository 包，确认无 Telegram/cache/Redis import、无 profile I/O helper，用户流程回归通过。

## 9. HTTP、认证与管理员投递（D3、D5、D8）

- [x] 9.1 核验安全前置条件，记录 fix-webapp-auth-bypass 当前工作树 D1–D5 的实现与测试结果并重新冻结已修复的认证基线。验证：`tests/test_webapp_auth_security.py` 9 passed；开发开关、签名/时效、管理员 ID、401 响应、session 密钥及日志脱敏均已覆盖；按用户要求不创建中间提交，最终与本结构变更一起提交。
- [x] 9.2 创建 transport.http.schemas/auth 和 integrations.telegram.init_data，迁移 HTTP 模型、认证适配和显式参数的纯校验。验证：`TelegramUser`/`BaseResponse` 已迁移；init_data verifier 只接收显式 token/max_age/now，不读取 settings 或抛 HTTPException；认证回归 9 passed。
- [x] 9.3 将 API middleware/error adapter 迁入 transport.http，由 api 保持原顺序注册；删除旧实现路径并更新消费者。验证：`transport/http/middleware.py` 与 `errors.py` 已接管注册，旧 `api/middlewares.py`/`api/errors.py` 已删除，API assembly 顺序保持；transport 未导入领域或装配层。
- [x] 9.4 清理 lines.service 等 HTTP 模型消费者，使用普通参数及本领域纯结果，由 router 包装响应。验证：lines service 的认证绑定流程改为普通参数与 `(success, message)`；service/repository/rules/types 无 transport.http import；123 项受影响流程回归通过。
- [x] 9.5 创建 transport.telegram.admin，迁移部署管理员群发；业务调用经各领域 notifications，普通投递使用 messaging。验证：管理员负数 ID 顺序/失败继续行为由 `test_webapp_auth_security.py` 覆盖；lines/premium/media_access/gift_pack 管理通知经各自 notifications，普通消息使用 integrations.telegram.messaging。

## 10. 删除旧入口并启用完整守卫（D10）

- [x] 10.1 删除 core.system/singleton/formatting/number/auth/schemas/telegram 及已迁出的 API adapter 路径，清除旧缓存实例和 LEGACY_ENV/MIGRATED_ENV_DEFAULTS 的运行时引用。验证：旧 core/API 文件已删除；`src` 无旧可执行导入；现有 Telegram、配置、领域回归通过；历史 mapping/provenance 仅作为冻结证据保留。
- [x] 10.2 更新 import-linter 顶层层级、外部集成隔离、领域角色、纯值模块及 cache 边界；启用所有职责清单/AST/负向 fixture 检查。验证：12/12 import-linter contracts、40 architecture tests、core ownership/cache/Telegram 负向检查通过；无新增通配豁免。
- [x] 10.3 仅更新受影响源码 surface/provenance 的确定性路径/符号映射，并用原行为 fixture 做对照。验证：core utility runtime/provenance snapshot 已重新生成；B2 mapping 与 core utility 行为/Telegram/缓存边界回归通过。

## 11. 文档、交接与最终验证

- [x] 11.1 更新 docs/architecture.md 与 AGENTS.md 的 core 准入、transport 角色、cache 所有权、HTTP 模型规则、格式化归属和配置装配约定；更新受影响的未实施变更引用及 D11 交接表。验证：文档已记录 core/transport/cache/HTTP 边界，D11 handoff 已标记当前工作树的认证前置证据。
- [x] 11.2 执行 `PYTHONPATH=src .venv/bin/lint-imports --no-cache`、`.venv/bin/python -m pytest tests/architecture tests/refactor`、针对性行为套件。验证：lint-imports 12/12、architecture 40 passed、refactor 276 passed/11 skipped；配置、认证、Telegram、cache 与领域针对性套件 137 passed。
- [x] 11.3 执行 `.venv/bin/python -m pytest tests/`、`ruff check src/ tests/`、`ruff format --check src/ tests/`、`pre-commit run --all-files`、`git diff --check`、`openspec validate refine-core-utility-boundaries --strict`。验证：全量 753 passed/11 skipped；Ruff、pre-commit、diff-check、strict validation 全部通过。AFT diagnostics 为 0，但大量文件没有可用 LSP producer 报告，未将该诊断替代测试证据。
- [x] 11.4 记录阶段提交、兼容证据、例外与回退顺序。验证：`core_utility_handoff.json` 已记录无中间提交、单次最终提交、HTTP/OpenAPI/Bot/Redis 兼容证据、无 schema/Redis 格式迁移及回退顺序；发布集合依赖闭合，安全修复和历史迁移明确不回退。
