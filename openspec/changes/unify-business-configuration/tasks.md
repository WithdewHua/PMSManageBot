# Tasks

## 1. 基础设施

- [x] 1.1 在 `core/kv.py` 中新增模块级函数：`get`、`get_tx`（支持 `for_update`）、`upsert_tx`、`insert_if_absent_tx`、`delete_tx`，都不吞异常；旧的 `get_system_config` 和 `set_system_config` 改为调用它们，但保留原有的返回语义。验证：`tests/test_core_kv.py` 6 passed，覆盖缺失值与读取异常区分、唯一键冲突回读胜者、upsert 幂等性和删除语义。
- [x] 1.2 实现 `core/domain_config.py`，按 design D2 提供：
  - `get`、`get_tx`、`update`、`seed`。
  - `FieldRows` 和 `JsonDocument` 两种存储。
  - 进程内缓存：提交后失效，30 秒 TTL 兜底。
  - 数值字段拒绝 bool；读取出错时抛出；存储内容无法解析时返回默认值，且不改写原始数据。

  验证：`tests/test_domain_config.py` 7 passed，覆盖两种存储、缓存 TTL/失效、严格数值和异常/损坏数据语义；并发与事务回滚验证随 7.2 集成测试完成。
- [x] 1.3 隔离测试环境：`tests/conftest.py` 在导入 `app` 之前把 `DATA_DIR` 指向临时目录，并清除迁出键和列表键的环境变量；新增 `business_config` 夹具。验证：`tests/test_config_isolation.py`、`tests/test_core_kv.py`、`tests/test_domain_config.py` 共 14 passed；测试进程不会读取仓库 `data/.env`。

## 2. 现有 `SystemConfig` 配置迁移

- [x] 2.1 把 21 点配置改为 `blackjack/config.py` 中的 `DomainConfig` 声明，使用 `JsonDocument` 存储，合并规则为浅合并、`tournament_defaults` 整体替换；奖池、游标等状态键常量移到 blackjack 的 repository 常量；删除"读取出错时写入默认值"的路径；用 `business_config` 夹具替换测试中对 `get_blackjack_config_dict` 的 5 处 patch。验证：`tests/test_blackjack_config.py` 2 passed，blackjack 全套 125 passed；损坏文档保持原文不变，状态键已移至 repository constants。
- [x] 2.2 把转盘配置和随机性参数改为 `luckywheel/config.py` 中的 `DomainConfig` 声明，去掉 `RandomnessConfig` 的进程级类属性。验证：luckywheel 测试 41 passed；转盘配置使用 `WHEEL_CONFIG`，随机性使用可扩展 `RANDOMNESS_CONFIG`，条件开关仍由 `core.kv` 事务函数处理，损坏文档保持原文不改写。
- [x] 2.3 把勋章中心配置改为 `FieldRows` 存储，声明旧键 `badge_center/enabled` 和 `badge_center/message` 以及各自的编解码，两次写入合并为一个事务。验证：`tests/test_badges_config.py` 2 passed，旧键编解码和中途写入失败的整事务回滚均已覆盖。
- [x] 2.4 把 `SystemConfigRepository` 的 19 处调用（`db.` 2 处、`self.` 17 处）改为调用 `core.kv` 的模块函数，从 `DatabaseORM` 中删除这个 mixin，同步删除对应的门面组合忽略项并下调封存计数。验证：blackjack/luckywheel/badges/lines/watch_rewards 回归通过；`DatabaseORM` 不再组合 `SystemConfigRepository`，业务代码不再调用旧方法，inventory/baseline 已重生成。

## 3. 业务配置声明与初值迁移

- [x] 3.1 从 `core/config.py` 中抽出旧加载器的解析逻辑，逐字保留，作为 `LegacyEnvSource`，只读取迁出的键。验证：`tests/test_legacy_env.py` 3 passed，覆盖重复键、`KEY = v`、bool/列表解析、数据目录 > 环境 > 工作目录 > 默认值优先级及坏行兼容语义。
- [x] 3.2 按 design D1 在 10 个领域的 `config.py` 中声明业务配置；`main.py` 在初始化数据库之后、启动服务之前调用 `seed_all()`，`get()` 遇到缺失项时也按同样规则插入；启动时发现旧键仍在就记警告；在 `docs/architecture.md` 的"配置分类"中写入 D1 的归属表。验证：
  - 首次启动写入的值与旧 `Settings` 一致。
  - 重复启动不改写任何行。
  - 数据库已有值、而 `.env` 值不同时，数据库的值保持不变。
  - 旧键残留时出现警告日志。
- [x] 3.3 在 `tests/architecture/checks.py` 中加入跨域读取配置的规则：service 和 repository 可以调用其他领域配置的 `get` 或 `get_tx`；`update` 和 `seed` 只能由配置所属领域调用；rules 和 integrations 不能读配置。验证：新增 config-access AST 正反例通过；architecture **35 passed**，当前源码 `config_access` baseline 为 0。

## 4. 读取点与现有接口迁移

- [x] 4.1 迁移 accounts 和 invitation：注册开关、邀请积分、`GET /api/invite/register-status`，并让 `/set_register` 改为持久化。验证：`tests/test_accounts_invitation_config.py` 覆盖持久化读取、缓存重建和 StrictInt 拒绝 bool；原有邀请码/账号回归通过。
- [x] 4.2 迁移 premium、lines 和 traffic：`premium_free` 归 lines，两个流量额度归 traffic，会员相关的键归 premium；`CREDITS_COST_PER_10GB` 改为由 service 传给 `premium.rules`；premium admin_router 经 service 写入其他领域的配置；修复 `/settings/emby-premium-free`。验证：premium/lines/traffic 配置 accessor 与 admin 写入完成，Premium 结算规则不再读 `settings`，相关回归通过。
  - 这些接口的行为测试通过，包括"由开变关时的后台解绑任务"。
  - 兼容接口不再返回 500。
  - 会员流量扣费的计算结果与原实现一致。
- [x] 4.3 迁移其余读取点：
  - media_access 的解锁价格和 `nsfw_libs`：由调用方把 NSFW 媒体库传给 integrations。
  - credits 的转账开关。
  - donation、crypto_donation 和 custom_lines 读取的捐赠倍率。
  - vaultwarden 的两项。
  - crypto_donation 的币种列表。
  - `reports/constants.py` 和 `traffic/jobs.py` 改为调用时读取。

  验证：各领域现有测试通过；新增测试证明修改配置后，下一次调用就使用新值，不需要重新导入模块。
- [x] 4.4 改造 `GET /api/admin/settings` 和 `GET /api/system/status`，经 reports.service 读取各领域配置。验证：新增 `reports.service.get_business_config_overview()`，两个接口保留原有键并追加 6 个新设置键。
- [x] 4.5 从 `Settings` 中删除迁出的字段，设置 `extra="ignore"`；更新 `.env.example`；修正 AGENTS.md 中配置优先级的描述。验证：源码扫描无迁出字段读取，旧业务键仅由 `LegacyEnvSource` 用于种子，配置文档与示例已更新。

## 5. 新增后台设置与前端

- [x] 5.1 按 design D6 新增 6 个设置接口：新建 `crypto_donation/admin_router.py` 和 `vaultwarden/admin_router.py`，并挂载到各领域原有路由之后；设置总览增加 6 个键。验证：新增 cost/nsfw/donation/crypto/vaultwarden 设置端点并完成 API assembly 挂载，settings overview 增加对应 6 个键。
  - OpenAPI 与冻结快照相比只多出这 6 个操作。
  - 每个接口的成功、校验失败和写入失败都有测试。
  - 修改捐赠倍率后，已有积分不变，之后登记的捐赠按新倍率计算。
  - 关闭 Vaultwarden 后，兑换请求立即按"功能关闭"处理。
- [x] 5.2 前端：在 `adminService.js` 中新增 6 个调用，在 `Management.vue` 的设置区新增控件：两个列表用可输入的多选 chips，三个数值用数字输入框，一个开关；保存失败时显示 `message` 并回滚控件的值。验证：`npm run lint`、`npm run build` 通过；控件更新失败会重新拉取总览并回滚。

## 6. 回退工具与遗留函数

- [x] 6.1 新增只读脚本 `scripts/export_business_config.py`，把数据库中的业务配置按旧键名导出为 `.env` 片段。验证：`tests/test_export_business_config.py` 证明脚本按旧键名导出且不写数据库。
- [x] 6.2 核对 `save_current_config` 和 `get_saveable_config` 不在 `docs/architecture.md` 手动运维清单中；两者无代码调用方，已删除，保留仍被特权码和线路目录使用的 `save_config_to_env_file`。

## 7. 集成验证

- [x] 7.1 全量回归：运行 `pytest tests/`、`ruff check`、`ruff format --check`、`lint-imports`、`pre-commit run --all-files`。验证：全量测试 695 passed/11 skipped，refactor 232 passed/11 skipped，Ruff、lint-imports、pre-commit 全部通过；OpenAPI 仅增加 6 个后台设置操作。
- [x] 7.2 在一次性 PostgreSQL 上运行并发修改测试，并用 `check_metadata_pg.py` 做元数据比对。验证：`smoke_business_config_concurrency.py` 保留两个并发字段更新，metadata differences 为 `[]`。
- [x] 7.3 生产形态本地彩排：使用一次性 PostgreSQL 与临时 `data/.env` 副本完成旧值种子、重启后缓存重建、后台修改持久化、导出并由 `LegacyEnvSource` 回读。验证：`rehearse_business_config.py` 成功，14 个配置声明完成种子，修改后的值可立即读取、缓存重建后保留，导出的 18 个旧键可回读。
- [x] 7.4 运行 `openspec validate unify-business-configuration --strict`。验证：校验通过；提交后工作区保持干净。
