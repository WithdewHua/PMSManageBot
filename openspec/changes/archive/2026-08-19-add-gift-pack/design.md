## Context

代码库已有三块可直接对照的现成范式，本设计尽量沿用而非发明：

- `Badge` / `UserBadge`（`src/app/models/models.py:698`）——「定义表 + 用户记录表 + `UniqueConstraint(tg_id, x_id)`」的结构，与礼包同构。
- `db.join_treasure_issue()`（`src/app/databases/db.py:1189`）——`with_for_update()` 行锁保护份额扣减的并发范式。
- `WheelAdminPanel.vue:958-1083`——动态奖品列表（增删项、上限、逐项配置）的管理端 UI 范式。

三个必须绕开的既有约束：

1. **Premium 是按服务存的，不是按用户**。`is_premium` / `premium_expiry_time` 在 `PlexUser` 与 `EmbyUser` 各存一份。`update_premium_status(db, tg_id, service, days)`（`src/app/premium.py:131`）的 `service` 是必填参数，用户未绑定该服务会抛 `NameError`，用户为永久会员会静默 `return None`。
2. **不存在积分流水表**。积分只是 `Statistics.credits` 上的一个 `Float`，`db.update_user_credits()` 是覆盖写。任何发放的审计痕迹必须由本次改动自己落地。
3. **`notify_admins_by_url()` 是逐管理员逐条发 TG 消息**。任何按笔通知在礼包这种量级下会刷屏并触发 Telegram 限流。

动机见 proposal.md — Why；行为契约见 specs/gift-pack/spec.md。

## Goals / Non-Goals

**Goals:**

- 礼包的定义、领取、提醒三件事共用尽量少的表，避免状态散落。
- 奖励类型可扩展：新增一种奖励只改发放分发器，不改表结构。
- 领取路径在并发与重复提交下严格幂等，且发放结果可审计。
- 提醒克制：一个汇总弹窗、每包每天至多一次、有次数上限。
- 管理端复杂度隔离在独立组件里，不继续膨胀已有 5073 行的 `Management.vue`。

**Non-Goals:**

- 不做过期礼包与领取记录的归档／清理（数据量增长在当前规模下可接受，留待后续）。
- 不做礼包的定向发放（指定用户名单）——本期资格只支持属性条件。
- 不做兑换码形式的礼包（已有邀请码体系覆盖该场景）。
- 不做礼包的部分领取（用户不能只领其中某几项奖励）。
- 不引入积分流水表；审计仅覆盖礼包自身的发放。

## Decisions

### D1: 两张表，用户状态表合并「领取」与「提醒」

```
  gift_pack                                gift_pack_user_state
  ═══════════════════════════              ══════════════════════════════
  id               BIGINT PK               id               BIGINT PK
  title            Text              ┌────▶ pack_id          BIGINT FK
  description      Text?             │      tg_id            BIGINT FK
  rewards          Text(JSON)        │
  eligibility      Text(JSON)?       │      claimed_at       BIGINT?   NULL=未领
  total_quantity   Integer?  NULL=不限量    reward_snapshot  Text(JSON)?
  claimed_count    Integer                 last_prompted_at BIGINT?
  start_at         BIGINT  epoch 秒        prompt_count     Integer   default 0
  end_at           BIGINT  epoch 秒
  max_prompt_count Integer  default 3      UNIQUE(pack_id, tg_id)
  is_enabled       SMALLINT default 1      INDEX(tg_id, claimed_at)
  expiry_notified  SMALLINT default 0
  created_by / created_at / updated_at
```

**为什么合并**：拆成 `gift_pack_claim` + `gift_pack_prompt_log` 两张表后，判定"要不要提醒"需要同时 join 两张表，而两张表的行都以 `(pack_id, tg_id)` 为唯一键——本质是同一实体的两个字段。合并后单表单次查询即可完成判定。

**代价**：只被提醒过、从未领取的用户也会建行，行数上界是「曝光用户数 × 礼包数」。当前用户规模与运营活动频次下这个量级无关紧要；`claimed_at IS NULL` 的行也正是"提醒了没领"的转化率数据来源。

**行按需创建**：仅在首次提醒或首次领取时插入，不预生成。系统中无进行中礼包时不写任何行。

### D2: 奖励与资格用 JSON 列，不用固定列

```json
rewards:     [{"type": "credits", "amount": 100},
              {"type": "premium_days", "days": 7}]

eligibility: {"min_credits": 50,
              "require_premium": false,
              "require_binding": "any" | "plex" | "emby" | null}
```

**替代方案**：`credits_reward Float` + `premium_days Integer` 两个固定列。被否，因为多奖励项是明确需求，且第三种奖励类型（邀请码、勋章）是可预见的演进方向——固定列方案每加一种就要一次 migration + 全链路改动。

**代价**：数据库无法用 CHECK 约束校验内容，校验全部落在 Pydantic 层与管理端 UI。同类型不得重复这条约束由 Pydantic validator 保证，管理端 UI 额外从下拉中剔除已选类型作为第一道防线。

### D3: Premium 发给所有已绑定服务

`update_premium_status()` 对每个服务独立调用。发放前先解析用户绑定情况：

```
  解析绑定 → services = [s for s in (plex, emby) if 用户已绑定 s]
    │
    ├─ services 为空 → 不进入发放（已被 D4 的资格拦在更早处）
    │
    └─ 逐个调用 update_premium_status(db, tg_id, s, days)
         ├─ 返回 datetime → 记入 snapshot: {"service": s, "new_expiry": ...}
         └─ 返回 None（永久会员）→ 记入 snapshot: {"service": s, "skipped": "lifetime"}
```

**替代方案**：
- (A) 礼包配置里写死服务——被否：会与「要求绑定 Emby」这类资格产生必然失败的矛盾组合，管理员很容易配错。
- (C) 领取时由用户选服务——被否：把一键领取变成两步交互，为一个边缘情况牺牲主路径体验。

**已知代价**：双绑用户获得的价值是单绑用户的两倍。这是有意接受的——双绑用户本就在两套体系里各自消耗资源，双份延长与既有的 Premium 解锁逻辑（也是按服务单独购买）口径一致。

**永久会员**：不阻断领取，跳过该服务并在 `reward_snapshot` 与返回结果中明确标注。所有服务均为永久会员时仍允许领取（用户还能拿到积分项），但必须在领取结果里说清 Premium 部分未生效，避免静默失败。

### D4: 「至少绑定一个媒体账号」上移为显式资格，而非发放时的隐式校验

含 `premium_days` 奖励的礼包，在创建时由后端自动补上 `require_binding: "any"`（若管理员未配置更严格的绑定要求）。

**为什么**：若留作发放时才发现的隐式校验，未绑定用户会在点击领取后才收到错误；而资格系统本就要在列表与提醒判定里跑一遍，把它归入资格意味着**只有一套校验逻辑**，用户在列表里就能看到"需先绑定媒体账号"这个可行动的提示，且天然不会进入提醒候选。

副作用：未绑定账号的用户领不到含 Premium 的礼包，即使该礼包同时含积分。这是有意的——礼包是一个整体，不支持部分领取（见 Non-Goals）。管理员若想覆盖未绑定用户，应单独发一个纯积分礼包。

### D5: 单层节流 + 汇总弹窗

提醒判定只有一层计数，挂在 `(pack_id, tg_id)` 上；"一天只弹一次"由**汇总弹窗**这一形式天然保证，不需要额外的 per-user 全局计数。

```
   候选集 = 进行中 ∧ 已启用 ∧ 未领取 ∧ 满足资格 ∧ 有余量
            ∧ prompt_count < max_prompt_count
            ∧ (last_prompted_at 为空 或 不在今天)
        │
        └─ 非空 → 弹一个弹窗列出全部候选，逐个 prompt_count += 1
```

**替代方案**：双层节流（per-user 的"今天弹过没" + per-pack 的次数上限）配单包弹窗。被否：多一张表或多一组列，多一个分支，且三个礼包同时上线时用户会被连弹三次。

**"今天"的判定基准**：用 `settings.TZ`，与运营口径和管理端时间录入保持一致，不用用户浏览器时区——否则跨时区用户的提醒节奏会与运营预期错位。

**默认 `max_prompt_count = 3`**，每个礼包可单独配置。

### D6: 提醒查询用 POST 并在返回时记账

接口为 `POST /api/gift-packs/prompt-check`，语义是"检查是否该提醒，并记录本次提醒"。返回候选列表的同时对每个候选 `prompt_count += 1`、`last_prompted_at = now`。

**替代方案**：`GET /pending` 查询 + 前端弹窗后再 `POST /prompted` 回报。被否：两个请求且第二个可能丢失，失败模式是"没记账 → 用户被反复提醒"，正是本设计要避免的骚扰。而 POST 在返回时记账的失败模式是"多记一次 → 用户少被提醒一次"，明显更可接受。

用 POST 而非 GET，是因为它确实有副作用，GET 应保持只读。

**空态短路**：先查是否存在进行中且启用的礼包，为空则立即返回空列表，不做任何用户维度查询、不写任何行。运营活动的常态就是"当前没有活动"，这条短路让绝大多数冷启动请求的成本接近于零。

该请求独立发出，不与 `getUserInfo` / `systemStatus` 合并（proposal 已定）。

### D7: 领取的并发与原子性

照搬 `join_treasure_issue` 的形状，全部动作在单个 `get_session()` 事务内：

```python
with get_session() as session:
    pack = session.execute(
        select(GiftPack).where(GiftPack.id == pack_id).with_for_update()
    ).scalar_one_or_none()
    # 1. 校验：存在 / 已启用 / 在窗口内
    # 2. 校验：claimed_count < total_quantity（不限量则跳过）
    # 3. 校验：资格（实时算，锁内算，避免锁外算完锁内失效）
    # 4. 校验：该用户 user_state.claimed_at 为空
    # 5. 发放全部奖励项，收集 reward_snapshot
    # 6. claimed_count += 1
    # 7. upsert user_state: claimed_at = now, reward_snapshot = ...
```

任一步失败 → 整个事务回滚 → 不扣余量、不记领取、不发奖励。`UniqueConstraint(pack_id, tg_id)` 作为并发重复提交的最后一道防线。

**Premium 发放如何进入这个事务**：`update_premium_status()` 原本自开 `get_session()` 并立即提交，且内部还会调用媒体服务器 API 授予下载权限——两者都会破坏上面的原子性。实现时对 `src/app/premium.py` 做了一次向后兼容的重构：

- 新增可选参数 `session`。传入时复用调用方事务（`session.execute(stmt)`），不自开事务；不传时行为与改造前完全一致，三处既有调用方（`routers/premium.py`、`routers/activities/luckywheel.py` ×2）无需改动。
- 把媒体服务器权限同步抽成独立的 `sync_media_permission(db, tg_id, service)`。它本就是 best-effort（原实现即 `except` 后只记 warning），现在由调用方在**事务提交之后**执行，既不污染事务，也避免把 HTTP 往返关在 `with_for_update()` 行锁里拖垮并发领取的吞吐。

这样积分与 Premium 到期时间的写入同在一个事务内，严格满足 spec 的原子性要求。

### D8: 通知走里程碑 + 异常，过期汇总用周期扫描

| 节点 | 触发方式 |
|---|---|
| 礼包创建上线 | 创建接口内 `BackgroundTasks` 直接发 |
| 限量领完 | 领取事务提交后，若 `claimed_count == total_quantity` 则发（并发下只有一个事务能把计数加到满，天然只触发一次） |
| 窗口过期汇总 | APScheduler 周期任务扫描 `end_at < now ∧ expiry_notified = 0`，发送后置 `expiry_notified = 1` |
| 发放失败 | 领取路径的异常分支立即发 |

**过期汇总为什么用周期扫描而非 date job**：treasure 用的是创建时安排 `date` job（`jobstore="sqlalchemy"` 持久化）。礼包的 `end_at` 是管理员可编辑的，date job 方案需要在每次编辑时重排 job，且漏排就永久丢失。周期扫描配一个 `expiry_notified` 标记列对重启、改期、漏发都免疫，代价只是通知延迟到下一个扫描周期（建议 10 分钟）。

**日常逐笔领取不通知**——管理员想看热度就去管理面板看统计，`gift_pack_user_state` 本身就是完整审计记录。

### D9: 入口放操作菜单，管理面板独立组件

用户入口挂在 `BottomMenu.vue` 中间 "+" 的操作菜单里（该菜单已承载"兑换邀请码"这类领取型操作，语义一致），不新增路由、不占用底部四个主标签位。

礼包中心做成 `GiftPackDialog.vue`，形状对齐 `TreasureDialog.vue`。

管理面板做成独立的 `GiftPackAdminPanel.vue`，避免继续膨胀已有 5073 行的 `Management.vue`。接入方式与转盘/竞拍/夺宝/大预言家完全同构：在「活动管理」tab 的 `activities-grid` 里放一张 `activity-card-enhanced` 入口卡（带实时统计），点击进入全屏 dialog 承载面板。

**为什么不是独立 tab**：礼包本身就是运营活动，和已有四个活动同层级；独立 tab 会让主 tab 栏从 3 个涨到 4 个，在手机上挤成一团，且与「活动都在活动管理里」的心智模型冲突。面板内部同样沿用 `WheelAdminPanel.vue` 的视觉 token（`.admin-panel` 渐变底、`.admin-card` + 渐变卡头、`rounded="xl"`、hover 上浮），保证跨面板观感一致。

### D10: 时间的存储与两端时区口径

存储统一为 epoch 秒（`BIGINT`），本身时区无关。两端口径有意不一致：

- **用户端**按浏览器时区展示——用户看到的是自己的当地时间，这是对的。
- **管理端**按 `settings.TZ` 录入与展示，并在输入框旁标注时区名——保证后台配置与 TG 群公告口径一致。若管理端也跟浏览器时区，身处不同时区的管理员配置的时间会与公告口径错位。

## Risks / Trade-offs

- ~~**`update_premium_status()` 自开 session，可能不在领取事务内**~~ → **已在实现中确认并解决**。确认结论：`get_session()` 每次 `SessionLocal()` 新建独立 session（非 scoped_session），内层 `with` 块结束即独立提交；且该函数还会调用媒体服务器 API，属不可回滚副作用。解决方式见 D7——给 `update_premium_status()` 加可选 `session` 参数复用外层事务，并把权限同步抽成 `sync_media_permission()` 挪到事务提交后。代价是 `premium.py` 需要一次向后兼容的重构（proposal.md 原写「不修改」），换来 spec 要求的严格原子性得以完整满足。

- **`gift_pack_user_state` 只增不减** → 本期明确不做清理（Non-Goals）。行数上界是曝光用户数 × 礼包数，按每年十余个运营活动估算，量级完全可控。真正增长到需要处理时再补归档任务。

- **双绑用户 Premium 价值翻倍** → 有意接受（D3）。若某个礼包不希望如此，管理员可改用「要求绑定 Plex」这类资格把受众收窄。

- **永久会员领取后 Premium 部分永久失去** → 通过领取结果的明确说明缓解，用户在看到结果时就知道发生了什么。不做"允许稍后再领"的补偿机制，那会破坏一人一次的模型。

- **`POST /prompt-check` 在弹窗渲染失败时会多记一次** → 有意接受（D6），最坏后果是用户少被提醒一次。

- **冷启动多一个请求** → 由 D6 的空态短路缓解；无活动时该请求只查一张小表且不写库。

- **管理端与用户端时区口径不同可能让人困惑** → 通过管理端界面上的显式时区标注缓解；这是有意设计而非缺陷。

## Migration Plan

1. 新增 Alembic 迁移创建 `gift_pack` 与 `gift_pack_user_state` 两张表，无数据迁移。
2. 后端路由与前端组件均为纯新增，不改动既有接口契约，可与旧前端共存。
3. 上线后不立即创建礼包，两张表为空时用户侧行为与上线前完全一致（`prompt-check` 走空态短路）。
4. **回滚**：两张表为空时直接 `alembic downgrade` 即可。若已有礼包与领取记录，回滚会丢失审计数据——回滚前应先停用所有礼包（`is_enabled = 0`）观察，确认无误再决定是否降级。

## Open Questions

- 过期汇总扫描任务的周期取 10 分钟是拍的数，上线后按管理员对通知及时性的实际感受调整即可。该参数不影响 specs、数据模型或任务拆分。
