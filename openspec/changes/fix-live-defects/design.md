# Design

## Context

动机和缺陷清单见 proposal.md，修复后的行为见 `specs/`。缺陷的位置、复现和来源，来自 2026-09-28 的六组只读调研，每项都在内存 SQLite 加外部服务替身上复现过。行号随着礼包变更的提交还在移动，下面用函数和文件定位。

**实施时的代码状态**

- `promote-gift-pack-domain` 已完成。可以直接使用：
  - `premium.repository.grant_premium_days_tx`、`media_access.repository.unlock_download_tx`。
  - credits 的 `*_tx` 已经自己登记提交后的缓存失效。
  - `types` 角色，以及基线重键脚本 `scripts/refactor/rewrite_baseline_keys.py`。
- 其余提升变更都还没开始：路由里还有业务流程，repository 还挂在门面上。本变更就在现有位置修改，不提前做提升。
- 生产环境跑的是重构前的代码，维护者决定不单独热修复，修复随重构版本发布。

**与提升变更的约定**：提升变更的"冻结现状"测试，对本变更涉及的行为，固定修复后的结果。本变更完成后，要同步修改那些变更中"由缺陷修复变更处理""用测试固定现状"的表述（见 D14）。

**测试工具**

- 使用 `tests/conftest.py` 的 `session_env`（内存 SQLite）。
- 路由用 `endpoint.__wrapped__` 加一个带 `state.telegram_data` 的假请求直接调用，写法参照 `tests/refactor/test_gift_pack_http_contract.py`。
- 时间用 FrozenDatetime 冻结，参照 21 点锦标赛的自动创建测试。
- 需要 PostgreSQL 的用例（`GROUP BY` 的语义、行锁并发），参照 `tests/refactor/test_credit_concurrency.py`，只在设置了测试数据库 URL 时运行。
- `system_config`、`ghost_session_log` 等主键为 BIGINT 的表，在 SQLite 上不会自增，测试里要显式给 id。

## Goals / Non-Goals

**Goals：**

- 消除 proposal 中列出的会算错积分、造成权益或数据不一致、把成功报成失败的缺陷。
- 所有涉及积分的修复都满足 `make-credit-changes-atomic` 的原子性要求。
- 定时任务幂等：重跑、补跑、多实例都不会重复发放。

**Non-Goals：**

- 不追溯以往漏发或多发的积分，也不重建已经丢失的每日 Plex 数据。
- `/api/user/users` 不加管理员校验（维护者决定）。
- 不做生产热修复。
- 以下问题不在本变更处理，需要先用生产数据核实：
  - 幽灵会话水位线按开始日期判断，可能漏补结算之后才写入历史的记录。
  - 同一个 plex_id 或 emby_id 对应多条已使用的邀请码。
- 不把 Plex 观看结算改为按日期查询。补跑时 Tautulli 的滚动 24 小时窗口仍会偏移，但有了结算记录，不会重复发放。
- 不修改 UPay 回调的幂等性，这由 `promote-remaining-domains` 的 D2 处理。

## Decisions

### D1 零额积分变动

- **规则**：`credits.service` 的 `add`、`deduct` 和 `credits.repository` 的 `add_tx`、`deduct_tx` 在数额为 0 时直接返回：
  - 返回的 `CreditMutation` 中，before 等于 after，delta 为 0。
  - 不加锁，不写库，不登记缓存失效。
- **仍然拒绝负数**：`CreditAmount.validate_amount` 的规则不变，现有测试照旧，只在它之前短路 0。这与 `apply_tx` 已有的"0 跳过"一致。
- **账户不存在**：数额为 0 时也照常检查账户是否存在，行为与原来相同，避免掩盖"找不到账户"的错误。
- **为什么放在 credits**：调研列出了 12 处可能传入 0 的调用点。逐个加判断容易遗漏；而且 proposal 的约定"价格为 0 就是免费，退款为 0 就是无退款"，本来就是积分层面的规则。

备选方案：各调用点判断。这需要改 12 处，而且之后新增的调用点仍可能漏掉。

**会员流量费的透支扣费**：

- credits 的 repository 新增 `charge_premium_traffic_tx(session, account, amount)`：锁住统计行，用 SQL 增量扣除，不检查余额，允许结果为负；零额和负数的处理与 `deduct_tx` 相同；自己登记提交后的缓存失效。
- 名字写明用途，文档字符串写明"系统中唯一允许余额为负的扣费"。
- 新增架构检查：只有 watch_rewards 可以调用它。将来会员流量费的结算搬到别的领域时，同步修改这条检查。
- `deduct_tx`、`deduct`、`transfer` 仍然不允许透支。
- **负余额随账户迁移**：`move_tx` 现在只在余额大于 0 时才迁移，余额为负时什么也不做。未绑定账户绑定 TG、TG 换绑都用它，于是会员流量费形成的欠款会被留在旧账户上，旧行随后被删除时欠款就消失了。改为按原值迁移，包括负数：源账户清零，目标账户加上这个值（可以因此变为负数）。这不算新的透支来源，只是让已有的欠款跟着账户走。

### D2 观看积分结算

改动都在 `watch_rewards/service.py` 的 Plex 和 Emby 两个结算函数中。两个函数的签名和返回值不变，`manage.py` 不用改。

- **结算记录表** `watch_reward_settlement`（新增迁移，接在当时的 alembic head 之后）：

  ```text
  id               BIGINT PK
  service          TEXT NOT NULL      -- 'plex' | 'emby'
  account_key      TEXT NOT NULL      -- plex_id 或 emby_id
  settlement_date  TEXT NOT NULL      -- YYYY-MM-DD，按 settings.TZ
  tg_id            BIGINT NULL
  credits_delta    NUMERIC NOT NULL
  premium_charge   NUMERIC NOT NULL   -- 会员流量费，可能使余额为负
  inviter_tg_id    BIGINT NULL
  inviter_bonus    NUMERIC NOT NULL
  created_at       BIGINT NOT NULL
  UNIQUE (service, account_key, settlement_date)
  ```

- **每个用户一个事务**，按以下顺序执行：
  1. 插入结算记录：PostgreSQL 用 `ON CONFLICT DO NOTHING`，SQLite 用 `INSERT OR IGNORE`；影响行数为 0 时，说明今天已经结算过，跳过这个用户。
  2. 计算并写入积分和扣费。
  3. 写入会员流量欠额。
  4. 给邀请人发奖励：邀请人有统计行时才发；两行统计按 tg_id 升序加锁，与转账的锁顺序一致。
  5. 把这个用户在快照中的幽灵会话按行 id 标记为已补偿。
- **会员流量费允许透支**：这是原有设计，也是系统中唯一允许余额为负的情况。
  - 第 2 步中，观看积分用 `add_tx`，会员流量费用 D1 新增的 `charge_premium_traffic_tx` 全额扣除，余额可以变为负数；结果与 `968dde2` 按净值写入的结果相同。
  - 余额为负的用户，之后使用其他功能时，由各功能现有的余额检查拒绝，这与原来一致。
- **失败隔离**：对每个用户单独 try/except，失败时回滚这个用户，记下原因，继续处理下一个。失败名单附在管理员汇总后面。
- **汇总和通知**：
  - 扣费汇总在每个用户提交之后才追加。
  - 邀请人通知在循环结束后，按已提交的奖励汇总，显示最后一次入账后的余额（`mutation.after`）。
- **水位线**：`ghost_session/settled_through_date` 在循环结束后推进，不论是否有用户失败。失败用户的幽灵补偿已经由第 5 步按行保留，不依赖水位线。
- **全表标记**：删除原来的 `mark_ghost_compensation_settled` 全表更新，改为按行 id 标记。

### D3 账号同步

改动在 `accounts/service.py` 的 `update_plex_info`，Emby 的同步函数按同样的写法检查。

- 同步分为四个阶段：改名和邮箱、plex_id 回填、邀请记录回填、头像刷新。每个阶段逐个账号处理，每个账号一个事务，并单独捕获异常，用 `logger.exception` 记录。
- 本地缺少记录的好友：记一条 info 日志后跳过，不建记录。
- 按邮箱解析 plex_id（`integrations/plex.py`）时，两边都转成小写再比较。
- 原来最外层把异常 `print` 到 stdout 的捕获，改为 `logger.exception`。

### D4 Plex 注册人数上限

- 判断从 `== 100` 改为 `>= 100`，计数口径不变（已绑定 plex_id 的行数）。
- 检查放在消耗邀请码之前；将来改为预占流程时，也放在预占之前（与 `move-privileged-codes-to-database` 的 D2 一致）。
- 部署前先查询当前人数。如果已经达到或超过 100，Plex 注册会立即关闭，需要提前告知维护者。

### D5 未绑定 TG 的 Plex 注册

本项依赖 `promote-account-domains`，在它之后实施，所以写在最后一组任务里。

- **建记录**：凭码注册 Plex 时，以下两种情况也建一条 `tg_id` 为空的 Plex 记录，并调度同一个具名任务 `invitation.resolve_plex_id`：
  - 用户选择不绑定。
  - 用户选择绑定，但他的 TG 已经绑定了其他 Plex 账号，因而降级为不绑定。
- **回填**：任务解析出 plex_id 后，发布 `PlexUserIdResolved`，由 invitation 回填邀请记录。
- **`/bind/plex`**：
  - 先按 plex_id 查找；找不到时，按邮箱（不区分大小写）查找 plex_id 为空的记录。
  - 绑定时补上 plex_id，并发布同一个事件。
  - 按现有规则转入这条记录上累积的积分。这些积分是注册以来按天累积的，不再按 Tautulli 的历史观看时长折算，这一点已由维护者确认。
- **并发绑定**：两个请求同时绑定同一个账号时，因账号已被绑定而产生的拒绝，包括唯一约束冲突，都映射为"该账户已被绑定"。Emby 的绑定也一样处理。

### D6 邀请码接口的未绑定响应

- `points-info`：返回 `can_generate=false`、`current_points=0`、`error_message="用户未绑定 Plex/Emby 账户"`。
- `generate`：返回 `success=false`，文案相同。
- 与 `redeem-for-credits` 和 bot `/exchange` 的现有做法一致，前端不用改。
- `promote-account-domains` 把这个拒绝建模为 `InvitationError` 的子类，映射回同样的 200 响应。

### D7 自建线路

- **结算记录表** `custom_line_settlement`（新增迁移）：

  ```text
  id, line_id (BIGINT, 不设外键), tg_id, domain,
  year_month (TEXT, YYYY-MM, 按 settings.TZ),
  trigger (TEXT: 'monthly' | 'delete'),
  traffic_bytes (BIGINT), credits (NUMERIC), created_at
  UNIQUE (line_id, year_month)
  INDEX (domain, year_month)
  ```

  唯一键选 `(line_id, 月份)`。选 `(domain, 月份)` 会让同名重建后当月剩余的部分不再结算。同名重建的重复计入，改由下面的扣减规则防止。

- **结算一条线路**（月度和删除共用）：在一个事务里执行：
  1. 插入记录；冲突则跳过。
  2. 计算结算流量：该域名当月总量，减去同域名当月已有结算记录的流量，排除所有者自用流量。
  3. `add_tx` 发放积分；数额为 0 时按 D1 自动跳过。
  4. 回写记录中的流量和积分。

  提交后再发通知。
- **删除**：与删除在同一个事务里，结算当月；上个月没有结算记录时，也结算上个月。
- **流量查询失败**：当月流量查询改为抛出异常，不再返回 0。结算时这条线路回滚并记录，继续处理下一条。流量上限检查逐条线路捕获同样的异常。
- **所有者排除**：两处比较都改为 `func.lower(列) == 所有者名的小写`。
- **月份口径**：新增纯函数 `custom_lines.rules.month_key(now, tz)`，流量检查、结算和通知都调用它；`jobs.py` 和路由里两处用本地时区的地方，改用 `settings.TZ`。
- **上线、续期和提交申请**：
  - 删除两处 `from app.core.config import config`，改用已导入的 `settings.TZ`。
  - 所有格式化都挪到提交之前。
  - 提交后的通知各自 try，失败只记日志。
  - 提交申请中的 `settings.TG_ADMIN_IDS` 改为 `TG_ADMIN_CHAT_ID`，并通过现有的管理员通知函数发送。
  - 失败响应去掉 `{e}`，只保留固定的失败文案。
- **导入守卫**：新增架构测试，要求 `src` 中所有 `from app.… import X`（包括函数内的延迟导入）都能解析。在当前 HEAD 上，它只会命中上线和续期这两处。

### D8 竞拍

- **结束函数**：repository 中的 `finish_auction_tx(session, auction_id)` 在一个事务里执行：
  1. `SELECT … FOR UPDATE` 锁住竞拍行；如果已经不是进行中，返回"已结束"。
  2. 取最高出价：`ORDER BY bid_amount DESC, bid_time ASC, id ASC LIMIT 1`。
  3. 有出价时 `deduct_tx` 扣得主积分。余额不足的处理与现在相同。
  4. 标记结束，写入得主。

  锁的顺序是先竞拍行、再统计行。
- **service**：`finish_auction(auction_id)` 调用上面的函数；只有真正完成结束的一方，才在提交后发送通知：
  - 有得主：私信得主，并通知频道。
  - 流拍：只发流拍通知。
  - 每条通知单独 try。
- **三个入口**都调用 `finish_auction`：定时结束任务、管理员手动结束、兜底任务。
  - 手动结束已结束的竞拍：返回 400"竞拍已结束"。
  - 流拍：返回 200，响应结构不变。
- **兜底任务** `finish_expired_auctions`：
  - 查询所有 `is_active=1 AND end_time<=now` 的竞拍 id，逐个调用 `finish_auction`，一场失败不影响其他场。
  - 删除原来带 `GROUP BY` 的查询。
  - 触发器从每天 02:00 改为每 10 分钟。任务 id 不变，调度快照同步更新。
- **启动恢复**：
  - 新增不限条数的查询，恢复所有 `is_active=1` 的竞拍，`run_date = max(end_time, now)`。
  - 保持 `finish_single_auction_job(auction_id)` 的签名，以便 `promote-activity-domains` 把它改为具名任务。
- **出价**：`place_bid` 锁住竞拍行后再校验，已结束或已过结束时间就拒绝，提示沿用现有的"竞拍已结束"。
- **前端**：`Management.vue` 中结束按钮的显示条件，从 `status=='active'` 改为 `is_active`。
- **没有调用方的统计函数**：`avg(count())` 在两种数据库上都报错。确认没有调用方后删除。

### D9 夺宝自动开期

- **迁移**：在夺宝期数表上新增两列：
  - `auto_reopen_due_at`：BIGINT，可为空。
  - `auto_reopen_issue_id`：BIGINT，可为空。

  历史数据这两列为空，不会被补开。
- **开奖**：在开奖事务里写入 `auto_reopen_due_at = 开奖时间 + 10 分钟`。
- **开期** `open_next_issue(source_issue_id)`：在一个事务里执行：
  1. 锁住源期。
  2. 已有 `auto_reopen_issue_id` 时跳过。
  3. 创建新期，并回填 `auto_reopen_issue_id`。

  提交后发送群通知。已有其他进行中的期数时照常开期。
- **任务**：`treasure.open_next_issue` 的任务名和参数不变，`misfire_grace_time` 改为 None。
- **补救扫描**：
  - 新增具名任务 `treasure.reopen_overdue`，每 10 分钟运行一次；启动时也运行一次。
  - 对 `auto_reopen_due_at <= now AND auto_reopen_issue_id IS NULL` 的期数调用 `open_next_issue`。
  - 在 `schedule.py` 中注册，并更新任务注册测试。

### D10 会员

- **购买**（`premium/router.py`）：
  1. 在任何写入之前，检查该服务是否为永久会员，是则抛出 400"您已是永久 Premium 会员，无需续费"。
  2. 在一个事务里依次执行 `deduct_tx`（金额和截断规则与原来相同）和 `grant_premium_days_tx`。
  3. 提交后同步媒体权限并通知管理员。

  前端 `PremiumUnlockDialog.vue` 的错误分支改为优先读取 `error.response.data.detail`。
- **到期任务**：
  - 逐个用户处理，每人一个事务：先做条件降级（`WHERE` 仍为会员且已到期，影响行数为 1 才继续），再解绑会员线路。
  - 提交后依次执行：写网关缓存、撤销会员附带的下载权限、发送通知。
  - 每个用户单独 try，失败的用户列进管理员汇总。
  - `lines.rules.is_binded_premium_line` 对空线路返回 False；通知中空线路显示为自动线路。
  - 由于每个用户单独判断是否到期，原来批量降级和逐个处理之间两次取当前时间造成的漏处理窗口也随之消失。
- **撤销下载权限**：
  - 从 repository 取撤销目标（邮箱或 emby_id）。
  - 该服务的永久解锁标志为 0，并且当前不是会员，才撤销。
  - `is_download_unlocked` 查询失败时不再返回 False，改为抛出异常。撤销路径捕获这个异常后不撤销，并列进管理员汇总（失败时保守处理）。
- **存量用户**：
  - 新增只读脚本 `scripts/list_expired_download_holders.py`，列出同时满足以下条件的用户：会员已到期、媒体服务器上仍有下载权限、没有永久解锁。
  - 维护者确认名单后，由同一脚本的 `--apply` 执行撤销。
  - 在 `docs/architecture.md` 的手动运维清单中注明：`sync_download_permissions.py` 会把服务器上的权限写成永久标志，不能用来对账，也不能重跑。

### D11 下载解锁

- 付费解锁改为在一个事务里依次执行：
  1. `deduct_tx`（先锁统计行）。
  2. `unlock_download_tx(session, tg_id, service)`，它会锁住媒体账号行。
- `unlock_download_tx` 的两处调整：
  - 没有记录时，抛出类型化异常 `MediaAccountNotBound`，替代现在的 `ValueError`。礼包调用方原来捕获 `ValueError` 的逻辑，改为捕获这个类型。它继承自 `ValueError`，所以原有的捕获也仍然有效。
  - 返回"已跳过"（已经解锁）时，付费路径抛出 `DownloadAlreadyUnlocked`，整体回滚。
- 路由的映射：
  - `MediaAccountNotBound`：200，`success=false`，"请先绑定 Plex/Emby 账户"，不通知管理员。
  - `DownloadAlreadyUnlocked`：原来的"无需重复解锁"响应。
- 提交后同步媒体服务器，失败只记 warning，与现在相同。
- 删除 `set_download_unlocked` 和原来的独立扣分路径。

### D12 业务拒绝与错误响应

- **在 `except Exception` 之前加 `except HTTPException: raise`**：
  - `invitation/router.py`：`points-info`、`generate`。这两处同时按 D6 改为 200 契约。
  - `prediction/router.py`：`create_market`、`submit_market`。
  - `rankings/router.py`：流量榜的两个接口。
  - `luckywheel/router.py`、`media_access/router.py`：各一处。
- **去掉异常原文**：错误响应中带 `{e}` 的地方，本变更只处理自建线路（提交、上线、续期）和线路预览这几个接口。其余接口的同类问题，交给各自的提升变更，它们引入类型化异常时会统一处理。
- **防止回归**：新增一个 AST 检查，列出路由中"`except Exception` 前没有放行 `HTTPException`、但 try 块里抛出了 `HTTPException`"的地方。本变更修完后，这个列表为空。

### D13 其余修复

- **排行**：
  - 删除路由内层的 try，以及 rankings、traffic、prediction、blackjack 排行查询中吞异常返回空列表的写法。
  - 外层 except 返回 500 和现有文案。
  - 名字和头像的补全逐行 try，失败时这一行的这两项留空。
  - 游戏榜任一子榜失败时，整个接口返回 500。
  - bot 的排行命令改为自己捕获异常，回复"获取失败"。
- **捐赠登记**：
  - repository 在同一个事务里返回新记录的 id，不再反查"最新一条"。
  - 删除失败时删除登记的逻辑。
  - 提交后用 `notify_admins_by_url` 尽力通知，然后返回 200。
  - 保存失败时返回 500 和固定文案，不会再出现 `UnboundLocalError`。
- **捐赠的 bot 通知**：文案中的积分改用 `credits_service.add(...)` 返回的 `delta`。
- **bot `/info`**：缺少统计行时，积分和捐赠额按 0 显示。
- **线路预览**：
  - 三个接口补上 `Depends(get_telegram_user)`。
  - 查询的账号就是当前用户绑定的账号时，照旧返回个性化结果。
  - 其他账号：`available` 返回完整目录（普通线路和全部高级线路，带标签和 `is_premium`），`current` 返回 `line=null`。
  - 失败响应去掉异常原文。

### D14 同步其他变更的文档

本变更完成后，逐一修改下列变更中"由缺陷修复变更处理""用测试固定现状"的表述，改为"已由 `fix-live-defects` 修复，冻结修复后的行为"：

- `promote-activity-domains`：Context 中的已知缺陷、D1"保持 500"、D5"条数上限和过滤条件不变"。
- `promote-account-domains`：Non-Goals；Context 中"中止的行为保持不变""仍是 == 100"；"register-status 把 404 吞成 500"的误记。
- `promote-line-domains`：Non-Goals、D3 中永久会员抛错、D4 中"未绑定仍扣分"。
- `promote-reward-domains`：Context 中的显示问题、Non-Goals 中的部分提交；D5 的 `settle_user_tx` 要包含结算记录、邀请人奖励和补偿标记。
- `promote-remaining-domains`：Non-Goals 中的五项；D4 中 `/api/user/users` "字段不变"保持原样，因为维护者决定不修。

如果某个提升变更先于本变更实施，就由本变更在它的新位置上修改，并翻转它固定现状的断言。

## Risks / Trade-offs

- **[Plex 人数上限立即生效]** → 部署前查询人数；已满时提前告知维护者。
- **[透支接口被误用]** → 名字只表达会员流量费一种用途，并由架构检查限定调用方；credits 规格写明这是唯一的例外。
- **[竞拍兜底频率提高]** → 查询只取进行中且已到期的竞拍，通常为空，开销很小。
- **[新表不回填历史]** → 部署当月，不要用新代码重跑旧代码已经结算过的月份或日期；这一点写进发布说明。
- **[撤销存量下载权限]** → 只读脚本先出名单，维护者确认后才执行。
- **[线路预览不再显示他人的当前线路]** → 绑定对话框里"当前绑定"的标记只对自己的账号显示；绑定时的权限检查不变，非会员仍然无法绑定高级线路。
- **[与礼包会话的冲突]** → 本变更在礼包变更完成后实施；动到礼包也使用的 `unlock_download_tx` 时，保持它对礼包的返回值不变。

## Migration Plan

1. 三个迁移（观看结算记录、自建线路结算记录、夺宝两列）依次接在当时的 alembic head `c0d1e2f3a4b5` 之后；已在一次性 PostgreSQL 上执行 upgrade → downgrade → upgrade，并在最终 head 上完成元数据比对（无差异）。
2. 按 tasks 的分组逐组实施，每组全量回归。
3. 在生产形态副本上彩排：
   - 观看结算：连续运行两次，第二次无变化；注入一个失败用户，其余用户照常结算。
   - 自建线路：月度结算重跑。
   - 竞拍：兜底结束一场丢失调度的竞拍。
   - 会员到期：一个线路为空的用户和两个绑定高级线路的用户。
   - 存量下载权限：只读名单。
4. 随重构版本部署：先执行迁移，再启动新版本。
5. 回退：回退镜像即可，新增的表和列留在库里，旧代码会忽略它们。回退后，旧代码的重复结算风险恢复。

## Open Questions

无。
