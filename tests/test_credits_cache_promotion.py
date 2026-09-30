"""Freeze gateway credit keys and binding-dependent balance selection."""

from app.core.db import get_session
from app.domains.credits import cache, jobs
from app.domains.identity.models import EmbyUser, PlexUser, Statistics


def test_cache_refresh_preserves_bound_unbound_and_pending_accounts(
    session_env, monkeypatch
):
    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=42, credits=-5),
                PlexUser(plex_id=1, tg_id=42, plex_username="Bound", credits=999),
                PlexUser(plex_id=2, plex_username="Unbound", credits=12),
                PlexUser(plex_id=None, plex_username="Pending", credits=17),
                PlexUser(
                    plex_id=3, tg_id=99, plex_username="MissingStats", credits=888
                ),
                EmbyUser(emby_username="EmbyBound", tg_id=42, emby_credits=777),
                EmbyUser(emby_username="EmbyUnbound", emby_credits=23),
            ]
        )
    written = {}
    monkeypatch.setattr(
        cache.user_credits_cache, "put", lambda key, value: written.update({key: value})
    )
    jobs.rewrite_users_credits_to_redis()
    assert written == {
        "plex:bound": -5,
        "plex:unbound": 12,
        "plex:missingstats": 0,
        "emby:embybound": -5,
        "emby:embyunbound": 23,
    }
