## Context

动机见 proposal.md，行为契约见 specs/gift-pack/spec.md。以下是决定实现方式的现状与约束。

**资格结构**：`gift_pack.eligibility` 是一个平铺的 JSON 对象，只有 `min_credits` / `require_premium` / `require_binding` 三个字段，字段之间都是「并且」。三个入口共用同一套判定：
- 列表 `get_gift_packs_for_user`
- 开屏提醒 `prompt_check_gift_packs`
- 领取 `claim_gift_pack`

判定分两步：先用 `_load_gift_pack_user_context` 每个用户读一次上下文，各礼包共用；再用 `_evaluate_gift_pack_eligibility` 返回 `(是否满足, [原因文字])`。

**提醒**：`prompt_check_gift_packs`（`db.py:12548`）遇到不满足资格的礼包直接跳过（`:12623`）；判定通过后在同一个事务里给 `prompt_count` 加一（「记账即计数」）。列表接口是 GET，没有副作用。

**领取**：在持有礼包行锁（`with_for_update`）的事务里完成全部校验与发放。计数查询必须复用这个事务的 session。已有的 `get_user_blackjack_stats` 会自己另开 `get_session()`，不能在这里调用。

**`gift_pack_user_state` 的用法**：已有 `claimed_at` 与提醒两组字段。统计与领取记录都按 `claimed_at IS NOT NULL` 过滤，所以新增只用于锁定或私信的行（`claimed_at` 为空）不会影响已领人数和领取记录。

**各表的时间字段与单位**（按时间范围计数时必须逐表换算）：

| 指标 | 表 | 时间字段 | 单位 |
|---|---|---|---|
| 大转盘 | `wheel_stats` | `timestamp` | 秒 |
| 21 点 | `blackjack_hand` | `created_at_ms` | 毫秒 |
| 夺宝 | `treasure_participation` | `created_at_ms` | 毫秒 |
| 大预言家 | `prediction_bet` | `created_at` | 带时区的 DateTime |
| 竞拍 | `auction_bids` | `bid_time` | 秒 |
| 锦标赛 | `blackjack_tournament_entry` | `registered_at_ms` | 毫秒 |
| 邀请 | `invitation` | 无 | — |
| 观看时长 | `plex_user.watched_time` / `emby_user.emby_watched_time` | 无（累计值，单位：小时） | — |

## Goals / Non-Goals

**Goals:**
- 列表、开屏提醒、领取三个入口共用同一套条件词汇、同一个求值器，口径不会各自漂移。
- 一次请求的求值成本只随「不同的计数键」增长，而不是随「礼包数 × 条件数」增长。
- 旧礼包不做数据迁移，行为与上线前一致。

**Non-Goals:**
- 任意嵌套的布尔表达式。
- 按天记录的观看时长（需要新建明细表，另立变更）。
- 用户「刚好达标」时的实时推送（没有达标时刻可以挂钩，见探索阶段的讨论）。
- 开始后放宽名单以外的受众条件（本版只允许停用后新建）。
- 任务提醒的深链：跳到具体游戏页。spec 只要求能进礼包中心，深链以后可以补，不影响 spec。

## Decisions

### D1 两个 JSON 列，同一套 schema

`gift_pack` 新增两个可空的 Text（JSON）列：`audience` 与 `requirements`，保留 `eligibility` 列只供读取时兼容。

**备选**：用一个条件列表，每项带 `visible_only` 标记。
**否决理由**：「谁能看见」和「要做到什么」在判定时机、锁定、提醒上的语义都不同，混在一个列表里，每个消费方都得先按标记拆开。两列的写法直接对应 spec 的两个概念。

### D2 条件 schema：判别联合，深度 2

```json
"requirements": [
  {"type": "bound", "service": "any"},
  {"type": "any_of", "items": [
    {"type": "wheel_spins", "min": 50, "window": {"kind": "pack"}, "paid_only": true},
    {"type": "blackjack_hands", "min": 100, "window": {"kind": "days", "days": 7},
     "min_bet": 10, "min_accuracy": 80}
  ]}
]
```

用 Pydantic 判别联合，判别字段是 `type`：
- 顶层项 = 叶子条件联合 | `AnyOf`；
- `AnyOf.items` 只接受叶子联合，由类型系统保证不会再嵌套，不需要额外校验。

`window` 用对象（`{"kind": "all" | "pack" | "days", "days": N}`），不用 `"days:7"` 这种字符串，这样 Pydantic 可以直接校验，不用再解析字符串。

**叶子类型**：

| type | 参数 | 可用的 window | 可用于受众 | 可用于领取条件 |
|---|---|---|---|---|
| `user_list` | `mode: include/exclude`, `tg_ids` (≤ 5000) | — | 仅顶层 | ✗ |
| `premium` | `state: active/none` | — | ✓ | ✓ |
| `bound` | `service: any/plex/emby` | — | ✓ | ✓ |
| `credits` | `min?`, `max?`（至少其一） | — | ✓ | ✓ |
| `badge` | `badge_id` | — | ✓ | ✓ |
| `claimed_pack` | `pack_id` | — | ✓ | ✓ |
| `wheel_spins` | `min`, `paid_only` (默认 true) | all/pack/days | ✓ | ✓ |
| `blackjack_hands` | `min`, `min_bet?`, `min_accuracy?` | all/pack/days | ✓ | ✓ |
| `treasure_issues` | `min` | all/pack/days | ✓ | ✓ |
| `prediction_bets` | `min` | all/pack/days | ✓ | ✓ |
| `auction_participations` | `min` | all/pack/days | ✓ | ✓ |
| `tournament_entries` | `min` | all/pack/days | ✓ | ✓ |
| `invitees` | `min` | 仅 all | ✓ | ✓ |
| `watched_hours` | `min` | 仅 all | ✓ | ✓ |

**跨字段校验**：
- 放在 schema 层：`days` 在 1–365；只支持 all 的类型拒绝其他 window；`credits` 至少有 min 或 max；`any_of` 至少 2 项；`user_list` 不在领取条件里、不在 `any_of` 组里。
- 需要查库的放在 db 层：`badge_id` 与 `pack_id` 必须存在，且 `pack_id` 不能是自身。

### D3 计数原语：`count(metric, tg_id, since, until, **qualifiers)`

三种时间范围只是 `since` 的取法不同，`until` 负责「截止后冻结」：

```
ref   = min(now, task_end_at or end_at)
since = 0                        (all)
      = start_at                 (pack)
      = ref - N * 86400          (days)
until = ref
```

- 领取时与展示时用同一个 `ref`，所以「截止后冻结」「领取时复核」不需要各自再写逻辑。
- 未开始的礼包（`ref < start_at`）碰到 `pack` 范围直接返回 0，不查库。
- 各计数器在函数内部按上面「时间字段与单位」表换算单位。

**各指标的口径**：

| 指标 | 口径 |
|---|---|
| `wheel_spins` | `paid_only` 时只计 `source='paid'`。十连抽是逐次调用单抽、每次写一行 `source='paid'`，自然计为 10 局 |
| `blackjack_hands` | 只计 `tournament_id IS NULL AND status IN TERMINAL_STATUSES`（与排行榜同口径）。`min_bet` 过滤 `bet_credits`。`min_accuracy` 在同一个过滤后的集合上算 `sum(decisions_correct) / sum(decisions_total)`，`decisions_total` 为 0 时准确率按 0 计。按 `created_at_ms` 落窗 |
| `treasure_issues` | `count(distinct issue_id)` |
| `auction_participations` | `count(distinct auction_id)` |
| `tournament_entries` | 排除已取消赛事的报名：取消后报名行仍保留、只做了退款，不排除会把「报了名但赛事被取消」也算作参赛 |
| `invitees` | `count(distinct used_by) where owner=tg_id and is_used=1` |
| `watched_hours` | Plex 与 Emby 两者的累计小时数相加 |

`invitees` 与 `watched_hours` 没有时间字段，所以不受 `until` 约束，仅可领取阶段内仍会增长。它们只支持历史累计，这一点与 spec 一致。

**不在热路径上另开连接**：所有计数器都接收 `session` 参数。21 点的准确率不复用 `get_user_blackjack_stats`：它自开连接，而且不支持按时间范围和注额过滤。

### D4 一次请求内的求值与缓存

扩展 `_load_gift_pack_user_context`：
- 状态型数据仍然每个用户读一次；新增持有的勋章 id 集合、已领取的礼包 id 集合。
- 计数结果按 `(metric, since, until, qualifiers)` 缓存在本次请求内。

这样 N 个礼包都用「礼包开始后转盘」时，只要它们的 `start_at` 相同就只查一次；`days` 范围的 `since` 按秒对齐到 `ref`，同一次请求内相同。

求值器 `_evaluate_conditions(items, ctx, pack, phase_ref) -> (ok, progress)`：一次遍历同时得到「是否满足」与「进度视图」，列表、开屏提醒、领取三处都调用它。

### D5 受众判定与锁定

```
audience_ok = all(user_list 项实时判定)
              and (state.audience_locked_at 已记录 or 非名单项实时全部满足)
```

**锁定只在开屏提醒（POST）里写入**：该请求本来就写库，而且每次打开应用都会调用，满足 spec 的「最迟一次打开应用时」。写入条件同时满足：
- 礼包处于进行中或仅可领取阶段，且已启用；
- 该用户未领取，也还没有锁定记录；
- 非名单项实时全部满足。

满足时 upsert 该行，写入 `audience_locked_at`。

**列表（GET）与领取只读锁定记录，不写入**：GET 保持没有副作用；从深链直接进入礼包中心、没经过开屏提醒的用户，按实时判定处理。

**名单项必须在顶层**（D2 已校验）：只有这样，「名单实时判定，其余项看锁定」才能按项拆开。名单若在 `any_of` 组里，组的结果无法拆成「名单部分」与「其他部分」。

### D6 用户视角的状态判定顺序

```
claimed      已领取（不看可见性，始终可见）
invisible    不在受众内（不返回给前端）
disabled     已停用（只有已领取的用户能看到已停用的礼包，前一条已覆盖）
upcoming     未开始
ended        已结束
sold_out     已领完
claimable    处于进行中或仅可领取阶段，领取条件满足
in_progress  处于进行中或仅可领取阶段，领取条件未满足；仅可领取阶段附带 task_closed=true
```

`in_progress` 对应 spec 里的「未达成」。沿用任务语境下的「进行中」这个词作为 API 值，前端显示为「未达成」或「任务进行中」。

未开始的礼包的可见性只做实时判定，不锁定。

### D7 提醒：两套计数、分别按天节流

`gift_pack_user_state` 新增 `task_prompt_count`（默认 0）与 `last_task_prompted_at`，与既有的 `prompt_count` / `last_prompted_at` 对称。

同一次请求里，一个礼包只可能落入一类提醒：领取条件满足与不满足互斥。所以两类提醒不会在一次请求里同时记账。

**响应**：保留原有的 `packs` 字段（可领取的礼包，形状不变），新增 `task_packs` 字段（带进度）。前端弹窗按这两个字段分块显示。

**短路**：没有进行中或仅可领取的已启用礼包时直接返回空，不加载用户上下文。现有实现已有这条优化，保留。

### D8 阶段计算

扩展 `_gift_pack_lifecycle`，新增 `claim_only` 阶段：只有当 `task_end_at` 存在且 `task_end_at < end_at`，并且 `task_end_at < now ≤ end_at` 时才进入。

边界沿用既有约定：`start_at ≤ now ≤ end_at` 算进行中。`now == task_end_at` 仍算进行中，这一刻的活动也计入。

### D9 名单型礼包的开始私信：周期扫描

新增 `scan_gift_pack_start_dms`，每 5 分钟运行一次。用周期扫描而不是在创建时安排定时任务，理由与 `scan_expired_gift_packs` 相同：开始时间和名单都可能被修改，扫描天然能处理改期、名单增补与服务重启。

**扫描哪些礼包**：已启用、`notify_audience_on_start=1`、处于进行中阶段、受众顶层有 include 模式的名单。

**私信发给谁**：include 名单里还没有 `start_dm_sent_at`、也没有 `claimed_at` 的用户，并且该用户实时满足全部受众条件（排除名单、积分区间等都要满足）。

**先记账再发送**：先在事务内写 `start_dm_sent_at`，提交后再发私信。与 21 点免费机会通知的「认领再发送」相同：宁可漏发一条，不重复发。发送失败只记日志，不重试。

**限速**：每条间隔 0.5s，与既有的批量私信相同；每轮最多发 200 条，剩下的留到下一轮，避免一轮扫描占用太久。5000 人的名单约 25 轮（约 2 小时）发完。

**私信内容**：标题、奖励、领取条件摘要、结束时间，并附一句「打开小程序的礼包中心领取」。私信由服务端渲染，无法按用户浏览器时区显示时间，所以按服务端配置的时区显示并注明时区。

### D10 开始后的编辑校验

`update_gift_pack` 在 `now ≥ start_at` 时调用 `_validate_post_start_edit(old, new)`，逐项检查：

| 字段 | 规则 |
|---|---|
| `start_at`、`rewards` | 必须与原值相同 |
| `requirements` | 把目标值字段（`min`、`credits.min`）抹掉后，与原值结构完全相同；目标值只能不变或降低 |
| `audience` | 把名单的 `tg_ids` 抹掉后与原值相同（名单的 mode 与位置也不能变） |
| `end_at` | 只能不变或推后 |
| `task_end_at` | 原来有值：只能推后或清空（清空等于放宽）。原来为空：不能新设（等于提前截止任务） |
| `total_quantity` | 原来不限量则保持不限量；原来限量则只能增加，或改为不限量 |

报错时指出是哪个字段违规，并附「可停用后新建礼包」。

`claimed_pack` 引用的完整性：
- 保存时校验被引用的礼包存在；
- 删除被其他礼包引用的礼包时拒绝，并列出引用方。

### D11 旧礼包：读取时转换，不做数据迁移

```
requirements 非空       --> 用 requirements
否则 eligibility 非空   --> 转换：
    min_credits      --> {type: credits, min}
    require_premium  --> {type: premium, state: active}
    require_binding  --> {type: bound, service}
audience 为空           --> 不限受众
```

- `max_task_prompt_count` 列的服务端默认值是 0，所以旧行的任务提醒上限自然是 0。新建礼包在 schema 层默认为 2。
- 编辑时总是写入 `requirements` 与 `audience`，并把 `eligibility` 置空。
- 空列表一律存为 NULL：「未配置条件」只有一种表示，回滚时也能用「非 NULL」找出受影响的礼包。
- **备选**：写 Alembic 数据迁移，一次性转换旧数据。
- **否决理由**：迁移脚本里要复刻 Pydantic 的校验，比读取时转换更容易出错；而旧礼包数量很少，读取时转换的成本可以忽略。

### D12 进度视图由服务端生成文案

```
RequirementProgress =
  Leaf  { type, label, met, current?, target?, window?, sub?: [{label, current, target, met}] }
| Group { type: "any_of", label: "任选其一", met, items: [Leaf] }
```

`label` 由服务端生成，例如：
- 「礼包开始后付费转盘」
- 「最近 7 天 21 点（每手 ≥ 10）」
- 「积分」

这些中文文案只有服务端一处来源。`min_accuracy` 作为 `sub` 展示，例如「准确率 76%，需 ≥ 80%」。

- 管理端列表也要展示条件摘要，同样用服务端生成的 `requirements_summary` / `audience_summary`，前端不再维护一套文案。
- 用户端的 `ineligible_reasons` 删除，唯一的消费方 `GiftPackDialog.vue:89-95` 同批改掉。

### D13 名单解析端点

`POST /api/gift-packs/admin/resolve-users {text}`，返回 `{resolved: [{token, tg_id, matched_by, display_name}], unresolved: [{token, reason}]}`。

**切分**：按空白、半角/全角逗号、换行切分，去空、去重。

**逐个匹配，按以下顺序**：
1. 纯数字，且在 `statistics` 中存在：按 tg_id 处理。
2. Plex 用户名或邮箱、Emby 用户名，不区分大小写。
3. `@` 开头：查 Telegram 用户缓存，结果仅供参考。

同一个标识匹配到多个 tg_id 时，列为无法解析并说明歧义。

保存时名单里只存 tg_id。

### D14 自动补绑定条件

奖励含「需要绑定」类型、而领取条件顶层没有 `bound` 叶子时，自动在领取条件里追加 `{type: bound, service: any}`。

「需要绑定」的判断：
- `expand-gift-pack-rewards` 已落地：读它的奖励类型登记表；
- 尚未落地：只看 `premium_days`。

## Risks / Trade-offs

- [回滚部署后，旧代码只认 `eligibility`，使用新条件的礼包会变成对所有人开放] → 空列表一律存为 NULL（见 D11），所以「非空」就等于「回滚后会变开放」。回滚前用一条 SQL 找出这些礼包并停用，写进 Migration Plan。
- [开屏提醒的耗时随进行中礼包数 × 不同计数键增长] → 靠 D4 的缓存与各表已有的 `tg_id` 索引。同时进行中的礼包通常是个位数。上线后如果观测到慢查询，再加 `(tg_id, 时间字段)` 复合索引（见 Open Questions）。
- [`gift_pack_user_state` 的行数增长：锁定会给每个受众用户写一行] → 上限是「活跃用户 × 进行中礼包」，每行很小，而且礼包删除时级联删除。
- [「最近 N 天」的进度会倒退，用户会觉得不公平] → 界面明确标注「最近 N 天」；领取时复核失败会返回当前进度。在管理端的时间范围选项旁提示「任务类礼包推荐用『礼包开始后』」。
- [受众锁定后，用户可能在已不属于受众时领取（如锁定后开通了 Premium，照样领到非 Premium 体验礼包）] → 这是有意的取舍（spec「受众锁定」），每人最多一份。
- [名单私信受 Telegram 频率限制] → 0.5s 间隔、每轮 200 条上限，并且只对 include 名单开放。
- [按 `@username` 解析依赖本地缓存，可能过期] → 解析结果注明匹配来源，tg_id 与 Plex/Emby 用户名才是可靠来源。
- [开始后的编辑限制可能让管理员觉得不便] → 开始前可以随意改；报错时明确指出违规字段并给出「停用后新建」的替代做法。
- [邀请人数与观看时长在仅可领取阶段仍会增长] → 它们只支持历史累计，本来就不是「活动期间的任务」。在 spec 里已写明只有带时间字段的计数会冻结。

## Migration Plan

1. 一个 Alembic 迁移，只加列，不改数据：
   - `gift_pack`：`audience` Text NULL、`requirements` Text NULL、`task_end_at` BIGINT NULL、`max_task_prompt_count` INT NOT NULL server_default 0、`notify_audience_on_start` SMALLINT NOT NULL server_default 0。
   - `gift_pack_user_state`：`audience_locked_at` BIGINT NULL、`task_prompt_count` INT NOT NULL server_default 0、`last_task_prompted_at` BIGINT NULL、`start_dm_sent_at` BIGINT NULL。
   - CheckConstraint：`task_end_at IS NULL OR (task_end_at > start_at AND task_end_at <= end_at)`、`max_task_prompt_count >= 0`、`notify_audience_on_start IN (0, 1)`。
2. 后端与前端同批发布：列表项的状态、进度字段和开屏提醒的响应形状都有变化。
3. 回滚：先查出并停用所有使用新条件的礼包，再回退代码，最后执行 `alembic downgrade` 删除新列。回退前在生产数据库执行：

   ```sql
   SELECT id, title, is_enabled
   FROM gift_pack
   WHERE audience IS NOT NULL OR requirements IS NOT NULL;
   ```

   这些行在旧版只读取 `eligibility`（新建/编辑时已置空）的代码下可能变成对所有人开放。确认并停用查询结果中的礼包后，才允许回退；不得把 `is_enabled = 0` 加到查询条件上，以免漏掉需审阅的行。

## Open Questions

- 名单私信的每轮上限（200）与扫描间隔（5 分钟）：可以按线上 Telegram 的限流反馈调整，只是常量。
- `(tg_id, 时间字段)` 复合索引：先不加，上线后看开屏提醒接口的 P95 再决定，需要时另写一个只加索引的迁移。
