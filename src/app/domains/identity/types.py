"""Typed value objects returned by the identity repository."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlexAccount:
    plex_id: int | None = None
    tg_id: int | None = None
    credits: float = 0.0
    plex_email: str | None = None
    plex_username: str | None = None
    all_lib: int = 0
    unlock_time: str | None = None
    watched_time: float = 0.0
    plex_line: str | None = None
    is_premium: int = 0
    premium_expiry_time: str | None = None
    premium_status_updated_at: int | None = None
    line_schedule_unlocked: int = 0
    line_schedule_unlock_time: int | None = None
    last_viewed_at: int | None = None
    sync_unlocked: int = 0
    sync_unlock_time: int | None = None
    premium_traffic_debt_bytes: int = 0
    premium_traffic_debt_updated_date: str | None = None


@dataclass(frozen=True, slots=True)
class EmbyAccount:
    emby_username: str = ""
    emby_id: str | None = None
    tg_id: int | None = None
    emby_is_unlock: int = 0
    emby_unlock_time: int | None = None
    emby_watched_time: float = 0.0
    emby_credits: float = 0.0
    emby_line: str | None = None
    is_premium: int = 0
    premium_expiry_time: str | None = None
    premium_status_updated_at: int | None = None
    line_schedule_unlocked: int = 0
    line_schedule_unlock_time: int | None = None
    last_viewed_at: int | None = None
    download_unlocked: int = 0
    download_unlock_time: int | None = None
    premium_traffic_debt_bytes: int = 0
    premium_traffic_debt_updated_date: str | None = None


@dataclass(frozen=True, slots=True)
class UserStatistics:
    tg_id: int
    donation: float = 0.0
    credits: float = 0.0
    tournament_wallet_credits: float = 0.0
    blackjack_lose_streak: int = 0
    blackjack_hands_since_freespin: int = 0


@dataclass(frozen=True, slots=True)
class OverseerrAccount:
    user_id: int
    user_email: str | None = None
    tg_id: int | None = None


__all__ = [
    "EmbyAccount",
    "OverseerrAccount",
    "PlexAccount",
    "UserStatistics",
]


# These tuple layouts are part of the temporary DatabaseORM compatibility API.
def plex_legacy_tuple(account: PlexAccount) -> tuple:
    return (
        account.plex_id,
        account.tg_id,
        account.credits,
        account.plex_email,
        account.plex_username,
        account.all_lib,
        account.unlock_time,
        account.watched_time,
        account.plex_line,
        account.is_premium,
        account.premium_expiry_time,
        account.last_viewed_at,
    )


def emby_legacy_tuple(account: EmbyAccount) -> tuple:
    return (
        account.emby_username,
        account.emby_id,
        account.tg_id,
        account.emby_is_unlock,
        account.emby_unlock_time,
        account.emby_watched_time,
        account.emby_credits,
        account.emby_line,
        account.is_premium,
        account.premium_expiry_time,
        account.last_viewed_at,
    )


def statistics_legacy_tuple(stats: UserStatistics) -> tuple:
    return (stats.tg_id, stats.donation, stats.credits)


def overseerr_legacy_tuple(account: OverseerrAccount) -> tuple:
    return (account.user_id, account.user_email, account.tg_id)


__all__ += [
    "emby_legacy_tuple",
    "overseerr_legacy_tuple",
    "plex_legacy_tuple",
    "statistics_legacy_tuple",
]
