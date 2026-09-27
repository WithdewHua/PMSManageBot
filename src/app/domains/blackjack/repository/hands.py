"""21 点 repository：现金局手牌的生命周期与动作（由 part_N 机械拆分）。"""

import json
import secrets
import time
from datetime import datetime

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.blackjack.exceptions import blackjack_error
from app.domains.blackjack.models import BlackjackHand
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import Statistics


class _BlackjackRepositoryHands:
    def _blackjack_hand_to_dict(self, hand: BlackjackHand) -> dict:
        """把手牌行转为字典。

        **有意包含 `deck_seed` 与 `next_card_index`**：本方法服务于服务端内部
        （路由、结算、调度任务），响应层的 schema 显式列字段、不复用本 dump，
        种子与游标不会因此泄漏到面向用户的响应里（见 schemas/blackjack.py）。
        """
        return {
            "id": int(hand.id),
            "tg_id": int(hand.tg_id),
            "status": int(hand.status),
            "bet_credits": int(hand.bet_credits),
            "doubled": int(hand.doubled),
            "deck_seed": str(hand.deck_seed),
            "next_card_index": int(hand.next_card_index),
            "player_cards": json.loads(hand.player_cards or "[]"),
            "dealer_cards": json.loads(hand.dealer_cards or "[]"),
            "outcome": hand.outcome,
            "payout_credits": float(hand.payout_credits)
            if hand.payout_credits is not None
            else None,
            "rake_credits": float(hand.rake_credits)
            if hand.rake_credits is not None
            else None,
            "jackpot_won": float(hand.jackpot_won)
            if hand.jackpot_won is not None
            else None,
            "relief_credits": float(hand.relief_credits)
            if hand.relief_credits is not None
            else None,
            "decisions_total": int(hand.decisions_total),
            "decisions_correct": int(hand.decisions_correct),
            "rake_waived": int(hand.rake_waived) == 1,
            "rake_bp_on_profit": int(hand.rake_bp_on_profit),
            "rake_jackpot_bp": int(hand.rake_jackpot_bp),
            "blackjack_payout": float(hand.blackjack_payout),
            "dealer_hits_soft_17": int(hand.dealer_hits_soft_17),
            "hand_timeout_minutes": int(hand.hand_timeout_minutes),
            "surrender_enabled": int(hand.surrender_enabled) == 1,
            # 该手牌属于哪一侧。响应层据此把用户引回正确的牌桌：两侧共用「同时至多
            # 一手」这个不变量，故 `/current` 可能返回一手赛内牌，而现金局界面若把
            # 它当自己的牌渲染，用户点任何动作都只会得到「找不到该手牌」
            "tournament_id": int(hand.tournament_id)
            if hand.tournament_id is not None
            else None,
            "created_at_ms": int(hand.created_at_ms),
            "settled_at": int(hand.settled_at) if hand.settled_at is not None else None,
        }

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

    def create_blackjack_hand(self, tg_id: int, bet_credits: int) -> dict:
        """发牌：校验 → 扣注额 → 生成种子定序 → 发初始牌 → 天胡则直接结算。

        并发安全：对该用户的 `Statistics` 行取 FOR UPDATE。发牌本来就要锁这行
        来扣积分，顺带把同一用户的发牌请求串行化，于是「并发双开」「并发绕过速率
        限制」「并发绕过门槛校验」三个问题一把锁解决，无需额外锁对象。

        本方法**只锁 statistics，不锁手牌行**——见下方「进行中手牌」检查处的说明。

        Returns: {hand, settled(bool), outcome?, payout_credits?, ...}
        """

        config = self.get_blackjack_config_dict()

        if not config.get("enabled", False):
            raise blackjack_error("blackjack disabled")

        bet_options = [int(b) for b in config.get("bet_options") or []]
        if int(bet_credits) not in bet_options:
            raise blackjack_error(f"invalid bet: must be one of {bet_options}")

        # 惰性清理走**独立事务**并先行提交：调度任务负责及时性，本步负责最终
        # 一致性，使用户不会被永久锁在「有进行中手牌无法发新牌」的状态里。
        # 放在本次发牌的事务之外，故发牌若被后续校验拒绝，也不会把已完成的
        # 结算连带回滚、丢弃用户的赔付。
        self.sweep_timed_out_blackjack_hands(tg_id=int(tg_id))

        now_ms = int(time.time() * 1000)

        with get_session() as session:
            return self.create_blackjack_hand_tx(
                session, tg_id, bet_credits, config=config, now_ms=now_ms
            )

    def create_blackjack_hand_tx(
        self, session, tg_id: int, bet_credits: int, *, config: dict, now_ms: int
    ) -> dict:
        from app.domains.blackjack import rules as engine

        min_credits = int(config.get("min_credits", 30))
        timeout_minutes = int(config.get("hand_timeout_minutes", 15))
        min_interval_seconds = float(config.get("min_deal_interval_seconds", 1))
        # 锁积分行：同时串行化同一用户的发牌
        stats = (
            session.execute(
                select(Statistics)
                .where(Statistics.tg_id == int(tg_id))
                .with_for_update()
            )
            .scalars()
            .one_or_none()
        )
        if not stats:
            raise blackjack_error("user stats not found")

        # 仍有进行中手牌则拒绝发牌，并引导用户回到该手牌。
        # 此处**只读不锁**：其余路径的加锁顺序均为 hand → statistics，
        # 若在已持有 statistics 锁时再锁手牌就构成 ABBA 死锁（超时任务持有
        # 手牌等 statistics，本方法持有 statistics 等手牌）。同一用户的手牌
        # 由 statistics 锁间接串行化，无需另外加锁。
        #
        # **刻意不加 `tournament_id IS NULL`**：「同时至多一手非终态」这个
        # 不变量跨现金局与全部锦标赛共用。单一不变量最简单、也最不容易被
        # 绕过；按侧分别计数会让「一个人同时开一手现金局和一手赛内牌」成为
        # 可能，而两侧共用同一套动作端点与超时机制，届时哪一手该被超时任务
        # 处置将变得依赖调用顺序。代价是一手悬挂的赛内牌会挡住现金局发牌，
        # 上界是该手牌自己的超时时限。
        #
        # 取阻塞方的 `tournament_id` 而非只数个数：现金局的 `/current` 会
        # 滤掉赛内手牌（那手牌不该出现在现金局牌桌上），于是用户看到的是一个
        # 正常的下注界面，点一次报错一次，而「你还有一手牌未结束」在现金局里
        # 根本无处可寻。必须把他指回锦标赛。
        blocking = session.execute(
            select(BlackjackHand.tournament_id)
            .where(
                BlackjackHand.tg_id == int(tg_id),
                BlackjackHand.status.notin_(engine.TERMINAL_STATUSES),
            )
            .limit(1)
        ).first()
        if blocking is not None:
            if blocking[0] is not None:
                raise blackjack_error(f"hand in progress in tournament {blocking[0]}")
            raise blackjack_error("hand in progress")

        # 速率下限：读该用户最近一手的 created_at_ms，同一事务、同一把锁、
        # 零额外依赖，且不会因缓存失效而失效。
        #
        # **刻意不加 `tournament_id IS NULL`**：该限制的目的是压制脚本化高频
        # 请求与积分行锁争用，两者都与手牌属于现金局还是赛内无关。按侧分别
        # 判定等于把允许的请求频率翻倍，恰好削弱它要防的东西。
        if min_interval_seconds > 0:
            last_ms = session.execute(
                select(func.max(BlackjackHand.created_at_ms)).where(
                    BlackjackHand.tg_id == int(tg_id)
                )
            ).scalar_one_or_none()
            if last_ms is not None:
                elapsed = (now_ms - int(last_ms)) / 1000.0
                if elapsed < min_interval_seconds:
                    raise blackjack_error("deal too frequent")

        # 门槛与余额。门槛按发牌前的积分判定；注额可等于门槛，
        # 故持有恰好 30 积分的用户可一次押空至 0（已确认接受的设计）。
        credits_before = float(stats.credits)
        if credits_before < float(min_credits):
            raise blackjack_error(f"insufficient credits: need {min_credits}")
        if credits_before < float(bet_credits):
            raise blackjack_error("insufficient credits")

        mutation = credits_repository.deduct_tx(
            session, CreditAccount.tg(int(tg_id)), float(bet_credits)
        )
        credits_service.register_cache_invalidation(session, mutation)

        # 每日首手免抽水：低成本的习惯钩子，无条件发放，不需下注解锁。
        # 判定用当日零点（settings.TZ）之后的手数，走已有的
        # (tg_id, created_at_ms) 索引，不新增存储也不新增查询模式。
        free_hands = int(config.get("free_hands_per_day", 1))
        rake_waived = False
        if free_hands > 0:
            hands_today = self._count_blackjack_hands_today(session, int(tg_id))
            rake_waived = hands_today < free_hands

        # 免抽水直接落在快照上（rake_bp_on_profit=0），结算读的本来就是快照，
        # 于是 rake 自然为 0——**结算路径不需要加任何分支**
        snapshot_rake_bp = (
            0 if rake_waived else int(config.get("rake_bp_on_profit", 300))
        )

        # 牌靴定序：种子来自 secrets（对用户不可预测），牌序由种子唯一决定
        # （可复现）。种子随手牌落库，故服务端无法在要牌时换牌。
        deck_seed = secrets.token_hex(16)
        deck = engine.build_deck(deck_seed)
        player_cards, dealer_cards, next_index = engine.deal_initial(deck)

        hand = BlackjackHand(
            tg_id=int(tg_id),
            status=engine.STATUS_PLAYER_TURN,
            bet_credits=int(bet_credits),
            doubled=0,
            deck_seed=deck_seed,
            next_card_index=int(next_index),
            player_cards=json.dumps(player_cards),
            dealer_cards=json.dumps(dealer_cards),
            # 参数快照：结算读这些列而非读当前配置
            rake_bp_on_profit=snapshot_rake_bp,
            rake_jackpot_bp=int(config.get("rake_jackpot_bp", 120)),
            blackjack_payout=float(config.get("blackjack_payout", 1.5)),
            dealer_hits_soft_17=1 if config.get("dealer_hits_soft_17", False) else 0,
            hand_timeout_minutes=timeout_minutes,
            surrender_enabled=1 if config.get("surrender_enabled", True) else 0,
            rake_waived=1 if rake_waived else 0,
            created_at_ms=now_ms,
        )
        session.add(hand)
        session.flush()

        # 开局天胡直接结算，不经玩家回合
        initial = engine.evaluate_initial_deal(
            player_cards,
            dealer_cards,
            blackjack_payout=float(hand.blackjack_payout),
        )
        if initial is not None:
            result = self._settle_blackjack_hand(session, hand, jackpot_config=config)
            result["settled"] = True
            return result

        return {
            "hand": self._blackjack_hand_to_dict(hand),
            "settled": False,
        }

    def _record_blackjack_decision(
        self,
        session,
        hand_id: int,
        *,
        player_cards: list,
        dealer_upcard: str,
        can_double: bool,
        can_surrender: bool,
        hits_soft_17: bool,
        action: str,
    ) -> dict:
        """按基本策略评判玩家本次动作，累加手牌上的决策计数，返回评判结果。

        局面参数由调用方在**抢占之前**捕获后传入：抢占会把状态推进到庄家回合，
        届时 `can_double` 等判定的依据已经变了。评判要还原的是玩家做决定时看到的
        局面，不是执行之后的局面。

        `hits_soft_17` 与 `can_surrender` 取自该手牌的参数快照而非当前配置：否则
        管理员改了庄家规则或投降开关，历史手牌的准确率会跟着漂移。
        """
        from app.domains.blackjack import rules as engine

        recommended = engine.recommend_action(
            player_cards,
            dealer_upcard,
            can_double=can_double,
            hits_soft_17=hits_soft_17,
            can_surrender=can_surrender,
        )
        correct = recommended == action

        session.execute(
            update(BlackjackHand)
            .where(BlackjackHand.id == int(hand_id))
            .values(
                decisions_total=BlackjackHand.decisions_total + 1,
                decisions_correct=BlackjackHand.decisions_correct
                + (1 if correct else 0),
            )
        )
        return {"action": action, "recommended": recommended, "correct": correct}

    def _capture_decision_context(self, hand: BlackjackHand) -> dict:
        """在抢占前捕获评判所需的局面。

        `can_surrender` 由手牌快照的 `surrender_enabled` 与当前牌面共同决定，
        **不读当前配置**：存量手牌的快照为 0，其评判继续走不含投降的策略表，
        历史准确率逐位不变（设计决策 2）。要牌/停牌/加倍三条路径同样取用本方法，
        故开关打开后它们的评判也会正确地把投降建议算进去。
        """
        from app.domains.blackjack import rules as engine

        player_cards = json.loads(hand.player_cards or "[]")
        dealer_cards = json.loads(hand.dealer_cards or "[]")
        surrender_enabled = int(hand.surrender_enabled) == 1
        return {
            "player_cards": player_cards,
            "dealer_upcard": dealer_cards[0] if dealer_cards else None,
            "can_double": engine.can_double(player_cards, int(hand.status)),
            "can_surrender": surrender_enabled
            and engine.can_surrender(
                player_cards, int(hand.status), int(hand.doubled) == 1
            ),
            "hits_soft_17": int(hand.dealer_hits_soft_17) == 1,
        }

    def blackjack_hit(self, tg_id: int, hand_id: int) -> dict:
        """要牌：按游标取下一张牌；爆牌则直接结算，未爆则交还玩家回合。

        取牌只是「翻开」发牌时既已确定的牌序，不重新生成牌面。
        """

        # 奖池参数在**开启事务之前**读好：本方法的事务内若再调
        # get_blackjack_config_dict() 会另开一个 session，同时占用两个连接，
        # 且首次读取还会在新连接上写库——外层正持有行锁时足以死锁。
        jackpot_config = self.get_blackjack_config_dict()

        with get_session() as session:
            return self.blackjack_hit_tx(
                session, tg_id, hand_id, jackpot_config=jackpot_config
            )

    def blackjack_hit_tx(
        self, session, tg_id: int, hand_id: int, *, jackpot_config: dict
    ) -> dict:
        from app.domains.blackjack import rules as engine

        hand = self._lock_blackjack_hand(session, tg_id, hand_id)

        if int(hand.status) in engine.TERMINAL_STATUSES:
            raise blackjack_error("hand already finished")
        if int(hand.status) != engine.STATUS_PLAYER_TURN:
            raise blackjack_error("not player turn")

        # 评判所需的局面必须在抢占前捕获——抢占会推进状态，届时加倍是否可用
        # 等判定依据就变了
        ctx = self._capture_decision_context(hand)

        # 先原子抢占，再动任何数据：抢不到就说明手牌已被他人推进，
        # 此时若已写入新牌，事务提交会留下与 outcome 不符的牌面
        if not self._claim_blackjack_hand(session, hand_id):
            raise blackjack_error("hand already finished")
        session.expire(hand)

        decision = self._record_blackjack_decision(
            session, hand_id, action=engine.ACTION_HIT, **ctx
        )

        player_cards = json.loads(hand.player_cards or "[]")
        deck = engine.build_deck(str(hand.deck_seed))
        card, next_index = engine.draw_card(deck, int(hand.next_card_index))
        player_cards.append(card)

        hand.player_cards = json.dumps(player_cards)
        hand.next_card_index = int(next_index)
        session.flush()

        if engine.is_bust(player_cards):
            result = self._settle_blackjack_hand(
                session, hand, jackpot_config=jackpot_config
            )
            result["settled"] = bool(not result.get("already_settled"))
            result["decision"] = decision
            return result

        # 未爆：交还玩家回合，玩家可继续要牌或停牌
        self._release_blackjack_hand(session, hand_id)
        session.expire(hand)
        return {
            "hand": self._blackjack_hand_to_dict(hand),
            "settled": False,
            "decision": decision,
        }

    def blackjack_stand(self, tg_id: int, hand_id: int) -> dict:
        """停牌：转入庄家回合并结算。"""

        # 奖池参数在**开启事务之前**读好：本方法的事务内若再调
        # get_blackjack_config_dict() 会另开一个 session，同时占用两个连接，
        # 且首次读取还会在新连接上写库——外层正持有行锁时足以死锁。
        jackpot_config = self.get_blackjack_config_dict()

        with get_session() as session:
            return self.blackjack_stand_tx(
                session, tg_id, hand_id, jackpot_config=jackpot_config
            )

    def blackjack_stand_tx(
        self, session, tg_id: int, hand_id: int, *, jackpot_config: dict
    ) -> dict:
        from app.domains.blackjack import rules as engine

        hand = self._lock_blackjack_hand(session, tg_id, hand_id)

        if int(hand.status) in engine.TERMINAL_STATUSES:
            raise blackjack_error("hand already finished")
        if int(hand.status) != engine.STATUS_PLAYER_TURN:
            raise blackjack_error("not player turn")

        ctx = self._capture_decision_context(hand)

        if not self._claim_blackjack_hand(session, hand_id):
            raise blackjack_error("hand already finished")
        session.expire(hand)

        decision = self._record_blackjack_decision(
            session, hand_id, action=engine.ACTION_STAND, **ctx
        )

        result = self._settle_blackjack_hand(
            session, hand, jackpot_config=jackpot_config
        )
        result["settled"] = bool(not result.get("already_settled"))
        result["decision"] = decision
        return result

    def blackjack_double(self, tg_id: int, hand_id: int) -> dict:
        """加倍：追加扣一份基础注额 → 只发一张牌 → 自动停牌结算。

        加倍要求用户另有不少于一份基础注额的可用积分。余额不足**必须**拒绝，
        否则存在把积分打成负数的路径。
        """

        # 奖池参数在**开启事务之前**读好：本方法的事务内若再调
        # get_blackjack_config_dict() 会另开一个 session，同时占用两个连接，
        # 且首次读取还会在新连接上写库——外层正持有行锁时足以死锁。
        jackpot_config = self.get_blackjack_config_dict()

        with get_session() as session:
            return self.blackjack_double_tx(
                session, tg_id, hand_id, jackpot_config=jackpot_config
            )

    def blackjack_double_tx(
        self, session, tg_id: int, hand_id: int, *, jackpot_config: dict
    ) -> dict:
        from app.domains.blackjack import rules as engine

        hand = self._lock_blackjack_hand(session, tg_id, hand_id)

        if int(hand.status) in engine.TERMINAL_STATUSES:
            raise blackjack_error("hand already finished")
        if int(hand.status) != engine.STATUS_PLAYER_TURN:
            raise blackjack_error("not player turn")
        if int(hand.doubled) == 1:
            raise blackjack_error("already doubled")

        player_cards = json.loads(hand.player_cards or "[]")
        # 加倍仅限手中恰为初始两张牌时；已要牌后不可加倍
        if not engine.can_double(player_cards, int(hand.status)):
            raise blackjack_error("cannot double after hit")

        bet = int(hand.bet_credits)
        ctx = self._capture_decision_context(hand)

        # **抢占必须早于扣分**：否则抢占失败时追加的注额已被扣掉，
        # 而结算又不会赔付，用户白损失一份注额
        if not self._claim_blackjack_hand(session, hand_id):
            raise blackjack_error("hand already finished")
        session.expire(hand)

        stats = (
            session.execute(
                select(Statistics)
                .where(Statistics.tg_id == int(tg_id))
                .with_for_update()
            )
            .scalars()
            .one_or_none()
        )
        if not stats:
            raise blackjack_error("user stats not found")
        if float(stats.credits) < float(bet):
            # 事务回滚会把 status 恢复为玩家回合，手牌不受影响
            raise blackjack_error(f"insufficient credits to double: need {bet}")

        # 余额校验通过后才记决策：校验失败会整体回滚，此时不该留下决策计数
        decision = self._record_blackjack_decision(
            session, hand_id, action=engine.ACTION_DOUBLE, **ctx
        )

        mutation = credits_repository.deduct_tx(
            session, CreditAccount.tg(int(tg_id)), float(bet)
        )
        credits_service.register_cache_invalidation(session, mutation)

        player_cards = json.loads(hand.player_cards or "[]")
        deck = engine.build_deck(str(hand.deck_seed))
        card, next_index = engine.draw_card(deck, int(hand.next_card_index))
        player_cards.append(card)

        hand.doubled = 1
        hand.player_cards = json.dumps(player_cards)
        hand.next_card_index = int(next_index)
        session.flush()

        # 加倍后只发一张并自动停牌；若该张牌导致爆牌，结算路径判负
        result = self._settle_blackjack_hand(
            session, hand, jackpot_config=jackpot_config
        )
        result["settled"] = bool(not result.get("already_settled"))
        result["decision"] = decision
        return result

    def blackjack_surrender(self, tg_id: int, hand_id: int) -> dict:
        """投降：返还一半基础注额，手牌立即结算，不经庄家回合。

        **不走 `_settle_blackjack_hand()`**（设计决策 4）：那条路径的职责是「让庄家
        补牌后按牌面判胜负」，而投降没有胜负——`resolve()` 的三元组里没有它的位置
        （`profit_multiplier` 恒为 0 但 `return_multiplier` 是 0.5，不是 stake 的
        整数倍）。硬塞进去要给一个纯按牌面判定的函数加一个与牌面无关的分支。

        比停牌短，少了三件事：不补牌、不抽水（返还额本就是净亏损，无赢利可抽）、
        不触碰奖池（投降的时点为手中恰两张牌，同花天胡在发牌阶段已结算、三张 7
        需要三张牌，两种牌型都在该时点之外——持一对 7 投降即放弃了凑成的可能）。

        幂等与并发照既有纪律：先 `_claim_blackjack_hand()` 抢占（把 status 从玩家
        回合原子地推进到庄家回合），抢不到即说明已被其他请求或超时任务处理，直接
        放弃且不做任何写入；随后的终态写入同样带 `WHERE status NOT IN (终态)`
        条件，构成第二道闸门。加锁顺序仍为手牌 → statistics。

        投降对留存机制是中性的：连败计数不变（投降是策略性离场，且计入连败
        会打开「投降凑救济」的口子），但仍计入免费机会的手数——它是已结算
        的现金局手牌。
        """

        # 配置在事务外读好：事务内读会另开连接，外层正持有行锁时会死锁
        config = self.get_blackjack_config_dict()

        with get_session() as session:
            return self.blackjack_surrender_tx(session, tg_id, hand_id, config=config)

    def blackjack_surrender_tx(
        self, session, tg_id: int, hand_id: int, *, config: dict
    ) -> dict:
        from app.domains.blackjack import rules as engine

        hand = self._lock_blackjack_hand(session, tg_id, hand_id)

        if int(hand.status) in engine.TERMINAL_STATUSES:
            raise blackjack_error("hand already finished")
        if int(hand.status) != engine.STATUS_PLAYER_TURN:
            raise blackjack_error("not player turn")

        # 开关取该手牌的**快照**而非当前配置：管理员在玩家思考期间关闭开关，
        # 已渲染出投降按钮的手牌仍应可投降（spec：关闭投降不影响进行中手牌）
        if int(hand.surrender_enabled) != 1:
            raise blackjack_error("surrender disabled")

        if int(hand.doubled) == 1:
            raise blackjack_error("cannot surrender after double")

        player_cards = json.loads(hand.player_cards or "[]")
        if not engine.can_surrender(
            player_cards, int(hand.status), int(hand.doubled) == 1
        ):
            raise blackjack_error("cannot surrender after hit")

        bet = int(hand.bet_credits)
        ctx = self._capture_decision_context(hand)

        # 抢占先于任何写入：抢不到就说明手牌已被他人推进或结算，
        # 此时若已入账，事务提交会造成重复赔付
        if not self._claim_blackjack_hand(session, hand_id):
            raise blackjack_error("hand already finished")
        session.expire(hand)

        # 投降本身也是一次决策，与要牌/停牌/加倍同样计入准确率
        decision = self._record_blackjack_decision(
            session, hand_id, action=engine.ACTION_SURRENDER, **ctx
        )

        # 返还比例固定为二分之一（不可配置，见 DEFAULT_BLACKJACK_CONFIG 的注释）
        payout = round(float(bet) * 0.5, 2)
        now_ts = int(time.time())

        # 第二道幂等闸门：只有把手牌从非终态原子地改成终态的那一方才入账。
        # `with_for_update()` 在 SQLite 上是 no-op，故不能只靠上方的读取判断。
        # `jackpot_won` 保持 NULL——投降不触发奖池派彩。
        session.flush()
        claimed = session.execute(
            update(BlackjackHand)
            .where(
                BlackjackHand.id == int(hand_id),
                BlackjackHand.status.notin_(engine.TERMINAL_STATUSES),
            )
            .values(
                status=engine.STATUS_SETTLED,
                outcome=engine.OUTCOME_SURRENDER,
                payout_credits=float(payout),
                rake_credits=0.0,
                settled_at=now_ts,
            )
        )
        if claimed.rowcount == 0:
            session.expire(hand)
            return {
                "hand": self._blackjack_hand_to_dict(hand),
                "already_settled": True,
                "settled": False,
            }
        session.expire(hand)

        stats = (
            session.execute(
                select(Statistics)
                .where(Statistics.tg_id == int(tg_id))
                .with_for_update()
            )
            .scalars()
            .one_or_none()
        )
        if stats:
            mutation = credits_repository.add_tx(
                session, CreditAccount.tg(int(tg_id)), payout
            )
            credits_service.register_cache_invalidation(session, mutation)
        else:
            session.add(Statistics(tg_id=int(tg_id), donation=0, credits=float(payout)))

        # 留存钩子：连败计数对投降中立（钩子内 outcome='surrender'
        # 不改计数），手数 +1 并按阈值发放免费机会
        retention = self.apply_blackjack_retention_tx(
            session,
            hand,
            stats,
            outcome=engine.OUTCOME_SURRENDER,
            config=config,
            now_ts=now_ts,
        )

        session.flush()

        return {
            "hand": self._blackjack_hand_to_dict(hand),
            "already_settled": False,
            "settled": True,
            "outcome": engine.OUTCOME_SURRENDER,
            "payout_credits": payout,
            "rake_credits": 0.0,
            "jackpot_won": 0.0,
            "jackpot_in": 0.0,
            "relief_credits": retention["relief_credits"],
            "freespins": retention["freespins"],
            "decision": decision,
        }

    def _lock_blackjack_hand(
        self, session, tg_id: int, hand_id: int, *, cash_only: bool = True
    ) -> BlackjackHand:
        """取手牌行并加锁，校验归属。锁顺序的第一步。

        `cash_only=True`（默认）会**拒绝赛内手牌**。这不是可选的洁癖：现金局的
        四个动作端点只按 hand_id 取牌，若不拦，用户把赛内手牌的 id 提交到
        `/blackjack/{id}/stand` 就会走现金局适配层——那会拿筹码注额算出一笔钱
        赔进他的**积分**，并把筹码数按抽水比例注进幸运奖池。两侧的 id 空间共用
        同一张表，故这道检查必须在加锁处而不是各端点里，漏一个端点即是漏洞。

        赛内路径用 `_lock_tournament_hand`（它以 `cash_only=False` 调用本方法，
        再反向要求 `tournament_id` 非空），两个方向各自把对面的手牌挡在外面。
        """
        hand = (
            session.execute(
                select(BlackjackHand)
                .where(BlackjackHand.id == int(hand_id))
                .with_for_update()
            )
            .scalars()
            .one_or_none()
        )
        if not hand:
            raise blackjack_error("hand not found")
        if int(hand.tg_id) != int(tg_id):
            raise blackjack_error("hand not found")
        if cash_only and hand.tournament_id is not None:
            raise blackjack_error("hand not found")
        return hand

    def _claim_blackjack_hand(
        self, session, hand_id: int, *, allow_dealer_turn: bool = False
    ) -> bool:
        """把手牌从「玩家回合」原子地推进到「庄家回合」，宣告本事务独占它。

        这是所有改动手牌的动作（要牌/停牌/加倍/超时结算）的**第一步**，必须在
        任何写操作之前完成。返回 False 说明抢占失败——手牌已被他人推进或结算，
        调用方必须立即放弃，不得做任何写入。

        为什么必须先抢占再写：`with_for_update()` 在 SQLite 上是 no-op，若沿用
        「读 status 判断 → 写 → 结算时再 CAS」的顺序，加倍会先扣掉一份注额、
        要牌会先写入一张新牌，而随后的结算 CAS 可能失败——此时事务仍会提交那些
        写入，造成**扣了钱不赔付**与**牌面和 outcome 不一致**。把闸门提到最前面，
        写操作就只发生在独占成立之后。

        `status=2`（庄家回合）在此同时充当独占标记与 spec 所述的中间状态：
        玩家回合 → 庄家回合 → 已结算。它只在事务内可见，事务回滚即恢复为 1。

        `allow_dealer_turn=True` 供超时兜底与定时清理使用，把可抢占的状态放宽到
        全部非终态。理由：判定「手牌是否还活着」的地方（兜底扫描、进行中手牌
        计数）用的都是 `status NOT IN (终态)`，而抢占只认 status=1；两个谓词一旦
        不一致，任何以 status=2 落库的行都会**既被视为进行中、又永远抢不到**，
        用户将带着已扣的押注被永久锁在活动之外且无自愈路径。正常流程下 status=2
        不会跨事务存活，故这是纯粹的恢复能力，不改变常规路径的语义。
        """
        from app.domains.blackjack import rules as engine

        claimable = (
            [engine.STATUS_PLAYER_TURN, engine.STATUS_DEALER_TURN]
            if allow_dealer_turn
            else [engine.STATUS_PLAYER_TURN]
        )
        session.flush()
        claimed = session.execute(
            update(BlackjackHand)
            .where(
                BlackjackHand.id == int(hand_id),
                BlackjackHand.status.in_(claimable),
            )
            .values(status=engine.STATUS_DEALER_TURN)
        )
        return claimed.rowcount == 1

    def _release_blackjack_hand(self, session, hand_id: int) -> None:
        """把手牌交还「玩家回合」——要牌未爆时用，使玩家可继续操作。"""
        from app.domains.blackjack import rules as engine

        session.execute(
            update(BlackjackHand)
            .where(
                BlackjackHand.id == int(hand_id),
                BlackjackHand.status == engine.STATUS_DEALER_TURN,
            )
            .values(status=engine.STATUS_PLAYER_TURN)
        )

    def settle_blackjack_hand_by_timeout(self, hand_id: int) -> dict:
        """超时兜底：由调度任务调用，等同于玩家停牌。

        与用户操作撞车时由抢占闸门保证只结算一次：抢不到即返回既有结果。
        """
        # 奖池参数在**开启事务之前**读好：本方法的事务内若再调
        # get_blackjack_config_dict() 会另开一个 session，同时占用两个连接，
        # 且首次读取还会在新连接上写库——外层正持有行锁时足以死锁。
        jackpot_config = self.get_blackjack_config_dict()

        with get_session() as session:
            return self.settle_blackjack_hand_by_timeout_tx(
                session, hand_id, jackpot_config=jackpot_config
            )

    def settle_blackjack_hand_by_timeout_tx(
        self, session, hand_id: int, *, jackpot_config: dict
    ) -> dict:
        hand = (
            session.execute(
                select(BlackjackHand)
                .where(BlackjackHand.id == int(hand_id))
                .with_for_update()
            )
            .scalars()
            .one_or_none()
        )
        if not hand:
            raise blackjack_error("hand not found")

        if not self._claim_blackjack_hand(session, int(hand_id)):
            # 用户已抢先操作或已结算，本次不再介入
            session.expire(hand)
            return {
                "hand": self._blackjack_hand_to_dict(hand),
                "already_settled": True,
            }
        session.expire(hand)
        return self._settle_blackjack_hand_dispatch(
            session, hand, abandoned=True, jackpot_config=jackpot_config
        )

    def get_current_blackjack_hand(self, tg_id: int) -> dict | None:
        """取该用户处于非终态的手牌，供恢复牌桌用。没有则返回 None。

        **本方法不是纯读操作**：它先调 `sweep_timed_out_blackjack_hands`（独立
        事务）清掉该用户已超时的手牌，那一步会改积分、动奖池。之所以仍留在这条
        读路径上：用户重新打开牌桌时必须看到正确的状态，若只依赖 10 分钟一次的
        定时兜底，最长会有 10 分钟看到一手早该结算的牌，且此期间无法开新局。

        代价是 GET 具有副作用，重试与预取都会触发结算。这一点靠幂等性兜住——
        结算由条件 UPDATE 把关，重复触发不会重复赔付，最坏情况只是多跑一次空扫描。
        """
        from app.domains.blackjack import rules as engine

        # 先清掉该用户已超时的手牌，避免返回一手早该结算的牌
        self.sweep_timed_out_blackjack_hands(tg_id=int(tg_id))

        with get_session() as session:
            hand = (
                session.execute(
                    select(BlackjackHand)
                    .where(
                        BlackjackHand.tg_id == int(tg_id),
                        BlackjackHand.status.notin_(engine.TERMINAL_STATUSES),
                    )
                    .order_by(BlackjackHand.created_at_ms.desc())
                )
                .scalars()
                .first()
            )
            if not hand:
                return None
            return self._blackjack_hand_to_dict(hand)

    def list_active_blackjack_hands(self) -> list[dict]:
        """列出所有非终态的手牌，供启动时重建超时任务用。

        **刻意不加 `tournament_id IS NULL`**：赛内手牌同样受单手超时兜底约束，
        重启后也必须重建其超时任务。此处漏掉赛内手牌会让它们在重启后失去及时性
        保障，只能等每 10 分钟的全量兜底——而全量兜底本就是最后一层，不该被当作
        常规路径。结算时走哪个适配层由 `_settle_blackjack_hand_dispatch` 按
        `tournament_id` 分派，与本方法无关。
        """
        from app.domains.blackjack import rules as engine

        try:
            with get_session() as session:
                rows = session.execute(
                    select(
                        BlackjackHand.id,
                        BlackjackHand.tg_id,
                        BlackjackHand.created_at_ms,
                        BlackjackHand.hand_timeout_minutes,
                    ).where(BlackjackHand.status.notin_(engine.TERMINAL_STATUSES))
                ).all()
                return [
                    {
                        "id": int(r[0]),
                        "tg_id": int(r[1]),
                        "created_at_ms": int(r[2]),
                        "hand_timeout_minutes": int(r[3]),
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"列出进行中的 21 点手牌失败: {e}")
            return []
