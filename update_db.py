from uuid import uuid3, NAMESPACE_URL
from time import time

from tautulli import Tautulli
from db import DB
from utils import get_user_total_duration
from plex import Plex


def update_credits():
    """更新积分及观看时长"""
    # 获取一天内的观看时长
    duration = get_user_total_duration(Tautulli().get_home_stats(1, "duration", len(Plex().users_by_id), "top_users"))
    _db = DB()
    try:
        # update credits and watched_time
        res = _db.cur.execute("select plex_id from user")
        users = res.fetchall()
        for user in users:
            plex_id = user[0]
            credits_inc = duration.get(plex_id, 0)
            res = _db.cur.execute("SELECT credits,watched_time,tg_id FROM user WHERE plex_id=?", (plex_id,)).fetchone()
            if not res:
                continue
            watched_time_init = res[1]
            tg_id = res[2]
            if not tg_id:
                credits_init = res[0]
                credits = credits_init + credits_inc
                watched_time = watched_time_init + credits_inc
                _db.cur.execute("UPDATE user SET credits=?,watched_time=? WHERE plex_id=?", (credits, watched_time, plex_id))
            else:
                credits_init = _db.cur.execute("SELECT credits FROM statistics WHERE tg_id=?", (tg_id,)).fetchone()[0]
                credits = credits_init + credits_inc
                watched_time = watched_time_init + credits_inc
                _db.cur.execute("UPDATE user SET watched_time=? WHERE plex_id=?", (watched_time, plex_id))
                _db.cur.execute("UPDATE statistics SET credits=? WHERE tg_id=?", (credits, tg_id))


    except Exception as e:
        print(e)
    else:
        _db.con.commit()
    finally:
        _db.close()
        

def update_plex_info():
    """更新 plex 用户信息"""
    _db = DB()
    _plex = Plex()
    try:
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


def update_all_lib():
    """更新用户资料库权限状态"""
    _db = DB()
    _plex = Plex()
    try:
        users = _plex.users_by_email
        all_libs = _plex.get_libraries()
        for email, user in users.items():
            if not email:
                continue
            _info = _db.cur.execute("select * from user where plex_email=?", (email,))
            _info = _info.fetchone()
            if not _info:
                continue
            cur_libs = _plex.get_user_shared_libs_by_id(user[0])
            all_lib_flag = 1 if not set(all_libs).difference(set(cur_libs)) else 0
            _db.cur.execute("UPDATE user SET all_lib=? WHERE plex_email=?", (all_lib_flag, email))
    except Exception as e:
        print(e)
    else:
        _db.con.commit()
    finally:
        _db.close()
        



def update_watched_time():
    """更新用户观看时长"""
    duration = get_user_total_duration(Tautulli().get_home_stats(1365, "duration", len(Plex().users_by_id), "top_users"))
    _db = DB()
    try:
        res = _db.cur.execute("select plex_id from user")
        users = res.fetchall()
        for user in users:
            plex_id = user[0]
            watched_time = duration.get(plex_id, 0)
            _db.cur.execute("UPDATE user SET watched_time=? WHERE plex_id=?", (watched_time, plex_id))
    
    except Exception as e:
        print(e)
    else:
        _db.con.commit()
    finally:
        _db.close()


def add_all_plex_user():
    """将所有 plex 用户均加入到数据库中"""

    duration = get_user_total_duration(Tautulli().get_home_stats(1365, "duration", len(Plex().users_by_id), "top_users"))
    _plex = Plex()
    users = [user for user in _plex.my_plex_account.users()]
    users.append(_plex.my_plex_account)
    _db = DB()
    all_libs = Plex().get_libraries()
    try:
        _existing_users = _db.cur.execute("select plex_id from user").fetchall()
        existing_users = [user[0] for user in _existing_users]
        for user in users:
            # 已存在用户及未接受邀请用户跳过
            if user.id in existing_users or (not user.email):
                continue
            watched_time = duration.get(user.id, 0)
            try:
                cur_libs = _plex.get_user_shared_libs_by_id(user.id)
            # 跳过分享给我的用户
            except Exception as e:
                print(e)
                continue
            all_lib_flag = 1 if not set(all_libs).difference(set(cur_libs)) else 0
            _db.add_plex_user(plex_id=user.id, tg_id=None, plex_email=user.email, plex_username=user.username, credits=watched_time, all_lib=all_lib_flag, watched_time=watched_time)

    except Exception as e:
        print(e)
    else:
        _db.con.commit()
    finally:
        _db.close()


def add_redeem_code(tg_id=None):
    db = DB()
    if tg_id is None:
        tg_id = [u[0] for u in db.cur.execute("SELECT tg_id FROM statistics").fetchall()]
    elif not isinstance(tg_id, list):
        tg_id = [tg_id]
    try:
        for uid in tg_id:
            code = uuid3(NAMESPACE_URL, str(uid + time())).hex
            db.add_invitation_code(code, owner=uid)
    except Exception as e:
        print(e)
    else:
        db.con.commit()
    finally:
        db.close()
        

if __name__ == "__main__":
    update_credits()
    update_plex_info()
    # add_all_plex_user()
