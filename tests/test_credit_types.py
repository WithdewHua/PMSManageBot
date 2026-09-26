from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.domains.credits import exceptions as credit_exceptions
from app.domains.credits import types as credit_types


def test_credit_account_reference_identifies_one_account() -> None:
    assert credit_types.CreditAccount.tg(123).label == "tg:123"
    assert credit_types.CreditAccount.plex(456).label == "plex:456"
    assert credit_types.CreditAccount.emby("abc").label == "emby:abc"
    assert credit_types.CreditAccount("tg", "123").identifier == 123


@pytest.mark.parametrize(
    ("kind", "identifier"),
    [
        ("invalid", 1),
        ("tg", 0),
        ("plex", -1),
        ("emby", ""),
        ("tg", True),
        ("tg", "not-a-number"),
        ("tg", 1.2),
        ("emby", "   "),
    ],
)
def test_credit_account_rejects_invalid_reference(
    kind: str, identifier: object
) -> None:
    with pytest.raises(ValueError):
        credit_types.CreditAccount(kind, identifier)


def test_credit_account_and_mutation_are_immutable() -> None:
    account = credit_types.CreditAccount.tg(10)
    mutation = credit_types.CreditMutation(account, 1.0, 3.0, 2.0, ())
    with pytest.raises(FrozenInstanceError):
        account.identifier = 20
    with pytest.raises(FrozenInstanceError):
        mutation.after = 4.0


@pytest.mark.parametrize(
    "amount", [0, -1, float("nan"), float("inf"), float("-inf"), True, "not-a-number"]
)
def test_credit_amount_rejects_invalid_deltas(amount: object) -> None:
    with pytest.raises((TypeError, ValueError), match="finite and positive"):
        credit_types.validate_amount(amount)


def test_credit_amount_accepts_positive_finite_values() -> None:
    assert credit_types.validate_amount(0.01) == 0.01
    assert credit_types.validate_amount(1) == 1.0


def test_insufficient_credits_carries_structured_context() -> None:
    error: credit_exceptions.InsufficientCredits = (
        credit_exceptions.InsufficientCredits("tg:10", 5.0, 2.0)
    )
    assert isinstance(error, ValueError)
    assert error.account == "tg:10"
    assert error.requested == 5.0
    assert error.available == 2.0
    assert "requested=5.00" in str(error)
