## Context

动机见 `proposal.md` 的 Why。行为契约见本变更的 `specs/blackjack-tournament/spec.md`。本文只记录实现取舍。

当前发牌（`create_blackjack_tournament_hand`）在同一事务里：无锁读赛事 → 锁报名 → 锁积分行 → 扣筹码 → 插手牌。`now_ms` 在进 session 之前冻住。完赛结算（`settle_blackjack_tournament`）在另一事务：CAS `2→3` → 锁全部报名 → 派奖。两边不共享可移植的赛事锁。`with_for_update()` 在 SQLite 上是 no-op，项目里赛事流转已经因此改成条件 UPDATE（`_claim_tournament_transition`）。

提前完赛（`early-settle-blackjack-tournament`）不修这条；其 design 决策 8 把本洞标为独立变更。

## Goals / Non-Goals

**Goals:**

- 发牌与结算对同一赛事互斥到提交
- SQLite 与 PostgreSQL 行为一致
- 锁序与现有结算相同：`tournament → entry → statistics`，避免与报名行死锁
- 不引入 `SETTLING` 中间态，不加列

**Non-Goals:**

- 不改动作路径（要牌/停牌等）的锁：它们改的是已存在的手牌，清场按手牌事务串行
- 不把清场与派奖合并成一个事务
- 不改资格门、奖池、前端

## Decisions

### 1. 同步点是「对进行中赛事行的条件 UPDATE」，不是 FOR UPDATE，也不是新状态

```
UPDATE blackjack_tournament
   SET status = 2
 WHERE id = :id AND status = 2
```

`rowcount == 1` 表示本事务钉住了一场进行中的赛事，直到提交或回滚。PostgreSQL 上行锁；SQLite 上库级写锁。结算的 CAS `2→3` 与发牌的这次 UPDATE 抢同一行同一谓词，先提交的一方决定后到者是「仍进行中」还是「已经不是」。

不新增 `SETTLING`：多一个状态要改 CHECK、tick、前端映射和重启恢复，而条件 UPDATE 已经是本项目证明过的可移植互斥。

不 bump `reminder_sent_at` 或其他业务列：无意义的写会造成提醒去重或审计噪音。`status = status` 在 PostgreSQL 上仍取行锁。

### 2. 发牌先钉赛事，再锁报名；截止用锁后的墙钟

现有发牌若先锁报名再锁赛事，会与结算的 `赛事 → 报名` 互相等待。因此写锁必须发生在 `_lock_tournament_entry` 之前。

锁到之后用 `int(time.time() * 1000)` 重检截止，丢弃进 session 之前冻住的 `now_ms`。否则「锁前未到截止、等锁期间截止已过、锁后仍用旧时点发牌」会把新手牌送进清场与 CAS 之间。

抢不到写锁：再读一次区分「不存在」与「不是进行中」，分别抛现有的 `tournament not found` / `tournament not running`。

### 3. 结算钉住之后、CAS 之前，在本事务里再扫未终结手牌

tick 仍是先 `force_settle_tournament_hands`（每手独立事务）再 `settle_blackjack_tournament`。两调用之间仍可能有发牌提交。结算侧：

1. 同一把写锁钉住进行中赛事
2. 本会话 `COUNT` 未终结手牌
3. 若 `> 0`：不 CAS、不派奖，返回 `settled=False`（赛事仍进行中，下一分钟 tick 会先清场）
4. 若 `= 0`：CAS `2→3` 再派奖

CAS 仍保留：写锁保证与发牌互斥，CAS 仍是通知与派奖的去重闸门。已经持锁时 CAS 几乎总成功；失败则按现有口径当作他人抢先。

### 4. 动作路径不加这把锁

`_lock_tournament_hand` 先锁手牌再读赛事。给它加赛事写锁会变成 `hand → tournament`，与结算的 `tournament → entry` 以及发牌的 `tournament → entry` 交错，容易死锁。未终结手牌由清场按手牌事务处理；本变更要堵的是「结算之后新插入的手牌」。

## Risks / Trade-offs

- **[Risk] `status = status` 被优化成不取锁** → PostgreSQL 对匹配行仍取行锁；SQLite 的 UPDATE 取写锁。若某后端将来跳过无变化 UPDATE，再改为加无语义计数列。当前两套后端不需要。
- **[Risk] 发牌持锁时间变长** → 锁粒度是一场赛事，持有到发牌事务结束（含天胡立即结算）。同场其他人发牌会等这一次，跨赛事不堵。可接受。
- **[Trade-off] 结算扫到未终结手牌只推迟、不在本事务清场** → 清场仍是每手独立事务，失败不能和派奖绑在一起。推迟给 tick 重试，与现有 `cleared=False` 口径一致。

## Migration Plan

- 无 schema 变更。部署即生效。
- 回滚：去掉写锁后，截止路径上的并发窗口回到现状；已结算赛事保持已结算。
