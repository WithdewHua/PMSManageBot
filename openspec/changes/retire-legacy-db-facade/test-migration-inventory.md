# tests/refactor/ 测试文件逐项审查与迁移证据

在实施 `retire-legacy-db-facade` 的工具与文档清理时，对原 `tests/refactor/` 中的全部 61 个文件（60 个测试/辅助模块 + 夹具目录）进行了逐一审计，区分**保护当前生产行为/安全/事务边界的测试**与**历史搬迁/彩排/工作区专用工具测试**。

所有仍保护生产行为、层序约束、副作用边界、HTTP/缓存/事件/规则契约的测试，均已迁移至 `tests/` 或 `tests/architecture/`，并在混合文件中拆分提取 live 检查；对缺少单元测试的组件补充了专项护栏测试。

---

## 逐文件处置清单

| 原始路径 | 处置方式 | 目标位置 | 处置理由与包含的 live 检查 |
|---|---|---|---|
| `test_account_baseline.py` | 拆分迁移 | `tests/architecture/test_domain_layer_boundaries.py` | 静态夹具比对属于搬迁脚手架予以删除；提取 live 检查 `test_account_and_invitation_entry_points_do_not_import_legacy_facade_or_models` 保护账号/邀请入口不触碰数据层与模型。 |
| `test_activity_baseline.py` | 删除 | 无 | 针对重构脚本 `activity_snapshot.py` 和过渡 `mapping.toml` 的一次性比对，无生产代码保护逻辑。 |
| `test_activity_rehearsal.py` | 删除 | 无 | 调用已删除的 `scripts.refactor.rehearse_activity`，历史彩排封装。 |
| `test_activity_rejections.py` | **保留迁移** | `tests/test_activity_rejections.py`（及 `tests/fixtures/activity_rejections.json`、`tests/fixtures/activity_surface.json`） | 保护四大活动领域（竞拍、大转盘、大预言家、夺宝）所有接口的拒绝分支 HTTP 状态码与 detail 契约。 |
| `test_b2_assembly.py` | **保留迁移** | `tests/test_b2_assembly.py` | 保护生产 FastAPI 与 Bot 命令装配的路由与命令完整性。 |
| `test_b2_mapping.py` | 删除 | 无 | 针对已废弃的 B2 `mapping.toml` 映射覆盖率测试。 |
| `test_b3_decycles.py` | 删除 | 无 | 针对 B3 解环阶段 `mapping.toml` 的 AST 测试。 |
| `test_b3_mapping.py` | 删除 | 无 | 针对 B3 `mapping.toml` 编排搬迁映射的测试。 |
| `test_b3_provenance.py` | 删除 | 无 | 针对 B3 提交来源封存和 git worktree 的检查，历史审计工具。 |
| `test_blackjack_baseline.py` | 删除 | 无 | 针对 `blackjack_snapshot.py` 的重构比对测试。 |
| `test_blackjack_concurrency.py` | 删除 | 无 | 包装已删除的 `smoke_blackjack_concurrency.py` 脚本，生产并发由专项并发测试覆盖。 |
| `test_blackjack_cross_domain.py` | **保留迁移** | `tests/architecture/test_blackjack_cross_domain.py` | 保护 21 点跨域调用走 service 或受控 `*_tx` 辅助函数，禁止外部领域导入 blackjack 模型与 repository 部件。 |
| `test_blackjack_inventory.py` | 删除 | 无 | 针对 `blackjack_inventory.json` AST 盘点文件的校验。 |
| `test_blackjack_rehearsal.py` | 删除 | 无 | 包装已删除的 `rehearse_blackjack.py` 彩排脚本。 |
| `test_blackjack_repository_split.py` | 删除 | 无 | 针对已删除的 `split_plans.toml` 的拆包比对测试（live 拆包后的函数可用性已在 `tests/test_blackjack_repository_tx.py` 覆盖）。 |
| `test_blackjack_service_boundary.py` | **保留迁移** | `tests/architecture/test_blackjack_service_boundary.py` | 保护 21 点接口层不直接触碰数据层，跨域调用强制通过 service，路由委托 rules 计算。 |
| `test_blackjack_side_effect_boundary.py` | **保留迁移** | `tests/architecture/test_blackjack_side_effect_boundary.py` | 关键事务边界护栏：repository 内禁止副作用（Telegram/调度），路由不直发消息，锦标赛阶段推进顺序与通知提交后顺序严格冻结。 |
| `test_business_config_concurrency.py` | 删除 | 无 | 包装已删除的 `smoke_business_config_concurrency.py` 脚本。 |
| `test_business_config_rehearsal.py` | 删除 | 无 | 包装已删除的 `rehearse_business_config.py` 彩排脚本。 |
| `test_cache_ownership.py` | **保留迁移** | `tests/architecture/test_cache_ownership.py` | 保护 live 业务 Redis 缓存实例声明（9 个缓存的 DB 与 key 前缀）、`app.core.cache` 纯机制不含业务实例、业务实例不从 core 导入。 |
| `test_core_utility_baseline.py` | 拆分迁移 | `tests/test_core_utility.py` | 删除 4 个重构 JSON 快照比对测试；保留并迁移全部 11 个生产核心工具行为测试（容量字节格式化、服务标签、随机数映射、容器检测、调度器单例、RedisCache 机制、LegacyEnvSource 优先级与 Telegram URL 发送器验证/重试/限流/拒绝及资料缓存空读取）。 |
| `test_credit_concurrency.py` | 删除 | 无 | 包装已删除的 `smoke_credit_concurrency.py` 脚本。 |
| `test_credit_inventory.py` | 删除 | 无 | 针对 `credit_inventory.json` 的盘点测试。 |
| `test_credit_migration.py` | 删除 | 无 | 针对已删除的 `check_credit_migration.py` 迁移工具的测试。 |
| `test_domain_event_boundaries.py` | **保留迁移** | `tests/architecture/test_domain_event_boundaries.py` | 保护领域事件订阅收敛：`subscribe` 仅限 `app.subscriptions` 组装层调用，`app.core.events` 不导入领域模块。 |
| `test_gift_pack_baseline.py` | 删除 | 无 | 针对 `gift_pack_snapshot.py` 和 `mapping.toml` 的一次性比对。 |
| `test_gift_pack_concurrency.py` | 删除 | 无 | 包装已删除的 `smoke_gift_pack_concurrency.py` 脚本。 |
| `test_gift_pack_http_contract.py` | **保留迁移** | `tests/test_gift_pack_http_contract.py`（及 `tests/fixtures/gift_pack_http_contract.json`） | 保护礼包用户端领取（各类拒绝与成功）及管理端 8 个 API 的冻结 HTTP 响应契约。 |
| `test_gift_pack_rehearsal.py` | 删除 | 无 | 包装已删除的 `rehearse_gift_pack.py` 彩排脚本。 |
| `test_gift_pack_split.py` | 删除 | 无 | 针对已删除的 `mapping.toml` 和 `split_plans.toml` 的拆包比对测试。 |
| `test_identity_compat.py` | 拆分迁移 | `tests/test_identity_cache_boundary.py` | 保留并迁移 `test_identity_cache_write_is_post_commit_only`（验证事务回滚不污染 `user_info_cache`，提交后正常写入）以及兼容层无 SQL 导入与元组形状保全。 |
| `test_inventory.py` | 删除 | 无 | 针对 `scripts/refactor/inventory.py` 工具的测试。 |
| `test_job_references.py` | 删除 | 无 | 针对已删除的 `rewrite_job_refs.py` 的测试。 |
| `test_kv_concurrency.py` | 删除 | 无 | 包装已删除的 `smoke_kv_concurrency.py` 脚本。 |
| `test_legacy_config_ownership.py` | **保留迁移** | `tests/test_legacy_config_ownership.py` | 保护业务配置负向与约束测试：遗留默认值重现、冲突默认值在绑定前拒绝、未绑定 DomainConfig 禁止静默 seed、core.legacy_env 不含业务全局实例。 |
| `test_line_baseline.py` | 删除 | 无 | 针对 `line_snapshot.py` 和 `mapping.toml` 的重构基线测试。 |
| `test_line_catalog_concurrency.py` | 删除 | 无 | 包装已删除的 `smoke_line_catalog_concurrency.py` 脚本。 |
| `test_luckywheel_concurrency.py` | 删除 | 无 | 包装已删除的 `smoke_luckywheel_concurrency.py` 脚本。 |
| `test_manage_cli.py` | **保留迁移** | `tests/test_manage_cli.py` | 保护 `app.manage` 手工运维 CLI（`rebind-tg-id`、`report`）功能与调用面。 |
| `test_metadata_pg.py` | **保留迁移** | `tests/test_metadata_pg.py` | 保护 PostgreSQL 元数据对比工具（`scripts/verify/check_metadata_pg.py`）无 live DB 依赖的功能。 |
| `test_model_registry.py` | **保留迁移** | `tests/test_model_registry.py` | 保护集中式 ORM 模型注册表在表创建前正确装配全部模型。 |
| `test_named_scheduler.py` | **保留迁移** | `tests/test_named_scheduler.py` | 保护命名任务注册、分发、持久化拦截守卫及内存生命周期。 |
| `test_prediction_concurrency.py` | 删除 | 无 | 包装已删除的 `smoke_prediction_concurrency.py` 脚本。 |
| `test_prediction_repository_split.py` | 删除 | 无 | 针对已删除的 `split_plans.toml` 的预测领域仓储拆解测试。 |
| `test_privileged_codes_rehearsal.py` | 删除 | 无 | 包装已删除的 `rehearse_privileged_codes.py` 彩排脚本。 |
| `test_rehearse_line_catalog.py` | 删除 | 无 | 包装已删除的 `rehearse_line_catalog.py` 彩排脚本。 |
| `test_relocate.py` | 删除 | 无 | 针对重构搬迁引擎 `scripts/refactor/relocate.py` 的 34 个单元测试。 |
| `test_remaining_baseline.py` | 删除 | 无 | 针对 `remaining_snapshot.py` 与 `mapping.toml` 的重构基线测试。 |
| `test_remaining_rehearsal.py` | 删除 | 无 | 针对 `remaining_rehearsal.py` 彩排框架的测试。 |
| `test_repository_telegram_boundary.py` | **保留迁移** | `tests/architecture/test_repository_telegram_boundary.py` | 保护所有领域 repository 严禁包含 Telegram 客户端/缓存/网络 I/O 依赖，必须暴露稳定 ID 供上层组装。 |
| `test_rewrite_baseline_keys.py` | 删除 | 无 | 针对已删除的 `rewrite_baseline_keys.py` 工具的 21 个单元测试。 |
| `test_rewrite_refs.py` | 删除 | 无 | 针对已删除的 `rewrite_refs.py` 工具的 19 个单元测试。 |
| `test_schedule_registry.py` | **保留迁移** | `tests/test_schedule_registry.py` | 保护声明式调度注册表完整声明 32 项周期任务。 |
| `test_seed_mapping.py` | 删除 | 无 | 针对已删除的 `seed_mapping.py` 工具的测试。 |
| `test_snapshot.py` | **保留迁移** | `tests/test_snapshot.py` | 保护行为快照生成工具（`scripts/verify/snapshot.py`）无 DB 运行及确定性。 |
| `test_split_repository.py` | 删除 | 无 | 针对已删除的 `split_repository.py` 工具的测试。 |
| `test_telegram_boundaries.py` | **保留迁移** | `tests/test_telegram_boundaries.py` | 保护 Telegram 集成拆分职责、init_data 签名校验无 settings 依赖、资料缓存本地性与职责隔离。 |
| `test_tg_rebind_backends.py` | **保留迁移** | `tests/test_tg_rebind_backends.py` | 保护 Telegram ID 换绑事务在 SQLite FK 模式与 PostgreSQL 中的幂等与约束。 |
| `test_treasure_random_rules.py` | **保留迁移** | `tests/test_treasure_random_rules.py` | 保护夺宝随机数 B 纯计算规则、HMAC fallback 密钥显式传递、RPC 返回原始哈希映射。 |
| `test_verify.py` | 删除 | 无 | 针对已删除的 `verify.py` 重构校验脚本的 25 个单元测试。 |
| `tg_rebind_backends.py` | **保留迁移** | `tests/tg_rebind_backends.py` | 换绑测试专用的可抛弃数据库后端支持类。 |

---

## 针对性补充的专项防护测试

为彻底覆盖审查指出的边界与缺口，新增了 3 个专项测试文件：

1. **`tests/test_credits_cache_only.py`**
   - 静态 AST 检查：`user_credits_cache` 仅在 `app.domains.credits` 内部导入和操作，外部领域严禁绕过积分服务直接操作缓存。
   - 运行时测试：校验 DB 0 与 `user_credits:` 前缀；验证 `invalidate_user_credits` 对批处理 keys 的有序去重删除。

2. **`tests/test_emby_client.py`**
   - 纯单元与 Mock 测试：测试 `Emby` 客户端的添加用户（成功、用户已存在、改密失败、网络超时异常分支）、修改密码、查询用户 ID、用户名查询及本地文件缓存与过期刷新。
   - 完全隔离生产：缓存重定向到临时目录，网络请求全部打桩，杜绝任何外部调用。

3. **`tests/architecture/test_rules_config_boundary.py`**
   - 规则与集成边界负向测试（项目规则 #239、#240）：
     - AST 扫描：所有 `src/app/domains/**/rules.py` 严禁导入 `DomainConfig`、`app.core.domain_config` 或领域 `config.py`，必须通过入参接收配置值。
     - AST 扫描：所有 `src/app/integrations/**/*.py` 严禁导入 `DomainConfig` 或 `app.core.domain_config`。
     - 架构扫描器负向用例：对合成代码验证 `scan_config_access` 能精准捕获 rules 越权读配置、integrations 越权读配置以及跨领域越权写配置。

---

## 路径与无假绿（False Green）保障

- 所有位于 `tests/` 的测试使用 `ROOT = Path(__file__).resolve().parents[1]`，位于 `tests/architecture/` 的测试使用 `ROOT = Path(__file__).resolve().parents[2]`。
- 每个文件均添加了 `assert (ROOT / "src/app").is_dir()` 显式断言，杜绝父路径解析偏差导致的静默扫空目录假绿。
