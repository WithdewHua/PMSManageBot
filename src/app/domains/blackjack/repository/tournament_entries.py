"""21 点 repository：参赛记录、排名与一致性查询（由 part_N 机械拆分）。"""

from sqlalchemy import func, select

from app.core.db import get_session
from app.core.log import logger
from app.domains.blackjack.exceptions import blackjack_error
from app.domains.blackjack.models import (
    BlackjackHand,
    BlackjackTournament,
    BlackjackTournamentEntry,
)


class _BlackjackRepositoryTournamentEntries:
    def _list_tournament_entrant_ids(self, session, tournament_id: int) -> list[int]:
        """该赛事全部报名者的 tg_id，供通知使用。"""
        rows = session.execute(
            select(BlackjackTournamentEntry.tg_id)
            .where(BlackjackTournamentEntry.tournament_id == int(tournament_id))
            .order_by(BlackjackTournamentEntry.registered_at_ms.asc())
        ).all()
        return [int(r[0]) for r in rows]

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
            raise blackjack_error("tournament entry not found")
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
