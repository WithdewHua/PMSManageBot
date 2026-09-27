"""Blackjack owns the tournament wallet column; cross-domain credits go through it.

Design D2 supplies one `*_tx` helper per piece of data a gift pack needs, so the
gift-pack repository never writes another domain's columns. This file covers the
wallet helper (lock, SQL increment, rounding, rollback) plus the boundary the
gift-pack code now uses for blackjack hand and tournament-entry counts.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.db import get_session
from app.domains.blackjack import repository as blackjack_repository
from app.domains.blackjack.exceptions import BlackjackError
from app.domains.identity.models import Statistics

ROOT = Path(__file__).parents[1]
WALLET_MODULE = ROOT / "src/app/domains/blackjack/repository/wallet.py"
GIFT_PACK_REPOSITORY = ROOT / "src/app/domains/gift_pack/repository"


def _stats(tg_id: int) -> dict:
    with get_session() as session:
        row = session.execute(
            select(Statistics).where(Statistics.tg_id == tg_id)
        ).scalar_one()
        return {
            "credits": row.credits,
            "wallet": row.tournament_wallet_credits,
        }


def _add_user(tg_id: int, *, wallet: float = 0.0) -> None:
    with get_session() as session:
        session.add(
            Statistics(
                tg_id=tg_id,
                donation=0,
                credits=10.0,
                tournament_wallet_credits=wallet,
            )
        )


def test_wallet_credit_adds_within_the_caller_transaction(session_env) -> None:
    _add_user(101, wallet=1.5)

    with get_session() as session:
        balance = blackjack_repository.credit_tournament_wallet_tx(session, 101, 2.25)

    assert balance == 3.75
    assert _stats(101)["wallet"] == 3.75
    # 争霸赛余额不是积分：积分分支不受影响
    assert _stats(101)["credits"] == 10.0


def test_wallet_credit_rounds_to_two_decimals(session_env) -> None:
    _add_user(102, wallet=0.0)

    with get_session() as session:
        balance = blackjack_repository.credit_tournament_wallet_tx(session, 102, 1.239)

    assert balance == 1.24
    assert _stats(102)["wallet"] == 1.24


def test_wallet_credit_rolls_back_with_the_caller(session_env) -> None:
    _add_user(103, wallet=5.0)

    with pytest.raises(RuntimeError, match="claim failed"), get_session() as session:
        blackjack_repository.credit_tournament_wallet_tx(session, 103, 4.0)
        raise RuntimeError("claim failed")

    assert _stats(103)["wallet"] == 5.0


def test_wallet_credit_rejects_non_positive_amounts(session_env) -> None:
    _add_user(104, wallet=1.0)

    with get_session() as session, pytest.raises(BlackjackError):
        blackjack_repository.credit_tournament_wallet_tx(session, 104, 0)

    with get_session() as session, pytest.raises(BlackjackError):
        blackjack_repository.credit_tournament_wallet_tx(session, 104, -1)

    assert _stats(104)["wallet"] == 1.0


def test_wallet_credit_requires_an_existing_user_row(session_env) -> None:
    with get_session() as session, pytest.raises(BlackjackError, match="积分信息"):
        blackjack_repository.credit_tournament_wallet_tx(session, 999, 1)


def test_wallet_helper_locks_the_row_and_increments_in_sql() -> None:
    """行锁、SQL 增量、两位小数舍入是这份 helper 的契约（design D2）。"""
    calls = {
        node.func.attr
        for node in ast.walk(ast.parse(WALLET_MODULE.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "with_for_update" in calls
    assert "round" in calls  # func.round(..., 2)
    source = WALLET_MODULE.read_text(encoding="utf-8")
    assert "update(Statistics)" in source


def test_gift_pack_repository_does_not_write_the_wallet_column() -> None:
    """礼包只调用 blackjack 的 `*_tx`，不再自己写 tournament_wallet_credits。"""
    offenders: list[str] = []
    users: list[str] = []
    for path in sorted(GIFT_PACK_REPOSITORY.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        users.append(source)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Attribute)
                    and target.attr == "tournament_wallet_credits"
                    for target in node.targets
                )
            ) or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "values"
                and "tournament_wallet_credits" in ast.unparse(node)
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
    assert any(
        "blackjack_repository.credit_tournament_wallet_tx" in source for source in users
    )
