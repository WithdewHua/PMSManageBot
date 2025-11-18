from app.config import settings
from app.databases.db import DB
from app.modules.plex import Plex

db = DB()
plex = Plex()

plex_users = db.cur.execute("select plex_email, all_lib from user").fetchall()

all_libs = plex.get_libraries()
not_all_libs = list(set(all_libs) - set(settings.NSFW_LIBS))

for plex_email, all_lib in plex_users:
    if plex_email != settings.PLEX_ADMIN_EMAIL:
        try:
            if all_lib:
                plex.invite_friend(plex_email, all_libs)
            else:
                plex.invite_friend(plex_email, not_all_libs)
        except Exception as e:
            print(f"Failed to invite {plex_email}: {e}")

print("Finished inviting all users in the database to their respective libraries.")
