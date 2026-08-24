## 1. 数据模型与迁移

- [x] 1.1 `src/app/models/models.py` 的 `BlackjackHand` 新增参数快照列 `surrender_enabled`（`SMALLINT`, `nullable=False`, `server_default="0"`），置于既有五列快照之后，注释说明「发牌时投降是否可用；存量手牌为 0，故其决策评判继续走不含投降的策略表」
- [x] 1.2 补 `CheckConstraint("surrender_enabled IN (0,1)", name="ck_blackjack_hand_surrender_enabled")`，与 `ck_blackjack_hand_doubled` 同一写法
- [x] 1.3 新建 Alembic 迁移，`down_revision = "y5z6a7b8c9d0"`，用 `batch_alter_table` 加列并建约束（SQLite 不支持 ADD CONSTRAINT，须整表重建；理由照抄 `y5z6a7b8c9d0` 的模块 docstring）；`downgrade()` 对称删除
- [x] 1.4 `alembic upgrade head` 在 SQLite 与 PostgreSQL 各验证一次，确认存量手牌的 `surrender_enabled` 全为 0、既有索引与外键未在重建中丢失

## 2. 规则引擎（纯函数，无 IO）

- [x] 2.1 `blackjack_engine.py` 新增 `ACTION_SURRENDER = "surrender"` 与 `OUTCOME_SURRENDER = "surrender"`
- [x] 2.2 实现 `can_surrender(cards, status, doubled)`：手中恰两张 + 状态为玩家回合 + 未加倍，三者同时满足才为真；与 `can_double()` 并列放置
- [x] 2.3 `_hard_strategy()` 新增投降记号 `_R_ELSE_HIT = "RH"`（硬 16 对 9/10/11、硬 15 对 10、H17 下硬 15 对 11）与 `_R_ELSE_STAND = "Rs"`（仅 H17 下硬 17 对 11——该格不能投降时应停牌而非要牌，否则存量手牌的评判口径会漂移）；顺序上须先于既有的 `total >= 17` 停牌与 13–16 停牌/要牌判断，否则会被提前返回截断
- [x] 2.4 `recommend_action()` 新增 `can_surrender` 参数（默认 `False`，与 `hits_soft_17` 同样的默认策略），并把 `"RH"` / `"Rs"` 按 `can_surrender` 分别落到投降或要牌 / 停牌；补充 docstring 说明该参数须取自手牌快照而非当前配置
- [x] 2.5 逐格核对策略表：投降开关关闭时，硬 16 对 10 仍建议要牌（spec 场景「投降开关关闭时的建议回退」）；开启时建议投降（spec 场景「决策与建议不符」）
- [x] 2.6 确认 `resolve()` 未被改动——投降不经胜负判定（设计决策 4）

## 3. 配置与 DB 层

- [x] 3.1 `db.py` 默认配置新增 `surrender_enabled: True`，注释注明返还比例固定为二分之一、不设配置项及其理由（设计决策 1）
- [x] 3.2 `create_blackjack_hand()` 把当前 `surrender_enabled` 写入手牌快照，与既有五列快照同一处
- [x] 3.3 实现 `blackjack_surrender(tg_id, hand_id)`：照 `blackjack_stand()` 的抢占模式——锁手牌行 → 幂等闸门（终态直接返回既有结果）→ 校验状态为玩家回合、恰两张牌、未加倍 → 校验该手牌快照的 `surrender_enabled` 为真 → 计入 `bet_credits * 0.5` → 写 `outcome="surrender"`、`payout_credits=bet_credits*0.5`、`rake_credits=0`、`jackpot_won` 保持 NULL → 置终态。不推进庄家补牌，不触碰奖池
- [x] 3.4 投降路径接入决策评判：调用既有的 `_capture_decision_context()` + 评判函数，把投降本身作为一次决策计入 `decisions_total` / `decisions_correct`
- [x] 3.5 评判入口传入 `can_surrender`：值取自**手牌快照**的 `surrender_enabled`，不读当前配置（设计决策 2）；要牌/停牌/加倍三条既有路径同样要传，否则开关打开后这三个动作的评判仍会漏掉投降建议
- [x] 3.6 `get_user_blackjack_stats()` 新增 `surrender_hands` 计数（`outcome == "surrender"` 的已结束手数）
- [x] 3.7 确认榜单侧零改动：`_blackjack_rank_rows()` 的 `win_flag` 不含 `"surrender"`（分子自动排除）、`COUNT(id)` 过滤 `TERMINAL_STATUSES`（分母自动含入）、`get_blackjack_max_win_rank()` 的 `max_win > 0` 自动滤掉投降手（设计决策 6）——只需核对，不改代码

## 4. API 层

- [x] 4.1 `schemas/blackjack.py`：`BlackjackAdminConfig` 与 `BlackjackConfigUpdateRequest` 新增 `surrender_enabled`；`BlackjackPublicConfigResponse` 新增同名字段供前端决定是否渲染按钮；`BlackjackUserStatsResponse` 新增 `surrender_hands`
- [x] 4.2 `BlackjackHandResponse.from_hand()` 暴露 `can_surrender`，由手牌快照与当前牌面共同判定，使前端不必自行推导可用性（与 `can_double` 一致的做法）
- [x] 4.3 新增 `POST /blackjack/{hand_id}/surrender` 路由，照 `stand` 的形状：`require_telegram_auth` → 调 DB 层 → `background_tasks` 触发游戏王勋章检查 → `_build_action_response(result, tg_id, "已投降")`
- [x] 4.4 `_raise_for_value_error()` 新增三条翻译：`"surrender disabled"` → 「投降当前未开放」、`"cannot surrender after hit"` → 「已要牌，不能再投降」、`"cannot surrender after double"` → 「已加倍，不能再投降」
- [x] 4.5 `get_public_config()` 返回 `surrender_enabled`

## 5. 前端

- [x] 5.1 `blackjackService.js` 新增 `surrenderBlackjackHand(handId)`
- [x] 5.2 `BlackjackDialog.vue` 牌桌新增投降按钮，仅在响应的 `can_surrender` 为真时渲染；与要牌/停牌/加倍同等形态并列（原计划做成低调的文字按钮，实际观感不佳，故改为一致；颜色取 `blue-grey-darken-1`，避开停牌已占用的 `grey-darken-1`）。误点的防护改由 5.3 的二次确认单独承担
- [x] 5.3 投降按钮加二次确认——本活动唯一点下去即无任何后续操作的动作（Risks 一节）
- [x] 5.4 结算展示支持 `outcome === "surrender"`：文案为「已投降，返还一半注额」，不显示胜负标识
- [x] 5.5 规则说明补充投降条目（仅在 `surrender_enabled` 为真时展示）：仅初始两张牌时可用、返还一半基础注额（spec 场景「投降规则对用户可见」）
- [x] 5.6 `BlackjackAdminPanel.vue` 在「规则」区新增投降开关，hint 注明「关闭后仅影响此后发出的手牌，进行中的手牌仍可投降」（Risks 一节的最后一条）
- [x] 5.7 `UserInfo.vue` 的 21 点区块新增「投降手数」，与胜/负/平并列

## 6. 验证

- [x] 6.1 逐条走查 spec 增量的新增场景：投降返还一半、要牌后不可投降、加倍后不可投降、开关关闭时拒绝、投降直接结算不经庄家回合、投降零抽水、持一对 7 投降不触发奖池、投降计入胜率分母、关闭开关不影响进行中手牌
- [x] 6.2 存量数据回归：取若干条上线前的历史手牌，确认其 `decisions_correct` 重算后与库中值逐位一致（快照隔离生效，设计决策 2）
- [x] 6.3 幂等验证：对同一手牌连发两次投降请求，确认仅入账一次；投降后等待超时任务触发，确认命中 `already_settled` 分支且不重复赔付
- [x] 6.4 暗牌公开验证：投降后的响应包含庄家全部牌面，且不含 `deck_seed`（设计决策 5 与 spec「隐藏信息」）
- [x] 6.5 回滚验证：关闭开关后，新发手牌无投降入口、服务端拒绝投降请求，已投降的历史手牌统计不受影响
