"""Atomic account-binding transactions."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.core.db import get_session
from app.core.events import publish
from app.domains.accounts.events import PlexUserIdResolved
from app.domains.accounts.exceptions import AccountAlreadyBound
from app.domains.credits import repository as credits_repository
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
            try:
                bound_user = identity_repository.bind_plex_user_tx(
                    session,
                    tg_id=tg_id,
                    plex_id=plex_id,
                    plex_email=plex_email,
                    plex_username=plex_username,
                )
            except (IntegrityError, ValueError) as error:
                raise AccountAlreadyBound() from error
            credits_repository.move_tx(
                session,
                CreditAccount.plex(plex_id),
                CreditAccount.tg(tg_id),
            )
            publish(
                session,
                PlexUserIdResolved(
                    email=bound_user.plex_email or plex_email,
                    plex_id=int(plex_id),
                ),
            )
            return

        try:
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
        except IntegrityError as error:
            raise AccountAlreadyBound() from error
        if existing_credits > 0:
            credits_repository.add_tx(
                session, CreditAccount.tg(tg_id), existing_credits
            )


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
            try:
                identity_repository.bind_emby_user_tx(
                    session, tg_id=tg_id, emby_id=emby_id
                )
            except (IntegrityError, ValueError) as error:
                raise AccountAlreadyBound() from error
            credits_repository.move_tx(
                session,
                CreditAccount.emby(emby_id),
                CreditAccount.tg(tg_id),
            )
            return

        try:
            identity_repository.create_emby_user_tx(
                session,
                emby_username=emby_username,
                emby_id=emby_id,
                tg_id=tg_id,
            )
        except IntegrityError as error:
            raise AccountAlreadyBound() from error


def resolve_plex_user_by_email(*, email: str, plex_id: int, plex_username: str) -> bool:
    """Resolve an invited Plex row and publish its event after commit."""
    with get_session() as session:
        resolved = identity_repository.resolve_plex_user_by_email_tx(
            session,
            email=email,
            plex_id=plex_id,
            plex_username=plex_username,
        )
        if resolved:
            publish(session, PlexUserIdResolved(email=email, plex_id=int(plex_id)))
        return resolved


def create_invited_plex_user(*, tg_id: int | None, email: str) -> bool:
    with get_session() as session:
        if tg_id is not None:
            identity_repository.ensure_statistics_tx(session, int(tg_id))
        identity_repository.add_plex_user_tx(
            session,
            tg_id=int(tg_id) if tg_id is not None else None,
            plex_email=email,
            plex_id=None,
            credits=0,
        )
        return True


def create_invited_emby_user(
    *, emby_username: str, emby_id: str, tg_id: int | None
) -> bool:
    with get_session() as session:
        if tg_id is not None:
            identity_repository.ensure_statistics_tx(session, int(tg_id))
        identity_repository.add_emby_user_tx(
            session,
            emby_username=emby_username,
            emby_id=emby_id,
            tg_id=tg_id,
        )
        return True


__all__ = [
    "bind_emby_account",
    "bind_plex_account",
    "create_invited_emby_user",
    "create_invited_plex_user",
    "resolve_plex_user_by_email",
]
