"""Operational repairs must not convert subscriptions into permanent unlocks."""

from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from app.core.config import settings
from app.domains.identity.types import PlexAccount
from scripts import reconcile_plex_download_permissions as reconciliation

NOW = datetime(2026, 10, 10, tzinfo=settings.TZ)
BASE = PlexAccount(
    plex_id=123,
    tg_id=456,
    plex_email="user@example.test",
    plex_username="user",
    premium_status_updated_at=1,
)


@pytest.mark.parametrize(
    ("account", "expected", "reason"),
    [
        (
            replace(
                BASE,
                is_premium=1,
                premium_expiry_time=(NOW + timedelta(days=1)).isoformat(),
            ),
            True,
            "active_premium",
        ),
        (replace(BASE, is_premium=1, premium_expiry_time=None), True, "active_premium"),
        (
            replace(
                BASE,
                is_premium=1,
                premium_expiry_time=(NOW - timedelta(days=1)).isoformat(),
            ),
            False,
            "inactive_premium_without_permanent_unlock",
        ),
        (
            replace(BASE, sync_unlocked=1, sync_unlock_time=100),
            True,
            "permanent_download_unlock",
        ),
        (
            replace(
                BASE,
                is_premium=1,
                premium_expiry_time=(NOW - timedelta(days=1)).isoformat(),
                sync_unlocked=1,
                sync_unlock_time=100,
            ),
            True,
            "permanent_download_unlock",
        ),
        (BASE, False, "inactive_premium_without_permanent_unlock"),
        (
            replace(BASE, premium_status_updated_at=None),
            None,
            "no_premium_history_or_permanent_unlock",
        ),
    ],
)
def test_expected_download_entitlement(account, expected, reason) -> None:
    assert reconciliation.expected_permission(account, NOW) == (expected, reason)


@pytest.mark.parametrize(
    "account",
    [
        replace(BASE, is_premium=1, premium_expiry_time="bad-date"),
        replace(BASE, sync_unlocked=1, sync_unlock_time=None),
        replace(BASE, sync_unlocked=2),
    ],
)
def test_unknown_entitlement_is_not_a_revocation(account) -> None:
    with pytest.raises(ValueError):
        reconciliation.expected_permission(account, NOW)


def _state(allowed: bool) -> dict:
    return {
        "allowSync": allowed,
        "allLibraries": False,
        "library_ids": [1, 2],
        "settings": {"allowSync": str(int(allowed)), "allowTuners": "1"},
    }


@pytest.fixture
def repair(monkeypatch):
    client = Mock()
    client.my_plex_account.id = 999
    client.update_sync_for_user.return_value = True
    monkeypatch.setattr(settings, "PLEX_ADMIN_EMAIL", "admin@example.test")
    monkeypatch.setattr(settings, "PLEX_ADMIN_USER", "admin")
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [])
    finder = Mock(return_value=BASE)
    monkeypatch.setattr(reconciliation.identity_service, "find_plex_by_id", finder)
    state = Mock(side_effect=[_state(True), _state(False)])
    monkeypatch.setattr(reconciliation, "read_state", state)
    revoker = Mock()
    monkeypatch.setattr(
        reconciliation.expired_holders, "revoke_download_holder", revoker
    )
    item = {"plex_id": 123, "target": BASE.plex_email, "expected": False}
    return client, finder, state, revoker, item


def test_expired_repair_reuses_explicit_holder_revocation(repair) -> None:
    client, _, _, revoker, item = repair

    result = reconciliation.apply_item(client, item)

    assert result["status"] == "verified"
    revoker.assert_called_once_with({"service": "plex", "target": BASE.plex_email})
    client.update_sync_for_user.assert_not_called()


def test_paid_unlock_after_audit_prevents_revocation(repair) -> None:
    client, finder, _, revoker, item = repair
    finder.return_value = replace(BASE, sync_unlocked=1, sync_unlock_time=100)

    assert (
        reconciliation.apply_item(client, item)["status"]
        == "skipped_entitlement_changed"
    )

    client.update_sync_for_user.assert_not_called()
    revoker.assert_not_called()


def test_renewal_during_repair_restores_download(repair) -> None:
    client, finder, state, revoker, item = repair
    renewed = replace(BASE, is_premium=1, premium_expiry_time=None)
    finder.side_effect = [BASE, renewed]
    state.side_effect = [_state(True), _state(True)]

    assert reconciliation.apply_item(client, item)["status"] == "verified"

    revoker.assert_called_once()
    client.update_sync_for_user.assert_called_once_with(
        BASE.plex_email, allow_sync=True
    )


def test_permanent_unlock_enable_is_verified(repair) -> None:
    client, finder, state, revoker, item = repair
    finder.return_value = replace(BASE, sync_unlocked=1, sync_unlock_time=100)
    state.side_effect = [_state(False), _state(True)]
    item["expected"] = True

    assert reconciliation.apply_item(client, item)["status"] == "verified"

    client.update_sync_for_user.assert_called_once_with(
        BASE.plex_email, allow_sync=True
    )
    revoker.assert_not_called()


def test_false_adapter_result_is_not_success(repair) -> None:
    client, finder, state, _, item = repair
    finder.return_value = replace(BASE, sync_unlocked=1, sync_unlock_time=100)
    state.return_value = _state(False)
    state.side_effect = None
    client.update_sync_for_user.return_value = False
    item["expected"] = True

    with pytest.raises(RuntimeError, match="enable failed"):
        reconciliation.apply_item(client, item)


def test_identity_change_does_not_modify_any_account(repair) -> None:
    client, finder, _, revoker, item = repair
    finder.return_value = replace(BASE, plex_email="someone-else@example.test")

    with pytest.raises(ValueError, match="identity changed"):
        reconciliation.apply_item(client, item)

    revoker.assert_not_called()
    client.update_sync_for_user.assert_not_called()
