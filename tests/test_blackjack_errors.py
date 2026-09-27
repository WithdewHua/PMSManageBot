from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.errors import DomainError
from app.domains.blackjack import exceptions
from app.domains.blackjack.router import cash, tournament


def test_blackjack_errors_are_structured_and_legacy_compatible() -> None:
    error = exceptions.blackjack_error("insufficient credits to double: need 10")

    assert isinstance(error, DomainError)
    assert isinstance(error, ValueError)
    assert error.code == "blackjack_insufficient_credits_to_double"
    assert error.payload["detail"] == "insufficient credits to double: need 10"


def test_cash_error_adapter_preserves_existing_http_detail() -> None:
    with pytest.raises(HTTPException) as caught:
        cash._raise_for_value_error(exceptions.blackjack_error("hand already finished"))

    assert caught.value.status_code == 400
    assert caught.value.detail == "该手牌已结束"


def test_tournament_error_adapter_preserves_existing_http_detail() -> None:
    with pytest.raises(HTTPException) as caught:
        tournament._raise_for_value_error(
            exceptions.blackjack_error("registration closed")
        )

    assert caught.value.status_code == 400
    assert caught.value.detail == "报名已截止"
