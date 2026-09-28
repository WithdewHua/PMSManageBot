"""Premium day grants move into premium's caller-owned `*_tx` (design D2).

Gift packs extend Premium membership, so the columns stay owned by premium and the
gift-pack side only passes its session. These cases pin the four grant shapes the
legacy `update_premium_status` produced — new grant, renewal from a live expiry,
restart after an expired one, and the permanent-member skip — plus the rollback and
post-commit sync boundary.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.db import get_session
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.premium import repository as premium_repository
from app.domains.premium import service as premium_service

ROOT = Path(__file__).parents[1]
SERVICE_MODULE = ROOT / "src/app/domains/premium/service.py"


def _bind_plex(tg_id: int, **cols) -> None:
    with get_session() as session:
        session.add(
            PlexUser(
                plex_id=tg_id * 10,
                tg_id=tg_id,
                plex_email=f"{tg_id}@x",
                plex_username=f"p{tg_id}",
                **cols,
            )
        )


def _bind_emby(tg_id: int, **cols) -> None:
    with get_session() as session:
        session.add(
            EmbyUser(
                emby_username=f"e{tg_id}",
                emby_id=f"emby-{tg_id}",
                tg_id=tg_id,
                **cols,
            )
        )


def _plex_cols(tg_id: int) -> dict:
    with get_session() as session:
        row = session.execute(
            PlexUser.__table__.select().where(PlexUser.tg_id == tg_id)
        ).one()
        return {
            "is_premium": row.is_premium,
            "expiry": row.premium_expiry_time,
            "updated_at": row.premium_status_updated_at,
        }


def _emby_cols(tg_id: int) -> dict:
    with get_session() as session:
        row = session.execute(
            EmbyUser.__table__.select().where(EmbyUser.tg_id == tg_id)
        ).one()
        return {"is_premium": row.is_premium, "expiry": row.premium_expiry_time}


def test_new_grant_sets_premium_and_records_the_transition(session_env) -> None:
    _bind_plex(1)

    with get_session() as session:
        new_expiry = premium_repository.grant_premium_days_tx(session, 1, "plex", 7)

    assert new_expiry is not None
    cols = _plex_cols(1)
    assert cols["is_premium"] == 1
    assert cols["expiry"] == new_expiry.isoformat()
    # 首次成为 Premium 才写 premium_status_updated_at
    assert cols["updated_at"] is not None


def test_renewal_extends_from_the_live_expiry(session_env) -> None:
    live = datetime.now(settings.TZ) + timedelta(days=3)
    _bind_plex(2, is_premium=1, premium_expiry_time=live.isoformat())
    updated_at_before = _plex_cols(2)["updated_at"]

    with get_session() as session:
        new_expiry = premium_repository.grant_premium_days_tx(session, 2, "plex", 7)

    assert new_expiry is not None
    assert new_expiry == live + timedelta(days=7)
    assert _plex_cols(2)["updated_at"] == updated_at_before


def test_expired_membership_restarts_from_now(session_env) -> None:
    expired = datetime.now(settings.TZ) - timedelta(days=30)
    _bind_emby(3, is_premium=1, premium_expiry_time=expired.isoformat())

    with get_session() as session:
        new_expiry = premium_repository.grant_premium_days_tx(session, 3, "emby", 5)

    assert new_expiry is not None
    assert new_expiry > datetime.now(settings.TZ) + timedelta(days=4)
    assert _emby_cols(3) == {"is_premium": 1, "expiry": new_expiry.isoformat()}


def test_permanent_member_is_skipped(session_env) -> None:
    _bind_plex(4, is_premium=1, premium_expiry_time=None)

    with get_session() as session:
        new_expiry = premium_repository.grant_premium_days_tx(session, 4, "plex", 30)

    assert new_expiry is None
    assert _plex_cols(4)["expiry"] is None


def test_unbound_account_still_raises_name_error(session_env) -> None:
    with get_session() as session, pytest.raises(NameError, match="Plex"):
        premium_repository.grant_premium_days_tx(session, 5, "plex", 30)


def test_grant_rolls_back_with_the_caller(session_env) -> None:
    _bind_plex(6)

    with pytest.raises(RuntimeError, match="claim failed"), get_session() as session:
        premium_repository.grant_premium_days_tx(session, 6, "plex", 7)
        raise RuntimeError("claim failed")

    # 回滚后仍是“未开通”：到期时间为空且没有写入升级时间
    assert _plex_cols(6)["expiry"] is None
    assert _plex_cols(6)["updated_at"] is None


def test_grant_tx_locks_the_media_row() -> None:
    source = (ROOT / "src/app/domains/premium/repository.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    methods = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "grant_premium_days_tx"
        and node.args.args
        and node.args.args[0].arg == "self"
    ]
    assert methods, "PremiumRepository.grant_premium_days_tx 必须存在"
    assert "with_for_update" in ast.unparse(methods[0])


def test_service_grant_syncs_after_commit(session_env, monkeypatch) -> None:
    _bind_plex(7)
    synced: list[tuple[int, tuple[str, ...]]] = []
    monkeypatch.setattr(
        premium_service,
        "sync_premium_media_access",
        lambda tg_id, services=None: synced.append((tg_id, tuple(services or ()))),
    )

    new_expiry = premium_service.update_premium_status(7, "plex", 3)

    assert new_expiry is not None
    assert synced == [(7, ("plex",))]


def test_permanent_member_does_not_trigger_a_sync(session_env, monkeypatch) -> None:
    _bind_plex(8, is_premium=1, premium_expiry_time=None)
    monkeypatch.setattr(
        premium_service,
        "sync_premium_media_access",
        lambda *args, **kwargs: pytest.fail("永久会员不应触发媒体权限同步"),
    )

    assert premium_service.update_premium_status(8, "plex", 3) is None


def test_sync_function_has_no_facade_parameter() -> None:
    import inspect

    for name in ("sync_premium_media_access", "apply_download_unlock_to_media"):
        function = getattr(premium_service, name)
        assert "db" not in inspect.signature(function).parameters, name
        # 函数体也不能再借用门面：读取媒体账号标识走 premium 自己的 repository
        body = inspect.getsource(function)
        assert "db." not in body and "from app.databases import db" not in body, name


def test_sync_skips_services_without_a_bound_media_account(
    session_env, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.integrations.plex.Plex",
        lambda: pytest.fail("未绑定 Plex 账号不应推送同步权限"),
    )
    monkeypatch.setattr(
        "app.integrations.emby.Emby",
        lambda: pytest.fail("未绑定 Emby 账号不应推送下载权限"),
    )

    premium_service.sync_premium_media_access(9)


def test_sync_premium_media_access_skips_unlocked_downloads(
    session_env, monkeypatch
) -> None:
    _bind_plex(10, unlock_time=123)
    monkeypatch.setattr(
        "app.domains.media_access.service.is_download_unlocked",
        lambda tg_id, service: True,
    )
    monkeypatch.setattr(
        "app.integrations.plex.Plex",
        lambda: pytest.fail("已解锁下载的用户不应再推送 Plex 同步权限"),
    )

    premium_service.sync_premium_media_access(10, ("plex",))
