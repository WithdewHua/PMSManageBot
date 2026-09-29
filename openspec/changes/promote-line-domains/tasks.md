# Tasks

## 1. 行为冻结与测试基座

- [ ] 1.1 在 test extra 中加入 `fakeredis`，并为网关缓存、流量队列和 token 缓存建立测试夹具；冻结五个领域的 OpenAPI 与路由（包括按函数名挂载的清单）、调度任务、Redis 写入（键、值和 JSON 键序）、通知文案；把各 mixin 的成员和 custom_lines 的 SQL 位置登记进 `mapping.toml` 并写明目标位置。验证：连续生成两次，快照一致；没有未映射的成员。
- [ ] 1.2 补齐 lines 和 traffic 的测试：
  - lines：线路列表（Emby 与 Plex 的差异）、绑定与解绑的 Redis 写入、认证绑定、调度的增删改、解锁扣分、生效调度的选择（跨越午夜、优先级）、自动切换（包括 "auto" 字面量、没有调度时不回退）。
  - traffic：两种日志格式的解析与入库去重、月度聚合与清理、改名合并、每日流量与排行。

  验证：新测试在当前代码上全部通过。
- [ ] 1.3 补齐 custom_lines、premium、media_access 的测试：
  - custom_lines：全部状态流转、三个定时任务、月度结算公式。
  - premium：购买的价格和折扣、到期、临期、统计、额度与欠额的查询。
  - media_access：NSFW 解锁和锁定（含退款比例）、下载解锁。

  `fix-live-defects` 已修复的缺陷用修复后行为断言冻结。验证：新测试在当前代码上全部通过。

## 2. traffic 与 lines

- [ ] 2.1 提升 traffic：新增 service（每日流量、高级线路统计、排行、改名）；日志解析和 `event_hash` 改为纯函数；采集、聚合、清理和 `_get_line_monthly_traffic` 移入 repository；从门面摘除 `TrafficRepository`，并提供转发兼容层 `TrafficCompat`。验证：1.2 中 traffic 的测试通过；采集任务的批大小、确认和推回行为不变；调度快照一致。
- [ ] 2.2 实现 lines 的目录接口，把 lines、premium、traffic、reports 中读写目录的地方都改为调用它；`is_binded_premium_line` 改为纯函数；新增架构检查，禁止在 lines 以外读取目录配置。验证：目录相关接口和 `GET /api/admin/settings` 的响应与夹具一致；架构检查的正反例测试通过。
- [ ] 2.3 在 `identity/rules.py` 中实现三种会员口径的纯函数，把 lines、media_access 和 gift_pack 的调用点改为调用与原来相同口径的函数。验证：每个调用点都有对照测试，覆盖到期时间缺失和无法解析的情况，结果不变。
- [ ] 2.4 提升 lines：改为模块级 repository；service 编排绑定、解绑、认证绑定、调度和自动切换；网关缓存集中在 `gateway_cache.py`；自动切换先读后写，每人一个事务；lines 的模型从 `profile/schemas.py` 搬回；经维护者确认后删除 7 个没有调用方的方法；从门面摘除 mixin，并提供 `LinesCompat`。验证：1.2 中 lines 的测试通过；fakeredis 中的键和值与夹具逐字一致；OpenAPI 不变。

## 3. custom_lines

- [ ] 3.1 为 custom_lines 新建完整的 repository，把路由、管理员路由、任务和 service 中的 SQL 全部移入；每次状态变更在一个事务里完成，解绑和通知在提交后执行；三个定时任务不再在打开的 session 里 await 网络；结算公式移入 rules，积分改用 `add_tx`；模型从 `profile/schemas.py` 搬回。验证：
  - 1.3 中 custom_lines 的测试通过。
  - 在 Telegram 发送时注入失败，已提交的状态不回滚。
  - 结算的积分和通知与夹具一致。
  - custom_lines 的入口不再导入 SQLAlchemy、`core.db` 或 models。

## 4. premium 与 media_access

- [ ] 4.1 提升 premium：repository 为模块级函数，并新增 `update_traffic_debt_tx`；删除 service 中的 SQL 和 B1 桥接；购买改为单事务（扣分和授予），提交后同步权限；三个任务由 service 编排；用对照测试证明两份"解绑会员线路"的实现等价后，统一改用 `lines.service.unbind_premium_line`；管理员路由中的目录接口改为调用 lines 的目录函数；用 `PremiumAccountNotBound` 替换 `NameError` 信号。验证：
  - 1.3 中 premium 的测试通过。
  - 购买时注入扣分失败，不会授予会员。
  - `premium` 中不再导入 `app.databases`，也没有 SQL。
- [ ] 4.2 提升 media_access：NSFW 的解锁和锁定改为"事务、提交后同步、失败补偿"；下载解锁改为单事务，并检查影响行数；`caculate_credits_fund` 改为纯函数；经维护者确认后删除 `update_all_lib`。验证：
  - 1.3 中 media_access 的测试通过。
  - 媒体服务器失败时，积分和标志都恢复到操作之前。
  - 补偿也失败时，有 error 日志和管理员通知。
- [ ] 4.3 把 watch_rewards 中写会员欠额的 6 处原生 SQL，改为调用 `premium.repository.update_traffic_debt_tx`（在 reward 变更之前先完成这个替换）；把 accounts 写 `all_lib` 的地方改为调用 media_access 的 `*_tx`。验证：观看结算和绑定的测试通过；`watch_rewards` 和 `accounts` 中不再有写会员列和 `all_lib` 列的 SQL。

## 5. 基线清理与集成验证

- [ ] 5.1 删除 lines 和 media_access 中对 `register_cache_invalidation` 的 2 处显式调用（design D8）；清除本变更名下的基线条目（199 条，其中 15 条 `credits.types` 条目已由礼包变更清除）、65 条忽略项、门面组合边和门面冻结的放行项；兼容层的组合边注释改为 retire 负责；下调封存计数；更新 `test_b3_decycles` 中对函数路径的引用。验证：`lint-imports`、`pytest tests/architecture`、`pytest tests/refactor` 通过；`baseline.json` 中不再有本变更名下的条目。
- [ ] 5.2 生产形态本地彩排：在完整数据库副本上，依次完成线路绑定与自动切换、会员购买与到期任务、NSFW 与下载解锁、自建线路上线与月度结算、流量采集一批日志（外部服务用替身，Redis 用隔离实例）。验证：数据库和 Redis 的变化，与旧实现在同一份数据上的结果一致。
- [ ] 5.3 运行全量回归：`pytest tests/`、`ruff check`、`ruff format --check`、`lint-imports`、`pre-commit run --all-files`，然后运行 `openspec validate promote-line-domains --strict`。验证：全部通过；工作区干净。
