# Tasks

## 1. 行为冻结与测试补齐

- [ ] 1.1 冻结四个领域的行为快照：OpenAPI 与路由顺序、调度任务，以及每个接口每个拒绝分支的请求和响应（包括被遮蔽分支、英文兜底、被吞成 500 的情况）；把四个 mixin 的成员登记进 `mapping.toml` 并写明目标位置。验证：连续生成两次，快照一致；没有未映射的成员。
- [ ] 1.2 补齐转盘测试：付费单抽、使用免费次数的单抽、十连、各类奖品（积分增减、邀请码、特权码、会员在已绑定和未绑定两种情况下）、随机性统计、用户状态。验证：新测试在当前代码上全部通过。
- [ ] 1.3 补齐夺宝、预言、竞拍测试：
  - 夺宝：参与（未满、满员开奖、各类拒绝）、创建、取消退款、自动开期的调度。
  - 预言：下注、投稿与审核、截止、开奖的三种派奖分支（记录派奖额和荣耀池变化）。
  - 竞拍：出价、创建、修改、删除、手动结束、过期兜底，并把已知缺陷的现状写成断言。

  验证：新测试在当前代码上全部通过。

## 2. 调度与基础能力

- [ ] 2.1 扩展 `core.scheduler.schedule_task`：支持内存 jobstore 中的具名任务，参数用 kwargs 传入，`misfire_grace_time` 必须显式传入；更新 `test_named_scheduler.py`。验证：单元测试覆盖内存 jobstore 中具名任务的调度、执行、按 id 替换、按 jobstore 删除，以及拒绝未注册的任务。
- [ ] 2.2 为领域配置的 JSON 文档存储实现 `compare_and_update(predicate, **changes)`。验证：在一次性 PostgreSQL 上，并发执行 20 次条件更新，只有一次成功。
- [ ] 2.3 把 ETH JSON-RPC 客户端移到 `integrations/eth_rpc.py`。验证：外部客户端隔离合约通过；夺宝的参与测试通过。

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
