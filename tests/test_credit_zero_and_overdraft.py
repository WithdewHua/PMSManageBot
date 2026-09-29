"""fix-live-defects D1：零额积分变动与会员流量费透支。

修复前：`add`/`deduct`/`add_tx`/`deduct_tx` 对 0 抛 ValueError（默认配置下
NSFW 锁定退款为 0 就会中途报错）；`move_tx` 只迁移正余额，会员流量欠款被
留在随后删除的旧账户上。修复后 0 为无操作、欠款随账户迁移。
"""

from __future__ import annotations

import pytest

from app.core.db import get_session
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.exceptions import InsufficientCredits
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import PlexUser, Statistics


def _plex_row(plex_id: int, credits: float, username: str | None = "owner") -> None:
    with get_session() as session:
        session.add(
            PlexUser(
                plex_id=plex_id,
                plex_email=f"{plex_id}@example.com",
                plex_username=username,
                credits=credits,
            )
        )


def _plex_credits(plex_id: int) -> float:
    from sqlalchemy import select

    with get_session() as session:
        row = session.execute(
            select(PlexUser).where(PlexUser.plex_id == int(plex_id))
        ).scalar_one()
        return float(row.credits)


def _tg_credits(tg_id: int) -> float:
    with get_session() as session:
        row = session.get(Statistics, int(tg_id))
        assert row is not None
        return float(row.credits)


class TestZeroAmountNoOp:
    def test_add_zero_keeps_balance(self, session_env):
        with get_session() as session:
            session.add(Statistics(tg_id=1, credits=50.0, donation=0.0))

        mutation = credits_service.add(CreditAccount.tg(1), 0)
        assert mutation.before == 50.0
        assert mutation.after == 50.0
        assert mutation.delta == 0
        assert _tg_credits(1) == 50.0

    def test_deduct_zero_keeps_balance(self, session_env):
        with get_session() as session:
            session.add(Statistics(tg_id=1, credits=50.0, donation=0.0))

        mutation = credits_service.deduct(CreditAccount.tg(1), 0)
        assert mutation.before == 50.0
        assert mutation.after == 50.0
        assert mutation.delta == 0
        assert _tg_credits(1) == 50.0

    def test_add_tx_zero_no_write(self, session_env):
        with get_session() as session:
            session.add(Statistics(tg_id=1, credits=50.0, donation=0.0))
            session.flush()
            mutation = credits_repository.add_tx(session, CreditAccount.tg(1), 0)
            session.commit()
        assert mutation.delta == 0
        assert _tg_credits(1) == 50.0

    def test_deduct_tx_zero_no_write(self, session_env):
        with get_session() as session:
            session.add(Statistics(tg_id=1, credits=50.0, donation=0.0))
            session.flush()
            mutation = credits_repository.deduct_tx(session, CreditAccount.tg(1), 0)
            session.commit()
        assert mutation.delta == 0
        assert _tg_credits(1) == 50.0


class TestAmountGuardsUnchanged:
    def test_zero_still_requires_account(self, session_env):
        with pytest.raises(ValueError):
            credits_service.add(CreditAccount.tg(404), 0)

    def test_negative_still_rejected(self, session_env):
        with get_session() as session:
            session.add(Statistics(tg_id=1, credits=50.0, donation=0.0))
        with pytest.raises(ValueError):
            credits_service.add(CreditAccount.tg(1), -1)
        with pytest.raises(ValueError):
            credits_service.deduct(CreditAccount.tg(1), -1)
        assert _tg_credits(1) == 50.0


class TestPremiumTrafficOverdraft:
    def test_overdraft_deducts_full_amount(self, session_env):
        with get_session() as session:
            session.add(Statistics(tg_id=1, credits=5.0, donation=0.0))
            session.flush()
            mutation = credits_repository.charge_premium_traffic_tx(
                session, CreditAccount.tg(1), 20.0
            )
            session.commit()
        assert mutation.before == 5.0
        assert mutation.after == -15.0
        assert _tg_credits(1) == -15.0


class TestNonOverdraftRulesUnchanged:
    def test_normal_deduct_still_rejects_overdraft(self, session_env):
        with get_session() as session:
            session.add(Statistics(tg_id=1, credits=5.0, donation=0.0))
        with pytest.raises(InsufficientCredits):
            credits_service.deduct(CreditAccount.tg(1), 20.0)
        assert _tg_credits(1) == 5.0

    def test_negative_balance_user_cannot_buy(self, session_env):
        with get_session() as session:
            session.add(Statistics(tg_id=1, credits=-15.0, donation=0.0))
        with pytest.raises(InsufficientCredits):
            credits_service.deduct(CreditAccount.tg(1), 10.0)


class TestMoveCarriesDebt:
    def test_negative_balance_moves_to_target(self, session_env):
        with get_session() as session:
            session.add(Statistics(tg_id=1, credits=40.0, donation=0.0))
        _plex_row(101, -15.0)

        result = credits_repository.move(CreditAccount.plex(101), CreditAccount.tg(1))
        assert result.amount == -15.0
        assert _tg_credits(1) == 25.0
        assert _plex_credits(101) == 0.0
