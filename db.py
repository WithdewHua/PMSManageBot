#!/usr/bin/env python3

import sqlite3
import logging
import os


class DB:
    """class DB"""
    
    def __init__(self, db=os.path.join(os.path.split(os.path.realpath(__file__))[0], "data.db")):
        self.con = sqlite3.connect(db)
        self.cur = self.con.cursor()
        # self.create_table()
        
    def create_table(self):
        try:
            self.cur.execute("CREATE TABLE user(plex_id, tg_id, credits, donate, plex_email, plex_username, init_lib, all_lib, unlock_time, watched_time)")
        except sqlite3.OperationalError:
            logging.warning("Table user is created already, skip...")
        else:
            self.con.commit()
    
    def add_user(self, plex_id, tg_id, plex_email, plex_username, credits: int=0, donate: int=0, all_lib=0, unlock_time=None, watched_time=0):
        try:
            self.cur.execute("INSERT INTO user VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (plex_id, tg_id, credits, donate, plex_email, plex_username, all_lib, unlock_time, watched_time))
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def update_user(self, plex_id, tg_id):
        try:
            self.cur.execute("UPDATE user SET tg_id=? WHERE plex_id=?", (plex_id, tg_id))
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True


    def add_invitation_code(self, code, owner, is_used=0, used_by=None) -> bool:
        try:
            self.cur.execute("INSERT INTO invitation VALUES (?, ?, ?, ?)", (code, owner, is_used, used_by))
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True
        
    def update_user_credits(self, credits: int, plex_id=None, tg_id=None):
        """Update user's credits"""
        try:
            if plex_id:
                self.cur.execute("UPDATE user SET credits=? WHERE plex_id=?", (credits, plex_id))
            elif tg_id:
                self.cur.execute("UPDATE user SET credits=? WHERE tg_id=?", (credits, tg_id))
            else:
                logging.error("Error: there is no enough params")
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def update_user_donation(self, donation: int, plex_id=None, tg_id=None):
        """Update user's donation"""
        try:
            if plex_id:
                self.cur.execute("UPDATE user SET donate=? WHERE plex_id=?", (donation, plex_id))
            elif tg_id:
                self.cur.execute("UPDATE user SET donate=? WHERE tg_id=?", (donation, tg_id))            
            else:
                logging.error("Error: there is no enough params")
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def update_invitation_status(self, code, used_by):
        try:
            self.cur.execute("UPDATE invitation SET is_used=?,used_by=? WHERE code=?", (1, used_by, code))
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True


    def update_all_lib_flag(self, all_lib: int, unlock_time=None, plex_id=None, tg_id=None):
        try:
            if plex_id:
                self.cur.execute("UPDATE user SET all_lib=?,unlock_time=? WHERE plex_id=?", (all_lib, unlock_time, plex_id))
            elif tg_id:
                self.cur.execute("UPDATE user SET all_lib=?,unlock_time=? WHERE tg_id=?", (all_lib, unlock_time, tg_id))            
            else:
                logging.error("Error: there is no enough params")
        except Exception as e:
            logging.error(f"Error: {e}")
            return False
        else:
            self.con.commit()
        return True

    def get_info_by_tg_id(self, tg_id):
        rslt = self.cur.execute("SELECT * FROM user WHERE tg_id = ?", (tg_id,))
        info = rslt.fetchone()
        return info

    def get_info_by_plex_id(self, plex_id):
        rslt = self.cur.execute("SELECT * FROM user WHERE plex_id = ?", (plex_id,))
        info = rslt.fetchone()
        return info

    def get_credits_rank(self):
        rslt = self.cur.execute("SELECT plex_id,tg_id,plex_username,credits FROM user ORDER BY credits DESC")
        res = rslt.fetchall()
        return res

    def get_donation_rank(self):
        rslt = self.cur.execute("SELECT plex_id,tg_id,plex_username,donate FROM user ORDER BY donate DESC")
        res = rslt.fetchall()
        return res

    def get_watched_time_rank(self):
        rslt = self.cur.execute("SELECT plex_id,tg_id,plex_username,watched_time FROM user ORDER BY watched_time DESC")
        res = rslt.fetchall()
        return res

    def verify_invitation_code_is_used(self, code):
        rslt = self.cur.execute("SELECT is_used,owner FROM invitation WHERE code=?", (code,))
        res = rslt.fetchone()
        return res

    def get_invitation_code_by_owner(self, tg_id, is_available=True):
        if is_available:
            rslt = self.cur.execute("SELECT code FROM invitation WHERE owner=? and is_used=0", (tg_id,))
        else:
            rslt = self.cur.execute("SELECT code FROM invitation WHERE owner=?", (tg_id,))
        res = rslt.fetchall()
        res = [_[0] for _ in res]
        return res

    def close(self):
        self.cur.close()
        self.con.close()
