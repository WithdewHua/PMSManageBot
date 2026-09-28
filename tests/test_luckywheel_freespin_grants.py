from __future__ import annotations

import pytest

from app.core.db import get_session
from app.domains.identity.models import Statistics
from app.domains.luckywheel import repository
from app.domains.luckywheel import repository as luckywheel_repository
from app.domains.luckywheel.models import LuckywheelFreeSpin


def test_grant_free_spins_tx_uses_caller_transaction(session_env) -> None:
    with get_session() as session:
        session.add(Statistics(tg_id=101, donation=0, credits=0))
        rows = repository.grant_free_spins_tx(
            session,
            101,
            2,
            source="blackjack",
            granted_at_ms=100,
            expires_at_ms=200,
            cost_credits=0,
        )
        assert len(rows) == 2
        assert all(row.id is not None for row in rows)

    with get_session() as session:
        rows = session.query(LuckywheelFreeSpin).all()
        assert len(rows) == 2
        assert {row.wheel_stats_source for row in rows} == {"blackjack_free"}
        assert {row.cost_credits_snapshot for row in rows} == {0}


def test_consumption_reads_immutable_snapshot_after_configuration_changes(
    session_env,
) -> None:
    with get_session() as session:
        session.add(Statistics(tg_id=101, donation=0, credits=0))
        repository.grant_free_spins_tx(
            session,
            101,
            1,
            source="gift_pack",
            granted_at_ms=100,
            expires_at_ms=2000000000000,
            cost_credits=7.5,
        )

    claimed = luckywheel_repository.consume_free_spin(101)
    assert claimed is not None
    assert claimed["cost_credits_snapshot"] == 7.5
    assert claimed["wheel_stats_source"] == "gift_pack_free"


def test_grant_free_spins_tx_rolls_back_with_caller_transaction(session_env) -> None:
    with pytest.raises(RuntimeError, match="abort"), get_session() as session:
        session.add(Statistics(tg_id=101, donation=0, credits=0))
        repository.grant_free_spins_tx(
            session,
            101,
            1,
            source="gift_pack",
            granted_at_ms=100,
            expires_at_ms=200,
        )
        raise RuntimeError("abort")

    with get_session() as session:
        assert session.query(LuckywheelFreeSpin).count() == 0
        assert session.get(Statistics, 101) is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"count": 0},
        {"source": "unknown"},
        {"expires_at_ms": 100},
        {"cost_credits": -1},
        {"cost_credits": float("inf")},
    ],
)
def test_grant_free_spins_tx_rejects_invalid_snapshots(session_env, kwargs) -> None:
    with get_session() as session:
        session.add(Statistics(tg_id=101, donation=0, credits=0))
        values = {
            "count": 1,
            "source": "blackjack",
            "granted_at_ms": 100,
            "expires_at_ms": 200,
            "cost_credits": 0,
        }
        values.update(kwargs)
        with pytest.raises(ValueError):
            repository.grant_free_spins_tx(session, 101, **values)
