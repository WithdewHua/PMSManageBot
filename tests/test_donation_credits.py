from __future__ import annotations

import pytest

from app.core.db import get_session
from app.domains.credits.exceptions import InsufficientCredits
from app.domains.donation import repository
from app.domains.identity.models import Statistics


def test_donation_repricing_commits_all_credit_deltas(session_env) -> None:
    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=101, donation=10, credits=20),
                Statistics(tg_id=202, donation=5, credits=20),
            ]
        )

    repository.update_donation_credits(1.0, 1.5)

    with get_session() as session:
        users = {
            row.tg_id: row.credits
            for row in session.query(Statistics)
            .filter(Statistics.tg_id.in_([101, 202]))
            .all()
        }
    assert users == {101: 25, 202: 22.5}


def test_donation_repricing_rolls_back_earlier_users_on_insufficient_funds(
    session_env,
) -> None:
    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=101, donation=1, credits=20),
                Statistics(tg_id=202, donation=10, credits=0),
            ]
        )

    with pytest.raises(InsufficientCredits, match="insufficient credits"):
        repository.update_donation_credits(1.0, 0.0)

    with get_session() as session:
        users = {
            row.tg_id: row.credits
            for row in session.query(Statistics)
            .filter(Statistics.tg_id.in_([101, 202]))
            .all()
        }
    assert users == {101: 20, 202: 0}
