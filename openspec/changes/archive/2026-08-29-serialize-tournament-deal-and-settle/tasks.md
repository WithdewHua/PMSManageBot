## 1. 赛事级写锁

- [x] 1.1 在 `src/app/databases/db.py` 新增对进行中赛事行做条件 UPDATE（`status = TOURNAMENT_RUNNING` 写回自身）的辅助方法：`rowcount == 1` 后加载并返回该行，否则返回 `None`。方法内 `flush` 后再 UPDATE，与 `_claim_tournament_transition` 相同。不使用 `with_for_update()`。静态核对：谓词含 `id` 与 `status == 进行中`，不改其他列
- [x] 1.2 `create_blackjack_tournament_hand` 在锁报名、扣筹码、插手牌之前调用该方法；抢不到则按行是否存在抛出既有的 `tournament not found` / `tournament not running`。取得锁后用当前墙钟重检 `play_deadline_ms`，到期抛 `tournament finished`。锁序为 `tournament → entry → statistics`

## 2. 结算侧复检

- [x] 2.1 `settle_blackjack_tournament` 在 CAS `2→3` 之前取得同一把写锁；本会话统计该赛事未终结手牌，若仍有则返回 `settled=False` 且不改状态、不派奖。无未终结手牌时再走既有 CAS 与派奖。`force_settle_tournament_hands` 仍由 tick 在本方法之前调用
- [x] 2.2 更新 `create_blackjack_tournament_hand`、`settle_blackjack_tournament`、`_lock_tournament_hand` 与 `BlackjackTournament.play_deadline_ms` 的注释：同步点是条件 UPDATE，不是固定截止时点，也不是 FOR UPDATE。动作路径不加这把锁

## 3. 核对

- [x] 3.1 静态核对资格门、CAS 去重、tick 先清场再结算的顺序未改
- [x] 3.2 `ruff check --select E4,E7,E9,F src/app/databases/db.py src/app/models/models.py` 通过
- [x] 3.3 `pytest tests/test_blackjack_tournament_settle.py` 覆盖：已结算后发牌拒绝、截止后发牌拒绝、锁后墙钟过截止拒绝、未终结手牌推迟结算、CAS 幂等
