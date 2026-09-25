## Context

动机见 proposal.md。以下是决定实现方式的现状与约束。

**发放分发器**：`_grant_gift_pack_rewards`（`db.py:12029`）在 `claim_gift_pack` 的事务内执行，此时礼包行已被 `with_for_update()` 锁住。每个奖励分支都必须复用调用方的 `session`。现有的发放辅助函数大多自开连接：
- `unlock_line_schedule`（`db.py:10692`）
- `set_download_unlocked`（`db.py:11665`）
- `add_invitation_code`（`db.py:700`）

在外层持锁时另开连接有死锁风险，`_settle_blackjack_hand` 的注释记录过同类问题。当初 Premium 奖励就是为此给 `update_premium_status` 加了 `session` 参数。

**`luckywheel_free_spins` 假定所有行都来自 21 点**，依赖这个假设的地方：
- 周上限计数（`db.py:3230`）：只按 `tg_id` 与 `granted_at_ms` 过滤。
- 获得通知游标（`db.py:3541`）：扫描全部新行，私信写死「打满手数奖励到账」（`routers/activities/blackjack.py:266`）。
- 单次转盘消耗后，写 `wheel_stats` 时来源写死为 `"blackjack_free"`（`routers/activities/luckywheel.py:416`）。响应里的 `used_free_spin` 由它推出，前端据此显示「本次消耗了 21 点免费机会」（`LuckyWheel.vue:103`）。
- 对账脚本（`scripts/blackjack_retention_audit.py:112`、`:207`）按行计数，不看来源。

以下几处本来就不区分来源，可以直接复用：
- 消耗顺序：按 `expires_at_ms` 取最早一张。
- 到期提醒：`list_expiring_blackjack_freespins`。
- 可用次数概览：`get_blackjack_freespin_summary`。
- 补偿归还：`release_blackjack_freespin`。

**邀请码**：`add_redeem_code`（`db_func.py:1414`）用 `uuid3(NAMESPACE_URL, str(uid + time()))` 生成码。同一秒内批量生成时输入可能重复，从而撞主键。特权码的做法是把码追加进内存里的 `settings.PRIVILEGED_CODES`，再整体重写 `.env`（`save_config_to_env_file`）。这个外部副作用不在数据库事务里，也没有并发保护。

**下载权限**：积分解锁的路由（`routers/user.py:1998`）是先写数据库，再同步媒体服务器（Plex `update_sync_for_user`，Emby `update_download_permission_for_user`），同步失败只记 warning。Premium 到期撤销时会跳过已有 `unlock_time` 的用户（`premium.py:50`），所以永久解锁能在 Premium 到期后保留。`sync_media_permission` 碰到已有 `unlock_time` 的用户会直接返回，不能用来同步本次的永久解锁。

## Goals / Non-Goals

**Goals:**
- 新增的 5 种奖励都接入同一个领取事务，与已有奖励同生共死。只有无法回滚的外部副作用例外，它们在事务提交后执行（见 D5）。
- 免费机会按来源解耦后，21 点侧的行为与改动前逐项一致：周上限、通知、对账都不变。

**Non-Goals:**
- 不给已有的积分解锁路由（线路调度、下载）改变事务结构，它们的行为不变。
- 不修复 `add_redeem_code` 自身的 `uuid3` 碰撞隐患。本变更只保证礼包路径不受影响（见 D3），其他调用方另行处理。
- 不让十连抽消耗免费机会。

## Decisions

### D1 礼包免费机会写入同一张表，用 `source` 区分

写入 `luckywheel_free_spins`，`source='gift_pack'`，`expires_at_ms = 领取时刻 + 有效天数`。

- **备选**：新建一张礼包免费机会表。
- **否决理由**：消耗、概览、到期提醒、角标都得改成合并两张表。「最早到期优先、不分来源」这条规则也要跨表实现。统一一张表后，这些消费方不用改。

`source` 是既有的 Text 列，不需要改表结构。

### D2 只针对 21 点的逻辑按来源过滤，不用否定条件

以下三处都加 `source == 'blackjack'`：
- 周上限计数；
- 获得通知游标的扫描；
- 对账脚本的两处计数。

**为什么不用 `source != 'gift_pack'`**：以后再加新来源时，否定条件会让它悄悄混进 21 点的口径；肯定条件天然只包含 21 点。

**通知游标仍按全表 id 推进**：扫描只挑 21 点来源的行，但游标取本轮扫描范围内的最大 id。这样礼包行夹在中间时游标也能越过它，不会卡住，也不会漏发 21 点的行。

### D3 消耗时返回来源，参与记录按来源映射

`consume_blackjack_freespin` 返回值增加 `source`。路由按下表映射成 `wheel_stats.source`：

| 机会来源 | `wheel_stats.source` |
|---|---|
| `blackjack` | `blackjack_free`（沿用既有值，保持历史连续） |
| `gift_pack` | `gift_pack_free` |

`LuckyWheelSpinResult` 的两个字段：
- `used_free_spin`：改为对任何免费来源都为真。
- 新增 `free_spin_source`：前端据此选文案，不再写死「21 点免费机会」。

方法名 `*_blackjack_freespin` 暂不改，避免大范围改名。在 docstring 里写明它们对所有来源生效。

### D4 解锁与邀请码用事务内的私有辅助函数

新增三个私有辅助函数，都接收调用方的 `session`，只做数据库写入，不含任何外部调用：
- `_grant_feature_unlock_tx(session, tg_id, service, feature)`：处理线路调度与下载解锁。
- `_grant_invite_codes_tx(session, tg_id, count)`
- `_grant_tournament_wallet_tx(...)`：见 D6。

公开函数（`unlock_line_schedule` 等）保持不变。

- **备选**：给公开函数加可选的 `session` 参数，参照 Premium 的做法。
- **否决理由**：这几个公开函数逻辑很简单（一条 UPDATE 或 INSERT），重复成本很低；给它们加参数反而要回归既有的积分解锁路径。

**「已拥有」直接读永久解锁标记列**，而不是调 `check_download_unlock`：
- 线路调度：`line_schedule_unlocked`
- 下载：Plex 的 `sync_unlocked`、Emby 的 `download_unlocked`

原因是 `check_download_unlock` 把 Premium 也算作已解锁，按它判断会导致 Premium 用户永远拿不到永久解锁，与 spec 的「Premium 用户获得永久解锁」相悖。

**邀请码用 `uuid4().hex` 生成**，与既有码同为 32 位十六进制，不会重复。

### D5 外部副作用：特权码写在提交前，媒体同步在提交后

两种副作用的失败后果不同，所以放在事务的不同位置。

**特权码配置：在提交前写，作为发放的最后一步。**
- 写失败就抛异常，整个领取回滚，满足 spec 的「与领取同生共死」。
- 反过来，配置写成功但事务提交失败，只会在配置里留下一个没有对应 `Invitation` 行的字符串。没有人能用它，所以无害。
- 如果改成提交后再写，写失败时用户手里就是一个「承诺是特权、实际是普通」的码，而且无法补救。

`settings.PRIVILEGED_CODES` 的追加与写文件用一把模块级 `threading.Lock` 串行化。礼包行锁只会串行同一个礼包的领取，不同礼包的并发领取仍会竞争同一个 `.env` 文件。

**下载权限同步：在提交后执行，失败只记录并通知管理员，不回滚。**
- 沿用 `pending_permission_sync` 的模式，新增 `apply_download_unlock_to_media(tg_id, service)`。
- 不复用 `sync_media_permission`：它对已有 `unlock_time` 的用户直接返回（见 Context）。
- 失败时：领取响应里对应条目的 `message` 说明「同步未完成」，并用 `_notify_detached` 发一条「需人工处理」的管理员通知。这条通知和「发放失败并已回滚」是两种文案，不能混用。
- 发放快照记录的是数据库的解锁状态。数据库是权威，管理员已被通知去补同步。

### D6 争霸赛余额复用积分分支的行锁

用 `with_for_update()` 锁该用户的 `Statistics` 行后，累加 `tournament_wallet_credits`。

同一个礼包里积分和余额的发放锁的是同一行，锁顺序与既有积分分支一致：先锁礼包，再锁 statistics。

周损失返还的净变动口径本来就不统计争霸赛余额的变动（见 blackjack spec「周损失返还与争霸赛余额」），所以礼包入账不影响返还结算。

### D7 用一张表登记奖励类型的元数据

在一处集中登记每种奖励类型：

| 奖励类型 | 是否需要绑定 | 文案模板 | 统计汇总口径 |
|---|---|---|---|
| `credits` | 否 | 「100 积分」 | 合计积分数 |
| `premium_days` | 是 | 「7 天 Premium」 | 合计天数（跳过的不计） |
| `wheel_free_spins` | 否 | 「3 次大转盘免费机会（7 天有效）」 | 合计次数 |
| `tournament_wallet` | 否 | 「50 争霸赛余额」 | 合计数额 |
| `invite_codes` | 否 | 「2 枚（特权）邀请码」 | 合计枚数 |
| `line_schedule_unlock` | 是 | 「线路调度解锁」 | 合计生效服务数 |
| `download_unlock` | 是 | 「下载权限解锁」 | 合计生效服务数 |

以下几处都读这张表，不再各自写 `if type == ...`：
- `create_gift_pack` / `update_gift_pack` 自动补绑定要求：原来是 `has_premium_reward`，推广为「是否需要绑定」这一列。
- `_gift_pack_reward_label`
- `get_gift_pack_stats` 的 `reward_totals`
- 过期汇总通知

`add-gift-pack-audience-and-tasks` 也会用「是否需要绑定」这一列。

### D8 数值上限

以下上限只写在 schema 校验里，spec 只要求「超出范围的数值被拒绝」：

| 奖励类型 | 上限 |
|---|---|
| `wheel_free_spins` | 次数 1–100，有效天数 1–365 |
| `tournament_wallet` | 数额 (0, 100000] |
| `invite_codes` | 数量 1–20（邀请码稀缺，上限压低） |

## Risks / Trade-offs

- [特权码写配置发生在持锁的事务内，写 `.env` 是一次文件 IO，会延长持锁时间] → 只有含特权码奖励的礼包才走这条路，一次写入通常是毫秒级。锁只影响同一个礼包的并发领取，影响有限。
- [领取响应与快照中出现了明文邀请码] → 快照只对该用户本人和管理员可见，与「我的邀请码」列表的可见范围相同。
- [礼包免费机会的使用会计入大转盘排行榜、个人游戏次数和游戏王勋章的转盘次数] → 这些统计本来就对所有来源一视同仁：21 点来源的免费参与一直计入。保持一致，不单独排除。
- [回滚部署时，旧代码读到含新奖励类型的礼包会抛「不支持的奖励类型」] → 回滚前先停用含新奖励类型的礼包。已领取的记录只用于展示，不受影响。
- [对账脚本改了口径，改动前后的历史周报无法直接比较] → 改动前礼包还不能发免费机会，历史数据里只有 21 点来源，所以加过滤前后结果一致。

## Migration Plan

1. 本变更没有表结构变更，不需要 Alembic 迁移。
2. 后端与前端同批发布：新奖励类型的展示依赖前端，`free_spin_source` 字段对旧前端是可忽略的新增字段。
3. 回滚：先停用含新奖励类型的礼包，再回退代码。已写入的 `source='gift_pack'` 免费机会行在旧代码下会被当作 21 点来源——会占用周上限、会被通知一次。影响有限，可以接受。
