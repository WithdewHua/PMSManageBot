## Why

21 点锦标赛的发牌事务只在前段读一次「进行中 / 未到截止」，之后锁报名、扣筹码、插手牌，提交前不重检。结算在另一事务里 CAS `2→3` 并派奖。PostgreSQL 上可以把一手尚未终结的牌插进已经派完奖的赛事：完赛 tick 不再扫已结算赛事，动作端点因 `tournament not running` 拒绝，赛内筹码账短暂不一致。这是预存洞，不随提前完赛引入；提前完赛路径更难踩（发牌中的报名仍是进行中），但截止路径一直能打。`with_for_update()` 在 SQLite 上是 no-op，不能当同步点。

## What Changes

- 发牌与完赛结算共用一个可移植的赛事级写锁（条件 UPDATE，不引入 `SETTLING` 中间态、不加列）
- 发牌在扣筹码 / 插手牌之前拿到该锁，并用锁后的墙钟重检进行中与完赛截止
- 结算拿到同一把锁后，在本事务内再扫一遍未终结手牌；扫到则本轮不 CAS、不派奖，留给下一轮 tick 先清场
- 不改资格门、奖池、前端、表结构

## Capabilities

### New Capabilities

- （无。本变更只补上发牌与结算之间缺失的同步点。）

### Modified Capabilities

- `blackjack-tournament`: 完赛截止与在局手牌的交界须在事务上成立——清场之后、CAS 之前不得再插入新手牌；发牌不得在已结算或已到截止的赛事上提交

## Impact

- `src/app/databases/db.py`：赛事级写锁辅助方法；`create_blackjack_tournament_hand` 与 `settle_blackjack_tournament` 共用
- 锁序保持 `tournament → entry → statistics`，与现有结算一致，避免与报名行互相等待
- 不改引擎、路由、前端、表结构
