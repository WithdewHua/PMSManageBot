from sqlalchemy import select

from app.core.db import get_session
from app.domains.identity.models import PlexUser
from app.integrations.plex import Plex

plex = Plex()

plex_user_ids = list(plex.users_by_id.keys())

with get_session() as session:
    stmt = select(PlexUser.plex_id).where(PlexUser.plex_id.isnot(None))
    db_user_ids = [int(x) for x in session.execute(stmt).scalars().all()]

missing_in_plex = set(db_user_ids) - set(plex_user_ids)
missing_in_db = set(plex_user_ids) - set(db_user_ids)

print("Users in DB but not in Plex:")
for user_id in sorted(missing_in_plex):
    print(f" - {user_id}")
print("\nUsers in Plex but not in DB:")
for user_id in sorted(missing_in_db):
    print(f" - {user_id} ({plex.users_by_id[user_id][0]})")
