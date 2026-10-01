"""Transaction-owned orchestration for Telegram identity reassignment."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, replace

from sqlalchemy import func, select

from app.core.db import get_session
from app.domains.identity import repository as identity_repository
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.identity.types import TgIdReassignIssue, TgIdReassignSource
from app.domains.tg_rebind.exceptions import (
    TgRebindAccountNotFound,
    TgRebindRejected,
    TgRebindSameId,
)
from app.domains.tg_rebind.types import RebindReport


@dataclass(frozen=True, slots=True)
class _LocatedIdentity:
    tg_id: int | None
    media_kind: str | None = None
    media_key: int | str | None = None
    media_id: int | str | None = None


_PARTICIPANT_IMPORTS = {
    "identity": "app.domains.identity.repository",
    "credits": "app.domains.credits.repository",
    "donation": "app.domains.donation.repository",
    "blackjack": "app.domains.blackjack.repository",
    "badges": "app.domains.badges.repository",
    "gift_pack": "app.domains.gift_pack.repository",
    "luckywheel": "app.domains.luckywheel.repository",
    "treasure": "app.domains.treasure.repository",
    "prediction": "app.domains.prediction.repository",
    "auction": "app.domains.auction.repository",
    "invitation": "app.domains.invitation.repository",
    "lines": "app.domains.lines.repository",
    "custom_lines": "app.domains.custom_lines.repository",
    "crypto_donation": "app.domains.crypto_donation.repository",
    "vaultwarden": "app.domains.vaultwarden.repository",
    "watch_rewards": "app.domains.watch_rewards.repository",
}


def _participants() -> list[tuple[str, object]]:
    ordered_domains = (
        "gift_pack",
        "blackjack",
        "luckywheel",
        "treasure",
        "prediction",
        "auction",
        "invitation",
        "custom_lines",
        "lines",
        "badges",
        "donation",
        "crypto_donation",
        "vaultwarden",
        "watch_rewards",
        "credits",
        "identity",
    )
    return [
        (domain, importlib.import_module(_PARTICIPANT_IMPORTS[domain]))
        for domain in ordered_domains
    ]


def locate_old_identity_tx(
    session,
    *,
    from_tg_id: int | None = None,
    plex_email: str | None = None,
    emby_username: str | None = None,
) -> _LocatedIdentity:
    provided = sum(
        value is not None for value in (from_tg_id, plex_email, emby_username)
    )
    if provided != 1:
        raise ValueError("exactly one old identity locator is required")
    if from_tg_id is not None:
        if (
            session.execute(
                select(Statistics.tg_id).where(Statistics.tg_id == int(from_tg_id))
            ).scalar_one_or_none()
            is None
        ):
            raise TgRebindAccountNotFound(str(from_tg_id))
        return _LocatedIdentity(int(from_tg_id))
    if plex_email is not None:
        account = session.execute(
            select(PlexUser).where(
                func.lower(PlexUser.plex_email) == str(plex_email).lower()
            )
        ).scalar_one_or_none()
        if account is None:
            raise TgRebindAccountNotFound(f"plex:{plex_email}")
        return _LocatedIdentity(
            account.tg_id,
            "plex",
            account.id,
            account.plex_id,
        )
    account = session.execute(
        select(EmbyUser).where(
            func.lower(EmbyUser.emby_username) == str(emby_username).lower()
        )
    ).scalar_one_or_none()
    if account is None:
        raise TgRebindAccountNotFound(f"emby:{emby_username}")
    return _LocatedIdentity(
        account.tg_id, "emby", account.emby_username, account.emby_id
    )


def _reassign_unbound_media_tx(
    session, located: _LocatedIdentity, new_tg_id: int
) -> dict[str, dict[str, int]]:
    from app.domains.credits import repository as credits_repository

    source = TgIdReassignSource(
        tg_id=None,
        media_service=located.media_kind,
        media_record_key=located.media_key,
        media_id=located.media_id,
    )
    issues = identity_repository.check_unbound_media_reassign_tx(
        session, source, new_tg_id
    )
    if issues:
        raise TgRebindRejected(issues)
    identity_repository.ensure_statistics_tx(session, new_tg_id)
    credit_counts = credits_repository.move_unbound_media_tx(
        session,
        media_service=str(located.media_kind),
        media_record_key=located.media_key,
        new_tg_id=new_tg_id,
    )
    identity_counts = identity_repository.bind_unbound_media_reassign_tx(
        session, source, new_tg_id
    )
    return {"credits": credit_counts, "identity": identity_counts}


class _DryRunRollback(Exception):
    def __init__(self, report: RebindReport) -> None:
        self.report = report


def rebind_tg_id(
    *,
    new_tg_id: int,
    from_tg_id: int | None = None,
    plex_email: str | None = None,
    emby_username: str | None = None,
    dry_run: bool = False,
) -> RebindReport:
    try:
        with get_session() as session:
            report = rebind_tg_id_tx(
                session,
                new_tg_id=new_tg_id,
                from_tg_id=from_tg_id,
                plex_email=plex_email,
                emby_username=emby_username,
            )
            if dry_run:
                raise _DryRunRollback(replace(report, dry_run=True))
            return report
    except _DryRunRollback as rollback:
        return rollback.report


def rebind_tg_id_tx(
    session,
    *,
    new_tg_id: int,
    from_tg_id: int | None = None,
    plex_email: str | None = None,
    emby_username: str | None = None,
) -> RebindReport:
    new_tg_id = int(new_tg_id)
    located = locate_old_identity_tx(
        session,
        from_tg_id=from_tg_id,
        plex_email=plex_email,
        emby_username=emby_username,
    )
    if located.tg_id is None:
        counts = _reassign_unbound_media_tx(session, located, new_tg_id)
        return RebindReport(
            old_tg_id=0, new_tg_id=new_tg_id, dry_run=False, counts=counts
        )
    old_tg_id = int(located.tg_id)
    if old_tg_id == new_tg_id:
        raise TgRebindSameId()

    source = TgIdReassignSource(
        tg_id=old_tg_id,
        media_service=located.media_kind,
        media_record_key=located.media_key,
        media_id=located.media_id,
    )
    if not identity_repository.lock_tg_id_reassign_tx(session, source, new_tg_id):
        raise TgRebindAccountNotFound(str(old_tg_id))
    issues: list[TgIdReassignIssue] = []
    participants = _participants()
    for domain, module in participants:
        issues.extend(module.check_tg_id_reassign_tx(session, old_tg_id, new_tg_id))
    if issues:
        raise TgRebindRejected(issues)

    identity_repository.ensure_statistics_tx(session, new_tg_id)
    counts: dict[str, dict[str, int]] = {}
    for domain, module in participants:
        result = module.reassign_tg_id_tx(session, old_tg_id, new_tg_id)
        counts[domain] = dict(result)
    session.flush()
    return RebindReport(old_tg_id, new_tg_id, False, counts)


__all__ = ["locate_old_identity_tx", "rebind_tg_id", "rebind_tg_id_tx"]
