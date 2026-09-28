# Tasks

## 1. 行为冻结与测试补齐

- [x] 1.1 冻结四个领域的行为快照：OpenAPI 与路由顺序、调度任务，以及每个接口每个拒绝分支的请求和响应（包括被遮蔽分支、英文兜底、被吞成 500 的情况）；把四个 mixin 的成员登记进 `mapping.toml` 并写明目标位置。验证：连续生成两次，快照一致；没有未映射的成员。
  - [x] 1.1a 面快照：新增 `scripts/refactor/activity_snapshot.py` 与冻结夹具 `tests/refactor/fixtures/activity_surface.json`（四个领域分节：13/12/8 条路由、10/12/12/8 条 OpenAPI path、2 条周期任务、具名任务与 legacy 映射、归属表、repository 类成员与模块级函数、跨域引用），`tests/refactor/test_activity_baseline.py` 8 例通过、连续生成一致。
  - [x] 1.1b 拒绝分支夹具：每个接口每个拒绝分支的请求/响应（含被遮蔽分支、英文兜底、被吞成 500 的情况）。新增 `tests/refactor/test_activity_rejections.py` 与冻结夹具 `tests/refactor/fixtures/activity_rejections.json`（164 例：41 条认证 401、20 条管理员 403、39 条 400、18 条 404、45 条 500、1 条无兜底分支），覆盖四个领域全部 42 个接口，连续生成两次一致。
  - [x] 1.1c 把四个 mixin 的成员与目标位置登记进 `scripts/refactor/mapping.toml`。44 个成员（luckywheel 5 / treasure 7 / auction 15 / prediction 17）补上 `planned_target`：三个不拆分的领域落在各自 repository，转盘的两个配置读写落在 `app.domains.luckywheel.config`，预言的成员按子主题落到 `repository.{markets,bets,settlement,analytics}`，赔率计算落在 `rules`；`tests/refactor/test_activity_baseline.py` 新增 `test_every_repository_member_has_a_reviewed_destination` 断言没有未映射的成员。
- [x] 1.2 补齐转盘测试：付费单抽、使用免费次数的单抽、十连、各类奖品（积分增减、邀请码、特权码、会员在已绑定和未绑定两种情况下）、随机性统计、用户状态。验证：新测试在当前代码上全部通过。
  - 交付：`tests/test_luckywheel_spins.py`（20 例）：付费单抽扣费与中奖、负分奖品触底截断、低于门槛拒绝、免费次数单抽免参与费并标记账本与统计来源、抽奖失败时补偿释放、十连扣 10 次参与费且不使用免费次数、十连门槛、五类积分奖品（含翻倍/减半）、普通邀请码、特权码开关只被消费一次、会员奖品在未绑定（NameError 跳过）与已绑定（写入 Plex/Emby 到期时间）两种情况、随机性统计与 0 概率过滤、用户状态与免费次数概览。
  - 验证：20 例在当前代码上全部通过（2.8s）。
- [x] 1.3 补齐夺宝、预言、竞拍测试：
  - 夺宝：参与（未满、满员开奖、各类拒绝）、创建、取消退款、自动开期的调度。
  - 预言：下注、投稿与审核、截止、开奖的三种派奖分支（记录派奖额和荣耀池变化）。
  - 竞拍：出价、创建、修改、删除、手动结束、过期兜底，并把已知缺陷的现状写成断言。

  验证：新测试在当前代码上全部通过。
  - 交付：`tests/test_treasure_flows.py`（12 例：未满参与扣费与进度通知、满员开奖与自动开期调度、开奖号码由 created_at 与 B 推导、各类拒绝不产生副作用、创建入库与通知、取消退还全部参与费、自动开期具名任务登记与克隆/跳过）、`tests/test_prediction_flows.py`（11 例：下注扣费与池/赔率更新、个人上限、已截止/未知/余额不足拒绝、投稿与审核（通过建题 +1 积分、驳回不建题）、截止、开奖的三种派奖分支（分别记录派奖额与荣耀池 4.0 / 97.0 / 5.0）、重复开奖拒绝）、`tests/test_auction_flows.py`（12 例：创建与调度、出价与各类拒绝、修改/删除、手动结束扣分、无人出价、过期兜底、启动恢复）。
  - 已知缺陷已写成断言：夺宝满员开奖的胜者查询看不见同事务未 flush 的参与行（当填满的那次参与中奖时 500 并回滚）；竞拍流拍时调用 `send_message_by_url(None, …)`；仓储 `finish_auction_by_id` 不检查 `is_active`，重复结束再扣一次分；`finish_expired_auctions` 的 `group_by` 选了未聚合的 `bidder_id`（SQLite 容忍、PostgreSQL 报错）；启动恢复只处理前 50 条。
  - 验证：33 例在当前代码上全部通过，反复运行稳定。

## 2. 调度与基础能力

- [x] 2.1 扩展 `core.scheduler.schedule_task`：支持内存 jobstore 中的具名任务，参数用 kwargs 传入，`misfire_grace_time` 必须显式传入；更新 `test_named_scheduler.py`。验证：单元测试覆盖内存 jobstore 中具名任务的调度、执行、按 id 替换、按 jobstore 删除，以及拒绝未注册的任务。
  - 交付：`schedule_task` 不再限制持久化 jobstore，改为接受 `Scheduler().jobstores` 中已存在的别名（`sqlalchemy` 默认、`default` 内存），未知别名报 `ValueError`；任务名仍作为 `run_task` 的位置参数，任务参数仍走 `kwargs`；`misfire_grace_time` 仍为必填关键字。`tests/refactor/test_named_scheduler.py` 把「拒绝内存 jobstore」改为「拒绝未注册的任务」（内存/持久化两条路径都验），新增 `test_memory_jobstore_named_task_lifecycle`（真 AsyncIOScheduler + MemoryJobStore）：调度元数据（`func is run_task`、`args`、`kwargs`、`misfire_grace_time`）、执行、同 id 替换只留一个、按 jobstore 删除不影响持久化存储。
  - 验证：`pytest tests/refactor/test_named_scheduler.py` 4 例通过。
- [x] 2.2 为领域配置的 JSON 文档存储实现 `compare_and_update(predicate, **changes)`。验证：在一次性 PostgreSQL 上，并发执行 20 次条件更新，只有一次成功。
  - 交付：依赖的 `unify-business-configuration` 未实施，按确认的选择在 `app/core/kv.py` 增加模块级事务内函数：`get_tx(session, type, key, *, for_update=False)`（列查加行锁，不经 ORM 标识映射）、`upsert_tx(session, type, key, value)`、`compare_and_update_tx(session, type, key, predicate, **changes)`（行锁内读 JSON 文档，`predicate` 为真才合并 `changes`，行不存在或文档不可解析则返回假且无副作用）；这些函数不吞异常，旧 `SystemConfigRepository` 保留原签名。单测 `tests/test_core_kv.py` 3 例；并发验证 `scripts/refactor/smoke_kv_concurrency.py` + `tests/refactor/test_kv_concurrency.py`（`KV_TEST_DATABASE_URL` 门控，子进程用过滤后的环境）。
  - 验证：在一次性 `postgres:18-alpine` 容器上 20 线程并发条件更新，连续 5 次均只有 1 次成功，文档落为 `{"gen_privileged_code": false}`；容器已销毁。
- [x] 2.3 把 ETH JSON-RPC 客户端移到 `integrations/eth_rpc.py`。验证：外部客户端隔离合约通过；夺宝的参与测试通过。
  - 交付：新增 `app/integrations/eth_rpc.py`（`latest_block_hash_int()`，只导入 `app.core`），夺宝 router 删除内嵌的 `_get_eth_latest_block_hash_int` 与 `aiohttp`/`jsonrpc` 调用，改为 `eth_rpc.latest_block_hash_int()`；1.1b/1.3 的夺宝测试改为 patch `eth_rpc.latest_block_hash_int`。
  - 验证：`PYTHONPATH=src .venv/bin/lint-imports --no-cache` 12 条合约全通过（含「External integration isolation」）；`pytest tests/test_treasure_flows.py tests/refactor/test_activity_rejections.py tests/architecture` 48 例通过。

## 3. prediction

- [ ] 3.1 把 `part_1` 和 `part_2` 按子主题搬移为 `markets.py`、`bets.py`、`settlement.py`、`analytics.py`（只搬不改），用重键脚本处理基线键，并删除 `numbered_modules` 中的两个例外。验证：`verify.py` 逐项 AST 零差异；序号模块检查通过；本次提交只含搬移、导入和基线的改动。
- [ ] 3.2 提升 prediction：
  - `rules.settle_market` 逐字保留派奖计算。
  - 结算时统计行按 `tg_id` 升序加锁；荣耀池改用 `core.kv` 的 `*_tx`。
  - 在源头抛出类型化异常。
  - service 在提交后发送通知，并使用结算返回的派奖额。
  - 截止提醒任务只调用 service。
  - 建档改用 `ensure_statistics_tx`。

  验证：
  - 1.3 中预言的全部测试通过，三种分支的派奖额和荣耀池变化逐字一致。
  - 错误映射与夹具一致。
  - 在一次性 PostgreSQL 上并发下注和开奖，不死锁。
- [ ] 3.3 在 `prediction.service` 中暴露两个排行函数；rankings 的 router 改为调用 `rankings.service` 中新增的包装函数。验证：两个排行接口的响应与夹具一致；在摘除 prediction 的 mixin 之后，排行仍然返回数据。

## 4. luckywheel

- [ ] 4.1 按 design D2 实现单事务抽奖：`rules.pick_prize` 和 `rules.prize_effects`，repository 在一个事务里完成消耗或扣费、发奖和写统计，提交后发送通知；特权码开关改用条件更新；十连在同一事务中循环。验证：
  - 1.2 的测试通过。
  - 每一步注入失败时整体回滚，免费次数恢复。
  - 并发抽中邀请码时，只发出一个特权码。
- [ ] 4.2 把账本函数改为与来源无关的命名，映射只保留一份；实现 `FreeSpinProgressProvider`，并在 `app/subscriptions.py` 中注册 21 点的实现；删除 luckywheel 对 21 点配置行和 `blackjack_hands_since_freespin` 的读取；更新 `scripts/blackjack_retention_audit.py`。验证：
  - `GET /api/luckywheel/free-spins` 和 21 点相关接口的响应与夹具一致。
  - 管理员修改 21 点的阈值后，汇总立即反映新阈值。
  - luckywheel 中不再出现 `blackjack` 的配置读取。
- [ ] 4.3 转盘的入口只调用 service，在源头抛出类型化异常，每个路由的 `except Exception` 之前先原样抛出领域异常。验证：错误映射与夹具一致；路由中不再有字符串分支。

## 5. treasure 与 auction

- [ ] 5.1 提升 treasure：service 负责编排参与、创建和取消；repository 的 `join_tx`；提交后发送通知并安排自动开期；在源头抛出类型化异常（按现状映射被遮蔽的分支）；建档改用 `ensure_statistics_tx`。验证：1.3 中夺宝的测试通过；错误映射与夹具一致；开奖结果与算法快照一致。
- [ ] 5.2 提升 auction：repository 和 service；竞拍结束改为内存 jobstore 中的具名任务 `auction.finish`；通知文案移入 notifications，所需数据由 service 传入；删除操作显式指定 jobstore。验证：1.3 中竞拍的测试通过；调度快照中只有 design D5 允许的那一项差异；重启后恢复的任务与原来一致。

## 6. 基线清理与集成验证

- [ ] 6.1 从门面删除四个领域的 mixin；按 design D6 删除 7 处显式缓存登记，并接手清除 blackjack 遗留的 18 条条目；清除 53 条基线条目，以及 21 行标给本变更的忽略项、6 行标为 B3 的忽略项和 8 行门面组合边；用重键脚本改写 3 条以 badge_awards 为目标的条目；下调封存计数。验证：`lint-imports`、`pytest tests/architecture`、`pytest tests/refactor` 通过；21 点现金局接口的响应与夹具一致；`baseline.json` 中本变更名下只剩这 3 条勋章相关的条目，blackjack 名下只剩 1 条以 badge_awards 为目标的条目（由 reward 清除）。
- [ ] 6.2 生产形态本地彩排：在完整数据库副本上，完成付费单抽、免费次数单抽、十连、夺宝满员开奖、预言开奖和竞拍结束（外部服务和通知用替身）。验证：积分、账本、奖池、荣耀池和调度的变化，与旧实现在同一份数据上的结果一致。
- [ ] 6.3 运行全量回归：`pytest tests/`、`ruff check`、`ruff format --check`、`lint-imports`、`pre-commit run --all-files`，然后运行 `openspec validate promote-activity-domains --strict`。验证：全部通过；工作区干净。
