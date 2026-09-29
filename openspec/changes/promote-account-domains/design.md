# Design

## Context

动机见 proposal.md。本设计假定以下变更已完成：`make-credit-changes-atomic`、`promote-blackjack-domain`、`promote-gift-pack-domain`（`types` 角色已放行，invitation 已有 `issue_codes_tx`）、`unify-business-configuration`（注册开关和邀请积分都已是领域配置）、`promote-activity-domains`。

现状（调研时的 `3f27100`）：

**identity**（593 行）

- `IdentityRepository` 有 17 个方法，其中 4 个没有调用方：`get_plex_info_by_plex_username`、`get_emby_info_by_emby_id`、`update_user_tg_id`，以及 accounts 的 `add_all_plex_user`。它们都不在手动运维清单里。
- 另有 5 个模块级 `*_tx`，用于建档和绑定。
- 查询返回位置元组：Plex 12 元、Emby 11 元、统计 3 元、Overseerr 3 元。
- 门面上共 84 处调用。本批的 accounts 11 处、invitation 19 处；本批以外有 9 个领域 50 处，另有 2 个脚本 4 处。
- `add_plex_user` 和 `add_emby_user` 在提交前写 `user_info_cache`。
- 5 个领域有 10 处直接构造 `Statistics(...)`。

**accounts**（767 行）

- 没有 mixin。只有 `bind_plex_account` 和 `bind_emby_account` 两个模块函数，各自在一个事务里完成绑定和积分合并。
- 绑定路由的预检用独立 session，不加锁；并发冲突靠 `tg_id IS NULL` 条件和唯一索引兜底。
- 没有媒体账号的解绑功能。
- 同步任务 `update_plex_info` 做了 7 件事：
  - 按 plex_id 改名。
  - 按邮箱回填 plex_id。
  - 回填 invitation 的 plex_id。
  - 改流量记录里的用户名（经门面调 traffic）。
  - 删除 token 缓存。
  - 刷新头像。
  - 启动守护线程，延时删除按邮箱命名的调度任务。
- 该任务已由 `fix-live-defects` 改为逐用户隔离；库里没有对应行时跳过当前用户，后续用户仍继续同步。

**invitation**（1,050 行）

- `InvitationRepository` 有 8 个方法。
- 生成邀请码有三处入口（路由、bot、管理员接口），都是先插码、后扣分。
- `add_redeem_code` 被 luckywheel、donation 和 invitation 的管理员接口调用，异常一律吞掉。
- 兑换积分时，"标记已用"的 UPDATE 不检查 `is_used`，并且总是返回成功。
- 凭码注册 Plex 的流程：
  1. 检查注册开关、Plex 人数上限（达到容量即拒绝，属于 reports）、邀请码。
  2. 发出 Plex 邀请。
  3. 在数据库里标记已用。
  4. 选择绑定 TG 时建一行 plex_id 为空的账号，并注册 `update_plex_info_for_{email}` 内存任务：每分钟运行一次，1 小时后结束。
  5. 通知管理员。
  6. 处理特权码。
- 凭码注册 Emby 的结构与此相同。

**D3 第 2 处环**

- accounts→invitation：`accounts/service.py:96-104` 经门面调用 `update_invitation_plex_id`。
- invitation→accounts：`invitation/router.py:26-27` 导入 `update_plex_info` 和 `refresh_emby_user_info`。
- 回填的数据只有 watch_rewards 在发邀请人奖励时读取。

**错误契约**

- 业务拒绝几乎都返回 HTTP 200 加 `success=false`，由 BaseResponse、RedeemResponse 等响应模型承载。
- `points-info`、`generate` 和 `register-status` 会把内部抛出的 404 吞掉，实际返回 500。
- 全局的 `DomainError` 处理器只能输出 `{"detail"}` 加错误状态码，表达不了这种 200 契约。

**基线与合约**

- `owner=promote-account-domains` 的条目共 63 条。
- 门面冻结合约中有本批的 7 个放行项。SQLAlchemy、引擎、模型三个合约各有 3 条标为 B3 的忽略项（accounts.jobs、accounts.service、invitation.service）。
- 六层合约有 5 条 `→db`，另有 2 条门面组合边；无环合约有 2 条组合边；入口合约有 8 条。

**事件机制**

仓库里还没有事件机制。`core/db.get_session` 已经支持 `session.info["post_commit_callbacks"]`：提交后同步执行，回滚时丢弃。

## Goals / Non-Goals

**Goals：**

- 三个领域达到提升模板的目标形态：入口只调用 service，SQL 只在 repository 中，跨域调用只经 service 或 `*_tx`。
- identity 提供带类型的查询 API。本批和能合法迁移的调用方改用新 API；其余调用方经兼容层保持可用。
- 用领域事件消除 D3 第 2 处环，回填的触发条件和范围与现在完全一致。
- 生成邀请码和兑换积分这两处改为单事务。
- 清空本批名下可以清空的基线条目和忽略项。

**Non-Goals：**

- 不迁移本批以外领域对 identity 或 invitation 的入口层调用。路由、bot、jobs 调用其他领域本来就是违规，由各领域自己的提升变更改为经过本领域 service。
- 不重复修复已由 `fix-live-defects` 完成的缺陷；本变更冻结以下修复后的行为：
  - `update_plex_info` 遇到缺少本地行时只隔离该用户，继续同步其他用户。
  - Plex 人数上限按容量边界判断，特权码也不能绕过容量限制。
  - `points-info`、`generate` 和 `register-status` 保留各自原始的 200/400/404 契约，不再把 404 吞成 500。
  - 凭码注册的外部调用与邀请码状态更新仍按既有顺序执行；邀请码"只能兑换一次"的语义由 `move-privileged-codes-to-database` 的 `invitation-codes` 规格统一定义。
  - 未绑定 TG 的 Plex 注册分支仍由本变更的 D5 继续完成，其他同步行为冻结在修复后的结果。
- 不新增媒体账号解绑功能。
- 不改 Emby 注册在响应和私信中返回明文密码的现有行为。

## Decisions

### D1 identity：带类型的查询 API 与兼容层

- **数据类**：在 `identity/types.py` 中定义 `PlexAccount`、`EmbyAccount`、`UserStatistics`、`OverseerrAccount`，字段名与列名一致。
- **查询函数**：repository 提供模块级函数，每个都有 `*_tx` 版本：
  - `find_plex_by_tg_tx` / `find_plex_by_id_tx` / `find_plex_by_email_tx`
  - `find_emby_by_tg_tx` / `find_emby_by_username_tx`
  - `get_statistics_tx`
  - `find_overseerr_by_tg_tx` / `find_overseerr_by_email_tx`
  - `count_bound_plex_users_tx`：取代凭码注册对 reports 的调用
  - 建档：`ensure_statistics_tx`，以及现有的 `create_*`、`bind_*`
  - identity.service 对外暴露不带事务的版本。
- **兼容层**：`IdentityRepository` 改为兼容层：
  - 每个方法只调用新函数，再把结果转换成原来的元组，没有任何 SQL，也不吞新的异常；旧方法原来吞异常并返回 None 的语义保留。
  - 类的文档字符串写明"仅供尚未提升的领域经门面调用，由 `retire-legacy-db-facade` 删除"。
  - 新增架构检查：兼容层模块不得导入 SQLAlchemy。
- **缓存写入**：`add_plex_user` 和 `add_emby_user` 中"提交前写 `user_info_cache`"的逻辑，改为在同一 session 上登记提交后回调，写入的内容不变。
- **零调用方法**：4 个没有调用方的方法，先查手动运维清单，并经维护者确认，再删除。
- **`Statistics` 的构造**：其他领域直接构造 `Statistics(...)` 的 10 处，本变更不改，在 `docs/architecture.md` 中写明"建档一律调用 `identity.repository.ensure_statistics_tx`"，由各领域在提升时迁移。

备选方案：本变更就迁移全部 50 处外部调用。其中大多数在路由里；改成调用 identity.service 仍然违规，只是基线键变了，会被只减不增的检查拒绝。要合法，就得先给这 9 个领域各建 service，这等于提前做它们的提升。所以不采用。

### D2 accounts：绑定、Overseerr 与同步进入 service

- **绑定**：
  - `accounts.service.bind_plex(tg_id, email)` 和 `bind_emby(tg_id, username)` 承担路由中的预检和外部查询：用 Plex API 查用户 ID 和库，用 Tautulli 查观看时长，用 Emby 查用户。
  - 写入仍由 repository 的 `bind_*_account_tx` 在一个事务里完成，预检的顺序和文案都不变。
- **Overseerr**：`accounts.service.create_overseerr(tg_id, …)` 先调外部接口、再写库，顺序与现在一致。
- **同步任务**：`update_plex_info` 拆成 service 编排和 repository 写入：
  - 流量用户名改为调用 `traffic.service.rename_user(...)`，这是本变更新增的 traffic service，内部调用 traffic repository 的模块级函数。
  - 删除 token 缓存和刷新头像，都放到提交后执行。
  - 删除延时移除调度任务的守护线程，这件事改由 D4 的具名任务自己完成。
  - `except: print` 改为记录日志；缺少本地行时只隔离当前用户，冻结 `fix-live-defects` 的修复行为。
- **注册开关**：`/set_register` 调用 accounts.service，读写的领域配置由 `unify-business-configuration` 提供。

### D3 invitation：生成、兑换与凭码注册进入 service

- **生成邀请码**：路由、bot、管理员三处统一调用 `invitation.service.generate_codes(owner_tg_id, count, *, charge=…, privileged=False)`。
  - 在一个事务里依次执行：锁统计行 → `credits.repository.deduct_tx` → `invitation.repository.issue_codes_tx`。
  - 扣分失败时，不再留下已插入的码。
  - `add_redeem_code` 的调用方（luckywheel、donation）改用同一个 service，并由 service 保持"异常吞掉、返回空列表"的旧语义，所以这两个领域看到的行为不变。
  - 码的格式不变，仍是 uuid3 或 uuid4 生成的 32 位十六进制。
- **兑换积分**：`invitation.service.redeem_for_credits(tg_id, code)` 在一个事务里完成：
  1. 条件更新 `WHERE code=? AND is_used=0`。
  2. 影响行数为 0 时，抛出 `InvitationCodeUsed`。
  3. 否则调用 `credits.repository.add_tx` 加分。

  删除原来"失败后再扣回"的补偿逻辑。
- **凭码注册**：`invitation.service.register_plex(...)` 和 `register_emby(...)` 按现有顺序编排：预检 → 外部调用 → 标记 → 建号或绑定 → 通知管理员 → 处理特权码。
  - Plex 人数上限改用 `identity.service.count_bound_plex_users()`，并冻结 `fix-live-defects` 的达到容量即拒绝行为。
  - Emby 的建号信息刷新改为调用 `accounts.service`（同层依赖，方向与现在相同）。
- **错误契约**：定义 `InvitationError(DomainError, ValueError)` 及其子类。对于 200 契约的接口，router 捕获这些类型化异常，构造原来的响应模型（`success=false` 加原文案）；500 路径保持原来的文案。全部删除字符串匹配。

### D4 领域事件：`core/events.py`

```python
class DomainEvent: ...  # 冻结 dataclass 的基类


def publish(session, event: DomainEvent) -> None: ...  # 在 session 上排队，提交后分发
def subscribe(event_type, handler) -> None: ...  # 只允许组装层调用
```

- **分发**：`publish` 在 session 上登记一个提交后回调，所有排队的事件都由它分发。每个 session 只登记一次。
- **执行语义**：
  - 提交后，`get_session` 在提交事务的线程里按发布顺序同步调用处理函数。
  - 回滚时，排队的事件随回调一起丢弃。
  - 处理函数在事务之外运行，自己开 session。
  - 它的异常只记日志，不影响已提交的原操作。
  - 处理函数必须幂等。
- **事件定义**：放在发布方领域的 `events.py` 中，只有不可变的 dataclass。`events` 与 `types`、`exceptions`、`constants` 一样，可以跨域导入。AST 检查允许订阅方的 service 导入它。
- **注册**：新增组装模块 `app/subscriptions.py`，用 `register_all()` 显式列出订阅关系，写法与 `schedule.py` 类似。
  - `main.py` 在启动 bot、API 线程和调度器之前调用它；`manage.py` 和测试夹具也调用。
  - `app.subscriptions` 加入顶层分层合约的组装层。
  - AST 检查禁止在组装层以外调用 `subscribe`。
- **本变更的唯一事件**：
  - accounts 发布 `PlexUserIdResolved(email, plex_id)`：由 `update_plex_info` 在"按邮箱回填 plex_id"的那一行写入时发布。
  - invitation 的处理函数回填 `service='plex' AND used_by=email AND plex_id IS NULL` 的邀请记录。条件与现在完全相同，包括区分大小写。
  - 因为只在原来会回填的那一刻触发，回填的范围与现在一致。
- **临时任务改为具名任务**：凭码注册改为调度 invitation 的具名任务 `invitation.resolve_plex_id`。
  - 它放在内存 jobstore，参数是 email；开始时间、间隔和 1 小时的结束时间都与现在相同。
  - 任务调用 `accounts.service.sync_plex_user_by_email(email)`，结束后自己移除，不再需要守护线程。
  - `promote-activity-domains` 已经让具名任务可以放进内存 jobstore，但只支持一次性触发。本变更在 `core.scheduler.schedule_task` 上增加带结束时间的 interval 触发，并配单元测试。

事件的异步扩展，例如处理函数需要发送 Telegram 通知，由 `promote-reward-domains` 在同一个模块上实现。

备选方案：

- **组装层组合两个调用**：由 `schedule.py` 先调 accounts，再用返回的 plex_id 调 invitation。这相当于把业务编排写进了组装层。
- **invitation 自己定期扫描**：会扩大回填范围，从而改变邀请人奖励的发放。

### D5 watch_rewards 的邀请人查询

watch_rewards 的 service 经门面调用 `get_inviter_tg_id_by_plex_id` / `get_inviter_tg_id_by_emby_id`（2 处）。改为调用 `invitation.service` 是合法的"service 调 service"，本变更一并迁移，并删除这 2 条基线条目。profile 对 invitation 的 3 处调用都在入口层，保留经兼容层调用，由 `promote-remaining-domains` 迁移。

### D6 基线与合约

- **基线条目**：`owner=promote-account-domains` 的 63 条，都是 accounts 和 invitation 对其他领域的调用和导入，本变更全部清除。另外，D5 删除 watch_rewards 名下的 2 条。
- **`promote-gift-pack-domain` 带来的变化**：
  - 它的 D3 放行了 `types` 角色。本批以 `credits.types` 为目标的 12 条（导入和 `CreditAccount` 的构造调用）在那时就会被清除，所以实施时本批名下是 51 条。
  - 它的 D3 还让 credits 的 `*_tx` 自己登记提交后的缓存失效。accounts 中 3 处对 `credits.service.register_cache_invalidation` 的显式调用因此变得多余：确认对应的积分写入都经过 credits 的 `*_tx` 后，直接删除，不搬进 service。
- **门面冻结合约**：删除 accounts 和 invitation 的 7 个放行项。
- **门面组合边**：identity 和 invitation 的兼容层仍由门面组合，所以六层和无环两个合约里的 4 条组合边忽略项保留，注释改为"负责变更：`retire-legacy-db-facade`"，并写明原因。
- **其他忽略项**：删除 B3 标注的 SQLAlchemy、引擎、模型忽略项（accounts.jobs、accounts.service、invitation.service），以及入口合约中本批的 8 条和六层合约中本批的 5 条 `→db`。
- **封存计数**：在同一提交中下调。

## Risks / Trade-offs

- **[兼容层让门面多存在一段时间]** → 兼容层没有 SQL，只能转发，有架构检查守住；`docs/architecture.md` 列出剩余调用方及其负责变更。retire 前，最后一个调用方迁移完即可删除。
- **[数据类替换元组会漏改下标访问]** → 本批改动完成后，用 AST 扫描 accounts 和 invitation，确认不再对查询结果做下标访问；原有测试加上新补的行为测试共同兜底。
- **[事件同步分发增加请求耗时]** → 本变更唯一的处理函数是一条 UPDATE，而且只在同步任务中触发。异步和耗时的处理函数由 reward 变更引入专门的派发方式。
- **[生成邀请码改为单事务，改变了失败时的结果]** → 只在扣分失败时有差异：原来留下一个免费的码，现在不留。这是修复，在测试和发布说明中写明。
- **[兑换积分的条件更新]** → 并发兑换时，第二个请求会得到"已被使用"，而不是同一个码再加一次分。这是修复，在测试中覆盖。
- **[具名任务替换临时任务]** → 用调度快照测试比对任务的触发时间、间隔和结束时间；一次性环境里的冒烟验证回填确实发生，并且任务会自己移除。

## Migration Plan

1. 补齐行为测试（proposal 所列的场景）。
2. 实现 identity 的新 API 和兼容层，迁移本批调用方和两个脚本。
3. 引入 `core/events.py` 和 `app/subscriptions.py`，完成回填事件和具名任务。
4. 迁移 accounts、invitation 的 service 与入口，完成两处原子性修复。
5. 迁移 watch_rewards 的 2 处调用，清理基线和合约，更新文档。
6. 全量回归；在一次性 PostgreSQL 上做并发兑换测试；在生产形态副本上彩排一次凭码注册（外部接口用替身）。
7. 部署：没有 schema 变更。回退就是回退镜像。

## Open Questions

无。
