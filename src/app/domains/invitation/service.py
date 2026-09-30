"""Invitation workflows and typed invitation lookups."""

from __future__ import annotations

import datetime
from collections.abc import Awaitable, Callable
from time import time
from typing import Any
from uuid import NAMESPACE_URL, uuid3

from app.core.config import settings
from app.core.log import logger
from app.core.scheduler import schedule_task
from app.domains.accounts import service as accounts_service
from app.domains.identity import service as identity_service
from app.domains.invitation import repository as invitation_repository
from app.domains.invitation.config import INVITATION_CONFIG
from app.domains.invitation.exceptions import (
    InvitationCodeNotFound,
    InvitationCodeUsed,
    InvitationRejected,
)
from app.domains.media_access import service as media_access_service
from app.integrations.emby import Emby
from app.integrations.plex import Plex
from app.integrations.telegram.messaging import send_message_by_url
from app.integrations.telegram.profiles import get_user_name_from_tg_id

Notifier = Callable[..., Awaitable[Any]]


def get_invitation_credits() -> int:
    return int(INVITATION_CONFIG.get().invitation_credits)


def set_invitation_credits(credits: int) -> int:
    return int(INVITATION_CONFIG.update(invitation_credits=credits).invitation_credits)


def get_register_status() -> dict[str, bool]:
    return {
        "plex": accounts_service.is_registration_enabled("plex"),
        "emby": accounts_service.is_registration_enabled("emby"),
    }


def refresh_emby_user_info(emby_username: str) -> None:
    accounts_service.refresh_emby_user_info(emby_username=emby_username)


def get_points_info(tg_id: int) -> tuple[int, float, bool, str | None]:
    required = get_invitation_credits()
    stats = identity_service.get_statistics(int(tg_id))
    if stats is None:
        return required, 0.0, False, "用户未绑定 Plex/Emby 账户"
    current = float(stats.credits)
    can_generate = current >= required
    return (
        required,
        current,
        can_generate,
        None if can_generate else "积分不足，无法生成邀请码",
    )


def _create_code(owner_tg_id: int) -> str:
    return uuid3(NAMESPACE_URL, str(int(owner_tg_id) + time())).hex


def generate_codes(
    owner_tg_id: int,
    count: int = 1,
    *,
    charge: float | None = None,
    privileged: bool = False,
    require_account: bool = False,
) -> list[str]:
    """Charge and insert all requested invitation codes atomically."""
    count = int(count)
    if count <= 0:
        raise InvitationRejected("invalid_count", "邀请码数量必须为正")
    codes = [_create_code(owner_tg_id) for _ in range(count)]
    amount = get_invitation_credits() if charge is None else float(charge)
    return invitation_repository.create_invitation_codes(
        owner_tg_id=int(owner_tg_id),
        codes=codes,
        charge=amount,
        privileged=privileged,
        require_account=require_account,
    )


def generate_one_code(owner_tg_id: int) -> str:
    """Generate one legacy-format code for the self-service HTTP and bot flows."""
    return generate_codes(
        owner_tg_id,
        1,
        charge=get_invitation_credits(),
        require_account=True,
    )[0]


def add_redeem_code(tg_id=None, num=1, is_privileged=False) -> list[str]:
    """Preserve legacy fan-out and failure-swallowing semantics for callers."""
    try:
        if tg_id is None:
            owners = identity_service.list_statistics_tg_ids()
        elif isinstance(tg_id, list):
            owners = tg_id
        else:
            owners = [tg_id]
        codes: list[str] = []
        for owner in owners:
            created = generate_codes(
                int(owner), int(num), charge=0, privileged=bool(is_privileged)
            )
            codes.extend(created)
            logger.info(
                "为用户 %s 生成 %s 个邀请码",
                get_user_name_from_tg_id(owner),
                len(created),
            )
        return codes
    except Exception as error:
        logger.error("生成邀请码失败: %s", error)
        return []


async def generate_codes_and_notify(
    *,
    owner_tg_id: int,
    count: int,
    privileged: bool = False,
    notify: Notifier = send_message_by_url,
) -> list[str]:
    codes = generate_codes(
        owner_tg_id,
        count,
        charge=0,
        privileged=privileged,
        require_account=True,
    )
    await notify(
        chat_id=owner_tg_id,
        text=f"已生成 {len(codes)} 个{'特权' if privileged else '普通'}邀请码。",
        parse_mode="HTML",
        token=settings.TG_API_TOKEN,
    )
    return codes


def redeem_for_credits(tg_id: int, code: str) -> tuple[float, float]:
    """Consume an unused code and grant credits in one caller-independent transaction."""
    credits_earned = get_invitation_credits() * 0.8
    result = invitation_repository.redeem_for_credits(
        tg_id=int(tg_id), code=code, credits=credits_earned
    )
    return credits_earned, result


def get_inviter_tg_id_by_plex_id(plex_id: int) -> int | None:
    return invitation_repository.get_inviter_tg_id_by_plex_id(plex_id)


def get_inviter_tg_id_by_emby_id(emby_id: str) -> int | None:
    return invitation_repository.get_inviter_tg_id_by_emby_id(emby_id)


def update_invitation_plex_id(email: str, plex_id: int) -> bool:
    return invitation_repository.update_invitation_plex_id(email, plex_id)


def _require_unused_code(code: str) -> int:
    result = invitation_repository.verify_invitation_code(code)
    if result is None:
        raise InvitationCodeNotFound()
    is_used, owner = result
    if is_used:
        raise InvitationCodeUsed()
    return int(owner)


def check_privileged_code(code: str) -> bool:
    """检查单个邀请码是否为有效未使用的特权码。"""
    return bool(invitation_repository.check_privileged_codes([code]))


def batch_check_privileged_codes(codes: list[str]) -> dict[str, bool]:
    """批量检查邀请码是否为有效未使用的特权码。"""
    privileged_set = invitation_repository.check_privileged_codes(codes)
    return {code: code in privileged_set for code in codes}


def import_legacy_privileged_codes(
    source: Any = None,
) -> dict[str, Any]:
    """升级后首次启动时从 .env 导入实际生效的特权码列表。"""
    import json
    import time

    from app.core import kv as core_kv
    from app.core.legacy_env import LegacyEnvSource

    if source is None:
        source = LegacyEnvSource({"PRIVILEGED_CODES": []})

    if "PRIVILEGED_CODES" in source.present_keys():
        logger.warning("业务配置键 PRIVILEGED_CODES 已迁出 .env，不再生效")

    marker = core_kv.get("invitation", "privileged_codes_imported")
    if marker is not None:
        return {"already_imported": True}

    raw_codes = source.read("PRIVILEGED_CODES")
    codes: list[str] = []
    seen: set[str] = set()
    for code in raw_codes:
        c = str(code).strip()
        if c and c not in seen:
            seen.add(c)
            codes.append(c)

    summary = invitation_repository.import_privileged_codes(codes)
    marker_payload = json.dumps(
        {
            "imported_at": int(time.time()),
            "total_codes": len(codes),
            "marked": summary["marked"],
            "used_skipped": summary["used_skipped"],
            "not_found_skipped": summary["not_found_skipped"],
        },
        ensure_ascii=False,
    )
    core_kv.upsert("invitation", "privileged_codes_imported", marker_payload)
    return summary


async def register_plex(
    *,
    code: str,
    email: str | None,
    bind_to_telegram: bool,
    telegram_user_id: int,
    privileged: bool | None = None,
    notify: Notifier = send_message_by_url,
    plex_factory: Callable[..., Plex] = Plex,
) -> tuple[bool, int]:
    """Redeem a Plex invite in preclaim -> external call -> confirm order."""
    if not email or "@" not in email:
        raise InvitationRejected("invalid_email", "请输入有效的邮箱地址")
    if identity_service.count_bound_plex_users() >= 100:
        raise InvitationRejected("plex_capacity", "Plex 用户数已达上限")

    reg_enabled = accounts_service.is_registration_enabled("plex")
    code_owner, is_privileged = invitation_repository.preclaim_invitation_code(
        code=code,
        used_by=email,
        service="plex",
        registration_enabled=reg_enabled,
    )
    logger.info(
        "邀请码 %s 已由邮箱 %s 预占 (owner=%s, privileged=%s)",
        code,
        email,
        code_owner,
        is_privileged,
    )

    try:
        plex = plex_factory()
        if email.lower() in plex.users_by_email:
            raise InvitationRejected(
                "already_invited", "该邮箱账户已被邀请，请使用其他邮箱"
            )
        if not plex.invite_friend(
            email, excluded_libraries=media_access_service.get_nsfw_libs()
        ):
            raise InvitationRejected(
                "invite_failed", "邀请失败，请稍后再试或联系管理员"
            )
    except Exception:
        invitation_repository.release_invitation_code(code=code, used_by=email)
        raise

    # The external invitation has succeeded. ID lookup is optional enrichment,
    # not grounds to make the consumed code reusable; the resolver can retry it.
    try:
        plex_id = plex.get_user_id_by_email(email) or None
    except Exception:
        logger.exception("Plex 邀请成功后查询用户 ID 失败，等待后台回填: %s", email)
        plex_id = None
    invitation_repository.confirm_invitation_redemption(code=code, plex_id=plex_id)

    existing_telegram_account = (
        identity_service.find_plex_by_tg(telegram_user_id) if bind_to_telegram else None
    )
    if existing_telegram_account:
        logger.warning("Telegram 用户 %s 已绑定其他 Plex 账户", telegram_user_id)
    record_tg_id = (
        None if existing_telegram_account or not bind_to_telegram else telegram_user_id
    )
    created = accounts_service.create_invited_plex_user(tg_id=record_tg_id, email=email)
    telegram_bound = bool(created and record_tg_id is not None)
    if created:
        register_plex_id_resolution_task(email)

    for admin in settings.TG_ADMIN_CHAT_ID:
        bind_status = (
            f"（已绑定 TG: {get_user_name_from_tg_id(telegram_user_id)}）"
            if telegram_bound
            else ""
        )
        try:
            await notify(
                chat_id=admin,
                text=f"信息：{get_user_name_from_tg_id(code_owner)} 成功邀请 Plex 用户 {email}{bind_status}",
                token=settings.TG_API_TOKEN,
            )
        except Exception:
            logger.exception("发送 Plex 邀请管理员通知失败: %s", admin)

    return telegram_bound, code_owner


async def register_emby(
    *,
    code: str,
    username: str | None,
    password: str | None,
    bind_to_telegram: bool,
    telegram_user_id: int,
    privileged: bool | None = None,
    notify: Notifier = send_message_by_url,
    emby_factory: Callable[..., Emby] = Emby,
) -> tuple[bool, int, str]:
    """Redeem an Emby invite in preclaim -> external call -> confirm order."""
    password = str(password or "").strip()
    if not username or len(username) < 2:
        raise InvitationRejected("invalid_username", "请输入有效的用户名")
    if len(password) < 4:
        raise InvitationRejected("invalid_password", "请输入有效的密码")

    reg_enabled = accounts_service.is_registration_enabled("emby")
    code_owner, is_privileged = invitation_repository.preclaim_invitation_code(
        code=code,
        used_by=username,
        service="emby",
        registration_enabled=reg_enabled,
    )
    logger.info(
        "邀请码 %s 已由用户名 %s 预占 (owner=%s, privileged=%s)",
        code,
        username,
        code_owner,
        is_privileged,
    )

    try:
        emby = emby_factory()
        if identity_service.find_emby_by_username(
            username
        ) or emby.get_uid_from_username(username):
            raise InvitationRejected(
                "username_exists", "该用户名已存在，请使用其他用户名"
            )
        created, result = emby.add_user(username=username, password=password)
        if not created:
            raise InvitationRejected("create_failed", f"创建用户失败: {result}")
        emby_id = str(result)
    except Exception:
        invitation_repository.release_invitation_code(code=code, used_by=username)
        raise

    invitation_repository.confirm_invitation_redemption(
        code=code, emby_id=emby_id or None
    )

    telegram_bound = False
    try:
        existing = (
            identity_service.find_emby_by_tg(telegram_user_id)
            if bind_to_telegram
            else None
        )
        created_local = accounts_service.create_invited_emby_user(
            emby_username=username,
            emby_id=emby_id,
            tg_id=telegram_user_id if bind_to_telegram and existing is None else None,
        )
        telegram_bound = bool(created_local and bind_to_telegram and existing is None)
        if bind_to_telegram and existing:
            logger.warning("Telegram 用户 %s 已绑定其他 Emby 账户", telegram_user_id)
    except Exception:
        logger.exception("绑定 Telegram 账户过程出错: %s", telegram_user_id)
        accounts_service.create_invited_emby_user(
            emby_username=username, emby_id=emby_id, tg_id=None
        )

    for admin in settings.TG_ADMIN_CHAT_ID:
        bind_status = (
            f"（已绑定 TG: {get_user_name_from_tg_id(telegram_user_id)}）"
            if telegram_bound
            else ""
        )
        try:
            await notify(
                chat_id=admin,
                text=f"信息：{get_user_name_from_tg_id(code_owner)} 成功邀请 Emby 用户 {username}{bind_status}",
                token=settings.TG_API_TOKEN,
            )
        except Exception:
            logger.exception("发送 Emby 邀请管理员通知失败: %s", admin)
    return telegram_bound, code_owner, password


def register_plex_id_resolution_task(email: str) -> None:
    """Schedule the periodic invite-email synchronization as a named memory task."""
    from datetime import timedelta

    from app.core.scheduler import TASK_REGISTRY, register_task

    if "invitation.resolve_plex_id" not in TASK_REGISTRY:
        register_task("invitation.resolve_plex_id", resolve_plex_id_job)
    now = datetime.datetime.now(settings.TZ)
    schedule_task(
        "invitation.resolve_plex_id",
        run_date=now + timedelta(minutes=3),
        job_id=f"update_plex_info_for_{email}",
        kwargs={"email": email},
        misfire_grace_time=60,
        jobstore="default",
        trigger="interval",
        minutes=1,
        end_date=now + timedelta(hours=1),
        replace_existing=True,
        max_instances=1,
    )


def resolve_plex_id_job(email: str) -> bool:
    from app.core.scheduler import Scheduler

    resolved = False
    try:
        resolved = accounts_service.sync_plex_user_by_email(email)
        return resolved
    finally:
        if resolved:
            job_id = f"update_plex_info_for_{email}"
            try:
                scheduler = Scheduler()
                job = scheduler.scheduler.get_job(job_id, jobstore="default")
                if job is not None:
                    scheduler.remove_job(job_id, jobstore="default")
            except Exception:
                logger.exception("移除 Plex 回填任务失败: %s", email)


__all__ = [
    "add_redeem_code",
    "generate_codes",
    "generate_codes_and_notify",
    "generate_one_code",
    "get_invitation_code_by_owner",
    "get_invitation_credits",
    "get_invitation_rank",
    "get_invitee_count_by_owner",
    "get_inviter_tg_id_by_emby_id",
    "get_inviter_tg_id_by_plex_id",
    "get_points_info",
    "get_register_status",
    "invitee_counts",
    "redeem_for_credits",
    "refresh_emby_user_info",
    "register_emby",
    "register_plex",
    "register_plex_id_resolution_task",
    "resolve_plex_id_job",
    "set_invitation_credits",
    "update_invitation_plex_id",
]


def invitee_counts() -> list[tuple[int, int]]:
    """获取按被邀请人去重计数的邀请排行榜数据 [(owner_tg_id, invite_count), ...]"""
    return invitation_repository.get_invitation_rank()


get_invitation_rank = invitee_counts


def get_invitation_code_by_owner(tg_id: int, is_available: bool = True) -> list[str]:
    """获取用户的邀请码列表"""
    return invitation_repository.get_invitation_code_by_owner(
        int(tg_id), is_available=is_available
    )


def get_invitee_count_by_owner(tg_id: int) -> int:
    """获取用户邀请的人数"""
    return invitation_repository.get_invitee_count_by_owner(int(tg_id))
