# Design

## Context

动机见 proposal.md。本设计假定以下变更已完成：

- `promote-activity-domains`：转盘、夺宝、预言、竞拍已有 service；它们的勋章触发调用仍在路由里，基线条目随行号重键。
- `promote-account-domains`：`core/events.py` 提供 `publish`、`subscribe` 和提交后同步分发；`app/subscriptions.py` 负责注册；`events` 角色可以跨域导入。
- `promote-line-domains`：premium 提供会员流量欠额的 `*_tx`，traffic 提供按用户查询每日流量的 service。

现状（调研时的 `3f27100`）：

**勋章触发点**

| 领域 | 位置 | 条件 | 调度方式 |
|---|---|---|---|
| luckywheel | 单抽、十连 | 每次成功 | BackgroundTasks |
| prediction | 下注 | 成功 | BackgroundTasks |
| treasure | 参与 | 成功 | BackgroundTasks |
| blackjack | 发牌、要牌 | 仅在结算时 | BackgroundTasks |
| blackjack | 停牌、加倍、投降 | 每次 | BackgroundTasks |
| donation | 确认捐赠 | 批准时 | BackgroundTasks |
| donation | 管理员登记 | — | 裸 `create_task` |
| crypto_donation | UPay 回调 | — | 裸 `create_task` |

- 不触发检查的路径：21 点超时结算、兜底扫描、锦标赛、bot 的 `/set_donation`。
- 每日批量检查：至尊贡献者 09:00，游戏王 09:10，启动后分别再各跑一次。

**颁发函数**：`check_and_award_supreme_contributor_badge(user_id=None)` 和 `check_and_award_game_king_badge(user_id=None)`，都是 async。

- 单用户模式：
  - 在独立会话里统计各领域的数据：捐赠额是否 > 1688；21 点统计、转盘次数、夺宝期数、预言注数，门槛分别为 5000、500、500，21 点另有 `badge_min_hands` 和 `badge_min_accuracy`。
  - 先 SELECT 再 INSERT `user_badges`。
  - 用 `send_message_by_url` 私信通知。
  - 异常全部吞掉。
- 批量模式：用 SQL UNION 求出候选用户后逐个颁发，并且在提交之前就追加了通知和计数。
- 冠军勋章：由 blackjack.service 调用 `badges.service.award_or_renew_badge`，按续期语义处理，不发通知。

**事件机制**：同步分发，处理函数在提交事务的线程里运行。现在请求触发的检查跑在 uvicorn 的事件循环上，批量检查跑在 PTB 的主循环上；两者都在 async 函数里做同步的数据库调用。

**badges**：`BadgesRepository` 有 11 个公开方法和 2 个静态方法。

- 3f27100 新增了模块级的 `award_or_renew_badge`，并由 `badges/service.py` 转发。
- 兑换走"200 + `success=false`"契约。
- 中心配置已由 `unify-business-configuration` 迁为领域配置。
- `rankings/repository.py:187` 借门面的 MRO 调用 `self._user_badge_to_dict`。

**badge_awards**：只有 `jobs.py`（424 行），没有 `__init__.py`。它直接导入 5 个领域的模型、SQLAlchemy 和 `get_session`。

**watch_rewards**（1,331 行）

- `update_credits` 是一个 async 任务，依次同步调用 `clean_tautulli_ghost_sessions`、`update_plex_credits` 和 `update_emby_credits`，然后发送通知。
- 结算按用户分事务提交，每个事务里调用 `credits.apply_tx`，用原生 SQL 写会员欠额列，并在需要时直接构造 `Statistics`。
- 邀请人奖励在循环结束后另开事务发放。结算中途失败导致的部分提交、补偿标记遗漏和通知显示问题已由 `fix-live-defects` 修复；后续提升冻结修复后的单用户事务结果。
- 邀请人通知里的总积分多算一次奖励的问题已由 `fix-live-defects` 修复，后续提升冻结库内余额与通知余额一致的行为。

**基线**：`owner=promote-reward-domains` 的条目 56 条（badge_awards 16、badges 10、watch_rewards 30）；指向 badge_awards 的另有 9 条，不在本变更名下。另有 3 条标给本变更的忽略项，以及 4 条标为 B3 的 watch_rewards.service 忽略项。

**测试**：以上都没有测试。

## Goals / Non-Goals

**Goals：**

- 六个领域不再导入或调用 `badge_awards`；D3 第 1 处环从代码和基线中消失。
- 勋章检查的触发粒度、时机语义和结果与现在一致：
  - 每个请求一次，与原请求解耦。
  - 现在不触发检查的路径仍不触发。
  - 批量任务保留。
- `badge_awards` 进入 import-linter 的检查范围，不新增任何豁免。
- 观看结算的积分结果、会员欠额、邀请奖励和通知文案逐项与现在相同。

**Non-Goals：**

- 不改勋章条件、门槛、加成和积分公式。
- 不改变单用户与批量两种模式在准确率舍入上的口径差异，由测试把现状固定下来。
- 显示问题和"结算中途失败后的部分提交"已由 `fix-live-defects` 的 D2 修复；本变更的 `settle_user_tx` 必须保留结算记录、邀请人奖励和补偿标记，冻结修复后的行为。
- 不改冠军勋章的续期语义，也不为它补发通知。

## Decisions

### D1 事件机制的异步扩展

在 `core/events.py` 上增加：

```python
def subscribe_async(
    event_type, handler: Callable[[E], Awaitable[None]]
) -> None: ...  # 只允许组装层调用
def emit(event: DomainEvent) -> None: ...  # 调用方已经在事务之外（已提交）时，立即分发
def bind_main_loop(
    loop: asyncio.AbstractEventLoop,
) -> None: ...  # main.py 在 PTB 循环就绪后调用
```

- **同步处理函数**：沿用现有语义，提交后在当前线程同步执行。
- **异步处理函数**：分发时不等待，而是安排到事件循环上运行：
  - 当前线程有正在运行的事件循环（uvicorn 请求线程、PTB 主循环中的任务），就在该循环上 `create_task`，并把任务放进模块级集合，完成后移除，防止被回收。
  - 当前线程没有事件循环（线程池任务、`to_thread` 中的具名任务），就用 `run_coroutine_threadsafe` 提交到 `bind_main_loop` 登记的主循环。
  - 既没有正在运行的循环、也没有登记过主循环（CLI 或测试），就在当前线程用 `asyncio.run` 同步执行。
- **异常**：处理函数的异常只记日志，与现在"颁发函数吞掉全部异常"的效果一致。
- **测试**：提供 `events.drain()` 夹具，等待所有未完成的任务，使测试可以断言结果。

这种安排与现在的时机语义对应：`BackgroundTasks` 在响应之后运行，`create_task` 与响应并发，都不阻塞请求。

备选方案：

- **每个事件都注册成调度器的一次性任务**：会把勋章检查写进 jobstore；而检查本来就是尽力而为的，失败了有批量任务兜底，持久化没有必要。
- **同步处理函数直接执行检查**：每个请求要多做 4–5 次查询，还可能发送通知，增加响应延迟，改变了现在"不阻塞请求"的语义。

### D2 事件定义与发布位置

| 发布方 | 事件（`<domain>/events.py`） | 发布位置 |
|---|---|---|
| blackjack | `CashHandPlayed(tg_id)` | 现金局 service 中与现有触发条件对应的 5 个动作：发牌和要牌仅在结算时；停牌、加倍、投降每次都发布。超时、兜底扫描和锦标赛不发布 |
| luckywheel | `WheelSpun(tg_id)` | 单抽与十连各发布一次 |
| prediction | `PredictionBetPlaced(tg_id)` | 下注成功后 |
| treasure | `TreasureJoined(tg_id)` | 参与成功后 |
| donation | `DonationApproved(tg_id)` | 确认接口和管理员登记接口；bot 的 `/set_donation` 不发布 |
| crypto_donation | `CryptoDonationCompleted(tg_id)` | 回调入账之后 |

- **四个已提升的领域**：21 点、转盘、预言、夺宝在 service 中用 `publish(session, event)` 发布，事件随事务提交后分发。
- **两个尚未提升的领域**：donation 和 crypto_donation 由 `promote-remaining-domains` 提升，本变更在它们现有的路由触发点改为 `emit(event)`。路由只导入本领域的 `events` 和 `core.events`，不违反入口层规则。remaining 变更再把它们挪进 service。
- **订阅**：`app/subscriptions.py` 注册两组订阅：游戏王检查订阅前四个事件；至尊贡献者检查订阅后两个事件。

### D3 badge_awards 的提升

- **service**：`badge_awards/service.py` 提供两个异步处理函数：`on_game_activity(event)` 和 `on_donation(event)`，分别调用单用户检查；还提供两个批量检查函数，供 jobs 调用。
- **读取数据**：改为调用各领域的 service：
  - 21 点的统计和候选用户：blackjack 已有。
  - 转盘次数、夺宝参与期数、预言下注数：本变更在这三个领域的 repository 中新增只读计数函数，并由各自的 service 暴露。计数口径与原 SQL 逐条一致，包括去重和 `source` 过滤。
  - 捐赠额：donation 尚未提升，本变更在它的 repository 中新增只读函数。
- **写入勋章**：通过 `badges.service.award_badge(tg_id, badge_type) -> bool` 完成：
  - 用 `INSERT … ON CONFLICT DO NOTHING` 实现幂等；SQLite 用等价的 `INSERT OR IGNORE`。
  - 返回 True 时才发送通知。
  - 批量模式改为每个用户提交之后再追加通知，从而修正"撞唯一约束也发恭喜"的时序问题。这只影响并发冲突的情况，不影响正常路径的结果。
- **不再写入 21 点的默认配置**：`unify-business-configuration` 之后，读取 21 点配置不会再写入默认值。
- **消除阻塞**：检查函数中的同步数据库调用改用 `asyncio.to_thread`，通知仍是 async。
- **补上 `__init__.py`**：在以上改动完成后补上，这时 6 个合约应当直接通过。补上的提交中不得新增任何 `ignore_imports`。

### D4 badges 的提升

- **repository**：改为模块级函数。
- **service**：`badges.service` 提供勋章定义的增删改查、兑换（`deduct_tx` 和插入在同一事务里）、`active_bonus_percentage(tg_id)`，以及中心配置的读写（领域配置）。
- **错误契约**：兑换的业务拒绝定义为 `BadgeError(DomainError, ValueError)` 的子类，由路由映射回原来的 `200 + success=false` 响应。
- **排行榜**：`rankings/repository.py` 中勋章榜对 `self._user_badge_to_dict` 的调用，改为在 rankings 内部把模型转换成字典。读模型可以直接读取 badge 的模型，字段和顺序与原来一致。本变更只做这一处必要的修改，避免摘除 mixin 后排行榜静默变空。
- **摘除 mixin**：从门面删除 `BadgesRepository`。

### D5 watch_rewards 的拆分

- **rules**：纯计算包括时长封顶、惩罚、勋章加成、邀请人 10% 奖励、增量计算和会员结算档位。会员结算档位原来调用 premium.rules 的私有函数，改为由 premium.service 传入结果。
- **notifications**：4 个用户和邀请人的通知模板移入 `notifications.py`，文案逐字不变，包括已知的显示问题。
- **repository**：每个用户的结算是一个 `settle_user_tx`，在同一 session 中完成：
  - `credits.repository.apply_tx`，它自己登记提交后的缓存失效。
  - `premium.repository.update_traffic_debt_tx`：`promote-line-domains` 已经把原来的 6 处原生 SQL 换成了这个函数，本变更把它纳入每个用户的结算事务。
  - `identity.repository.ensure_statistics_tx`（替换直接构造）。
  - `watched_time` 的更新。
- **service**：编排的顺序与现在相同：幽灵补偿 → 逐个用户结算 → 邀请人奖励 → 推进补偿水位线。
  - 外部读取（Tautulli、Emby）和其他领域的查询（traffic 的每日流量、invitation 的邀请人、badges 的加成）都在 service 中通过对方的 service 完成。
- **任务**：`update_credits` 把同步的结算整体放进 `asyncio.to_thread`，完成后再在事件循环里发送通知，发送间隔和"静默"参数不变。这个任务的调度 id、触发器和 runner 都不变。
- **手动入口**：`app.manage legacy-credit-sync` 继续直接调用这两个结算函数，行为不变。

### D6 基线与合约

- **本变更名下**：清除 56 条基线条目、3 条标给本变更的忽略项，以及 4 条标为 B3 的 watch_rewards.service 忽略项。
- **`promote-gift-pack-domain` 带来的变化**：
  - 它的 D3 放行了 `types` 角色。本变更名下以 `credits.types` 为目标的 15 条在那时就会被清除，所以实施时是 41 条。
  - 它的 D3 还让 credits 的 `*_tx` 自己登记提交后的缓存失效。badges 中 1 处对 `register_cache_invalidation` 的显式调用因此变得多余：确认对应的积分写入经过 `*_tx` 后直接删除。
- **其他变更名下**：D2 删除了 9 条以 badge_awards 为目标的条目；当前负责这些条目的变更 activity、blackjack 和 remaining 只会看到条目减少。
- **门面组合边**：删除 badges 和 watch_rewards 在六层、无环合约中的门面组合边忽略项，并下调封存计数。
- **重键**：行号移动的条目，用 `promote-gift-pack-domain` 引入的基线重键脚本重写键。

## Risks / Trade-offs

- **[异步分发的执行上下文多样]** → D1 为三种上下文（有运行中的循环、线程池、CLI）各写单元测试；集成测试覆盖从路由、从线程池任务、从 CLI 发布事件。
- **[事件粒度与现在不一致]** → 发布位置逐一对应现有的 12 个触发点，由测试断言：每类操作恰好分发一次，不触发的路径不分发。
- **[ON CONFLICT 在两种数据库上的写法不同]** → repository 按方言选择语句；在 SQLite 和一次性 PostgreSQL 上分别做并发颁发测试，确认每人只有一行、只有一条通知。
- **[结算改在线程中运行]** → 结算本来就是同步代码，每次调用都新开 session，没有共享状态；在线程中运行不改变结果，只是不再阻塞 bot。用生产形态副本对比新旧实现的结算结果。
- **[补上 `__init__.py` 暴露遗漏]** → 把它安排为最后一步：先让 AST 基线清零，再加文件；如果合约失败，说明还有未迁移的导入，必须修复，不得豁免。

## Migration Plan

1. 补齐勋章颁发、12 个触发点和观看结算的行为测试，冻结通知文案和结算结果的快照。
2. 扩展 `core/events.py`；定义六个领域的事件，替换触发点；注册订阅。
3. 提升 badges、badge_awards、watch_rewards。
4. 补上 `badge_awards/__init__.py`，清理基线和合约。
5. 在生产形态副本上对比新旧实现的每日结算和勋章批量检查结果；然后全量回归。
6. 部署：没有 schema 变更。回退就是回退镜像。

## Open Questions

无。


## 实施彩排发现的基线缺陷

完整生产副本对比发现，`ca6ba12` 的观看结算在调用 `premium.repository.update_traffic_debt_tx` 时使用 `CreditAccount.emby(media_id)`，但该接口依照 credits 账户约定按 `emby_username` 定位。真实 Emby ID 与用户名不同，旧实现会因找不到账户而回滚该用户结算。提升后的 repository 使用 `media_row.emby_username`，保留正确的欠额接口契约，不复现该错误。

验证必须区分原始旧版和修正对照版：保留原始运行的回滚差异；另外对旧版仅修正这一处参数，在同一初始副本上比较积分、欠额、邀请奖励及通知。不能把修正对照版的结果声称为原始旧版完全等价。

另发现 sqlite3 legacy transaction control 下首次 SAVEPOINT 可能没有外层数据库事务，释放保存点会让结算记录提前提交。结算 ledger 的 helper 在 SQLite 未开始事务时显式 BEGIN，确保后续欠额或积分写入失败时 ledger 也回滚；PostgreSQL 事务路径不变。`test_settlement_failure_rolls_back_every_write` 覆盖该失败情形。
