from sqlalchemy import select
from sqlalchemy import update as sql_update

from app.core.db import get_session
from app.core.log import logger
from app.databases.db import db
from app.domains.accounts.config import ACCOUNTS_CONFIG
from app.domains.identity.models import EmbyUser, PlexUser
from app.integrations import media_tokens
from app.integrations.emby import Emby
from app.integrations.plex import Plex
from app.integrations.tautulli import Tautulli, get_user_total_duration


def get_registration_config() -> object:
    return ACCOUNTS_CONFIG.get()


def set_registration_enabled(server: str, enabled: bool) -> object:
    field = {"plex": "plex_register", "emby": "emby_register"}.get(server.lower())
    if field is None:
        raise ValueError(f"unsupported registration server: {server}")
    return ACCOUNTS_CONFIG.update(**{field: bool(enabled)})


def is_registration_enabled(server: str) -> bool:
    config = get_registration_config()
    return bool(getattr(config, f"{server.lower()}_register"))


def update_plex_info(
    plex_name=True, plex_id=True, plex_avatar=True, target_email: str | None = None
):
    """Synchronize Plex names, ids, invitation records and avatars independently."""
    _plex = Plex()
    try:
        if plex_name:
            cache_clear_users: list[str] = []
            for uid, user in _plex.users_by_id.items():
                try:
                    email = user[1].email
                    username = user[0]
                    with get_session() as session:
                        existing_user = session.execute(
                            select(PlexUser).where(PlexUser.plex_id == uid)
                        ).scalar_one_or_none()
                        if existing_user is None:
                            logger.info(
                                "Plex 用户 %s(%s) 未在本地注册，跳过同步",
                                username,
                                uid,
                            )
                            continue
                        if (
                            existing_user.plex_username == username
                            and existing_user.plex_email == email
                        ):
                            continue
                        plex_username = existing_user.plex_username
                        cache_clear_users.append(plex_username)
                        session.execute(
                            sql_update(PlexUser)
                            .where(PlexUser.plex_id == uid)
                            .values(plex_username=username, plex_email=email)
                        )
                    if not db.update_traffic_username(
                        old_username=plex_username,
                        new_username=username,
                    ):
                        logger.error(
                            "更新流量表中的用户名失败: %s -> %s",
                            plex_username,
                            username,
                        )
                except Exception:
                    logger.exception("同步 Plex 用户 %s 的名称失败", uid)
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
            with get_session() as session:
                if target_email:
                    stmt = select(PlexUser.plex_email).where(
                        PlexUser.plex_id.is_(None), PlexUser.plex_email == target_email
                    )
                else:
                    stmt = select(PlexUser.plex_email).where(PlexUser.plex_id.is_(None))
                empty_plex_users = session.execute(stmt).scalars().all()

            for email in empty_plex_users:
                try:
                    plex_id = _plex.get_user_id_by_email(email)
                    plex_username = (
                        _plex.get_username_by_user_id(plex_id) if plex_id else None
                    )
                    if not plex_id or not plex_username:
                        logger.warning(
                            "无法找到 Plex 用户 %s 的 ID 或用户名，跳过更新。", email
                        )
                        continue
                    with get_session() as session:
                        session.execute(
                            sql_update(PlexUser)
                            .where(PlexUser.plex_email == email)
                            .values(plex_id=plex_id, plex_username=plex_username)
                        )
                    db.update_invitation_plex_id(plex_email=email, plex_id=plex_id)
                    if target_email and email.lower() == target_email.lower():
                        import threading

                        def delayed_job_removal():
                            try:
                                import time

                                from app.core.scheduler import Scheduler

                                time.sleep(2)
                                Scheduler().remove_job(
                                    f"update_plex_info_for_{target_email}"
                                )
                            except Exception:
                                logger.exception("延迟删除 Plex 回填任务失败")

                        threading.Thread(
                            target=delayed_job_removal, daemon=True
                        ).start()
                except Exception:
                    logger.exception("回填 Plex 用户 %s 的 ID 失败", email)

        if plex_avatar:
            try:
                _plex.update_all_user_avatars()
            except Exception:
                logger.exception("刷新 Plex 用户头像失败")
    except Exception:
        logger.exception("更新 Plex 用户信息失败")


def add_all_plex_user():
    """将所有 plex 用户均加入到数据库中"""

    duration = get_user_total_duration(
        Tautulli().get_home_stats(
            36500, "duration", len(Plex().users_by_id), "top_users"
        )
    )
    _plex = Plex()
    users = [user for user in _plex.my_plex_account.users()]
    users.append(_plex.my_plex_account)
    all_libs = Plex().get_libraries()
    try:
        with get_session() as session:
            stmt = select(PlexUser.plex_id)
            existing_users = [user[0] for user in session.execute(stmt).fetchall()]
        for user in users:
            # 已存在用户及未接受邀请用户跳过
            if user.id in existing_users or (not user.email):
                continue
            watched_time = duration.get(user.id, 0)
            try:
                cur_libs = _plex.get_user_shared_libs_by_id(user.id)
            # 跳过分享给我的用户
            except Exception as e:
                print(e)
                continue
            all_lib_flag = 1 if not set(all_libs).difference(set(cur_libs)) else 0
            db.add_plex_user(
                plex_id=user.id,
                tg_id=None,
                plex_email=user.email,
                plex_username=user.username,
                credits=watched_time,
                all_lib=all_lib_flag,
                watched_time=watched_time,
            )

    except Exception as e:
        print(e)


def update_emby_users_last_viewed_at():
    """更新所有Emby用户的最后观看时间"""
    logger.info("开始更新 Emby 用户最后观看时间")
    try:
        emby = Emby()
        # 获取所有用户的最后活动时间
        user_activities = emby.get_all_users_last_activity()

        if not user_activities:
            logger.warning("未获取到任何用户的最后活动时间")
            return

        # 批量更新数据库
        updated_count = 0
        with get_session() as session:
            for user_id, last_activity in user_activities.items():
                if last_activity is not None:
                    stmt = (
                        sql_update(EmbyUser)
                        .where(EmbyUser.emby_id == user_id)
                        .values(last_viewed_at=last_activity)
                    )
                    result = session.execute(stmt)
                    if result.rowcount > 0:
                        updated_count += 1

        logger.info(f"Emby 用户最后观看时间更新完成，共更新 {updated_count} 个用户")

    except Exception as e:
        logger.error(f"更新 Emby 用户最后观看时间失败: {e}")


def update_plex_users_last_viewed_at():
    """更新所有 Plex 用户的最后观看时间"""
    logger.info("开始更新 Plex 用户的最后观看时间")
    try:
        _plex = Plex()

        # 获取所有用户的最后观看时间
        last_viewed_dict = _plex.get_all_users_last_viewed_at()

        updated_count = 0
        with get_session() as session:
            for plex_id, last_viewed_at in last_viewed_dict.items():
                if last_viewed_at > 0:
                    stmt = (
                        sql_update(PlexUser)
                        .where(PlexUser.plex_id == plex_id)
                        .values(last_viewed_at=last_viewed_at)
                    )
                    result = session.execute(stmt)
                    if result.rowcount > 0:
                        updated_count += 1

        logger.info(f"成功更新 {updated_count} 个 Plex 用户的最后观看时间")

    except Exception as e:
        logger.error(f"更新 Plex 用户最后观看时间失败: {e}")


def bind_plex_account(**kwargs) -> None:
    """Commit Plex binding and balance transfer atomically."""
    from app.domains.accounts import repository as accounts_repository

    accounts_repository.bind_plex_account(**kwargs)


def bind_emby_account(**kwargs) -> None:
    """Commit Emby binding and balance transfer atomically."""
    from app.domains.accounts import repository as accounts_repository

    accounts_repository.bind_emby_account(**kwargs)
