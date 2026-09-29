"""Account workflows and external-service orchestration."""

from __future__ import annotations

from app.core.log import logger
from app.domains.accounts import repository as accounts_repository
from app.domains.accounts.config import ACCOUNTS_CONFIG
from app.domains.accounts.exceptions import AccountAlreadyBound
from app.domains.identity import service as identity_service
from app.domains.traffic import service as traffic_service
from app.integrations import media_tokens
from app.integrations.emby import Emby
from app.integrations.plex import Plex
from app.integrations.tautulli import Tautulli, get_user_total_duration


def get_registration_config():
    return ACCOUNTS_CONFIG.get()


def set_registration_enabled(server: str, enabled: bool):
    field = {"plex": "plex_register", "emby": "emby_register"}.get(server.lower())
    if field is None:
        raise ValueError(f"unsupported registration server: {server}")
    return ACCOUNTS_CONFIG.update(**{field: bool(enabled)})


def is_registration_enabled(server: str) -> bool:
    field = {"plex": "plex_register", "emby": "emby_register"}.get(server.lower())
    if field is None:
        raise ValueError(f"unsupported registration server: {server}")
    config = get_registration_config()
    return bool(getattr(config, field))


def update_plex_info(
    plex_name: bool = True,
    plex_id: bool = True,
    plex_avatar: bool = True,
    target_email: str | None = None,
) -> bool:
    """Synchronize Plex identities with per-user failure isolation."""
    plex = Plex()
    resolved_target = False

    if plex_name:
        cache_clear_users: list[str] = []
        try:
            users_by_id = plex.users_by_id
        except Exception:
            logger.exception("读取 Plex 用户列表失败")
            users_by_id = {}
        for plex_user_id, user in users_by_id.items():
            try:
                email = user[1].email
                username = user[0]
                old_username = identity_service.update_plex_identity(
                    plex_id=int(plex_user_id),
                    plex_username=username,
                    plex_email=email,
                )
                if old_username is None:
                    logger.info(
                        "Plex 用户 %s(%s) 未在本地注册，跳过同步",
                        username,
                        plex_user_id,
                    )
                    continue
                if old_username:
                    cache_clear_users.append(old_username)
                    if not traffic_service.rename_user(old_username, username):
                        logger.error(
                            "更新流量表中的用户名失败: %s -> %s",
                            old_username,
                            username,
                        )
            except Exception:
                logger.exception("同步 Plex 用户 %s 的名称失败", plex_user_id)

        if cache_clear_users:
            try:
                deleted_tokens = media_tokens.clear_plex_tokens_for_usernames(
                    cache_clear_users
                )
                for username in deleted_tokens:
                    logger.info("已清除 Plex 用户 %s 的 Token 缓存", username)
            except Exception:
                logger.exception("清理 Plex 用户 Token 缓存失败")

    if plex_id:
        try:
            empty_plex_users = identity_service.list_unresolved_plex_emails(
                target_email
            )
        except Exception:
            logger.exception("读取待回填的 Plex 用户失败")
            empty_plex_users = []

        for email in empty_plex_users:
            try:
                resolved_id = plex.get_user_id_by_email(email)
                username = (
                    plex.get_username_by_user_id(resolved_id) if resolved_id else None
                )
                if not resolved_id or not username:
                    logger.warning(
                        "无法找到 Plex 用户 %s 的 ID 或用户名，跳过更新。", email
                    )
                    continue
                resolved = accounts_repository.resolve_plex_user_by_email(
                    email=email,
                    plex_id=int(resolved_id),
                    plex_username=username,
                )
                resolved_target = resolved_target or resolved
            except Exception:
                logger.exception("回填 Plex 用户 %s 的 ID 失败", email)

    if plex_avatar:
        try:
            plex.update_all_user_avatars()
        except Exception:
            logger.exception("刷新 Plex 用户头像失败")

    return resolved_target


def sync_plex_user_by_email(email: str) -> bool:
    """Resolve one invited Plex user; used by the named memory task."""
    return update_plex_info(
        plex_name=False,
        plex_id=True,
        plex_avatar=False,
        target_email=email,
    )


def update_emby_users_last_viewed_at() -> None:
    logger.info("开始更新 Emby 用户最后观看时间")
    try:
        activities = Emby().get_all_users_last_activity() or {}
        updated_count = identity_service.update_emby_last_viewed(activities)
        logger.info("Emby 用户最后观看时间更新完成，共更新 %s 个用户", updated_count)
    except Exception:
        logger.exception("更新 Emby 用户最后观看时间失败")


def update_plex_users_last_viewed_at() -> None:
    logger.info("开始更新 Plex 用户的最后观看时间")
    try:
        activities = Plex().get_all_users_last_viewed_at() or {}
        updated_count = identity_service.update_plex_last_viewed(activities)
        logger.info("成功更新 %s 个 Plex 用户的最后观看时间", updated_count)
    except Exception:
        logger.exception("更新 Plex 用户最后观看时间失败")


def refresh_emby_user_info(
    emby_username: str | None = None, *, emby_factory=Emby
) -> None:
    """Refresh Emby users independently so one API failure cannot abort a batch."""
    emby = emby_factory()
    try:
        if emby_username:
            usernames = [emby_username]
        else:
            usernames = identity_service.list_emby_usernames()
    except Exception:
        logger.exception("获取待刷新的 Emby 用户失败")
        return

    for username in usernames:
        try:
            emby.get_user_info_from_username(username)
        except Exception:
            logger.exception("刷新 Emby 用户 %s 信息失败", username)


def bind_plex(tg_id: int, email: str) -> tuple[bool, str]:
    """Validate and atomically bind a Plex account."""
    if identity_service.find_plex_by_tg(tg_id):
        return False, "您已绑定 Plex 账户，请勿重复操作"

    plex = Plex()
    plex_id = plex.get_user_id_by_email(email)
    if plex_id == 0:
        return False, "该邮箱无 Plex 权限，请检查输入的邮箱"

    existing = identity_service.find_plex_by_id(int(plex_id))
    if existing is None:
        existing = identity_service.find_unresolved_plex_by_email(email)
    if existing and existing.tg_id:
        return False, f"该 Plex 账户已经绑定 Telegram 账户 {existing.tg_id}"

    plex_username = existing.plex_username if existing else None
    if existing and not plex_username:
        plex_username = plex.get_username_by_user_id(plex_id)
    all_lib = existing.all_lib if existing else 0
    if existing:
        plex_credits = float(existing.credits or 0)
    else:
        plex_username = plex.get_username_by_user_id(plex_id)
        current_libs = plex.get_user_shared_libs_by_id(plex_id)
        all_lib = 1 if not set(plex.get_libraries()).difference(current_libs) else 0
        try:
            duration = get_user_total_duration(
                Tautulli().get_home_stats(
                    1365, "duration", len(plex.users_by_id), stat_id="top_users"
                )
            )
            plex_credits = float(duration.get(plex_id, 0))
        except Exception as error:
            logger.error("获取用户观看时长失败: %s", error)
            return False, "获取用户观看时长失败，请稍后再试"

    try:
        accounts_repository.bind_plex_account(
            tg_id=int(tg_id),
            plex_id=int(plex_id),
            plex_email=email,
            plex_username=plex_username,
            all_lib=int(all_lib or 0),
            watched_time=plex_credits,
            existing_unbound=bool(existing),
            existing_credits=plex_credits,
        )
    except AccountAlreadyBound:
        return False, "该账户已被绑定"
    return True, f"绑定 Plex 账户 {email} 成功！"


def bind_emby(tg_id: int, username: str) -> tuple[bool, str]:
    """Validate and atomically bind an Emby account."""
    if identity_service.find_emby_by_tg(tg_id):
        return False, "您已绑定 Emby 账户，请勿重复操作"
    emby = Emby()
    emby_id = emby.get_uid_from_username(username)
    if not emby_id:
        return False, f"用户 {username} 不存在"
    existing = identity_service.find_emby_by_username(username)
    if existing and existing.tg_id:
        return False, f"该 Emby 账户已经绑定 Telegram 账户 {existing.tg_id}"
    try:
        accounts_repository.bind_emby_account(
            tg_id=int(tg_id),
            emby_id=str(emby_id),
            emby_username=username,
            existing_unbound=bool(existing),
        )
    except AccountAlreadyBound:
        return False, "该账户已被绑定"
    return True, f"绑定 Emby 账户 {username} 成功！"


def bind_plex_account(**kwargs) -> None:
    accounts_repository.bind_plex_account(**kwargs)


def bind_emby_account(**kwargs) -> None:
    accounts_repository.bind_emby_account(**kwargs)


def create_invited_plex_user(*, tg_id: int | None, email: str) -> bool:
    return accounts_repository.create_invited_plex_user(tg_id=tg_id, email=email)


def create_invited_emby_user(
    *, emby_username: str, emby_id: str, tg_id: int | None
) -> bool:
    return accounts_repository.create_invited_emby_user(
        emby_username=emby_username, emby_id=emby_id, tg_id=tg_id
    )


def create_overseerr(
    tg_id: int,
    email: str,
    password: str,
    *,
    overseerr_factory=None,
) -> tuple[bool, int | str]:
    """Create an Overseerr user after identity checks and persist it."""
    emby_info = identity_service.find_emby_by_tg(tg_id)
    plex_info = identity_service.find_plex_by_tg(tg_id)
    overseerr_info = identity_service.find_overseerr_by_tg(tg_id)
    overseerr_by_email = identity_service.find_overseerr_by_email(email)
    if not emby_info:
        return False, "未绑定 Emby 帐号，不允许创建 Overseer 账户"
    if plex_info:
        return False, "您已绑定 Plex 账户，请使用 Plex 帐号登录 Overseer"
    if overseerr_info:
        return False, "您已创建过 Overseerr 账户，请勿重复创建"
    if overseerr_by_email:
        return False, "已存在该邮箱创建的 Overseerr 账户，请勿重复创建"

    if overseerr_factory is None:
        from app.integrations.overseerr import Overseerr

        overseerr_factory = Overseerr
    success, result = overseerr_factory().add_user(email, password)
    if not success:
        logger.error("Failed to create overseerr user: %s", result)
        return False, "创建账户失败，请联系管理员"
    if not identity_service.add_overseerr_user(
        user_id=int(result), user_email=email, tg_id=tg_id
    ):
        return False, "数据库操作失败，请联系管理员"
    return True, result


__all__ = [
    "bind_emby",
    "bind_emby_account",
    "bind_plex",
    "bind_plex_account",
    "create_invited_emby_user",
    "create_invited_plex_user",
    "create_overseerr",
    "get_registration_config",
    "is_registration_enabled",
    "refresh_emby_user_info",
    "set_registration_enabled",
    "sync_plex_user_by_email",
    "update_emby_users_last_viewed_at",
    "update_plex_info",
    "update_plex_users_last_viewed_at",
]
