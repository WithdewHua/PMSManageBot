from sqlalchemy import select

from app.core.config import settings
from app.core.db import get_session
from app.domains.identity.models import EmbyUser, PlexUser
from app.integrations.emby import Emby
from app.integrations.plex import Plex

settings.load_config_from_file()


_plex = Plex()
_emby = Emby()


def update_plex():
    with get_session() as session:
        stmt = select(PlexUser.plex_email, PlexUser.plex_username).where(
            PlexUser.all_lib == 1
        )
        plex_users = session.execute(stmt).all()

    for email, username in plex_users:
        if email == settings.PLEX_ADMIN_EMAIL:
            continue
        print(f"Adding Hentai library for Plex user: {username}")
        _plex.add_shared_libs_for_user(email, "Hentai")


def update_emby():
    # 使用 session.execute 替代 db.cur.execute
    with get_session() as session:
        stmt = select(EmbyUser.emby_id, EmbyUser.emby_username).where(
            EmbyUser.emby_is_unlock == 1
        )
        emby_users = session.execute(stmt).all()

    for emby_id, emby_username in emby_users:
        if emby_username == settings.EMBY_ADMIN_USER:
            continue
        print(f"Adding Hentai library for Emby user: {emby_username}")
        _emby.add_user_library(emby_id, "Hentai")


if __name__ == "__main__":
    update_emby()
    update_plex()
