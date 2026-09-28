from sqlalchemy import select

from app.core.config import settings
from app.core.db import get_session
from app.domains.identity.models import PlexUser
from app.domains.media_access import service as media_access_service
from app.integrations.plex import Plex

plex = Plex()

with get_session() as session:
    stmt = select(PlexUser.plex_id, PlexUser.plex_email, PlexUser.all_lib)
    plex_users = session.execute(stmt).all()

not_all_libs = list(
    set(plex.get_libraries()) - set(media_access_service.get_nsfw_libs())
)
for plex_id, plex_email, all_lib in plex_users:
    if plex_email != settings.PLEX_ADMIN_EMAIL and not all_lib:
        try:
            plex.update_user_shared_libs(plex_id, not_all_libs)
        except Exception as e:
            print(f"Failed to remove libraries for {plex_email}: {e}")
