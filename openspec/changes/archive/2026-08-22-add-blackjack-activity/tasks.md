## 1. 数据模型与迁移

- [x] 1.1 在 `src/app/models/models.py` 新增 `BlackjackHand` 模型：状态、注额、加倍标记、种子与取牌游标、双方牌面、结果与赔付、参数快照四列、`tournament_id` 预留列（可空无外键）、时间戳；按设计决策 9 建 `(tg_id, status)` 与 `(tg_id, created_at_ms)` 索引
- [x] 1.2 补 CheckConstraint：`bet_credits > 0`、`status IN (1,2,3,4)`、`doubled IN (0,1)`、`next_card_index >= 0`
- [x] 1.3 更新 `SystemConfig` 的 docstring：补 `blackjack` 配置类型，并标注 `prediction_market.glory_fund` 已为跨活动共用（设计决策 8）
- [x] 1.4 生成并人工复核 Alembic 迁移（`alembic revision --autogenerate`），确认 CheckConstraint 与索引未被漏掉；`alembic upgrade head` 验证

## 2. 规则引擎（纯函数，无 IO）

- [x] 2.1 新建 `src/app/blackjack_engine.py`：牌的表示与 `random.Random(seed)` + Fisher-Yates 定序，单副 52 张
- [x] 2.2 实现点数计算：A 按 11/1 自适应降级，取不超过 21 的最大点数；对照 spec「点数判定」的三个场景验证（A+6+9=16、A+A=12、A+7=18）
- [x] 2.3 实现开局天胡判定：四种组合（仅玩家、仅庄家、双方、均无）
- [x] 2.4 实现动作合法性：要牌/停牌/加倍；加倍仅限手中恰为初始两张牌时
- [x] 2.5 实现庄家补牌：达到 17 即停（含软 17），由 `dealer_hits_soft_17` 参数控制
- [x] 2.6 实现胜负判定并返回 `(return_multiplier, profit_multiplier)` 二元组，按设计决策 1 的倍率表；逐行核对七种情形，尤其加倍胜的 `(4, 2)`
- [x] 2.7 用一组固定种子手工验算若干整手牌，确认同种子恒得同牌序、且牌序不随取牌次数改变

## 3. 配置与 DB 层

- [x] 3.1 `db.py` 新增 `get_blackjack_config` / `set_blackjack_config`，转发 `get_system_config('blackjack', key)`，照 `get_lucky_wheel_config`（`db.py:5993`）的写法
- [x] 3.2 定义默认配置并在首次读取时落库：注额档 `[5, 15, 30]`、门槛 30、`rake_bp_on_profit=300`、`rake_burn_bp=180`、`rake_glory_bp=120`、`dealer_hits_soft_17=false`、`blackjack_payout=1.5`、`hand_timeout_minutes=15`、`enabled=false`（首次上线默认停用，见迁移计划）
- [x] 3.3 实现 `create_blackjack_hand`：单事务内锁 `Statistics` 行 → 校验停用开关/门槛/注额档位/余额 → 检查无进行中手牌 → 速率下限判定（读该用户最近一手 `created_at_ms`）→ 惰性结算已超时的旧手牌 → 扣注额 → 生成种子定序 → 发初始牌 → 天胡则直接走结算路径。锁顺序 hand → statistics → system_config
- [x] 3.4 实现 `blackjack_hit`：锁手牌行，幂等闸门（终态直接返回既有结果）→ 校验状态为玩家回合 → 按游标取牌 → 爆牌则走结算路径
- [x] 3.5 实现 `blackjack_double`：校验未曾要牌 + 另有一份基础注额余额（余额不足须拒绝，防止积分为负）→ 追加扣分 → 发一张 → 自动进入结算路径
- [x] 3.6 实现共用结算路径 `_settle_blackjack_hand`：幂等闸门 → 引擎推进庄家补牌 → 按手牌上的参数快照算 `rake` 与 `payout`（`round(x, 2)`，禁止 int 截断）→ 计入积分 → 锁 `glory_fund` 并注入 → 写回终态与庄家牌面
- [x] 3.7 实现 `get_current_blackjack_hand`（取该用户非终态手牌）与 `get_user_blackjack_stats`（手数、净积分变动、单手最大赢利）
- [x] 3.8 在 21 点结算处与 `db.py:2213` 大预言家结算处补注释，说明荣耀奖池的历史命名与跨活动共用（设计决策 8）
- [x] 3.9 将荣耀奖池由整数字符串改为小数存储（设计决策 8）：大预言家结算处的读取 `int(cfg.config_value)` → `float(...)`、余额累加与可用额判定改浮点并统一 `round(x, 2)`、写回 `str(int(...))` → `str(round(float(...), 2))`；确认既有整数字符串余额可被正常读入，无需数据迁移

## 4. 路由与 Schema

- [x] 4.1 新建 `src/app/webapp/schemas/blackjack.py`：请求模型；响应模型显式列字段，`deck_seed` 与 `next_card_index` 不出现在模型中，`dealer_cards` 在玩家回合由构造入口裁剪为仅首张（设计决策 10）
- [x] 4.2 新建 `src/app/webapp/routers/activities/blackjack.py`：`POST /deal`、`POST /{hand_id}/hit`、`POST /{hand_id}/stand`、`POST /{hand_id}/double`、`GET /current`、`GET /user-stats`，全部带 `@require_telegram_auth`
- [x] 4.3 加 `GET /config`（用户可读的公开参数：注额档、门槛、赔率、抽水口径，供规则说明渲染）与 `PUT /config`（`check_admin_permission`，含停用开关）
- [x] 4.4 ValueError → HTTPException 的中文消息映射，照 `treasure.py:467` 的写法：积分不足、低于门槛、注额非法、已有进行中手牌、手牌已结束、加倍余额不足、操作过于频繁、活动未开放
- [x] 4.5 在 webapp 应用中注册该路由（照既有四个活动路由的注册处）
- [x] 4.6 发牌成功后安排超时任务：`Scheduler().add_async_job(trigger="date", jobstore="sqlalchemy", id=f"blackjack_timeout_{hand_id}", replace_existing=True)`；任务体调用结算路径，异常仅记日志不抛出
- [x] 4.7 `background_tasks.add_task(check_and_award_game_king_badge, ...)` 挂在结算之后，照 `treasure.py:452`

## 5. 榜单与勋章

- [x] 5.1 `db.py` 新增 `get_blackjack_net_credits_rank`（按累计净积分变动排序，口径照 `get_wheel_credits_rank`，`db.py:2724`）与 `get_blackjack_max_win_rank`（按单手最高净赢利排序）
- [x] 5.2 `src/app/webapp/routers/rankings.py` 新增 `get_blackjack_game_rankings` 端点，与既有三个 `get_*_game_rankings`（`rankings.py:254` 起）并列
- [x] 5.3 `db_func.py` 的 `check_and_award_game_king_badge`（`db_func.py:2683`）新增 `BLACKJACK_HAND_THRESHOLD = 2000` 及对应查询分支，单用户与批量两条路径都要覆盖；同步更新勋章描述文案

## 6. 前端

- [x] 6.1 `webapp-frontend/src/api/index.js` 新增各接口的调用函数
- [x] 6.2 新建 `BlackjackDialog.vue`：牌桌布局、注额档位选择、要牌/停牌/加倍按钮（按状态与余额启用禁用）、庄家暗牌占位、结算结果展示
- [x] 6.3 在牌桌内加规则说明入口（tips 图标 → 弹层）：动作与限制、天胡与普通胜赔率、庄家补牌规则、抽水口径（须含「仅对赢利计取，输与平局不抽」）、注额档与门槛；赔率与注额等数字从 `GET /config` 取值渲染，不硬编码
- [x] 6.4 进入活动时调 `GET /current`，若有进行中手牌则直接恢复牌桌，而非展示下注界面
- [x] 6.5 `views/Activities.vue`：`black-jack` 项 `enabled: true`、移动到 `lucky-wheel` 之后、图标由 `mdi-gift` 改为 `mdi-cards-playing`、`requireCredits` 改 30、参与成本改为注额区间展示（需相应调整卡片上 `costCredits` 的渲染分支）
- [x] 6.6 新建 `BlackjackAdminPanel.vue`：全部配置项 + 停用开关，照 `WheelAdminPanel.vue` 的组织方式；挂入管理页
- [x] 6.7 `views/Rankings.vue` 游戏榜新增 21 点分区，复用 `RankingStateBlock` 的加载/失败/无数据状态

## 7. 验证与收尾

- [x] 7.1 `ruff check src/` 与 `ruff format src/` 通过；`webapp-frontend/` 下 `npm run lint` 通过
- [x] 7.2 逐条走查 spec 的场景：门槛边界（积分 30 押 30 归零）、加倍余额不足被拒、要牌后不可加倍、软 17 停牌、双方天胡平局、加倍平局返还两份注额、平局与判负零抽水、小额注抽水不被抹零
- [x] 7.3 并发与幂等：并发双开发牌只成立一手、重复提交停牌只结算一次、超时任务与用户停牌撞车只结算一次
- [x] 7.4 超时兜底：手牌超时后被自动停牌结算；模拟调度任务丢失，确认下次发牌时惰性结算旧手牌
- [x] 7.5 信息隐藏：玩家回合的响应中不含庄家暗牌；任何状态下响应均不含 `deck_seed`
- [x] 7.6 经济核对：抽水按 6:4 拆分，荣耀奖池余额增量与预期一致；确认大预言家结算仍正常读写同一余额
- [x] 7.7 前端联调：活动列表顺序与图标、规则说明数字与后端配置一致、榜单展示、管理面板改配置后新手牌生效而进行中手牌按快照结算
- [x] 7.8 清理验证过程中产生的临时数据与脚本

## 8. Code review 修复

代码审查发现的缺陷，均在本次新增代码中，已逐项修复并验证：

- [x] 8.1 抢占闸门提到所有写操作之前（`_claim_blackjack_hand`）：原实现把 CAS 放在结算函数内部，导致加倍会先扣一份注额、要牌会先写入新牌，而 CAS 失败后事务仍提交这些写入——造成扣了钱不赔付、牌面与 outcome 不一致
- [x] 8.2 修正 `create_blackjack_hand` 的加锁顺序倒置（statistics → hand），与其余路径的 hand → statistics 构成 ABBA 死锁；改为只锁 statistics、手牌只读
- [x] 8.3 惰性清理独立成事务 `sweep_timed_out_blackjack_hands`：原先寄生在发牌事务里，发牌被后续校验拒绝时会连带回滚已完成的结算、丢弃用户赔付
- [x] 8.4 超时任务补 `misfire_grace_time=None`、新增启动恢复 `restore_blackjack_timeouts()` 与每 10 分钟的全量兜底任务；原实现会因调度器默认 60 秒的 misfire 窗口在重启后永久丢弃任务，手牌带着押注长期悬挂
- [x] 8.5 `hand_timeout_minutes` 加入手牌参数快照（模型 + 迁移 + 约束），与其余四个快照参数口径一致；原先读实时配置，管理员调低时限会强制结算进行中的手牌，与管理面板的说明文案矛盾
- [x] 8.6 `already_settled` 时不再把 `settled` 置为 True，避免路由误报成功并触发勋章任务
- [x] 8.7 `GET /current` 改为只读：清理委托给独立事务的 sweep，读路径不再改积分、动奖池
- [x] 8.8 勋章检查复用 `count_blackjack_hands` 并以 `engine.TERMINAL_STATUSES` 为终态集合的单一来源，消除死代码与三处重复的状态字面量
- [x] 8.9 管理页 `refreshBlackjackPanel` 改为 await 面板加载后再按结果提示，不再在加载失败时误报「配置已刷新」

## 9. 实测反馈修复

- [x] 9.1 牌桌回放庄家的补牌过程：后端一次性返回补完的最终牌面，原先前端整组渲染，庄家从一张明牌瞬间跳到最终结果，玩家看不到他是怎么打的。改为按真实牌桌顺序回放——亮暗牌 → 逐张补牌（同步显示当前点数与「继续要牌／停牌／爆牌」）→ 出结果，并提供跳过入口；纯前端改动，暗牌公开时机仍符合 spec「隐藏信息」的约定

## 10. 吸引力设计（决策反馈 / 免抽水 / 幸运奖池 / 榜单改口径）

### 10.1 规则引擎扩展

- [x] 10.1.1 `blackjack_engine.py` 新增基本策略表与 `recommend_action(player_cards, dealer_upcard, can_double, hits_soft_17)`：标准「不分牌、不投降、不保险」策略，S17 与 H17 两套（后者只有少数几格不同）；加倍不可用时自动回退为要牌或停牌
- [x] 10.1.2 逐格核对策略表，并对代表性局面写明确用例：16 vs 10 要牌、A7 vs 3 加倍、A7 vs 9 要牌、11 vs A（S17 要牌 / H17 加倍）、12 vs 4 停牌、软手三张时的加倍回退
- [x] 10.1.3 新增奖池触发牌型判定：`is_suited_blackjack`（初始两张为 A 与同花色的 10/J/Q/K）与 `is_triple_seven`（恰三张 7 且合计 21）；验证两者互斥、非同花天胡不触发

### 10.2 数据模型与迁移

- [x] 10.2.1 `BlackjackHand` 新增五列：`jackpot_won`（FLOAT NULL）、`decisions_total`、`decisions_correct`（INTEGER 默认 0）、`rake_waived`（SMALLINT 0/1）、快照列 `rake_jackpot_bp` 取代 `rake_glory_bp`
- [x] 10.2.2 补 CheckConstraint：`decisions_correct >= 0`、`decisions_correct <= decisions_total`、`rake_waived IN (0,1)`、`jackpot_won IS NULL OR jackpot_won >= 0`
- [x] 10.2.3 **新增**一个 Alembic 迁移（`down_revision` 指向 `x4y5z6a7b8c9`），SHALL NOT 改写它——21 点已部署至真实环境，该建表迁移已执行，表结构须用 ALTER 而非重建；因需 ADD CONSTRAINT，用 `op.batch_alter_table`（SQLite 整表重建，PostgreSQL 透传）；验证 upgrade / downgrade 双向、约束与索引不丢、存量手牌行拿到新列的默认值

### 10.3 配置与奖池

- [x] 10.3.1 默认配置新增：`rake_jackpot_bp=120`（取代 `rake_glory_bp`）、`jackpot_suited_bj_pct=10`、`jackpot_enabled=true`、`free_hands_per_day=1`、`rank_min_hands=100`、`badge_min_hands=2000`、`badge_min_accuracy=80`
- [x] 10.3.2 实现 `get_blackjack_jackpot` / `_add_to_jackpot_fund` / `_pay_from_jackpot_fund`，沿用荣耀奖池已验证的 CAS + SAVEPOINT 首次插入模式；余额以小数字符串存储
- [x] 10.3.3 管理面板支持手动注入奖池种子余额（唯一会增发积分的路径，须为管理员显式操作）

### 10.4 结算路径接入

- [x] 10.4.1 `create_blackjack_hand` 判定当日首手（`created_at_ms >= 当日零点`，按 `settings.TZ`），命中则快照 `rake_bp_on_profit=0` 且 `rake_waived=1`——结算逻辑不加任何分支
- [x] 10.4.2 `_settle_blackjack_hand` 接入奖池：先判触发牌型并派彩、后累积本手抽水（同一手牌不应吃到自己刚交的抽水）；`jackpot_won` 单独入账，不并入 `payout_credits`；派彩不计抽水且独立于胜负
- [x] 10.4.3 要牌 / 停牌 / 加倍三个入口在执行动作**前**调用 `recommend_action` 评判，累加 `decisions_total` 与 `decisions_correct`；评判依据手牌快照的 `dealer_hits_soft_17`
- [x] 10.4.4 移除 21 点对荣耀奖池的注入（`_add_to_glory_fund` 调用），确认大预言家结算完全不受影响

### 10.5 榜单与勋章

- [x] 10.5.1 `db.py` 新增 `get_blackjack_accuracy_rank`（决策准确率，设最低手数门槛）与 `get_blackjack_win_rate_rank`（胜率，同门槛）；`get_blackjack_max_win_rank` 改为排除 `jackpot_won`
- [x] 10.5.2 移除 `get_blackjack_net_credits_rank` 及其端点字段
- [x] 10.5.3 `rankings.py` 的 21 点端点改为返回三个榜单
- [x] 10.5.4 `db_func.py` 勋章条件改为手数 + 准确率双条件，单用户与批量两条路径都要覆盖；同步更新勋章描述文案
- [x] 10.5.5 `get_user_blackjack_stats` 增加决策准确率与奖池累计中奖额

### 10.6 接口与前端

- [x] 10.6.1 `GET /config` 增加奖池余额、奖池触发规则与派彩比例、每日免抽水手数；手牌响应增加 `rake_waived`、`jackpot_won`、本手决策评判结果
- [x] 10.6.2 牌桌顶部常驻展示幸运奖池余额；中奖时单独高亮，与本手赔付分开呈现
- [x] 10.6.3 结算后展示决策反馈：逐次列出「你的决策 / 建议决策」，并显示本手与累计准确率
- [x] 10.6.4 免抽水手在下注界面与牌桌上标示
- [x] 10.6.5 规则说明补充：每日首手免抽水、幸运奖池的两种触发牌型与派彩比例、决策反馈的性质（仅建议不强制）；数字仍全部取自 `GET /config`
- [x] 10.6.6 `Rankings.vue` 的 21 点分区改为三个榜单，移除净积分变动榜
- [x] 10.6.7 管理面板补入新配置项与奖池种子注入入口

### 10.7 验证

- [x] 10.7.1 基本策略表逐格核对；决策准确率在固定牌局下可复现
- [x] 10.7.2 免抽水：当日首手抽水为 0 且入账正确、当日第二手正常抽水、跨日重置；管理员把全局抽水调为 0 时 `rake_waived` 仍能区分两者
- [x] 10.7.3 奖池：同花天胡派 10%、三张 7 派全额、两者互斥、非同花天胡不触发、派彩独立于胜负、余额不足不派且不为负、并发派彩不超发
- [x] 10.7.4 奖池账目守恒：奖池增量 = Σ 抽水 × 奖池分成 − Σ 派彩；确认无凭空增发
- [x] 10.7.5 榜单：准确率榜与胜率榜的门槛过滤、单手最大赢利榜排除奖池派彩
- [x] 10.7.6 勋章双条件：手数够但准确率不足不授予、两者都够才授予、批量路径同样覆盖
- [x] 10.7.7 确认大预言家的荣耀奖池余额不再因 21 点变动
- [x] 10.7.8 `ruff check` / `ruff format` 与前端 `npm run lint` / `npm run build` 通过；清理临时验证数据

## 11. 幸运奖池中奖的群组播报

用游标轮询而非在结算处挂钩子：派彩散落在发牌、停牌、加倍、超时任务、定时兜底与
惰性清理六条路径上，逐条挂钩既啰嗦又极易漏播——而漏掉的恰恰会是最该播报的那次。

- [x] 11.1 `db.py` 增加播报游标常量与 `claim_unannounced_jackpot_wins()`：按主键范围取 `jackpot_won > 0` 的新手牌，游标推进到「最小进行中手牌 ID − 1」，首次运行只初始化游标不回溯历史
- [x] 11.2 配置增加 `jackpot_notify_enabled`（默认开），并接入 `BlackjackAdminConfig` 与管理面板
- [x] 11.3 路由层实现 `notify_blackjack_jackpot_wins_job()`：取 `TG_GROUP_ID`，按牌型渲染文案（含玩家、牌面、派彩金额、当前奖池余额），未配置群组时照常认领以免日后倾泻
- [x] 11.4 `main.py` 注册每分钟的播报任务，`max_instances=1`（游标的并发安全依赖于此）
- [x] 11.5 验证：六条结算路径产生的派彩均被播报且各仅一次、首次启用不回溯、未配置群组不积压、关闭开关后不播报且不影响派彩、游标不越过进行中的手牌
