import time

from sqlalchemy import func, select, update

from app.core.db import get_session
from app.core.log import logger
from app.domains.blackjack.models import (
    BlackjackHand,
    BlackjackTournament,
    BlackjackTournamentEntry,
)
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import Statistics


class _BlackjackRepositoryPart5:
    def _list_tournament_entrant_ids(self, session, tournament_id: int) -> list[int]:
        """该赛事全部报名者的 tg_id，供通知使用。"""
        rows = session.execute(
            select(BlackjackTournamentEntry.tg_id)
            .where(BlackjackTournamentEntry.tournament_id == int(tournament_id))
            .order_by(BlackjackTournamentEntry.registered_at_ms.asc())
        ).all()
        return [int(r[0]) for r in rows]

    def start_blackjack_tournament(self, tournament_id: int) -> dict:
        """报名截止且人数达标时开赛。由 tick 任务调用。

        Returns: {started(bool), tournament, notify_entrants: [tg_id]}
        """
        with get_session() as session:
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
                return {"started": False, "tournament": None, "notify_entrants": []}
            if int(tournament.status) != self.TOURNAMENT_REGISTERING:
                return {
                    "started": False,
                    "tournament": self._tournament_to_dict(tournament),
                    "notify_entrants": [],
                }
            if int(tournament.entrant_count) < int(tournament.min_entrants):
                return {
                    "started": False,
                    "tournament": self._tournament_to_dict(tournament),
                    "notify_entrants": [],
                }

            started = self._claim_tournament_transition(
                session,
                int(tournament_id),
                self.TOURNAMENT_REGISTERING,
                self.TOURNAMENT_RUNNING,
            )
            notify_entrants = (
                self._list_tournament_entrant_ids(session, int(tournament_id))
                if started
                else []
            )
            session.expire(tournament)
            return {
                "started": started,
                "tournament": self._tournament_to_dict(tournament),
                "notify_entrants": notify_entrants,
            }

    def cancel_blackjack_tournament(
        self, tournament_id: int, reason: str = "insufficient_entrants"
    ) -> dict:
        """取消赛事并**全额**退还报名费。

        退款不计任何抽水——赛事从未开始，没有可供计取的东西。

        幂等由 `1 → 4` 的 CAS 保证：抢不到的一方一分钱不退、一条通知不发。
        进行中的赛事一律不可取消：报名费已收而筹码无法折算回积分，强制作废只会
        制造一批无法解释的账。

        锁序 tournament → entry → statistics。

        Returns: {cancelled(bool), tournament, refunds: [{tg_id, credits}]}
        """
        with get_session() as session:
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
                raise ValueError("tournament not found")
            if int(tournament.status) == self.TOURNAMENT_RUNNING:
                raise ValueError("tournament already started")
            if int(tournament.status) in self.TOURNAMENT_TERMINAL:
                return {
                    "cancelled": False,
                    "tournament": self._tournament_to_dict(tournament),
                    "refunds": [],
                }

            buy_in = int(tournament.buy_in_credits)

            # 先抢占状态：抢不到说明已被他人取消或开赛，绝不能继续退款
            if not self._claim_tournament_transition(
                session,
                int(tournament_id),
                self.TOURNAMENT_REGISTERING,
                self.TOURNAMENT_CANCELLED,
            ):
                session.expire(tournament)
                return {
                    "cancelled": False,
                    "tournament": self._tournament_to_dict(tournament),
                    "refunds": [],
                }
            session.expire(tournament)

            entries = (
                session.execute(
                    select(BlackjackTournamentEntry)
                    .where(BlackjackTournamentEntry.tournament_id == int(tournament_id))
                    .order_by(BlackjackTournamentEntry.registered_at_ms.asc())
                )
                .scalars()
                .all()
            )

            refunds = []
            for entry in entries:
                # 退款按报名时的实际支付拆分原路退回：争霸赛余额支付的部分回
                # 争霸赛余额，积分支付的部分回积分——返还的价值不因路径改换
                # 而意外进入可挪用的积分。
                #
                # 存量兼容：迁移前创建的 entry 两列均为 0，但其实际支付是全额
                # 积分（争霸赛余额当时尚不存在），拆分之和为 0 即按全额积分退。
                wallet_paid = round(float(entry.wallet_paid_credits or 0), 2)
                credits_paid = round(float(entry.credits_paid_credits or 0), 2)
                if wallet_paid + credits_paid <= 0:
                    credits_paid = float(buy_in)

                stats = (
                    session.execute(
                        select(Statistics)
                        .where(Statistics.tg_id == int(entry.tg_id))
                        .with_for_update()
                    )
                    .scalars()
                    .one_or_none()
                )
                if stats:
                    stats.tournament_wallet_credits = round(
                        float(stats.tournament_wallet_credits or 0) + wallet_paid, 2
                    )
                    if credits_paid > 0:
                        mutation = credits_repository.add_tx(
                            session, CreditAccount.tg(int(entry.tg_id)), credits_paid
                        )
                        credits_service.register_cache_invalidation(session, mutation)
                else:
                    session.add(
                        Statistics(
                            tg_id=int(entry.tg_id),
                            donation=0,
                            credits=credits_paid,
                            tournament_wallet_credits=wallet_paid,
                        )
                    )
                refunds.append(
                    {
                        "tg_id": int(entry.tg_id),
                        "credits": round(wallet_paid + credits_paid, 2),
                        "wallet_credits": wallet_paid,
                        "paid_credits": credits_paid,
                    }
                )

            session.flush()
            logger.info(
                f"21 点锦标赛 {tournament_id} 已取消（{reason}），"
                f"退还 {len(refunds)} 人各 {buy_in} 积分"
            )
            return {
                "cancelled": True,
                "tournament": self._tournament_to_dict(tournament),
                "refunds": refunds,
            }

    def claim_tournament_reminder(self, tournament_id: int) -> dict:
        """抢占完赛提醒的发送权，并返回该发给谁。

        去重靠 `reminder_sent_at` 的**条件 UPDATE**（`WHERE reminder_sent_at IS
        NULL`）：tick 任务每分钟都会扫到同一场处于提醒窗口内的赛事，抢不到的那些
        轮次直接返回 `claimed=False`，一条也不发。

        **通知开关关闭时调用方仍应照常调用本方法**，只是不发送。若关闭时直接跳过、
        让标记冻结，重新打开的那一分钟会把积压的提醒一次性倾泻给所有人。

        `pending` 只含**未打满且未被淘汰**的报名——已打完与已淘汰的人都已具备派奖
        资格，提醒他们毫无意义。

        Returns: {claimed(bool), pending: [{tg_id, hands_remaining}]}
        """
        now_ts = int(time.time())
        try:
            with get_session() as session:
                claimed = session.execute(
                    update(BlackjackTournament)
                    .where(
                        BlackjackTournament.id == int(tournament_id),
                        BlackjackTournament.status == self.TOURNAMENT_RUNNING,
                        BlackjackTournament.reminder_sent_at.is_(None),
                    )
                    .values(reminder_sent_at=now_ts)
                )
                if claimed.rowcount == 0:
                    return {"claimed": False, "pending": []}

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
                    return {"claimed": False, "pending": []}
                total_hands = int(tournament.total_hands)

                rows = session.execute(
                    select(
                        BlackjackTournamentEntry.tg_id,
                        BlackjackTournamentEntry.hands_played,
                    ).where(
                        BlackjackTournamentEntry.tournament_id == int(tournament_id),
                        BlackjackTournamentEntry.status == self.ENTRY_PLAYING,
                    )
                ).all()

                pending = [
                    {
                        "tg_id": int(r[0]),
                        "hands_remaining": max(0, total_hands - int(r[1])),
                    }
                    for r in rows
                    if int(r[1]) < total_hands
                ]
                return {"claimed": True, "pending": pending}
        except Exception as e:
            logger.error(f"抢占锦标赛完赛提醒失败 (id={tournament_id}): {e}")
            return {"claimed": False, "pending": []}

    def get_blackjack_tournament(
        self, tournament_id: int, tg_id: int | None = None
    ) -> dict | None:
        """赛事详情。给定 `tg_id` 时附带该用户的报名（没报名则为 None）。"""
        try:
            with get_session() as session:
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
                    return None
                result = self._tournament_to_dict(tournament)
                result["my_entry"] = None
                if tg_id is not None:
                    entry = (
                        session.execute(
                            select(BlackjackTournamentEntry).where(
                                BlackjackTournamentEntry.tournament_id
                                == int(tournament_id),
                                BlackjackTournamentEntry.tg_id == int(tg_id),
                            )
                        )
                        .scalars()
                        .one_or_none()
                    )
                    if entry:
                        result["my_entry"] = self._tournament_entry_to_dict(entry)
                return result
        except Exception as e:
            logger.error(f"获取 21 点锦标赛失败 (id={tournament_id}): {e}")
            return None

    def list_blackjack_tournaments(
        self,
        tg_id: int | None = None,
        statuses: tuple | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """赛事列表。默认列出报名中与进行中的赛事，供大厅展示。

        给定 `tg_id` 时一次性带出该用户在这批赛事中的报名，避免前端逐场再查。
        """
        if statuses is None:
            statuses = (self.TOURNAMENT_REGISTERING, self.TOURNAMENT_RUNNING)
        try:
            with get_session() as session:
                tournaments = (
                    session.execute(
                        select(BlackjackTournament)
                        .where(BlackjackTournament.status.in_(tuple(statuses)))
                        .order_by(BlackjackTournament.id.desc())
                        .limit(int(limit))
                    )
                    .scalars()
                    .all()
                )
                results = [self._tournament_to_dict(t) for t in tournaments]
                if tg_id is not None and results:
                    ids = [r["id"] for r in results]
                    entries = (
                        session.execute(
                            select(BlackjackTournamentEntry).where(
                                BlackjackTournamentEntry.tournament_id.in_(ids),
                                BlackjackTournamentEntry.tg_id == int(tg_id),
                            )
                        )
                        .scalars()
                        .all()
                    )
                    by_tid = {
                        int(e.tournament_id): self._tournament_entry_to_dict(e)
                        for e in entries
                    }
                    for r in results:
                        r["my_entry"] = by_tid.get(r["id"])
                else:
                    for r in results:
                        r["my_entry"] = None
                return results
        except Exception as e:
            logger.error(f"列出 21 点锦标赛失败: {e}")
            return []

    def list_blackjack_tournaments_with_playing_entries(
        self, tournament_ids: list[int]
    ) -> set[int] | None:
        """批量返回仍有 `ENTRY_PLAYING` 报名的赛事 id。

        给 tick 的完赛阶段用：一次 IN 查出本轮进行中赛事里谁还没打完。
        空列表不打库。不读 `play_deadline`——截止与全员终态的取舍在调用方。

        查询失败返回 None，**不得**返回空集：空集会被 tick 当成「全员终态」
        而提前结算。
        """
        ids = [int(tid) for tid in tournament_ids]
        if not ids:
            return set()
        try:
            with get_session() as session:
                rows = session.execute(
                    select(BlackjackTournamentEntry.tournament_id)
                    .where(
                        BlackjackTournamentEntry.tournament_id.in_(ids),
                        BlackjackTournamentEntry.status == self.ENTRY_PLAYING,
                    )
                    .distinct()
                ).all()
                return {int(r[0]) for r in rows}
        except Exception as e:
            logger.error(f"查询仍有进行中报名的锦标赛失败: {e}")
            return None

    def count_registering_blackjack_tournaments(self, now_ms: int) -> int | None:
        """统计报名尚未截止的赛事数，给每周自动开赛的去重闸门用。

        只看「报名中且报名截止晚于当前」：本周自动建的周赛报名截止固定在周三
        18:00，任务重复触发（重启补跑 / 误配双任务）时第二次会在这里被挡下；
        管理员本周手动建的、报名仍开放的赛事同样计入——再自动建一场即形成排期
        重叠。比较的是纯整数毫秒列，不受时区存储差异影响。

        查询失败返回 None 而非 0：调用方需要区分「确认没有」与「没查到」——
        自动创建宁可漏一期（管理员可手动补建）也不能重复建两场。
        """
        try:
            with get_session() as session:
                count = (
                    session.execute(
                        select(func.count(BlackjackTournament.id)).where(
                            BlackjackTournament.status == self.TOURNAMENT_REGISTERING,
                            BlackjackTournament.register_deadline_ms > int(now_ms),
                        )
                    ).scalar()
                    or 0
                )
                return int(count)
        except Exception as e:
            logger.error(f"统计报名中的锦标赛数量失败: {e}")
            return None

    def get_blackjack_tournament_standings(self, tournament_id: int) -> list[dict]:
        """全场排名。进行中按当前筹码排序，已结算按最终名次排序。

        排序口径与结算时完全一致（筹码降序，并列由报名时点较早者列前），使进行中
        看到的顺序不会在结算那一刻莫名重排。

        **是否已结算按赛事状态判定，不能靠「所有行都有 final_rank」**：无资格者
        （既没打完也没被淘汰）永远拿不到 final_rank，而设计上就假定这种人存在，
        故那个条件几乎恒假——已结算的赛事会掉进临时位次分支，按筹码重排，让一个
        坐等不打的人顶着「第 1」和真正的冠军并列显示。无资格者在已结算的赛事里
        **两个名次字段都留空**，由前端渲染成「无名次」。
        """
        try:
            with get_session() as session:
                settled = (
                    session.execute(
                        select(BlackjackTournament.status).where(
                            BlackjackTournament.id == int(tournament_id)
                        )
                    ).scalar()
                    == self.TOURNAMENT_SETTLED
                )
                entries = (
                    session.execute(
                        select(BlackjackTournamentEntry)
                        .where(
                            BlackjackTournamentEntry.tournament_id == int(tournament_id)
                        )
                        .order_by(
                            BlackjackTournamentEntry.chips.desc(),
                            BlackjackTournamentEntry.registered_at_ms.asc(),
                        )
                    )
                    .scalars()
                    .all()
                )
                rows = [self._tournament_entry_to_dict(e) for e in entries]
                if settled:
                    # 有名次的按名次升序在前，无资格者维持筹码序垫在最后
                    rows.sort(
                        key=lambda r: (
                            r["final_rank"] is None,
                            r["final_rank"] if r["final_rank"] is not None else 0,
                        )
                    )
                else:
                    for i, r in enumerate(rows, start=1):
                        r["provisional_rank"] = i
                return rows
        except Exception as e:
            logger.error(f"获取 21 点锦标赛排名失败 (id={tournament_id}): {e}")
            return []

    def get_user_blackjack_tournament_entry(
        self, tg_id: int, tournament_id: int
    ) -> dict | None:
        """该用户在某赛事中的报名。"""
        try:
            with get_session() as session:
                entry = (
                    session.execute(
                        select(BlackjackTournamentEntry).where(
                            BlackjackTournamentEntry.tournament_id
                            == int(tournament_id),
                            BlackjackTournamentEntry.tg_id == int(tg_id),
                        )
                    )
                    .scalars()
                    .one_or_none()
                )
                return self._tournament_entry_to_dict(entry) if entry else None
        except Exception as e:
            logger.error(
                f"获取 21 点锦标赛报名失败 (tg_id={tg_id}, id={tournament_id}): {e}"
            )
            return None

    def count_user_blackjack_tournament_titles(self, tg_id: int) -> int:
        """该用户的锦标赛冠军次数。

        由 `final_rank == 1` 数出，不新增存储。这是个人统计里的展示项，**不是
        榜单**——spec 明确锦标赛赛果不进入任何榜单。
        """
        try:
            with get_session() as session:
                return int(
                    session.execute(
                        select(func.count(BlackjackTournamentEntry.id)).where(
                            BlackjackTournamentEntry.tg_id == int(tg_id),
                            BlackjackTournamentEntry.final_rank == 1,
                        )
                    ).scalar_one()
                    or 0
                )
        except Exception as e:
            logger.error(f"获取 21 点冠军次数失败 (tg_id={tg_id}): {e}")
            return 0

    def check_blackjack_tournament_consistency(self, tournament_id: int) -> dict | None:
        """比对 `entrant_count` 与 entry 实际行数，供管理端校验。

        两者只在同一事务内一起变动，本不该漂移；但 `entrant_count` 是奖池推导的
        因子，一旦漂移会直接影响派奖金额，故提供一处显式校验而不是等出问题再查。
        """
        try:
            with get_session() as session:
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
                    return None
                actual = int(
                    session.execute(
                        select(func.count(BlackjackTournamentEntry.id)).where(
                            BlackjackTournamentEntry.tournament_id == int(tournament_id)
                        )
                    ).scalar_one()
                    or 0
                )
                counter = int(tournament.entrant_count)
                return {
                    "tournament_id": int(tournament_id),
                    "entrant_count": counter,
                    "entry_rows": actual,
                    "consistent": counter == actual,
                }
        except Exception as e:
            logger.error(f"校验 21 点锦标赛一致性失败 (id={tournament_id}): {e}")
            return None

    def _lock_tournament_entry(
        self, session, tournament_id: int, tg_id: int
    ) -> BlackjackTournamentEntry:
        """取报名行并加锁。赛内路径上它替代现金局的 `Statistics`。"""
        entry = (
            session.execute(
                select(BlackjackTournamentEntry)
                .where(
                    BlackjackTournamentEntry.tournament_id == int(tournament_id),
                    BlackjackTournamentEntry.tg_id == int(tg_id),
                )
                .with_for_update()
            )
            .scalars()
            .one_or_none()
        )
        if not entry:
            raise ValueError("tournament entry not found")
        return entry

    def _apply_tournament_entry_terminal_status(
        self,
        entry: BlackjackTournamentEntry,
        tournament: BlackjackTournament | None,
    ) -> None:
        """按打完手数与剩余筹码判定报名的终态。

        打满总手数记已打完；筹码不足最小注记已淘汰（不必等归零——低于最小注就
        再也发不出牌了，让他挂在「进行中」只会让他误以为还能打）。两者都具备派奖
        资格，区别仅在于展示与统计口径。

        **这条规则只此一份**：结算适配层与投降各写一遍时，两份的空值防护就已经
        分了叉，而任何一次口径调整（比如把淘汰线从「低于最小注」改成「归零」）
        都必须同时改两处，漏一处就会让投降的人拿到与其他人不同的终态。
        """
        total_hands = int(tournament.total_hands) if tournament else 0
        min_bet = int(tournament.min_bet_chips) if tournament else 0
        if total_hands and int(entry.hands_played) >= total_hands:
            entry.status = self.ENTRY_FINISHED
        elif min_bet and int(entry.chips) < min_bet:
            entry.status = self.ENTRY_ELIMINATED

    def _tournament_total_hands(self, session, tournament_id: int) -> int | None:
        """取赛事的总手数，供动作响应算「剩余手数」。

        动作响应里捎回它，路由层就不必为了这一个数字再开一次事务去查赛事——那次
        查询失败会返回 `None`，而路由层原本会直接下标取值，把一次已经落库并按筹码
        赔付完毕的结算变成 500。
        """
        value = session.execute(
            select(BlackjackTournament.total_hands).where(
                BlackjackTournament.id == int(tournament_id)
            )
        ).scalar()
        return int(value) if value is not None else None

    def _tournament_entry_state(self, session, tournament_id: int, tg_id: int) -> dict:
        """动作未使手牌结算时的筹码与进度快照。"""
        entry = self._lock_tournament_entry(session, int(tournament_id), int(tg_id))
        return {
            "chips": int(entry.chips),
            "hands_played": int(entry.hands_played),
            "entry_status": int(entry.status),
            "total_hands": self._tournament_total_hands(session, int(tournament_id)),
        }

    def _tournament_already_settled_result(self, session, hand: BlackjackHand) -> dict:
        """本次结算未生效（他人已抢先结算）时的返回值。

        **必须捎上 entry 的三个字段**：路由层会把缺失的键兜底成 `0 / 0 / 1`，而前端
        拿到就直接覆盖本地状态——玩家的筹码栈会显示成 0、进度回退到 0/N，直到他
        重新打开牌桌。这条路径并不罕见：十分钟一次的兜底扫描与用户自己的停牌撞在
        一起就会走到（`with_for_update()` 在 SQLite 上是 no-op，CAS 正是为此存在）。

        entry 缺失只记日志、不抛异常：本方法也在清场路径上被调用，那里抛异常会让
        手牌停在非终态、赛事永远清不干净，比少三个展示字段严重得多。
        """
        result = {
            "hand": self._blackjack_hand_to_dict(hand),
            "already_settled": True,
        }
        entry = (
            session.execute(
                select(BlackjackTournamentEntry).where(
                    BlackjackTournamentEntry.tournament_id == int(hand.tournament_id),
                    BlackjackTournamentEntry.tg_id == int(hand.tg_id),
                )
            )
            .scalars()
            .one_or_none()
        )
        if entry:
            result["chips"] = int(entry.chips)
            result["hands_played"] = int(entry.hands_played)
            result["entry_status"] = int(entry.status)
        else:
            logger.error(
                f"赛内手牌 {int(hand.id)} 找不到对应报名行 "
                f"(tournament={hand.tournament_id}, tg_id={hand.tg_id})"
            )
        result["total_hands"] = self._tournament_total_hands(
            session, int(hand.tournament_id)
        )
        return result
