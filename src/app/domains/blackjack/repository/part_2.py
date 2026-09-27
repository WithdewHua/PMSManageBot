import json
import time
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.db import get_session
from app.core.kv import SystemConfig
from app.core.log import logger
from app.domains.blackjack.exceptions import blackjack_error
from app.domains.blackjack.models import (
    BlackjackHand,
)
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import Statistics

from . import (
    JACKPOT_CONFIG_KEY,
    JACKPOT_CONFIG_TYPE,
    JACKPOT_NOTIFY_CURSOR_KEY,
)


class _BlackjackRepositoryPart2:
    def _settle_blackjack_hand(
        self,
        session,
        hand: BlackjackHand,
        abandoned: bool = False,
        jackpot_config: dict | None = None,
    ) -> dict:
        """21 点结算的共用路径：停牌 / 加倍 / 爆牌 / 超时兜底四条入口都走这里。

        调用方**必须**已对 `hand` 行取过 FOR UPDATE。锁顺序固定为
        hand → statistics → system_config，全路径一致以避免死锁。

        `abandoned=True` 表示由超时兜底触发：结算口径与玩家停牌完全相同
        （庄家按规则补牌、正常判定胜负），只是终态记为已弃牌以便区分来源；
        绝不因超时直接判负。

        **幂等由条件 UPDATE（compare-and-swap）保证，而非读取 status 后判断。**
        终态的写入带 `WHERE status IN (非终态)` 条件，只有把手牌从非终态成功改成
        终态的那一方才继续计入积分与注入奖池；`rowcount == 0` 说明已被他人结算，
        直接返回既有结果。

        为什么不能只靠「FOR UPDATE 后读 status」：SQLite 无行级锁，
        `with_for_update()` 在该方言下是 no-op，两个并发事务可以各自读到
        status=1、各自算出赔付、再依次写入，造成**重复赔付**（已实测复现）。
        条件 UPDATE 不依赖行锁，在 SQLite 与 PostgreSQL 上都成立。

        **加锁顺序：手牌 → statistics → system_config（奖池）。**
        本方法内部据此把 Statistics 的行锁取在奖池之前。这条顺序是全局的，
        发牌与加倍路径先锁 Statistics 再进入本方法，同样成立。任何新增的写路径
        都必须遵守它——奖池是一行**全局共享**的记录，一旦有人反着来，
        PostgreSQL 上就会出现只在并发下复现的死锁。
        """
        from app.domains.blackjack import rules as engine

        # 先做一次廉价的前置检查：多数重复请求在这里就被挡掉，省去无谓的计算。
        # 但它**不是**幂等的保证——真正的保证是下方的条件 UPDATE。
        if int(hand.status) in engine.TERMINAL_STATUSES:
            return {
                "hand": self._blackjack_hand_to_dict(hand),
                "already_settled": True,
            }

        hand_id = int(hand.id)
        tg_id = int(hand.tg_id)
        bet = int(hand.bet_credits)
        doubled = int(hand.doubled) == 1
        player_cards = json.loads(hand.player_cards or "[]")
        dealer_cards = json.loads(hand.dealer_cards or "[]")

        # 按手牌上的参数快照结算，而非读当前配置——管理员改配置不影响本手牌
        blackjack_payout = float(hand.blackjack_payout)
        hits_soft_17 = int(hand.dealer_hits_soft_17) == 1
        rake_bp = int(hand.rake_bp_on_profit)
        rake_jackpot_bp = int(hand.rake_jackpot_bp)

        # 奖池的开关与派彩比例不随手牌快照——它们是奖池自身的运营参数，
        # 而非本手牌的结算口径；奖池余额本就是全局共享、随时在变的。
        #
        # 配置由调用方在**开启事务之前**读好传入：本方法运行在调用方的事务里，
        # 若在此处调 get_blackjack_config_dict() 会另开一个 session，使每次结算
        # 同时占用两个连接（池只有 5+10），且首次读取还会在新连接上写库——外层
        # 正持有行锁时这会直接死锁。
        if jackpot_config is None:
            jackpot_config = self.get_blackjack_config_dict()
        jackpot_enabled = bool(jackpot_config.get("jackpot_enabled", True))
        jackpot_suited_pct = float(jackpot_config.get("jackpot_suited_bj_pct", 10))

        deck = engine.build_deck(str(hand.deck_seed))
        next_index = int(hand.next_card_index)

        # 庄家在两种情形下不补牌：
        #   1. 玩家爆牌——spec：庄家 SHALL NOT 补牌
        #   2. 开局任一方天胡——spec：手牌 SHALL 直接进入已结算，不经玩家回合，
        #      而庄家 SHALL 在玩家停牌或加倍后才开始补牌
        # 第 2 条曾被漏掉：天胡虽然赔付正确（resolve 优先判天胡），但庄家会照常
        # 补牌，幽灵牌被写进 dealer_cards，前端于是回放「庄家逐张补牌甚至爆牌」
        # 之后再打出「天胡」，牌面完全是编造的。
        #
        # 走到停牌/加倍/超时时双方都不可能再有天胡（天胡在发牌时就结算了），
        # 故这个判定只会在发牌路径上为真。
        settled_on_deal = engine.is_natural_blackjack(
            player_cards
        ) or engine.is_natural_blackjack(dealer_cards)
        if engine.is_bust(player_cards) or settled_on_deal:
            final_dealer_cards = dealer_cards
        else:
            final_dealer_cards, next_index = engine.play_dealer(
                deck, dealer_cards, next_index, hits_soft_17=hits_soft_17
            )

        settlement = engine.calculate_cash_settlement(
            player_cards,
            final_dealer_cards,
            bet=bet,
            doubled=doubled,
            blackjack_payout=blackjack_payout,
            rake_bp=rake_bp,
        )
        outcome = settlement.outcome
        rake = settlement.rake
        payout = settlement.payout

        final_status = engine.STATUS_ABANDONED if abandoned else engine.STATUS_SETTLED
        now_ts = int(time.time())

        # 以上都是无副作用的纯计算。真正的幂等闸门在此：只有把手牌从非终态原子地
        # 改成终态的那一方，才有权继续写积分与奖池。先把 ORM 层的挂起改动刷下去，
        # 使随后的条件 UPDATE 读到的是最新状态。
        session.flush()
        claimed = session.execute(
            update(BlackjackHand)
            .where(
                BlackjackHand.id == hand_id,
                BlackjackHand.status.notin_(engine.TERMINAL_STATUSES),
            )
            .values(
                status=final_status,
                outcome=outcome,
                payout_credits=float(payout),
                rake_credits=float(rake),
                dealer_cards=json.dumps(final_dealer_cards),
                next_card_index=int(next_index),
                settled_at=now_ts,
            )
        )
        if claimed.rowcount == 0:
            # 已被他人结算：不计积分、不动奖池，返回既有结果
            session.expire(hand)
            return {
                "hand": self._blackjack_hand_to_dict(hand),
                "already_settled": True,
            }

        # 抢占成功，本次结算生效。使 ORM 对象读到刚写入的值
        session.expire(hand)

        # 先取该用户 Statistics 的行锁，**再**去碰奖池行——全局加锁顺序统一为
        # 手牌 → statistics → system_config。
        #
        # 为什么必须在这里、且必须无条件取：本方法原先把 Statistics 的锁放在
        # 奖池之后、还包在 `if credited > 0` 里，于是同一对资源出现了两种顺序：
        #   发牌 / 加倍：statistics → system_config
        #   停牌 / 要牌 / 超时 / 兜底：system_config → statistics
        # 这是教科书式的 ABBA。它目前之所以没真的死锁，靠的是两个**没有写下来
        # 的巧合**：发牌路径的「进行中手牌」检查恰好是非加锁 SELECT（并发结算
        # 未提交时它读到旧状态并抛错退出，环因此断开），以及「同一用户至多一手
        # 进行中」使加倍路径总被手牌行锁挡在前面。任何一处改动——比如给那句
        # 计数加上 `.with_for_update()`——都会让死锁立刻成真，而且只在
        # PostgreSQL 上、只在并发下出现。
        #
        # 条件加锁不构成加锁纪律：顺序只有无条件成立才有意义，故不再放进
        # `if credited > 0`。代价只是判负时多锁一行本用户的记录，可忽略。
        stats = (
            session.execute(
                select(Statistics).where(Statistics.tg_id == tg_id).with_for_update()
            )
            .scalars()
            .one_or_none()
        )

        # 幸运奖池：先派彩、后累积。同一手牌不应吃到自己刚交的抽水，故顺序不可颠倒。
        # 派彩独立于本手胜负——拿到三张 7 却因庄家天胡判负仍照发，否则最稀有的
        # 牌型会有概率颗粒无收，而那恰是最需要正反馈的时刻。
        jackpot_won = 0.0
        if jackpot_enabled:
            if engine.is_triple_seven(player_cards):
                # 三张 7：派发全部余额。金额在锁内确定，不先无锁读一次再传进去
                jackpot_won = self._pay_from_jackpot(session, pay_all=True)
            elif engine.is_suited_blackjack(player_cards):
                # 同花天胡：派发余额的固定比例。比例的基数取无锁读到的余额即可——
                # 「当前余额的 10%」本就没有唯一正确的瞬间，且实际派发额仍受锁内
                # 余额的上限约束，不会超发。
                balance = self.read_fund_balance(
                    session, JACKPOT_CONFIG_TYPE, JACKPOT_CONFIG_KEY
                )
                target = engine.calculate_jackpot_target(balance, jackpot_suited_pct)
                jackpot_won = self._pay_from_jackpot(session, target)

        # 抽水去向：一部分注入幸运奖池，其余直接销毁。
        # 销毁部分不需要落账——销毁即「不发给任何人」，未进奖池的部分自然消失；
        # 手牌上的 rake_credits 记录抽水总额供审计。
        jackpot_in = engine.calculate_jackpot_injection(rake, rake_jackpot_bp, rake_bp)
        if jackpot_in > 0:
            self._add_to_fund(
                session, JACKPOT_CONFIG_TYPE, JACKPOT_CONFIG_KEY, jackpot_in
            )

        # 计入积分：赔付与奖池派彩一并入账，但在手牌上分列两处记账。
        # Statistics 的行锁已在奖池之前取好，此处只写不再加锁。
        credited = round(payout + jackpot_won, 2)
        if credited > 0:
            if stats:
                mutation = credits_repository.add_tx(
                    session, CreditAccount.tg(tg_id), credited
                )
                credits_service.register_cache_invalidation(session, mutation)
            else:
                session.add(
                    Statistics(tg_id=tg_id, donation=0, credits=float(credited))
                )

        if jackpot_won > 0:
            session.execute(
                update(BlackjackHand)
                .where(BlackjackHand.id == hand_id)
                .values(jackpot_won=float(jackpot_won))
            )
            session.expire(hand)

        # 留存钩子：连败救济与免费转盘机会。放在积分入账之后、最终 flush
        # 之前——救济补偿也走 stats.credits，与赔付同一事务同一行锁；
        # 两项计数写入 stats，金额写入手牌行。幂等性已由上方的结算 CAS
        # 保证（抢不到的一方根本走不到这里）
        retention = self.apply_blackjack_retention_tx(
            session,
            hand,
            stats,
            outcome=outcome,
            config=jackpot_config,
            now_ts=now_ts,
        )

        session.flush()

        return {
            "hand": self._blackjack_hand_to_dict(hand),
            "already_settled": False,
            "outcome": outcome,
            "payout_credits": payout,
            "rake_credits": rake,
            "jackpot_won": jackpot_won,
            "jackpot_in": jackpot_in,
            "relief_credits": retention["relief_credits"],
            "freespins": retention["freespins"],
        }

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

    def sweep_timed_out_blackjack_hands(self, tg_id: int | None = None) -> int:
        """结算所有已超时的进行中手牌，返回**实际结算成功**的手数。

        **每手牌自成一个事务**，不与调用方共用、也不彼此共用。两层理由：

        1. 不寄生在发牌或查询的事务里——否则调用方后续任何一次校验失败（速率、
           门槛、余额）都会把已完成的结算连带回滚，用户的赔付被丢弃。
        2. 不把整批放进一个事务——否则第 31 手上的任何异常（牌靴耗尽、约束冲突、
           瞬时连接错误）都会回滚前 30 手已经算好的赔付，而返回值仍会把它们报成
           已结算：积分没进账、手牌仍非终态、押注还扣着，日志却显示一切正常。

        `tg_id` 为空表示全量扫描，供定时兜底任务使用。为什么需要全量兜底：
        APScheduler 的 `misfire_grace_time` 会丢弃错过窗口过久的任务（重启即可
        触发），而按用户的惰性清理只在该用户自己再次操作时发生——若用户再也不
        回来，手牌会永久悬挂、押注不退，违反 spec「超时任务 SHALL 持久化，
        服务重启 SHALL NOT 导致待处置的手牌被遗漏」。

        超时判定下推到 SQL（`created_at_ms + 时限 <= now`）且只取 id：全量扫描
        每 10 分钟跑一次且永不停歇，把整表的非终态行实体化成 ORM 对象再在 Python
        里筛选，会随手牌表增长成为反复的全表水化。
        """
        from app.domains.blackjack import rules as engine

        now_ms = int(time.time() * 1000)
        # 奖池参数在循环外读一次：它对本批所有手牌都一样，而在每手的事务内读会
        # 各自另开一个连接
        jackpot_config = self.get_blackjack_config_dict()

        try:
            with get_session() as session:
                stmt = select(BlackjackHand.id).where(
                    BlackjackHand.status.notin_(engine.TERMINAL_STATUSES),
                    BlackjackHand.created_at_ms
                    + BlackjackHand.hand_timeout_minutes * 60000
                    <= now_ms,
                )
                if tg_id is not None:
                    stmt = stmt.where(BlackjackHand.tg_id == int(tg_id))
                expired_ids = [int(r[0]) for r in session.execute(stmt).all()]
        except Exception as e:
            logger.error(f"扫描超时 21 点手牌失败 (tg_id={tg_id}): {e}")
            return 0

        swept = 0
        for hand_id in expired_ids:
            try:
                with get_session() as session:
                    hand = (
                        session.execute(
                            select(BlackjackHand)
                            .where(BlackjackHand.id == hand_id)
                            .with_for_update()
                        )
                        .scalars()
                        .one_or_none()
                    )
                    if not hand or int(hand.status) in engine.TERMINAL_STATUSES:
                        continue
                    # 先抢占再结算：与用户的并发操作撞车时先到者赢
                    if not self._claim_blackjack_hand(
                        session, hand_id, allow_dealer_turn=True
                    ):
                        continue
                    session.expire(hand)
                    # 按 tournament_id 分派适配层：赛内手牌必须走筹码路径，
                    # 否则会用筹码算出的数额去赔用户的**积分**
                    self._settle_blackjack_hand_dispatch(
                        session,
                        hand,
                        abandoned=True,
                        jackpot_config=jackpot_config,
                    )
                    swept += 1
            except Exception as e:
                # 单手失败只丢这一手，其余照常结算；下一轮兜底会再试
                logger.error(f"清理超时 21 点手牌失败 (hand={hand_id}): {e}")

        if swept:
            logger.info(f"已结算 {swept} 手超时的 21 点手牌 (tg_id={tg_id})")
        return swept

    def _blackjack_day_start_ms(self) -> int:
        """当日零点（`settings.TZ`）的毫秒时间戳，免抽水判定的分界。"""
        day_start = datetime.now(settings.TZ).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return int(day_start.timestamp() * 1000)

    def _blackjack_week_start_ms(self, *, now: datetime | None = None) -> int:
        """本周一零点（`settings.TZ`）的毫秒时间戳。

        与免抽水的自然日同一口径（周一为一周之始），免费机会的周配额与
        周损失返还的结算周期都以它为界。"""
        now = now or datetime.now(settings.TZ)
        week_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return int(week_start.timestamp() * 1000)

    def _count_blackjack_hands_today(self, session, tg_id: int) -> int:
        """该用户当日已发的**现金局**手数（含进行中）。

        走已有的 `(tg_id, created_at_ms)` 复合索引，不新增存储也不新增查询模式。

        锦标赛赛内手牌不计入（`tournament_id IS NULL`）：赛内根本不产生抽水，
        故不该消耗当日的免抽水额度——否则先打一场赛事就会把当天的免抽水吃掉。
        """
        return int(
            session.execute(
                select(func.count(BlackjackHand.id)).where(
                    BlackjackHand.tg_id == int(tg_id),
                    BlackjackHand.created_at_ms >= self._blackjack_day_start_ms(),
                    BlackjackHand.tournament_id.is_(None),
                )
            ).scalar_one()
            or 0
        )

    def get_blackjack_free_hands_remaining(self, tg_id: int) -> int:
        """该用户今日剩余的免抽水手数，供下注界面标示。

        仅供展示：真正是否免抽水由发牌事务内的同一口径重新判定并落到快照上，
        故本方法与发牌之间的竞态只会让提示短暂失准，不会造成错误的抽水。
        """
        try:
            with get_session() as session:
                free_hands = int(
                    self.get_blackjack_config_dict().get("free_hands_per_day", 1)
                )
                if free_hands <= 0:
                    return 0
                used = self._count_blackjack_hands_today(session, int(tg_id))
                return max(0, free_hands - used)
        except Exception as e:
            logger.error(f"获取 21 点剩余免抽水手数失败 (tg_id={tg_id}): {e}")
            return 0
