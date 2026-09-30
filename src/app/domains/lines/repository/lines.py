import time

from sqlalchemy import select, update

from app.core import kv as core_kv
from app.core.db import get_session
from app.core.log import logger
from app.domains.identity.models import EmbyUser, PlexUser


def set_emby_line_tx(
    session, line: str | None, tg_id: int | None = None, emby_id: str | None = None
) -> None:
    """Set an Emby line in the caller-owned transaction."""
    if tg_id is not None:
        session.execute(
            update(EmbyUser).where(EmbyUser.tg_id == tg_id).values(emby_line=line)
        )
    elif emby_id is not None:
        session.execute(
            update(EmbyUser).where(EmbyUser.emby_id == emby_id).values(emby_line=line)
        )


def set_emby_line(
    line: str | None, tg_id: int | None = None, emby_id: str | None = None
) -> bool:
    """设置 Emby 线路"""
    try:
        with get_session() as session:
            set_emby_line_tx(session, line, tg_id=tg_id, emby_id=emby_id)
            return True
    except Exception as e:
        logger.error(f"Error setting emby line: {e}")
        return False


def get_emby_line_tx(session, tg_id: int) -> str | None:
    return session.execute(
        select(EmbyUser.emby_line).where(EmbyUser.tg_id == tg_id)
    ).scalar_one_or_none()


def get_emby_line(tg_id: int) -> str | None:
    """获取 Emby 线路"""
    with get_session() as session:
        return get_emby_line_tx(session, tg_id)


def get_emby_user_with_binded_line_tx(session) -> list:
    stmt = select(
        EmbyUser.emby_username,
        EmbyUser.tg_id,
        EmbyUser.emby_id,
        EmbyUser.emby_line,
        EmbyUser.is_premium,
    ).where(EmbyUser.emby_line.isnot(None))
    results = session.execute(stmt).fetchall()
    return [(r[0], r[1], r[2], r[3], r[4]) for r in results]


def get_emby_user_with_binded_line() -> list:
    """获取绑定线路的 Emby 用户"""
    with get_session() as session:
        return get_emby_user_with_binded_line_tx(session)


def set_plex_line_tx(
    session, line: str | None, tg_id: int | None = None, plex_id: int | None = None
) -> None:
    """Set a Plex line in the caller-owned transaction."""
    if tg_id is not None:
        session.execute(
            update(PlexUser).where(PlexUser.tg_id == tg_id).values(plex_line=line)
        )
    elif plex_id is not None:
        session.execute(
            update(PlexUser).where(PlexUser.plex_id == plex_id).values(plex_line=line)
        )


def set_plex_line(
    line: str | None, tg_id: int | None = None, plex_id: int | None = None
) -> bool:
    """设置 Plex 线路"""
    try:
        with get_session() as session:
            set_plex_line_tx(session, line, tg_id=tg_id, plex_id=plex_id)
            return True
    except Exception as e:
        logger.error(f"Error setting plex line: {e}")
        return False


def get_plex_line_tx(session, tg_id: int) -> str | None:
    return session.execute(
        select(PlexUser.plex_line).where(PlexUser.tg_id == tg_id)
    ).scalar_one_or_none()


def get_plex_line(tg_id: int) -> str | None:
    """获取 Plex 线路"""
    with get_session() as session:
        return get_plex_line_tx(session, tg_id)


def get_plex_user_with_binded_line_tx(session) -> list:
    stmt = select(
        PlexUser.plex_username,
        PlexUser.tg_id,
        PlexUser.plex_id,
        PlexUser.plex_line,
        PlexUser.is_premium,
    ).where(PlexUser.plex_line.isnot(None))
    results = session.execute(stmt).fetchall()
    return [(r[0], r[1], r[2], r[3], r[4]) for r in results]


def get_plex_user_with_binded_line() -> list:
    """获取绑定线路的 Plex 用户"""
    with get_session() as session:
        return get_plex_user_with_binded_line_tx(session)


def get_free_premium_lines() -> list[str]:
    """获取所有免费高级线路列表"""
    configs = core_kv.get_all("free_premium_line")
    return [key for key, value in configs.items() if value == "1"]


def set_free_premium_lines(lines: list[str]) -> bool:
    """
    设置免费高级线路列表

    Args:
        lines: 线路名称列表

    Returns:
        是否成功
    """
    try:
        # 获取现有的免费线路
        existing_lines = set(get_free_premium_lines())
        new_lines = set(lines)

        # 删除不再免费的线路
        for line in existing_lines - new_lines:
            core_kv.delete("free_premium_line", line)

        # 添加新的免费线路
        for line in new_lines:
            core_kv.upsert("free_premium_line", line, "1")

        logger.info(f"设置免费高级线路成功，共 {len(lines)} 条线路")
        return True
    except Exception as e:
        logger.error(f"设置免费高级线路失败: {e!s}")
        return False


def is_free_premium_line(line_name: str) -> bool:
    """检查线路是否为免费高级线路"""
    value = core_kv.get("free_premium_line", line_name)
    return value == "1"


def get_line_tags(line_name: str) -> list[str]:
    """
    获取线路的标签列表

    Args:
        line_name: 线路名称

    Returns:
        标签列表
    """
    tags_str = core_kv.get("line_tag", line_name)
    if tags_str:
        tags = tags_str.split(",")
        return [tag.strip() for tag in tags if tag.strip()]
    return []


def set_line_tags(line_name: str, tags: list[str]) -> bool:
    """
    设置线路标签

    Args:
        line_name: 线路名称
        tags: 标签列表

    Returns:
        是否成功
    """
    if not tags:
        # 如果标签为空，删除该配置
        return core_kv.delete("line_tag", line_name)

    # 去重并转换为逗号分隔的字符串
    tags_str = ",".join(set(tags))
    core_kv.upsert("line_tag", line_name, tags_str)
    return True


def delete_line_tags(line_name: str) -> bool:
    """删除线路的所有标签"""
    return core_kv.delete("line_tag", line_name)


def get_all_line_tags() -> dict:
    """
    获取所有线路的标签

    Returns:
        字典 {line_name: [tags]}
    """
    configs = core_kv.get_all("line_tag")
    result = {}
    for line_name, tags_str in configs.items():
        tags = tags_str.split(",")
        result[line_name] = [tag.strip() for tag in tags if tag.strip()]
    return result


def unlock_line_schedule(tg_id: int, service: str) -> bool:
    """
    解锁用户的线路调度功能

    Args:
        tg_id: 用户的 Telegram ID
        service: 服务类型 (plex/emby)

    Returns:
        是否成功
    """

    try:
        with get_session() as session:
            unlock_time = int(time.time())

            if service == "plex":
                stmt = (
                    update(PlexUser)
                    .where(PlexUser.tg_id == tg_id)
                    .values(
                        line_schedule_unlocked=1,
                        line_schedule_unlock_time=unlock_time,
                    )
                )
            elif service == "emby":
                stmt = (
                    update(EmbyUser)
                    .where(EmbyUser.tg_id == tg_id)
                    .values(
                        line_schedule_unlocked=1,
                        line_schedule_unlock_time=unlock_time,
                    )
                )
            else:
                logger.error(f"未知的服务类型: {service}")
                return False

            session.execute(stmt)
            logger.info(f"用户 {tg_id!s} 解锁 {service} 线路调度功能")
            return True

    except Exception as e:
        logger.error(f"解锁 {service} 线路调度功能失败: {e}")
        return False
