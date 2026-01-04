from app.config import settings
from app.databases.session import get_session
from app.models.models import PlexUser
from app.modules.plex import Plex
from sqlalchemy import select

plex = Plex()

with get_session() as session:
    stmt = select(PlexUser.plex_id, PlexUser.plex_email, PlexUser.all_lib)
    plex_users = session.execute(stmt).all()

not_all_libs = list(set(plex.get_libraries()) - set(settings.NSFW_LIBS))
for plex_id, plex_email, all_lib in plex_users:
    if plex_email != settings.PLEX_ADMIN_EMAIL and not all_lib:
        try:
            plex.update_user_shared_libs(plex_id, not_all_libs)
        except Exception as e:
            print(f"Failed to remove libraries for {plex_email}: {e}")
