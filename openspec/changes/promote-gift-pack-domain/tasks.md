# Tasks

## 1. 前置核对与行为冻结

- [ ] 1.1 核对 `promote-blackjack-domain` 的任务已全部完成，并记录它对 D3 两个前提的处理方式：`types` 能否跨域导入；积分缓存失效由谁登记。如果试点的做法与 D3 不同，先更新 design D3 再往下做。验证：试点 tasks 全部勾选；D3 中写有核对结论。
- [x] 1.2 冻结礼包的行为快照：OpenAPI 与路由顺序、两项调度任务（id、触发器、首跑延迟）、领取的各类结果（成功、每种拒绝、发放阶段拒绝、500）、管理端 8 个接口的响应；把 repository 全部 55 个成员登记进 `scripts/refactor/mapping.toml` 并写明目标位置。验证：连续生成两次，快照逐字节一致；覆盖检查没有未映射的成员。
  - 交付：`scripts/refactor/gift_pack_snapshot.py` + `tests/refactor/fixtures/gift_pack_surface.json`（11 条路由、10 条 OpenAPI path、2 项调度任务含触发器与首跑延迟、15 个门面方法、55 个 repository 成员、3 张表）；`tests/refactor/fixtures/gift_pack_http_contract.json` + `tests/refactor/test_gift_pack_http_contract.py`（28 个用例：领取成功与各类拒绝、发放阶段拒绝、500、用户列表与开屏提醒、管理端 8 个接口）。
  - 验证：两个夹具连续生成逐字节一致（md5 不变）；`test_gift_pack_baseline.py` 断言快照与夹具相等且 55 个成员都有 `planned_target`；时间戳、随机邀请码、邮箱在快照里已归一化，行 id 从固定基数分配，与执行顺序无关。
- [ ] 1.3 补齐描述现有行为的测试：
  - 管理端 list 和 records 接口。
  - 删除接口的 404/400 分流，包括"标题含'不存在'时返回 404"这一现状。
  - 各个 500 分支。
  - 领取被拒的全部文案。
  - 创建、售罄、发放失败三种通知。
  - 会员续期的计算，以及永久会员的跳过和提示。
  - 提交后的权限同步和同步失败时的文案。
  - 过期扫描任务。
  - 邀请码以外的每类奖励，在后续步骤失败时一并回滚。
  - `.env` 写入成功、随后提交失败时的现状。

  验证：新增测试在当前代码上全部通过。
  - 交付：`tests/test_gift_pack_jobs.py`（过期扫描：汇总内容、限量/不限量文案、置位后不重发、发送失败不置位并下轮重试）；`tests/test_gift_pack_audience.py`（管理端 list/records 分页与总数、删除 404/400 分流与“被引用礼包标题含『不存在』即返回 404”的现状、六个管理端 500 分支的固定文案、开屏提醒失败静默）；`tests/test_gift_pack_rewards.py`（除邀请码外六类奖励在后续奖励失败时逐类回滚、会员续期的三种情形与永久会员提示、提交后媒体权限同步且同步时领取已落库、`.env` 写入成功后提交失败的现状残留、创建与售罄通知只入队一次及正文）；`tests/test_gift_pack_conditions.py`（八类领取拒绝的原有文案）。
  - 验证：新增 24 个用例在当前代码上全部通过；`pytest tests/` 460 passed / 3 skipped。
- [x] 1.4 在一次性 PostgreSQL 上新增并发测试：最后一份的争抢、同一用户并发领取、礼包领取与线路调度解锁交叉进行（两边奖励顺序相反）。验证：测试能通过 `CREDITS_TEST_DATABASE_URL` 这类开关重复运行；在当前代码上，不超发的断言通过；交叉加锁用例如果复现死锁，就标为 xfail 并注明由 5.1 修复。
  - 交付：`scripts/refactor/smoke_gift_pack_concurrency.py` + `tests/refactor/test_gift_pack_concurrency.py`（由 `GIFT_PACK_TEST_DATABASE_URL` 开启，子进程跑脚本并过滤环境变量）。
  - 验证（一次性 PostgreSQL 16 容器 `postgres:16-alpine`）：S1 八人抢一份 → 恰好一人成功、`claimed_count=1`、只有一条领取状态、只发放一次奖励，七人收到“礼包已被领完”；S2 同一用户八次并发领取 → 恰好一次成功、奖励只发一次；S3 奖励顺序为“先解锁线路调度（锁 plex_user）再发积分（锁 statistics）”，与线路解锁购买路径（先 statistics 再 plex_user）相反，已复现 ABBA 死锁（每轮一次），用例标记为 xfail 并要求 5.1 固定加锁顺序后取消。
  - 说明：S3 用 `after_cursor_execute` 事件在持有行锁后短休休眠，把生产语句之间本来只有几条 Python 语句的窗口拉开，使反转可稳定复现；不对生产代码做任何修改。

## 2. 按子主题搬移（只搬不改）

- [x] 2.1 编写基线键改写脚本：按搬移映射把基线条目的 `path|line` 改到新位置，并校验条目总数不变、按 `(owner, kind, source_domain, target_domain, target/symbol)` 统计的多重集合不变。验证：单元测试覆盖正常改写、多重集合变化被拒绝、映射缺失被拒绝。
  - 交付：`scripts/refactor/rewrite_baseline_keys.py` + `tests/refactor/test_rewrite_baseline_keys.py`（12 个用例）；搬移声明文件为 `scripts/refactor/baseline_moves.toml`。
  - 规则：旧条目按 `identity + 所属符号` 配对，符号与 `path/line` 均从 `git show <base>:<path>` 的搬移前源码解析，目标侧从工作区解析；路径变化必须被搬移声明覆盖，声明里的符号目标反过来与 `mapping.toml` 的 `planned_target` 对比；`owner`、`b3_source_id` 等评审元数据保留，只改 `path`/`line`/`key`。
  - 验证：把 `part_1.py` 声明为“搬到自己”的恒等搬移后，544 条条目全部配对成功、`rewritten=0`，重写后的 `baseline.json` 与重写前逐字节相同（证明配对与来源标记不会漂移）；把 `--mapping` 指回真实的 `mapping.toml` 时会因计划目标不一致而拒绝；单测覆盖正常改写、多重集合增删、映射缺失、未登记搬移、目标不一致、符号不一致、重复声明。
- [x] 2.2 把礼包 repository 的 `part_1`–`part_3` 按 design D1 搬移为 `conditions.py`、`rewards.py`、`packs.py`、`claims.py`、`notices.py` 五个 mixin 模块，由 `repository/__init__.py` 组合，门面看到的类不变；用 2.1 的脚本改写基线键。验证：`verify.py` 逐项 AST 零差异，全量测试和 `pytest tests/architecture` 通过；本次提交只含搬移、导入和基线键的改动。
  - 交付：五个 mixin 模块 + 门面 `__init__.py`（55 个注册成员全部按 `planned_target` 到位：conditions 25、rewards 7、packs 17、claims 3、notices 3），`part_1`–`part_3` 删除；`scripts/refactor/split_gift_pack_repository.py` 是本次搬移的机械执行者（尚未纳入门面特例清理的 5.5），搬移登记在 `baseline_moves.toml`。
  - 门面自身的 5 个方法（`_resolve_gift_pack_conditions`、`_gift_pack_condition_label`、`_gift_pack_condition_summary`、`_validate_post_start_edit`、`_gift_pack_referencing_packs`）也按 `planned_target` 搬入 conditions/packs；它们的三个类限定自引用改写为新 mixin 名，并由 `[repository_mixins]` 声明在 `mapping.toml` 里，`verify.py` 据此归一化。
  - 基线：544 → 545 条。20 条礼包条目按映射改写 `path`/`line`/`key`（`owner`、`b3_source_id` 等元数据逐字节保留，`same-key-different-content = 0`），新增 1 条是 `conditions.py` 与 `rewards.py` 都要用 `Invitation` 造成的重复导入边，已在 `baseline_moves.toml` 用 `[[addition]]` 点名原条目；5.5 把生码移到 `invitation.repository.issue_codes_tx` 后消失。
  - 验证：`verify.py --base $(cat scripts/refactor/BASE)` 的错误集合与搬移前逐条相同（154 条，礼包相关 4 条，均为既有 `blackjack_service` 重绑定的已知差异）——搬移本身零新增 AST 差异；`pytest tests/` 478 passed / 4 skipped；`pytest tests/architecture` 通过；`blackjack_surface.json`、`blackjack_inventory.json`、`gift_pack_surface.json` 的 diff 只有路径/行号（条目总数分别 357/355/不变）。
- [x] 2.3 把 21 点 repository 的 `part_1`–`part_7` 按子主题搬移，目标文件名在映射表中审阅确定（参考 design D1 的表），`repository/__init__.py` 的导出不变；21 点的冻结夹具如果仍在，按映射只更新路径。验证：`verify.py` 零差异；21 点全部测试通过；夹具的 diff 只有路径变化；单独提交。
  - 交付：97 个成员按 `split_plans.toml` 的审阅表拆到 hands 24、settlement 2、jackpot 7、retention 8、wallet 1、stats 4、tournaments 35、tournament_entries 10、tournament_play 16、config_store 6；`award_or_renew_badge` 留在门面组合类 `_BlackjackRepositoryImplementation` 里（它只是兼容导出，真正实现在 `badges`）。`tournaments.py` 一开始 1,104 行超过 1,000 行预算，因此按 D1 把参赛记录／排名／一致性查询再拆出 `tournament_entries.py`（设计表同步补了这一行）。
  - 工具：`scripts/refactor/split_repository_members.py` + `scripts/refactor/split_plans.toml`（计划驱动，逐符号目标与 `mapping.toml` 的 `planned_target` 互相校验；门面类在 `[repository_mixins]` 里声明）。
  - 基线：545 → 543 条。29 条旧 `part_N` 条目按映射改写为新模块，其中两条 `credits` 导入（part_1 与其它 part 各一条）在新布局下合并成同一条边，已在 `baseline_moves.toml` 用两条 `[[removal]]` 声明并校验“边仍在包内”；`same-key-different-content = 0`，其余类别逐字节不变。
  - 验证：`verify.py --base $(cat scripts/refactor/BASE)` 错误集合与搬移前逐条相同（154 条）；`pytest tests/` 488 passed / 4 skipped；`blackjack_surface.json` 与 `blackjack_inventory.json` 的差异只有路径/行号；新增 `tests/refactor/test_blackjack_repository_split.py` 按 `planned_target` 固定落点（补上 `verify.py` 只能按包匹配的缺口）。
- [x] 2.4 在 `tests/architecture` 新增序号模块检查，并在 `baseline.json` 新增 `numbered_modules` 类别，登记 `prediction/repository/part_1.py` 和 `part_2.py`（负责变更为 `promote-activity-domains`）。在 `docs/architecture.md` 的提升模板里写明三条：按子主题拆包、搬移与语义改造分开提交、禁止序号模块。验证：临时加一个 `part_9.py` 时检查失败；删掉已登记的例外但文件还在时检查失败；文档中的规则可以在 AGENTS.md 找到链接。
  - 交付：`tests/architecture/checks.py` 的 `scan_numbered_modules` 扫 `src/app/domains/*/repository/part_<数字>.py`，负责人按领域映射（`owner_for_domain`），扫描结果进入 `scan_all` 与 `ARCHITECTURE_CATEGORIES`；`baseline.json` 新增 `numbered_modules`，当前只登记预测领域的两个文件。
  - 负向测试 `test_numbered_repository_modules_are_rejected` 覆盖两条验收：新加 `part_9.py` 报 new violations；删掉登记的例外但文件还在时报 new violations（只减不增）。
  - 文档：提升模板新增“按子主题拆包 / 搬移与语义改造分开提交 / 禁止序号模块”三条硬约束，并注明与 `AGENTS.md` 的 “Where new code goes” 同步；子主题落点与基线改写工具（`split_plans.toml`、`baseline_moves.toml`）一并记录。

## 3. 各领域提供的 `*_tx`

- [x] 3.1 如果 1.1 的结论需要，实现 design D3：（1.1 的结论是两条前提都要补）
  - 在 `tests/architecture/checks.py` 中把 `types` 列为可跨域导入的角色。
  - 新增 import-linter 的 `types` 纯度合约。
  - 让 credits 的 `add_tx`、`deduct_tx`、`move_tx` 自行在 session 上登记提交后的缓存失效，并按 key 去重。
  - 在 `docs/architecture.md` 和 AGENTS.md 中更新跨域导入规则。

  验证：检查规则的正反例测试通过；提交后缓存被失效、回滚后缓存不变的测试通过；`lint-imports` 通过。
  - 交付：`tests/architecture/checks.py` 把 `types` 与 `service`/`exceptions`/`constants` 并列，`_import_allowed` 与 `_call_allowed` 对 `target_role == "types"` 直接放行；正反例测试分别是 `test_cross_domain_types_imports_and_calls_are_allowed` 与 `test_types_role_does_not_whitelist_neighbour_roles`。
  - 纯性：`pyproject.toml` 新增 import-linter 合约 “Domain types are pure value modules”（禁止 types 导入本领域 service/repository/router/models/config/exceptions 以及 `app.core.db`、SQLAlchemy），`lint-imports` 11 kept / 0 broken。
  - 自登记：`app.core.db` 的提交后回调改为按 key 幂等注册（`register_post_commit` / `run_post_commit_callbacks`），`app.core.cache.invalidate_user_credits` 提供失效原语；`credits.repository.add_tx`/`deduct_tx`/`move_tx` 各自登记失效，`credits_service.register_cache_invalidation` 改为转发（同一 key 只失效一次）。standalone 包装不再重复失效。
  - 基线：`types` 合法化使 543 条跨域条目降到 445 条（stale 98、new 0），`audit_b3_baseline.py --write` 逐条保留 `b3_source_id`（56 条）并让 `contract_ignore_counts` 反映新合约；审计脚本改写走 `helpers.write_baseline`。
  - 验证：`lint-imports` 11/0；`pytest tests/` 497 passed / 4 skipped；新增去重用例（同一事务多次改动同一账号只失效一次）与回滚不失效用例。
  - 文档：`docs/architecture.md` 新增“跨域导入规则”一节，`AGENTS.md` 的 Imports 规则写入 types 例外。
- [x] 3.2 在 blackjack repository 中新增 `credit_tournament_wallet_tx`、`cash_hand_metrics_tx` 和 `count_tournament_entries_tx`，其中后者用常量排除已取消的赛事。验证：锁、SQL 增量、舍入和回滚测试通过；两个计数函数与原礼包计数器的边界用例（终态、非锦标赛、毫秒边界、准确率、已取消赛事）逐条一致。
  - 交付：`credit_tournament_wallet_tx` 落在 `blackjack/repository/wallet.py`（行锁 + `func.round(..., 2)` SQL 增量，返回新余额，非法数额/缺行抛 `BlackjackError`）；`cash_hand_metrics_tx`（原名 `count_eligible_cash_hands_tx`，返回手数或（手数，准确率））与 `count_tournament_entries_tx` 在 `repository/analytics.py`，后者改用 `TOURNAMENT_CANCELLED` 常量；两者经 `repository/__init__.py` 暴露（analytics 的导入放在包级包装函数之后，避免部分初始化循环）。
  - 礼包侧改走 `blackjack.repository.*_tx`：`conditions.py` 的两个计数器、`rewards.py` 的争霸赛余额奖励都不再直接写 `statistics.tournament_wallet_credits`，也不再导入 `blackjack.service`。
  - 验证：新增 `tests/test_blackjack_wallet.py`（事务内累加、两位小数舍入、调用方回滚、非正数额与缺行拒绝、AST 断言行锁/SQL 增量，以及礼包不再直接写该列）；`tests/refactor/test_blackjack_cross_domain.py` 新增“走 repository 的调用方只能调登记的 `*_tx`”。全量 505 passed / 4 skipped。
  - 基线：这三条礼包→21 点的边在新边界下合法，基线 445 → 442 条（`b3_source_id` 仍 56 条）。
- [x] 3.3 在 premium 中新增 `grant_premium_days_tx` 和 `sync_premium_media_access(tg_id)`，前者在调用方 session 内对媒体账号行加锁后读写。验证：新开、续期、已过期、永久会员（含提示）各用例与 `update_premium_status` 的结果一致；外层事务回滚时一并回滚；同步函数的签名里不再有门面实例。
  - 交付：`premium/repository.py` 新增 `grant_premium_days_tx`（`SELECT ... FOR UPDATE` 锁媒体行 + 调用方事务，永久会员返回 None，未过期从原到期时间续期，首次开通写 `premium_status_updated_at`）与 `get_premium_sync_target`，并以模块级函数暴露；`premium/service.py` 的 `update_premium_status` 改为自开事务调用 `grant_premium_days_tx` 后同步（名字与调用点不变，路由零改动），`sync_media_permission` 改名为 `sync_premium_media_access(tg_id, services=None)` 且不再接收门面实例，`apply_download_unlock_to_media` 也改为只读 premium 自己的 repository。
  - `media_access` 新增 `service.is_download_unlocked(tg_id, service)`（配 `repository.check_download_unlock` 模块级入口），premium 的同步用它判断是否需要推送，不再直读 media_access 的列。
  - 礼包侧：`rewards.py` 用 `premium_repository.grant_premium_days_tx(session, …)`（repository→repository 的合法 `*_tx` 边），`claims.py` 提交后调用 `premium_service.sync_premium_media_access(tg_id, (service,))`。
  - 验证：新增 `tests/test_premium_grants.py`（新开/续期/已过期/永久会员跳过/未绑定报 NameError/回滚/行锁 AST/签名无 db/未绑定不推送/已解锁跳过/大转盘 Premium 奖品两个服务顺序）；全量 519 passed / 4 skipped。
  - 工具与基线：`pyproject.toml` 删除 3 条已失效的 `ignore_imports`（premium.service 不再直接 import SQLAlchemy 与 identity models）；基线 445 → 430 条（20 stale / 2 条 reviewed 新增：`sync_premium_media_access` 的重命名调用与导入），`b3_source_id` 58 条；`verify.py` 零新增差异（`claim_gift_pack` 与 `_handle_premium_reward` 登记了带行为测试的 AST 例外）。
- [x] 3.4 新增 `lines.repository.unlock_line_schedule_tx` 和 `media_access.repository.unlock_download_tx`，返回“已解锁”或“已跳过”。
  - 交付：两个 `*_tx` 都在调用方事务内 `SELECT ... FOR UPDATE` 锁住媒体账号行，按各自的列归属写永久解锁标记（`line_schedule_unlocked` 归 lines，`sync_unlocked` / `download_unlocked` 归 media_access），已解锁过则返回 `{"unlocked": False, "skipped": "already_unlocked"}`，未绑定账号抛 `ValueError`。
  - 礼包侧：`_grant_feature_unlock_tx` 只保留用户可见文案，写列全部委托给这两个 `*_tx`；原先的 `_GIFT_PACK_UNLOCK_COLUMNS` 常量按列归属拆成 `_LINE_SCHEDULE_UNLOCK_COLUMNS` 与 `_DOWNLOAD_UNLOCK_COLUMNS`（mapping 与 split plan 已按人工搬运登记）。
  - 验证：`tests/test_gift_pack_rewards.py` 的 Premium 用户仍拿到永久标记、已解锁服务 skipped、未绑定报错三条用例全部通过（全量 519 passed / 4 skipped）。
- [x] 3.5 在 invitation 中实现 `issue_codes_tx`、`persist_privileged_codes_tx` 和 `count_invitees_tx`，把特权码例外挪过来；更新 `docs/architecture.md` 的例外清单。
  - 交付：`invitation/repository.py` 新增 `issue_codes_tx`（调用方事务内写 `Invitation` 行并 flush）、`persist_privileged_codes_tx`（模块锁 + 先改内存再落盘，写失败恢复内存并把异常抛给调用方 → 外围事务回滚）与 `count_invitees_tx`（按全部时间统计去重被邀请人）。
  - 礼包侧：`_grant_invite_codes_tx` 与 `_persist_privileged_invite_codes` 改成调用 invitation；`_GIFT_PACK_PRIVILEGED_CODES_LOCK` 从礼包删除，锁随例外一起搬到 invitation（`_INVITATION_PRIVILEGED_CODES_LOCK`）。
  - 文档：`docs/architecture.md` 明确这是唯一的提交前外部副作用例外且落在 invitation；`AGENTS.md` 同步更新例外描述。
  - 验证：`test_invite_codes_generated_and_in_snapshot`、`test_invite_codes_rolled_back_when_other_reward_fails`、`test_privileged_invite_config_write_failure_rolls_back_claim`、`test_privileged_code_written_to_env_stays_when_commit_fails` 全部通过。
- [x] 3.6 条件计数器落到各自领域：`luckywheel` 的 `count_paid_spins_tx`、`treasure` 的 `count_participated_issues_tx`、`prediction` 的 `count_bets_tx`、`auction` 的 `count_participated_auctions_tx`、`badges` 的 `active_badge_ids_tx` 与 `badges_exist_tx`。
  - 交付：各领域 repository 以模块级 `*_tx` 暴露口径（转盘默认只数付费、可关；夺宝按 issue 去重且毫秒边界；竞拍按 auction 去重；预言家按 UTC datetime 闭区间；被邀请人按全部时间去重；勋章取生效集合与存在集合）。
  - 礼包侧：`conditions.py` 的条件计数与 `badge_ids`、`packs.py` 的勋章引用校验全部改走这些 `*_tx`，礼包不再直接读别的领域的表。
  - 验证：`tests/test_gift_pack_conditions.py` 的窗口边界、去重、UTC、准确率与被邀请人历史口径用例逐条通过（`paid_only=False` 也在 `test_wheel_counter_includes_time_boundaries_and_filters_free_spins` 里覆盖）。
- [ ] 4.1 把 design D1、D4 列出的纯计算抽到 `gift_pack.rules`。
  - [x] 4.1a 奖励登记表、标签和摘要；条件解析（两套实现合并成一套）；生命周期、`phase_ref`、余量、受众规模、自动补绑定条件、开始后的编辑校验；`required_metrics` 与 `evaluate`（求值只读预取好的计数，`metric_value` 在窗口未开始时按 0 计，取数计划由 repository 执行）。
    - 交付：`gift_pack/rules.py`（约 500 行，未超过 1,000 行因此仍是单模块）；repository 只剩取数（`_load_gift_pack_user_context`、8 个 `*_count_*`/计数器委托、`_gift_pack_metrics`、受众锁定）与写入。
    - 验证：新增 import-linter 合约「Domain rules are pure value computations」（直接导入层面禁止 `app.core.db`、`sqlalchemy`、repository/service/router/jobs/notifications；模型只作为类型注解来源并已登记）；`tests/test_gift_pack_rules.py` 14 个用例覆盖旧格式条件、12 种条件、any_of 全子项进度、窗口未开始不取数、指标身份去重、生命周期/相位/余量/受众规模、文案与开始后编辑校验。
    - 说明：`verify.py` 新增 `method_to_function` 登记项（类方法搬成目标模块同名函数），17 个搬移单元逐条登记 `b3_ast_exception` + `b3_behavior_test`，`verify.py` 仍是 154 条既有差异、零新增。
  - [ ] 4.1b 列表状态推导、提醒节流、统计聚合、字段校验（create/update 入参校验）尚未抽出：它们目前散在 `packs.py`/`claims.py` 的较大方法里，随 5.x 的 service 化一起搬。
- [x] 4.2 新增 `gift_pack/exceptions.py`，按 design D8 定义异常类和错误码，替换 repository 里的 38 处 `raise ValueError`。验证：逐条测试每个旧文案对应的状态码和 detail；`ConditionsNotMet` 自带条件进度；外域的 `ValueError` 被包装成 `gift_pack_reward_rejected` 且保留原文。
  - 交付：`GiftPackError(DomainError, ValueError)`（错误码来自旧文案前缀表，detail 默认保留原文）+ 携带 `requirements` 进度的 `ConditionsNotMet`（有进度时 detail 就是 `{"message": "不满足领取条件", "requirements": [...]}`，与 1.2 夹具逐字一致）+ `gift_pack_not_found` / `gift_pack_error` / `wrap_reward_rejection` 工厂；状态码在抛出点确定（删除缺失礼包是 404，编辑/领取仍是 400）。
  - 迁移：repository 里 45 处 `raise ValueError` 全部改为类型化异常（conditions/packs/claims/rewards 各文件），router 的领取与删除分支改成读 `e.status_code` 与 `e.payload["detail"]`，不再做子串判断（`不满足领取条件；当前进度：` 与 `"不存在" in message` 都已删除）。
  - 唯一行为差异已固定：被引用的礼包无论引用者标题里有没有“不存在”，删除都返回 400；`tests/test_gift_pack_audience.py` 的用例改名并断言行新语义。
  - 工具：`verify.py` 抽出 `_reviewed_exception_entry`，让“登记过的变更”既能解释 AST 差异、也能解释少掉的导入绑定（礼包 router 不再需要 `json`），并补了负向单测。
  - 验证：新增 `tests/test_gift_pack_errors.py`（22 条旧文案 → 错误码/状态码/detail 逐条、进度结构、ValueError 兼容、外域包装、repository 无裸 ValueError、router 无子串判断、删除/编辑/开始后编辑三个状态码用例）；全量 554 passed / 4 skipped；`verify.py` 与改动前同为 154 条既有差异。
- [ ] 5.1 把礼包 repository 改成模块级函数。领取事务按 design D4 实现：固定加锁顺序、三步式求值、按 JSON 顺序发放、特权码持久化放在最后；其余操作在各自的事务里完成，`*_tx` 不吞异常。验证：
  - 每类奖励在发放中途失败时，余额、领取状态、邀请码和解锁全部回滚。
  - 现有的查询次数断言保持通过。
  - 1.4 的交叉加锁用例取消 xfail 后通过。
- [ ] 5.2 新增 `gift_pack.service`，覆盖 design D7 列出的全部用例；9 个吞异常的方法保持原有的默认返回；提交后依次执行缓存失效、媒体权限同步和通知派发。验证：提交后的副作用失败不会回滚已提交的领取；每类通知恰好发送一次，且在提交之后；下载同步失败时的响应文案不变。
- [ ] 5.3 改造 notifications 和 jobs：
  - notifications 不再访问数据；派发函数同时支持在事件循环线程和线程池中调用。
  - jobs 只调用 service；调度 id、触发器、首跑延迟、每批 200 人的认领上限和 0.5 秒的发送间隔都不变。

  验证：调度快照与 1.2 一致；两项 job 的测试通过。
- [ ] 5.4 改造 router：只调用 service；删除 JSON 解析和子串判断；保留 500 文案和 `claim_failed` 通知；`except DomainError` 放在 `except Exception` 之前。验证：HTTP 夹具与 1.2 逐项一致，唯一例外是 design D8 中"标题含'不存在'的被引用礼包"那一条，由测试固定；OpenAPI 与 1.2 一致。
- [ ] 5.5 摘掉 mixin 并清理合约：
  - 从 `DatabaseORM` 中删除 `GiftPackRepository`。
  - 删除礼包名下的 21 条基线条目、5 条 `ignore_imports`，以及 Six-tier 和 Acyclic 合约里各 1 条门面组合边，同步下调封存计数。
  - 从门面冻结合约的 `allowed_importers` 中删除礼包的 3 个模块。
  - 删除 `scripts/refactor/verify.py` 和 `split_repository.py` 中礼包的特例。
  - 把测试改为调用公开的 service 或 repository 函数。

  验证：`PYTHONPATH=src .venv/bin/lint-imports --no-cache`、`pytest tests/architecture tests/refactor` 通过；门面上查不到任何礼包方法；礼包代码里不再导入外域的 models。

## 6. 集成验证

- [ ] 6.1 运行全量回归：`pytest tests/`、`ruff check`、`ruff format --check`、`lint-imports`、`pre-commit run --all-files`。验证：全部通过；OpenAPI、路由、调度、Bot 快照与 1.2 一致。
- [ ] 6.2 在一次性 PostgreSQL 上运行 1.4 的并发测试和各类回滚测试，并用 `check_metadata_pg.py` 做元数据比对。验证：不超发、不死锁、没有部分提交；元数据没有差异。
- [ ] 6.3 生产形态本地彩排：在完整数据库副本上领取一个含全部奖励类型的礼包，通知替换为 no-op。验证：奖励、领取状态、积分缓存和媒体同步的调用参数与预期一致；日志里没有异常。
- [ ] 6.4 核对 `docs/architecture.md` 与实现一致，内容包括提升模板、特权码例外的新位置，以及跨域写入一律经 `*_tx`；然后运行 `openspec validate promote-gift-pack-domain --strict`。验证：校验通过；工作区干净。
