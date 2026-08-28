## 1. 进行中报名查询

- [x] 1.1 在 `src/app/databases/db.py` 新增按赛事 id 列表批量查询「仍有 `ENTRY_PLAYING`」的方法，返回这些赛事 id 的集合；空列表返回空集、不打库。用一次 `IN` + `DISTINCT`/`status = ENTRY_PLAYING`，不给 `blackjack_tournament` 加计数列。静态核对：方法签名可被 tick 直接使用，查询条件不含 `play_deadline`
- [x] 1.2 核对 `create_blackjack_tournament_hand` 与 `_lock_tournament_hand` 仍是先判 `status == 进行中`、再判 `now >= play_deadline_ms`，并更新两处注释：两阶段之间不再依赖「截止是与状态无关的固定时间戳」，改为「截止路径靠时点、全员终态路径靠报名终态、CAS 之后靠赛事状态」。`ruff check` 这两处无新增问题

## 2. tick 完赛阶段

- [x] 2.1 改 `src/app/webapp/routers/activities/blackjack_tournament.py` 的 `_tick_play_deadlines`：对本轮进行中赛事一次性查出仍有进行中报名的 id 集合；`now < play_deadline` 且集合中仍有该 id 则跳过，否则走既有清场 → `settle_blackjack_tournament` → 授勋/赛果通知。截止已到的赛事即使仍有 `ENTRY_PLAYING` 也必须进入该链。静态核对：清场与 CAS 仍是同一段代码，无第二套派奖
- [x] 2.2 更新 `_tick_play_deadlines` 的模块注释，写明闸门是「截止已到或已无进行中报名」，并写明全员终态时清场几乎为空仍必须先跑。提醒阶段 `_tick_completion_reminders` 控制流不动。`ruff check src/app/webapp/routers/activities/blackjack_tournament.py`

## 3. 文案

- [x] 3.1 改 `webapp-frontend/src/components/BlackjackTournamentDialog.vue` 里把打满后结算绑到完赛截止的提示（当前为「等待赛事在完赛截止后结算」），改为等待赛事结算；`dealDisabledHint` / `finished-hint` 已是该口径则保持。大厅的完赛截止展示、开赛私聊与完赛提醒里的截止时点不改。`rg` 前端锦标赛组件不再出现「完赛截止后结算」
- [x] 3.2 淘汰出局的提示保持「仍保留派奖资格」，不把截止说成结算条件。管理端不增加「立即完赛」按钮。`webapp-frontend` 下 `npm run lint` 通过（若仅文案变更且 lint 未覆盖该文件，以 `rg` 核对待结算文案为准）
- [x] 3.3 `loadStandings` 把排名接口返回的 `status` 写回 `this.tournament.status`；报名终态且赛事仍为进行中、对话框停在牌桌时轮询排名（约 15s），已结算 / 回大厅 / 关闭时停表。最后一手仍在展示时不得因 `status` 变为已结算而拆掉牌桌。`rg` 确认 `loadStandings` 读取 `res.data.status`

## 4. 回归核对

- [x] 4.1 静态核对资格门未改：`settle_blackjack_tournament` 仍只给已打完/已淘汰排名；未打满且未淘汰者在截止路径上仍无名次、报名费留在奖池。提前完赛路径上这类报名按定义不存在
- [x] 4.2 静态核对发牌/动作拒绝：全员终态后发牌仍因报名终态被拒；赛事 CAS 为已结算后，发牌与动作因 `tournament not running` 被拒（中文「赛事尚未开赛或已结束」），不得只靠 `tournament finished`。手牌热路径仍不调用 `settle_blackjack_tournament`
- [x] 4.3 `ruff check src/app/databases/db.py src/app/webapp/routers/activities/blackjack_tournament.py` 通过
- [x] 4.4 `pytest tests/test_blackjack_tournament_settle.py` 覆盖：全员终态提前结算、仍有 `ENTRY_PLAYING` 不提前、截止已到仍结算、查询失败返回 None 不得当空集、清场 `cleared=False` 不派奖、CAS 失败不重复派奖
