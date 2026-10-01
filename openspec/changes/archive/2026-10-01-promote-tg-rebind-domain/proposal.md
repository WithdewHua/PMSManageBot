## Why

TG 换绑（`rebind_user_tg_id`）是管理员手动执行的运维操作，代码里没有调用方。`restructure-backend-architecture` 把它原样搬进了 `tg_rebind` 领域，但它本身有三类问题。

**合并模式目前不可用。** `make-credit-changes-atomic` 把积分合并改成调用 `credits_service.add_tx`，但 credits 的 service 里没有这个函数。只要旧 ID 有积分，合并就抛 `AttributeError`，整体回滚并返回 `False`。生产环境还在跑重构前的版本，暂时不受影响。

**会漏迁数据，还会把用户拆成两半。** 它按手写的清单迁移表，2026 年 8–9 月新增的表没有加进去：

- 5 张引用 `statistics.tg_id` 的表：免费次数、21 点手牌、锦标赛报名、周返水、礼包领取状态。
- 礼包和锦标赛的创建人列：`gift_pack.created_by`、`blackjack_tournament.created_by`。
- 以字符串或 JSON 形式存的 TG ID：积分兑换邀请码时记录的 `invitation.used_by = "credits_by_<TG ID>"`，以及礼包受众名单中的 TG ID。

后果：

- **换到全新 ID**：
  - 在 PostgreSQL 上，带外键的列靠 `ON UPDATE CASCADE` 跟着改，但上面两列创建人和字符串形式的 ID 不会改。
  - SQLite 没有打开外键，级联不会发生：勋章、线路调度、自建线路、捐赠和加密货币订单、Vaultwarden 记录以及上面 5 张表，都会留在旧 ID 上。
- **合并到已有 ID**：
  - 旧 ID 只要在那 5 张表里有记录，删除旧的 `statistics` 行时就会违反外键，整体回滚。
  - 补上这 5 张表以后，两边都有记录时还会撞上唯一约束，例如同一枚勋章、同一个礼包的领取状态、同一场锦标赛的报名、同一周的返水。
  - 两边都有 Overseerr 账号时，合并后会出现两行，而按 TG ID 查询的代码假定只有一行。
  - `statistics` 只合并了 `credits` 和 `donation`，锦标赛钱包余额和 21 点的两个计数器随旧行一起被删掉。
- **只指定一个媒体账号时**：旧 TG 名下的另一个媒体账号仍然指向旧 ID，而积分等 TG 维度的数据已经全部迁走，用户被拆成两半。
- **Emby 用户名**：按用户名查找 Emby 账号时区分大小写，与其他地方的查询不一致。

**结构上容易出错。**

- 它直接改写 13 个领域的表。每新增一张存 TG ID 的表，都要有人记得改这份清单，上面的漏迁就是这么来的。
- 手动执行只能通过 `db.rebind_user_tg_id(...)`。门面删除后，这个入口也就没有了。

## What Changes

- **按领域分担迁移**：
  - 每个存有用户 TG ID 的领域，都在自己的 repository 里提供两个函数：一个检查冲突和在途状态，一个执行迁移（`reassign_tg_id_tx`）。
  - 每个领域只处理自己的表，包括管理员审计列，以及以字符串或 JSON 形式存的 TG ID。
  - 不依赖数据库的级联更新：先确保新 ID 有 `statistics` 行，再逐列显式迁移，最后删除旧行。这样在 SQLite（无论是否打开外键）和 PostgreSQL 上结果一致。
- **合并规则**（已与维护者确认）：
  - 换绑以 Telegram 身份为单位：旧 TG ID 名下的 Plex、Emby、Overseerr 账号和全部数据一起迁到新 ID。
  - `statistics` 的各列相加：积分、捐赠额、锦标赛钱包余额、21 点连败计数和免费转盘进度。
  - 遇到唯一冲突就整体拒绝，不做任何改动，并输出冲突清单。冲突包括：同一枚勋章、同一个礼包的领取状态、同一周的返水、同一场锦标赛的报名、两边都有 Overseerr 账号，以及新 ID 已经绑定了同类媒体账号。
  - 旧 ID 有未结束的 21 点手牌，或者报名中、进行中的锦标赛时拒绝。其他在途记录（竞拍出价、未开奖的夺宝和预言、待处理的捐赠和订单、待审核的自建线路）照常迁移，之后按新 ID 结算。
  - 字符串和 JSON 形式的 TG ID、管理员审计列全部改写。礼包受众名单改写后去重。
  - 被定位的媒体账号还没有绑定 TG 时，按绑定规则处理：确保新 ID 有 `statistics` 行，并转入账号上未绑定期间积累的积分。
- **`tg_rebind` 只负责编排**：
  - repository 在一个事务里先锁定新旧两个 `statistics` 行，再按固定顺序调用各领域的检查函数；全部通过后，再按固定顺序调用各领域的 `reassign_tg_id_tx`。
  - service 在提交后刷新相关媒体账号的用户信息缓存；积分缓存由 credits 的 `*_tx` 在提交后自动失效。
- **稳定的手动入口**：
  - 在已有的 `app/manage.py` 中新增 `python -m app.manage rebind-tg-id` 子命令，可以用旧 TG ID、Plex 邮箱或 Emby 用户名（不区分大小写）定位旧身份。
  - 命令输出每个领域迁移的行数。失败时说明原因，例如找不到账号、存在冲突（附清单）或存在在途的 21 点。
  - 支持 `--dry-run`：在事务里完整执行一遍后回滚，只输出将要发生的变化。
  - 旧 ID 如果在 `TG_ADMIN_CHAT_ID` 中，命令会提示管理员手动修改部署配置。
  - `app.manage` 加入顶层分层合约，与 `api`、`bot`、`schedule` 同属组装层。
  - `docs/architecture.md` 手动运维清单里的调用方式改为这个命令，并补上已有的 `legacy-credit-sync` 和 `report` 两个子命令。
- **删除旧入口**：`TgRebindRepository` mixin 和 `db.rebind_user_tg_id` 随领域提升一起删除。
- **防止再次漏表**：
  - 新增架构测试。存 TG ID 的列用列上的 `info` 元数据标记（不改表结构），测试要求每一个被标记的列都被某个领域的 `reassign_tg_id_tx` 覆盖。
  - 名称可疑、但既没有被标记为 TG ID、也没有被明确声明"不是 TG ID"的列，同样会让测试失败。例如名为 `*_by`、`owner` 或 `user_id` 的列。
  - 以字符串或 JSON 形式存 TG ID 的位置，在同一份登记表中列出并逐项测试。
- **清空本领域名下的基线条目**。

## Capabilities

### New Capabilities

- `tg-rebind`：TG 换绑的行为约定，包括：
  - 以 Telegram 身份为单位迁移哪些数据。
  - 换到全新 ID 与合并到已有 ID 的规则。
  - 冲突和在途状态的拒绝条件。
  - 整个换绑在一个事务里完成，任何一步失败都整体回滚；SQLite 和 PostgreSQL 的结果一致。
  - 手动命令的参数、输出和演练模式。

### Modified Capabilities

无。

## Impact

- **代码**：
  - `domains/tg_rebind/`。
  - 15 个领域的 repository 新增检查函数和 `reassign_tg_id_tx`：identity、credits、donation、blackjack、badges、gift_pack、luckywheel、treasure、prediction、auction、lines、custom_lines、crypto_donation、vaultwarden、invitation。
  - 各领域 models 给存 TG ID 的列加上 `info` 标记。
  - `app/manage.py`、`pyproject.toml`（顶层分层合约加入 `manage`）、`tests/architecture/`、`docs/architecture.md`。
- **测试**：两种换绑、各类冲突和在途拒绝都要覆盖。在 SQLite 上分别开、关外键约束各跑一遍，再在一次性 PostgreSQL 上跑一遍。
- **历史数据**：
  - 生产以往的换绑，合并失败时都整体回滚了，不会留下迁了一半的数据。
  - 换到新 ID 的操作，可能让两列创建人和字符串形式的 ID 还指向旧 ID。实施时用只读脚本列出这些悬空的值，由维护者决定是否手动修正。
  - SQLite 部署的历史数据不在范围内。
- **运维**：手动换绑的方式从 Python 交互环境改为命令行。
- **依赖**：`promote-remaining-domains`。届时各领域都已是目标形态，可以直接在各自的 repository 里提供这两个函数。
