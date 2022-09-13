from tautulli import Tautulli
from db import DB
from utils import get_user_total_duration
from plex import Plex


def update_credits():
    duration = get_user_total_duration(Tautulli().get_home_stats(1, "duration", len(Plex().users_by_id), "top_users"))
    try:
        # update credits
        _db = DB()
        res = _db.cur.execute("select plex_id from user")
        users = res.fetchall()
        for user in users:
            plex_id = user[0]
            credits_inc = duration.get(plex_id, 0)
            res = _db.cur.execute("SELECT credits FROM user WHERE plex_id=?", (plex_id,)).fetchone()
            if not res:
                continue
            credits_init = res[0]
            credits = credits_init + credits_inc
            _db.update_user_credits(credits, plex_id=plex_id)
    
    except Exception as e:
        print(e)
    finally:
        _db.close()
        

def update_plex_info():
    try:
        _db = DB()
        _plex = Plex()
        users = _plex.users_by_id
        for uid, user in users.items():
            email = user[1].email
            username = user[0]
            _db.cur.execute("UPDATE user SET plex_username=?,plex_email=? WHERE plex_id=?", (username, email, uid))
    except Exception as e:
        print(e)
    else:
        _db.con.commit()
    finally:
        _db.close()
        
        
if __name__ == "__main__":
    update_credits()
    update_plex_info()
