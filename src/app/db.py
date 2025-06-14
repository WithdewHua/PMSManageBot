#!/usr/bin/env python3

import logging
import sqlite3
from typing import Optional

from app.config import settings


class DB:
    """class DB"""

    def __init__(self, db=settings.DATA_PATH / "data.db"):
        self.con = sqlite3.connect(db)
        self.cur = self.con.cursor()
        # self.create_table()

    def create_table(self):
        try:
            self.cur.executescript(
                """
                CREATE TABLE user(
                    plex_id,
                    tg_id,
                    credits,
                    plex_email,
                    plex_username,
                    all_lib,
                    unlock_time,
                    watched_time,
                    plex_line,
                    is_premium,
                );

                CREATE TABLE invitation(
                    code, owner, is_used, userd_by
                );

                CREATE TABLE statistics(
                    tg_id, donation, credits
                );

                CREATE TABLE emby_user(
                    emby_username, emby_id, tg_id, emby_is_unlock, emby_unlock_time, emby_watched_time, emby_credits, emby_line, is_premium
                );

                CREATE TABLE overseerr(
                    user_id, user_email, tg_id
                );

                CREATE TABLE wheel_stats(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_id INTEGER,
                    item_name TEXT,
                    credits_change REAL,
                    timestamp INTEGER,
                    date TEXT
                );
                """
            )
        except sqlite3.OperationalError:
            logging.warning("Table user is created already, skip...")
        else:
            self.con.commit()

    def add_plex_user(
        self,
        plex_id: Optional[int] = None,
        tg_id: Optional[int] = None,
        plex_email: Optional[str] = None,
        plex_username: Optional[str] = None,
        credits: int = 0,
        all_lib=0,
        unlock_time=None,
        watched_time=0,
        plex_line: Optional[str] = None,
        is_premium: Optional[int] = 0,
    ):
        try:
            self.cur.execute(
                "INSERT INTO user VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plex_id,
                    tg_id,
                    credits,
                    plex_email,
                    plex_username,
                    all_lib,
                    unlock_time,
                    watched_time,
                    plex_line,
                    is_premium,
                ),
            )
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def add_emby_user(
        self,
        emby_username: str,
        emby_id: Optional[str] = None,
        tg_id: Optional[int] = None,
        emby_is_unlock: Optional[int] = 0,
        emby_unlock_time: Optional[int] = None,
        emby_watched_time: float = 0,
        emby_credits: float = 0,
        emby_line: Optional[str] = None,
        is_premium: Optional[int] = 0,
    ) -> bool:
        try:
            self.cur.execute(
                "INSERT INTO emby_user VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    emby_username,
                    emby_id,
                    tg_id,
                    emby_is_unlock,
                    emby_unlock_time,
                    emby_watched_time,
                    emby_credits,
                    emby_line,
                    is_premium,
                ),
            )
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def add_overseerr_user(self, user_id: int, user_email: str, tg_id: int):
        try:
            self.cur.execute(
                "INSERT INTO overseerr VALUES (?, ?, ?)",
                (user_id, user_email, tg_id),
            )
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
            return True

    def add_user_data(self, tg_id, credits=0, donation=0):
        try:
            self.cur.execute(
                "INSERT INTO statistics VALUES (?, ?, ?)", (tg_id, donation, credits)
            )
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def update_user_tg_id(self, tg_id, plex_id=None, emby_id=None):
        try:
            if plex_id:
                self.cur.execute(
                    "UPDATE user SET tg_id=? WHERE plex_id=?", (tg_id, plex_id)
                )
            if emby_id:
                self.cur.execute(
                    "UPDATE emby_user SET tg_id=? WHERE emby_id=?", (tg_id, emby_id)
                )
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def add_invitation_code(self, code, owner, is_used=0, used_by=None) -> bool:
        try:
            self.cur.execute(
                "INSERT INTO invitation VALUES (?, ?, ?, ?)",
                (code, owner, is_used, used_by),
            )
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def get_stats_by_tg_id(self, tg_id):
        return self.cur.execute(
            "SELECT * from statistics WHERE tg_id=?", (tg_id,)
        ).fetchone()

    def update_user_credits(
        self, credits: float, plex_id=None, emby_id=None, tg_id=None
    ):
        """Update user's credits"""
        try:
            if tg_id:
                self.cur.execute(
                    "UPDATE statistics SET credits=? WHERE tg_id=?", (credits, tg_id)
                )
            elif plex_id:
                self.cur.execute(
                    "UPDATE user SET credits=? WHERE plex_id=?", (credits, plex_id)
                )
            elif emby_id:
                self.cur.execute(
                    "UPDATE emby_user SET emby_credits=? WHERE emby_id=?",
                    (credits, emby_id),
                )
            else:
                logging.error("Error: there is no enough params")
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def get_user_credits(self, tg_id):
        """Get user's credits by tg_id"""
        try:
            rslt = self.cur.execute(
                "SELECT credits FROM statistics WHERE tg_id=?", (tg_id,)
            )
            res = rslt.fetchone()
            if res:
                return True, res[0]
            return False, f"未找到用户: {tg_id}"
        except Exception as e:
            logging.error(f"Error: {e}")
            return False, "获取积分失败"

    def update_user_donation(self, donation: int, tg_id):
        """Update user's donation"""
        try:
            self.cur.execute(
                "UPDATE statistics SET donation=? WHERE tg_id=?", (donation, tg_id)
            )
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def update_invitation_status(self, code, used_by):
        try:
            self.cur.execute(
                "UPDATE invitation SET is_used=?,used_by=? WHERE code=?",
                (1, used_by, code),
            )
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def update_all_lib_flag(
        self,
        all_lib: int,
        unlock_time=None,
        plex_id=None,
        emby_id=None,
        tg_id=None,
        media_server="plex",
    ):
        try:
            if media_server.lower() == "plex":
                if plex_id:
                    self.cur.execute(
                        "UPDATE user SET all_lib=?,unlock_time=? WHERE plex_id=?",
                        (all_lib, unlock_time, plex_id),
                    )
                elif tg_id:
                    self.cur.execute(
                        "UPDATE user SET all_lib=?,unlock_time=? WHERE tg_id=?",
                        (all_lib, unlock_time, tg_id),
                    )
            elif media_server.lower() == "emby":
                if emby_id:
                    self.cur.execute(
                        "UPDATE emby_user SET emby_is_unlock=?,emby_unlock_time=? WHERE emby_id=?",
                        (all_lib, unlock_time, emby_id),
                    )
                elif tg_id:
                    self.cur.execute(
                        "UPDATE emby_user SET emby_is_unlock=?,emby_unlock_time=? WHERE tg_id=?",
                        (all_lib, unlock_time, tg_id),
                    )
            else:
                logging.error("Error: please specify correct media server")
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def get_plex_users_num(self):
        rslt = self.cur.execute("SELECT count(*) FROM user")
        return rslt.fetchone()[0]

    def get_emby_users_num(self):
        rslt = self.cur.execute("SELECT count(*) FROM emby_user")
        return rslt.fetchone()[0]

    def get_plex_info_by_tg_id(self, tg_id):
        rslt = self.cur.execute("SELECT * FROM user WHERE tg_id = ?", (tg_id,))
        info = rslt.fetchone()
        return info

    def get_plex_info_by_plex_id(self, plex_id):
        rslt = self.cur.execute("SELECT * FROM user WHERE plex_id = ?", (plex_id,))
        info = rslt.fetchone()
        return info

    def get_plex_info_by_plex_username(self, plex_username: str):
        rslt = self.cur.execute(
            "SELECT * FROM user WHERE plex_username = ?", (plex_username,)
        )
        info = rslt.fetchone()
        return info

    def get_plex_info_by_plex_email(self, plex_email: str):
        rslt = self.cur.execute(
            "SELECT * FROM user WHERE plex_email = ?", (plex_email,)
        )
        info = rslt.fetchone()
        return info

    def get_emby_info_by_emby_username(self, username: str):
        return self.cur.execute(
            "SELECT * FROM emby_user WHERE emby_username = ?", (username,)
        ).fetchone()

    def get_emby_info_by_tg_id(self, tg_id):
        return self.cur.execute(
            "SELECT * FROM emby_user WHERE tg_id = ?", (tg_id,)
        ).fetchone()

    def get_emby_info_by_emby_id(self, emby_id):
        return self.cur.execute(
            "SELECT * FROM emby_user WHERE emby_id = ?", (emby_id,)
        ).fetchone()

    def get_overseerr_info_by_tg_id(self, tg_id):
        return self.cur.execute(
            "SELECT * FROM overseerr WHERE tg_id = ?", (tg_id,)
        ).fetchone()

    def get_overseerr_info_by_email(self, email):
        return self.cur.execute(
            "SELECT * FROM overseerr WHERE user_email = ?", (email,)
        ).fetchone()

    def get_credits_rank(self):
        rslt = self.cur.execute(
            "SELECT tg_id,credits FROM statistics ORDER BY credits DESC"
        )
        res = rslt.fetchall()
        return res

    def get_donation_rank(self):
        rslt = self.cur.execute(
            "SELECT tg_id,donation FROM statistics ORDER BY donation DESC"
        )
        res = rslt.fetchall()
        return res

    def get_plex_watched_time_rank(self):
        rslt = self.cur.execute(
            "SELECT plex_id,tg_id,plex_username,watched_time FROM user ORDER BY watched_time DESC"
        )
        res = rslt.fetchall()
        return res

    def get_emby_watched_time_rank(self):
        return self.cur.execute(
            "SELECT emby_id,emby_username,emby_watched_time FROM emby_user ORDER BY emby_watched_time DESC"
        ).fetchall()

    def verify_invitation_code_is_used(self, code):
        rslt = self.cur.execute(
            "SELECT is_used,owner FROM invitation WHERE code=?", (code,)
        )
        res = rslt.fetchone()
        return res

    def get_invitation_code_by_owner(self, tg_id, is_available=True):
        if is_available:
            rslt = self.cur.execute(
                "SELECT code FROM invitation WHERE owner=? and is_used=0", (tg_id,)
            )
        else:
            rslt = self.cur.execute(
                "SELECT code FROM invitation WHERE owner=?", (tg_id,)
            )
        res = rslt.fetchall()
        res = [_[0] for _ in res]
        return res

    def set_emby_line(self, line, tg_id=None, emby_id=None):
        try:
            if tg_id:
                self.cur.execute(
                    "UPDATE emby_user SET emby_line=? WHERE tg_id=?", (line, tg_id)
                )
            elif emby_id:
                self.cur.execute(
                    "UPDATE emby_user SET emby_line=? WHERE emby_id=?", (line, emby_id)
                )
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def get_emby_line(self, tg_id):
        return self.cur.execute(
            "SELECT emby_line FROM emby_user WHERE tg_id=?", (tg_id,)
        ).fetchone()[0]

    def get_emby_user_with_binded_line(self):
        rslt = self.cur.execute(
            "SELECT emby_username,tg_id,emby_line,is_premium FROM emby_user WHERE emby_line IS NOT NULL"
        )
        return rslt.fetchall()

    def set_plex_line(self, line, tg_id=None, plex_id=None):
        try:
            if tg_id:
                self.cur.execute(
                    "UPDATE user SET plex_line=? WHERE tg_id=?", (line, tg_id)
                )
            elif plex_id:
                self.cur.execute(
                    "UPDATE user SET plex_line=? WHERE plex_id=?", (line, plex_id)
                )
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def get_plex_line(self, tg_id):
        return self.cur.execute(
            "SELECT plex_line FROM user WHERE tg_id=?", (tg_id,)
        ).fetchone()[0]

    def get_plex_user_with_binded_line(self):
        rslt = self.cur.execute(
            "SELECT plex_username,tg_id,plex_line,is_premium FROM user WHERE plex_line IS NOT NULL"
        )
        return rslt.fetchall()

    def add_wheel_spin_record(self, tg_id: int, item_name: str, credits_change: float):
        """记录转盘旋转记录"""
        try:
            import time
            from datetime import datetime

            timestamp = int(time.time())
            date = datetime.now().strftime("%Y-%m-%d")

            self.cur.execute(
                "INSERT INTO wheel_stats (tg_id, item_name, credits_change, timestamp, date) VALUES (?, ?, ?, ?, ?)",
                (tg_id, item_name, credits_change, timestamp, date),
            )
            self.con.commit()
            return True
        except Exception as e:
            logging.error(f"Error adding wheel spin record: {e}")
            return False

    def get_wheel_stats(self):
        """获取转盘统计数据"""
        try:
            from datetime import datetime, timedelta

            # 获取总抽奖次数
            total_spins = self.cur.execute(
                "SELECT COUNT(*) FROM wheel_stats"
            ).fetchone()[0]

            # 获取参与用户数（去重）
            active_users = self.cur.execute(
                "SELECT COUNT(DISTINCT tg_id) FROM wheel_stats"
            ).fetchone()[0]

            # 获取今日抽奖次数
            today = datetime.now().strftime("%Y-%m-%d")
            today_spins = self.cur.execute(
                "SELECT COUNT(*) FROM wheel_stats WHERE date = ?", (today,)
            ).fetchone()[0]

            # 获取本周抽奖次数
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            week_spins = self.cur.execute(
                "SELECT COUNT(*) FROM wheel_stats WHERE date >= ?", (week_ago,)
            ).fetchone()[0]

            # 获取转盘总积分变化（通过转盘获得或失去的积分总和）
            total_credits_change_result = self.cur.execute(
                "SELECT SUM(credits_change) FROM wheel_stats"
            ).fetchone()
            total_credits_change = (
                float(total_credits_change_result[0])
                if total_credits_change_result[0]
                else 0.0
            )

            # 获取幸运大转盘中总邀请码发放数
            total_invite_codes_result = self.cur.execute(
                'SELECT COUNT(*) FROM wheel_stats where item_name="邀请码 1 枚"'
            ).fetchone()
            total_invite_codes = (
                int(total_invite_codes_result[0]) if total_invite_codes_result[0] else 0
            )

            return {
                "totalSpins": total_spins,
                "activeUsers": active_users,
                "todaySpins": today_spins,
                "lastWeekSpins": week_spins,
                "totalCreditsChange": total_credits_change,
                "totalInviteCodes": total_invite_codes,
            }
        except Exception as e:
            logging.error(f"Error getting wheel stats: {e}")
            return {
                "totalSpins": 0,
                "activeUsers": 0,
                "todaySpins": 0,
                "lastWeekSpins": 0,
                "totalCreditsChange": 0.0,
                "totalInviteCodes": 0,
            }

    def close(self):
        self.cur.close()
        self.con.close()
