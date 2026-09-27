from __future__ import annotations

import pytest

from app.core.errors import DomainError


def test_domain_error_preserves_structured_response_context() -> None:
    cause = RuntimeError("database unavailable")
    error = DomainError(
        "blackjack_disabled",
        "21 点活动当前未开放",
        status_code=409,
        payload={"activity": "blackjack"},
        cause=cause,
    )

    assert str(error) == "21 点活动当前未开放"
    assert error.message == "21 点活动当前未开放"
    assert error.code == "blackjack_disabled"
    assert error.status_code == 409
    assert error.as_response() == {
        "activity": "blackjack",
        "code": "blackjack_disabled",
        "message": "21 点活动当前未开放",
    }
    assert error.__cause__ is cause


@pytest.mark.parametrize(
    "kwargs",
    [
        {"code": "", "message": "bad"},
        {"code": "ok", "message": "bad", "status_code": 99},
        {"code": "ok", "message": "bad", "status_code": 600},
    ],
)
def test_domain_error_rejects_invalid_metadata(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        DomainError(**kwargs)
