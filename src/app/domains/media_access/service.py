from sqlalchemy import select
from sqlalchemy import update as sql_update

from app.core.db import get_session
from app.domains.identity.models import PlexUser
from app.integrations.plex import Plex


def update_all_lib():
    """更新用户资料库权限状态"""
    _plex = Plex()
    try:
        users = _plex.users_by_email
        all_libs = _plex.get_libraries()
        for email, user in users.items():
            if not email:
                continue
            with get_session() as session:
                stmt = select(PlexUser).where(PlexUser.plex_email == email)
                _info = session.execute(stmt).fetchone()
            if not _info:
                continue
            cur_libs = _plex.get_user_shared_libs_by_id(user[0])
            all_lib_flag = 1 if not set(all_libs).difference(set(cur_libs)) else 0
            with get_session() as session:
                stmt = (
                    sql_update(PlexUser)
                    .where(PlexUser.plex_email == email)
                    .values(all_lib=all_lib_flag)
                )
                session.execute(stmt)
    except Exception as e:
        print(e)
