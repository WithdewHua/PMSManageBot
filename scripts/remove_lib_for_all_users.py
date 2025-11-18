from app.config import settings
from app.databases.db import DB
from app.modules.plex import Plex

db = DB()
plex = Plex()
plex_users = db.cur.execute("select plex_id, plex_email, all_lib from user").fetchall()

not_all_libs = list(set(plex.get_libraries()) - set(settings.NSFW_LIBS))
for plex_id, plex_email, all_lib in plex_users:
    if plex_email != settings.PLEX_ADMIN_EMAIL and not all_lib:
        try:
            plex.update_user_shared_libs(plex_id, not_all_libs)
        except Exception as e:
            print(f"Failed to remove libraries for {plex_email}: {e}")
