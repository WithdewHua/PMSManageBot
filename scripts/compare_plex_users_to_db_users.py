from app.databases.db import DB
from app.modules.plex import Plex

db = DB()
plex = Plex()

plex_user_ids = list(plex.users_by_id.keys())
db_users = db.cur.execute("select plex_id from user").fetchall()
db_user_ids = [user[0] for user in db_users]

missing_in_plex = set(db_user_ids) - set(plex_user_ids)
missing_in_db = set(plex_user_ids) - set(db_user_ids)

print("Users in DB but not in Plex:")
for user_id in missing_in_plex:
    print(f" - {user_id}")
print("\nUsers in Plex but not in DB:")
for user_id in missing_in_db:
    print(f" - {user_id} ({plex.users_by_id[user_id][0]})")
