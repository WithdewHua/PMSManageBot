from app.config import settings
from app.databases.db import DB
from app.modules.emby import Emby
from app.modules.plex import Plex

settings.load_config_from_file()

db = DB()
_plex = Plex()
_emby = Emby()


def update_plex():
    plex_users = db.cur.execute(
        "select plex_email, plex_username from user where all_lib=1"
    ).fetchall()

    for plex_user in plex_users:
        email = plex_user[0]
        username = plex_user[1]
        if email == settings.PLEX_ADMIN_EMAIL:
            continue
        print(f"Adding Hentai library for Plex user: {username}")
        _plex.add_shared_libs_for_user(email, "Hentai")


def update_emby():
    emby_users = db.cur.execute(
        "select emby_id, emby_username from emby_user where emby_is_unlock=1"
    ).fetchall()

    for emby_user in emby_users:
        emby_id = emby_user[0]
        emby_username = emby_user[1]
        if emby_username == settings.EMBY_ADMIN_USER:
            continue
        print(f"Adding Hentai library for Emby user: {emby_username}")
        _emby.add_user_library(emby_id, "Hentai")


if __name__ == "__main__":
    update_emby()
    update_plex()
