"""Read-only blackjack aggregate queries used by the owning domain services."""

from __future__ import annotations

from sqlalchemy import case, func, select

from app.core.db import get_session
from app.core.log import logger
from app.domains.blackjack import rules
from app.domains.blackjack.config import DEFAULT_BLACKJACK_CONFIG, TOURNAMENT_CANCELLED
from app.domains.blackjack.models import (
    BlackjackHand,
    BlackjackTournament,
    BlackjackTournamentEntry,
)
from app.domains.blackjack.repository import get_blackjack_config_dict


def _rank_rows_tx(session, min_hands: int) -> list[dict]:
    win_flag = case(
        (
            BlackjackHand.outcome.in_([rules.OUTCOME_WIN, rules.OUTCOME_BLACKJACK]),
            1,
        ),
        else_=0,
    )
    hand_count = func.count(BlackjackHand.id).label("hand_count")
    wins = func.sum(win_flag).label("wins")
    decisions_total = func.sum(BlackjackHand.decisions_total).label("decisions_total")
    decisions_correct = func.sum(BlackjackHand.decisions_correct).label(
        "decisions_correct"
    )
    stmt = (
        select(
            BlackjackHand.tg_id,
            hand_count,
            wins,
            decisions_total,
            decisions_correct,
        )
        .where(
            BlackjackHand.status.in_(rules.TERMINAL_STATUSES),
            BlackjackHand.tournament_id.is_(None),
        )
        .group_by(BlackjackHand.tg_id)
        .having(func.count(BlackjackHand.id) >= int(min_hands))
    )
    rows = []
    for row in session.execute(stmt).all():
        hands = int(row[1] or 0)
        decision_count = int(row[3] or 0)
        rows.append(
            {
                "tg_id": row[0],
                "hand_count": hands,
                "win_rate": round(float(row[2] or 0) / hands * 100, 2)
                if hands
                else 0.0,
                "decisions_total": decision_count,
                "accuracy": round(float(row[4] or 0) / decision_count * 100, 2)
                if decision_count
                else 0.0,
            }
        )
    return rows


def get_blackjack_skill_ranks_tx(session, min_hands: int) -> dict:
    """Calculate both cash-game skill leaderboards with a caller-owned session."""
    rows = _rank_rows_tx(session, min_hands)
    return {
        "accuracy": sorted(
            [row for row in rows if row["decisions_total"] > 0],
            key=lambda row: row["accuracy"],
            reverse=True,
        ),
        "win_rate": sorted(rows, key=lambda row: row["win_rate"], reverse=True),
    }


def get_blackjack_skill_ranks(min_hands: int | None = None) -> dict:
    """Return cash-game accuracy and win-rate rankings."""
    if min_hands is None:
        try:
            min_hands = int(
                get_blackjack_config_dict().get(
                    "rank_min_hands", DEFAULT_BLACKJACK_CONFIG["rank_min_hands"]
                )
            )
        except Exception as exc:
            logger.error(f"读取 21 点榜单门槛失败，使用默认值: {exc}")
            min_hands = int(DEFAULT_BLACKJACK_CONFIG["rank_min_hands"])
    try:
        with get_session() as session:
            return get_blackjack_skill_ranks_tx(session, int(min_hands))
    except Exception as exc:
        logger.error(f"获取 21 点技巧类排行失败: {exc}")
        return {"accuracy": [], "win_rate": []}


def get_blackjack_max_win_rank_tx(session) -> list[tuple[int, float, int]]:
    """Get the largest positive per-hand cash-game wins in a caller session."""
    total_stake = case(
        (BlackjackHand.doubled == 1, BlackjackHand.bet_credits * 2),
        else_=BlackjackHand.bet_credits,
    )
    max_win = func.max(
        func.coalesce(BlackjackHand.payout_credits, 0) - total_stake
    ).label("max_win")
    hand_count = func.count(BlackjackHand.id).label("hand_count")
    stmt = (
        select(BlackjackHand.tg_id, max_win, hand_count)
        .where(
            BlackjackHand.status.in_(rules.TERMINAL_STATUSES),
            BlackjackHand.tournament_id.is_(None),
        )
        .group_by(BlackjackHand.tg_id)
        .order_by(max_win.desc())
    )
    return [
        (row[0], round(float(row[1] or 0), 2), int(row[2] or 0))
        for row in session.execute(stmt).fetchall()
        if float(row[1] or 0) > 0
    ]


def get_blackjack_max_win_rank() -> list[tuple[int, float, int]]:
    """Return the largest positive per-hand cash-game wins."""
    try:
        with get_session() as session:
            return get_blackjack_max_win_rank_tx(session)
    except Exception as exc:
        logger.error(f"获取 21 点单手最大赢利排行失败: {exc}")
        return []


def cash_hand_metrics_tx(
    session,
    tg_id: int,
    since: int,
    until: int,
    *,
    min_bet: float | None = None,
    min_accuracy: float | None = None,
) -> int | tuple[int, float]:
    """手牌口径的条件计数：返回手数，或（手数，决策准确率）。

    条件计数只统计已结算的现金局（终态且非锦标赛），毫秒边界用闭区间，
    可选 min_bet / min_accuracy 过滤；准确率按累计决策数加权。
    """
    stmt = select(
        func.count(BlackjackHand.id),
        func.coalesce(func.sum(BlackjackHand.decisions_total), 0),
        func.coalesce(func.sum(BlackjackHand.decisions_correct), 0),
    ).where(
        BlackjackHand.tg_id == int(tg_id),
        BlackjackHand.tournament_id.is_(None),
        BlackjackHand.status.in_(rules.TERMINAL_STATUSES),
        BlackjackHand.created_at_ms >= int(since) * 1000,
        BlackjackHand.created_at_ms <= int(until) * 1000,
    )
    if min_bet is not None:
        stmt = stmt.where(BlackjackHand.bet_credits >= float(min_bet))
    count, total, correct = session.execute(stmt).one()
    count = int(count)
    if min_accuracy is None:
        return count
    accuracy = float(correct) / float(total) * 100 if total else 0.0
    return count, accuracy


def count_tournament_entries_tx(session, tg_id: int, since: int, until: int) -> int:
    """Count non-cancelled tournament entries for a gift-pack audience."""
    stmt = (
        select(func.count(BlackjackTournamentEntry.id))
        .join(
            BlackjackTournament,
            BlackjackTournamentEntry.tournament_id == BlackjackTournament.id,
        )
        .where(
            BlackjackTournamentEntry.tg_id == int(tg_id),
            BlackjackTournament.status != TOURNAMENT_CANCELLED,
            BlackjackTournamentEntry.registered_at_ms >= int(since) * 1000,
            BlackjackTournamentEntry.registered_at_ms <= int(until) * 1000,
        )
    )
    return int(session.execute(stmt).scalar_one())


def get_game_king_eligible_tg_ids_tx(
    session, min_hands: int, min_accuracy: float
) -> list[int]:
    """List blackjack-qualified users for the cross-domain badge award job."""
    stmt = (
        select(BlackjackHand.tg_id)
        .where(
            BlackjackHand.status.in_(rules.TERMINAL_STATUSES),
            BlackjackHand.tournament_id.is_(None),
        )
        .group_by(BlackjackHand.tg_id)
        .having(
            func.count(BlackjackHand.id) >= int(min_hands),
            func.sum(BlackjackHand.decisions_total) > 0,
            func.sum(BlackjackHand.decisions_correct) * 100.0
            >= func.sum(BlackjackHand.decisions_total) * float(min_accuracy),
        )
    )
    return [int(row[0]) for row in session.execute(stmt).all()]


__all__ = [
    "cash_hand_metrics_tx",
    "count_tournament_entries_tx",
    "get_blackjack_max_win_rank",
    "get_blackjack_max_win_rank_tx",
    "get_blackjack_skill_ranks",
    "get_blackjack_skill_ranks_tx",
    "get_game_king_eligible_tg_ids_tx",
]
