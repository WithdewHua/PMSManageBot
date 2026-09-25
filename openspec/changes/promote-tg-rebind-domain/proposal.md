## Why

TG 换绑（`rebind_user_tg_id`）是管理员手动执行的运维操作，代码里没有调用方。`restructure-backend-architecture` 把它原样搬进了 `tg_rebind` 领域，但它本身有两类问题。

**会漏迁数据。** 按照要迁移的表，它手写了一份清单。2026 年 8–9 月新增的几张表没有加进去：

- 5 张引用 `statistics.tg_id` 的表：免费次数、21 点手牌、锦标赛报名、周返水、礼包领取状态。
- 礼包和锦标赛的创建人列：`gift_pack.created_by`、`blackjack_tournament.created_by`。

在生产使用的 PostgreSQL 上，后果如下：

- **换到全新 ID**：上面两列创建人不会跟着改，只影响创建过礼包或锦标赛的管理员。其余带外键的列靠数据库的 `ON UPDATE CASCADE` 跟着改。SQLite 部署下项目没有打开 `PRAGMA foreign_keys`，级联不会发生，勋章、线路调度、自建线路、捐赠记录、Vaultwarden 记录和上面 5 张表都会留在旧 ID 上。
- **合并到已有 ID**：
  - 只要旧 ID 在那 5 张表里有记录，删除旧的 `statistics` 行时就会违反外键，整个操作回滚，返回 `False`。
  - 补上这 5 张表之后，两边都有记录时还会撞上唯一约束，例如同一枚勋章、同一个礼包的领取状态、同一场锦标赛的报名、同一周的返水。
  - 按 TG ID 查 Overseerr 账号的代码假定只有一行。两边都有账号时，合并后查询会报错。
  - `statistics` 只累加 `credits` 和 `donation`。锦标赛钱包余额和 21 点的两个计数器会随旧记录一起删除。
- **缓存不刷新**：`user_info_cache` 以媒体用户名为键，缓存值里存有 TG ID。换绑后缓存里还是旧 ID；合并后 `user_credits_cache` 里的积分也是旧的。

**结构上容易出错。**

- 它直接改写 13 个领域的表。每新增一张存 TG ID 的表，都要有人记得改这份清单，上面的漏迁就是这么来的。
- 手动执行只能通过 `db.rebind_user_tg_id(...)`。`retire-legacy-db-facade` 删除门面后，这个方式也就没有了。

## What Changes

- **按领域分担迁移**：每个存有用户 TG ID 的领域，都在自己的 repository 里提供 `reassign_tg_id_tx(session, old_tg_id, new_tg_id, *, merge)`。
  - 每个领域只处理自己的表。
  - 合并时的冲突也由本领域按规则处理。
  - 不依赖数据库的级联更新，每一列都显式迁移，SQLite 和 PostgreSQL 的结果一致。
- **修复漏迁**：补上上面列出的 5 张表和两列创建人。
- **定下合并规则**：实施前和维护者逐条确认，然后写进 `tg-rebind` 规格。待定的有：
  - `statistics` 上的锦标赛钱包余额（`tournament_wallet_credits`），以及 21 点的两个计数器（`blackjack_lose_streak`、`blackjack_hands_since_freespin`）怎么合并。
  - 新旧 ID 持有同一枚勋章、同一个礼包的领取状态、同一场锦标赛的报名、同一周的返水时，保留哪条，数值要不要合并。
  - 两边都有 Overseerr 账号时怎么处理。
  - 旧 ID 有进行中的 21 点手牌或锦标赛时，是拒绝换绑还是照常迁移。
  - 积分兑换的邀请码把兑换人记成 `invitation.used_by = "credits_by_<TG ID>"`，这个值要不要改写。
- **`tg_rebind` 只负责编排**：
  - repository 在一个事务里，按固定顺序调用各领域的 `reassign_tg_id_tx`。
  - service 在事务提交后刷新相关媒体账号的用户信息缓存和积分缓存。
- **稳定的手动入口**：
  - 新增 `app/manage.py`，提供 `python -m app.manage rebind-tg-id …` 命令。它和 `api`、`bot`、`schedule` 同属入口组装层。
  - 命令输出每个领域迁移的行数。失败时说明原因，比如找不到账号、目标 ID 已绑定同类账号，或者有无法自动处理的冲突。
  - 支持 `--dry-run`：在事务里执行，然后回滚，只输出将要迁移的内容。
  - `docs/architecture.md` 手动运维清单里的调用方式改为这个命令。
- **防止再次漏表**：新增架构测试，要求模型里每一个存 TG ID 的列都被某个领域的 `reassign_tg_id_tx` 覆盖。这些列用列上的 `info` 元数据标记，不改表结构。以后新表漏掉了换绑，测试会直接失败。
- **清空本领域名下的基线条目**。

## Capabilities

### New Capabilities

- `tg-rebind`：TG 换绑的行为约定，包括：
  - 换到全新 ID 时，哪些数据跟着迁移。
  - 合并到已有 ID 时，哪些数据跟着迁移，以及各类冲突的处理规则。
  - 整个换绑在一个事务里完成，任何一步失败都整体回滚。
  - SQLite 和 PostgreSQL 的结果一致。

  规格要按搬迁后的代码来写，轮到本变更时再补。

### Modified Capabilities

无。

## Impact

- **代码**：
  - `domains/tg_rebind/`。
  - 各领域 repository 新增 `reassign_tg_id_tx`。
  - `app/manage.py`。
  - `pyproject.toml`：在顶层分层合约里加入 `manage`。
  - `tests/architecture/`、`docs/architecture.md`。
- **测试**：两种换绑都要覆盖。在 SQLite 上分别开、关外键约束各跑一遍，再在一次性 PostgreSQL 上跑一遍。
- **历史数据**：
  - 生产以往的换绑，合并失败时都整体回滚了，不会留下迁了一半的数据。
  - 换到新 ID 的操作，可能让两列创建人还指向旧 ID。实施时查一下这两列里有没有已经不存在的 TG ID，有的话手动修正。
  - SQLite 部署的历史数据不在范围内。
- **运维**：手动执行换绑的方式从 Python 交互环境改为命令行。旧方式可以用到 `retire-legacy-db-facade` 为止。
- **依赖**：`promote-remaining-domains`。届时各领域都已是目标形态，可以直接在各自的 repository 里提供 `reassign_tg_id_tx`。
