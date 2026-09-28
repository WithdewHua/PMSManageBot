# Tasks

## 1. 基础设施

- [ ] 1.1 在 `core/kv.py` 中新增模块级函数：`get`、`get_tx`（支持 `for_update`）、`upsert_tx`、`insert_if_absent_tx`、`delete_tx`，都不吞异常；旧的 `get_system_config` 和 `set_system_config` 改为调用它们，但保留原有的返回语义。验证：单元测试覆盖区分"没有这一行"与"读取出错"、`insert_if_absent_tx` 撞唯一约束时回读对方的值、upsert 的幂等性。
- [ ] 1.2 实现 `core/domain_config.py`，按 design D2 提供：
  - `get`、`get_tx`、`update`、`seed`。
  - `FieldRows` 和 `JsonDocument` 两种存储。
  - 进程内缓存：提交后失效，30 秒 TTL 兜底。
  - 数值字段拒绝 bool；读取出错时抛出；存储内容无法解析时返回默认值，且不改写原始数据。

  验证：单元测试覆盖以上每一条；在一次性 PostgreSQL 上并发修改同一领域的两个字段，两项都保留；在事务回滚后缓存不变。
- [ ] 1.3 隔离测试环境：`tests/conftest.py` 在导入 `app` 之前把 `DATA_DIR` 指向临时目录，并清除迁出键和列表键的环境变量；新增 `business_config` 夹具。验证：新增一个测试断言仓库里的 `data/.env` 没有被读取；在 `data/.env` 被故意改坏时，全量测试仍然通过。

## 2. 现有 `SystemConfig` 配置迁移

- [ ] 2.1 把 21 点配置改为 `blackjack/config.py` 中的 `DomainConfig` 声明，使用 `JsonDocument` 存储，合并规则为浅合并、`tournament_defaults` 整体替换；奖池、游标等状态键常量移到 blackjack 的 repository 常量；删除"读取出错时写入默认值"的路径；用 `business_config` 夹具替换测试中对 `get_blackjack_config_dict` 的 5 处 patch。验证：用同一份已保存的配置，升级前后读到的字典逐字相同；读取出错时不写入；21 点全部测试通过。
- [ ] 2.2 把转盘配置和随机性参数改为 `luckywheel/config.py` 中的 `DomainConfig` 声明，去掉 `RandomnessConfig` 的进程级类属性。验证：`GET`/`PUT /api/luckywheel/config` 和 `/randomness-config` 的响应与冻结夹具一致；随机性 PUT 仍然合并任意键；配置损坏时按默认值运行，原始数据不被改写。
- [ ] 2.3 把勋章中心配置改为 `FieldRows` 存储，声明旧键 `badge_center/enabled` 和 `badge_center/message` 以及各自的编解码，两次写入合并为一个事务。验证：`GET`/`POST /api/badges/config` 的响应与夹具一致；中途写入失败时两项都不变。
- [ ] 2.4 把 `SystemConfigRepository` 的 19 处调用（`db.` 2 处、`self.` 17 处）改为调用 `core.kv` 的模块函数，从 `DatabaseORM` 中删除这个 mixin，同步删除对应的门面组合忽略项并下调封存计数。验证：`lint-imports`、`pytest tests/architecture` 通过；门面上查不到 `get_system_config` 和 `set_system_config`。

## 3. 业务配置声明与初值迁移

- [ ] 3.1 从 `core/config.py` 中抽出旧加载器的解析逻辑，逐字保留，作为 `LegacyEnvSource`，只读取迁出的键。验证：对比测试给定同一份 `data/.env`、环境变量和工作目录 `.env`，旧 `Settings` 与 `LegacyEnvSource` 取得的值逐项相同；用例覆盖坏行中止、重复键、`KEY = v`、bool 和列表的解析，以及四级优先级。
- [ ] 3.2 按 design D1 在 10 个领域的 `config.py` 中声明业务配置；`main.py` 在初始化数据库之后、启动服务之前调用 `seed_all()`，`get()` 遇到缺失项时也按同样规则插入；启动时发现旧键仍在就记警告；在 `docs/architecture.md` 的"配置分类"中写入 D1 的归属表。验证：
  - 首次启动写入的值与旧 `Settings` 一致。
  - 重复启动不改写任何行。
  - 数据库已有值、而 `.env` 值不同时，数据库的值保持不变。
  - 旧键残留时出现警告日志。
- [ ] 3.3 在 `tests/architecture/checks.py` 中加入跨域读取配置的规则：service 和 repository 可以调用其他领域配置的 `get` 或 `get_tx`；`update` 和 `seed` 只能由配置所属领域调用；rules 和 integrations 不能读配置。验证：规则的正反例测试通过；`pytest tests/architecture` 通过。

## 4. 读取点与现有接口迁移

- [ ] 4.1 迁移 accounts 和 invitation：注册开关、邀请积分、`GET /api/invite/register-status`，并让 `/set_register` 改为持久化。验证：2 个开关接口和邀请积分接口在缺字段、真值解释、拒绝 bool 或负数、写入失败时的行为都有测试，响应与夹具一致；`/set_register` 修改后，重建配置缓存（模拟重启）仍然保留，回复文案不变。
- [ ] 4.2 迁移 premium、lines 和 traffic：`premium_free` 归 lines，两个流量额度归 traffic，会员相关的键归 premium；`CREDITS_COST_PER_10GB` 改为由 service 传给 `premium.rules`；premium admin_router 经 service 写入其他领域的配置；修复 `/settings/emby-premium-free`。验证：
  - 这些接口的行为测试通过，包括"由开变关时的后台解绑任务"。
  - 兼容接口不再返回 500。
  - 会员流量扣费的计算结果与原实现一致。
- [ ] 4.3 迁移其余读取点：
  - media_access 的解锁价格和 `nsfw_libs`：由调用方把 NSFW 媒体库传给 integrations。
  - credits 的转账开关。
  - donation、crypto_donation 和 custom_lines 读取的捐赠倍率。
  - vaultwarden 的两项。
  - crypto_donation 的币种列表。
  - `reports/constants.py` 和 `traffic/jobs.py` 改为调用时读取。

  验证：各领域现有测试通过；新增测试证明修改配置后，下一次调用就使用新值，不需要重新导入模块。
- [ ] 4.4 改造 `GET /api/admin/settings` 和 `GET /api/system/status`，经 reports.service 读取各领域配置。验证：两个接口原有的键和取值与夹具一致。
- [ ] 4.5 从 `Settings` 中删除迁出的字段，设置 `extra="ignore"`；更新 `.env.example`；修正 AGENTS.md 中配置优先级的描述。验证：AST 扫描确认 `src` 中不再读取任何迁出的 `settings` 字段；工作目录 `.env` 里残留旧键或未知键时，应用仍能启动。

## 5. 新增后台设置与前端

- [ ] 5.1 按 design D6 新增 6 个设置接口：新建 `crypto_donation/admin_router.py` 和 `vaultwarden/admin_router.py`，并挂载到各领域原有路由之后；设置总览增加 6 个键。验证：
  - OpenAPI 与冻结快照相比只多出这 6 个操作。
  - 每个接口的成功、校验失败和写入失败都有测试。
  - 修改捐赠倍率后，已有积分不变，之后登记的捐赠按新倍率计算。
  - 关闭 Vaultwarden 后，兑换请求立即按"功能关闭"处理。
- [ ] 5.2 前端：在 `adminService.js` 中新增 6 个调用，在 `Management.vue` 的设置区新增控件：两个列表用可输入的多选 chips，三个数值用数字输入框，一个开关；保存失败时显示 `message` 并回滚控件的值。验证：`npm run lint` 和 `npm run build` 通过；在本地逐项手动验证保存成功、失败回滚和总览回显。

## 6. 回退工具与遗留函数

- [ ] 6.1 新增只读脚本 `scripts/export_business_config.py`，把数据库中的业务配置按旧键名导出为 `.env` 片段。验证：测试证明导出的片段写入 `data/.env` 后，旧版 `Settings` 读到的值与数据库中的值一致；脚本不写数据库。
- [ ] 6.2 核对 `save_current_config` 和 `get_saveable_config` 不在手动运维清单中，经维护者确认后删除；如果确认要保留，就修正敏感键名单，并登记进 `docs/architecture.md` 的手动运维清单。验证：确认结论记录在本变更中；`src` 中不再有会把密钥写进 `.env` 的代码路径。

## 7. 集成验证

- [ ] 7.1 全量回归：运行 `pytest tests/`、`ruff check`、`ruff format --check`、`lint-imports`、`pre-commit run --all-files`。验证：全部通过；除了新增的 6 个操作外，OpenAPI 与冻结快照一致。
- [ ] 7.2 在一次性 PostgreSQL 上运行并发修改测试，并用 `check_metadata_pg.py` 做元数据比对。验证：两项同时修改都保留；元数据没有差异。
- [ ] 7.3 生产形态本地彩排：分别用旧版本和新版本启动同一份数据库副本和 `data/.env`；在后台修改几项配置后重启；运行导出脚本后回退到旧版本。验证：
  - 新版本种子日志中的每一项都等于旧版本的生效值。
  - 修改立即生效，重启后保留。
  - 回退后，旧版本读到导出的值。
- [ ] 7.4 运行 `openspec validate unify-business-configuration --strict`。验证：校验通过；工作区干净。
