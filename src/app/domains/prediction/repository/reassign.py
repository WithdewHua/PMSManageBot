"""Prediction domain Telegram ID reassignment operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import update

from app.domains.identity.types import TgIdReassignIssue
from app.domains.prediction.models import (
    PredictionBet,
    PredictionMarket,
    PredictionMarketSubmission,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

REASSIGNED_TG_ID_COLUMNS: tuple[str, ...] = (
    "prediction_bet.tg_id",
    "prediction_market_submission.submitter_tg_id",
    "prediction_market_submission.reviewed_by",
    "prediction_market.created_by",
    "prediction_market.resolved_by",
)


def check_tg_id_reassign_tx(
    session: Session, old_tg_id: int, new_tg_id: int
) -> list[TgIdReassignIssue]:
    return []


def reassign_tg_id_tx(
    session: Session, old_tg_id: int, new_tg_id: int
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model, column in (
        (PredictionBet, PredictionBet.tg_id),
        (PredictionMarketSubmission, PredictionMarketSubmission.submitter_tg_id),
        (PredictionMarketSubmission, PredictionMarketSubmission.reviewed_by),
        (PredictionMarket, PredictionMarket.created_by),
        (PredictionMarket, PredictionMarket.resolved_by),
    ):
        result = session.execute(
            update(model)
            .where(column == int(old_tg_id))
            .values({column: int(new_tg_id)})
        )
        counts[f"{model.__tablename__}.{column.key}"] = max(
            0, int(result.rowcount or 0)
        )
    return counts


__all__ = [
    "REASSIGNED_TG_ID_COLUMNS",
    "check_tg_id_reassign_tx",
    "reassign_tg_id_tx",
]
