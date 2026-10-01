"""Badge storage and caller-owned atomic redemption operations."""

import time
from collections.abc import Iterable

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, joinedload

from app.core.db import get_session
from app.core.log import logger
from app.domains.badges import exceptions
from app.domains.badges.config import BADGE_CENTER_CONFIG
from app.domains.badges.models import Badge, UserBadge
from app.domains.credits import repository as credits_repository
from app.domains.credits.types import CreditAccount
from app.domains.identity import repository as identity_repository
from app.domains.identity.types import TgIdReassignIssue

REASSIGNED_TG_ID_COLUMNS: tuple[str, ...] = ("user_badges.tg_id",)


def _badge_to_dict(badge: Badge) -> dict:
    return {
        key: getattr(badge, key)
        for key in (
            "id",
            "badge_type",
            "name",
            "description",
            "icon_url",
            "credits_cost",
            "bonus_percentage",
            "valid_days",
            "is_enabled",
            "created_at",
            "updated_at",
        )
    }


def _user_badge_to_dict(user_badge: UserBadge, include_badge: bool = True) -> dict:
    result = {
        key: getattr(user_badge, key)
        for key in (
            "id",
            "tg_id",
            "badge_id",
            "credits_cost",
            "redeemed_at",
            "expires_at",
            "is_active",
        )
    }
    result["bonus_active"] = user_badge.expires_at > int(time.time())
    result["badge"] = (
        _badge_to_dict(user_badge.badge) if include_badge and user_badge.badge else None
    )
    return result


def get_badge_center_config() -> tuple[bool, str | None]:
    config = BADGE_CENTER_CONFIG.get()
    return config.enabled, config.message


def set_badge_center_config(enabled: bool, message: str | None = None) -> bool:
    try:
        changes: dict[str, bool | str] = {"enabled": bool(enabled)}
        if message is not None:
            changes["message"] = message
        BADGE_CENTER_CONFIG.update(**changes)
        return True
    except Exception as exc:
        logger.error(f"设置勋章中心配置失败: {exc}")
        return False


def create_badge(
    badge_type: str,
    name: str,
    description: str,
    icon_url: str,
    credits_cost: float,
    bonus_percentage: float,
    valid_days: int = 365,
    is_enabled: int = 1,
) -> dict | None:
    try:
        with get_session() as session:
            now = int(time.time())
            badge = Badge(
                badge_type=badge_type,
                name=name,
                description=description,
                icon_url=icon_url,
                credits_cost=credits_cost,
                bonus_percentage=bonus_percentage,
                valid_days=valid_days,
                is_enabled=is_enabled,
                created_at=now,
                updated_at=now,
            )
            session.add(badge)
            session.flush()
            return _badge_to_dict(badge)
    except Exception as exc:
        logger.error(f"创建勋章失败: {exc}")
        return None


def get_badge_by_id(badge_id: int) -> dict | None:
    try:
        with get_session() as session:
            row = session.get(Badge, badge_id)
            return _badge_to_dict(row) if row else None
    except Exception as exc:
        logger.error(f"获取勋章失败: {exc}")
        return None


def get_badge_by_type(badge_type: str) -> dict | None:
    try:
        with get_session() as session:
            row = session.execute(
                select(Badge).where(Badge.badge_type == badge_type)
            ).scalar_one_or_none()
            return _badge_to_dict(row) if row else None
    except Exception as exc:
        logger.error(f"获取勋章失败: {exc}")
        return None


def get_all_badges(only_enabled: bool = False) -> list[dict]:
    try:
        with get_session() as session:
            statement = select(Badge).order_by(Badge.created_at.desc())
            if only_enabled:
                statement = statement.where(Badge.is_enabled == 1)
            return [_badge_to_dict(row) for row in session.execute(statement).scalars()]
    except Exception as exc:
        logger.error(f"获取勋章列表失败: {exc}")
        return []


def update_badge(badge_id: int, **kwargs) -> bool:
    try:
        with get_session() as session:
            badge = session.get(Badge, badge_id)
            if badge is None:
                return False
            for key, value in kwargs.items():
                if hasattr(badge, key) and value is not None:
                    setattr(badge, key, value)
            badge.updated_at = int(time.time())
            return True
    except Exception as exc:
        logger.error(f"更新勋章失败: {exc}")
        return False


def delete_badge(badge_id: int) -> bool:
    try:
        with get_session() as session:
            result = session.execute(
                delete(Badge).where(Badge.id == badge_id).returning(Badge.id)
            )
            return result.scalar_one_or_none() is not None
    except Exception as exc:
        logger.error(f"删除勋章失败: {exc}")
        return False


def _serialize_sqlite_write(session: Session) -> None:
    """SQLite has no FOR UPDATE. Acquire its writer lock before any reads.

    An explicit outer transaction also prevents sqlite3's legacy savepoint mode
    from committing an insertion before the enclosing credit debit commits.
    """
    if session.get_bind().dialect.name == "sqlite":
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")


def _ownership(session: Session, tg_id: int, badge_id: int) -> UserBadge | None:
    return session.execute(
        select(UserBadge)
        .where(UserBadge.tg_id == tg_id, UserBadge.badge_id == badge_id)
        .with_for_update()
    ).scalar_one_or_none()


def _new_ownership(
    session: Session, tg_id: int, badge: Badge, cost: float, valid_days: int
) -> UserBadge:
    now = int(time.time())
    row = UserBadge(
        tg_id=tg_id,
        badge_id=badge.id,
        credits_cost=cost,
        redeemed_at=now,
        expires_at=now + valid_days * 86400,
        is_active=1,
    )
    # Existing BIGINT schema is not an SQLite rowid. The outer writer lock
    # serializes allocation; PostgreSQL continues to use its sequence.
    if session.get_bind().dialect.name == "sqlite":
        row.id = int(session.scalar(select(func.max(UserBadge.id))) or 0) + 1
    row.badge = badge
    session.add(row)
    session.flush()
    return row


def redeem_badge_tx(session: Session, tg_id: int, badge_id: int) -> dict:
    """Debit and ownership insertion share the caller's transaction; no catches."""
    badge = session.get(Badge, badge_id)
    if badge is None:
        raise exceptions.BadgeNotFound()
    if badge.is_enabled != 1:
        raise exceptions.BadgeUnavailable()
    # The user's stable foundation row serializes awards and purchases even
    # when there is no ownership row yet. Do not import a foreign ORM model.
    stats = identity_repository.get_statistics_tx(session, tg_id, for_update=True)
    if _ownership(session, tg_id, badge_id) is not None:
        raise exceptions.BadgeAlreadyOwned()
    if stats is None:
        raise exceptions.BadgeUserNotFound()
    # The identity row is already locked above; eligibility cannot race with
    # another debit. Zero-price badges must remain redeemable even with debt.
    if badge.credits_cost > 0 and stats.credits < badge.credits_cost:
        raise exceptions.BadgeInsufficientCredits(badge.credits_cost)
    credits_repository.deduct_tx(
        session, CreditAccount.tg(tg_id), float(badge.credits_cost)
    )
    row = _new_ownership(session, tg_id, badge, badge.credits_cost, badge.valid_days)
    return _user_badge_to_dict(row)


def redeem_badge_or_raise(tg_id: int, badge_id: int) -> dict:
    with get_session() as session:
        _serialize_sqlite_write(session)
        return redeem_badge_tx(session, int(tg_id), int(badge_id))


def redeem_badge(tg_id: int, badge_id: int) -> tuple[bool, str, dict | None]:
    """Retain the legacy manual tuple API; services use the typed variant."""
    try:
        return True, "兑换成功", redeem_badge_or_raise(tg_id, badge_id)
    except exceptions.BadgeError as exc:
        return False, str(exc), None
    except Exception as exc:
        logger.error(f"兑换勋章失败: {exc}")
        return False, "兑换失败，请稍后重试", None


def get_user_badges(tg_id: int, only_active: bool = True) -> list[dict]:
    try:
        with get_session() as session:
            statement = (
                select(UserBadge)
                .options(joinedload(UserBadge.badge))
                .where(UserBadge.tg_id == tg_id)
                .order_by(UserBadge.redeemed_at.desc())
            )
            if only_active:
                statement = statement.where(UserBadge.is_active == 1)
            return [
                _user_badge_to_dict(row)
                for row in session.execute(statement).scalars().unique()
            ]
    except Exception as exc:
        logger.error(f"获取用户勋章失败: {exc}")
        return []


def get_user_active_badges_with_bonus(tg_id: int) -> list[dict]:
    try:
        with get_session() as session:
            statement = (
                select(UserBadge)
                .options(joinedload(UserBadge.badge))
                .where(
                    UserBadge.tg_id == tg_id,
                    UserBadge.is_active == 1,
                    UserBadge.expires_at > int(time.time()),
                )
                .order_by(UserBadge.redeemed_at.desc())
            )
            return [
                {
                    "badge": _badge_to_dict(row.badge),
                    "bonus_percentage": row.badge.bonus_percentage,
                    "expires_at": row.expires_at,
                }
                for row in session.execute(statement).scalars().unique()
                if row.badge
            ]
    except Exception as exc:
        logger.error(f"获取用户有效勋章失败: {exc}")
        return []


def active_bonus_percentage(tg_id: int) -> float:
    return sum(
        (
            float(row["bonus_percentage"])
            for row in get_user_active_badges_with_bonus(tg_id)
        ),
        0.0,
    )


def award_badge(tg_id: int, badge_type: str) -> bool:
    """Exactly one winner per (user, badge), returning only after commit.

    Only ownership conflicts are ignored. Other database failures propagate so
    callers cannot misinterpret an outage as an already-owned badge.
    """
    with get_session() as session:
        _serialize_sqlite_write(session)
        if (
            identity_repository.get_statistics_tx(session, tg_id, for_update=True)
            is None
        ):
            raise exceptions.BadgeUserNotFound()
        badge = session.execute(
            select(Badge).where(Badge.badge_type == badge_type)
        ).scalar_one_or_none()
        if badge is None:
            raise exceptions.BadgeNotFound()
        now = int(time.time())
        values = {
            "tg_id": int(tg_id),
            "badge_id": badge.id,
            "credits_cost": 0,
            "redeemed_at": now,
            "expires_at": now + badge.valid_days * 86400,
            "is_active": 1,
        }
        dialect = session.get_bind().dialect.name
        if dialect == "sqlite":
            values["id"] = int(session.scalar(select(func.max(UserBadge.id))) or 0) + 1
            insert = sqlite_insert(UserBadge)
        elif dialect == "postgresql":
            insert = pg_insert(UserBadge)
        else:
            raise RuntimeError(f"Unsupported badge storage dialect: {dialect}")
        with session.begin_nested():
            result = session.execute(
                insert.values(**values)
                .on_conflict_do_nothing(index_elements=["tg_id", "badge_id"])
                .returning(UserBadge.id)
            )
            awarded = result.scalar_one_or_none() is not None
    return awarded


def award_or_renew_badge(
    tg_id: int, badge_id: int, valid_days: int, cap_days: int | None = None
) -> dict:
    """Preserve the champion badge's renewal and failure-result contract."""
    now = int(time.time())
    span = int(valid_days) * 86400
    try:
        with get_session() as session:
            _serialize_sqlite_write(session)
            identity_repository.get_statistics_tx(session, tg_id, for_update=True)
            existing = _ownership(session, int(tg_id), int(badge_id))
            if existing is None:
                badge = session.get(Badge, badge_id)
                if badge is None:
                    raise exceptions.BadgeNotFound()
                _new_ownership(session, tg_id, badge, 0, valid_days)
                return {
                    "awarded": True,
                    "renewed": False,
                    "expires_at": now + span,
                    "previous_expires_at": None,
                }
            previous = int(existing.expires_at)
            expires = max(previous, now) + span
            if cap_days:
                expires = min(expires, now + int(cap_days) * 86400)
            existing.expires_at = expires
            existing.is_active = 1
            return {
                "awarded": False,
                "renewed": True,
                "expires_at": expires,
                "previous_expires_at": previous,
            }
    except Exception as exc:
        logger.error(f"授予/续期勋章失败 (tg_id={tg_id}, badge={badge_id}): {exc}")
        return {
            "awarded": False,
            "renewed": False,
            "expires_at": None,
            "previous_expires_at": None,
        }


def active_badge_ids_tx(session: Session, tg_id: int) -> set[int]:
    return {
        int(badge_id)
        for badge_id in session.execute(
            select(UserBadge.badge_id).where(
                UserBadge.tg_id == int(tg_id), UserBadge.is_active == 1
            )
        ).scalars()
    }


def badges_exist_tx(session: Session, badge_ids: Iterable[int]) -> set[int]:
    wanted = {int(badge_id) for badge_id in badge_ids}
    if not wanted:
        return set()
    return {
        int(badge_id)
        for badge_id in session.execute(
            select(Badge.id).where(Badge.id.in_(wanted))
        ).scalars()
    }


def check_tg_id_reassign_tx(
    session: Session, old_tg_id: int, new_tg_id: int
) -> list[TgIdReassignIssue]:
    """Check for conflicting badge ownership between old and new identities."""
    if old_tg_id == new_tg_id:
        return []

    old_badges = set(
        session.execute(
            select(UserBadge.badge_id).where(UserBadge.tg_id == int(old_tg_id))
        )
        .scalars()
        .all()
    )
    if not old_badges:
        return []

    new_badges = set(
        session.execute(
            select(UserBadge.badge_id).where(UserBadge.tg_id == int(new_tg_id))
        )
        .scalars()
        .all()
    )
    common_badges = sorted(old_badges & new_badges)
    if common_badges:
        return [
            TgIdReassignIssue(
                kind="conflict",
                domain="badges",
                description="both IDs hold the same badge(s)",
                record_ids=tuple(str(b) for b in common_badges),
            )
        ]
    return []


def reassign_tg_id_tx(
    session: Session, old_tg_id: int, new_tg_id: int
) -> dict[str, int]:
    """Reassign user badges from old identity to new identity."""
    result = session.execute(
        update(UserBadge)
        .where(UserBadge.tg_id == int(old_tg_id))
        .values(tg_id=int(new_tg_id))
    )
    return {"user_badges.tg_id": result.rowcount}
