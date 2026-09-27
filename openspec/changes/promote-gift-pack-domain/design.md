# Design

## Context

动机见 proposal.md 的 Why。本设计假定 `make-credit-changes-atomic` 与 `promote-blackjack-domain` 的全部任务已经完成：

- credits 已有模块级的 `add_tx` / `deduct_tx` / `move_tx`，以及值对象 `CreditAccount`。
- 21 点已经是目标形态：模块级 repository，另有 service、rules 和 `BlackjackError(DomainError, ValueError)`。
- luckywheel 已有 `grant_free_spins_tx`。
- 门面 `app.databases.db` 仍组合着其余领域的 mixin。

以下事实以调研时的 HEAD（`67ccd29`）为准。

**规模与结构**

- 礼包共约 3,500 行。其中 repository 2,164 行：`__init__` 280、`part_1` 756、`part_2` 648、`part_3` 480。其余为 router 397、schemas 565、models 157、notifications 122、jobs 95。
- `GiftPackRepository` 有 53 个方法、2 个类属性，其中公开方法 15 个。
  - 每个公开方法各开一个 session。
  - 有 9 个方法吞掉异常并返回默认值：`False`、`None`、`[]` 或 `([], 0)`。这种返回对接口可见。
- 门面上的礼包方法只有礼包自己调用：router 14 次、jobs 4 次、notifications 3 次。测试直接调用约 110 次，其中 33 处调的是私有方法。

**领取事务**

领取事务是 `claim_gift_pack`（`part_2.py:504-648`），全程在一个 session 里：

1. 锁礼包行。
2. 锁用户领取状态行。
3. 读取用户上下文（不加锁）。
4. 依次校验：受众 → 启用 → 时间窗 → 余量 → 是否已领 → 统计行 → 领取条件。
5. 按礼包 JSON 里的顺序发放奖励。
6. 已领份数加一，写入领取状态。
7. 有特权码时，先 flush 再写 `.env`。
8. 提交。
9. 在 repository 里、提交之后同步媒体服务器权限。

锁的顺序取决于奖励的配置顺序。lines 的 `unlock_line_schedule_with_credit` 是先锁 `statistics` 再锁 `plex_user`；如果礼包配置成"线路解锁在前、积分在后"，两边加锁顺序正好相反。

**各类奖励的现状**

| 奖励 | 现状 | 问题 |
|---|---|---|
| 积分 | `credits.repository.add_tx` 加 `credits.service.register_cache_invalidation` | repository 导入了 credits 的 service 和 `types`，计入基线 |
| 转盘免费次数 | `luckywheel.repository.grant_free_spins_tx` | 无 |
| 会员天数 | `premium.service.update_premium_status(self, …, session=)`，要传门面实例；读到期时间用独立 session，不加锁 | 可能丢失更新；门面实例 |
| 争霸赛余额 | 直接改 `Statistics.tournament_wallet_credits`（该列归 blackjack） | 直接写外域列 |
| 邀请码 / 特权码 | `session.add(Invitation)`；特权码在持有 `threading.Lock` 时写 `settings.PRIVILEGED_CODES` 和 `.env` | 直接写外域表；提交前写文件 |
| 线路调度解锁 / 下载解锁 | 先 FOR UPDATE，再对媒体账号行 `setattr`；已解锁的记为跳过 | 直接写 lines、media_access 的列 |

**条件与受众**

条件共有 12 种。
- 数据来自 identity 宽表、badges、luckywheel、blackjack（现金局和锦标赛）、treasure、prediction、auction、invitation，以及本领域的领取状态。
- 外域模型在模块顶层直接导入（`part_1.py:9-25`、`part_2.py:9`）。
- 计数按需懒加载，并在一次请求内缓存。`tests/test_gift_pack_conditions.py:709-757` 断言了查询次数。
- 只有领取和开始私信两条路径在行锁之后取数；列表和提醒路径不加锁。

**错误处理**

- repository 里有 38 处 `raise ValueError`。
- 路由在 `router.py:120-146` 从 `"不满足领取条件；当前进度："` 后面解析 JSON。
- 删除接口在 `router.py:342` 按错误文案里是否含"不存在"来区分 404 和 400。
- 发放阶段抛出的 `ValueError` 返回 400，不通知管理员；包括外域的英文文案，例如 `credit account not found`。其他异常返回 500 并通知管理员。

**提交后的副作用**

- 积分缓存失效走 post-commit 回调。
- 下载权限同步和会员媒体权限同步，在 repository 里、提交之后执行。
- 售罄通知和创建通知用 `BackgroundTasks`；同步失败和发放失败的通知用 detached task，因为抛出 `HTTPException` 时 `BackgroundTasks` 不会执行。

**基线与合约**

- `owner=promote-gift-pack-domain` 的条目共 21 条，全部在 repository。
- `ignore_imports` 中标给礼包的有 5 条。另外，门面组合边 `app.databases.db -> app.domains.gift_pack.repository` 在 Six-tier 和 Acyclic 两个合约里各有一条忽略项；摘掉 mixin 后这两条会变成未匹配项，而合约设了 `unmatched_ignore_imports_alerting = "error"`。
- 门面冻结合约的 `allowed_importers` 里有礼包的 router、jobs 和 notifications。
- 基线的键包含 `path|line`，任何让行号移动的提交都要重写键。

**测试**

共 64 个测试，跑在内存 SQLite 上，FOR UPDATE 不起作用。
- 未覆盖：管理端 list 和 records、各 500 分支、三种通知、会员续期计算、过期扫描任务、除邀请码外其他奖励的回滚、并发领取。

## Goals / Non-Goals

**Goals：**

- 礼包 repository 改为模块级函数，从门面摘除。入口只调用 `gift_pack.service`。
- 领取事务对其他领域的每一处读写，都通过该领域的 `*_tx` 完成，并复用领取事务的 session。礼包不再导入任何外域模型。
- 领取时按固定顺序加锁，与奖励的配置顺序无关。会员到期时间在同一 session 内加锁读写。
- 条件求值拆成三步：规划要取哪些数、取数、纯计算。保持现有的按需取数和查询次数。
- 用类型化异常表达全部业务拒绝，保持现有的状态码、detail 文案，以及"发放阶段拒绝返回 400、不通知管理员"这条边界。
- 礼包和 21 点的 repository 包按子主题重组；新增禁止序号模块的架构检查。
- 清空礼包名下的 21 条基线条目、5 条忽略项、2 条门面组合边，以及门面冻结合约里礼包的放行项。

**Non-Goals：**

- 不改变领取规则、条件语义、奖励数额、提醒节流、接口路径和请求/响应结构。
- 不移除特权码"提交前写 `.env`"的例外。本变更只把它挪到 invitation，由 `move-privileged-codes-to-database` 移除。
- 不提升 premium、lines、media_access、invitation、treasure、prediction、auction、badges 这些领域本身。只在它们的 repository 里新增礼包需要的模块级 `*_tx`；其余代码仍按原样组合进门面，由各自的 promote 变更处理。
- 不把同步的数据库和媒体服务器调用改成异步。
- 不修复 `.env` 写入成功、随后提交失败时留下的特权码残留（见 Risks）。

## Decisions

### D1 先搬移、再改造，按子主题重组 repository 包

分两个阶段，分别提交：

1. **只搬移**：函数体逐字不变，只调整函数所在的文件和导入，用 `scripts/refactor/inventory.py` 和 `verify.py` 做逐项 AST 比对。这样 `git blame -C` 能追到每个函数的来历，重组本身也可以机械证明。
2. **语义改造**：D2–D8。

**礼包**在改造前还是 mixin，搬移后按子主题拆成几个 mixin，由 `repository/__init__.py` 组合，门面看到的类不变：

- `conditions.py`：用户上下文，条件和受众的取数与求值。
- `rewards.py`：奖励发放。
- `packs.py`：定义的增删改、引用校验、管理端列表、统计、领取记录、名单解析。
- `claims.py`：用户列表、开屏提醒、领取。
- `notices.py`：开始私信的认领、过期扫描与标记。

改造完成后，纯计算移入 `rules.py`。它若超过 1,000 行，就改成 `rules/` 包，按 conditions、rewards、lifecycle 拆分。

**21 点**在试点完成后，`part_1`–`part_7` 已经是模块级函数，按子主题重组为以下几类：

| 目标模块 | 内容 |
|---|---|
| `hands.py` | 现金局手牌的生命周期与动作 |
| `settlement.py` | 结算 |
| `jackpot.py` | 奖池 |
| `retention.py` | 救济、返水、游标 |
| `wallet.py` | 争霸赛余额 |
| `stats.py` | 统计 |
| `tournaments.py` | 赛事的管理、报名、状态流转和查询 |
| `tournament_entries.py` | 参赛记录、排名与一致性查询（`tournaments.py` 超过 1,000 行预算后拆出的第二层子主题）|
| `tournament_play.py` | 锦标赛手牌与结算 |
| `config_store.py` | 配置行的读写，避免与领域角色文件 `config.py` 重名 |

最终文件名以试点完成后的函数清单为准，在映射表中审阅确定。`repository/__init__.py` 的导出和各函数的行为都不变。

**配套工作**：

- **基线键**：搬移会移动基线键，由脚本按搬移映射把旧的 `path|line` 改写为新位置。脚本还要校验两点：条目总数不变；按 `(owner, kind, source_domain, target_domain, target/symbol)` 统计的多重集合不变。
  - 搬移映射是 `scripts/refactor/baseline_moves.toml`：每个源文件逐符号登记新模块（模块级条目用 `package_level` 声明所属包，因为同一份导入会按使用位置散到多个模块），目标反过来与 `mapping.toml` 的 `planned_target` 逐条对比。
  - **例外（一个子主题共用同一个模型的导入）**：拆成两个 mixin 后，两个子主题各自要用同一个外域模型时，一次导入必然变成两条边。这种增加只能在搬移映射里用 `[[addition]]` 显式声明，并且必须点名它重复的那条原条目；脚本校验两者身份相同、原条目确实在旧基线里，新条目继承原条目的 `owner`。除声明之外任何条目增减都被拒绝。
  - **组合类声明**：`mapping.toml` 新增 `[repository_mixins]`，按包登记组合的 mixin 类名。`verify.py` 用它把搬移后的类成员按“定义类”归位（不再依赖 `part_<n>` 命名），并校验声明的 mixin 真实存在；成员具体落在哪个子主题模块，由 `tests/refactor/test_gift_pack_split.py` 按 `planned_target` 固定。
- **21 点冻结夹具**：`tests/refactor/fixtures/blackjack_surface.json` 和 `scripts/refactor/blackjack_inventory.json` 如果届时仍在，就在同一个提交里按映射更新，diff 只允许路径变化。
- **序号模块检查**：在 `tests/architecture` 新增一项，`src/app/domains/**/part_<数字>.py` 出现即失败。在 `baseline.json` 新增 `numbered_modules` 类别，登记 `prediction/repository/part_1.py`、`part_2.py`，负责变更为 `promote-activity-domains`。只减不增的规则与其他类别相同。
- **文档**：更新 `docs/architecture.md` 的提升模板，写明三条：角色文件改成包时按子主题拆分；搬移和语义改造分开提交；禁止序号模块。

备选方案：先改造、最后再重命名。改造会重写每个函数的签名；如果最后才搬移，git 就无法区分"位置变了"和"内容变了"。搬移之前先改造，也会让基线在两次提交里各改一遍键。所以不采用。

### D2 奖励与条件取数全部走所属领域的 `*_tx`

礼包 repository 只读写本领域的表和 identity 宽表的只读列，其余一律调用所属领域 repository 的 `*_tx`，并传入领取事务的 session。还没有提升的领域，就在它的 repository 模块里新增模块级函数，与现有 mixin 并存；这些领域提升时，这些函数原样保留。

**写入**

| 奖励 | 提供方与函数 | 语义 |
|---|---|---|
| 积分 | `credits.repository.add_tx`（已有） | 见 D3 |
| 转盘免费次数 | `luckywheel.repository.grant_free_spins_tx`（已有） | 不变 |
| 会员天数 | `premium.repository.grant_premium_days_tx(session, tg_id, days)`（新增） | 见 D5 |
| 争霸赛余额 | `blackjack.repository.credit_tournament_wallet_tx(session, tg_id, amount)`（新增） | 锁 `statistics` 行，用 SQL 增量更新，舍入与现在的 `_grant_tournament_wallet_tx` 一致 |
| 邀请码 | `invitation.repository.issue_codes_tx(session, owner_tg_id, count, *, privileged=False)`（新增） | 生码规则和写入的行与现在逐字一致；特权码见 D6 |
| 线路调度解锁 | `lines.repository.unlock_line_schedule_tx(session, tg_id, *, now)`（新增） | 返回"已解锁"或"已跳过"；已解锁则跳过，与现有行为一致 |
| 下载解锁 | `media_access.repository.unlock_download_tx(session, tg_id, *, now)`（新增） | 同上 |

**条件取数**

全部只读，不对活动表加锁，这与现状相同。

| 条件 | 提供方与函数 |
|---|---|
| wheel_spins | `luckywheel.repository.count_paid_spins_tx` |
| blackjack_hands | `blackjack.repository.cash_hand_metrics_tx`：终态、非锦标赛手牌的数量与准确率 |
| tournament_entries | `blackjack.repository.count_tournament_entries_tx`：用 blackjack 常量排除已取消的赛事，替换魔数 `4` |
| treasure_issues | `treasure.repository.count_participated_issues_tx` |
| prediction_bets | `prediction.repository.count_bets_tx` |
| auction_participations | `auction.repository.count_participated_auctions_tx` |
| invitees | `invitation.repository.count_invitees_tx` |
| badge | `badges.repository.active_badge_ids_tx`；引用校验用 `badges.repository.badges_exist_tx` |

- **时间窗**：各条件现在用不同的时间单位（秒、毫秒、UTC datetime）和边界开闭。时间窗的语义沿用现有计数器，由提供方按本表的单位换算。每个 `*_tx` 都有测试，逐条对照原计数器的边界用例。
- **宽表的只读列**：积分、会员、绑定状态、观看时长仍由礼包 repository 通过 `identity.models` 读取，这是架构允许的。

备选方案：由各领域的 service 提供计数。service 会自己开 session，锁内取数就会跨事务，领取路径也会多出几次连接获取。所以不采用。

### D3 跨域值对象与积分缓存失效

礼包 repository 要构造 `CreditAccount`，还要在提交后让积分缓存失效。现有检查把这两件事都算作违规：`types` 不是可跨域导入的角色，repository 也不能调用其他领域的 service。

- **`types` 成为可跨域导入的无 I/O 角色**，与 `exceptions`、`constants` 并列。
  - `types` 只放不可变值对象和结果类型，例如 dataclass、Enum。它不得导入 SQLAlchemy、session、网络、调度器或其他角色的模块。
  - 更新 `tests/architecture/checks.py` 的角色识别和 import / call 放行规则：service 和 repository 可以导入其他领域的 `types`，并调用其构造器和类方法（如 `CreditAccount.tg`）。
  - 在 import-linter 中新增 `types` 纯度合约，并同步 D10 规则在 `docs/architecture.md` 和 AGENTS.md 中的表述。
- **credits 的写入 `*_tx` 自行登记提交后的缓存失效**：`add_tx`、`deduct_tx`、`move_tx` 在调用方 session 的 `post_commit_callbacks` 上登记失效，按 key 去重；回滚时丢弃，这由 `core.db.get_session` 保证。`credits.service.register_cache_invalidation` 只保留给 service 层使用。

如果 21 点试点在它的任务 4.4 和 4.6 中已经用等价方式解决了这两个问题，本变更就沿用试点的实现，只迁移礼包的调用，不重复实现。实施的第一步就是核对这一点（见 tasks 1.1）。

**1.1 核对结论（2026-09-27，`promote-blackjack-domain` 34/34 全部勾选）**：试点**没有**解决这两件事，所以本变更必须实现 D3 的两项，并用它作为 D2 的前提。

- `types` 跨域导入：`tests/architecture/checks.py:_role_for_module` 的合法角色集合不含 `types`，而 `_import_allowed` 只对 `repository`\/`models` 等已知角色放行，所以 `app.domains.credits.types` 的导入恒判为违规。试点在 4.4 只把跨域调用改成 service\/`*_tx`，没有新增 `types` 角色，因此这些边全部以既有债务形式封存在 `tests/architecture/baseline.json`：以 `target_module == "app.domains.credits.types"` 计共 66 条，分布在 accounts、auction、badges、blackjack、gift_pack 等 15 个领域。D3 落地后这 66 条可一次清零（`credits/types.py` 是目前唯一的 `types` 模块）。
- 积分缓存失效：试点把登记留在调用方。`credits/repository.py` 的 `add_tx`\/`deduct_tx`\/`move_tx` 只做加锁与 SQL 增量，失效由调用方显式调用 `credits.service.register_cache_invalidation(session, mutation)` 完成（blackjack `part_1/2/3/4/5/7`、gift_pack、auction、badges、accounts、donation、lines、media_access、prediction、treasure 等约 18 处），这些 repository → credits.service 的边也以债务形式封存。
- 因此实施顺序固定为：先做 3.1（`types` 放行与纯度合约、credits 写入 `*_tx` 自登记并按 key 去重），再做礼包的 `*_tx` 迁移；自登记落地后，调用方的显式登记变成幂等冗余，礼包移除自己的那处，其余领域按 `make-credit-changes-atomic` 的清理责任分批收敛。

备选方案：在 credits repository 里增加以 `tg_id` 为参数的 `*_tx` 变体，绕开 `CreditAccount`。这会为 plex 和 emby 两类账户重复出一套 API，也会丢掉值对象的校验。所以不采用。

### D4 领取事务：固定加锁顺序与三步式条件求值

领取在一个 session 内完成：

1. 锁礼包行，再锁领取状态行，与现在相同。
2. 读取用户上下文，然后由 `rules.required_metrics(conditions, audience, now)` 算出需要取哪些数：指标名加时间窗。受众名单、礼包未开始时不取窗口数据等短路规则都在这一步决定。
3. 按上一步的清单逐项调用 D2 的查询 `*_tx`，每个指标只取一次。
4. `rules.evaluate(...)` 做纯计算，得到受众结果、条件结果和进度。
5. 根据奖励清单，按固定顺序预先加锁：先 `statistics`，再 `plex_user`，最后 `emby_user`。只锁本次发放需要的行。
6. 按礼包 JSON 里的顺序调用各写入 `*_tx`。它们对已经锁住的行再次 `FOR UPDATE` 不会获取新锁，所以奖励的生效顺序和响应中的奖励顺序都不变。
7. 已领份数加一，写入领取状态；有特权码时，把持久化放在最后（D6）；然后提交。

固定的加锁顺序与 credits 转账、lines 解锁的顺序一致，消除了"奖励顺序相反导致死锁"的可能。三步式求值与现在"按需计数、请求内缓存"取到的数据集合相同。如果现有实现在某条路径上短路了取数，第二步的规划必须复现同样的集合；`test_gift_pack_conditions.py` 里现有的查询次数断言保持不变。

开始私信的认领路径复用第 2–4 步，加锁方式和现在相同。列表和开屏提醒路径同样复用这几步，但不加锁。

### D5 会员天数与媒体权限同步

- **写入**：新增 `premium.repository.grant_premium_days_tx`。
  - 它在调用方 session 内对已绑定的媒体账号行加锁，读出当前到期时间，用 `premium.rules` 算出新的到期时间，然后写入。
  - 计算规则与现在的 `update_premium_status` 逐项一致，包括永久会员跳过及其提示。
  - 读和写在同一个 session、同一把锁下，不会丢失更新。
- **提交后同步**：新增 `premium.service.sync_premium_media_access(tg_id)`，参数中不再有门面实例。
  - 它的内部暂时仍可延迟导入门面：premium.service 在 B1 桥接时本来就是门面的合法导入者，这部分由 `promote-line-domains` 清理。
  - 下载权限同步继续调用 `premium.service.apply_download_unlock_to_media`。
  - 两者都由 `gift_pack.service` 在提交后调用，失败时的处理与现在相同：下载同步失败记为 `download_sync_failed` 并改写响应文案，会员同步失败只记 warning。

### D6 特权码例外挪到 invitation

- **发放**：`issue_codes_tx(..., privileged=True)` 只在事务里写入邀请码行。
- **持久化**：写 `settings.PRIVILEGED_CODES` 和 `.env` 的动作，改由新增的 `invitation.repository.persist_privileged_codes_tx(session, codes)` 完成。它沿用现在的模块锁、`raise_on_error=True`，以及失败时恢复内存列表的逻辑。
- **调用时机**：礼包在领取事务的最后一步调用它，位置与现在相同，也就是其他写入都完成之后、提交之前。这样把 `.env` 写入与提交之间的间隔保持在最短。
- **文档**：`docs/architecture.md` 的例外清单改为"invitation 的特权码持久化"。

这样，`move-privileged-codes-to-database` 只需要改 invitation 的这两个函数，礼包不用再动。invitation 里其他写 `.env` 的路径（`service.py:38-42`、`router.py:313-315`、`451-453`）本变更不动，由那个变更一并移除。

### D7 service 与提交后副作用

`gift_pack.service` 提供领取、用户列表、开屏提醒、管理端的增删改查、统计、领取记录、名单解析、开始私信认领和过期扫描等用例。router、jobs 和 notifications 只调用 service。

- **吞异常的方法**：现在吞异常并返回默认值的 9 个方法，改由 service 保持同样的返回值。repository 的 `*_tx` 一律不吞异常。
- **提交后的副作用**：由 service 在提交后执行，依次是：积分缓存失效（已经登记在 session 上）、媒体权限同步（D5）、通知。
- **通知的派发**：统一通过 `gift_pack.notifications` 以 detached、best-effort 的方式派发。派发函数须同时支持两种调用场景：在事件循环线程里直接创建任务；在线程池里提交到主事件循环。售罄通知和创建通知不再依赖 FastAPI 的 `BackgroundTasks`。通知的内容和接收人不变，发出时刻相对 HTTP 响应的先后不属于对外契约。
- **通知模块不再读数据**：`_format_rewards` 改用 `rules.reward_label`；各个 `notify_*` 所需的礼包数据由 service 传入，不再调用 `db.get_gift_pack_by_id`。

备选方案：service 返回待执行的通知列表，由 router 交给 `BackgroundTasks`。这会让 FastAPI 的类型留在业务流程里，同一类副作用也会分散到两处处理。所以不采用。

### D8 类型化异常与错误契约

新增 `gift_pack/exceptions.py`，基类是 `GiftPackError(DomainError, ValueError)`，与 21 点保持一致。继承 `ValueError` 是为了兼容过渡期现存的 `except ValueError` 和 16 处测试断言。API 层已注册的 `DomainError` 处理器按 `payload["detail"]`（没有则用 message）返回 `{"detail": …}`。

| code | 状态码 | detail |
|---|---|---|
| `gift_pack_not_found` | 领取、编辑时 400；删除、启停、统计时 404 | 礼包不存在 |
| `gift_pack_disabled` / `not_started` / `ended` / `sold_out` / `already_claimed` | 400 | 礼包已停用 / 礼包尚未开始 / 礼包已结束 / 礼包已被领完 / 你已领取过该礼包 |
| `gift_pack_user_missing` | 400 | 用户积分信息不存在 |
| `gift_pack_conditions_not_met` | 400 | `{"message": "不满足领取条件", "requirements": [...]}`，由 `ConditionsNotMet` 直接携带进度 |
| `gift_pack_reward_rejected` | 400 | 原文，如"请先绑定媒体账号后再领取"，或外域的业务文案 |
| `gift_pack_invalid` | 400 | 创建、编辑、名单解析时的校验原文 |
| `gift_pack_referenced` | 400 | 被其他礼包引用时的原文 |

规则：

- **状态码在抛出处确定**：同一个"礼包不存在"，在不同用例中返回 400 或 404，所以状态码由 service 在抛出点确定。启停和统计接口仍然由"返回 None"映射成 404，这包括数据库异常的情况。
- **发放阶段的外域异常**：service 捕获外域抛出的 `ValueError` 子类（例如 `CreditError`，或其他领域的 `DomainError` + `ValueError`），包装成 `gift_pack_reward_rejected` 并保留原文。这样，发放阶段的拒绝仍然返回 400、不通知管理员。
- **非业务异常**：由 router 统一返回原来的 500 文案。领取路径额外发送 `claim_failed` 通知。router 在 `except Exception` 之前先 `except DomainError: raise`，不做任何字符串匹配。
- **唯一允许的差异**：删除一个被引用的礼包时，如果它的标题里含"不存在"，旧实现会误判成 404，新实现返回 400。测试会固定这一情况。

### D9 基线、合约与工具

- **清理**：删除礼包名下的 21 条基线条目、5 条 `ignore_imports`，以及 Six-tier 和 Acyclic 合约里各 1 条门面组合边；在同一个提交里下调封存计数。门面冻结合约的 `allowed_importers` 中删除礼包的 3 个模块。
- **refactor 工具**：`scripts/refactor/verify.py:28-30` 和 `split_repository.py:120-121` 按字符串引用了礼包的私有方法，这是 B 阶段 D4 自引用改写的特例。这些特例失效后一并删除，`tests/refactor` 保持通过。
- **测试**：测试里的 `setattr(router, "db", orm)`、按模块 patch `time`、patch 私有方法等写法，改为调用 service 或 repository 的公开函数，断言内容不变。

## Risks / Trade-offs

- **[搬移提交移动基线键和冻结夹具]** → 由脚本改写基线键并校验多重集合不变；夹具的 diff 只允许路径变化。搬移提交不能夹带语义改动，verify 的逐项 AST 比对必须零差异。
- **[D3 改动架构规则]** → 新规则只放行无 I/O 的值对象，并用 import-linter 的纯度合约守住。如果试点已有等价实现，就不重复实现。
- **[固定加锁顺序改变了锁的集合]** → 只是提前锁住本来就会锁的行。会员天数新增的锁，把原来可能丢失更新的读写收进同一事务。用一次性 PostgreSQL 做并发测试：最后一份的争抢、同一用户并发领取、领取与线路解锁交叉进行；验证既不死锁也不超发。
- **[三步式求值改变查询次数]** → 规划阶段复现现有的取数集合，保留现有的查询次数断言；规划结果与原懒加载路径逐条对照。
- **[外域异常的包装改变文案]** → `gift_pack_reward_rejected` 原样保留外域的 message，响应文案逐条与冻结夹具对比。
- **[通知改为 detached 派发]** → 内容、接收人和"失败只记日志"的语义都不变。测试用假的派发器断言每类通知恰好发一次，且在提交之后。
- **[特权码残留]** → `.env` 写入成功、随后提交失败时，文件里会留下没有对应数据库行的码。这是现有行为，本变更不扩大这个窗口，由 `move-privileged-codes-to-database` 彻底消除。用测试固定当前行为，避免被无意改变。
- **[测试基于 SQLite]** → 行锁和并发语义以一次性 PostgreSQL 的测试为准，SQLite 只做功能回归。

## Migration Plan

1. 确认 `promote-blackjack-domain` 已全部完成，并核对 D3 的前提。冻结礼包的接口、调度、错误响应和领取结果快照。
2. 搬移阶段：礼包 mixin 按子主题重组，21 点按子主题重组，新增序号模块检查；各自单独提交，verify 零差异。
3. 新增 D2 的各个 `*_tx`，以及 D5、D6 的函数，每个都配测试。
4. 抽取 rules，引入类型化异常。
5. 把 repository 改为模块级函数，新增 service，迁移入口。
6. 摘掉 mixin，清理基线与合约。
7. 在 SQLite 上跑全量回归；在一次性 PostgreSQL 上跑并发和回滚测试，并做元数据比对；对照快照。
8. 部署：没有 schema 变更，也没有 jobstore 变更，正常发布即可。回退就是回退镜像。

## Open Questions

无。21 点和礼包包内的最终文件名在映射表审阅时确定，不影响方法或任务拆分。
