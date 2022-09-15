#!/usr/bin/env python3

import sqlite3
import logging
import os


class DB:
    """class DB"""
    
    def __init__(self, db=os.path.join(os.path.split(os.path.realpath(__file__))[0], "data.db")):
        self.con = sqlite3.connect(db)
        self.cur = self.con.cursor()
        self.create_table()
        
    def create_table(self):
        try:
            self.cur.execute("CREATE TABLE user(plex_id, tg_id, credits, donate, plex_email, plex_username, init_lib, all_lib)")
            self.con.commit()
        except sqlite3.OperationalError:
            logging.warning("Table is created already, skip...")
    
    def add_user(self, plex_id, tg_id, plex_email, plex_username, credits: int=0, donate: int=0, all_lib=0):
        try:
            self.cur.execute("INSERT INTO user VALUES (?, ?, ?, ?, ?, ?, ?)", (plex_id, tg_id, credits, donate, plex_email, plex_username, all_lib))
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

    def update_all_lib_flag(self, all_lib: int, plex_id=None, tg_id=None):
        try:
            if plex_id:
                self.cur.execute("UPDATE user SET all_lib=? WHERE plex_id=?", (all_lib, plex_id))
            elif tg_id:
                self.cur.execute("UPDATE user SET all_lib=? WHERE tg_id=?", (all_lib, tg_id))            
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

    def get_credits_rank(self):
        rslt = self.cur.execute("SELECT plex_id,tg_id,plex_username,credits FROM user ORDER BY credits DESC")
        res = rslt.fetchall()
        return res

    def get_donation_rank(self):
        rslt = self.cur.execute("SELECT plex_id,tg_id,plex_username,donate FROM user ORDER BY donate DESC")
        res = rslt.fetchall()
        return res

    def close(self):
        self.cur.close()
        self.con.close()
