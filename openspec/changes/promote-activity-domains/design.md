# Design

## Context

动机见 proposal.md。本设计假定以下变更已完成：

- `promote-blackjack-domain`：21 点已提升。免费次数的消耗、释放、汇总和周配额计数，已经从 21 点搬进 luckywheel 的 repository 和 service。
- `promote-gift-pack-domain`：已提供 premium 的 `grant_premium_days_tx`、invitation 的 `issue_codes_tx`、`types` 跨域角色、积分 `*_tx` 的缓存失效自登记、基线重键脚本和序号模块检查（其中登记了 prediction 的两个 part 文件）。
- `unify-business-configuration`：转盘配置和随机性参数已是 `luckywheel.config` 中的领域配置；`core.kv` 已有 `*_tx` 函数。

现状（调研时的 `3f27100`）：

**luckywheel**

- 共 1,600 行：router 930、repository 约 600、models、schemas、service。
- 11 个接口，其中 5 个管理员接口。
- `execute_single_spin` 一次抽奖至少 6 个独立事务：
  1. 扣参与费。
  2. 选奖。
  3. 中了邀请码、且特权码开关打开时，读出整份配置、改写开关、写回。
  4. `calculate_credits_change` 在计算中直接发邀请码或会员。会员经 `premium.service.update_premium_status(db, …)`，未绑定的服务靠 `except NameError` 跳过。
  5. 增减积分。
  6. 读余额。
  7. 写抽奖统计，失败只返回 False。
  8. 逐个私信管理员。
- 单抽先认领免费次数，失败时再补偿释放；十连不使用免费次数。
- 免费次数汇总直接读 21 点的配置行和 `statistics.blackjack_hands_since_freespin`。
- "来源 → 抽奖统计来源"的映射有两份：router 和 repository 各一份。
- 函数名仍带 `blackjack`，但作用于所有来源。
- 9 处 `raise ValueError`；router 有 19 个 `except Exception`。

**treasure**

- 7 个接口，其中 2 个管理员接口。
- 参与流程：
  1. 在事务之前取 ETH 区块哈希。ETH JSON-RPC 客户端内嵌在 router 里。
  2. 满员时用 `TG_API_TOKEN` 做 HMAC 作为兜底。
  3. 在一个事务里依次：锁期数 → 锁统计行 → 扣费 → 分配号码 → 满员则开奖发奖。
  4. 提交后，router 直接 await 通知，并安排具名的自动开期任务。
- repository 有 18 处 `raise ValueError`；router 有 13 行按文本分支：
  - "user stats not found" 被 "not found" 遮蔽，实际返回 404"期数不存在"。
  - 同一条"not active"消息，在参与和取消两个接口中的文案不同。
  - 另有 3 处兜底返回英文原文。
- 没有统计行时，直接构造 `Statistics(credits=…)`。

**prediction**

- repository 分为 `part_1`（732 行）和 `part_2`（339 行）；11 个接口，其中 4 个管理员接口，另有 1 个按管理员身份过滤。
- 通知都在提交之后发送：下注、创建、投稿由 router 直接 await；开奖由 BackgroundTasks 发送，其中每个人的派奖额在 router 里又按公式算了一遍。
- 审核通过后另开事务给投稿人加 1 分，失败只记警告。
- 结算的加锁顺序：题目 → 荣耀池（kv 行，余额以字符串存储）→ 按 IN 列表锁统计行（不排序）。
- 23 处 `raise ValueError`；router 有 11 行按文本分支，另有 6 处兜底返回英文原文，还有两处把 400 吞成 500。
- `jobs.py` 直接查询模型并发群通知。
- rankings 经门面调用两个排行方法，扫描器没有把它们计入基线。
- 结算中也会直接构造 `Statistics`。

**auction**

- 13 个接口，其中 10 个管理员接口。repository 失败时返回 False 或 None；router 没有文本分支。
- 结束任务在内存 jobstore 中按函数引用调度，任务 id 为 `finish_auction_{id}`，添加 3 处、删除 3 处，删除时都不指定 jobstore。
- `restore_auction_schedules` 作为 ON_STARTUP 同步执行，最多恢复 50 条。
- `auction/notifications.py` 会查数据库；通知发到 `TG_CHANNEL_ID`。

**调度 API**

`schedule_task` 只允许持久化 jobstore；`test_named_scheduler.py:153-160` 专门断言传入内存 jobstore 会被拒绝。

**基线**

- 本变更名下 56 条。其中 3 条以 badge_awards 为目标，由 reward 处理。
  - 另有 23 条以 `credits.types` 为目标，会在 `promote-gift-pack-domain` 放行 `types` 角色时被清除。
  - auction、prediction、treasure 共有 7 处显式调用 `credits.service.register_cache_invalidation`（分别为 2、2、3 处）。
- pyproject 中标给本变更的忽略项 21 行；标为 B3 的 prediction.jobs 忽略项 6 行；门面组合边 8 行。
- `promote-blackjack-domain` 已经完成，但名下还有 36 条。礼包变更会清除其中 17 条 `credits.types` 条目，reward 会清除 1 条以 badge_awards 为目标的条目。其余 18 条没有后续变更负责：
  - repository 中 8 处显式调用 `register_cache_invalidation`，以及对 `credits.service` 的导入（调研时分布在 6 个文件中）。
  - 现金局路由直接调用 `credits.service.read_optional` 读取余额（2 处），并为此导入 `credits.service`。
  - repository 中的 `award_or_renew_badge` 直接写 `UserBadge`。冠军勋章已经改由 `badges.service` 颁发，这个函数和它在 `repository/__init__.py` 中的导出都没有调用方。

**测试**

四个路由都没有 API 级测试；除 21 点相关的免费次数用例外，业务流程基本没有覆盖。

**已由 `fix-live-defects` 修复，以下行为由本变更冻结**

- 竞拍无人出价时安全完成流拍并发送流拍通知，不调用空的接收人。
- `finish_expired_auctions` 的聚合查询兼容 PostgreSQL。
- 结束竞拍按 `is_active` 条件加锁并保证单次结算。
- 启动恢复处理全部未结束的活动竞拍，不再限制前 50 条。
- 夺宝自动开期幂等，并在启动和补救扫描中恢复遗漏期数。

## Goals / Non-Goals

**Goals：**

- 四个领域达到提升模板的目标形态；路由中没有业务流程、通知、调度和字符串分支；领域异常能原样穿过路由的兜底分支。
- 转盘单次抽奖的数据库影响在一个事务里完成；luckywheel 不再读取 21 点的数据；免费次数账本与来源无关。
- 竞拍结束改为具名任务，放在内存 jobstore 中，时间、id 和恢复行为都不变。
- 预言的排行留在 prediction，作为分析函数暴露；rankings 通过自己的 service 调用。
- 清空本变更名下的基线条目（勋章相关的 3 条除外，保留给 reward），以及 prediction 的序号模块例外；并接手清除 blackjack 遗留的 18 条。

**Non-Goals：**

- 不移动勋章触发调用；只随行号变化重写基线键。
- 不再重复修复 Context 中列出的缺陷；它们已由 `fix-live-defects` 修复，本变更只冻结修复后的行为。
- 不改奖池、派奖、赔率和开奖算法，也不改通知文案和接收人。
- 不迁移转盘和夺宝的排行，由 `promote-remaining-domains` 处理。

## Decisions

### D1 类型化异常：在源头抛出，逐接口冻结映射

- **在源头抛出**：每个领域新增 `exceptions.py`，基类是 `<Domain>Error(DomainError, ValueError)`。repository 和 service 在产生拒绝的地方，直接抛出带稳定错误码的子类，不再构造英文消息让上层翻译。这与 21 点试点中"按消息子串表翻译"的做法不同：那样只是把字符串匹配挪了个位置。
- **状态码和文案在抛出处确定**：同一种拒绝在不同接口中的状态码或文案不同时，由 service 在抛出点决定，例如夺宝"not active"在参与和取消两个接口中的文案不同。
- **被遮蔽的分支**：按现状的实际结果映射。例如夺宝参与时缺少统计行，映射为 404"期数不存在"。
- **英文原文兜底**：用 `detail` 保留原来的英文文本。
- **router 的写法**：每个 `except Exception` 之前加上 `except DomainError: raise`，由全局处理器输出原来的响应；原来把 400 吞成 500 的接口已由 `fix-live-defects` 恢复原状态码和文案，本变更冻结修复后的映射。
- **冻结映射**：实施前，为每个接口的每个拒绝分支生成请求和响应的夹具。实施后逐项比对。

### D2 转盘：单事务抽奖与账本唯一入口

- **单事务**：`luckywheel.service.spin(tg_id, *, use_free_spin)` 在一个事务里完成：
  1. `consume_free_spin_tx`，锁定一条可用的免费次数；或者 `credits.repository.deduct_tx` 扣参与费。
  2. `rules.pick_prize(config, randomness)`。
  3. 发放奖品：积分用 `add_tx` 或 `deduct_tx`；邀请码用 `invitation.repository.issue_codes_tx`，特权码时 `privileged=True`；会员天数用 `premium.repository.grant_premium_days_tx`，未绑定的服务跳过，与现状相同。
  4. 写入抽奖统计。
  5. 提交后发送管理员通知，每条单独 try，与现在一致。

  任何一步失败都整体回滚，免费次数会自动恢复，不再需要补偿释放。十连抽在同一个事务里循环 10 次，仍然不使用免费次数。
- **拆分 `calculate_credits_change`**：它原来一边计算一边发奖，现在拆成两部分：纯函数 `rules.prize_effects(prize)` 只算出要做什么；repository 负责执行。
- **特权码开关**：开关仍存在转盘配置里，由 `luckywheel.config` 在配置行锁内做条件更新：只有开关为真时才把它改为假，并返回是否成功。第 3 步中，只有更新成功的那一次抽奖才发特权码，其余按普通码发放。这需要给领域配置的 JSON 文档存储补上 `compare_and_update(predicate, **changes)`，本变更负责实现，并配 PostgreSQL 并发测试。
- **账本与来源无关**：
  - 函数改名为 `consume_free_spin`、`release_free_spin`、`free_spin_summary`。21 点的通知任务调用的函数不改名，保持 `blackjack.service` 对外的名字不变。
  - "来源 → 抽奖统计来源"的映射只保留一份，放在 `luckywheel/constants.py`，发放时写进账本行的快照。
- **21 点的进度**：luckywheel 定义进度查询的接口 `FreeSpinProgressProvider`，由 `app/subscriptions.py` 注册 21 点的实现 `blackjack.service.free_spin_progress`。`free_spin_summary` 按来源调用已注册的提供者，没有注册时这部分字段为空。这样消除了"luckywheel 读取 21 点的配置和列"这一数据层面的反向依赖，而阈值仍然是实时读取的，与现状相同。

备选方案：

- **由 21 点在每次结算时把进度快照写进 luckywheel 的表**：需要新表和迁移；管理员修改阈值后，快照要等到下一手才更新，改变了现在"实时读取"的表现。
- **luckywheel 直接导入 21 点的配置模块**：21 点已经依赖 luckywheel，这会形成导入环。

### D3 夺宝

- **ETH 客户端**：移到 `integrations/eth_rpc.py`，只导入 core。
- **service 编排**（`treasure.service.join(...)`）：
  1. 在事务外取区块哈希。
  2. repository 的 `join_tx`：锁期数、锁统计行、扣费、分配号码、满员则开奖发奖。
  3. 提交后发送进度或开奖通知，并用 `schedule_task` 安排自动开期。
- **创建**：同样由 service 在提交后发送群通知。
- **建档**：没有统计行时，改用 `identity.repository.ensure_statistics_tx`，再用 `credits.repository.add_tx` 加分，结果与原来的直接构造相同。

### D4 预言

- **按子主题重组**（先搬移，后改造，与礼包的做法相同）：
  - `markets.py`：投稿、审核、创建、查询。
  - `bets.py`：下注、下注列表、持仓。
  - `settlement.py`：截止、开奖、荣耀池。
  - `analytics.py`：个人统计、排行及其共用的已结算题目信息。

  完成后删除 `numbered_modules` 中登记的两个例外。
- **结算**：
  - 统计行按 `tg_id` 升序加锁，这与 credits 转账的锁顺序一致。
  - 荣耀池改用 `core.kv.get_tx(for_update=True)` 和 `upsert_tx`，存储格式（字符串）不变。
  - 三种派奖分支、可能为负的手续费和舍入余差，都原样搬进 `rules.settle_market(...)`，结果逐字不变。
  - service 用结算结果中每个人的派奖额发送通知，删除 router 中重复的公式。
- **审核**：审核通过后给投稿人加 1 分，仍然放在提交之后、尽力而为，与现状相同。
- **截止提醒任务**：`jobs.py` 只调用 service，查询移进 repository。
- **排行**：`analytics.py` 提供两个排行函数，由 `prediction.service` 暴露；rankings 的 router 改为调用 `rankings.service` 中新增的两个包装函数，这是合法的"service 调 service"。这两处调用原来不在基线里，改造后也不会产生新的违规。
- **建档**：没有统计行时，同样改用 `ensure_statistics_tx`。

### D5 竞拍与具名任务

- **扩展 `core.scheduler.schedule_task`**：
  - 允许 `jobstore="default"`，也就是内存 jobstore，此时只接受已注册的具名任务，参数用 kwargs 传入。
  - `misfire_grace_time` 必须显式传入。
  - 更新 `test_named_scheduler.py` 中"拒绝内存 jobstore"的断言，改为"拒绝未注册的任务"。
- **注册与调度**：
  - 在 `schedule.py` 的 `TASKS` 中注册 `auction.finish`，指向 `auction.jobs.finish_single_auction`，参数为 `auction_id`。这发生在 API 线程启动之前。
  - 3 个调度点改由 service 调用 `schedule_task("auction.finish", run_date=end_time, job_id=f"finish_auction_{id}", kwargs={"auction_id": id}, misfire_grace_time=60, jobstore="default", replace_existing=True)`。其中 `misfire_grace_time=60` 与现在继承的默认值相同。
  - 3 个删除点都显式指定内存 jobstore。
- **启动恢复**：`restore_auction_schedules` 仍在 ON_STARTUP 中执行，恢复全部未结束的活动竞拍，过滤条件保持不变。
- **通知**：文案移入 `notifications.py`，所需数据由 service 传入，通知模块不再查库；仍然发到频道。
- **调度快照**：比对结果中只允许这一项差异：竞拍任务的函数由原函数引用变为 `run_task`，参数改为具名任务名加 kwargs。

### D6 基线与合约

- **重键**：勋章触发调用所在的 3 个路由会大幅改写，这 3 条以 badge_awards 为目标的条目用重键脚本改写到新行号，负责变更保持不变。
- **清除**：
  - 其余 53 条基线条目（其中 23 条 `credits.types` 条目已由礼包变更清除）。
  - 21 行标给本变更的忽略项、6 行标为 B3 的 prediction.jobs 忽略项、8 行门面组合边。
  - 从门面删除四个领域的 mixin。
- **显式缓存登记**：礼包变更之后，credits 的 `*_tx` 会自己登记提交后的缓存失效。删除 auction、prediction、treasure 中 7 处对 `register_cache_invalidation` 的显式调用；删除前确认对应的积分写入都经过 `*_tx`。不把这些调用搬进 service。
- **接手 blackjack 的遗留条目**（Context 中的 18 条）：
  - 用同样的方式删除 blackjack repository 中 8 处显式登记，以及随之不再需要的 `credits.service` 导入。
  - 现金局路由改为调用 `blackjack.service` 读取余额，由 service 调用 `credits.service.read_optional`；响应不变。
  - 删除 blackjack repository 中没有调用方的 `award_or_renew_badge` 及其导出，并修正 `blackjack/service.py` 中指向它的注释。
  - 这些条目的负责变更不改，直接删除即可，因为删除条目符合只减不增的规则。
  - 实施前先盘点：如果礼包变更在实现自登记时已经顺带删除了 blackjack 的显式登记，这一项只需核对。
- **封存计数**：在同一提交中下调。
- **其他改动**：`scripts/blackjack_retention_audit.py` 改用 `luckywheel.config` 读取配置。

## Risks / Trade-offs

- **[单事务抽奖改变了失败结果]** → 只影响中途失败的情况：原来可能扣了费却没发奖，现在整体回滚。用故障注入测试覆盖每一步失败；正常路径的结果与夹具一致。
- **[抽奖事务变长，加锁范围变大]** → 锁定的仍然只有本人的统计行和免费次数行，与现在各步单独加的锁是同一批行；在一次性 PostgreSQL 上做并发抽奖测试。
- **[特权码开关的并发语义]** → 原来并发时可能发出多个特权码，现在只会发一个。这更符合"一次性开关"的本意，在测试中写明。
- **[错误映射的细节很多]** → 用逐接口的请求和响应夹具兜底；被遮蔽分支和英文兜底都有专门的用例。
- **[依赖倒置的提供者没有注册]** → `app/subscriptions.py` 在 `main.py`、`manage.py` 和测试夹具中都会调用；另有测试断言注册后汇总中含有 21 点的进度字段。
- **[调度快照差异]** → 只允许 D5 列出的那一项，其余任务的快照必须完全一致。

## Migration Plan

1. 冻结四个领域的接口、错误映射、调度和通知快照，补齐各业务流程的测试。
2. 搬移 prediction 的 repository（只搬不改）。
3. 各领域的 rules、exceptions、repository 和 service；完成转盘单事务、账本和进度提供者、竞拍具名任务。
4. 迁移入口；更新 rankings 的两处调用；摘除 mixin；清理基线和合约。
5. 全量回归；在一次性 PostgreSQL 上做并发抽奖、特权码开关和预言结算测试；在生产形态副本上彩排抽奖、夺宝开奖、预言开奖和竞拍结束。
6. 部署：没有 schema 变更。回退就是回退镜像。内存中的竞拍任务在重启时由恢复逻辑重建，不涉及 jobstore 迁移。

## Open Questions

无。
