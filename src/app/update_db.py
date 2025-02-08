from time import time
from uuid import NAMESPACE_URL, uuid3

from app.db import DB
from app.emby import Emby
from app.plex import Plex
from app.tautulli import Tautulli
from app.utils import get_user_total_duration


def update_credits():
    """更新积分及观看时长"""
    # 获取一天内的观看时长
    duration = get_user_total_duration(
        Tautulli().get_home_stats(1, "duration", len(Plex().users_by_id), "top_users")
    )
    _db = DB()
    try:
        # update credits and watched_time
        res = _db.cur.execute("select plex_id from user")
        users = res.fetchall()
        for user in users:
            plex_id = user[0]
            credits_inc = duration.get(plex_id, 0)
            res = _db.cur.execute(
                "SELECT credits,watched_time,tg_id FROM user WHERE plex_id=?",
                (plex_id,),
            ).fetchone()
            if not res:
                continue
            watched_time_init = res[1]
            tg_id = res[2]
            if not tg_id:
                credits_init = res[0]
                credits = credits_init + credits_inc
                watched_time = watched_time_init + credits_inc
                _db.cur.execute(
                    "UPDATE user SET credits=?,watched_time=? WHERE plex_id=?",
                    (credits, watched_time, plex_id),
                )
            else:
                credits_init = _db.cur.execute(
                    "SELECT credits FROM statistics WHERE tg_id=?", (tg_id,)
                ).fetchone()[0]
                credits = credits_init + credits_inc
                watched_time = watched_time_init + credits_inc
                _db.cur.execute(
                    "UPDATE user SET watched_time=? WHERE plex_id=?",
                    (watched_time, plex_id),
                )
                _db.cur.execute(
                    "UPDATE statistics SET credits=? WHERE tg_id=?", (credits, tg_id)
                )

    except Exception as e:
        print(e)
    else:
        _db.con.commit()
    finally:
        _db.close()


def update_emby_credits():
    """更新 emby 积分及观看时长"""
    # 获取所有用户的观看时长
    emby = Emby()
    duration = emby.get_user_total_play_time()
    _db = DB()
    try:
        # 获取数据库中的观看时长信息
        users = _db.cur.execute(
            "select emby_id, tg_id, emby_watched_time, emby_credits from emby_user"
        ).fetchall()
        for user in users:
            playduration = float(int(duration.get(user[0], 0)) / 3600)
            if playduration == 0:
                continue
            # 最大记 8
            credits_inc = min(playduration - user[2], 8)
            if not user[1]:
                _credits = user[3] + credits_inc
                _db.cur.execute(
                    "UPDATE emby_user SET emby_watched_time=?,emby_credits=? WHERE emby_id=?",
                    (playduration, _credits, user[0]),
                )
            else:
                stats_info = _db.get_stats_by_tg_id(user[1])
                # statistics 表中有数据
                if stats_info:
                    credits_init = stats_info[2]
                    _credits = credits_init + credits_inc
                    _db.update_user_credits(_credits, tg_id=user[1])
                else:
                    # 清空 emby_user 表中积分信息
                    _db.update_user_credits(0, emby_id=user[0])
                    # 在 statistic 表中增加用户数据
                    _db.add_user_data(user[1], credits=user[3] + credits_inc)
                # 更新 emby_user 表中观看时间
                _db.cur.execute(
                    "UPDATE emby_user SET emby_watched_time=? WHERE emby_id=?",
                    (playduration, user[0]),
                )

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
            _db.cur.execute(
                "UPDATE user SET plex_username=?,plex_email=? WHERE plex_id=?",
                (username, email, uid),
            )
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
            _db.cur.execute(
                "UPDATE user SET all_lib=? WHERE plex_email=?", (all_lib_flag, email)
            )
    except Exception as e:
        print(e)
    else:
        _db.con.commit()
    finally:
        _db.close()


def update_watched_time():
    """更新用户观看时长"""
    duration = get_user_total_duration(
        Tautulli().get_home_stats(
            36500, "duration", len(Plex().users_by_id), "top_users"
        )
    )
    _db = DB()
    try:
        res = _db.cur.execute("select plex_id from user")
        users = res.fetchall()
        for user in users:
            plex_id = user[0]
            watched_time = duration.get(plex_id, 0)
            _db.cur.execute(
                "UPDATE user SET watched_time=? WHERE plex_id=?",
                (watched_time, plex_id),
            )

    except Exception as e:
        print(e)
    else:
        _db.con.commit()
    finally:
        _db.close()


def add_all_plex_user():
    """将所有 plex 用户均加入到数据库中"""

    duration = get_user_total_duration(
        Tautulli().get_home_stats(
            36500, "duration", len(Plex().users_by_id), "top_users"
        )
    )
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
            _db.add_plex_user(
                plex_id=user.id,
                tg_id=None,
                plex_email=user.email,
                plex_username=user.username,
                credits=watched_time,
                all_lib=all_lib_flag,
                watched_time=watched_time,
            )

    except Exception as e:
        print(e)
    else:
        _db.con.commit()
    finally:
        _db.close()


def add_redeem_code(tg_id=None, num=1):
    db = DB()
    if tg_id is None:
        tg_id = [
            u[0] for u in db.cur.execute("SELECT tg_id FROM statistics").fetchall()
        ]
    elif not isinstance(tg_id, list):
        tg_id = [tg_id]
    try:
        for uid in tg_id:
            for _ in range(num):
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
    update_emby_credits()
