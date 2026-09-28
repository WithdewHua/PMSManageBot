"""21 点 repository：幸运奖池（由 part_N 机械拆分）。"""

import json
import time

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.db import get_session
from app.core.kv import SystemConfig
from app.core.log import logger
from app.domains.blackjack.exceptions import blackjack_error
from app.domains.blackjack.models import BlackjackHand
from app.domains.blackjack.repository.constants import (
    JACKPOT_CONFIG_KEY,
    JACKPOT_CONFIG_TYPE,
    JACKPOT_NOTIFY_CURSOR_KEY,
)


class _BlackjackRepositoryJackpot:
    def _locked_fund_row(self, session, config_type: str, config_key: str):
        """取奖池余额行并加锁。行不存在时返回 None。"""
        return (
            session.execute(
                select(SystemConfig)
                .where(
                    SystemConfig.config_type == config_type,
                    SystemConfig.config_key == config_key,
                )
                .with_for_update()
            )
            .scalars()
            .one_or_none()
        )

    def _add_to_fund(
        self, session, config_type: str, config_key: str, amount: float
    ) -> float:
        """把指定金额注入某个奖池，返回注入后的余额。调用方须在事务内。

        余额以**小数**字符串存储：21 点的单手注入天然为小数（注 5 普通胜的奖池
        份额为 0.06），取整会长期为零。

        首次注入（配置行尚不存在）时并发安全：`SELECT ... FOR UPDATE` 对**不存在
        的行**锁不到任何东西，两个并发事务会各自认为需要 INSERT 并双双写入，撞上
        `uq_config_type_key` 唯一约束（此点在 PostgreSQL 上同样成立，不限于 SQLite）。
        故插入放在 SAVEPOINT 内，撞约束时回退到「重新读取 + 累加」，使先到者的注入
        不被丢弃。
        """
        if amount <= 0:
            return self.read_fund_balance(session, config_type, config_key)

        now_ts = int(time.time())

        def _accumulate(cfg) -> float:
            try:
                current = float(cfg.config_value or "0")
            except Exception:
                current = 0.0
            new_balance = round(current + float(amount), 2)
            cfg.config_value = str(new_balance)
            cfg.updated_at = now_ts
            return new_balance

        cfg = self._locked_fund_row(session, config_type, config_key)
        if cfg:
            return _accumulate(cfg)

        new_balance = round(float(amount), 2)
        try:
            with session.begin_nested():
                session.add(
                    SystemConfig(
                        config_type=config_type,
                        config_key=config_key,
                        config_value=str(new_balance),
                        created_at=now_ts,
                        updated_at=now_ts,
                    )
                )
            return new_balance
        except IntegrityError:
            # 并发的另一方已建好该行：回退到累加，不丢本次注入
            cfg = self._locked_fund_row(session, config_type, config_key)
            if cfg:
                return _accumulate(cfg)
            raise

    def read_fund_balance(self, session, config_type: str, config_key: str) -> float:
        """读奖池余额（不加锁）。行不存在或值非法时返回 0。"""
        raw = session.execute(
            select(SystemConfig.config_value).where(
                SystemConfig.config_type == config_type,
                SystemConfig.config_key == config_key,
            )
        ).scalar_one_or_none()
        try:
            return float(raw or 0)
        except Exception:
            return 0.0

    def _pay_from_jackpot(
        self, session, amount: float | None = None, *, pay_all: bool = False
    ) -> float:
        """从幸运奖池扣减派彩额，返回实际派发的金额。调用方须在事务内。

        余额不足时按余额发放（而非拒发），且绝不会使余额变为负数——奖池只由抽水
        供养，派彩上限就是它自己的余额，这是「不增发积分」的硬保证。

        `pay_all=True` 表示派发全部余额（三张 7）。这个模式是必需的：若由调用方
        先无锁读一次余额、再把该数值当作 amount 传进来，两次读之间提交的抽水会
        让加锁读到的 current 大于 amount，`min` 取 amount 于是**少派**了差额，
        与 spec「三张 7 SHALL 派发全部余额」相悖。金额只在锁内确定一次。
        """
        if not pay_all and (amount is None or amount <= 0):
            return 0.0

        cfg = self._locked_fund_row(session, JACKPOT_CONFIG_TYPE, JACKPOT_CONFIG_KEY)
        if not cfg:
            return 0.0
        try:
            current = float(cfg.config_value or "0")
        except Exception:
            current = 0.0
        if current <= 0:
            return 0.0

        paid = round(current if pay_all else min(float(amount), current), 2)
        if paid <= 0:
            return 0.0
        cfg.config_value = str(round(current - paid, 2))
        cfg.updated_at = int(time.time())
        return paid

    def get_blackjack_jackpot(self) -> float:
        """读幸运奖池当前余额，供牌桌与配置接口展示。"""
        try:
            with get_session() as session:
                return self.read_fund_balance(
                    session, JACKPOT_CONFIG_TYPE, JACKPOT_CONFIG_KEY
                )
        except Exception as e:
            logger.error(f"读取 21 点幸运奖池余额失败: {e}")
            return 0.0

    def seed_blackjack_jackpot(self, amount: float) -> float:
        """由管理员手动注入奖池种子余额，返回注入后的余额。

        这是本设计里**唯一会增发积分**的路径——奖池平时只由抽水供养。故它必须是
        管理员的显式操作，绝不能自动发生。用途是上线冷启动时让奖池有个初值。
        """
        if amount <= 0:
            raise blackjack_error("jackpot seed must be positive")
        with get_session() as session:
            balance = self._add_to_fund(
                session, JACKPOT_CONFIG_TYPE, JACKPOT_CONFIG_KEY, float(amount)
            )
            logger.info(f"管理员向 21 点幸运奖池注入种子 {amount}，余额 → {balance}")
            return balance

    def claim_unannounced_jackpot_wins(self) -> list[dict]:
        """认领尚未播报的奖池中奖手牌，并把游标推进到本轮的安全边界。

        「认领」意味着调用方**必须**负责播报——本方法一旦返回就已推进游标，
        同一手牌不会再被返回第二次。宁可偶尔漏播一条（发送失败），也不能重复
        刷屏，故不做失败回滚。

        游标的安全边界是关键：不能简单推到当前最大手牌 ID，否则一手刚发出、
        尚未结算的牌会被游标跳过，它之后若中奖就永远播报不到。边界取
        **最小的进行中手牌 ID 减一**，没有进行中手牌时才推到最大 ID。手牌至多
        悬挂 `hand_timeout_minutes` 分钟就会被兜底结算，故边界不会长期卡住。

        依赖调度器的 `max_instances=1` 保证同一时刻只有一个实例在跑；读游标与
        写游标在同一事务内完成。
        """
        from app.domains.blackjack import rules as engine

        try:
            with get_session() as session:
                cursor_row = session.execute(
                    select(SystemConfig).where(
                        SystemConfig.config_type == JACKPOT_CONFIG_TYPE,
                        SystemConfig.config_key == JACKPOT_NOTIFY_CURSOR_KEY,
                    )
                ).scalar_one_or_none()
                try:
                    cursor = int(float(cursor_row.config_value)) if cursor_row else 0
                except (TypeError, ValueError):
                    cursor = 0

                max_id = (
                    session.execute(select(func.max(BlackjackHand.id))).scalar() or 0
                )
                # 进行中的最小手牌 ID 即为本轮不可越过的边界
                oldest_active = session.execute(
                    select(func.min(BlackjackHand.id)).where(
                        BlackjackHand.status.notin_(engine.TERMINAL_STATUSES)
                    )
                ).scalar()
                frontier = int(oldest_active) - 1 if oldest_active else int(max_id)

                now_ts = int(time.time())
                if cursor_row is None:
                    # 首次运行：游标直接落在当前边界并**不播报任何历史中奖**。
                    # 本功能可能在活动已上线一段时间后才部署，若从 0 开始，
                    # 第一轮就会把过往全部中奖一次性倒进群里。
                    session.add(
                        SystemConfig(
                            config_type=JACKPOT_CONFIG_TYPE,
                            config_key=JACKPOT_NOTIFY_CURSOR_KEY,
                            config_value=str(frontier),
                            created_at=now_ts,
                            updated_at=now_ts,
                        )
                    )
                    logger.info(f"21 点奖池播报游标初始化为 {frontier}，不回溯历史中奖")
                    return []

                if frontier <= cursor:
                    return []

                rows = session.execute(
                    select(
                        BlackjackHand.id,
                        BlackjackHand.tg_id,
                        BlackjackHand.player_cards,
                        BlackjackHand.jackpot_won,
                        BlackjackHand.bet_credits,
                        BlackjackHand.outcome,
                    )
                    .where(
                        BlackjackHand.id > cursor,
                        BlackjackHand.id <= frontier,
                        BlackjackHand.jackpot_won > 0,
                    )
                    .order_by(BlackjackHand.id)
                ).all()

                cursor_row.config_value = str(frontier)
                cursor_row.updated_at = now_ts

                wins = []
                for hand_id, tg, cards_json, won, bet, outcome in rows:
                    cards = json.loads(cards_json or "[]")
                    wins.append(
                        {
                            "hand_id": int(hand_id),
                            "tg_id": int(tg),
                            "player_cards": cards,
                            "jackpot_won": float(won or 0),
                            "bet_credits": int(bet or 0),
                            "outcome": outcome,
                            "triple_seven": engine.is_triple_seven(cards),
                        }
                    )
                return wins
        except Exception as e:
            logger.error(f"认领待播报的 21 点奖池中奖失败: {e}")
            return []
