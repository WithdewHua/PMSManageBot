from __future__ import annotations

import pytest

from app.core.db import get_session
from app.domains.identity.models import PlexUser, Statistics
from app.domains.media_access import service as media_access_service


def _seed_user(tg_id: int = 1, credits: float = 100.0, **columns) -> None:
    with get_session() as session:
        session.add(Statistics(tg_id=tg_id, credits=credits, donation=0.0))
        session.add(
            PlexUser(
                plex_id=tg_id * 10,
                tg_id=tg_id,
                plex_email=f"{tg_id}@example.com",
                plex_username=f"plex{tg_id}",
                **columns,
            )
        )


def _state(tg_id: int = 1) -> tuple[float, int, str | None]:
    with get_session() as session:
        stats = session.get(Statistics, tg_id)
        user = session.query(PlexUser).filter_by(tg_id=tg_id).one()
        return float(stats.credits), int(user.all_lib), user.unlock_time


@pytest.mark.asyncio
async def test_nsfw_unlock_sync_failure_compensates_database_and_credits(
    session_env, monkeypatch
):
    _seed_user()

    class FailingPlex:
        def get_libraries(self):
            return ["Movies"]

        def update_user_shared_libs(self, *_args):
            raise RuntimeError("media unavailable")

    monkeypatch.setattr(media_access_service, "Plex", FailingPlex)

    with pytest.raises(RuntimeError, match="media unavailable"):
        await media_access_service.unlock_nsfw(1, "plex", 25)

    assert _state() == (100.0, 0, None)


@pytest.mark.asyncio
async def test_nsfw_compensation_failure_notifies_admin(session_env, monkeypatch):
    _seed_user()
    notified = []

    class FailingPlex:
        def get_libraries(self):
            return ["Movies"]

        def update_user_shared_libs(self, *_args):
            raise RuntimeError("media unavailable")

    monkeypatch.setattr(media_access_service, "Plex", FailingPlex)

    def fail_compensation(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        "app.domains.media_access.repository.compensate_nsfw_unlock_tx",
        fail_compensation,
    )

    async def record(*args):
        notified.append(args)

    monkeypatch.setattr(
        "app.domains.media_access.notifications.notify_nsfw_compensation_failed",
        record,
    )

    with pytest.raises(RuntimeError, match="media unavailable"):
        await media_access_service.unlock_nsfw(1, "plex", 25)

    assert notified and notified[0][0:3] == (1, "plex", "unlock")
