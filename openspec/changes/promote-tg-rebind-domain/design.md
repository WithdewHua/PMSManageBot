# Design

## Context

动机和已确认的合并规则见 proposal.md，行为约定见 `specs/tg-rebind/spec.md`。本设计假定之前的 promote 变更已全部完成：各领域都已是模块级 repository 加 service 的目标形态，门面里只剩尚未退役的空壳。

现状（调研时的 `3f27100`）：

- **现有实现**：`tg_rebind/repository.py` 的 `rebind_user_tg_id(new_tg_id, plex_email=None, emby_username=None)`：
  - 在一个事务里先改媒体账号行，再处理旧 `statistics`：
    - 新行不存在时改主键，依赖 PostgreSQL 的 `ON UPDATE CASCADE` 带动子表。
    - 新行存在时合并 `credits`、`donation`，更新 14 个普通列和 8 个外键列，最后删除旧行。
  - 合并时调用不存在的 `credits_service.add_tx`，只要旧 ID 有积分就失败。
  - Emby 用户名区分大小写。
  - 返回 bool，异常全部吞掉。
- **存 TG ID 的位置**：共 33 个数值列，外加 1 个 JSON 字段（`gift_pack.audience`）和 1 种字符串编码（`invitation.used_by = "credits_by_<ID>"`）。
  - 其中 13 列有外键指向 `statistics.tg_id`（`ON UPDATE CASCADE`，没有 `ON DELETE`，也不是 DEFERRABLE）。
  - 7 列是管理员审计列，其中 `approved_by`、`processed_by` 带外键。
- **SQLite 不打开外键**，所以同样的代码在不同数据库上结果不同。
- **唯一约束**：`user_badges(tg_id, badge_id)`、`gift_pack_user_state(pack_id, tg_id)`、`blackjack_tournament_entry(tournament_id, tg_id)`、`blackjack_weekly_cashback(tg_id, week_start_ms)`，以及 `plex_user.tg_id`、`emby_user.tg_id`。Overseerr 在 `tg_id` 上没有唯一约束，但查询代码假定最多一行。
- **21 点的状态**：
  - 手牌未结束的判断是 status 不在 (3, 4) 中。
  - 锦标赛状态中，1 为报名中、2 为进行中。
  - 超时任务的参数只有 `hand_id`，不含 `tg_id`。
- **缓存**：
  - `user_info_cache` 以媒体用户名为键，值里有 `tg_id`，每 15 分钟全量重写。
  - `user_credits_cache` 在提交后按键失效。
  - TG 资料的文件缓存按 `tg_id` 每日刷新。
- **`app/manage.py`**：已存在，有 `legacy-credit-sync` 和 `report` 两个子命令，但不在任何 import-linter 合约里。

## Goals / Non-Goals

**Goals：**

- 按规格迁移全部存储位置，在 SQLite（无论是否开外键）和 PostgreSQL 上结果相同。
- 冲突和在途状态在任何写入之前检查完毕；有问题就整体拒绝，并一次列出全部问题。
- 新增存 TG ID 的列或编码位置时，如果漏了换绑，架构测试会失败。
- 手动入口改成可演练、可审计输出的命令。

**Non-Goals：**

- 不提供自动解决冲突的工具。冲突由管理员按文档手动处理。
- 不迁移数据库之外的 TG ID，例如部署配置中的 `TG_ADMIN_CHAT_ID` 和 TG 资料的文件缓存。前者只提示，后者等每日刷新。
- 不修改 Overseerr 服务端的账号。
- 不处理 SQLite 部署的历史数据。

## Decisions

### D1 各领域提供检查和迁移两个函数

每个参与换绑的领域，在 repository 中提供：

```python
def check_tg_id_reassign_tx(
    session, old_tg_id: int, new_tg_id: int
) -> list[TgIdReassignIssue]: ...
def reassign_tg_id_tx(session, old_tg_id: int, new_tg_id: int) -> dict[str, int]: ...


REASSIGNED_TG_ID_COLUMNS: tuple[str, ...]  # "table.column"，供架构测试核对
```

- `TgIdReassignIssue` 定义在 `identity/types.py`，包含种类（冲突或在途）、领域、描述和相关记录的标识。
  - 放在最底层的 identity，是因为各参与领域都要构造它，而 `tg_rebind` 在 T4，下层领域不能向上依赖。
  - `types` 已由 `promote-gift-pack-domain` 放行为可以跨域导入的值对象角色。
- 检查函数只读，不加额外的锁。迁移函数返回"列 → 迁移行数"。
- 两个函数都不吞异常，也不打开 session。

参与的领域和各自负责的内容如下：

| 领域 | 迁移内容 | 检查内容 |
|---|---|---|
| identity | Plex、Emby、Overseerr 账号行；最后删除旧 `statistics` 行 | 新 ID 已绑定同类媒体账号；两边都有 Overseerr |
| credits | 旧积分整额移到新 ID（`move_tx`） | — |
| donation | `statistics.donation` 相加；登记记录的 `user_id` 和 `processed_by` | — |
| blackjack | 钱包余额和两个计数器相加；手牌、锦标赛报名、周返水、锦标赛 `created_by` | 未结束的手牌；报名中或进行中的赛事；同一周返水；同一场赛事的报名 |
| badges | `user_badges` | 同一枚勋章 |
| gift_pack | 领取状态；`created_by`；受众名单 JSON 中的 ID（替换后去重） | 同一礼包的领取状态 |
| luckywheel | 免费次数账本；转盘统计 | — |
| treasure / prediction / auction | 参与、投注、投稿、出价、成交，以及创建人、开奖人、审核人 | — |
| invitation | `owner`；`used_by` 中的 `credits_by_<旧ID>` | — |
| lines / custom_lines | 线路调度；自建线路的 `tg_id` 和 `approved_by` | — |
| crypto_donation / vaultwarden | 订单的 `user_id`；兑换记录 | — |

备选方案：由 `tg_rebind` 集中写一份迁移清单。这正是现在漏表的原因，所以不采用。

### D2 不依赖级联的迁移顺序

`tg_rebind` 的 repository 在一个事务里依次执行以下步骤：

1. **定位旧身份**：identity 按旧 ID，或按小写的 Plex 邮箱、Emby 用户名查找。
   - 媒体账号没有绑定 TG 时，改走 D5 的绑定路径。
   - 旧 ID 等于新 ID 时，直接拒绝。
2. **加锁**：按 `tg_id` 升序锁住新旧两个 `statistics` 行（新 ID 还没有这一行时，只锁旧行），再锁两边的媒体账号行。这与 credits 转账的锁顺序一致。
3. **预检**：按参与者顺序调用全部检查函数，汇总问题。有任何问题就抛出 `TgRebindRejected(issues)` 并回滚。
4. **确保新行**：identity 确保新 ID 有 `statistics` 行，没有就新建一行全零的记录。
5. **按固定顺序迁移**：先是各领域的子表（gift_pack、blackjack、luckywheel、treasure、prediction、auction、invitation、custom_lines、lines、badges、donation、crypto_donation、vaultwarden），然后是 `statistics` 各列的所有者（blackjack、donation、credits），最后由 identity 迁移媒体账号，并删除旧的 `statistics` 行。
6. **提交**：汇总各领域返回的计数，然后提交。

整个过程从不修改 `statistics.tg_id`：子表在新行存在之后才改指向，旧行在所有子表迁走之后才删除。所以外键是否打开、是否级联，都不影响结果；删除旧行时也不会违反外键。

"换到全新 ID"就是合并到一个刚建好的空行，所以两种模式走同一条代码路径。

### D3 列的覆盖登记与架构测试

- **标记列**：模型里存 TG ID 的列加 `info={"tg_id": "user"}`，管理员审计列加 `info={"tg_id": "admin"}`。只改元数据，不改表结构，也不生成迁移。
- **声明例外**：名称可疑但并非 TG ID 的列，显式标记为 `info={"tg_id": False}`。例如 `line_traffic_stats.user_id` 存的是媒体账号 ID，`ghost_session_log.user_id` 存的是 Plex 用户 ID。
- **编码位置登记**：`tg_rebind/constants.py` 中的 `ENCODED_TG_ID_LOCATIONS` 登记以字符串或 JSON 形式存 TG ID 的位置：`invitation.used_by` 的 `credits_by_` 前缀，以及 `gift_pack.audience` 的 `user_list.tg_ids`。
- **新增的架构测试**：
  - 每个带 `tg_id` 标记的列，都出现在所属领域的 `REASSIGNED_TG_ID_COLUMNS` 里，而且该领域在参与者列表中。
  - 名称匹配 `tg_id`、`*_tg_id`、`*_by`、`owner`、`winner_id`、`bidder_id`、`user_id`，或带外键指向 `statistics.tg_id` 的列，必须有 `tg_id` 标记；没有标记就失败。
  - 每个编码位置都有对应的迁移测试。
- **测试夹具由登记表生成**：给一个用户在每个被标记的列上都造一行数据，所以新增一列时，夹具会自动覆盖它。

### D4 `statistics` 的合并与所有权

按照 D3 的列归属表，每列由所属领域在自己的函数里合并：

- 积分：credits 用 `move_tx` 把旧行积分整额移到新行，包括会员流量费形成的负余额（由 `fix-live-defects` 的 D1 修正，原来负余额不会被迁移）；`move_tx` 自己登记提交后的缓存失效。
- 捐赠额：donation 相加。
- 锦标赛钱包余额、21 点连败计数、免费转盘进度：blackjack 相加。

这些列在旧行里清零后，identity 再删除旧行。合并规则按维护者的决定，五列全部相加。连败计数和免费转盘进度相加后，可能提前触发救济或免费转盘，这一点记在 Risks 中。

### D5 未绑定 TG 的媒体账号

定位到的账号没有绑定 TG 时，复用 accounts 的绑定逻辑，即 `promote-account-domains` 提供的绑定 `*_tx`：

- 确保新 ID 有 `statistics` 行。
- 用 credits 的 `move_tx` 转入未绑定期间的积分。

新 ID 已经绑定同类账号时拒绝。这条路径不涉及其他领域的数据迁移。

### D6 编排、演练与提交后刷新

- **类型化异常**：在 `tg_rebind/exceptions.py` 中定义 `TgRebindRejected`（携带全部问题）、`TgRebindAccountNotFound` 和 `TgRebindSameId`。
- **service**：
  - `rebind(new_tg_id, *, from_tg_id | plex_email | emby_username, dry_run=False) -> RebindReport` 调用 repository。
  - 演练模式下，repository 在第 6 步不提交而是回滚。这时 `get_session` 会丢弃所有提交后回调，所以缓存不受影响。
- **提交后刷新缓存**：
  - 调用负责网关用户缓存的 lines.service，按被迁移账号的用户名刷新 `user_info_cache`。
  - 积分缓存的失效已经由 credits 的 `*_tx` 登记，提交后自动执行。
- **管理员提示**：`RebindReport` 带上"旧 ID 在 `TG_ADMIN_CHAT_ID` 中"的标志，由命令输出提示。

### D7 `app.manage rebind-tg-id`

- **参数**：`--to NEW_TG_ID`；`--from-tg OLD_TG_ID`、`--plex-email EMAIL`、`--emby-username NAME` 三者互斥且必选其一；可选 `--dry-run`。
- **输出**：
  - 成功时，逐领域列出"表.列：行数"，并标明是否为演练，退出码为 0。
  - 被拒绝时，逐条列出问题，退出码为 2。
  - 找不到账号时，退出码为 3。
  - 其他错误打印原因，退出码为 1。
- **分层合约**：`app.manage` 加入 import-linter 顶层分层合约的组装层，与 `app.api`、`app.bot`、`app.schedule` 同层。
- **文档**：更新 `docs/architecture.md` 的手动运维清单，写入这个命令、已有的 `legacy-credit-sync` 和 `report`，以及每类冲突的手动处理指引。

### D8 删除旧入口与清理基线

- 删除 `TgRebindRepository` 和 `db.rebind_user_tg_id`，同步从门面的组合中移除。
- 清理 `tg_rebind` 名下的 20 条基线条目，以及门面组合边在 Six-tier 和 Acyclic 两个合约中的 2 条忽略项，并下调封存计数。其中 2 条以 `credits.types` 为目标，会先由 `promote-gift-pack-domain` 清除；另有 1 处对 `register_cache_invalidation` 的显式调用，随旧实现一起删除，因为新实现经 `move_tx` 自动登记。
- `scripts/refactor/smoke_b1.py` 调用了旧入口；它属于一次性工具，由 `retire-legacy-db-facade` 删除。本变更只在文档中注明它已失效。

### D9 历史数据检查

新增只读脚本 `scripts/check_dangling_tg_ids.py`，按 D3 的登记表列出所有指向不存在 `statistics` 行的 TG ID，包括数值列、`credits_by_<ID>` 和礼包受众名单。在生产形态副本上运行，结果交给维护者决定是否手动修正。脚本不写数据库。

## Risks / Trade-offs

- **[计数器相加可能提前触发奖励]** → 这是维护者确认的规则。影响只限于合并后下一次结算：救济或免费转盘可能提前发放，而免费转盘仍受每周上限约束。如果要改成取较大值，只需改 blackjack 的迁移函数和对应的规格场景。
- **[拒绝策略让部分换绑需要人工介入]** → 演练模式会一次列出全部冲突；`docs/architecture.md` 给出每类冲突的处理指引，例如删除重复勋章中的一条。
- **[与在途结算争锁]** → 预检已经拒绝在途的 21 点。其他结算事务按 `statistics` 加锁时，会等待换绑提交；换绑提交后，旧 ID 已不存在，这些结算按"找不到用户"失败或重试。建议在低峰期执行；PostgreSQL 检测到死锁时会中止其中一方，换绑是原子的，可以直接重跑。
- **[覆盖测试误报]** → 名称匹配只是兜底，可以用 `info={"tg_id": False}` 显式声明例外，并在 review 时核对。
- **[单个事务较大]** → 重度用户的记录可能有数千行，仍在单事务的可接受范围内；演练模式可以提前看到规模。
- **[不同数据库的计数差异]** → 因为从不修改主键，三种数据库环境下的迁移行数完全相同；测试矩阵逐项比对。

## Migration Plan

1. 标记各领域的列，实现覆盖测试；各领域实现检查和迁移函数，每个领域配测试。
2. 实现编排、service 和命令；在三种数据库环境下跑完整的场景矩阵。
3. 在生产形态副本上运行悬空 ID 检查脚本；对抽样的用户对先演练、再真实执行，核对计数和缓存。
4. 删除旧入口，清理基线，更新文档。
5. 部署：没有 schema 变更。回退就是回退镜像；旧入口的合并功能本来就已不可用，回退不会带来新的风险。

## Open Questions

无。合并规则已由维护者确认。
