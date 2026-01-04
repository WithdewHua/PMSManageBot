from app.config import settings
from app.databases.session import get_session
from app.models.models import PlexUser
from app.modules.plex import Plex
from sqlalchemy import select

plex = Plex()

with get_session() as session:
    stmt = select(PlexUser.plex_email, PlexUser.all_lib)
    plex_users = session.execute(stmt).all()

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
