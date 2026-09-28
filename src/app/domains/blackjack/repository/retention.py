"""21 点 repository：连败救济、周返水与游标（由 part_N 机械拆分）。"""

import time
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.db import get_session
from app.core.kv import SystemConfig
from app.core.log import logger
from app.domains.blackjack.models import BlackjackHand, BlackjackWeeklyCashback
from app.domains.credits import repository as credits_repository
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import Statistics
from app.domains.luckywheel import repository as luckywheel_repository
from app.domains.luckywheel.types import FreeSpinProgress


class _BlackjackRepositoryRetention:
    def free_spin_progress(self, tg_id: int) -> FreeSpinProgress:
        """Return live 21-point progress for the luckywheel provider boundary."""
        config = self.get_blackjack_config_dict()
        with get_session() as session:
            stats = session.get(Statistics, int(tg_id))
            hands = int(stats.blackjack_hands_since_freespin or 0) if stats else 0
        enabled = bool(config.get("freespins_enabled", True))
        return FreeSpinProgress(
            enabled=enabled,
            hands_since_freespin=hands,
            hand_threshold=(
                int(config.get("freespins_hand_threshold", 20) or 0) if enabled else 0
            ),
        )

    def apply_blackjack_retention_tx(
        self,
        session,
        hand: BlackjackHand,
        stats: Statistics | None,
        *,
        outcome: str,
        config: dict,
        now_ts: int,
    ) -> dict:
        """Apply retention counters and ledger records in the caller transaction."""
        return self._apply_blackjack_retention(
            session,
            hand,
            stats,
            outcome=outcome,
            config=config,
            now_ts=now_ts,
        )

    def _apply_blackjack_retention(
        self,
        session,
        hand: BlackjackHand,
        stats: Statistics | None,
        *,
        outcome: str,
        config: dict,
        now_ts: int,
    ) -> dict:
        """留存机制的结算钩子：连败救济 + 打满送免费大转盘机会。

        仅现金局调用（赛内手牌走 `_settle_blackjack_tournament_hand`，不经过
        此处）；调用方须已持有该用户 Statistics 的行锁，且已在结算 CAS 抢占
        成功之后——幂等性完全继承自那两道闸门。

        连败计数：判负（含爆牌）+1、判胜（含天胡）归零、平局与投降不变。
        计数达到阈值时立即补偿「该手基础注额 × 倍数」（加倍手牌也按基础
        注额——加倍是玩家的风险选择，救济不应随之翻倍），补偿不抽水，
        金额落 `blackjack_hand.relief_credits` 供周结算与对账使用。触发后
        计数归零，再次救济需重新累计满阈值。

        免费机会：每结算一手现金局计数 +1，达阈值且本周配额有余时发放
        `luckywheel_free_spins` 行并扣除阈值。周配额由「本周一以来已发放
        行数」推导而非计数器——任何计数器都需要周界重置逻辑，而按
        granted_at 过滤天然正确。用 while 而非 if：管理员调低阈值后，
        存量计数可能已是新阈值的数倍，应连续转换直至配额用尽。

        配置从入参读取而非现读库：调用方（含发牌路径）已在开启事务前
        把完整配置读好传入，事务内再调 get_blackjack_config_dict() 会
        另开一个连接，外层正持有行锁时会死锁（见 _settle_blackjack_hand
        的注释）。阈值/开关类参数不随手牌快照——它们是留存机制的运营
        参数而非本手牌的结算口径，调整后对下一手结算立即生效。

        Returns: {relief_credits: float, freespins: [{expires_at_ms: int}]}
        """
        result = {"relief_credits": 0.0, "freespins": []}
        if stats is None:
            # 现金局发牌必先建 Statistics 行（扣注额），此处仅为防御：
            # 行不存在时放弃两项计数，不阻断结算本身
            return result

        tg_id = int(hand.tg_id)
        now_ms = int(now_ts) * 1000

        # ---- 连败救济 ----
        # 计数无条件维护（spec：系统 SHALL 按用户维护现金局手牌的连败计数），
        # 只有发放受 relief_enabled 门控——否则停用期间计数冻结，重启用后
        # 会凭陈旧计数支付玩家当前状态并不匹配的救济
        streak = int(stats.blackjack_lose_streak or 0)
        if outcome in ("lose", "bust"):
            streak += 1
            threshold = int(config.get("relief_threshold", 8) or 0)
            multiplier = float(config.get("relief_multiplier", 1.0) or 0.0)
            if (
                bool(config.get("relief_enabled", True))
                and threshold > 0
                and multiplier > 0
                and streak >= threshold
            ):
                from app.domains.blackjack import rules

                relief = rules.calculate_relief_credits(hand.bet_credits, multiplier)
                credits_repository.add_tx(session, CreditAccount.tg(tg_id), relief)
                session.execute(
                    update(BlackjackHand)
                    .where(BlackjackHand.id == int(hand.id))
                    .values(relief_credits=float(relief))
                )
                session.expire(hand)
                result["relief_credits"] = relief
                streak = 0
            stats.blackjack_lose_streak = streak
        elif outcome in ("win", "blackjack"):
            stats.blackjack_lose_streak = 0
        # push / surrender：计数不变

        # ---- 打满送免费大转盘机会 ----
        if bool(config.get("freespins_enabled", True)):
            # 进度累加只受总开关门控：weekly_cap/expiry_days 临时置 0 只暂停
            # 发放，不得冻结进度（否则恢复后这段进度永久丢失，与触顶后继续
            # 累计的行为也不一致）；各参数的有效性只门控转换
            progress = int(stats.blackjack_hands_since_freespin or 0) + 1
            threshold = int(config.get("freespins_hand_threshold", 20) or 0)
            cap = int(config.get("freespins_weekly_cap", 5) or 0)
            expiry_days = int(config.get("freespins_expiry_days", 7) or 0)
            if threshold > 0 and cap > 0 and expiry_days > 0 and progress >= threshold:
                # 周上限只统计 21 点来源：礼包等其他来源的免费机会不占用配额。
                # 用肯定条件而非 != 'gift_pack'，以后新增来源不会悄悄混进口径
                granted_this_week = (
                    luckywheel_repository.count_blackjack_freespins_since_tx(
                        session, tg_id, self._blackjack_week_start_ms()
                    )
                )
                grant_count = 0
                while progress >= threshold and granted_this_week + grant_count < cap:
                    progress -= threshold
                    grant_count += 1
                if grant_count:
                    expires_at_ms = now_ms + expiry_days * 86400 * 1000
                    rows = luckywheel_repository.grant_free_spins_tx(
                        session,
                        tg_id,
                        grant_count,
                        source="blackjack",
                        granted_at_ms=now_ms,
                        expires_at_ms=expires_at_ms,
                        cost_credits=0,
                    )
                    result["freespins"].extend(
                        {"expires_at_ms": row.expires_at_ms} for row in rows
                    )
            stats.blackjack_hands_since_freespin = progress

        return result

    # 周返还游标：system_config(config_type=blackjack) 中记录已处理到的
    # 周起始（毫秒）。首次运行时写入锚点，此后每次运行把锚点之后的全部
    # 完整自然周逐周结算并推进——服务器停机跨周也能补漏，不会永久跳过某周
    CASHBACK_CURSOR_KEY = "cashback_settled_through"

    def settle_blackjack_weekly_cashback(self) -> dict:
        """结算应结而未结的全部完整自然周的 21 点损失返还。

        每周一由调度任务调用，亦可手动重跑：逐周幂等（结算行带
        UNIQUE(tg_id, week_start_ms)，撞约束即跳过）。停机跨周时本方法
        会把错过的完整周逐周补上（游标推进），而非永久跳过。

        净变动口径（spec「周损失返还与争霸赛余额」）：该周期内全部现金局
        终态手牌的 Σ(赔付 − 投注 + 连败救济 + 奖池派彩)。锦标赛赛内手牌、
        转盘结果、争霸赛余额变动、报名费的积分支付均不计入。

        首个结算周期：首次运行把锚点写到「刚结束的完整周」（部署周），部署
        周与其前不结算，首个结算周期为其后的第一个完整自然周。停用期间游标
        照常推进（停用的周不结算、重启用后不回溯），与奖池播报游标同款纪律。

        Returns: {
            enabled: bool,
            anchored: bool,          # 本次是否只做了首次锚定
            settled_weeks: [         # 本次结算的各周期
                {week_start_ms, users: [{tg_id, net_change, cashback,
                                        wallet_balance}]}
            ],
        }
        """
        config = self.get_blackjack_config_dict()
        week_ms = 7 * 86400 * 1000

        if not config.get("cashback_enabled", True):
            # 停用期间也推进游标：停用的周就是「不结算的周」。若冻结游标，
            # 重启用后会把停用期积累的全部完整周一次性补结并逐周倾泻私信
            # ——与「关闭即停发新让利」的语义相悖。推进到本周一起点后，
            # 重启用的首个结算周期 = 启用后的第一个完整自然周（与上线锚定
            # 同语义）。
            #
            # 已接受的代价：若「启用期间的某次周一任务没跑 + 随后停用」，
            # 那一周的数据会被跳过——无法与停用周区分，除非记录配置翻转
            # 历史；需要补救时管理员可在停用前手动触发本方法
            with get_session() as session:
                cursor_row, cursor = self._read_retention_cursor(
                    session, self.CASHBACK_CURSOR_KEY
                )
                now_week_start = self._blackjack_week_start_ms()
                if cursor < now_week_start:
                    self._write_retention_cursor(
                        session, cursor_row, self.CASHBACK_CURSOR_KEY, now_week_start
                    )
                    session.commit()
            return {"enabled": False, "anchored": False, "settled_weeks": []}

        rate = float(config.get("cashback_rate", 0.15) or 0)
        min_payout = float(config.get("cashback_min_payout", 1.0) or 0)

        with get_session() as session:
            now_week_start = self._blackjack_week_start_ms()

            cursor_row, cursor = self._read_retention_cursor(
                session, self.CASHBACK_CURSOR_KEY, for_update=True
            )
            if cursor_row is None or cursor <= 0:
                # 首次运行（或游标值损坏归零）：锚定到刚结束的那个完整周（即
                # 部署周）。部署周与其前的一切不结算，首个结算周期为其后的
                # 第一个完整自然周——周中部署时，部署周内部署日之前的亏损
                # 不参与返还。
                # 取 now − 7d 而非 now：定时任务固定周一 00:05 跑，此时刚结束
                # 的完整周恰好是部署周；若取 now（首跑周）会把「启用后的第
                # 一个完整自然周」整周丢弃（周一跑、周三部署的常见时序）
                self._write_retention_cursor(
                    session,
                    cursor_row,
                    self.CASHBACK_CURSOR_KEY,
                    now_week_start - week_ms,
                )
                session.commit()
                return {"enabled": True, "anchored": True, "settled_weeks": []}

            settled_weeks = []
            week_start = cursor + week_ms
            while week_start < now_week_start:
                users = self._settle_one_cashback_week(
                    session, week_start, rate=rate, min_payout=min_payout
                )
                settled_weeks.append({"week_start_ms": week_start, "users": users})
                self._write_retention_cursor(
                    session, cursor_row, self.CASHBACK_CURSOR_KEY, week_start
                )
                session.commit()  # 逐周提交：中途失败时已结的周不丢
                week_start += week_ms

            return {
                "enabled": True,
                "anchored": False,
                "settled_weeks": settled_weeks,
            }

    def _read_retention_cursor(
        self, session, key: str, *, for_update: bool = False
    ) -> tuple:
        """读取 system_config(blackjack) 中的留存游标行与解析后的整数值。

        供周返还（周起点）与免费机会通知（行 ID）两个游标共用。解析失败
        按 0 处理：游标只会前移，0 意味着从头补——宁可重扫不可跳过。
        Returns: (行对象或 None, 解析值)
        """
        stmt = select(SystemConfig).where(
            SystemConfig.config_type == "blackjack",
            SystemConfig.config_key == key,
        )
        if for_update:
            stmt = stmt.with_for_update()
        row = session.execute(stmt).scalars().one_or_none()
        try:
            value = int(float(row.config_value)) if row else 0
        except (TypeError, ValueError):
            value = 0
        return row, value

    def _write_retention_cursor(
        self,
        session,
        cursor_row: SystemConfig | None,
        key: str,
        value: int,
    ) -> None:
        """把留存游标写入或更新到指定值。调用方须在事务内；行不存在时
        新建（insert），存在时原地更新。"""
        now_ts = int(time.time())
        if cursor_row is None:
            session.add(
                SystemConfig(
                    config_type="blackjack",
                    config_key=key,
                    config_value=str(int(value)),
                    created_at=now_ts,
                    updated_at=now_ts,
                )
            )
        else:
            cursor_row.config_value = str(int(value))
            cursor_row.updated_at = now_ts
        session.flush()

    def _settle_one_cashback_week(
        self, session, week_start_ms: int, *, rate: float, min_payout: float
    ) -> list:
        """结算单个自然周。返回获得返还的用户列表（供任务发通知）。

        幂等：逐用户 INSERT 结算行，撞 UNIQUE(tg_id, week_start_ms) 说明该
        周已结算过，跳过该用户（SAVEPOINT 隔离，不影响同批其他用户）。
        """
        week_ms = 7 * 86400 * 1000
        start_s = int(week_start_ms) // 1000
        end_s = (int(week_start_ms) + week_ms) // 1000

        from app.domains.blackjack import rules as engine

        # 净变动 = Σ(赔付 − 投注 + 救济 + 奖池派彩)；投注含加倍的两份
        wager = BlackjackHand.bet_credits * (1 + BlackjackHand.doubled)
        net_expr = (
            func.coalesce(BlackjackHand.payout_credits, 0)
            - wager
            + func.coalesce(BlackjackHand.relief_credits, 0)
            + func.coalesce(BlackjackHand.jackpot_won, 0)
        )
        rows = session.execute(
            select(BlackjackHand.tg_id, func.sum(net_expr).label("net_change"))
            .where(
                BlackjackHand.tournament_id.is_(None),
                BlackjackHand.status.in_(engine.TERMINAL_STATUSES),
                BlackjackHand.settled_at >= start_s,
                BlackjackHand.settled_at < end_s,
            )
            .group_by(BlackjackHand.tg_id)
        ).all()

        from app.domains.blackjack import rules

        payload = []
        for tg_id, net_change in rows:
            net = round(float(net_change or 0), 2)
            cashback = rules.calculate_cashback(net, rate, min_payout)
            if cashback is None:
                # 净赢者或低于发放门槛：不发、不通知、不留结算行
                continue
            try:
                with session.begin_nested():
                    session.add(
                        BlackjackWeeklyCashback(
                            tg_id=int(tg_id),
                            week_start_ms=int(week_start_ms),
                            net_change=net,
                            cashback_credits=cashback,
                            created_at_ms=int(time.time() * 1000),
                        )
                    )
                    session.flush()
            except IntegrityError:
                # 该周该用户已结算（任务重跑）：跳过，不重复入账
                continue

            stats = (
                session.execute(
                    select(Statistics)
                    .where(Statistics.tg_id == int(tg_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if stats is None:
                # 现金局手牌必然来自有 Statistics 行的用户，此处为防御
                session.add(
                    Statistics(
                        tg_id=int(tg_id),
                        donation=0,
                        credits=0,
                        tournament_wallet_credits=cashback,
                    )
                )
                wallet_balance = cashback
            else:
                stats.tournament_wallet_credits = round(
                    float(stats.tournament_wallet_credits or 0) + cashback, 2
                )
                wallet_balance = round(float(stats.tournament_wallet_credits), 2)
            payload.append(
                {
                    "tg_id": int(tg_id),
                    "net_change": net,
                    "cashback": cashback,
                    "wallet_balance": wallet_balance,
                }
            )

        if payload:
            logger.info(
                f"21 点周返还结算完成（week_start={week_start_ms}，"
                f"{len(payload)} 人获得返还）"
            )
        return payload

    def _blackjack_week_start_ms(self, *, now: datetime | None = None) -> int:
        """本周一零点（`settings.TZ`）的毫秒时间戳。

        与免抽水的自然日同一口径（周一为一周之始），免费机会的周配额与
        周损失返还的结算周期都以它为界。"""
        now = now or datetime.now(settings.TZ)
        week_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return int(week_start.timestamp() * 1000)
