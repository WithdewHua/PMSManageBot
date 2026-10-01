## Why

积分余额现在按"先读、再算、再写回绝对值"的方式修改：

- B3 搬迁后的初步盘点已经发现 18 处直接写 `Statistics.credits`、2 处 SQL 算术更新、32 处调用 `update_user_credits(credits=新余额)`，以及若干直接 `.values(credits=...)` 写入；最终迁移清单以 Task 1.1 的冻结 AST inventory 为准，不用一个过时的总数掩盖新增写入。
- 这些写入大多没有加锁。最典型的是 `transfer_credits`：它不加锁地读出双方余额再写回。如果此时正好有一局 21 点在加锁结算，结算加上的积分会被转账写回的值覆盖掉。
- 尚未绑定 TG 的账号积分（`plex_user.credits`、`emby_user.emby_credits`）也有同样的问题。

积分是用户最在意的数字，也是后续每个领域提升都要用到的底层能力，所以这个变更排在所有 promote 变更之前。

## What Changes

- **把 `credits` 领域提升为目标形态**：使用模块级 repository 加 service，从门面上摘掉它的 mixin。
  - repository 只提供加锁的增量操作：`add_tx(session, …)` 和 `deduct_tx(session, …)`，后者在余额不足时抛出 `InsufficientCredits`。两者都有对应的单事务版本。不提供直接设置余额的函数。
  - service 提供 `transfer()`：在同一个事务里，按固定顺序锁住转出方和转入方的行。
  - 以上操作覆盖三处余额：`statistics.credits`、`plex_user.credits`、`emby_user.emby_credits`。
  - 积分缓存（`user_credits_cache`）在事务提交后失效。
- **把冻结 inventory 中的全部积分写入改为增量调用**，包括已发现的 18 处直接赋值、2 处 SQL 算术更新、32 处 `update_user_credits` 调用和其他直接 `.values(credits=...)` 写入。如果积分变动必须和其他写入放在同一事务里（比如 21 点结算、礼包领取），就改用 `*_tx`，复用调用方的 session。
- **删除 `update_user_credits`**，也就是按绝对值写余额的入口。
- **保持外部表现不变**：沿用现有的舍入规则（两位小数），接口的响应格式和错误文案不变。
- **新增并发测试**：在一次性 PostgreSQL 上并发执行转账、21 点结算和扣费，验证余额守恒、不会透支。

## Capabilities

### New Capabilities

- `credits`：积分账本的一致性约定，包括：
  - 每次变动都是原子增量。
  - 余额不足时，扣减整体失败，不会透支。
  - 并发操作不会丢失更新。
  - 转账在一个事务内完成。

### Modified Capabilities

无。21 点、礼包等规格中描述的积分数额不变。

## Impact

- **代码**：
  - `domains/credits/`。
  - 所有写积分的领域：初步盘点的直接写入中有 8 处在 21 点家族；其余分布在账号绑定、礼包、转盘、夺宝、预言、竞拍、捐赠、邀请、线路、媒体权限、观看奖励及换绑等领域。
- **数据库**：无结构变更。
- **行为**：只有在并发场景下才有差别。以前可能丢失更新或透支，改完后不会。
- **依赖**：`restructure-backend-architecture`。
- **基线**：清空记在本变更名下的条目。
