from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.domains.blackjack import rules


def test_cash_settlement_preserves_ordinary_win_and_rake_math() -> None:
    settlement = rules.calculate_cash_settlement(
        ["10S", "8H"],
        ["9S", "7H"],
        bet=5,
        doubled=False,
        rake_bp=300,
    )

    assert settlement.outcome == rules.OUTCOME_WIN
    assert settlement.return_multiplier == 2.0
    assert settlement.profit_multiplier == 1.0
    assert settlement.gross_profit == 5.0
    assert settlement.rake == 0.15
    assert settlement.payout == 9.85


def test_cash_settlement_preserves_blackjack_and_double_multipliers() -> None:
    blackjack = rules.calculate_cash_settlement(
        ["AS", "KH"],
        ["9S", "7H"],
        bet=10,
        doubled=False,
        blackjack_payout=1.5,
        rake_bp=300,
    )
    doubled = rules.calculate_cash_settlement(
        ["10S", "8H"],
        ["9S", "7H"],
        bet=5,
        doubled=True,
        rake_bp=300,
    )

    assert (
        blackjack.outcome,
        blackjack.gross_profit,
        blackjack.rake,
        blackjack.payout,
    ) == (
        rules.OUTCOME_BLACKJACK,
        15.0,
        0.45,
        24.55,
    )
    assert (
        doubled.outcome,
        doubled.profit_multiplier,
        doubled.rake,
        doubled.payout,
    ) == (
        rules.OUTCOME_WIN,
        2.0,
        0.3,
        19.7,
    )


def test_pure_retention_and_jackpot_calculations() -> None:
    assert rules.calculate_relief_credits(12.34, 1.5) == 18.51
    assert rules.calculate_jackpot_target(123.45, 10) == 12.35
    assert rules.calculate_jackpot_injection(0.3, 5000, 10000) == 0.15
    assert rules.calculate_jackpot_injection(0.3, 5000, 0) == 0.0
    assert rules.calculate_cashback(-10.01, 0.15, 1.0) == 1.5
    assert rules.calculate_cashback(10.01, 0.15, 1.0) is None
    assert rules.calculate_cashback(-2.0, 0.15, 1.0) is None


def test_blackjack_rules_has_no_infrastructure_imports() -> None:
    tree = ast.parse(Path(rules.__file__).read_text(encoding="utf-8"))
    forbidden = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    forbidden |= {
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(
        module == "sqlalchemy" or module.startswith(("sqlalchemy.", "app."))
        for module in forbidden
    )


@pytest.mark.parametrize(
    ("net_change", "rate", "minimum", "expected"),
    [(-100, 0.15, 1, 15), (-6.66, 0.15, 1, 1), (-6.6, 0.15, 1, None)],
)
def test_cashback_rounding_boundaries(net_change, rate, minimum, expected) -> None:
    assert rules.calculate_cashback(net_change, rate, minimum) == expected
