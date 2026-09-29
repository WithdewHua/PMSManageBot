import threading
from uuid import uuid4

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.credits import repository as credits_repository
from app.domains.credits.types import CreditAccount
from app.domains.identity import repository as identity_repository
from app.domains.invitation.exceptions import (
    InvitationCodeNotFound,
    InvitationCodeUsed,
)
from app.domains.invitation.models import Invitation


class InvitationRepository:
    def add_invitation_code(
        self, code: str, owner: int, is_used: int = 0, used_by: int | None = None
    ) -> bool:
        """添加邀请码"""
        try:
            with get_session() as session:
                invitation = Invitation(
                    code=code, owner=owner, is_used=is_used, used_by=used_by
                )
                session.add(invitation)
                return True
        except Exception as e:
            logger.error(f"Error adding invitation code: {e}")
            return False

    def update_invitation_status(
        self,
        code: str,
        used_by: str,
        service: str | None = None,
        plex_id: int | None = None,
        emby_id: str | None = None,
    ) -> bool:
        """更新邀请码状态"""
        try:
            with get_session() as session:
                session.execute(
                    update(Invitation)
                    .where(Invitation.code == code, Invitation.is_used == 0)
                    .values(
                        is_used=1,
                        used_by=used_by,
                        service=service,
                        plex_id=plex_id,
                        emby_id=emby_id,
                    )
                )
                return True
        except Exception as e:
            logger.error(f"Error updating invitation status: {e}")
            return False

    def update_invitation_plex_id(self, plex_email: str, plex_id: int) -> bool:
        """通过 plex_email（used_by）更新对应邀请码的 plex_id 字段"""
        try:
            with get_session() as session:
                session.execute(
                    update(Invitation)
                    .where(
                        Invitation.used_by == plex_email,
                        Invitation.service == "plex",
                        Invitation.plex_id.is_(None),
                    )
                    .values(plex_id=plex_id)
                )
                return True
        except Exception as e:
            logger.error(f"Error updating invitation plex_id: {e}")
            return False

    def get_inviter_tg_id_by_plex_id(self, plex_id: int) -> int | None:
        """通过被邀请人的 plex_id 查找邀请人的 tg_id"""
        with get_session() as session:
            stmt = select(Invitation.owner).where(
                Invitation.plex_id == plex_id,
                Invitation.service == "plex",
                Invitation.is_used == 1,
            )
            return session.execute(stmt).scalar_one_or_none()

    def get_inviter_tg_id_by_emby_id(self, emby_id: str) -> int | None:
        """通过被邀请人的 emby_id 查找邀请人的 tg_id"""
        with get_session() as session:
            stmt = select(Invitation.owner).where(
                Invitation.emby_id == emby_id,
                Invitation.service == "emby",
                Invitation.is_used == 1,
            )
            return session.execute(stmt).scalar_one_or_none()

    def verify_invitation_code_is_used(self, code: str) -> tuple | None:
        """验证邀请码是否已使用"""
        with get_session() as session:
            stmt = select(Invitation.is_used, Invitation.owner).where(
                Invitation.code == code
            )
            result = session.execute(stmt).fetchone()
            return (result[0], result[1]) if result else None

    def get_invitation_code_by_owner(
        self, tg_id: int, is_available: bool = True
    ) -> list:
        """获取用户的邀请码"""
        with get_session() as session:
            if is_available:
                stmt = select(Invitation.code).where(
                    Invitation.owner == tg_id, Invitation.is_used == 0
                )
            else:
                stmt = select(Invitation.code).where(Invitation.owner == tg_id)
            results = session.execute(stmt).fetchall()
            return [r[0] for r in results]

    def get_invitee_count_by_owner(self, tg_id: int) -> int:
        """获取用户邀请的人数"""
        try:
            with get_session() as session:
                stmt = select(func.count(func.distinct(Invitation.used_by))).where(
                    Invitation.owner == tg_id,
                    Invitation.is_used == 1,
                    Invitation.used_by.isnot(None),
                )
                count = session.execute(stmt).scalar()
                return count if count else 0
        except Exception as e:
            logger.error(f"获取邀请人数失败: {e}")
            return 0


def count_invitees_tx(session, tg_id: int, since: int, until: int) -> int:
    """被邀请注册的人数（邀请码没有事件时间，只按“全部时间”统计）。"""
    return int(
        session.execute(
            select(func.count(func.distinct(Invitation.used_by))).where(
                Invitation.owner == int(tg_id), Invitation.is_used == 1
            )
        ).scalar_one()
    )


def verify_invitation_code_tx(session, code: str) -> tuple[int, int] | None:
    row = session.execute(
        select(Invitation.is_used, Invitation.owner).where(Invitation.code == code)
    ).one_or_none()
    return (int(row[0]), int(row[1])) if row else None


def verify_invitation_code(code: str) -> tuple[int, int] | None:
    with get_session() as session:
        return verify_invitation_code_tx(session, code)


def update_invitation_status_tx(
    session,
    *,
    code: str,
    used_by: str,
    service: str | None = None,
    plex_id: int | None = None,
    emby_id: str | None = None,
) -> bool:
    result = session.execute(
        update(Invitation)
        .where(Invitation.code == code, Invitation.is_used == 0)
        .values(
            is_used=1,
            used_by=used_by,
            service=service,
            plex_id=plex_id,
            emby_id=emby_id,
        )
    )
    return result.rowcount == 1


def update_invitation_status(
    *,
    code: str,
    used_by: str,
    service: str | None = None,
    plex_id: int | None = None,
    emby_id: str | None = None,
) -> bool:
    with get_session() as session:
        return update_invitation_status_tx(
            session,
            code=code,
            used_by=used_by,
            service=service,
            plex_id=plex_id,
            emby_id=emby_id,
        )


def update_invitation_plex_id_tx(
    session,
    *,
    plex_email: str | None = None,
    plex_id: int,
    code: str | None = None,
) -> int:
    """Backfill only still-empty invitation records for this account."""
    statement = update(Invitation).where(
        Invitation.service == "plex",
        Invitation.plex_id.is_(None),
    )
    if code is not None:
        statement = statement.where(Invitation.code == code)
    elif plex_email is not None:
        statement = statement.where(Invitation.used_by == str(plex_email))
    else:
        raise ValueError("plex_email or code is required")
    result = session.execute(statement.values(plex_id=int(plex_id)))
    return int(result.rowcount or 0)


def get_inviter_tg_id_by_plex_id(plex_id: int) -> int | None:
    with get_session() as session:
        return get_inviter_tg_id_by_plex_id_tx(session, plex_id)


def get_inviter_tg_id_by_plex_id_tx(session, plex_id: int) -> int | None:
    return session.execute(
        select(Invitation.owner).where(
            Invitation.plex_id == int(plex_id),
            Invitation.service == "plex",
            Invitation.is_used == 1,
        )
    ).scalar_one_or_none()


def get_inviter_tg_id_by_emby_id(emby_id: str) -> int | None:
    with get_session() as session:
        return get_inviter_tg_id_by_emby_id_tx(session, emby_id)


def get_inviter_tg_id_by_emby_id_tx(session, emby_id: str) -> int | None:
    return session.execute(
        select(Invitation.owner).where(
            Invitation.emby_id == str(emby_id),
            Invitation.service == "emby",
            Invitation.is_used == 1,
        )
    ).scalar_one_or_none()


def redeem_invitation_code_tx(
    session, *, code: str, tg_id: int, credits: float
) -> float:
    """Atomically consume a code and add its reward to the TG account."""
    from app.domains.credits import repository as credits_repository
    from app.domains.credits.types import CreditAccount

    result = session.execute(
        update(Invitation)
        .where(Invitation.code == code, Invitation.is_used == 0)
        .values(is_used=1, used_by=f"credits_by_{int(tg_id)}")
    )
    if result.rowcount != 1:
        state = session.execute(
            select(Invitation.is_used).where(Invitation.code == code)
        ).scalar_one_or_none()
        if state is None:
            raise InvitationCodeNotFound()
        raise InvitationCodeUsed()
    try:
        mutation = credits_repository.add_tx(
            session, CreditAccount.tg(int(tg_id)), float(credits)
        )
    except ValueError as error:
        from app.domains.invitation.exceptions import InvitationRejected

        raise InvitationRejected(
            "credit_update_failed", "更新积分失败，请稍后再试"
        ) from error
    return float(mutation.after)


#: 特权码写 data/.env 是文档化的 pre-commit 例外（docs/architecture.md 已知例外）。
_INVITATION_PRIVILEGED_CODES_LOCK = threading.Lock()


def list_used_invitation_records() -> list[dict[str, object]]:
    with get_session() as session:
        rows = session.execute(
            select(
                Invitation.code,
                Invitation.used_by,
                Invitation.service,
                Invitation.plex_id,
                Invitation.emby_id,
            ).where(Invitation.is_used == 1)
        ).all()
        return [
            {
                "code": row.code,
                "used_by": row.used_by,
                "service": row.service,
                "plex_id": row.plex_id,
                "emby_id": row.emby_id,
            }
            for row in rows
        ]


def update_invitation_plex_id(plex_email: str, plex_id: int) -> bool:
    with get_session() as session:
        return (
            update_invitation_plex_id_tx(
                session, plex_email=plex_email, plex_id=plex_id
            )
            > 0
        )


def update_invitation_emby_id(emby_username: str, emby_id: str) -> bool:
    with get_session() as session:
        result = session.execute(
            update(Invitation)
            .where(
                Invitation.used_by == emby_username,
                Invitation.service == "emby",
                Invitation.emby_id.is_(None),
            )
            .values(emby_id=str(emby_id))
        )
        return bool(result.rowcount)


def update_invitation_id_for_code(
    *, code: str, service: str, account_id: int | str
) -> bool:
    field = {"plex": Invitation.plex_id, "emby": Invitation.emby_id}.get(service)
    if field is None:
        raise ValueError(f"unsupported invitation service: {service}")
    with get_session() as session:
        result = session.execute(
            update(Invitation)
            .where(
                Invitation.code == code,
                Invitation.service == service,
                field.is_(None),
            )
            .values({field.key: account_id})
        )
        return bool(result.rowcount)


def update_invitation_service(code: str, service: str) -> bool:
    with get_session() as session:
        result = session.execute(
            update(Invitation)
            .where(Invitation.code == code, Invitation.is_used == 1)
            .values(service=service)
        )
        return bool(result.rowcount)


def create_invitation_codes(
    *,
    owner_tg_id: int,
    codes: list[str],
    charge: float,
    privileged: bool,
    require_account: bool,
) -> list[str]:
    with get_session() as session:
        stats = identity_repository.get_statistics_tx(session, int(owner_tg_id))
        if stats is None and require_account:
            from app.domains.invitation.exceptions import InvitationAccountNotFound

            raise InvitationAccountNotFound()
        if stats is None:
            stats = identity_repository.ensure_statistics_tx(session, int(owner_tg_id))
        if charge:
            try:
                credits_repository.deduct_tx(
                    session, CreditAccount.tg(int(owner_tg_id)), float(charge)
                )
            except ValueError as error:
                from app.domains.invitation.exceptions import InvitationRejected

                available = float(stats.credits or 0)
                raise InvitationRejected(
                    "insufficient_credits",
                    f"积分不足，您当前积分 {available}，需要 {charge:g} 积分才能生成邀请码",
                ) from error
        inserted = insert_invitation_codes_tx(session, int(owner_tg_id), codes)
        if privileged:
            persist_privileged_codes_tx(inserted)
        return inserted


def insert_invitation_codes_tx(
    session, owner_tg_id: int, codes: list[str]
) -> list[str]:
    if not codes:
        raise ValueError("邀请码数量必须为正")
    for code in codes:
        session.add(Invitation(code=str(code), owner=int(owner_tg_id), is_used=0))
    session.flush()
    return list(codes)


def redeem_for_credits(*, tg_id: int, code: str, credits: float) -> float:
    with get_session() as session:
        if identity_repository.get_statistics_tx(session, int(tg_id)) is None:
            from app.domains.invitation.exceptions import InvitationAccountNotFound

            raise InvitationAccountNotFound()
        return redeem_invitation_code_tx(
            session, code=code, tg_id=int(tg_id), credits=float(credits)
        )


def issue_codes_tx(
    session, owner_tg_id: int, count: int, *, privileged: bool = False
) -> list[str]:
    """在调用方事务内为用户生成邀请码，返回新码列表。

    与调用方的其余写入同生共死：事务回滚不会留下可用邀请码；
    `uuid4().hex` 与既有码同为 32 位十六进制。
    """
    total = int(count)
    if total <= 0:
        raise ValueError("邀请码数量必须为正")
    codes = [uuid4().hex for _ in range(total)]
    return insert_invitation_codes_tx(session, owner_tg_id, codes)


def persist_privileged_codes_tx(codes) -> None:
    """把特权码写入配置（pre-commit 例外，调用方须在最后一次 flush 之后调用）。

    配置文件不是事务性的：先更新内存列表再落盘，写失败就恢复内存列表并把异常
    抛给调用方，让整个领取事务回滚（这是唯一被允许的 pre-commit 副作用）。
    """
    if not codes:
        return
    with _INVITATION_PRIVILEGED_CODES_LOCK:
        original_codes = list(settings.PRIVILEGED_CODES)
        new_codes = original_codes.copy()
        for code in codes:
            if code not in new_codes:
                new_codes.append(code)
        settings.PRIVILEGED_CODES[:] = new_codes
        try:
            settings.save_config_to_env_file(
                {"PRIVILEGED_CODES": ",".join(new_codes)},
                raise_on_error=True,
            )
        except Exception:
            settings.PRIVILEGED_CODES[:] = original_codes
            raise
