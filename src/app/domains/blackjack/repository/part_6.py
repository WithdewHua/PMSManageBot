import json
import secrets
import time

from sqlalchemy import func, select, update

from app.core.db import get_session
from app.core.log import logger
from app.domains.badges.models import UserBadge
from app.domains.blackjack.models import (
    BlackjackHand,
    BlackjackTournament,
)
from app.domains.identity.models import Statistics


class _BlackjackRepositoryPart6:
    def _settle_blackjack_tournament_hand(
        self,
        session,
        hand: BlackjackHand,
        abandoned: bool = False,
    ) -> dict:
        """赛内结算：停牌 / 加倍 / 爆牌 / 投降 / 超时兜底 / 赛事清场共用这一条。

        **本方法是 `_settle_blackjack_hand` 的同构复刻，不是它的一个分支。**
        引擎完全共用（`resolve()` 返回的是相对基础注额的倍率，与钱还是筹码无关），
        差异全在适配层：

        | | 现金局 | 赛内 |
        |---|---|---|
        | 加锁对象 | `Statistics` | `BlackjackTournamentEntry` |
        | 抽水 | 按快照计取 | **不计** —— 已在报名费上一次性收过 |
        | 幸运奖池 | 派彩 + 注入 | **不碰** —— 筹码不是积分，注进去等于凭空造钱 |
        | 决策计数 | 落库 | **不写**（恒为 0） |
        | 取整 | `round(x, 2)` | `floor` —— 筹码是整数 |

        为什么不在现有函数里加三条 `if hand.tournament_id`：那个函数已 200 余行，
        其中相当篇幅是历史事故的说明；穿上分支后每一条既有推理都要重新验证「在
        赛内这一支是否仍成立」。两个函数各自短、各自能被读完，比一个长函数便宜。

        代价是 CAS 闸门被复制了一份。**这是有意接受的**：那段逻辑最不该「聪明地
        复用」——把它抽成公共 helper 会让闸门与其保护的写操作在源码上分离，而现金局
        踩过的事故恰恰是「闸门晚于写操作」导致扣了钱不赔付。宁可两份都显式。

        锁序 hand → entry。赛内结算**完全不触及 `Statistics`**，故赛内高频路径与
        积分行锁彻底解耦。

        调用方须已对 `hand` 行取过 FOR UPDATE 并完成抢占。
        """
        from app.domains.blackjack import rules as engine

        # 廉价前置检查：多数重复请求在此被挡掉。**不是**幂等的保证——真正的
        # 保证是下方的条件 UPDATE
        if int(hand.status) in engine.TERMINAL_STATUSES:
            return self._tournament_already_settled_result(session, hand)

        hand_id = int(hand.id)
        tg_id = int(hand.tg_id)
        tournament_id = int(hand.tournament_id)
        bet = int(hand.bet_credits)
        doubled = int(hand.doubled) == 1
        player_cards = json.loads(hand.player_cards or "[]")
        dealer_cards = json.loads(hand.dealer_cards or "[]")

        # 按手牌上的快照结算（快照来自赛事，赛事又快照自创建时的全局配置）
        blackjack_payout = float(hand.blackjack_payout)
        hits_soft_17 = int(hand.dealer_hits_soft_17) == 1

        deck = engine.build_deck(str(hand.deck_seed))
        next_index = int(hand.next_card_index)

        # 庄家在两种情形下不补牌：玩家爆牌，或开局任一方天胡（天胡在发牌阶段
        # 即已结算，庄家从未开始行动）。漏掉后者会把幽灵牌写进 dealer_cards，
        # 前端于是回放一段完全编造的庄家补牌过程
        settled_on_deal = engine.is_natural_blackjack(
            player_cards
        ) or engine.is_natural_blackjack(dealer_cards)
        if engine.is_bust(player_cards) or settled_on_deal:
            final_dealer_cards = dealer_cards
        else:
            final_dealer_cards, next_index = engine.play_dealer(
                deck, dealer_cards, next_index, hits_soft_17=hits_soft_17
            )

        outcome, return_multiplier, _profit_multiplier = engine.resolve(
            player_cards,
            final_dealer_cards,
            doubled=doubled,
            blackjack_payout=blackjack_payout,
        )

        # 筹码为整数，赔付向下取整。注额被约束为步进的整数倍，故 3:2 赔率下
        # `2.5 × bet` 必为整数，取整实际不会触发；只有管理员把赔率设成非常规值
        # 时才生效，量级在 1 筹码以内。`_profit_multiplier` 在赛内无用武之地
        # ——它是给抽水算基数的，而赛内不抽水。
        #
        # **先 round 到分位再取整**，不直接 `int(a * b)`：二进制浮点会让本该整数的
        # 乘积落在整数下方（如 1.2 赔率下某些注额算出 x.999999999999），`int()`
        # 向零截断就白吃掉玩家 1 个筹码，而那正是这段注释声称不会发生的事。
        payout = int(round(float(return_multiplier) * float(bet), 2))

        final_status = engine.STATUS_ABANDONED if abandoned else engine.STATUS_SETTLED
        now_ts = int(time.time())

        # 以上都是无副作用的纯计算。幂等闸门在此：只有把手牌从非终态原子地改成
        # 终态的那一方，才有权继续写筹码
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
                # 赛内不抽水，显式写 0 而非留空：留空会让「这手没抽水」与
                # 「这手还没结算」在审计时无法区分
                rake_credits=0.0,
                dealer_cards=json.dumps(final_dealer_cards),
                next_card_index=int(next_index),
                settled_at=now_ts,
            )
        )
        if claimed.rowcount == 0:
            session.expire(hand)
            return self._tournament_already_settled_result(session, hand)

        session.expire(hand)

        # 抢占成功，本次结算生效。锁序 hand → entry
        entry = self._lock_tournament_entry(session, tournament_id, tg_id)
        tournament = (
            session.execute(
                select(BlackjackTournament).where(
                    BlackjackTournament.id == tournament_id
                )
            )
            .scalars()
            .one_or_none()
        )
        total_hands = int(tournament.total_hands) if tournament else 0

        entry.chips = int(entry.chips) + int(payout)
        entry.hands_played = int(entry.hands_played) + 1
        self._apply_tournament_entry_terminal_status(entry, tournament)

        session.flush()

        return {
            "hand": self._blackjack_hand_to_dict(hand),
            "already_settled": False,
            "outcome": outcome,
            "payout_credits": float(payout),
            "chips": int(entry.chips),
            "hands_played": int(entry.hands_played),
            "entry_status": int(entry.status),
            # 捎回总手数，省掉路由层为算「剩余手数」而多打的一次赛事查询
            "total_hands": total_hands,
        }

    def _settle_blackjack_hand_dispatch(
        self,
        session,
        hand: BlackjackHand,
        abandoned: bool = False,
        jackpot_config: dict | None = None,
    ) -> dict:
        """按 `tournament_id` 选结算适配层。

        超时任务、定时兜底与赛事清场三条入口共用本函数，避免三处各写一遍判断
        ——漏掉任何一处都会让赛内手牌走现金局的适配层：那会给用户的**积分**
        赔付一笔按筹码算出来的钱，并把筹码注额当积分注进幸运奖池。
        """
        if hand.tournament_id is not None:
            return self._settle_blackjack_tournament_hand(
                session, hand, abandoned=abandoned
            )
        return self._settle_blackjack_hand(
            session, hand, abandoned=abandoned, jackpot_config=jackpot_config
        )

    def create_blackjack_tournament_hand(
        self, tg_id: int, tournament_id: int, bet_chips: int
    ) -> dict:
        """赛内发牌：校验 → 扣筹码 → 定序 → 发初始牌 → 天胡则直接结算。

        锁序 tournament → entry → statistics。赛事行靠 `_lock_running_tournament`
        的条件 UPDATE 钉住，不能用 `with_for_update()`——SQLite 上那是 no-op，
        截止边界上发牌会与结算 CAS 交错，把新手牌插进已派奖的赛事。

        **为什么还要锁一行自己根本不修改的 `Statistics`**：
        「同一用户同时至多一手非终态」这个不变量跨现金局与全部赛事共用，而现金局
        发牌正是以该用户的 `Statistics` 行锁作为串行化点。赛内若只锁 entry，一个
        用户并发发起「现金局发牌 + 赛内发牌」会各持一把互不相干的锁，双双通过
        「无进行中手牌」检查，于是同时开出两手牌——两侧共用同一套动作端点与超时
        机制，届时哪一手该被处置将取决于调用顺序。锁同一行是让该不变量真正成立
        的唯一办法，代价只是一次单行加锁。

        Returns: {hand, settled(bool), chips, ...}
        """
        from app.domains.blackjack import rules as engine

        # 惰性清理走独立事务并先行提交，理由同现金局：不寄生在发牌事务里，
        # 否则后续任何一次校验失败都会把已完成的结算连带回滚
        self.sweep_timed_out_blackjack_hands(tg_id=int(tg_id))

        config = self.get_blackjack_config_dict()
        min_interval_seconds = float(config.get("min_deal_interval_seconds", 1))

        with get_session() as session:
            tournament = self._lock_running_tournament(session, int(tournament_id))
            if not tournament:
                exists = session.execute(
                    select(BlackjackTournament.id).where(
                        BlackjackTournament.id == int(tournament_id)
                    )
                ).first()
                if not exists:
                    raise ValueError("tournament not found")
                raise ValueError("tournament not running")
            # 截止必须用锁后的墙钟。进 session 之前冻住的 `now_ms` 若在等锁期间
            # 已经过了完赛截止，继续用它会把新手牌送进清场与 CAS 之间。
            now_ms = int(time.time() * 1000)
            if now_ms >= int(tournament.play_deadline_ms):
                raise ValueError("tournament finished")

            entry = self._lock_tournament_entry(session, int(tournament_id), int(tg_id))
            if int(entry.status) == self.ENTRY_FINISHED:
                raise ValueError("all hands played")
            if int(entry.status) == self.ENTRY_ELIMINATED:
                raise ValueError("eliminated")

            total_hands = int(tournament.total_hands)
            if int(entry.hands_played) >= total_hands:
                raise ValueError("all hands played")

            # 注额校验：区间内、步进的整数倍、不超过当前筹码
            bet = int(bet_chips)
            step = int(tournament.bet_step_chips)
            min_bet = int(tournament.min_bet_chips)
            max_bet = int(tournament.max_bet_chips)
            if bet % step:
                raise ValueError(f"bet must be a multiple of {step}")
            if bet < min_bet or bet > max_bet:
                raise ValueError(f"bet out of range: {min_bet}~{max_bet}")
            if bet > int(entry.chips):
                raise ValueError("insufficient chips")

            # 见方法 docstring：这一行只锁不改，是全局「至多一手」不变量的串行化点
            session.execute(
                select(Statistics.tg_id)
                .where(Statistics.tg_id == int(tg_id))
                .with_for_update()
            )

            # 「同时至多一手」与发牌速率两项**跨现金局与赛内共同计算**，
            # 故此处不加 tournament_id 过滤。同样取阻塞方的归属，好把用户指回
            # 正确的那张牌桌——现金局的牌与别场赛事的牌在本赛事界面里都看不见
            blocking = session.execute(
                select(BlackjackHand.tournament_id)
                .where(
                    BlackjackHand.tg_id == int(tg_id),
                    BlackjackHand.status.notin_(engine.TERMINAL_STATUSES),
                )
                .limit(1)
            ).first()
            if blocking is not None:
                blocking_tid = blocking[0]
                if blocking_tid is None:
                    raise ValueError("hand in progress in cash game")
                if int(blocking_tid) != int(tournament_id):
                    raise ValueError(f"hand in progress in tournament {blocking_tid}")
                raise ValueError("hand in progress")

            if min_interval_seconds > 0:
                last_ms = session.execute(
                    select(func.max(BlackjackHand.created_at_ms)).where(
                        BlackjackHand.tg_id == int(tg_id)
                    )
                ).scalar_one_or_none()
                if last_ms is not None:
                    elapsed = (now_ms - int(last_ms)) / 1000.0
                    if elapsed < min_interval_seconds:
                        raise ValueError("deal too frequent")

            entry.chips = int(entry.chips) - bet

            deck_seed = secrets.token_hex(16)
            deck = engine.build_deck(deck_seed)
            player_cards, dealer_cards, next_index = engine.deal_initial(deck)

            hand = BlackjackHand(
                tg_id=int(tg_id),
                tournament_id=int(tournament_id),
                status=engine.STATUS_PLAYER_TURN,
                bet_credits=bet,
                doubled=0,
                deck_seed=deck_seed,
                next_card_index=int(next_index),
                player_cards=json.dumps(player_cards),
                dealer_cards=json.dumps(dealer_cards),
                # 参数快照取自**赛事**而非当前全局配置
                blackjack_payout=float(tournament.blackjack_payout),
                dealer_hits_soft_17=int(tournament.dealer_hits_soft_17),
                surrender_enabled=int(tournament.surrender_enabled),
                hand_timeout_minutes=int(tournament.hand_timeout_minutes),
                # 赛内不抽水：快照写 0，结算路径读的本来就是快照。`rake_waived`
                # 保持 0——那一列的语义是「当日首手免抽水」，赛内根本不在那个
                # 体系里，标成 1 会让审计误以为它消耗了免抽水额度
                rake_bp_on_profit=0,
                rake_jackpot_bp=0,
                rake_waived=0,
                created_at_ms=now_ms,
            )
            session.add(hand)
            session.flush()

            initial = engine.evaluate_initial_deal(
                player_cards,
                dealer_cards,
                blackjack_payout=float(hand.blackjack_payout),
            )
            if initial is not None:
                result = self._settle_blackjack_tournament_hand(session, hand)
                result["settled"] = True
                return result

            return {
                "hand": self._blackjack_hand_to_dict(hand),
                "settled": False,
                "chips": int(entry.chips),
                "hands_played": int(entry.hands_played),
                "entry_status": int(entry.status),
                "total_hands": total_hands,
            }

    def _lock_tournament_hand(self, session, tg_id: int, hand_id: int) -> BlackjackHand:
        """取赛内手牌行并加锁，校验归属、确实属于某场赛事、且该赛事仍可操作。

        与 `_lock_blackjack_hand` 的 `cash_only` 构成双向隔离：现金局手牌被提交到
        赛内端点时同样按「找不到」拒绝，绝不能在此按筹码结算——那会让一手用积分
        押注的牌把赔付写进某场赛事的筹码栈。

        **完赛截止闸门必须在这里，而不是只在发牌处**：清场与排名是两个相邻但独立
        的事务，若截止后仍放行动作，一个恰好挤在两者之间的 `double` 会让该玩家
        带着已扣未赔的筹码参与排名，之后那手牌再把赔付写回一场已经派完奖的赛事。
        锁序 hand → tournament，与结算路径一致。
        """
        hand = self._lock_blackjack_hand(session, tg_id, hand_id, cash_only=False)
        if hand.tournament_id is None:
            raise ValueError("hand not found")

        tournament = (
            session.execute(
                select(BlackjackTournament).where(
                    BlackjackTournament.id == int(hand.tournament_id)
                )
            )
            .scalars()
            .one_or_none()
        )
        if not tournament:
            raise ValueError("tournament not found")
        if int(tournament.status) != self.TOURNAMENT_RUNNING:
            raise ValueError("tournament not running")
        if int(time.time() * 1000) >= int(tournament.play_deadline_ms):
            # 清场任务会把它按停牌口径结算，不因截止判负。
            # 动作路径不加赛事写锁：锁序是 hand → tournament，与发牌/
            # 结算的 tournament → entry 交错会死锁。本路径只改已存在的
            # 手牌，未终结牌由清场按手牌事务处理。
            raise ValueError("tournament finished")
        return hand

    def blackjack_tournament_hit(self, tg_id: int, hand_id: int) -> dict:
        """赛内要牌。**不记录决策评判**——赛内的正解与基本策略并不一致。"""
        from app.domains.blackjack import rules as engine

        with get_session() as session:
            hand = self._lock_tournament_hand(session, tg_id, hand_id)

            if int(hand.status) in engine.TERMINAL_STATUSES:
                raise ValueError("hand already finished")
            if int(hand.status) != engine.STATUS_PLAYER_TURN:
                raise ValueError("not player turn")

            # 先原子抢占，再动任何数据
            if not self._claim_blackjack_hand(session, hand_id):
                raise ValueError("hand already finished")
            session.expire(hand)

            player_cards = json.loads(hand.player_cards or "[]")
            deck = engine.build_deck(str(hand.deck_seed))
            card, next_index = engine.draw_card(deck, int(hand.next_card_index))
            player_cards.append(card)

            hand.player_cards = json.dumps(player_cards)
            hand.next_card_index = int(next_index)
            session.flush()

            if engine.is_bust(player_cards):
                result = self._settle_blackjack_tournament_hand(session, hand)
                result["settled"] = bool(not result.get("already_settled"))
                return result

            self._release_blackjack_hand(session, hand_id)
            session.expire(hand)
            return {
                "hand": self._blackjack_hand_to_dict(hand),
                "settled": False,
                **self._tournament_entry_state(
                    session, int(hand.tournament_id), int(tg_id)
                ),
            }

    def blackjack_tournament_stand(self, tg_id: int, hand_id: int) -> dict:
        """赛内停牌：转入庄家回合并结算。"""
        from app.domains.blackjack import rules as engine

        with get_session() as session:
            hand = self._lock_tournament_hand(session, tg_id, hand_id)

            if int(hand.status) in engine.TERMINAL_STATUSES:
                raise ValueError("hand already finished")
            if int(hand.status) != engine.STATUS_PLAYER_TURN:
                raise ValueError("not player turn")

            if not self._claim_blackjack_hand(session, hand_id):
                raise ValueError("hand already finished")
            session.expire(hand)

            result = self._settle_blackjack_tournament_hand(session, hand)
            result["settled"] = bool(not result.get("already_settled"))
            return result

    def blackjack_tournament_double(self, tg_id: int, hand_id: int) -> dict:
        """赛内加倍：追加扣一份注额的筹码 → 只发一张 → 自动停牌结算。

        余额不足必须拒绝，否则存在把筹码打成负数的路径。
        """
        from app.domains.blackjack import rules as engine

        with get_session() as session:
            hand = self._lock_tournament_hand(session, tg_id, hand_id)

            if int(hand.status) in engine.TERMINAL_STATUSES:
                raise ValueError("hand already finished")
            if int(hand.status) != engine.STATUS_PLAYER_TURN:
                raise ValueError("not player turn")
            if int(hand.doubled) == 1:
                raise ValueError("already doubled")

            player_cards = json.loads(hand.player_cards or "[]")
            if not engine.can_double(player_cards, int(hand.status)):
                raise ValueError("cannot double after hit")

            bet = int(hand.bet_credits)
            tournament_id = int(hand.tournament_id)

            # **抢占必须早于扣筹码**：否则抢占失败时追加的注额已被扣掉，
            # 而结算又不会赔付，用户白损失一份注额
            if not self._claim_blackjack_hand(session, hand_id):
                raise ValueError("hand already finished")
            session.expire(hand)

            entry = self._lock_tournament_entry(session, tournament_id, int(tg_id))
            if int(entry.chips) < bet:
                # 事务回滚会把 status 恢复为玩家回合，手牌不受影响
                raise ValueError(f"insufficient chips to double: need {bet}")
            entry.chips = int(entry.chips) - bet

            player_cards = json.loads(hand.player_cards or "[]")
            deck = engine.build_deck(str(hand.deck_seed))
            card, next_index = engine.draw_card(deck, int(hand.next_card_index))
            player_cards.append(card)

            hand.doubled = 1
            hand.player_cards = json.dumps(player_cards)
            hand.next_card_index = int(next_index)
            session.flush()

            result = self._settle_blackjack_tournament_hand(session, hand)
            result["settled"] = bool(not result.get("already_settled"))
            return result

    def blackjack_tournament_surrender(self, tg_id: int, hand_id: int) -> dict:
        """赛内投降：返还一半基础注额的筹码，立即结算，不经庄家回合。

        返还比例固定为二分之一，与现金局同一口径。筹码为整数，故返还额向下取整
        ——注额被约束为步进（默认 10）的整数倍，实际不会产生小数。
        """
        from app.domains.blackjack import rules as engine

        with get_session() as session:
            hand = self._lock_tournament_hand(session, tg_id, hand_id)

            if int(hand.status) in engine.TERMINAL_STATUSES:
                raise ValueError("hand already finished")
            if int(hand.status) != engine.STATUS_PLAYER_TURN:
                raise ValueError("not player turn")
            if int(hand.surrender_enabled) != 1:
                raise ValueError("surrender disabled")

            player_cards = json.loads(hand.player_cards or "[]")
            if not engine.can_surrender(
                player_cards, int(hand.status), int(hand.doubled) == 1
            ):
                raise ValueError("cannot surrender now")

            bet = int(hand.bet_credits)
            tournament_id = int(hand.tournament_id)

            if not self._claim_blackjack_hand(session, hand_id):
                raise ValueError("hand already finished")
            session.expire(hand)

            payout = int(bet // 2)
            now_ts = int(time.time())

            # 第二道幂等闸门。投降不经庄家回合，故 dealer_cards 与游标一律不动
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
                result = self._tournament_already_settled_result(session, hand)
                result["settled"] = False
                return result
            session.expire(hand)

            entry = self._lock_tournament_entry(session, tournament_id, int(tg_id))
            tournament = (
                session.execute(
                    select(BlackjackTournament).where(
                        BlackjackTournament.id == tournament_id
                    )
                )
                .scalars()
                .one_or_none()
            )
            entry.chips = int(entry.chips) + payout
            entry.hands_played = int(entry.hands_played) + 1
            # 终态判定与结算适配层共用同一份规则，不在此另写一遍
            self._apply_tournament_entry_terminal_status(entry, tournament)
            session.flush()

            return {
                "hand": self._blackjack_hand_to_dict(hand),
                "already_settled": False,
                "settled": True,
                "outcome": engine.OUTCOME_SURRENDER,
                "payout_credits": float(payout),
                "chips": int(entry.chips),
                "hands_played": int(entry.hands_played),
                "entry_status": int(entry.status),
                "total_hands": int(tournament.total_hands) if tournament else None,
            }

    def force_settle_tournament_hands(self, tournament_id: int) -> dict:
        """结算某赛事全部尚未终结的手牌。

        完赛截止时点到达时的**第一阶段**：排名必须读到终局筹码，而一手在局的牌
        意味着押注已从 chips 扣除、赔付尚未计入，其持有者的筹码被低估。

        口径等同玩家停牌（庄家按规则补牌、正常判定胜负），**绝不因截止而判负**。
        不看各手牌自己的 15 分钟时限——赛事已到点，一律清场。

        **每手牌自成一个事务**：不把整批放进一个事务，否则第 N 手上的任何异常
        都会回滚前面已算好的赔付，而返回值仍会把它们报成已结算。

        返回 `{"settled": 本次结算手数, "remaining": 仍未终结手数, "cleared": bool}`。
        **`cleared` 必须由调用方检查**：单手结算失败会被本函数吞掉（只丢那一手），
        此时排名读到的是被低估的筹码，而派奖的 CAS 一旦触发就再没有重试的机会。
        `remaining` 由结算后的**重新扫描**得出，不靠计数相减——扫描才能反映期间
        被其他事务终结的手牌。
        """
        from app.domains.blackjack import rules as engine

        def _scan_pending() -> list[int]:
            with get_session() as session:
                return [
                    int(r[0])
                    for r in session.execute(
                        select(BlackjackHand.id).where(
                            BlackjackHand.tournament_id == int(tournament_id),
                            BlackjackHand.status.notin_(engine.TERMINAL_STATUSES),
                        )
                    ).all()
                ]

        try:
            pending_ids = _scan_pending()
        except Exception as e:
            logger.error(f"扫描赛事在局手牌失败 (tournament={tournament_id}): {e}")
            # 扫不到就不能宣称已清场，否则会放行一次读不准筹码的派奖
            return {"settled": 0, "remaining": -1, "cleared": False}

        settled = 0
        for hand_id in pending_ids:
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
                    if not self._claim_blackjack_hand(
                        session, hand_id, allow_dealer_turn=True
                    ):
                        continue
                    session.expire(hand)
                    # 记为已结算而非已弃牌：它是被赛事截止收走的，不是玩家离场
                    self._settle_blackjack_tournament_hand(session, hand)
                    settled += 1
            except Exception as e:
                logger.error(f"清场赛内手牌失败 (hand={hand_id}): {e}")

        try:
            remaining = len(_scan_pending())
        except Exception as e:
            logger.error(f"复查赛事在局手牌失败 (tournament={tournament_id}): {e}")
            return {"settled": settled, "remaining": -1, "cleared": False}

        if settled:
            logger.info(f"赛事 {tournament_id} 清场：结算了 {settled} 手在局手牌")
        if remaining:
            logger.error(
                f"赛事 {tournament_id} 清场未尽：仍有 {remaining} 手未终结，"
                f"本轮跳过派奖，等下一分钟重试"
            )
        return {"settled": settled, "remaining": remaining, "cleared": remaining == 0}

    def award_or_renew_badge(
        self,
        tg_id: int,
        badge_id: int,
        valid_days: int,
        cap_days: int | None = None,
    ) -> dict:
        """授予勋章；已持有则**续期**其加成而非重置。

        `UserBadge` 的语义是「持有永久、仅加成过期」（见模型注释），故续期只动
        `expires_at`，不新建行——`UNIQUE(tg_id, badge_id)` 也不允许新建。

            首次   expires_at = now + valid_days
            再次   expires_at = min(max(expires_at, now) + valid_days,
                                    now + cap_days)

        `max(expires_at, now)` 就是「续期而非重置」的全部含义：加成还没过期就往后
        接（连庄因此有连续的获得感），已经过期就从现在起算。外层 `cap_days` 防止
        持续夺冠者把加成累积到无限长。

        **不改既有的授予路径**（`game_king` / `supreme_contributor` 那两处只做
        「有则跳过」）：续期是本变更引入的新语义，混进去会让那两个勋章的行为
        跟着变。

        Returns: {awarded(bool), renewed(bool), expires_at, previous_expires_at}
        """
        now_ts = int(time.time())
        span = int(valid_days) * 24 * 3600
        try:
            with get_session() as session:
                existing = (
                    session.execute(
                        select(UserBadge)
                        .where(
                            UserBadge.tg_id == int(tg_id),
                            UserBadge.badge_id == int(badge_id),
                        )
                        .with_for_update()
                    )
                    .scalars()
                    .one_or_none()
                )

                if not existing:
                    session.add(
                        UserBadge(
                            tg_id=int(tg_id),
                            badge_id=int(badge_id),
                            credits_cost=0,
                            redeemed_at=now_ts,
                            expires_at=now_ts + span,
                            is_active=1,
                        )
                    )
                    return {
                        "awarded": True,
                        "renewed": False,
                        "expires_at": now_ts + span,
                        "previous_expires_at": None,
                    }

                previous = int(existing.expires_at)
                new_expires = max(previous, now_ts) + span
                if cap_days:
                    new_expires = min(new_expires, now_ts + int(cap_days) * 24 * 3600)
                existing.expires_at = new_expires
                # 加成过期后 is_active 可能已被置 0，续期时一并恢复
                existing.is_active = 1
                return {
                    "awarded": False,
                    "renewed": True,
                    "expires_at": new_expires,
                    "previous_expires_at": previous,
                }
        except Exception as e:
            logger.error(f"授予/续期勋章失败 (tg_id={tg_id}, badge={badge_id}): {e}")
            return {
                "awarded": False,
                "renewed": False,
                "expires_at": None,
                "previous_expires_at": None,
            }
