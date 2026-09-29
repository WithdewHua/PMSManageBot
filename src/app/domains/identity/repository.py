"""Identity queries and transaction-owned identity mutations.

The module-level functions are the typed identity boundary. The temporary
SQLAlchemy-free DatabaseORM compatibility facade lives in ``identity.compat``.
"""

from __future__ import annotations

import json

from sqlalchemy import delete, func, select, update

from app.core.db import get_session, register_post_commit
from app.core.log import logger
from app.domains.identity.cache import user_info_cache
from app.domains.identity.models import EmbyUser, Overseerr, PlexUser, Statistics
from app.domains.identity.types import (
    EmbyAccount,
    OverseerrAccount,
    PlexAccount,
    UserStatistics,
)


def _plex_account(row: PlexUser | None) -> PlexAccount | None:
    if row is None:
        return None
    return PlexAccount(
        plex_id=row.plex_id,
        tg_id=row.tg_id,
        credits=row.credits,
        plex_email=row.plex_email,
        plex_username=row.plex_username,
        all_lib=row.all_lib,
        unlock_time=row.unlock_time,
        watched_time=row.watched_time,
        plex_line=row.plex_line,
        is_premium=row.is_premium,
        premium_expiry_time=row.premium_expiry_time,
        premium_status_updated_at=row.premium_status_updated_at,
        line_schedule_unlocked=row.line_schedule_unlocked,
        line_schedule_unlock_time=row.line_schedule_unlock_time,
        last_viewed_at=row.last_viewed_at,
        sync_unlocked=row.sync_unlocked,
        sync_unlock_time=row.sync_unlock_time,
        premium_traffic_debt_bytes=row.premium_traffic_debt_bytes,
        premium_traffic_debt_updated_date=row.premium_traffic_debt_updated_date,
    )


def _emby_account(row: EmbyUser | None) -> EmbyAccount | None:
    if row is None:
        return None
    return EmbyAccount(
        emby_username=row.emby_username,
        emby_id=row.emby_id,
        tg_id=row.tg_id,
        emby_is_unlock=row.emby_is_unlock,
        emby_unlock_time=row.emby_unlock_time,
        emby_watched_time=row.emby_watched_time,
        emby_credits=row.emby_credits,
        emby_line=row.emby_line,
        is_premium=row.is_premium,
        premium_expiry_time=row.premium_expiry_time,
        premium_status_updated_at=row.premium_status_updated_at,
        line_schedule_unlocked=row.line_schedule_unlocked,
        line_schedule_unlock_time=row.line_schedule_unlock_time,
        last_viewed_at=row.last_viewed_at,
        download_unlocked=row.download_unlocked,
        download_unlock_time=row.download_unlock_time,
        premium_traffic_debt_bytes=row.premium_traffic_debt_bytes,
        premium_traffic_debt_updated_date=row.premium_traffic_debt_updated_date,
    )


def _statistics(row: Statistics | None) -> UserStatistics | None:
    if row is None:
        return None
    return UserStatistics(
        tg_id=row.tg_id,
        donation=row.donation,
        credits=row.credits,
        tournament_wallet_credits=row.tournament_wallet_credits,
        blackjack_lose_streak=row.blackjack_lose_streak,
        blackjack_hands_since_freespin=row.blackjack_hands_since_freespin,
    )


def _overseerr_account(row: Overseerr | None) -> OverseerrAccount | None:
    if row is None:
        return None
    return OverseerrAccount(
        user_id=row.user_id,
        user_email=row.user_email,
        tg_id=row.tg_id,
    )


def find_plex_by_tg_tx(
    session, tg_id: int, *, for_update: bool = False
) -> PlexAccount | None:
    statement = select(PlexUser).where(PlexUser.tg_id == int(tg_id))
    if for_update:
        statement = statement.with_for_update()
    return _plex_account(session.execute(statement).scalar_one_or_none())


def find_plex_by_id_tx(
    session, plex_id: int, *, for_update: bool = False
) -> PlexAccount | None:
    statement = select(PlexUser).where(PlexUser.plex_id == int(plex_id))
    if for_update:
        statement = statement.with_for_update()
    return _plex_account(session.execute(statement).scalar_one_or_none())


def find_plex_by_email_tx(
    session, plex_email: str, *, for_update: bool = False
) -> PlexAccount | None:
    statement = select(PlexUser).where(
        func.lower(PlexUser.plex_email) == str(plex_email).lower()
    )
    if for_update:
        statement = statement.with_for_update()
    return _plex_account(session.execute(statement).scalar_one_or_none())


def find_emby_by_tg_tx(
    session, tg_id: int, *, for_update: bool = False
) -> EmbyAccount | None:
    statement = select(EmbyUser).where(EmbyUser.tg_id == int(tg_id))
    if for_update:
        statement = statement.with_for_update()
    return _emby_account(session.execute(statement).scalar_one_or_none())


def find_emby_by_username_tx(
    session, username: str, *, for_update: bool = False
) -> EmbyAccount | None:
    statement = select(EmbyUser).where(
        func.lower(EmbyUser.emby_username) == str(username).lower()
    )
    if for_update:
        statement = statement.with_for_update()
    return _emby_account(session.execute(statement).scalar_one_or_none())


def get_statistics_tx(
    session, tg_id: int, *, for_update: bool = False
) -> UserStatistics | None:
    statement = select(Statistics).where(Statistics.tg_id == int(tg_id))
    if for_update:
        statement = statement.with_for_update()
    return _statistics(session.execute(statement).scalar_one_or_none())


def find_overseerr_by_tg_tx(
    session, tg_id: int, *, for_update: bool = False
) -> OverseerrAccount | None:
    statement = select(Overseerr).where(Overseerr.tg_id == int(tg_id))
    if for_update:
        statement = statement.with_for_update()
    return _overseerr_account(session.execute(statement).scalar_one_or_none())


def find_overseerr_by_email_tx(
    session, email: str, *, for_update: bool = False
) -> OverseerrAccount | None:
    statement = select(Overseerr).where(Overseerr.user_email == email)
    if for_update:
        statement = statement.with_for_update()
    return _overseerr_account(session.execute(statement).scalar_one_or_none())


def count_bound_plex_users_tx(session) -> int:
    """Count Plex accounts that have an accepted Plex id."""
    return int(
        session.execute(
            select(func.count(PlexUser.plex_id)).where(PlexUser.plex_id.is_not(None))
        ).scalar_one()
    )


def list_statistics_tg_ids_tx(session) -> list[int]:
    return list(session.execute(select(Statistics.tg_id)).scalars().all())


def find_plex_by_tg(tg_id: int, *, for_update: bool = False) -> PlexAccount | None:
    with get_session() as session:
        return find_plex_by_tg_tx(session, tg_id, for_update=for_update)


def find_plex_by_id(plex_id: int, *, for_update: bool = False) -> PlexAccount | None:
    with get_session() as session:
        return find_plex_by_id_tx(session, plex_id, for_update=for_update)


def find_plex_by_email(
    plex_email: str, *, for_update: bool = False
) -> PlexAccount | None:
    with get_session() as session:
        return find_plex_by_email_tx(session, plex_email, for_update=for_update)


def find_unresolved_plex_by_email_tx(
    session, plex_email: str, *, for_update: bool = False
) -> PlexAccount | None:
    statement = select(PlexUser).where(
        func.lower(PlexUser.plex_email) == str(plex_email).lower(),
        PlexUser.plex_id.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    return _plex_account(session.execute(statement).scalar_one_or_none())


def find_unresolved_plex_by_email(
    plex_email: str, *, for_update: bool = False
) -> PlexAccount | None:
    with get_session() as session:
        return find_unresolved_plex_by_email_tx(
            session, plex_email, for_update=for_update
        )


def find_emby_by_tg(tg_id: int, *, for_update: bool = False) -> EmbyAccount | None:
    with get_session() as session:
        return find_emby_by_tg_tx(session, tg_id, for_update=for_update)


def find_emby_by_username(
    username: str, *, for_update: bool = False
) -> EmbyAccount | None:
    with get_session() as session:
        return find_emby_by_username_tx(session, username, for_update=for_update)


def get_statistics(tg_id: int, *, for_update: bool = False) -> UserStatistics | None:
    with get_session() as session:
        return get_statistics_tx(session, tg_id, for_update=for_update)


def find_overseerr_by_tg(
    tg_id: int, *, for_update: bool = False
) -> OverseerrAccount | None:
    with get_session() as session:
        return find_overseerr_by_tg_tx(session, tg_id, for_update=for_update)


def find_overseerr_by_email(
    email: str, *, for_update: bool = False
) -> OverseerrAccount | None:
    with get_session() as session:
        return find_overseerr_by_email_tx(session, email, for_update=for_update)


def count_bound_plex_users() -> int:
    with get_session() as session:
        return count_bound_plex_users_tx(session)


def list_statistics_tg_ids() -> list[int]:
    with get_session() as session:
        return list_statistics_tg_ids_tx(session)


def list_plex_ids() -> set[int]:
    with get_session() as session:
        return list_plex_ids_tx(session)


def list_unresolved_plex_emails(target_email: str | None = None) -> list[str]:
    with get_session() as session:
        return list_unresolved_plex_emails_tx(session, target_email)


def update_plex_identity(
    *, plex_id: int, plex_username: str, plex_email: str | None
) -> str | None:
    with get_session() as session:
        return update_plex_identity_tx(
            session,
            plex_id=plex_id,
            plex_username=plex_username,
            plex_email=plex_email,
        )


def update_plex_last_viewed(values: dict[int, int]) -> int:
    with get_session() as session:
        return update_plex_last_viewed_tx(session, values)


def update_emby_last_viewed(values: dict[str, int | None]) -> int:
    with get_session() as session:
        return update_emby_last_viewed_tx(session, values)


def list_emby_usernames() -> list[str]:
    with get_session() as session:
        return list_emby_usernames_tx(session)


def ensure_statistics_tx(session, tg_id: int) -> Statistics:
    """Return the TG statistics row, creating it in the caller transaction."""
    stats = session.execute(
        select(Statistics).where(Statistics.tg_id == int(tg_id)).with_for_update()
    ).scalar_one_or_none()
    if stats is None:
        stats = Statistics(tg_id=int(tg_id), credits=0, donation=0)
        session.add(stats)
        session.flush()
    return stats


def bind_plex_user_tx(
    session,
    *,
    tg_id: int,
    plex_id: int,
    plex_email: str | None = None,
    plex_username: str | None = None,
) -> PlexUser:
    statement = select(PlexUser).where(
        PlexUser.plex_id == int(plex_id), PlexUser.tg_id.is_(None)
    )
    user = session.execute(statement.with_for_update()).scalar_one_or_none()
    if user is None and plex_email:
        user = session.execute(
            select(PlexUser)
            .where(
                func.lower(PlexUser.plex_email) == str(plex_email).lower(),
                PlexUser.plex_id.is_(None),
                PlexUser.tg_id.is_(None),
            )
            .with_for_update()
        ).scalar_one_or_none()
    if user is None:
        raise ValueError("Plex account is missing or already bound")
    user.plex_id = int(plex_id)
    user.tg_id = int(tg_id)
    if plex_email and not user.plex_email:
        user.plex_email = plex_email
    if plex_username:
        user.plex_username = plex_username
    session.flush()
    return user


def create_plex_user_tx(
    session,
    *,
    plex_id: int,
    tg_id: int | None,
    plex_email: str,
    plex_username: str | None,
    credits: float,
    all_lib: int,
    watched_time: float,
) -> PlexUser:
    user = PlexUser(
        plex_id=int(plex_id),
        tg_id=int(tg_id) if tg_id is not None else None,
        credits=float(credits),
        plex_email=plex_email,
        plex_username=plex_username,
        all_lib=int(all_lib),
        watched_time=float(watched_time),
    )
    session.add(user)
    session.flush()
    return user


def bind_emby_user_tx(session, *, tg_id: int, emby_id: str) -> None:
    result = session.execute(
        update(EmbyUser)
        .where(EmbyUser.emby_id == str(emby_id), EmbyUser.tg_id.is_(None))
        .values(tg_id=int(tg_id))
    )
    if result.rowcount != 1:
        raise ValueError("Emby account is missing or already bound")


def create_emby_user_tx(
    session, *, emby_username: str, emby_id: str, tg_id: int | None
) -> EmbyUser:
    user = EmbyUser(
        emby_username=emby_username,
        emby_id=str(emby_id),
        tg_id=int(tg_id) if tg_id is not None else None,
    )
    session.add(user)
    session.flush()
    return user


def _publish_plex_cache(user: PlexUser) -> None:
    if not user.plex_username:
        return
    user_info_cache.put(
        f"plex:{user.plex_username.lower()}",
        json.dumps(
            {
                "plex_id": user.plex_id,
                "tg_id": user.tg_id,
                "plex_email": user.plex_email,
                "plex_username": user.plex_username,
                "is_premium": user.is_premium,
            }
        ),
    )


def _publish_emby_cache(user: EmbyUser) -> None:
    user_info_cache.put(
        f"emby:{user.emby_username.lower()}",
        json.dumps(
            {
                "emby_id": user.emby_id,
                "tg_id": user.tg_id,
                "emby_username": user.emby_username,
                "is_premium": user.is_premium,
            }
        ),
    )


def write_user_info_cache() -> None:
    with get_session() as session:
        plex_users = session.execute(select(PlexUser)).scalars().all()
        emby_users = session.execute(select(EmbyUser)).scalars().all()
    for user in plex_users:
        _publish_plex_cache(user)
    for user in emby_users:
        _publish_emby_cache(user)


def add_plex_user_tx(
    session,
    *,
    plex_id: int | None = None,
    tg_id: int | None = None,
    plex_email: str | None = None,
    plex_username: str | None = None,
    credits: float = 0,
    all_lib: int = 0,
    unlock_time: str | None = None,
    watched_time: float = 0,
    plex_line: str | None = None,
    is_premium: int = 0,
    premium_expiry_time: str | None = None,
) -> PlexUser:
    user = PlexUser(
        plex_id=plex_id,
        tg_id=tg_id,
        credits=credits,
        plex_email=plex_email,
        plex_username=plex_username,
        all_lib=all_lib,
        unlock_time=unlock_time,
        watched_time=watched_time,
        plex_line=plex_line,
        is_premium=is_premium,
        premium_expiry_time=premium_expiry_time,
    )
    session.add(user)
    session.flush()
    if plex_username:
        register_post_commit(
            session,
            f"identity:plex-cache:{plex_username.lower()}",
            lambda user=user: _publish_plex_cache(user),
        )
    return user


def add_plex_user(**kwargs) -> bool:
    try:
        with get_session() as session:
            add_plex_user_tx(session, **kwargs)
        return True
    except Exception as error:
        logger.error(f"Error adding plex user: {error}")
        return False


def delete_plex_user(plex_email: str) -> bool:
    try:
        with get_session() as session:
            session.execute(
                delete(PlexUser).where(
                    func.lower(PlexUser.plex_email) == str(plex_email).lower()
                )
            )
        return True
    except Exception as error:
        logger.error(f"Error deleting plex user: {error}")
        return False


def add_emby_user_tx(
    session,
    *,
    emby_username: str,
    emby_id: str | None = None,
    tg_id: int | None = None,
    emby_is_unlock: int = 0,
    emby_unlock_time: int | None = None,
    emby_watched_time: float = 0,
    emby_credits: float = 0,
    emby_line: str | None = None,
    is_premium: int = 0,
    premium_expiry_time: str | None = None,
) -> EmbyUser:
    user = EmbyUser(
        emby_username=emby_username,
        emby_id=emby_id,
        tg_id=tg_id,
        emby_is_unlock=emby_is_unlock,
        emby_unlock_time=emby_unlock_time,
        emby_watched_time=emby_watched_time,
        emby_credits=emby_credits,
        emby_line=emby_line,
        is_premium=is_premium,
        premium_expiry_time=premium_expiry_time,
    )
    session.add(user)
    session.flush()
    register_post_commit(
        session,
        f"identity:emby-cache:{emby_username.lower()}",
        lambda user=user: _publish_emby_cache(user),
    )
    return user


def add_emby_user(**kwargs) -> bool:
    try:
        with get_session() as session:
            add_emby_user_tx(session, **kwargs)
        return True
    except Exception as error:
        logger.error(f"Error adding emby user: {error}")
        return False


def add_user_data_tx(
    session, *, tg_id: int, credits: float = 0, donation: float = 0
) -> Statistics:
    stats = Statistics(tg_id=int(tg_id), credits=credits, donation=donation)
    session.add(stats)
    session.flush()
    return stats


def add_user_data(tg_id: int, credits: float = 0, donation: float = 0) -> bool:
    try:
        with get_session() as session:
            add_user_data_tx(session, tg_id=tg_id, credits=credits, donation=donation)
        return True
    except Exception as error:
        logger.error(f"Error adding user data: {error}")
        return False


def add_overseerr_user(user_id: int, user_email: str, tg_id: int) -> bool:
    try:
        with get_session() as session:
            add_overseerr_user_tx(
                session, user_id=user_id, user_email=user_email, tg_id=tg_id
            )
        return True
    except Exception as error:
        logger.error(f"Error adding overseerr user: {error}")
        return False


def list_plex_ids_tx(session) -> set[int]:
    return {
        int(plex_id)
        for plex_id in session.execute(
            select(PlexUser.plex_id).where(PlexUser.plex_id.is_not(None))
        ).scalars()
    }


def list_unresolved_plex_emails_tx(
    session, target_email: str | None = None
) -> list[str]:
    statement = select(PlexUser.plex_email).where(PlexUser.plex_id.is_(None))
    if target_email:
        statement = statement.where(PlexUser.plex_email == target_email)
    return [email for email in session.execute(statement).scalars().all() if email]


def update_plex_identity_tx(
    session, *, plex_id: int, plex_username: str, plex_email: str | None
) -> str | None:
    """Update a Plex identity and return its previous username when changed."""
    user = session.execute(
        select(PlexUser).where(PlexUser.plex_id == int(plex_id)).with_for_update()
    ).scalar_one_or_none()
    if user is None:
        return None
    old_username = user.plex_username
    if old_username == plex_username and user.plex_email == plex_email:
        return ""
    user.plex_username = plex_username
    user.plex_email = plex_email
    session.flush()
    return old_username or ""


def resolve_plex_user_by_email_tx(
    session, *, email: str, plex_id: int, plex_username: str
) -> bool:
    """Fill one invited Plex row in the caller-owned transaction."""

    result = session.execute(
        update(PlexUser)
        .where(
            func.lower(PlexUser.plex_email) == str(email).lower(),
            PlexUser.plex_id.is_(None),
        )
        .values(plex_id=int(plex_id), plex_username=plex_username)
    )
    return result.rowcount == 1


def update_plex_last_viewed_tx(session, values: dict[int, int]) -> int:
    updated = 0
    for plex_id, last_viewed_at in values.items():
        if last_viewed_at <= 0:
            continue
        result = session.execute(
            update(PlexUser)
            .where(PlexUser.plex_id == int(plex_id))
            .values(last_viewed_at=int(last_viewed_at))
        )
        updated += int(result.rowcount or 0)
    return updated


def update_emby_last_viewed_tx(session, values: dict[str, int | None]) -> int:
    updated = 0
    for emby_id, last_viewed_at in values.items():
        if last_viewed_at is None:
            continue
        result = session.execute(
            update(EmbyUser)
            .where(EmbyUser.emby_id == str(emby_id))
            .values(last_viewed_at=int(last_viewed_at))
        )
        updated += int(result.rowcount or 0)
    return updated


def list_emby_usernames_tx(session) -> list[str]:
    return list(session.execute(select(EmbyUser.emby_username)).scalars().all())


def add_overseerr_user_tx(
    session, *, user_id: int, user_email: str, tg_id: int
) -> Overseerr:
    user = Overseerr(user_id=int(user_id), user_email=user_email, tg_id=int(tg_id))
    session.add(user)
    session.flush()
    return user


__all__ = [
    "add_emby_user",
    "add_emby_user_tx",
    "add_overseerr_user",
    "add_overseerr_user_tx",
    "add_plex_user",
    "add_plex_user_tx",
    "add_user_data",
    "add_user_data_tx",
    "bind_emby_user_tx",
    "bind_plex_user_tx",
    "count_bound_plex_users",
    "count_bound_plex_users_tx",
    "create_emby_user_tx",
    "create_plex_user_tx",
    "delete_plex_user",
    "ensure_statistics_tx",
    "find_emby_by_tg",
    "find_emby_by_tg_tx",
    "find_emby_by_username",
    "find_emby_by_username_tx",
    "find_overseerr_by_email",
    "find_overseerr_by_email_tx",
    "find_overseerr_by_tg",
    "find_overseerr_by_tg_tx",
    "find_plex_by_email",
    "find_plex_by_email_tx",
    "find_plex_by_id",
    "find_plex_by_id_tx",
    "find_plex_by_tg",
    "find_plex_by_tg_tx",
    "find_unresolved_plex_by_email",
    "get_statistics",
    "get_statistics_tx",
    "list_emby_usernames",
    "list_emby_usernames_tx",
    "list_plex_ids",
    "list_plex_ids_tx",
    "list_statistics_tg_ids",
    "list_statistics_tg_ids_tx",
    "list_unresolved_plex_emails",
    "list_unresolved_plex_emails_tx",
    "resolve_plex_user_by_email_tx",
    "update_emby_last_viewed",
    "update_emby_last_viewed_tx",
    "update_plex_identity",
    "update_plex_identity_tx",
    "update_plex_last_viewed",
    "update_plex_last_viewed_tx",
    "write_user_info_cache",
]
