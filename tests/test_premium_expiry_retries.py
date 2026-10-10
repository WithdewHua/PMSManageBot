"""Failed post-commit Premium cleanup remains discoverable after the next scan."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import get_session
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.premium import repository, service


@pytest.fixture
def external_services(monkeypatch):
    plex_update = Mock(return_value=True)
    emby_update = Mock(return_value=(True, "ok"))
    notify = AsyncMock()
    unbind = Mock(return_value="自动线路")
    monkeypatch.setattr(
        "app.integrations.plex.Plex",
        lambda: SimpleNamespace(update_sync_for_user=plex_update),
    )
    monkeypatch.setattr(
        "app.integrations.emby.Emby",
        lambda: SimpleNamespace(update_download_permission_for_user=emby_update),
    )
    monkeypatch.setattr(service, "send_message_by_url", notify)
    monkeypatch.setattr(service, "_unbind_premium_line", unbind)
    return SimpleNamespace(
        plex=plex_update, emby=emby_update, notify=notify, unbind=unbind
    )


def _seed_account(
    media_service: str = "plex",
    tg_id: int = 1,
    *,
    paid_download: bool = False,
    legacy_expiry: bool = False,
    line: str | None = None,
    active: bool = False,
) -> str:
    expiry = (
        datetime.now(settings.TZ) + timedelta(hours=1)
        if active
        else datetime.now(settings.TZ) - timedelta(hours=1)
    )
    expiry_text = str(int(expiry.timestamp())) if legacy_expiry else expiry.isoformat()
    with get_session() as session:
        session.add(Statistics(tg_id=tg_id, credits=100.0, donation=0.0))
        common = {
            "tg_id": tg_id,
            "is_premium": 1,
            "premium_expiry_time": expiry_text,
        }
        if media_service == "plex":
            session.add(
                PlexUser(
                    plex_id=tg_id + 100,
                    plex_email=f"user{tg_id}@example.com",
                    plex_username=f"user{tg_id}",
                    plex_line=line,
                    sync_unlocked=int(paid_download),
                    sync_unlock_time=123 if paid_download else None,
                    **common,
                )
            )
        else:
            session.add(
                EmbyUser(
                    emby_id=f"emby-{tg_id}",
                    emby_username=f"user{tg_id}",
                    emby_line=line,
                    download_unlocked=int(paid_download),
                    download_unlock_time=123 if paid_download else None,
                    **common,
                )
            )
    return expiry_text


def _account_state(media_service: str = "plex", tg_id: int = 1) -> dict:
    model = PlexUser if media_service == "plex" else EmbyUser
    with get_session() as session:
        row = session.execute(
            select(
                model.is_premium,
                model.premium_expiry_time,
                model.premium_status_updated_at,
            ).where(model.tg_id == tg_id)
        ).one()
        return dict(row._mapping)


def _user_notifications(notify: AsyncMock, tg_id: int = 1) -> list:
    return [call for call in notify.await_args_list if call.args[0] == tg_id]


@pytest.mark.parametrize(
    ("media_service", "failure"),
    [
        ("plex", False),
        ("plex", RuntimeError("Plex unavailable")),
        ("emby", (False, "Emby unavailable")),
        ("emby", False),
        ("emby", RuntimeError("Emby timed out")),
    ],
)
async def test_failed_revocation_is_retried(
    external_services, media_service, failure, caplog
) -> None:
    expiry = _seed_account(media_service)
    update = getattr(external_services, media_service)
    if isinstance(failure, Exception):
        update.side_effect = failure
    else:
        update.return_value = failure

    await service.check_premium_expiry()

    first_state = _account_state(media_service)
    assert first_state["is_premium"] == 0
    assert first_state["premium_expiry_time"] == expiry
    assert len(repository.get_expired_premium_users()) == 1
    assert len(_user_notifications(external_services.notify)) == 1
    assert "撤销下载权限失败" in caplog.text
    assert any(
        "撤销下载权限失败" in call.args[1]
        for call in external_services.notify.await_args_list
        if call.args[0] in settings.TG_ADMIN_CHAT_ID
    )

    update.side_effect = None
    update.return_value = True if media_service == "plex" else (True, "ok")
    await service.check_premium_expiry()

    final_state = _account_state(media_service)
    assert final_state["is_premium"] == 0
    assert final_state["premium_expiry_time"] is None
    assert (
        final_state["premium_status_updated_at"]
        == first_state["premium_status_updated_at"]
    )
    assert repository.get_expired_premium_users() == []
    assert update.call_count == 2
    assert len(_user_notifications(external_services.notify)) == 1

    await service.check_premium_expiry()
    assert update.call_count == 2


async def test_permission_query_failure_keeps_cleanup_pending(
    external_services, monkeypatch
) -> None:
    expiry = _seed_account()
    original_check = service.media_access_service.check_download_unlock
    monkeypatch.setattr(
        service.media_access_service,
        "check_download_unlock",
        Mock(side_effect=RuntimeError("query failed")),
    )

    await service.check_premium_expiry()

    external_services.plex.assert_not_called()
    assert _account_state()["is_premium"] == 0
    assert _account_state()["premium_expiry_time"] == expiry
    assert len(_user_notifications(external_services.notify)) == 1

    monkeypatch.setattr(
        service.media_access_service, "check_download_unlock", original_check
    )
    await service.check_premium_expiry()

    external_services.plex.assert_called_once()
    assert _account_state()["premium_expiry_time"] is None
    assert len(_user_notifications(external_services.notify)) == 1


@pytest.mark.parametrize("media_service", ["plex", "emby"])
async def test_paid_download_access_is_preserved(
    external_services, media_service
) -> None:
    _seed_account(media_service, paid_download=True)

    await service.check_premium_expiry()

    getattr(external_services, media_service).assert_not_called()
    assert _account_state(media_service)["is_premium"] == 0
    assert _account_state(media_service)["premium_expiry_time"] is None


@pytest.mark.parametrize("entitlement", ["renewal", "permanent", "paid_download"])
async def test_retry_rechecks_new_entitlements(external_services, entitlement) -> None:
    _seed_account()
    external_services.plex.return_value = False
    await service.check_premium_expiry()

    if entitlement == "renewal":
        repository.grant_premium_days(1, "plex", 1)
    else:
        with get_session() as session:
            row = session.execute(
                select(PlexUser).where(PlexUser.tg_id == 1)
            ).scalar_one()
            if entitlement == "permanent":
                row.is_premium = 1
                row.premium_expiry_time = None
            else:
                row.sync_unlocked = 1
                row.sync_unlock_time = 123
    expected_state = _account_state()
    external_services.plex.reset_mock()

    await service.check_premium_expiry()

    external_services.plex.assert_not_called()
    assert len(_user_notifications(external_services.notify)) == 1
    if entitlement == "paid_download":
        assert _account_state()["premium_expiry_time"] is None
    else:
        assert _account_state() == expected_state


@pytest.mark.parametrize("media_service", ["plex", "emby"])
def test_stale_completion_cannot_clear_a_renewal(media_service) -> None:
    _seed_account(media_service)
    expired = repository.expire_user(1, media_service, datetime.now(settings.TZ))
    assert expired is not None
    assert expired["newly_expired"] is True
    new_expiry = repository.grant_premium_days(1, media_service, 2)
    assert new_expiry is not None

    assert not repository.complete_expiry_cleanup(
        1, media_service, expired["expiry_time"]
    )
    assert _account_state(media_service)["is_premium"] == 1
    assert (
        _account_state(media_service)["premium_expiry_time"] == new_expiry.isoformat()
    )


async def test_renewal_during_entitlement_check_skips_stale_cleanup(
    external_services, monkeypatch
) -> None:
    _seed_account(line="premium-line")

    def renew(tg_id: int, media_service: str) -> bool:
        repository.grant_premium_days(tg_id, media_service, 1)
        return True

    monkeypatch.setattr(service, "is_download_unlocked", renew)
    await service.check_premium_expiry()

    external_services.plex.assert_not_called()
    external_services.unbind.assert_not_called()
    external_services.notify.assert_not_called()
    assert _account_state()["is_premium"] == 1


async def test_failed_user_does_not_block_other_expirations(external_services) -> None:
    _seed_account(tg_id=1)
    _seed_account(tg_id=2)
    external_services.plex.side_effect = [False, True]

    await service.check_premium_expiry()

    assert _account_state(tg_id=1)["premium_expiry_time"] is not None
    assert _account_state(tg_id=2)["premium_expiry_time"] is None
    assert len(_user_notifications(external_services.notify, 1)) == 1
    assert len(_user_notifications(external_services.notify, 2)) == 1


async def test_line_cleanup_failure_is_also_retryable(external_services) -> None:
    _seed_account(line="premium-line")
    external_services.unbind.side_effect = RuntimeError("line cleanup failed")

    await service.check_premium_expiry()
    assert _account_state()["premium_expiry_time"] is not None

    external_services.unbind.side_effect = None
    await service.check_premium_expiry()

    assert _account_state()["premium_expiry_time"] is None
    assert external_services.unbind.call_count == 2
    assert len(_user_notifications(external_services.notify)) == 1


async def test_missing_sync_target_is_not_silently_completed(external_services) -> None:
    _seed_account()
    with get_session() as session:
        row = session.execute(select(PlexUser).where(PlexUser.tg_id == 1)).scalar_one()
        row.plex_email = None

    await service.check_premium_expiry()

    external_services.plex.assert_not_called()
    assert _account_state()["is_premium"] == 0
    assert _account_state()["premium_expiry_time"] is not None


def test_legacy_expiry_is_normalized_so_pending_accounts_can_renew() -> None:
    _seed_account(legacy_expiry=True)
    expired = repository.expire_user(1, "plex", datetime.now(settings.TZ))
    assert expired is not None
    assert _account_state()["premium_expiry_time"] is not None
    assert datetime.fromisoformat(expired["expiry_time"]) < datetime.now(settings.TZ)

    assert repository.grant_premium_days(1, "plex", 1) is not None


def test_bulk_expiration_preserves_pending_cleanup() -> None:
    expiry = _seed_account()

    assert repository.update_expired_premium_status() == 1

    assert _account_state()["is_premium"] == 0
    assert _account_state()["premium_expiry_time"] == expiry
    assert len(repository.get_expired_premium_users()) == 1


@pytest.mark.parametrize(
    ("media_service", "failure"), [("plex", False), ("emby", (False, "denied"))]
)
def test_premium_grant_sync_does_not_log_false_success(
    external_services, monkeypatch, caplog, media_service, failure
) -> None:
    _seed_account(media_service, active=True)
    getattr(external_services, media_service).return_value = failure

    service.sync_premium_media_access(1, (media_service,))

    assert "已为 Premium 用户" not in caplog.text
    assert f"启用 {media_service} 权限失败" in caplog.text
    assert any(record.exc_info for record in caplog.records)


def test_permission_query_error_does_not_turn_a_committed_grant_into_failure(
    external_services, monkeypatch
) -> None:
    _seed_account()
    monkeypatch.setattr(
        service.media_access_service,
        "check_download_unlock",
        Mock(side_effect=RuntimeError("permission query failed")),
    )

    new_expiry = service.update_premium_status(1, "plex", 1)

    assert new_expiry is not None
    assert _account_state()["is_premium"] == 1
    assert _account_state()["premium_expiry_time"] == new_expiry.isoformat()
    external_services.plex.assert_not_called()
