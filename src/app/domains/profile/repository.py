"""Read-only profile projections; no writes or transaction-owned mutations."""

from sqlalchemy import select

from app.core.db import get_session
from app.domains.identity.models import Statistics


def list_user_balances() -> list[tuple[int, float, float]]:
    """Preserve the unfiltered user-selection query and its database ordering."""
    with get_session() as session:
        return [
            tuple(row)
            for row in session.execute(
                select(Statistics.tg_id, Statistics.donation, Statistics.credits)
            ).all()
        ]
