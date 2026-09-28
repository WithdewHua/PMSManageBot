"""21 点 repository：手牌结算与超时结算（由 part_N 机械拆分）。"""

import json
import time

from sqlalchemy import select, update

from app.domains.blackjack.models import BlackjackHand
from app.domains.blackjack.repository.constants import (
    JACKPOT_CONFIG_KEY,
    JACKPOT_CONFIG_TYPE,
)
from app.domains.credits import repository as credits_repository
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import Statistics


class _BlackjackRepositorySettlement:
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
                credits_repository.add_tx(session, CreditAccount.tg(tg_id), credited)
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
