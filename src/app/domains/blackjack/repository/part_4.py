import json
import time

from sqlalchemy import case, distinct, func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.db import get_session
from app.core.log import logger
from app.domains.blackjack.exceptions import blackjack_error
from app.domains.blackjack.models import (
    BlackjackHand,
    BlackjackTournament,
    BlackjackTournamentEntry,
)
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import Statistics

from . import (
    JACKPOT_CONFIG_KEY,
    JACKPOT_CONFIG_TYPE,
)


class _BlackjackRepositoryPart4:
    def get_user_blackjack_stats(self, tg_id: int) -> dict:
        """用户的 21 点个人统计。"""
        empty = {
            "total_hands": 0,
            "net_credits": 0.0,
            "max_win": 0.0,
            "win_rate": 0.0,
            "accuracy": 0.0,
            "decisions_total": 0,
            "jackpot_total": 0.0,
            "surrender_hands": 0,
        }
        try:
            with get_session() as session:
                return self.get_user_blackjack_stats_tx(session, tg_id)
        except Exception as e:
            logger.error(f"获取用户 21 点统计失败 (tg_id={tg_id}): {e}")
            return empty

    def get_blackjack_admin_stats(self) -> dict:
        """21 点的运营聚合统计，供管理页卡片展示。"""
        empty = {
            "total_hands": 0,
            "active_hands": 0,
            "total_players": 0,
            "today_hands": 0,
            "total_wagered": 0.0,
            "total_rake": 0.0,
            "net_credits": 0.0,
            "jackpot_paid": 0.0,
            "jackpot_balance": 0.0,
        }
        try:
            with get_session() as session:
                return self.get_blackjack_admin_stats_tx(session)
        except Exception as e:
            logger.error(f"获取 21 点运营统计失败: {e}")
            return empty

    def get_user_blackjack_stats_tx(self, session, tg_id: int) -> dict:
        """Read user statistics using the caller-owned session."""
        from app.domains.blackjack import rules as engine

        total_stake = case(
            (BlackjackHand.doubled == 1, BlackjackHand.bet_credits * 2),
            else_=BlackjackHand.bet_credits,
        )
        net = (
            func.coalesce(BlackjackHand.payout_credits, 0)
            - total_stake
            + func.coalesce(BlackjackHand.relief_credits, 0)
        )
        win_flag = case(
            (
                BlackjackHand.outcome.in_(
                    [engine.OUTCOME_WIN, engine.OUTCOME_BLACKJACK]
                ),
                1,
            ),
            else_=0,
        )
        surrender_flag = case(
            (BlackjackHand.outcome == engine.OUTCOME_SURRENDER, 1), else_=0
        )
        row = session.execute(
            select(
                func.count(BlackjackHand.id),
                func.coalesce(func.sum(net), 0),
                func.coalesce(func.max(net), 0),
                func.coalesce(func.sum(win_flag), 0),
                func.coalesce(func.sum(BlackjackHand.decisions_total), 0),
                func.coalesce(func.sum(BlackjackHand.decisions_correct), 0),
                func.coalesce(func.sum(BlackjackHand.jackpot_won), 0),
                func.coalesce(func.sum(surrender_flag), 0),
            ).where(
                BlackjackHand.tg_id == int(tg_id),
                BlackjackHand.status.in_(engine.TERMINAL_STATUSES),
                BlackjackHand.tournament_id.is_(None),
            )
        ).one()
        hands = int(row[0] or 0)
        decisions_total = int(row[4] or 0)
        return {
            "total_hands": hands,
            "net_credits": round(float(row[1] or 0), 2),
            "max_win": round(float(row[2] or 0), 2),
            "win_rate": round(float(row[3] or 0) / hands * 100, 2) if hands else 0.0,
            "accuracy": round(float(row[5] or 0) / decisions_total * 100, 2)
            if decisions_total
            else 0.0,
            "decisions_total": decisions_total,
            "jackpot_total": round(float(row[6] or 0), 2),
            "surrender_hands": int(row[7] or 0),
        }

    def get_blackjack_admin_stats_tx(self, session) -> dict:
        """Read aggregate statistics using the caller-owned session."""
        from app.domains.blackjack import rules as engine

        terminal = BlackjackHand.status.in_(engine.TERMINAL_STATUSES)
        stake = case(
            (BlackjackHand.doubled == 1, BlackjackHand.bet_credits * 2),
            else_=BlackjackHand.bet_credits,
        )
        staked = case((terminal, stake), else_=0)
        paid = case((terminal, func.coalesce(BlackjackHand.payout_credits, 0)), else_=0)
        raked = case((terminal, func.coalesce(BlackjackHand.rake_credits, 0)), else_=0)
        jackpot = case((terminal, func.coalesce(BlackjackHand.jackpot_won, 0)), else_=0)
        relief = case(
            (terminal, func.coalesce(BlackjackHand.relief_credits, 0)), else_=0
        )
        row = session.execute(
            select(
                func.coalesce(func.sum(case((terminal, 1), else_=0)), 0),
                func.coalesce(func.sum(case((terminal, 0), else_=1)), 0),
                func.count(distinct(BlackjackHand.tg_id)),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                BlackjackHand.created_at_ms
                                >= self._blackjack_day_start_ms(),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(func.sum(staked), 0),
                func.coalesce(func.sum(raked), 0),
                func.coalesce(func.sum(paid), 0),
                func.coalesce(func.sum(jackpot), 0),
                func.coalesce(func.sum(relief), 0),
            ).where(BlackjackHand.tournament_id.is_(None))
        ).one()
        wagered = float(row[4] or 0)
        payout = float(row[6] or 0)
        jackpot_paid = float(row[7] or 0)
        relief_paid = float(row[8] or 0)
        return {
            "total_hands": int(row[0] or 0),
            "active_hands": int(row[1] or 0),
            "total_players": int(row[2] or 0),
            "today_hands": int(row[3] or 0),
            "total_wagered": round(wagered, 2),
            "total_rake": round(float(row[5] or 0), 2),
            "net_credits": round(payout + jackpot_paid + relief_paid - wagered, 2),
            "jackpot_paid": round(jackpot_paid, 2),
            "jackpot_balance": self.read_fund_balance(
                session, JACKPOT_CONFIG_TYPE, JACKPOT_CONFIG_KEY
            ),
        }

    # 赛事状态
    TOURNAMENT_REGISTERING = 1
    TOURNAMENT_RUNNING = 2
    TOURNAMENT_SETTLED = 3
    TOURNAMENT_CANCELLED = 4
    TOURNAMENT_TERMINAL = (3, 4)
    # 报名状态。**只有已打完与已淘汰具备派奖资格**：21 点接近零期望，故不打牌的
    # 期望筹码高于打满全部手数的中位数——若无这道资格门，最优策略将是报名后什么
    # 都不做。
    ENTRY_PLAYING = 1
    ENTRY_FINISHED = 2
    ENTRY_ELIMINATED = 3
    ENTRY_ELIGIBLE = (2, 3)
    # 已有报名者之后仍可改的字段——**只有展示文案与两个截止时点**。
    # 其余一律冻结：报名者是按公示参数付的报名费，而 `buy_in_credits` 同时是
    # 奖池推导（entrant_count × buy_in）与取消退款的因子，改它等于拿新价去算
    # 旧钱——按 30 收了 10 个人再改成 100，奖池会凭空多出 700 分派出去。
    TOURNAMENT_MUTABLE_WITH_ENTRANTS = (
        "title",
        "description",
        "register_deadline_ms",
        "play_deadline_ms",
    )
    # 赛程窗口下限。缺了这道校验，`register_deadline == play_deadline` 的赛事会在
    # 同一次 tick 内开赛并立即结算：无人打完、无人淘汰，资格集为空，**全部报名费
    # 静默销毁**。窗口还要随总手数放大，否则 100 手配 30 分钟同样无人打得完。
    TOURNAMENT_MIN_PLAY_WINDOW_MS = 30 * 60 * 1000
    TOURNAMENT_MS_PER_HAND = 60 * 1000

    def _tournament_to_dict(self, t: BlackjackTournament) -> dict:
        """把赛事行转为字典。奖池按报名数推导，不读累加列（本表没有那一列）。"""
        try:
            payout_structure = json.loads(t.payout_structure or "[]")
            if not isinstance(payout_structure, list):
                payout_structure = []
        except Exception:
            payout_structure = []

        from app.domains.blackjack import rules

        gross, _rake, net_pool = rules.calculate_tournament_pool(
            t.entrant_count,
            t.buy_in_credits,
            t.seeded_prize_credits,
            t.rake_bp,
        )
        return {
            "id": int(t.id),
            "title": str(t.title),
            "description": t.description,
            "status": int(t.status),
            "buy_in_credits": int(t.buy_in_credits),
            "starting_chips": int(t.starting_chips),
            "total_hands": int(t.total_hands),
            "min_bet_chips": int(t.min_bet_chips),
            "max_bet_chips": int(t.max_bet_chips),
            "bet_step_chips": int(t.bet_step_chips),
            "min_entrants": int(t.min_entrants),
            "max_entrants": int(t.max_entrants),
            "entrant_count": int(t.entrant_count),
            "rake_bp": int(t.rake_bp),
            "seeded_prize_credits": float(t.seeded_prize_credits),
            "payout_structure": payout_structure,
            # 奖池总额与实际可派发额分列：前者是玩家看到的「奖池」，后者扣掉抽水
            "prize_pool_gross": gross,
            "prize_pool_net": net_pool,
            "dealer_hits_soft_17": int(t.dealer_hits_soft_17) == 1,
            "blackjack_payout": float(t.blackjack_payout),
            "surrender_enabled": int(t.surrender_enabled) == 1,
            "hand_timeout_minutes": int(t.hand_timeout_minutes),
            "register_deadline_ms": int(t.register_deadline_ms),
            "play_deadline_ms": int(t.play_deadline_ms),
            "created_by": int(t.created_by) if t.created_by is not None else None,
            "settled_at": int(t.settled_at) if t.settled_at is not None else None,
        }

    def _tournament_entry_to_dict(self, e: BlackjackTournamentEntry) -> dict:
        """把报名行转为字典。"""
        return {
            "id": int(e.id),
            "tournament_id": int(e.tournament_id),
            "tg_id": int(e.tg_id),
            "chips": int(e.chips),
            "hands_played": int(e.hands_played),
            "status": int(e.status),
            "eligible": int(e.status) in self.ENTRY_ELIGIBLE,
            "final_rank": int(e.final_rank) if e.final_rank is not None else None,
            "prize_credits": float(e.prize_credits)
            if e.prize_credits is not None
            else None,
            "wallet_paid_credits": round(float(e.wallet_paid_credits or 0), 2),
            "credits_paid_credits": round(float(e.credits_paid_credits or 0), 2),
            "registered_at_ms": int(e.registered_at_ms),
        }

    def _validate_tournament_params(self, params: dict) -> dict:
        from app.domains.blackjack import rules

        try:
            normalized = rules.validate_tournament_params(params)
        except ValueError as exc:
            raise blackjack_error(str(exc)) from exc
        normalized["payout_structure"] = json.dumps(normalized["payout_structure"])
        return normalized

    def _generate_tournament_title(self) -> str:
        """赛事名称留空时的自动命名：`21 点锦标赛 · 第 N 期`。

        期数取**已创建赛事总数 + 1**而非 `id`：id 是内部编号，管理端列表本来就在
        标题前显示 `#id`，写进名字只是重复；而「第 N 期」自带连续感。赛事没有删除
        路径（取消也只是状态流转），故该计数单调递增，语义稳定。

        并发创建会算出同一个 N 而两场重名——**不加唯一约束是有意的**：重名只是
        显示上的巧合，而 UNIQUE 会把它升级成一次创建失败。赛事创建是管理员的手动
        低频操作，实际不会并发。
        """
        with get_session() as session:
            count = (
                session.execute(select(func.count(BlackjackTournament.id))).scalar()
                or 0
            )
        return f"21 点锦标赛 · 第 {int(count) + 1} 期"

    def create_blackjack_tournament(
        self, params: dict, created_by: int | None = None
    ) -> dict:
        """创建赛事。快照创建当时生效的庄家规则、天胡赔率、投降开关与单手时限。

        快照的意义与现金局手牌相同：赛内全部手牌按该快照结算，管理员改全局配置
        不影响已创建的赛事。故这四个值**不从 `get_blackjack_config_dict()` 现读**，
        而是在此固化到赛事行上。
        """
        # 名称留空即「你帮我取一个」。**更新路径刻意不做同样处理**：那里留空的
        # 意思是「把名字清空」，应当照旧拒绝——静默换成一个新名字会让管理员以为
        # 自己改的名字生效了，而群里公示的是另一个。
        params = dict(params)
        if not str(params.get("title") or "").strip():
            params["title"] = self._generate_tournament_title()

        validated = self._validate_tournament_params(params)
        config = self.get_blackjack_config_dict()

        if not config.get("enabled", False):
            raise blackjack_error("blackjack disabled")

        now_ms = int(time.time() * 1000)
        from app.domains.blackjack import rules

        if rules.is_deadline_reached(now_ms, validated["register_deadline_ms"]):
            raise blackjack_error("register deadline must be in the future")

        with get_session() as session:
            tournament = BlackjackTournament(
                status=self.TOURNAMENT_REGISTERING,
                entrant_count=0,
                # 参数快照
                dealer_hits_soft_17=1 if config.get("dealer_hits_soft_17") else 0,
                blackjack_payout=float(config.get("blackjack_payout", 1.5)),
                surrender_enabled=1 if config.get("surrender_enabled", True) else 0,
                hand_timeout_minutes=int(config.get("hand_timeout_minutes", 15)),
                created_by=int(created_by) if created_by is not None else None,
                **validated,
            )
            session.add(tournament)
            session.flush()
            return self._tournament_to_dict(tournament)

    def update_blackjack_tournament(self, tournament_id: int, params: dict) -> dict:
        """修改赛事。**仅允许修改处于报名中的赛事**，且已有报名者后经济参数冻结。

        进入进行中后一律拒绝：报名者已按公示的参数付过报名费，而总手数、注额区间
        与派奖档位都直接决定他们的策略与预期收益，中途变更等于事后改规则。

        报名中但**已有人付费**时同样不能改经济参数——理由更硬：奖池是
        `entrant_count × buy_in_credits` 推导出来的，取消退款也读同一个字段。
        按 30 收了 10 个人再把 buy_in 改成 100，派奖会按 1000 算而实收只有
        300，差额是凭空增发；走取消路径则每人退 100。要改就先取消（全额退款）
        再重建。可改的只有展示文案与两个截止时点，外加**只增不减**的奖池补贴。
        """
        validated = self._validate_tournament_params(params)

        with get_session() as session:
            tournament = (
                session.execute(
                    select(BlackjackTournament)
                    .where(BlackjackTournament.id == int(tournament_id))
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not tournament:
                raise blackjack_error("tournament not found")
            if int(tournament.status) != self.TOURNAMENT_REGISTERING:
                raise blackjack_error("tournament already started")

            # 已有报名时不得把人数上限压到报名数以下，否则 entrant_count 会越界
            if validated["max_entrants"] < int(tournament.entrant_count):
                raise blackjack_error(
                    f"max_entrants must not be below current entrants "
                    f"({int(tournament.entrant_count)})"
                )

            if int(tournament.entrant_count) > 0:
                self._assert_tournament_params_frozen(tournament, validated)

            for key, value in validated.items():
                setattr(tournament, key, value)
            session.flush()
            return self._tournament_to_dict(tournament)

    def _assert_tournament_params_frozen(
        self, tournament: BlackjackTournament, validated: dict
    ) -> None:
        """已有报名者时，校验本次修改没有触碰冻结字段。"""
        for key, value in validated.items():
            if key in self.TOURNAMENT_MUTABLE_WITH_ENTRANTS:
                continue
            current = getattr(tournament, key)

            if key == "seeded_prize_credits":
                # 加码是纯利好，减码等于事后缩水已公示的奖池，故只放行增加
                if float(value) < float(current):
                    raise blackjack_error("seeded_prize_credits must not decrease")
                continue

            if isinstance(current, (int, float)) and isinstance(value, (int, float)):
                same = abs(float(value) - float(current)) < 1e-9
            else:
                # payout_structure 两端都是同一段 json.dumps 产出的字符串
                same = str(value) == str(current)
            if not same:
                raise blackjack_error(f"cannot change {key} after entrants joined")

    def register_blackjack_tournament(self, tg_id: int, tournament_id: int) -> dict:
        """报名：占名额 → 扣报名费 → 建 entry；满员则尝试开赛。"""
        config = self.get_blackjack_config_dict()
        if not config.get("enabled", False):
            raise blackjack_error("blackjack disabled")
        return self._run_registration_transaction(
            tg_id, tournament_id, config=config, now_ms=int(time.time() * 1000)
        )

    def _run_registration_transaction(
        self, tg_id: int, tournament_id: int, *, config: dict, now_ms: int
    ) -> dict:
        with get_session() as session:
            return self.register_blackjack_tournament_tx(
                session, tg_id, tournament_id, config=config, now_ms=now_ms
            )

    def register_blackjack_tournament_tx(
        self,
        session,
        tg_id: int,
        tournament_id: int,
        *,
        config: dict,
        now_ms: int,
    ) -> dict:
        """在 caller-owned session 中完成报名、扣费、占位和自动开赛。

        所有写入必须留在同一事务：entrant_count、Statistics、credits 和 entry
        任何一步失败都由调用方回滚。赛事行先用条件 UPDATE 占位，随后才锁
        Statistics，保持 tournament → statistics 的锁序。
        """
        if not config.get("enabled", False):
            raise blackjack_error("blackjack disabled")

        tournament = (
            session.execute(
                select(BlackjackTournament).where(
                    BlackjackTournament.id == int(tournament_id)
                )
            )
            .scalars()
            .one_or_none()
        )
        if not tournament:
            raise blackjack_error("tournament not found")
        if int(tournament.status) != self.TOURNAMENT_REGISTERING:
            raise blackjack_error("tournament not open for registration")
        from app.domains.blackjack import rules

        if rules.is_deadline_reached(now_ms, tournament.register_deadline_ms):
            raise blackjack_error("registration closed")

        buy_in = int(tournament.buy_in_credits)
        starting_chips = int(tournament.starting_chips)
        max_entrants = int(tournament.max_entrants)
        existing = (
            session.execute(
                select(BlackjackTournamentEntry).where(
                    BlackjackTournamentEntry.tournament_id == int(tournament_id),
                    BlackjackTournamentEntry.tg_id == int(tg_id),
                )
            )
            .scalars()
            .one_or_none()
        )
        if existing:
            raise blackjack_error("already registered")

        claimed = session.execute(
            update(BlackjackTournament)
            .where(
                BlackjackTournament.id == int(tournament_id),
                BlackjackTournament.status == self.TOURNAMENT_REGISTERING,
                BlackjackTournament.entrant_count < max_entrants,
            )
            .values(entrant_count=BlackjackTournament.entrant_count + 1)
        )
        if claimed.rowcount == 0:
            raise blackjack_error("tournament full")

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
        wallet = round(float(stats.tournament_wallet_credits or 0), 2)
        if wallet + float(stats.credits) < float(buy_in):
            raise blackjack_error(f"insufficient credits: need {buy_in}")
        wallet_paid = round(min(wallet, float(buy_in)), 2)
        credits_paid = round(float(buy_in) - wallet_paid, 2)
        stats.tournament_wallet_credits = round(wallet - wallet_paid, 2)
        if credits_paid > 0:
            mutation = credits_repository.deduct_tx(
                session, CreditAccount.tg(int(tg_id)), credits_paid
            )
            credits_service.register_cache_invalidation(session, mutation)

        entry = BlackjackTournamentEntry(
            tournament_id=int(tournament_id),
            tg_id=int(tg_id),
            chips=starting_chips,
            hands_played=0,
            status=self.ENTRY_PLAYING,
            wallet_paid_credits=wallet_paid,
            credits_paid_credits=credits_paid,
            registered_at_ms=now_ms,
        )
        session.add(entry)
        try:
            session.flush()
        except IntegrityError:
            raise blackjack_error("already registered")
        session.expire(tournament)

        entry_dict = self._tournament_entry_to_dict(entry)
        started = False
        notify_entrants: list[int] = []
        if int(tournament.entrant_count) >= max_entrants:
            started = self._claim_tournament_transition(
                session,
                int(tournament_id),
                self.TOURNAMENT_REGISTERING,
                self.TOURNAMENT_RUNNING,
            )
            if started:
                session.expire(tournament)
                notify_entrants = self._list_tournament_entrant_ids(
                    session, int(tournament_id)
                )

        return {
            "entry": entry_dict,
            "tournament": self._tournament_to_dict(tournament),
            "started": started,
            "notify_entrants": notify_entrants,
            "current_credits": round(float(stats.credits), 2),
            "tournament_wallet_credits": round(
                float(stats.tournament_wallet_credits or 0), 2
            ),
        }

    def _claim_tournament_transition(
        self, session, tournament_id: int, from_status: int, to_status: int
    ) -> bool:
        """把赛事状态从 `from_status` 原子地改为 `to_status`，返回是否抢到。

        这是赛事的**唯一**流转方式，也是五处通知的去重闸门：抢到的一方负责发通知，
        抢不到的一方什么都不做。开赛、赛果、取消三处各有多条触发路径（最后一次
        报名 / tick 任务 / 任务重试），靠「记得只发一次」是不可能正确的。

        不依赖行锁——`with_for_update()` 在 SQLite 上是 no-op，两个并发事务可以
        各自读到旧状态再依次写入，于是通知发两遍、派奖也可能算两遍。

        调用方须在事务内，且必须先 `session.flush()` 把挂起的改动刷下去，否则
        条件 UPDATE 读到的可能不是最新状态。
        """
        session.flush()
        values: dict = {"status": int(to_status)}
        if int(to_status) in self.TOURNAMENT_TERMINAL:
            values["settled_at"] = int(time.time())
        claimed = session.execute(
            update(BlackjackTournament)
            .where(
                BlackjackTournament.id == int(tournament_id),
                BlackjackTournament.status == int(from_status),
            )
            .values(**values)
        )
        return claimed.rowcount == 1

    def _lock_running_tournament(
        self, session, tournament_id: int
    ) -> BlackjackTournament | None:
        """钉住一场进行中的赛事直到本事务提交。

        条件 UPDATE 把 `status` 写回自身：PostgreSQL 上行锁，SQLite 上库级写锁。
        `with_for_update()` 在 SQLite 上是 no-op，不能当同步点。发牌与完赛结算
        共用本方法，使截止边界上尚未提交的发牌无法插进已经派完奖的赛事。

        抢不到返回 None（不存在，或已经不是进行中）。调用方须在事务内。
        """
        session.flush()
        claimed = session.execute(
            update(BlackjackTournament)
            .where(
                BlackjackTournament.id == int(tournament_id),
                BlackjackTournament.status == self.TOURNAMENT_RUNNING,
            )
            .values(status=self.TOURNAMENT_RUNNING)
        )
        if claimed.rowcount != 1:
            return None
        return (
            session.execute(
                select(BlackjackTournament).where(
                    BlackjackTournament.id == int(tournament_id)
                )
            )
            .scalars()
            .one_or_none()
        )
