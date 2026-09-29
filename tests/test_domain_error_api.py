from __future__ import annotations

import asyncio
import json

from app.core.errors import DomainError
from app.transport.http.errors import domain_error_content, domain_error_handler


def test_domain_error_api_adapter_preserves_fastapi_detail_shape() -> None:
    error = DomainError(
        "blackjack_disabled",
        "21 点活动当前未开放",
        status_code=400,
        payload={"detail": "21 点活动当前未开放", "internal": "hidden"},
    )

    response = asyncio.run(domain_error_handler(None, error))

    assert response.status_code == 400
    assert json.loads(response.body) == {"detail": "21 点活动当前未开放"}
    assert domain_error_content(error) == {"detail": "21 点活动当前未开放"}
