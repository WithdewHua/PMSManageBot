# Design

## Context

动机见 proposal.md。本设计假定此前的变更都已完成，尤其是：

- `promote-line-domains`：lines 和 custom_lines 的模型已经从 `profile/schemas.py` 搬回各自的领域；traffic 已经把流量排行作为分析函数通过 service 暴露。
- `promote-activity-domains`：prediction 已经把排行作为分析函数通过 service 暴露。
- `promote-reward-domains`：donation 和 crypto_donation 在路由中用 `emit` 发布勋章事件。
- `fix-webapp-auth-bypass`：UPay 回调已有签名和金额校验。
- identity 和 invitation 的兼容层仍由门面组合。

现状（调研时的 `3f27100`）：

| 领域 | 结构 | 门面 mixin |
|---|---|---|
| donation（1,111 行） | router、repository、schemas、admin_router、bot、models、service | `DonationRepository`，8 个方法 |
| crypto_donation（1,131 行） | router、repository、schemas、jobs、models | `CryptoDonationRepository`，10 个方法 |
| vaultwarden（311 行） | router、notifications、models、schemas；没有 repository | 无 |
| rankings（1,105 行） | router、repository、bot、service、schemas | `RankingsRepository`，10 个方法 |
| reports（763 行） | service、repository、router、constants、admin_router、rules、bot、jobs | `ReportsRepository`，6 个方法 |
| profile（755 行） | schemas、router、service、bot、jobs；没有 repository | 无 |

**donation**

- 登记时，donation 的 repository 会自己构造 `Statistics`。
- 确认时，先在独立事务里改状态（不检查 `pending`），然后在事务外读出捐赠额、算出新值，再在另一个事务里 `apply_tx` 并写回绝对值。没有统计行时，用 `add_user_data(credits=…, donation=…)` 通过构造参数直接写积分，积分 inventory 检测不到这种写法。
- 管理员登记和 bot 登记都先写捐赠额，再另开事务加分。
- bot 通知里把倍率写死为 2。

**crypto_donation**

- 路由里直接写 SQL 查询媒体账号、删除订单。
- 下单：先插入本地订单，再调用 UPay，最后回写 UPay 返回的信息（不检查结果）。
- 回调：按 trade_id 查到订单后，无条件把状态更新为 2；再用读改写更新捐赠额，另开事务加分；入账失败时仍返回 ok。
- 过期任务：查询和更新分在两个事务里。

**vaultwarden**

- 兑换顺序：读余额 → 调用外部服务开号（同步的 requests，会阻塞事件循环）→ 扣积分（独立事务）→ 写兑换记录（路由里直接用 `get_session`）。
- 扣分失败时，返回 200"兑换成功但更新积分失败"。

**rankings**

- 自己的 repository 查询积分、捐赠、观看时长、邀请、转盘、夺宝和勋章。21 点、预言、流量三类榜单通过对应领域的 service 获取。
- 路由内层吞掉异常，返回 200 加 `[]`。
- bot 与接口的差异：积分榜 bot 取前 30、不排除管理员，接口不限数量、排除管理员；时长榜 bot 每个服务取前 15、不过滤 0，接口过滤掉 0，并附加头像、会员标记和 `is_self`。

**reports**

- 系统统计的总用户数在路由里直接写 SQL。
- 流量总览按 `STREAM_BACKEND`、`PREMIUM_STREAM_BACKEND` 做子串匹配来识别线路，按 `status == "approved"` 识别自建线路。
- 设置总览按路由名在 `api/app.py` 中组装。

**profile**

- `/api/user/info` 依次调用 identity、traffic、media_access、premium 和 invitation，每一块都用 try 包住，出错就省略；会员欠额的计算公式与 premium 重复。
- `/api/user/users` 在路由里直接写 SQL，列出所有用户的积分和捐赠额，没有管理员校验，前端转账功能在用。
- bot 的 `/info` 在没有统计行时会抛 TypeError。

**基线**

- remaining 名下 80 条：donation 29、profile 19、crypto_donation 10、rankings 8、reports 8、vaultwarden 6。
- make-credit-changes-atomic 名下遗留 14 条。
- pyproject 中标给 remaining 的忽略项 69 条：门面冻结 11、SQLAlchemy 4、引擎 5、模型 6、六层 17、入口 26。另有 crypto_donation.jobs 的 2 条，以及 8 条门面组合边。

**测试**：只有倍率重算的 2 个测试。

## Goals / Non-Goals

**Goals：**

- 三个业务领域达到目标形态，捐赠和积分的每个用例都在一个事务里完成。
- 读模型的边界清楚：只读；不涉及业务规则的聚合直接读表；需要其他领域业务规则的数据，通过该领域的 service 获取。
- 清空 remaining 名下的基线条目，以及 credits 的遗留条目。到本变更结束时，门面只剩 identity 和 invitation 的兼容层，而它们已经没有调用方。

**Non-Goals：**

- 不重复修复已由 `fix-live-defects` 完成的缺陷；本变更冻结以下修复后的行为：
  - 排行接口查询或头像补全出错时返回固定 500；空结果仍返回 200 加空列表。
  - bot `/info` 在缺少统计行时按 0 显示。
  - bot 通知使用实际入账的积分倍率。
  - 登记通知失败不删除已保存的登记；保存失败返回固定 500 文案。
- `/api/user/users` 不加管理员校验：维护者判断排行榜本来就公开了这些数据，`fix-live-defects` 也不修改它。
- 不修正读模型现有的统计口径，例如时长榜用原始的 `is_premium` 列，不考虑到期时间。
- 不改变 `app.manage report` 的参数与默认值。

## Decisions

### D1 donation：单事务与增量

- **repository**：改为模块级函数。新增 `add_donation_tx(session, tg_id, amount)`，用 SQL 增量更新 `statistics.donation`；删除按绝对值写入的 `update_user_donation`。
- **确认**（`service.confirm_registration(id, admin_id, approve)`），在一个事务里依次执行：
  1. 条件更新：`UPDATE … WHERE id=? AND status='pending'`；影响行数为 0 时，返回原来的"状态不是 pending"。
  2. 批准时：`identity.repository.ensure_statistics_tx` → `add_donation_tx` → 对非开号捐赠调用 `credits.repository.add_tx`。
  3. 事务提交后：捐赠开号（`invitation.service.generate_codes`），失败只记日志，与现在一致；发布 `DonationApproved`（从路由的 `emit` 改为 service 的 `publish`）；通知用户和管理员。
- **管理员登记和 bot 登记**：同样在单事务中写入捐赠额增量和积分；bot 路径仍不发布勋章事件。
- **登记**：改用 `ensure_statistics_tx` 建档，不再在 donation 中构造 `Statistics`。
- **通知**：通知模板移入 `notifications.py`，文案不变。
- **倍率重算**：`update_donation_credits` 保留，作为手动运维入口，登记进手动运维清单。

### D2 crypto_donation：回调幂等与单事务

- **repository**：路由里的 SQL 全部移入 repository。
- **下单**：顺序不变（插入本地订单 → 调用 UPay → 回写）。回写时检查影响行数；回写失败按下单失败处理：删除本地订单并返回原来的错误。
- **回调**（在签名和金额校验之后）在一个事务里完成：
  1. 执行 `UPDATE … SET status=2 WHERE trade_id=? AND status=1`。
  2. 影响行数为 0、而订单已经完成时，直接返回 ok，保证幂等。
  3. 否则按订单金额执行 `add_donation_tx` 和 `credits.repository.add_tx`，然后发布 `CryptoDonationCompleted`。
  4. 事务失败时回滚，返回非 ok 的响应，让 UPay 重试。原来是"返回 ok、入账丢失"，这是有意为之的变化。
- **过期任务**：在一个事务里执行 `UPDATE … SET status=3 WHERE status=1 AND expire_at < now`。

### D3 vaultwarden：先扣分、后开号

- **repository**：新建，内容包括兑换记录的写入和统计。reports 原来直接读这张表，改为调用 vaultwarden 的 service。
- **兑换**（`service.redeem(tg_id, email)`）：
  1. 检查功能开关和配置。
  2. 在一个事务里 `deduct_tx`。积分不足时，返回原来的"积分不足"文案。
  3. 在线程中调用外部开号，不再阻塞事件循环。
  4. 开号成功：在一个事务里写兑换记录，提交后通知管理员。
  5. 开号失败：在一个事务里用 `add_tx` 退还积分，并返回原来的失败文案。
- **响应文案**：原来的"兑换成功但更新积分失败"不会再出现，因为扣分失败时根本不会开号。

### D4 读模型边界

- **规则**：读模型的 repository 可以直接读其他领域的表，但只限于不涉及业务规则的聚合，即对列直接求计数、求和、排序或过滤。凡是需要其他领域业务规则的数据，都通过该领域的 service 获取；这些领域为此提供只读的分析函数。这条规则写入 `docs/architecture.md`，替换原来 D2 中"只被读模型使用的查询放在读模型领域"的表述：21 点试点已经按新规则把 21 点的排行查询放回了 blackjack。
- **迁移**：

| 数据 | 现状 | 迁移后 |
|---|---|---|
| 转盘榜"邀请码 1 枚"次数 | rankings 硬编码奖品名 | `luckywheel.service` 的分析函数 |
| 夺宝榜奖金 | rankings 用魔数 `status == 2` | `treasure.service` 的分析函数 |
| 邀请榜 | rankings 重复 invitation 的计数规则 | `invitation.service.invitee_counts()` |
| 流量总览中的线路分类 | reports 做子串匹配 | `lines.service` 和 `custom_lines.service` 的分析函数 |
| NSFW 与下载解锁数、线路调度解锁数 | reports 自己计数 | 保持 reports 直接计数（按列计数，与现在的口径一致） |
| 个人信息中的会员欠额 | profile 重复公式 | `premium.service` |

- **口径**：每个分析函数的口径与原 SQL 逐条一致，由对照测试证明。
- **只读检查**：新增架构检查。rankings、reports、profile 的 repository 中出现 `insert`、`update`、`delete`、`session.add`、`session.merge`，或者构造任何模型，都判为失败。
- **profile**：
  - 新建 repository，放 `/api/user/users` 的查询。结果和字段都不变，不加管理员校验（见 Non-Goals）。
  - 其余数据通过各领域的 service 获取。

### D5 排行的 service 与入口

- **service**：`rankings.service` 为每个榜单提供一个函数，入口之间的差异改为显式参数，例如 `credits_rank(limit: int | None, exclude_admins: bool)`、`watch_time_rank(service, limit, include_zero, with_profile)`。bot 和接口各自传入原来的取值，输出与冻结夹具逐字一致。
- **错误**：路由吞异常返回 `[]` 的行为保留，见 Non-Goals。
- **批量读取**：头像和用户名改用已有的批量函数 `get_user_names_from_tg_ids`，返回值不变，只是不再为每一行都加载一次缓存文件。

### D6 模型归位与 credits 遗留

- **转账模型**：`CreditsTransferRequest` 和 `CreditsTransferResponse` 搬进 `credits/schemas.py`。credits 的路由改为导入本领域的模型。profile 如果仍需要它们，就向下导入 credits 的模型。
- **积分缓存重写任务**：`credits/jobs.py` 中 `rewrite_users_credits_to_redis` 的查询搬进 credits 的 repository，jobs 只调用 credits 的 service。
- **基线**：清除这 14 条遗留条目、六层合约中 `credits → profile.schemas` 的忽略项，以及 6 条 B3 忽略项。条目的负责变更不改，直接删除即可，因为删除条目符合只减不增的规则。

### D7 错误契约与入口

- **状态码**：donation 和 crypto_donation 的 HTTPException 状态码保持不变；donation 的管理员接口保持 200 契约；由路由把类型化异常映射成原来的响应。
- **组装方式**：`api/app.py` 按路由名组装的 4 个接口，名字保持不变：`get_user_info`、`get_all_users`、`submit_donation_record`、`get_admin_settings`。
- **路由顺序**：`/pending` 在 `/{id}` 之前，`/orders/all` 在 `/orders/{order_id}` 之前。
- **调度**：调度任务 id 保持不变。

### D8 基线与合约

- **清理**：清除 remaining 名下的 80 条基线条目，以及 69 条标注的忽略项、2 条 crypto_donation.jobs 忽略项和 8 条门面组合边；从门面删除 `DonationRepository`、`CryptoDonationRepository`、`RankingsRepository`、`ReportsRepository`；下调封存计数。
- **`promote-gift-pack-domain` 带来的变化**：
  - 它的 D3 放行了 `types` 角色。remaining 名下以 `credits.types` 为目标的 13 条在那时就会被清除，所以实施时是 67 条。
  - 它的 D3 还让 credits 的 `*_tx` 自己登记提交后的缓存失效。donation 中 2 处对 `register_cache_invalidation` 的显式调用因此变得多余：确认对应的积分写入都经过 `*_tx` 后直接删除，不搬进 service。
- **依赖门面的测试和脚本**：
  - `tests/refactor/test_model_registry.py:23-28` 改为断言新的模块函数。
  - `scripts/refactor/smoke_b3_decycles.py` 调用了 `db.get_traffic_statistics`，改为调用 reports.service，使 `test_b3_decycles` 继续有效；这个脚本和测试最终由 retire 删除。
- **兼容层**：本变更结束时，用 AST 确认 identity 和 invitation 兼容层的调用方为 0，并记录在 `docs/architecture.md` 中，供 retire 删除。

## Risks / Trade-offs

- **[UPay 重试语义变化]** → 只在入账事务失败时出现：现在返回非 ok，UPay 会重试；回调是幂等的，重试不会重复入账。在测试中模拟重复回调和失败后重试。
- **[Vaultwarden 开号失败需要退款]** → 退款失败时记录 error 并通知管理员，由人工处理，这比现在"开了号却没扣分"更容易核对。用测试覆盖开号失败、退款失败两种情况。
- **[分析函数与原 SQL 口径不一致]** → 每个迁出的查询都有对照测试：在同一份夹具数据上，新旧实现的结果完全相同。
- **[读模型只读检查误报]** → 检查只作用于三个读模型的 repository；如有合法写入需求，例如缓存，应放在 service 层，不能放进 repository。
- **[profile 兼容层调用方迁移遗漏]** → D8 在结束前用 AST 确认兼容层的调用方为 0。

## Migration Plan

1. 补齐六个领域的行为测试，冻结响应、bot 输出和调度快照。
2. 提升 donation、crypto_donation、vaultwarden，完成原子性修复与事件迁移。
3. 迁移读模型：分析函数、只读检查、service 参数化、模型归位、credits 遗留。
4. 清理基线与合约，确认兼容层没有调用方。
5. 全量回归；在一次性 PostgreSQL 上做捐赠并发确认和重复回调测试；在生产形态副本上对比排行、统计和个人信息接口的输出。
6. 部署：没有 schema 变更。回退就是回退镜像。

## Open Questions

无。
