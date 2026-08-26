## Context

动机见 `proposal.md` 的 Why。需求契约见 `specs/blackjack-tournament/spec.md` 与 `specs/blackjack/spec.md`。本文只记录实现取舍。

塑造设计的现有约束（在 21 点现金局落地时已经踩实，本变更必须继承而非重新发明）：

- **引擎已经是纯函数且返回倍率**：`blackjack_engine.py` 的 `resolve()` 返回 `(outcome, return_multiplier, profit_multiplier)`，不接触积分。这是当初留的接缝，本变更**一行不动它**。
- **结算适配层是 `_settle_blackjack_hand`（`db.py:3067`，约 220 行）**：事务边界、CAS 幂等闸门、锁序、`session.flush()` 时机都在其中，且注释记录了两处实测过的事故（SQLite 下重复赔付、闸门晚于写操作导致「扣了钱不赔付」）。
- **幂等一律靠条件 UPDATE（CAS）而非行锁**：`with_for_update()` 在 SQLite 上是 no-op，两个并发事务可以各自读到同一状态再依次写入。这一点在现金局是实测证伪后改的（design 决策 14），本变更的每一处状态流转都必须照此办理。
- **全局锁序为 `hand → statistics → system_config`**：`_settle_blackjack_hand` 的注释详述了曾经的 ABBA 隐患，以及它当时只靠两个「没写下来的巧合」才没真死锁。新增表必须并入这条顺序而不是另立一套。
- **超时兜底是三层保障**：持久化 date 任务（`misfire_grace_time=None`，全局默认 60 秒会导致重启即永久丢任务）、重启恢复、每 10 分钟全量扫描。
- **群播报用游标轮询**：因为奖池派彩散落在六条结算路径上，逐条挂钩必漏（见 `db.JACKPOT_NOTIFY_CURSOR_KEY` 注释）。
- **私聊与群播报同一个出口**：`send_message_by_url(chat_id, text)`，chat_id 传 tg_id 即为私聊（`auction.py:60` 通知竞拍获胜者用的正是它）。
- **`db.py` 已逾 8300 行**，单一 `DatabaseORM` 单例；纯计算不进去，DB 操作必须进去。
- **`BlackjackDialog.vue` 已近千行**，牌桌 UI 嵌在其中。
- **`Statistics.credits` 是 `Float`**，全项目以 `round(x, 2)` 收敛。
- **数据库目标为 SQLite 与 PostgreSQL**，不依赖任一方言特有特性。

## Goals / Non-Goals

**Goals:**

- 赛内结算与现金局结算共用同一个引擎，且两条路径的幂等与锁纪律形状一致——一处踩过的坑不在另一处重现
- 赛内与现金局的隔离是**结构性**的而非依赖「记得加过滤」：漏一处即静默污染主榜，且事后极难回溯
- 赛事的每一次状态流转与每一次通知都恰好发生一次，且不依赖任务是否被重复触发
- 排名读到的筹码是终局筹码——不存在「押注已扣、赔付未计」的中间态被计入名次
- 在 SQLite 与 PostgreSQL 上行为一致

**Non-Goals:**

- 不做实时同桌对战（无 WebSocket/SSE，项目也没有这套基础设施）
- 不做复式赛制（理由见 proposal 与下方决策 6）
- 不做重买（rebuy）、加注期（add-on）、淘汰赛轮次（bracket）
- 不引入新的第三方依赖
- 不为锦标赛设任何榜单

## Decisions

### 决策 1：赛内适配层是**同构复刻**，不是 `if tournament_id` 分支

新增 `_settle_blackjack_tournament_hand(session, hand, entry, abandoned=False)`，与 `_settle_blackjack_hand` 平级。

```
                    ┌─────────────────────────────────┐
                    │  blackjack_engine.py（不动）      │
                    │  resolve() → 倍率                │
                    └───────┬─────────────────┬───────┘
                            │                 │
        ┌───────────────────▼──┐   ┌──────────▼────────────────────┐
        │ _settle_blackjack_   │   │ _settle_blackjack_tournament_ │
        │ hand（现金局）        │   │ hand（赛内）                   │
        ├──────────────────────┤   ├───────────────────────────────┤
        │ CAS 闸门              │   │ CAS 闸门        ← 同构         │
        │ lock Statistics      │   │ lock Entry     ← 换掉          │
        │ 抽水计取              │   │ ——             ← 砍掉          │
        │ 奖池派彩 + 注入        │   │ ——             ← 砍掉          │
        │ 决策计数落库           │   │ ——             ← 砍掉          │
        │ credits += payout    │   │ chips += floor(payout)        │
        └──────────────────────┘   └───────────────────────────────┘
```

**为什么不在现有函数里加分支**：它已经 220 行，其中相当篇幅是注释掉的历史事故说明；再穿三条 `if hand.tournament_id` 会让每一条既有推理都要重新验证「在赛内这一支是否仍成立」。两个函数各自短、各自能被读完，比一个长函数便宜。

**代价是 CAS 闸门与 `session.flush()` 时机被复制了一份。** 这是有意接受的：那段逻辑是本项目里最不该「聪明地复用」的地方——把它抽成公共 helper 会让闸门与其保护的写操作在源码上分离，而现金局的事故恰恰是「闸门晚于写操作」。宁可两份都显式。

替代方案：把两者的公共部分抽成模板方法（策略回调）。否决——控制流被回调打断后，「闸门必须早于任何写操作」这条不变量就无法靠阅读单个函数确认。

### 决策 2：锁序扩展为 `hand → tournament → entry → statistics → system_config`

新增两张表插在既有链条中间，而不是另起一套。各路径取到的都是这条全序的**子序列**：

| 路径 | 依次触及 | 是否子序列 |
|---|---|---|
| 报名 | tournament（CAS 占位）→ statistics（扣费） | ✅ |
| 赛内发牌 | entry（扣筹码）→ statistics（**只锁不改**，见下） | ✅ |
| 赛内结算 | hand（CAS）→ entry | ✅ 不碰 statistics |
| 派奖 | tournament（CAS）→ entry（读）→ statistics（逐个 FOR UPDATE） | ✅ |
| 取消退款 | tournament（CAS）→ entry（读）→ statistics（逐个 FOR UPDATE） | ✅ |
| 现金局各路径 | 原样不变 | ✅ |

**赛内结算完全不触及 `statistics`**，这是筹码不是积分带来的直接好处：赛内高频路径与积分行锁彻底解耦，一个人打 30 手赛内牌不会和自己的现金局、也不会和派奖抢同一行锁。

派奖与赛内结算都要 `entry`，但派奖不持有 `hand`、赛内结算不持有 `tournament`，两者只会在 `entry` 上互等一次，不成环。

**赛内发牌必须额外锁一行它根本不修改的 `statistics`。** 「同一用户同时至多一手非终态」这个不变量跨现金局与全部赛事共用，而现金局发牌正是以该用户的 `statistics` 行锁作为串行化点（它本来就要锁这行扣积分）。赛内若只锁 `entry`，一个用户并发发起「现金局发牌 + 赛内发牌」会各持一把互不相干的锁，双双通过「无进行中手牌」检查而同时开出两手牌——两侧共用同一套动作端点与超时机制，届时哪一手该被处置将取决于调用顺序。锁同一行是让该不变量真正成立的唯一办法，代价只是一次单行加锁，且顺序 `entry → statistics` 仍在全序内。

### 决策 3：每一处状态流转都是 CAS，且**通知挂在 CAS 赢家身上**

赛事状态 `1 报名中 / 2 进行中 / 3 已结算 / 4 已取消`，每次流转都是：

```sql
UPDATE blackjack_tournament SET status = <新> WHERE id = ? AND status = <旧>
-- rowcount == 0 → 放弃，不做任何写入、不发任何通知
```

这一条同时解决了两个问题，且解法只有一个：

- **重复流转**：定时任务重试、最后一次报名与截止任务撞车、结算任务被并发触发
- **重复通知**：五处通知里有三处（开赛、赛果、取消）都有多条触发路径

**通知的去重不另设机制，就是 CAS。** 抢到状态流转的那一方负责发通知，抢不到的一方什么都不做。这与奖池播报的游标轮询是**有意不同的选择**：

| | 奖池派彩 | 赛事事件 |
|---|---|---|
| 触发点 | 散落六条结算路径 | 状态流转，天然单点 |
| 去重 | 游标轮询（逐条挂钩必漏） | CAS |

奖池那边用游标是因为「谁结算的」这件事无法收敛成单点；赛事这边状态流转本身就是单点，再套一层游标只是多一份可失步的状态。

**报名不超员也是 CAS**，不是「读计数再判断」：

```sql
UPDATE blackjack_tournament SET entrant_count = entrant_count + 1
 WHERE id = ? AND status = 1 AND entrant_count < max_entrants
```

抢到名额后再插入 `entry`。同一用户并发重复报名由 `UNIQUE(tournament_id, tg_id)` 兜住——插入撞约束时整个事务回滚，计数增量随之回滚，不需要补偿性的减一。

### 决策 4：奖池金额**不落列，按报名数推导**

`prize_pool = entrant_count × buy_in_credits + seeded_prize_credits`。

不设 `prize_pool_credits` 累加列。累加列会引入一整类漂移 bug（报名成功但累加失败、退款后忘记回退、并发累加丢失），而报名费是每场固定值，推导式恒等于真值。报名中展示的「当前奖池」与结算时用的是同一个推导，不可能不一致。

这与幸运奖池的处理**刻意不同**：幸运奖池的增量来自每手不同的抽水份额，无法推导，只能累加（故它才需要 `SystemConfig` + `FOR UPDATE` + SAVEPOINT 那一套）。赛事奖池没有这个必要。

`seeded_prize_credits` 是本变更唯一的增发路径之一，须为管理员显式操作（与幸运奖池注入种子余额同一口径）。

### 决策 5：筹码为整数，赔付向下取整

`entry.chips` 用 `Integer`，赔付 `floor(return_multiplier × bet)`。

- 注额约束为 10 的整数倍，故 3:2 天胡赔率下 `2.5 × bet` 必为整数，`floor` 实际不会触发
- 管理员把 `blackjack_payout` 改成 1.2 之类的非常规值时 `floor` 才生效，方向对玩家不利但量级在 1 筹码以内
- 好处是排名与展示不会出现 `1247.5 筹码`，也不需要在赛内重复现金局那套 `round(x, 2)` 的浮点收敛纪律

替代方案：照 `credits` 用 `Float` + `round(x, 2)`，与现金局代码形状完全一致。否决——筹码是纯展示性的内部计量单位，没有任何理由继承积分的小数复杂度；而整数让「筹码低于最小注即淘汰」这个判定不存在边界模糊。

### 决策 6：每手牌自己一个 `secrets` 种子，**不设赛事级种子**

赛内发牌与现金局完全一样：`deck_seed = secrets.token_hex(16)`，落在手牌行上。

原本的直觉方案是给赛事一个 `tournament_seed`，每手牌的种子由 `HMAC(tournament_seed, tg_id, hand_no)` 派生。**否决**：派生的唯一收益是「凭一个赛事种子复现全场」，而每手牌本来就存着自己的种子，争议复现的能力已经具备。派生只是多一个必须保密的字段和一层无收益的间接。

**复式赛制（全场同牌序）在此明确否决**，理由记录在此以免日后重提：它是最强的技巧信号，且 `build_deck(seed)` 让实现成本接近零；但异步作战下先打完的人在群里说一句就泄漏全部牌序与庄家暗牌。推演过的三个补丁均不成立——「回合窗口 + 结果封盘」泄漏的是牌不是结果；「只复式初始发牌」因下注在发牌前而等于提前告知该不该重注；「先锁注再发牌 + 复式」仍可由他人代答play决策。要救它必须逐决策同步，而这需要项目明确不具备的实时基础设施。

### 决策 7：隔离靠**两层**，不靠「记得加过滤」

第一层是六处 `tournament_id IS NULL` 过滤。逐处列明，实现时按此清单核对：

| 位置 | 方法 | 后果 |
|---|---|---|
| `db.py` | `_blackjack_rank_rows` | 准确率榜与胜率榜被污染 |
| `db.py` | `get_blackjack_max_win_rank` | 筹码被当积分排名 |
| `db.py` | `_count_blackjack_hands_today` | 打赛事把当日免抽水额度吃掉 |
| `db.py` | `get_user_blackjack_stats` | 个人统计准确率被稀释 |
| `db.py` | `get_blackjack_admin_stats` | 赛内 `bet_credits` 是**筹码**，混入会把筹码数加进以积分计价的 `total_wagered` 与 `net_credits`，运营数字失去意义 |
| `db_func.py` | 游戏王勋章子查询 | 刷赛事拿勋章 |

第二层是**赛内手牌不写决策计数**（`decisions_total` / `decisions_correct` 恒为 0）。这不只是「反正不用」——它是纵深防御：即使将来某个新查询漏了第一层过滤，赛内手牌对准确率**分子与分母的贡献都是 0**，污染被限制在「手数门槛」这一项上，不会产出一个错误的准确率数字。

**三处刻意不过滤**，因为它们的语义本就是全局的。实现时已在各处就地写下理由，以免日后被「补全」：

- `create_blackjack_hand` 的「同时只有一手」——单一不变量最简单、最不容易被绕过。按侧分别计数会让一人同时持有一手现金局与一手赛内牌，而两侧共用同一套超时机制，届时哪一手该被处置将依赖调用顺序。代价是一手悬挂的赛内牌会挡住现金局发牌，上界是该手牌自己的超时时限
- `create_blackjack_hand` 的发牌速率下限——目的是压制脚本与积分行锁争用，与手牌属于哪一侧无关；按侧分别判定等于把允许频率翻倍，恰好削弱它要防的东西
- `list_active_blackjack_hands`——赛内手牌同样受单手超时约束，重启后也必须重建其超时任务。漏掉会让赛内手牌在重启后只能等每 10 分钟的全量兜底，而全量兜底是最后一层、不该当常规路径

**必须分派而非过滤的一处**：`sweep_timed_out_blackjack_hands` 要扫到赛内手牌，但结算得走另一个适配层。分派点收敛为一个内部函数 `_settle_blackjack_hand_dispatch`（按 `hand.tournament_id` 是否为空选适配层），`settle_blackjack_hand_by_timeout`、`restore_blackjack_timeouts`、全量兜底任务三条入口共用它，避免三处各写一遍判断。

**还有一处隔离与聚合无关，但比聚合更要紧：两侧的 hand id 共用同一张表。**

现金局的四个动作端点只按 `hand_id` 取牌并校验归属，若不额外拦，用户把赛内手牌的 id 提交到 `/blackjack/{id}/stand` 就会走现金局适配层——那会拿**筹码**注额算出一笔钱赔进他的**积分**，还会把筹码数按抽水比例注进幸运奖池。反向同理：现金局手牌提交到赛内端点会把用积分押的注赔成某场赛事的筹码。

故隔离做在**加锁处**而非各端点里（漏一个端点即是漏洞）：`_lock_blackjack_hand` 默认 `cash_only=True` 拒绝赛内手牌，`_lock_tournament_hand` 以 `cash_only=False` 调用它后反向要求 `tournament_id` 非空。两个方向各自把对面的手牌当「找不到」拒掉。

与此配套，`_blackjack_hand_to_dict` 带出 `tournament_id`：`GET /current` 因为共用「至多一手」不变量而可能返回一手赛内牌，界面需要据此把用户引回正确的牌桌，否则他在现金局界面点任何动作都只会得到「找不到该手牌」。

### 决策 8：赛事推进用**每分钟一次的 tick 任务**，不用 per-赛事 date 任务

一个 `blackjack_tournament_tick_job()`，每分钟依次处理三件事，每件都是 CAS 门控的：

```
① status=1 且 register_deadline <= now
     ├─ entrant_count >= min_entrants → CAS 1→2，通知全部报名者（开赛）
     └─ 否则                          → CAS 1→4，退款 + 通知（取消）

② status=2 且 play_deadline - remind_lead <= now < play_deadline
     └─ reminder_sent_at IS NULL → 通知未打满者，写 reminder_sent_at（即为去重标记）

③ status=2 且 play_deadline <= now
     └─ 强制结算该赛事全部非终态手牌 → CAS 2→3 → 排名派奖发勋章 → 通知
```

**完赛提醒的提前量按赛事时长收敛**，取 `lead = min(配置的 6 小时, 赛程/2)`：赛程比提前量还短时（如 2 小时的赛事），提醒窗口会在开赛那一刻就成立，用户同一分钟收到「已开赛」和「你还有 N 手未完成」两条，后者纯属噪音。赛程用 `play_deadline − register_deadline` 作下界——赛事无 `started_at` 列，而 `register_deadline` 是最晚开赛时点，满员提前开赛只会让玩家有更充裕的时间、提醒仍落在后半程。去重标记 `reminder_sent_at` 由 `claim_tournament_reminder` 在一次 `WHERE reminder_sent_at IS NULL` 的条件 UPDATE 里抢占（与状态 CAS 同构），并顺带返回「该发给谁」。

**为什么不照竞拍与手牌超时那样用持久化 date 任务**：那套机制的代价是 `misfire_grace_time=None` 的陷阱（全局默认 60 秒，一次超过一分钟的重启就让 APScheduler 永久丢弃任务）外加一个重启恢复函数（`restore_auction_schedules` / `restore_blackjack_timeouts`）。手牌超时值得付这个代价，因为 15 分钟的时限要求及时性；**赛事是跨天的事件，一分钟的推进延迟无人可感**，而周期性 tick 天然免疫任务丢失与重启，不需要恢复函数。

单手 15 分钟超时仍然沿用既有的 date 任务三层保障——那里对及时性的要求没变。

`min_entrants` 达标时若同时满员，开赛可能由 ① 或由第 N 次报名触发，两条路径由同一个 CAS 收敛。

### 决策 9：完赛截止的两阶段——先清场，后排名

排名 SHALL 读到终局筹码，而一手在局的牌意味着押注已从 `chips` 扣除、赔付尚未计入，其持有者的筹码被低估。故：

```
阶段一  强制结算该赛事全部非终态手牌
        · 每手牌一个独立事务（照 sweep_timed_out_blackjack_hands 的两条理由：
          不寄生在调用方事务里、不把整批放进一个事务）
        · 口径等同玩家停牌，绝不判负
        · 不看该手牌自己的 15 分钟时限——赛事已到点，一律清场
阶段二  CAS 2→3 → 读 entry 排名 → 逐个派奖 → 授勋章 → 通知
```

**新手牌无法在两阶段之间冒出来**：发牌端点以 `now < play_deadline_ms` 为闸门，这是个固定时间戳，与赛事状态无关，过点即拒。故不需要引入「结算中」这个中间状态。晚到的动作请求由手牌自己的 CAS 挡住（已是终态 → `already_settled`）。

**闸门必须同时装在动作端点上，不能只装在发牌端点上。** 初版只在 `create_blackjack_tournament_hand` 校验了 `play_deadline_ms`，`hit / stand / double / surrender` 只看 `hand.status`。那是个真实的漏洞：一个恰好挤在阶段一与阶段二之间的 `double` 会让该玩家带着已扣未赔的筹码参与排名，随后那手牌再把赔付写回一场**已经派完奖**的赛事。现改为在 `_lock_tournament_hand` 里统一校验赛事状态与完赛截止——五个动作共用同一道闸门，加新动作时不会漏。

**阶段一必须把清场结果告知阶段二。** 初版丢弃了 `force_settle_tournament_hands` 的返回值并无条件派奖，而该函数是吞掉单手异常继续循环的：任何一手结算失败都会让排名读到被低估的筹码，而派奖的 CAS 一触发就再无重试机会——「下一分钟的 tick 会再试」这句注释在当时是错的。现返回 `{settled, remaining, cleared}`，`remaining` 由**结算后的重新扫描**得出（不靠计数相减，扫描才能反映期间被其他事务终结的手牌），未清干净则本轮跳过派奖、赛事保持进行中。

### 决策 15：已有报名者之后，经济参数一律冻结

`update_blackjack_tournament` 初版只守了 `max_entrants >= entrant_count`，其余字段无差别 `setattr`。这是本变更里唯一的**增发**路径：奖池是 `entrant_count × buy_in_credits + seeded` 推导出来的，取消退款也读同一个 `buy_in_credits`。按 30 收了 10 个人再把它改成 100，派奖按 1000 算而实收只有 300；走取消路径则每人退 100。

故 `entrant_count > 0` 时白名单只留四项——标题、说明、报名截止、完赛截止，外加**只增不减**的 `seeded_prize_credits`（加码是纯利好，减码等于事后缩水已公示的奖池）。要改经济参数就先取消（全额退款）再重建。

白名单而非黑名单：新增字段时默认落在「冻结」一侧，漏掉一个的后果是管理员少一项可改，而不是多一条增发路径。

### 决策 16：赛程窗口有下限

`register_deadline == play_deadline` 曾是合法输入，其后果是**报名费被静默销毁**：同一次 tick 内开赛并立即结算，无人打完、无人淘汰，资格集为空，`_compute_tournament_payouts(0, ...)` 返回空表，每个人的 `prize_credits` 都是 0。

现要求窗口 ≥ `max(30 分钟, 总手数 × 1 分钟)`。窗口须随总手数放大——100 手配 30 分钟同样无人打得完，只是destruction 的比例低一些。

顺带地，tick 把两份赛事列表在任务体里**一次查出**再传给三个阶段（原本完赛提醒与完赛结算各查一遍同一个「进行中」集合），这使「同一 tick 内开赛又结算」这条路径在结构上也不存在了：阶段一新开的赛事不在本轮的「进行中」列表里。有 30 分钟的窗口下限兜着，这一分钟的推进延迟不改变任何结果。

### 决策 17：标题留空的含义按路径分叉——创建即自动命名，修改即拒绝

留空创建时生成 `21 点锦标赛 · 第 N 期`，N 取**已创建赛事总数 + 1**。

不用 `id`：管理端列表本来就在标题前显示 `#id`，写进名字只是重复；「第 N 期」自带连续感，且赛事没有删除路径（取消也只是状态流转），故该计数单调递增。不加 `UNIQUE(title)`：并发创建会算出同一个 N 而重名，但重名只是显示上的巧合，唯一约束会把它升级成一次创建失败——赛事创建是管理员的手动低频操作，代价与收益倒挂。

**修改路径刻意不复用这条兜底。** 创建时没有可保留的原值，留空只可能是「你帮我取一个」；修改时已有原值，静默换成一个新名字会让管理员以为自己改的生效了，而群播报公示的是另一个。故 `TournamentUpdateRequest` 把 `title` 改回必填——但**不设 `min_length`**：空串要落到 DB 层，由那里抛出的业务错误被翻译成中文，而不是一条 422 的字段校验噪音；前端另加一道就地校验，省掉那次注定失败的请求。

创建成功后回显最终名称：留空创建时，管理员否则要翻列表才知道系统取了什么名字，而群播报已经发出去了。

### 决策 10：数据模型

```
blackjack_tournament
├─ id                     BIGINT   PK
├─ title / description    TEXT
├─ status                 SMALLINT 1报名中 2进行中 3已结算 4已取消
├─ buy_in_credits         INTEGER
├─ starting_chips         INTEGER
├─ total_hands            INTEGER
├─ min_bet_chips / max_bet_chips   INTEGER
├─ min_entrants / max_entrants     INTEGER
├─ entrant_count          INTEGER  ← 报名占位的 CAS 依据，兼奖池推导的因子
├─ rake_bp                INTEGER
├─ seeded_prize_credits   FLOAT    管理员补贴，默认 0
├─ payout_structure       TEXT     JSON 数组，如 [50, 30, 20]
├─ 参数快照：dealer_hits_soft_17 / blackjack_payout / surrender_enabled
│             hand_timeout_minutes
├─ register_deadline_ms / play_deadline_ms   BIGINT
├─ reminder_sent_at       BIGINT   NULL ← 完赛提醒的去重标记
├─ created_by / created_at / settled_at
└─ CHECK: status IN (1,2,3,4) / buy_in > 0 / total_hands > 0
          min_bet <= max_bet / min_entrants <= max_entrants
          entrant_count >= 0

blackjack_tournament_entry
├─ id                 BIGINT   PK
├─ tournament_id      BIGINT   FK → blackjack_tournament.id, index
├─ tg_id              BIGINT   FK → statistics.tg_id, index
├─ chips              INTEGER  ← 赛内适配层锁这一行，替代 Statistics
├─ hands_played       INTEGER
├─ status             SMALLINT 1进行中 2已打完 3已淘汰
├─ final_rank         INTEGER  NULL 结算后写入
├─ prize_credits      FLOAT    NULL 结算后写入，0 表示无派奖
├─ registered_at_ms   BIGINT   ← 并列时的决胜依据
└─ UNIQUE(tournament_id, tg_id)   ← 重复报名的唯一防线

blackjack_hand
└─ tournament_id      已存在（可空），本变更仅补索引 (tournament_id, tg_id)
```

`blackjack_hand` **不加 `entry_id`**：`(tournament_id, tg_id)` 已经唯一确定一条 entry，多一个外键只是多一处可不一致。当初预留 `tournament_id` 这一列的收益在此兑现——不改既有表结构、不写数据迁移。

**派奖结果落在 entry 上**（`final_rank` / `prize_credits`）而非另建流水表：一次派奖对一条 entry 恰好写一次，CAS 已保证不重复，流水表提供不了额外信息。

### 决策 11：排名并列由**报名时点**决胜

筹码相同时报名较早者列前。理由是它**不可操纵且不奖励任何行为**：以手数决胜会奖励少打（保守者占优），以最后一手时点决胜会奖励拖到截止前，而报名时点在赛事开始前就已固定，无法在赛中调整。

### 决策 12：勋章续期是 `expires_at` 的一次 UPDATE，带上限

Badge 系统的语义正好合用（`models.py:749` 注释：badge ownership is permanent, only bonus expires）：`UserBadge` 的 `is_active` 表持有、`expires_at` 表加成到期，`UNIQUE(tg_id, badge_id)` 使同一勋章至多一行。

```
首次夺冠  INSERT UserBadge(expires_at = now + valid_days)
再次夺冠  UPDATE expires_at = min( max(expires_at, now) + valid_days,
                                   now + CHAMPION_BONUS_CAP_DAYS )
```

`max(expires_at, now)` 是「续期而非重置」的全部含义：加成还没过期就往后接，已经过期就从现在起算。外层 `min` 是上限（90 天），防止持续夺冠者无限累积。

Badge 行本身照 `game_king`（`db_func.py:2720`）的形状：缺失时自动创建，`credits_cost=0`、`is_enabled=0`（禁用兑换、仅系统授予）、`bonus_percentage=0.05`、`valid_days=30`。自动创建这个既有范式让本变更**不需要预置数据或数据迁移**。

新增 DB 方法 `award_or_renew_badge(tg_id, badge_type, cap_days)`——既有的授予路径只做「有则跳过」，续期是新语义，不改既有方法以免影响 `game_king` 与 `supreme_contributor`。

**这是一条增发路径**：0.4 积分/天/人（观看上限 8 × 5%），十个持有者约 4 积分/天。量级相对大转盘的回收可忽略，但原设计对增发很严格，故在此显式记账。

### 决策 13：通知在事务提交之后发，且逐收件人隔离

DB 方法只返回「谁该收到什么」（收件人列表 + 渲染所需数据），发送全部在路由/任务层。**绝不在事务内发送**——事务回滚后人已经收到「赛事已开始」是不可撤回的。

开赛通知走 `BackgroundTasks`（`auction.py:23` 已在用）：它可能由第 N 个报名者的 HTTP 请求触发，同步发 20 条私聊会让那次报名卡住数秒。tick 任务触发的那三处本就在后台，直接 await 即可。

逐收件人 `try/except`，照 `notify_blackjack_jackpot_wins_job` 的循环：从未与机器人建立私聊、或将其拉黑的用户会发送失败，不能因一人失败中断其余。失败只记日志、不重试——与奖池播报同一口径（业务结果早已落库，通知只是事后公示）。

群播报沿用 `_get_group_chat_id()`（未配置 `TG_GROUP_ID` 即跳过）与 `jackpot_notify_enabled` 并列的新开关 `tournament_notify_enabled`。**关闭播报时仍照常推进 `reminder_sent_at` 与各状态 CAS**——照现金局那条已经写下来的教训：若关闭时直接 return，去重标记会冻结，重新打开的那一分钟会一次性倾泻积压。

### 决策 14：前端先抽 `BlackjackTable.vue`，再复用

`BlackjackDialog.vue` 近千行且牌桌嵌在其中。抽出的子组件以 props 承接两侧差异，而不是在组件内判断「是否锦标赛」：

| prop | 现金局 | 赛内 |
|---|---|---|
| `betMode` | `tiers`（5/15/30） | `range`（min–max，步进 10） |
| `balance` / `currencyLabel` | 积分 | 筹码 |
| `showStrategyHint` | `true` | `false` |
| `showRake` / `showJackpot` | `true` | `false` |

`showStrategyHint=false` 是 spec 要求的行为，把它做成 prop 而非组件内的赛事判断，使「赛内不显示提示」在调用点一眼可见。

组件**不发起任何请求**：动作以 emit 上抛，父组件调接口后把新手牌回传到 `hand`。庄家回放的时机由父组件通过 `$refs` 调 `startReveal()` / `cancelReveal()` 控制——回放该不该播取决于「这一手是刚结算的，还是打开页面时就已结算的」，只有父组件知道。反向的回放状态则经 `reveal-change` 事件上抛，**不能让父组件在 computed 里读子组件的 `revealing`**：`$refs` 不是响应式的，那样写奖池高亮不会随回放结束而更新。

抽取是**纯重构**，独立成实施阶段并单独验证现金局无回归，不与锦标赛功能混在同一批改动里。

## Risks / Trade-offs

- **[六处隔离点漏一处即静默污染主榜，且事后极难回溯]** → 两层防御（决策 7）：过滤清单逐处列明按项核对，外加赛内不写决策计数使漏过滤时贡献为 0/0。上线后应人工比对一次「某个只打赛事的用户是否出现在准确率榜与个人统计中」。

- **[赛内适配层复制了现金局的 CAS 闸门，两份可能日后分叉]** → 这是决策 1 明确接受的代价。缓解是两个函数都短到能被完整读完，且各自的闸门与其保护的写操作在源码上相邻——现金局的事故恰恰是闸门与写操作分离造成的。

- **[方差压过技巧，冠军基本由运气决定]** → 30 手平注下累计标准差约 6.2 个注额单位，10 人场里最强者胜率大约从 10% 升到 15–20%。**这是接受而非缓解**：spec 已规定赛果不进任何榜单、不与准确率榜争夺技巧叙事。复式赛制本可根治，但异步下不可行（决策 6）。

- **[赛内 EV 成本远低于现金局，可能蚕食积分回收]** → 赛内 30 手的庄家优势全作用在虚拟筹码上，真实成本只有报名费上的抽水。单人单周把 30 手现金局换成一场赛事，站点少回收约 7.8 积分；20 人全换约 156 积分/周，与大转盘 21 次的回收量相当。**周赛频次下可忽略，日赛则会实质蚕食**——故频次是运营约束而非技术参数，须写入管理面板的说明文案。

- **[资格门使未完赛者白交报名费]** → 这是反退化的必要条件（不设门则「报名后不打」是占优策略），但它把公平性的担子压在完赛提醒上。故提醒被列为公平性要求而非便利（spec 明文），且 `reminder_sent_at` 的去重必须在关闭通知时也照常推进（决策 13），否则关播报期间的赛事将无人被提醒。

- **[勋章加成是增发路径]** → 约 4 积分/天（十个持有者），相对回收量可忽略。上限 90 天防止无限累积。已在决策 12 显式记账。

- **[奖池是再分配，会向少数人集中]** → `min_entrants ≥ 6` 挡住「三人报名人人有奖」；档位截断归一保证奖池不残留。集中度本身与竞拍同类，社区已有既成容忍度。

- **[tick 任务使赛事推进有最多一分钟延迟]** → 跨天事件上无人可感（决策 8）。换来的是免疫任务丢失与重启，且不需要重启恢复函数——相对 date 任务是净收益。

- **[并发报名的计数 CAS 与唯一约束需配合正确]** → 计数增量与 entry 插入在同一事务内，插入撞 `UNIQUE(tournament_id, tg_id)` 时整个事务回滚、计数增量随之回退，不需要补偿性减一。实现时须确认二者确实同事务，否则会出现「名额被占但无 entry」的幽灵占位。

- **[`entrant_count` 与 entry 实际行数可能漂移]** → 二者只在同一事务内一起变动，且赛事进入进行中后 `entrant_count` 不再改变。奖池按 `entrant_count` 推导（决策 4），故一旦漂移会直接影响派奖金额；管理端应提供一处一致性校验（比对 `entrant_count` 与 `COUNT(entry)`）。

- **[赛内手牌悬挂会挡住现金局发牌]** → 「至多一手」跨两侧共用（决策 7）的代价。上界是单手 15 分钟超时，且用户自己再次操作时的惰性清理会立即释放。**拒绝提示必须指明手牌所在的场次**：两侧的 `/current` 互相过滤掉对方的手牌，只说「你还有一手牌未结束」会让用户在一个显示着正常下注界面的牌桌上反复点发牌、反复报错，长达一个超时周期。

- **[动作响应的状态字段可能为空]** → 结算被兜底扫描抢先时（`already_settled`），这一份响应无从得知最新的筹码与进度。四个字段因此是可空的，前端**只在非空时覆盖**本地状态。反过来的做法——兜底成 0——会把玩家的筹码栈显示成 0、进度回退到 0/N，看上去像资产凭空蒸发。

- **[决定性一手的结果容易被界面吞掉]** → 打满手数或被淘汰的那一手会把 `entry.status` 从 1 改成 2/3，若牌桌的挂载条件只看该状态，牌桌会在同一 tick 被卸载，玩家看不到那一手的庄家牌与赔付。挂载条件因此是 `entry.status === 1 || hand`，由「查看赛果」按钮清空 `hand` 后才切到终结面板。

- **[管理端的可见范围决定了运维能力的边界]** → 一致性校验的价值全在已派过奖的赛事上（`entrant_count` 漂移直接影响派奖金额），而赛事列表默认只给报名中与进行中。列表因此需要一个 `include_finished`，否则那个校验恰好在唯一需要它的时候不可达。

## Migration Plan

1. Alembic 迁移：建 `blackjack_tournament`、`blackjack_tournament_entry` 两张表，为 `blackjack_hand.tournament_id` 加 `(tournament_id, tg_id)` 索引。纯新增，无既有表结构变更，无数据迁移
2. **先落六处隔离过滤并单独上线**——此时尚无赛内手牌，过滤是无操作（no-op），可零风险验证现金局榜单与个人统计口径逐位不变
3. 前端牌桌组件抽取，单独验证现金局无回归（纯重构，不含新功能）
4. 后端赛事逻辑上线，管理面板可见，**不创建任何赛事**
5. 管理员创建一场小规模内测赛事（`min_entrants` 调低），核对：报名扣费与并发不超员、赛内筹码结算与零抽水、赛内不触发幸运奖池、淘汰与完赛判定、资格门、档位截断归一、派奖入账、勋章授予与续期、五处通知各发一次且不重复、完赛截止的两阶段清场
6. 前端赛事大厅与赛内牌桌启用

**回滚**：21 点服务端停用开关即可阻止创建新赛事与新报名，进行中赛事仍能正常结算派奖（spec 已规定）。两张表可保留，无需回退迁移。若需在赛事进行中回滚，管理员应先取消处于报名中的赛事（全额退款），进行中的赛事让其自然结束——**不提供强制作废进行中赛事的路径**，因为报名费已收而筹码无法折算回积分。

**冷启动**：首场赛事建议把 `min_entrants` 设在社区实际活跃人数以下，并配 `seeded_prize_credits` 提高首场吸引力；两者都是管理员显式操作。

## Open Questions

无。
