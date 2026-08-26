## 1. 隔离过滤先行（此时尚无赛内手牌，全部为 no-op，可零风险验证口径不变）

- [x] 1.1 在 `db.py` `_blackjack_rank_rows` 的聚合上加 `BlackjackHand.tournament_id.is_(None)`，覆盖准确率榜与胜率榜
- [x] 1.2 在 `db.py` `get_blackjack_max_win_rank` 的聚合上加同一过滤
- [x] 1.3 在 `db.py` `_count_blackjack_hands_today` 上加同一过滤（每日首手免抽水的判定）
- [x] 1.4 在 `db.py` `get_user_blackjack_stats` 上加同一过滤
- [x] 1.5 在 `db.py` `get_blackjack_admin_stats` 上加同一过滤（该函数原本无 WHERE，对全表聚合；赛内 `bet_credits` 是筹码，混入会污染 `total_wagered` 与 `net_credits` 而非仅展示失真）
- [x] 1.6 在 `db_func.py` 游戏王勋章的 21 点子查询上加同一过滤
- [x] 1.7 在三处**刻意不过滤**的位置就地写下理由，防止日后被「补全」：`create_blackjack_hand` 的「同时只有一手」与发牌速率下限，以及 `list_active_blackjack_hands`（赛内手牌同样需要重启后重建超时任务）
- [x] 1.8 上线并人工核对：现金局的准确率榜、胜率榜、单手最大赢利榜、个人统计与勋章判定结果逐位不变

## 2. 前端牌桌抽取（纯重构，不含新功能）

- [x] 2.1 从 `BlackjackDialog.vue` 抽出 `components/BlackjackTable.vue`，以 props 承接两侧差异：`betMode`（`tiers` / `range`）、`balance`、`currencyLabel`、`showStrategyHint`、`showRake`、`showJackpot`
- [x] 2.2 牌桌动作以 emit 上抛（deal / hit / stand / double / surrender / new-hand），子组件不直接调用接口；回放状态经 `reveal-change` 上抛（`$refs` 非响应式，父组件的 computed 读子组件状态不会重新求值）
- [x] 2.3 改造 `BlackjackDialog.vue` 复用该子组件，传入现金局的一组 props
- [x] 2.4 验证现金局无回归：注额三档、加倍、投降、决策反馈、免抽水标示、奖池展示、规则说明、超时后重新进入（静态验证：eslint 通过、production build 通过、抽出前后标识符与用户可见文案逐项比对无遗漏）

## 3. 数据模型与迁移

- [x] 3.1 在 `models.py` 新增 `BlackjackTournament` 模型：状态、报名费、起始筹码、总手数、注额上下限、人数上下限、`entrant_count`、抽水比率、`seeded_prize_credits`、`payout_structure`、四列参数快照、两个截止时点、`reminder_sent_at`、时间戳；按设计决策 10 建 CHECK 约束
- [x] 3.2 新增 `BlackjackTournamentEntry` 模型：`chips`（Integer）、`hands_played`、状态、`final_rank`、`prize_credits`、`registered_at_ms`，`UNIQUE(tournament_id, tg_id)`，两个外键与索引
- [x] 3.3 Alembic 迁移：建两张表，并为 `blackjack_hand.tournament_id` 加 `(tournament_id, tg_id)` 索引（列已存在，不改既有表结构）
- [x] 3.4 在 `SystemConfig` 的 docstring 与 `DEFAULT_BLACKJACK_CONFIG` 补 `tournament_notify_enabled` 开关及赛事默认参数

## 4. 赛事生命周期与报名

- [x] 4.1 `create_blackjack_tournament()`：管理员创建，校验参数区间（`min_bet <= max_bet`、`min_entrants <= max_entrants`、注额为 10 的倍数、两个截止时点先后顺序），快照庄家规则/天胡赔率/投降开关/单手时限
- [x] 4.2 `update_blackjack_tournament()`：仅允许修改处于报名中的赛事，进入进行中后一律拒绝
- [x] 4.3 `register_blackjack_tournament()`：同一事务内完成名额 CAS（`UPDATE ... SET entrant_count = entrant_count + 1 WHERE status = 1 AND entrant_count < max_entrants`）与 entry 插入；撞 `UNIQUE(tournament_id, tg_id)` 时整个事务回滚，不做补偿性减一
- [x] 4.4 报名扣费：按锁序 `tournament → statistics`，对 `Statistics` 取 `with_for_update()` 后扣报名费，积分不足则拒绝
- [x] 4.5 满员即开：报名成功后若 `entrant_count` 达到上限，以 CAS `1 → 2` 尝试开赛，抢到者负责触发开赛通知
- [x] 4.6 `cancel_blackjack_tournament()`：CAS `1 → 4`，逐个报名者全额退款（每人一个 `Statistics` 行锁），返回退款收件人列表；进行中的赛事一律拒绝取消
- [x] 4.7 赛事与报名的查询方法：大厅列表、赛事详情、我的报名、进行中的全场筹码排名、已结算的最终名次与派奖结果

## 5. 赛内结算适配层

- [x] 5.1 `create_blackjack_tournament_hand()`：校验赛事处于进行中且 `now < play_deadline_ms`、报名处于进行中、注额在区间内且为 10 的倍数且不超过当前筹码；扣筹码、生成 `secrets` 种子定序、发初始牌、天胡则直接结算
- [x] 5.2 沿用既有的「同时只有一手」与发牌速率校验（跨现金局与赛内共用，不加 `tournament_id` 过滤）；赛内发牌**额外锁一行自己不修改的 `Statistics`** 作为该不变量的串行化点，否则并发的「现金局发牌 + 赛内发牌」会各持互不相干的锁而双双通过检查
- [x] 5.3 `_settle_blackjack_tournament_hand()`：与 `_settle_blackjack_hand` 同构复刻——CAS 闸门置于任何写操作之前、`session.flush()` 时机一致；锁 `entry` 替代 `Statistics`；砍掉抽水、奖池派彩与注入、决策计数落库；`chips += floor(return_multiplier × bet)`
- [x] 5.4 结算后推进 `hands_played`，并判定报名终态：打满总手数记已打完，筹码低于最小注记已淘汰
- [x] 5.5 赛内要牌/停牌/加倍/投降四个动作方法：复用引擎的合法性判定与快照的投降开关；加倍校验筹码是否另有一份注额；**不调用 `_record_blackjack_decision`**，`decisions_total` / `decisions_correct` 保持 0
- [x] 5.6 把 `settle_blackjack_hand_by_timeout`、`restore_blackjack_timeouts` 与 `sweep_timed_out_blackjack_hands` 三条入口的适配层选择收敛为**单个分派函数** `_settle_blackjack_hand_dispatch`（按 `hand.tournament_id` 是否为空选择）；并给 `_lock_blackjack_hand` 加 `cash_only` 参数，与 `_lock_tournament_hand` 构成**双向隔离**——两侧 id 共用同一张表，现金局端点若不拦赛内手牌，用户提交赛内 id 即可让筹码注额算出的赔付进入自己的积分
- [x] 5.7 `force_settle_tournament_hands(tournament_id)`：结算该赛事全部非终态手牌，**每手牌一个独立事务**，不看各手牌自己的 15 分钟时限，口径等同玩家停牌

## 6. 赛事推进的 tick 任务

- [x] 6.1 `blackjack_tournament_tick_job()`：每分钟运行，依次处理报名截止、完赛提醒、完赛结算三个阶段，每阶段以 CAS 门控，单个赛事失败只记日志不影响其余
- [x] 6.2 阶段一（报名截止）：`status=1 且 register_deadline_ms <= now` → 人数达标则 CAS `1 → 2` 并通知开赛，否则 CAS `1 → 4` 并退款通知
- [x] 6.3 阶段二（完赛提醒）：`status=2 且 play_deadline_ms - remind_lead <= now < play_deadline_ms 且 reminder_sent_at IS NULL` → 取未打满且未淘汰的报名者，写 `reminder_sent_at` 作为去重标记
- [x] 6.4 阶段三（完赛结算）：`status=2 且 play_deadline_ms <= now` → 先调 `force_settle_tournament_hands` 清场，再 CAS `2 → 3` 后排名派奖
- [x] 6.5 在 `main.py` 注册该 tick 任务；确认**不需要**重启恢复函数（周期任务天然免疫任务丢失，与手牌超时的 date 任务不同）

## 7. 排名、派奖与冠军勋章

- [x] 7.1 排名：仅取具备派奖资格的报名（已打完或已淘汰），按 `chips` 降序、`registered_at_ms` 升序决胜，写入 `final_rank`
- [x] 7.2 奖池推导：`entrant_count × buy_in_credits + seeded_prize_credits`，减去按 `rake_bp` 计取并销毁的抽水；**不设累加列**
- [x] 7.3 档位截断与归一：具备资格者少于档位数时截断至该数量并重新归一至 100%，确保奖池无残留
- [x] 7.4 派奖入账：逐个获奖者取 `Statistics` 行锁后计入积分，写 `prize_credits`；未获奖者写 0
- [x] 7.5 `award_or_renew_badge()`：新增 DB 方法，首次授予则插入，已持有则 `expires_at = min(max(expires_at, now) + valid_days, now + 上限)`；不改既有授予方法以免影响 `game_king` 与 `supreme_contributor`
- [x] 7.6 冠军勋章定义：照 `game_king` 形状缺失时自动创建（`credits_cost=0`、`is_enabled=0`、`bonus_percentage=0.05`、`valid_days=30`），上限常量与既有阈值常量并列
- [x] 7.7 结算后向第一名授予/续期勋章；赛事取消时不授予

## 8. 通知

- [x] 8.1 `_format_*` 系列渲染函数：创建播报、开赛私聊（含需完成手数与完赛截止时点）、完赛提醒（含剩余手数与截止时点）、赛果私聊与群播报、取消退款私聊（含退款金额）
- [x] 8.2 全部通知在**事务提交之后**发送；DB 方法只返回收件人列表与渲染所需数据，不在事务内发送
- [x] 8.3 开赛通知走 `BackgroundTasks`（可能由第 N 个报名者的 HTTP 请求触发）；tick 任务触发的三处直接 await
- [x] 8.4 逐收件人 `try/except`，单个失败不中断同批其余；失败只记日志、不重试
- [x] 8.5 群播报复用 `_get_group_chat_id()`；`tournament_notify_enabled` 关闭或未配置群组时**照常推进 `reminder_sent_at` 与各状态 CAS**，仅跳过发送
- [x] 8.6 核对五处通知各自恰好发出一次：创建、开赛、完赛提醒、赛果、取消退款

## 9. 路由与响应模型

- [x] 9.1 `schemas/blackjack_tournament.py`：请求响应模型；赛内手牌的响应模型**显式列字段**，`deck_seed` 与 `next_card_index` 不在模型里，玩家回合时 `dealer_cards` 由构造入口裁剪为仅首张
- [x] 9.2 `routers/activities/blackjack_tournament.py`：大厅列表、赛事详情、报名、我的报名与筹码、全场排名、赛果
- [x] 9.3 赛内牌桌端点：发牌、要牌、停牌、加倍、投降、当前手牌
- [x] 9.4 管理端端点：创建、修改、取消、注入补贴、一致性校验（比对 `entrant_count` 与 `COUNT(entry)`）
- [x] 9.5 `ValueError` 到中文提示的翻译，覆盖新增的拒绝原因（未开赛/已结束/已满员/已报名/注额非法/筹码不足/已打满/已淘汰/赛事已停用）
- [x] 9.6 在 `webapp/__init__.py` 注册路由；服务端停用开关同时拒绝创建赛事与报名

## 10. 前端

- [x] 10.1 `BlackjackTournamentDialog.vue` 赛事大厅：报名中与进行中的赛事列表、报名费、起始筹码、总手数、注额区间、当前人数与上下限、当前奖池、两个截止时点、报名入口
- [x] 10.2 赛内牌桌：复用 `BlackjackTable.vue` 并传入 `betMode=range`、`currencyLabel=筹码`、`showStrategyHint=false`、`showRake=false`、`showJackpot=false`
- [x] 10.3 赛内状态区：当前筹码、已打手数与剩余手数、全场实时排名、已打完/已淘汰的提示
- [x] 10.4 赛果页：最终名次、派奖金额、冠军勋章展示
- [x] 10.5 赛内规则说明：注额区间与 10 倍数约束、淘汰条件、**派奖资格门**、排名与并列口径、奖池档位、赛内不抽水且不触发幸运奖池、赛内无策略提示且不计入决策准确率
- [x] 10.6 `BlackjackTournamentAdminPanel.vue`：创建/修改/取消赛事、注入补贴、一致性校验；面板内说明**频次建议为周赛**及其经济学理由
- [x] 10.7 `Activities.vue` 增加锦标赛入口、`Management.vue` 挂载管理面板、`api/index.js` 与 `services/` 增加接口

## 11. 内测核对（以临时 SQLite 库 + FastAPI TestClient 完成；正式内测赛事待上线后由管理员创建）

- [x] 11.1 创建小规模内测赛事（`min_entrants` 调低），核对报名扣费与并发不超员（并发提交同一赛事的报名）
- [x] 11.2 核对赛内结算：零抽水、不触发幸运奖池（构造同花天胡与三张 7）、赔付作用于筹码、积分余额不变
- [x] 11.3 核对淘汰与完赛判定、资格门（构造一个报名后不打牌的账号，确认其不参与派奖）
- [x] 11.4 核对档位截断归一（构造具备资格者少于档位数的场次）、派奖入账、奖池无残留
- [x] 11.5 核对勋章授予与续期（同一账号连续夺冠两次，确认 `expires_at` 为累加而非重置，且不超上限）
- [x] 11.6 核对完赛截止的两阶段清场：截止时点前留一手在局，确认其被结算后才参与排名
- [x] 11.7 核对并发与幂等：重复提交赛内动作、重复触发结算任务、重复触发取消，确认筹码与积分均只变动一次
- [x] 11.8 核对隔离：只打赛事的账号不出现在准确率榜、胜率榜、单手最大赢利榜与个人统计中，且不获得游戏王勋章

## 12. code review 修复（15 项，均已复核属实）

P0（资金与正确性）

- [x] 12.1 已有报名者后冻结经济参数（决策 15）：白名单只留标题/说明/两个截止时点，`seeded_prize_credits` 只增不减；奖池仍按实收报名费推导
- [x] 12.2 完赛截止闸门下沉到 `_lock_tournament_hand`，覆盖 hit/stand/double/surrender（原先只有发牌端点校验）
- [x] 12.3 `force_settle_tournament_hands` 返回 `{settled, remaining, cleared}`，`remaining` 由结算后重新扫描得出；未清干净则跳过本轮派奖、赛事保持进行中
- [x] 12.4 赛程窗口下限 `max(30 分钟, 总手数 × 1 分钟)`（决策 16）；tick 的两份列表在任务体一次查出，结构上消除「同一 tick 内开赛又结算」

P1（展示与可用性）

- [x] 12.5 排名按**赛事状态**判定是否已结算，不再用「所有行都有 final_rank」；已结算赛事中无资格者两个名次字段都留空
- [x] 12.6 `already_settled` 路径捎回 `chips / hands_played / entry_status / total_hands`；响应模型四字段改为可空，前端只在非空时覆盖
- [x] 12.7 牌桌挂载条件改为 `entry.status === 1 || hand`，决定性一手的庄家牌与结果不再被吞；终态下按钮语义切为「查看赛果」
- [x] 12.8 并发重复报名撞唯一约束时翻成 `ValueError("already registered")`；五个动作端点与四个管理端点补齐兜底 `except Exception`
- [x] 12.9 赛事列表支持 `include_finished`，管理面板据此列出已结算与已取消的赛事，一致性校验重新可达
- [x] 12.10 「至多一手」的拒绝提示指明手牌所在场次（现金局 / 本赛事 / 另一场赛事），不再让用户在过滤掉该手牌的界面里空找

P2（质量与性能）

- [x] 12.11 动作响应的 `total_hands` 由 DB 层捎回，删掉五个端点各自多打的一次赛事查询及其 `None` 崩溃路径
- [x] 12.12 终态判定抽为 `_apply_tournament_entry_terminal_status`，投降不再持有第二份（防口径漂移）
- [x] 12.13 赛内赔付改为 `int(round(x, 2))`，消除二进制浮点导致的少赔 1 筹码
- [x] 12.14 tick 的「进行中」列表只查一次供两个阶段共用；列表触顶记 error 而非静默截断
- [x] 12.15 排名的显示名批量取自单次缓存加载（`get_user_names_from_tg_ids`），不再逐行 pickle 全量反序列化
- [x] 12.16 回归验证：45 项断言全通过（含并发、清场失败、坐等者名次、跨侧阻塞、端点层）；ruff 无新增告警、前端 build 通过

## 13. 赛事名称自动生成（决策 17）

- [x] 13.1 `_generate_tournament_title()` 生成 `21 点锦标赛 · 第 N 期`，N = 已创建赛事总数 + 1；`create_blackjack_tournament` 在标题留空（含全空格）时调用，且复制 params 不污染调用方
- [x] 13.2 `TournamentCreateRequest.title` 改为可选；`TournamentUpdateRequest` 覆写回必填但去掉 `min_length`，让空串落到 DB 层换取中文错误
- [x] 13.3 `tournament title required` 翻译为「赛事名称不能为空」
- [x] 13.4 管理面板：创建模式显示「留空将自动命名为…」提示；编辑模式就地拒绝空标题；创建成功的提示回显最终名称
- [x] 13.5 验证：15 项断言全通过（自动生成/显式命名/期数递增/params 无污染/更新留空被拒/schema 两端/播报含名/错误翻译）

## 14. 冠军勋章图标

- [x] 14.1 补齐 `webapp-frontend/public/badges/blackjack_champion.svg`——`_award_tournament_champion_badge` 自动创建的 badge 行以 `icon_url="/badges/blackjack_champion.svg"` 落库，但该文件从未存在，勋章在中心与个人页都会破图
- [x] 14.2 沿用 `game_king.svg` 的骨架（120×120、圆形金边、装饰四方星、闪烁光点、底部四字）保持系列感；背景改牌桌绿以区分两枚 21 点勋章，主视觉为皇冠 + 杯身刻「21」的奖杯 + 两侧花色
- [x] 14.3 核对三条自动创建路径（`supreme_contributor` / `game_king` / `blackjack_champion`）的 `icon_url` 均有对应文件；构建确认图标进入 `dist/badges/`

## 15. 修正管理面板提示的 emit 形参

- [x] 15.1 `BlackjackTournamentAdminPanel.vue` 的 8 处 `$emit('show-message', ...)` 全部改为位置参数 `(message, type)`——接收方 `Management.vue:3723` 的签名是 `showMessage(message, type)`，传对象会让 `showPopup({ message })` 收到对象并渲染成 `[object Object]`，该面板每一条提示（创建/更新/取消/校验/加载失败）都受影响
- [x] 15.2 核对全项目无同类传参：`Activities.vue:832` 的 `showMessage(message, type)` 与 `Management.vue` 同构，其余面板（现金局、转盘、礼包）本就是位置参数
