# Tasks: add-blackjack-retention

## 1. 数据模型与迁移

- [x] 1.1 在 `src/app/models/models.py` 扩展模型：`statistics` 加 `tournament_wallet_credits`、连败计数列、`blackjack_hands_since_freespin`（均默认 0）；`blackjack_hand` 加 `relief_credits`（默认 0）；锦标赛报名表加 `wallet_paid_credits`/`credits_paid_credits`（默认 0）；新建 `blackjack_weekly_cashback`（UNIQUE(tg_id, week_start)）与 `luckywheel_free_spins`（含 `(tg_id, used_at)` 索引）；`wheel_stats` 加 `source`（nullable，默认 'paid'）。验证：`ruff check src/` 通过且 `python3 -c "from app.models import models"` 无报错
- [x] 1.2 生成并审阅 Alembic 迁移（新列全部带默认值、新表空建），执行 `alembic upgrade head` 后用 `alembic check` 确认无残留差异

## 2. 连败救济（后端）

- [x] 2.1 在 `_settle_blackjack_hand`（db.py）CAS 抢占成功后的入账点挂接：按 outcome 更新连败计数（判负 +1 / 判胜归零 / 平局与投降不变），达阈值则补偿「基础注额 × 倍数」入账、计数归零、金额写入 `relief_credits`。验证：新增 pytest 覆盖——连败 8 手触发并归零、救济后重新累计、平局与投降不打断、加倍判负按基础注额、赛内手牌不计数、超时兜底路径同样计数、补偿不抽水
- [x] 2.2 结算 API 响应（现金局各路径：停牌/加倍/爆牌/投降/超时查询）加入救济金额与免费机会获得提示字段。验证：API 测试断言响应字段

## 3. 周损失返还与争霸赛余额（后端）

- [x] 3.1 db 层实现争霸赛余额的读取、返还入账、报名扣减（争霸赛余额优先、拆分记录两列）与取消退款按拆分原路回补；改造锦标赛报名校验为「余额 + 积分 ≥ 报名费」。验证：pytest 覆盖全额余额支付、混合支付、合计不足拒绝、零积分可报名、退款按来源回补、重复报名不重复扣
- [x] 3.2 实现周结算函数：聚合上一完整自然周 `settled_at` 窗口内现金局手牌的 `Σ(payout − 投注 + relief_credits + jackpot_won)`，净亏损且达发放门槛者 INSERT `blackjack_weekly_cashback`（UNIQUE 冲突跳过）→ 争霸赛余额入账 → TG 通知（含净亏损、返还金额、余额用途）。验证：pytest 覆盖净亏损返还、净赢不发、彩池派彩计入、低于门槛不发、任务重跑幂等不漏不重
- [x] 3.3 在调度器注册每周一执行的周结算任务与日界口径（与每日首手免抽水一致的时区处理），并处理「上线后首个完整自然周才开始结算」。验证：任务注册断言 + 手动触发测试

## 4. 免费大转盘机会（后端）

- [x] 4.1 在结算核心同事务挂接手数累加：每结算一手现金局 `blackjack_hands_since_freespin += 1`；`while 进度 ≥ 阈值 and 本周配额有余: 插入 luckywheel_free_spins 行, 进度 −= 阈值`（周配额由表内 `granted_at ≥ 本周一` COUNT 推导，不存计数器）。验证：pytest 覆盖——不分胜负结果均计数（含平局、投降、超时）、周上限后继续累计、管理员调低阈值后存量进度连续转换、赛内不计
- [x] 4.2 改造 `luckywheel.py`：单抽端点先查可用机会（未用、未过期）→ 优先消耗（标记 `used_at`、`cost_override=0` 调 `execute_single_spin`、跳过 `min_credits_required`、`wheel_stats.source='blackjack_free'`）；十连抽不消耗免费机会。验证：pytest 覆盖免费不扣费、优先消耗、十连保留、0 余额可用且负奖品截断
- [x] 4.3 注册每日到期任务：向次日将到期的未用机会持有人发送合并提醒（每用户每日一条）。过期的行**保留作发放台账**（与 wheel_stats 保留全部参与记录同哲学，对账脚本依赖），「作废」由可用性查询的过期过滤实现，无需删除写。验证：测试断言过期机会不可消耗、提醒按用户合并为一条
- [x] 4.4 新增查询 API：可用免费次数（未用未过期）、各机会到期时间、当前累计手数与阈值进度。验证：API 测试断言响应结构
- [x] 4.5 免费机会发放的 Telegram 获得通知（含次数与有效期；复用 per-user 消息通道；发送失败仅记日志，不影响结算）。**实现口径调整**：改用游标轮询任务（每分钟，镜像奖池播报的 JACKPOT_NOTIFY_CURSOR 模式）而非路由层挂钩——发放散落在全部结算路径（含超时清理等不经路由的路径），只有轮询能全覆盖。验证：游标认领逻辑经 pytest 覆盖（认领/初始化不回溯）

## 5. 配置

- [x] 5.1 扩展 blackjack 配置对象（system_config 模式）：`relief_enabled/threshold/multiplier`、`cashback_enabled/rate/min_payout`、`freespins_enabled/hand_threshold/weekly_cap/expiry_days`，含在线调整接口与非管理员拒绝。验证：API 测试覆盖调整生效仅及此后结算、非管理员 403

## 6. 前端（webapp-frontend/）

- [x] 6.1 牌桌页：结算结果展示救济金额；获得免费机会的提示；手数进度（当前累计/阈值，配置关闭时隐藏）。验证：`npm run lint` 通过 + 手动核对展示
- [x] 6.2 转盘页：免费次数角标与到期时间、转盘优先消耗免费机会、余额达上限时的锁定提示。验证：`npm run lint` 通过 + 手动核对
- [x] 6.3 锦标赛页：争霸赛余额展示，报名确认弹窗展示预计支付拆分（余额/积分）。验证：`npm run lint` 通过 + 手动核对
- [x] 6.4 规则说明更新：连败救济、周返还与争霸赛余额用途、免费机会获取条件与有效期；对应机制关闭时不展示。验证：手动核对各开关状态下的说明内容

## 7. 收尾

- [x] 7.1 编写 `scripts/` 对账脚本：连败计数与手数进度 vs `blackjack_hand` 历史回溯比对、按周输出三项让利率（救济总额/返还总额/免费转盘 EV——按线上实际奖池配置计算，若出现翻倍/减半类随余额放大的奖品则在周报中显著警示）供管理端核算预算表。验证：脚本在测试库上运行并输出报表
- [x] 7.2 全量回归：`ruff check src/`、`ruff format --check src/`、`pytest tests/`、`pre-commit run --all-files`、前端 `npm run lint` 全部通过
