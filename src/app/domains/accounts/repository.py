"""Atomic account-binding transactions."""

from __future__ import annotations

from app.core.db import get_session
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity import repository as identity_repository


def bind_plex_account(
    *,
    tg_id: int,
    plex_id: int,
    plex_email: str,
    plex_username: str | None,
    all_lib: int,
    watched_time: float,
    existing_unbound: bool,
    existing_credits: float = 0.0,
) -> None:
    """Bind Plex and move its balance in the same database transaction."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, tg_id)
        if existing_unbound:
            identity_repository.bind_plex_user_tx(session, tg_id=tg_id, plex_id=plex_id)
            result = credits_repository.move_tx(
                session,
                CreditAccount.plex(plex_id),
                CreditAccount.tg(tg_id),
            )
            credits_service.register_cache_invalidation(session, result)
            return

        identity_repository.create_plex_user_tx(
            session,
            plex_id=plex_id,
            tg_id=tg_id,
            plex_email=plex_email,
            plex_username=plex_username,
            credits=0,
            all_lib=all_lib,
            watched_time=watched_time,
        )
        if existing_credits > 0:
            mutation = credits_repository.add_tx(
                session, CreditAccount.tg(tg_id), existing_credits
            )
            credits_service.register_cache_invalidation(session, mutation)


def bind_emby_account(
    *,
    tg_id: int,
    emby_id: str,
    emby_username: str,
    existing_unbound: bool,
) -> None:
    """Bind Emby and move its balance in the same database transaction."""
    with get_session() as session:
        identity_repository.ensure_statistics_tx(session, tg_id)
        if existing_unbound:
            identity_repository.bind_emby_user_tx(session, tg_id=tg_id, emby_id=emby_id)
            result = credits_repository.move_tx(
                session,
                CreditAccount.emby(emby_id),
                CreditAccount.tg(tg_id),
            )
            credits_service.register_cache_invalidation(session, result)
            return

        identity_repository.create_emby_user_tx(
            session,
            emby_username=emby_username,
            emby_id=emby_id,
            tg_id=tg_id,
        )


__all__ = ["bind_emby_account", "bind_plex_account"]
