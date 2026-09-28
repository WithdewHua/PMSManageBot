# Tasks

## 1. 行为冻结与测试补齐

- [ ] 1.1 冻结六个领域的行为快照：OpenAPI 与路由顺序（包括 `/pending`、`/orders/all` 的位置）、bot 输出、调度任务，以及各接口在成功和各类拒绝下的响应；把各 mixin 的成员登记进 `mapping.toml` 并写明目标位置。验证：连续生成两次，快照一致；没有未映射的成员。
- [ ] 1.2 补齐 donation 和 crypto_donation 的测试：
  - donation：登记、查询、确认（批准、拒绝、非 pending）、管理员登记、bot `/set_donation`。
  - crypto_donation：下单（成功，以及 UPay 失败时删除本地订单）、回调（签名错误、重复回调、正常入账）、过期任务。

  外部接口用替身。验证：新测试在当前代码上全部通过，已知问题的现状由测试明确断言。
- [ ] 1.3 补齐 vaultwarden、rankings、reports、profile 的测试：兑换的成功与各类失败；每个榜单的接口和对应的 bot 命令（数量上限、是否排除管理员、过滤条件）；系统统计、流量总览、设置总览、周报；个人信息接口和 bot `/info`。验证：新测试在当前代码上全部通过；排行接口出错时返回 `[]` 的现状由测试断言。

## 2. 业务领域提升

- [ ] 2.1 提升 donation：改为模块级 repository，新增 `add_donation_tx`，删除 `update_user_donation`；确认、管理员登记和 bot 登记都改为单事务；登记改用 `ensure_statistics_tx`；勋章事件改由 service 发布；通知移入 `notifications.py`；把 `update_donation_credits` 登记进手动运维清单。验证：
  - 1.2 的测试通过。
  - 在一次性 PostgreSQL 上并发确认同一条登记，只入账一次。
  - 在积分写入时注入失败，状态、捐赠额和积分一起回滚。
- [ ] 2.2 提升 crypto_donation：SQL 全部移入 repository；下单时检查回写结果；回调改为单事务，带状态条件，保证幂等，失败时返回非 ok；过期任务改为单事务。验证：
  - 1.2 的测试通过。
  - 在一次性 PostgreSQL 上并发发送重复回调，只入账一次。
  - 入账失败时订单仍处于待支付状态，响应为非 ok；随后重试回调能正常入账。
- [ ] 2.3 提升 vaultwarden：新建 repository；兑换改为"扣分 → 开号（在线程中执行）→ 记录"，开号失败时退还积分；reports 改为调用 vaultwarden 的 service 统计兑换数。验证：1.3 的兑换测试通过；开号失败时积分被退还；退款也失败时有 error 日志和管理员通知。

## 3. 读模型整理

- [ ] 3.1 按 design D4 新增分析函数：luckywheel 的邀请码奖品次数、treasure 的夺宝奖金、`invitation.service.invitee_counts()`、lines 和 custom_lines 的线路分类；让 rankings 和 reports 改为调用这些函数；在 `docs/architecture.md` 中写入新的读模型规则。验证：每个分析函数都有对照测试，在同一份夹具上与原 SQL 的结果完全相同；排行和统计接口的响应与夹具一致。
- [ ] 3.2 在 `rankings.service` 中把入口之间的差异改为显式参数，bot 和接口共用这些函数；改用批量函数读取用户名和头像。验证：bot 输出和接口响应与夹具逐字一致。
- [ ] 3.3 新建 profile 的 repository，放 `/api/user/users` 的查询；个人信息接口通过各领域的 service 组装，会员欠额改用 `premium.service`。验证：两个接口和 bot `/info` 的输出与夹具一致。
- [ ] 3.4 新增读模型只读检查：rankings、reports、profile 的 repository 中不得出现写操作或模型构造。验证：检查的正反例测试通过；`pytest tests/architecture` 通过。

## 4. 模型归位与遗留清理

- [ ] 4.1 把 `CreditsTransferRequest` 和 `CreditsTransferResponse` 搬进 `credits/schemas.py`，把积分缓存重写任务的查询搬进 credits 的 repository；清除 make-credit-changes-atomic 名下的 14 条遗留条目，以及相关的 7 条忽略项。验证：转账接口的 OpenAPI 与响应不变；缓存重写任务的测试通过；这 14 条基线条目已删除。
- [ ] 4.2 从门面删除 `DonationRepository`、`CryptoDonationRepository`、`RankingsRepository`、`ReportsRepository`；删除 donation 中 2 处对 `register_cache_invalidation` 的显式调用（design D8）；清除 remaining 名下的条目（80 条，其中 13 条 `credits.types` 条目已由礼包变更清除）、69 条标注的忽略项、2 条 crypto_donation.jobs 忽略项和 8 条门面组合边，并下调封存计数；更新 `test_model_registry.py` 和 `smoke_b3_decycles.py`。验证：
  - `lint-imports`、`pytest tests/architecture`、`pytest tests/refactor` 通过。
  - `baseline.json` 中不再有 remaining 或 make-credit-changes-atomic 名下的条目。
- [ ] 4.3 用 AST 确认 identity 和 invitation 兼容层的调用方为 0，并记录进 `docs/architecture.md`。验证：扫描结果为 0；文档写明兼容层已经可以由 retire 删除。

## 5. 集成验证

- [ ] 5.1 生产形态本地彩排：在完整数据库副本上，对比新旧实现的全部排行、统计、个人信息接口和 bot 排行命令的输出。外部服务用固定的替身数据。验证：输出逐项一致。
- [ ] 5.2 运行全量回归：`pytest tests/`、`ruff check`、`ruff format --check`、`lint-imports`、`pre-commit run --all-files`，然后运行 `openspec validate promote-remaining-domains --strict`。验证：全部通过；工作区干净。
