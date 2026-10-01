"""Gift pack domain Telegram ID reassignment operations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import select, update

from app.domains.gift_pack.models import GiftPack, GiftPackUserState
from app.domains.identity.types import TgIdReassignIssue

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

REASSIGNED_TG_ID_COLUMNS: tuple[str, ...] = (
    "gift_pack.created_by",
    "gift_pack_user_state.tg_id",
    "gift_pack.audience",
)


def _reassign_tg_id_in_audience(
    raw_audience: str | None, old_tg_id: int, new_tg_id: int
) -> tuple[str | None, bool]:
    if not raw_audience:
        return raw_audience, False
    try:
        data = json.loads(raw_audience)
    except (json.JSONDecodeError, TypeError):
        return raw_audience, False
    if not isinstance(data, list):
        return raw_audience, False

    modified = False
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "user_list" and isinstance(item.get("tg_ids"), list):
            tg_ids = item["tg_ids"]
            has_old = False
            for x in tg_ids:
                try:
                    if int(x) == old_tg_id:
                        has_old = True
                        break
                except (ValueError, TypeError):
                    continue
            if not has_old:
                continue

            new_list: list[int] = []
            seen: set[int] = set()
            for x in tg_ids:
                try:
                    val = int(x)
                except (ValueError, TypeError):
                    val = x
                if val == old_tg_id:
                    val = new_tg_id
                if val not in seen:
                    seen.add(val)
                    new_list.append(val)
            item["tg_ids"] = new_list
            modified = True

    if modified:
        return json.dumps(data, ensure_ascii=False), True
    return raw_audience, False


def check_tg_id_reassign_tx(
    session: Session, old_tg_id: int, new_tg_id: int
) -> list[TgIdReassignIssue]:
    """Check for duplicate claim states between old and new identities."""
    if old_tg_id == new_tg_id:
        return []

    old_packs = set(
        session.execute(
            select(GiftPackUserState.pack_id).where(
                GiftPackUserState.tg_id == int(old_tg_id)
            )
        )
        .scalars()
        .all()
    )
    if not old_packs:
        return []

    new_packs = set(
        session.execute(
            select(GiftPackUserState.pack_id).where(
                GiftPackUserState.tg_id == int(new_tg_id)
            )
        )
        .scalars()
        .all()
    )
    common_packs = sorted(old_packs & new_packs)
    if common_packs:
        return [
            TgIdReassignIssue(
                kind="conflict",
                domain="gift_pack",
                description="both IDs have claim state for the same gift pack(s)",
                record_ids=tuple(str(p) for p in common_packs),
            )
        ]
    return []


def reassign_tg_id_tx(
    session: Session, old_tg_id: int, new_tg_id: int
) -> dict[str, int]:
    """Reassign gift pack creator IDs, user states, and audience list IDs."""
    res_created_by = session.execute(
        update(GiftPack)
        .where(GiftPack.created_by == int(old_tg_id))
        .values(created_by=int(new_tg_id))
    )

    res_user_state = session.execute(
        update(GiftPackUserState)
        .where(GiftPackUserState.tg_id == int(old_tg_id))
        .values(tg_id=int(new_tg_id))
    )

    packs_with_audience = (
        session.execute(select(GiftPack).where(GiftPack.audience.is_not(None)))
        .scalars()
        .all()
    )
    audience_updates = 0
    for pack in packs_with_audience:
        new_audience, changed = _reassign_tg_id_in_audience(
            pack.audience, int(old_tg_id), int(new_tg_id)
        )
        if changed:
            pack.audience = new_audience
            audience_updates += 1

    session.flush()
    return {
        "gift_pack.created_by": res_created_by.rowcount,
        "gift_pack_user_state.tg_id": res_user_state.rowcount,
        "gift_pack.audience": audience_updates,
    }
