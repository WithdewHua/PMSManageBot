from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domains.accounts import service as accounts_service
from app.domains.accounts.config import ACCOUNTS_CONFIG
from app.domains.invitation import router as invitation_router
from app.domains.invitation import service as invitation_service
from app.domains.invitation.config import INVITATION_CONFIG


@pytest.mark.asyncio
async def test_register_status_reads_persisted_account_config(session_env) -> None:
    ACCOUNTS_CONFIG.invalidate()
    accounts_service.set_registration_enabled("plex", True)
    accounts_service.set_registration_enabled("emby", False)

    assert await invitation_router.get_register_status() == {
        "plex": True,
        "emby": False,
    }


def test_invitation_credits_update_survives_cache_rebuild(session_env) -> None:
    INVITATION_CONFIG.invalidate()
    assert invitation_service.set_invitation_credits(777) == 777
    INVITATION_CONFIG.invalidate()
    assert invitation_service.get_invitation_credits() == 777

    with pytest.raises(ValidationError):
        invitation_service.set_invitation_credits(True)
