#!/usr/bin/env python3

import sqlite3
import time
import traceback
from datetime import datetime, timedelta
from typing import List, Optional

from app.config import settings
from app.log import logger


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
                    premium_expiry_time
                );

                CREATE TABLE invitation(
                    code, owner, is_used, userd_by
                );

                CREATE TABLE statistics(
                    tg_id, donation, credits
                );

                CREATE TABLE emby_user(
                    emby_username, emby_id, tg_id, emby_is_unlock, emby_unlock_time, emby_watched_time, emby_credits, emby_line, is_premium, premium_expiry_time
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

                CREATE TABLE auctions(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    starting_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    end_time INTEGER NOT NULL,
                    created_by INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    winner_id INTEGER DEFAULT NULL,
                    bid_count INTEGER DEFAULT 0
                );

                CREATE TABLE auction_bids(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    auction_id INTEGER NOT NULL,
                    bidder_id INTEGER NOT NULL,
                    bid_amount REAL NOT NULL,
                    bid_time INTEGER NOT NULL,
                    FOREIGN KEY (auction_id) REFERENCES auctions (id)
                );

                CREATE TABLE line_traffic_stats(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    line TEXT NOT NULL,
                    send_bytes INTEGER NOT NULL,
                    service TEXT NOT NULL,
                    username TEXT NOT NULL,
                    user_id TEXT DEFAULT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
        except sqlite3.OperationalError:
            logger.warning("Table user is created already, skip...")
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
        premium_expiry_time: Optional[str] = None,
    ):
        try:
            self.cur.execute(
                "INSERT INTO user VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    premium_expiry_time,
                ),
            )
        except Exception as e:
            logger.error(f"Error: {e}")
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
        premium_expiry_time: Optional[str] = None,
    ) -> bool:
        try:
            self.cur.execute(
                "INSERT INTO emby_user VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    premium_expiry_time,
                ),
            )
        except Exception as e:
            logger.error(f"Error: {e}")
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
            logger.error(f"Error: {e}")
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
            logger.error(f"Error: {e}")
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
            logger.error(f"Error: {e}")
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
            logger.error(f"Error: {e}")
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
                logger.error("Error: there is no enough params")
        except Exception as e:
            logger.error(f"Error: {e}")
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
            logger.error(f"Error: {e}")
            return False, "获取积分失败"

    def update_user_donation(self, donation: int, tg_id):
        """Update user's donation"""
        try:
            self.cur.execute(
                "UPDATE statistics SET donation=? WHERE tg_id=?", (donation, tg_id)
            )
        except Exception as e:
            logger.error(f"Error: {e}")
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
            logger.error(f"Error: {e}")
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
                logger.error("Error: please specify correct media server")
        except Exception as e:
            logger.error(f"Error: {e}")
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
            "SELECT * FROM user WHERE LOWER(plex_email) = ?", (plex_email.lower(),)
        )
        info = rslt.fetchone()
        return info

    def get_emby_info_by_emby_username(self, username: str):
        return self.cur.execute(
            "SELECT * FROM emby_user WHERE LOWER(emby_username) = ?",
            (username.lower(),),
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
            "SELECT plex_id,tg_id,plex_username,watched_time,is_premium FROM user ORDER BY watched_time DESC"
        )
        res = rslt.fetchall()
        return res

    def get_emby_watched_time_rank(self):
        return self.cur.execute(
            "SELECT emby_id,emby_username,emby_watched_time,is_premium,tg_id FROM emby_user ORDER BY emby_watched_time DESC"
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
            logger.error(f"Error: {e}")
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
            logger.error(f"Error: {e}")
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
            timestamp = int(time.time())
            date = datetime.now(settings.TZ).strftime("%Y-%m-%d")

            self.cur.execute(
                "INSERT INTO wheel_stats (tg_id, item_name, credits_change, timestamp, date) VALUES (?, ?, ?, ?, ?)",
                (tg_id, item_name, credits_change, timestamp, date),
            )
            self.con.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding wheel spin record: {e}")
            return False

    def get_wheel_stats(self):
        """获取转盘统计数据"""
        try:
            # 获取总抽奖次数
            total_spins = self.cur.execute(
                "SELECT COUNT(*) FROM wheel_stats"
            ).fetchone()[0]

            # 获取参与用户数（去重）
            active_users = self.cur.execute(
                "SELECT COUNT(DISTINCT tg_id) FROM wheel_stats"
            ).fetchone()[0]

            # 获取今日抽奖次数（使用UTC+8北京时间）
            today = datetime.now(settings.TZ).strftime("%Y-%m-%d")
            today_spins = self.cur.execute(
                "SELECT COUNT(*) FROM wheel_stats WHERE date = ?", (today,)
            ).fetchone()[0]

            # 获取本周抽奖次数（使用UTC+8北京时间）
            week_ago = (datetime.now(settings.TZ) - timedelta(days=7)).strftime(
                "%Y-%m-%d"
            )
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
            logger.error(f"Error getting wheel stats: {e}")
            return {
                "totalSpins": 0,
                "activeUsers": 0,
                "todaySpins": 0,
                "lastWeekSpins": 0,
                "totalCreditsChange": 0.0,
                "totalInviteCodes": 0,
            }

    def create_auction(
        self,
        title: str,
        description: str,
        starting_price: float,
        end_time: int,
        created_by: int,
    ) -> Optional[int]:
        """创建竞拍"""
        try:
            import time

            created_at = int(time.time())

            self.cur.execute(
                """INSERT INTO auctions 
                   (title, description, starting_price, current_price, end_time, created_by, created_at) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    title,
                    description,
                    starting_price,
                    starting_price,
                    end_time,
                    created_by,
                    created_at,
                ),
            )
            self.con.commit()
            return self.cur.lastrowid
        except Exception as e:
            logger.error(f"Error creating auction: {e}")
            return None

    def get_auction_by_id(self, auction_id: int) -> Optional[dict]:
        """根据ID获取竞拍信息"""
        try:
            result = self.cur.execute(
                "SELECT * FROM auctions WHERE id = ?", (auction_id,)
            ).fetchone()

            if result:
                return {
                    "id": result[0],
                    "title": result[1] or f"竞拍活动 #{result[0]}",
                    "description": result[2] or "无描述",
                    "starting_price": result[3] or 0,
                    "current_price": result[4] or result[3] or 0,
                    "end_time": result[5],
                    "created_by": result[6],
                    "created_at": result[7],
                    "is_active": result[8],
                    "winner_id": result[9],
                    "bid_count": result[10],
                }
            return None
        except Exception as e:
            logger.error(f"Error getting auction by id: {e}")
            return None

    def get_active_auctions(self, limit: int = 50) -> List[dict]:
        """获取活跃竞拍列表"""
        try:
            import time

            current_time = int(time.time())

            results = self.cur.execute(
                """SELECT * FROM auctions 
                   WHERE is_active = 1 AND end_time > ? 
                   ORDER BY created_at DESC LIMIT ?""",
                (current_time, limit),
            ).fetchall()

            auctions = []
            for result in results:
                auctions.append(
                    {
                        "id": result[0],
                        "title": result[1] or f"竞拍活动 #{result[0]}",
                        "description": result[2] or "无描述",
                        "starting_price": result[3] or 0,
                        "current_price": result[4] or result[3] or 0,
                        "end_time": result[5],
                        "created_by": result[6],
                        "created_at": result[7],
                        "is_active": result[8],
                        "winner_id": result[9],
                        "bid_count": result[10],
                    }
                )
            return auctions
        except Exception as e:
            logger.error(f"Error getting active auctions: {e}")
            return []

    def place_bid(self, auction_id: int, bidder_id: int, bid_amount: float) -> bool:
        """出价"""
        try:
            import time

            bid_time = int(time.time())

            # 检查竞拍是否存在且活跃
            auction = self.get_auction_by_id(auction_id)
            if (
                not auction
                or not auction["is_active"]
                or auction["end_time"] <= bid_time
            ):
                return False

            # 检查出价是否高于当前价格
            if bid_amount <= auction["current_price"]:
                return False

            # 插入出价记录
            self.cur.execute(
                "INSERT INTO auction_bids (auction_id, bidder_id, bid_amount, bid_time) VALUES (?, ?, ?, ?)",
                (auction_id, bidder_id, bid_amount, bid_time),
            )

            # 更新竞拍当前价格和出价次数
            self.cur.execute(
                "UPDATE auctions SET current_price = ?, bid_count = bid_count + 1 WHERE id = ?",
                (bid_amount, auction_id),
            )

            self.con.commit()
            return True
        except Exception as e:
            logger.error(f"Error placing bid: {e}")
            return False

    def get_auction_bids(self, auction_id: int, limit: int = 50) -> List[dict]:
        """获取竞拍出价记录"""
        try:
            results = self.cur.execute(
                """SELECT ab.* 
                FROM auction_bids ab 
                WHERE ab.auction_id = ? 
                ORDER BY ab.bid_time DESC 
                LIMIT ?""",
                (auction_id, limit),
            ).fetchall()

            bids = []
            for result in results:
                bids.append(
                    {
                        "id": result[0],
                        "auction_id": result[1],
                        "bidder_id": result[2],
                        "bid_amount": result[3],
                        "bid_time": result[4],
                        "bidder_name": f"用户{result[2]}",
                    }
                )
            return bids
        except Exception as e:
            logger.error(f"Error getting auction bids: {e}")
            return []

    def get_user_highest_bid(self, auction_id: int, user_id: int) -> Optional[float]:
        """获取用户在特定竞拍中的最高出价"""
        try:
            result = self.cur.execute(
                "SELECT MAX(bid_amount) FROM auction_bids WHERE auction_id = ? AND bidder_id = ?",
                (auction_id, user_id),
            ).fetchone()

            return result[0] if result and result[0] else None
        except Exception as e:
            logger.error(f"Error getting user highest bid: {e}")
            return None

    def finish_expired_auctions(self) -> List[dict]:
        """结束过期的竞拍"""
        try:
            import time

            current_time = int(time.time())

            # 查找过期的活跃竞拍
            expired_auctions = self.cur.execute(
                "SELECT * FROM auctions WHERE is_active = 1 AND end_time <= ?",
                (current_time,),
            ).fetchall()

            finished_auctions = []
            for auction in expired_auctions:
                auction_id = auction[0]

                # 获取最高出价者
                highest_bid = self.cur.execute(
                    """SELECT bidder_id, MAX(bid_amount) FROM auction_bids 
                       WHERE auction_id = ? GROUP BY auction_id""",
                    (auction_id,),
                ).fetchone()

                winner_id = highest_bid[0] if highest_bid else None
                final_price = auction[4]  # current_price from auctions table
                credits_reduced = False
                # 如果有获胜者，扣除其积分
                if winner_id and highest_bid:
                    final_price = highest_bid[1]  # 使用最高出价作为最终价格

                    # 扣除获胜者的积分
                    success, current_credits = self.get_user_credits(winner_id)
                    if success and current_credits >= final_price:
                        self.cur.execute(
                            "UPDATE statistics SET credits = credits - ? WHERE tg_id = ?",
                            (final_price, winner_id),
                        )
                        credits_reduced = True
                        logger.info(
                            f"Auction {auction_id} finished: deducted {final_price} credits from winner {winner_id}"
                        )
                    else:
                        logger.warning(
                            f"Winner {winner_id} has insufficient credits ({current_credits}) for auction {auction_id} (price: {final_price})"
                        )

                # 更新竞拍状态
                self.cur.execute(
                    "UPDATE auctions SET is_active = 0, winner_id = ?, current_price = ? WHERE id = ?",
                    (winner_id, final_price, auction_id),
                )

                finished_auctions.append(
                    {
                        "id": auction_id,
                        "title": auction[1] or f"竞拍活动 #{auction_id}",
                        "winner_id": winner_id,
                        "final_price": final_price,
                        "credits_reduced": credits_reduced,
                    }
                )

            self.con.commit()
            return finished_auctions
        except Exception as e:
            logger.error(f"Error finishing expired auctions: {e}")
            logger.error(traceback.format_exc())
            return []

    def get_auction_stats(self) -> dict:
        """获取竞拍统计数据"""
        try:
            # 总竞拍数
            total_auctions = self.cur.execute(
                "SELECT COUNT(*) FROM auctions"
            ).fetchone()[0]

            # 活跃竞拍数
            import time

            current_time = int(time.time())
            active_auctions = self.cur.execute(
                "SELECT COUNT(*) FROM auctions WHERE is_active = 1 AND end_time > ?",
                (current_time,),
            ).fetchone()[0]

            # 总出价数
            total_bids = self.cur.execute(
                "SELECT COUNT(*) FROM auction_bids"
            ).fetchone()[0]

            # 总成交价值
            total_value_result = self.cur.execute(
                "SELECT SUM(current_price) FROM auctions WHERE winner_id IS NOT NULL"
            ).fetchone()
            total_value = float(total_value_result[0]) if total_value_result[0] else 0.0

            return {
                "total_auctions": total_auctions,
                "active_auctions": active_auctions,
                "total_bids": total_bids,
                "total_value": total_value,
            }
        except Exception as e:
            logger.error(f"Error getting auction stats: {e}")
            return {
                "total_auctions": 0,
                "active_auctions": 0,
                "total_bids": 0,
                "total_value": 0.0,
            }

    def get_all_auctions(
        self, status: str = None, limit: int = 50, offset: int = 0
    ) -> List[dict]:
        """获取所有竞拍活动（管理员用）"""
        try:
            if status:
                if status == "active":
                    import time

                    current_time = int(time.time())
                    self.cur.execute(
                        """SELECT * FROM auctions 
                        WHERE is_active = 1 AND end_time > ? 
                        ORDER BY created_at DESC 
                        LIMIT ? OFFSET ?""",
                        (current_time, limit, offset),
                    )
                elif status == "ended":
                    import time

                    current_time = int(time.time())
                    self.cur.execute(
                        """SELECT * FROM auctions 
                        WHERE is_active = 0 OR end_time <= ? 
                        ORDER BY created_at DESC 
                        LIMIT ? OFFSET ?""",
                        (current_time, limit, offset),
                    )
                else:
                    self.cur.execute(
                        "SELECT * FROM auctions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                        (limit, offset),
                    )
            else:
                self.cur.execute(
                    "SELECT * FROM auctions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )

            auctions = []
            for auction in self.cur.fetchall():
                # 获取出价数量
                bid_count = self.cur.execute(
                    "SELECT COUNT(*) FROM auction_bids WHERE auction_id = ?",
                    (auction[0],),
                ).fetchone()[0]

                auctions.append(
                    {
                        "id": auction[0],
                        "title": auction[1] or f"竞拍活动 #{auction[0]}",
                        "description": auction[2] or "无描述",
                        "starting_price": auction[3] or 0,
                        "current_price": auction[4] or auction[3] or 0,
                        "end_time": auction[5],
                        "created_by": auction[6],
                        "created_at": auction[7],
                        "is_active": bool(auction[8]),
                        "winner_id": auction[9],
                        "bid_count": bid_count,
                        "status": self._get_auction_status(auction),
                    }
                )

            return auctions
        except Exception as e:
            logger.error(f"Error getting all auctions: {e}")
            return []

    def _get_auction_status(self, auction) -> str:
        """获取竞拍状态"""
        import time

        current_time = int(time.time())

        if not auction[8]:  # is_active
            return "ended"
        elif auction[5] <= current_time:  # end_time
            return "ended"
        else:
            return "active"

    def update_auction(self, auction_id: int, update_data: dict) -> bool:
        """更新竞拍活动"""
        try:
            # 构建更新语句
            set_clauses = []
            values = []

            if "title" in update_data:
                set_clauses.append("title = ?")
                values.append(update_data["title"])

            if "description" in update_data:
                set_clauses.append("description = ?")
                values.append(update_data["description"])

            if "starting_price" in update_data:
                set_clauses.append("starting_price = ?")
                values.append(update_data["starting_price"])

            if "end_time" in update_data:
                set_clauses.append("end_time = ?")
                values.append(update_data["end_time"])

            if not set_clauses:
                return False

            values.append(auction_id)

            self.cur.execute(
                f"UPDATE auctions SET {', '.join(set_clauses)} WHERE id = ?",
                tuple(values),
            )

            self.con.commit()
            return self.cur.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating auction: {e}")
            return False

    def delete_auction(self, auction_id: int) -> bool:
        """删除竞拍活动"""
        try:
            # 先删除相关的出价记录
            self.cur.execute(
                "DELETE FROM auction_bids WHERE auction_id = ?", (auction_id,)
            )

            # 再删除竞拍活动
            self.cur.execute("DELETE FROM auctions WHERE id = ?", (auction_id,))

            self.con.commit()
            return self.cur.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting auction: {e}")
            return False

    def finish_auction_by_id(self, auction_id: int) -> tuple:
        """手动结束指定竞拍活动"""
        try:
            # 获取竞拍信息
            auction = self.get_auction_by_id(auction_id)
            if not auction:
                return False, f"竞拍 id {auction_id} 不存在"

            # 获取最高出价
            highest_bid = self.cur.execute(
                """SELECT bidder_id, bid_amount FROM auction_bids 
                WHERE auction_id = ? ORDER BY bid_amount DESC LIMIT 1""",
                (auction_id,),
            ).fetchone()

            winner_id = None
            final_price = auction["starting_price"]
            credits_reduced = False

            if highest_bid:
                winner_id = highest_bid[0]
                final_price = highest_bid[1]

                # 扣除获胜者的积分
                success, current_credits = self.get_user_credits(winner_id)
                if success and current_credits >= final_price:
                    self.cur.execute(
                        "UPDATE statistics SET credits = credits - ? WHERE tg_id = ?",
                        (final_price, winner_id),
                    )
                    credits_reduced = True

            # 更新竞拍状态
            self.cur.execute(
                """UPDATE auctions 
                SET is_active = 0, winner_id = ?, current_price = ? 
                WHERE id = ?""",
                (winner_id, final_price, auction_id),
            )

            self.con.commit()
            return True, {
                "id": auction_id,
                "title": auction["title"],
                "winner_id": winner_id,
                "final_price": final_price,
                "credits_reduced": credits_reduced,
            }

        except Exception as e:
            logger.error(f"Error finishing auction {auction_id}: {e}")
            logger.error(traceback.format_exc())
            return False, str(e)

    def get_user_auction_history(self, user_id: int, limit: int = 20) -> List[dict]:
        """获取用户参与的竞拍历史"""
        try:
            self.cur.execute(
                """SELECT DISTINCT a.*, ab.bid_amount as user_highest_bid
                FROM auctions a
                JOIN auction_bids ab ON a.id = ab.auction_id
                WHERE ab.bidder_id = ?
                ORDER BY a.created_at DESC
                LIMIT ?""",
                (user_id, limit),
            )

            auctions = []
            for auction in self.cur.fetchall():
                # 获取用户最高出价
                highest_bid = self.cur.execute(
                    """SELECT MAX(bid_amount) FROM auction_bids 
                    WHERE auction_id = ? AND bidder_id = ?""",
                    (auction[0], user_id),
                ).fetchone()[0]

                auctions.append(
                    {
                        "id": auction[0],
                        "title": auction[1] or f"竞拍活动 #{auction[0]}",
                        "description": auction[2] or "无描述",
                        "starting_price": auction[3] or 0,
                        "current_price": auction[4] or auction[3] or 0,
                        "end_time": auction[5],
                        "created_by": auction[6],
                        "created_at": auction[7],
                        "is_active": bool(auction[8]),
                        "winner_id": auction[9],
                        "user_highest_bid": highest_bid,
                        "is_winner": auction[9] == user_id,
                    }
                )

            return auctions
        except Exception as e:
            logger.error(f"Error getting user auction history: {e}")
            return []

    def get_detailed_auction_stats(
        self, start_date: int = None, end_date: int = None
    ) -> dict:
        """获取详细的竞拍统计数据"""
        try:
            # 设置默认时间范围（如果未提供）
            if not start_date:
                start_date = 0
            if not end_date:
                end_date = int(time.time())

            # 基本统计
            stats = self.get_auction_stats()

            # 时间段内的统计
            period_auctions = self.cur.execute(
                "SELECT COUNT(*) FROM auctions WHERE created_at BETWEEN ? AND ?",
                (start_date, end_date),
            ).fetchone()[0]

            period_bids = self.cur.execute(
                """SELECT COUNT(*) FROM auction_bids ab
                JOIN auctions a ON ab.auction_id = a.id
                WHERE a.created_at BETWEEN ? AND ?""",
                (start_date, end_date),
            ).fetchone()[0]

            # 平均出价数
            avg_bids_result = self.cur.execute(
                """SELECT AVG(bid_count) FROM (
                    SELECT COUNT(*) as bid_count FROM auction_bids 
                    GROUP BY auction_id
                )"""
            ).fetchone()
            avg_bids = float(avg_bids_result[0]) if avg_bids_result[0] else 0.0

            # 最高成交价
            highest_price_result = self.cur.execute(
                "SELECT MAX(current_price) FROM auctions WHERE winner_id IS NOT NULL"
            ).fetchone()
            highest_price = (
                float(highest_price_result[0]) if highest_price_result[0] else 0.0
            )

            stats.update(
                {
                    "period_auctions": period_auctions,
                    "period_bids": period_bids,
                    "avg_bids_per_auction": avg_bids,
                    "highest_transaction": highest_price,
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )

            return stats
        except Exception as e:
            logger.error(f"Error getting detailed auction stats: {e}")
            return self.get_auction_stats()

    def get_user_wheel_stats(self, tg_id: int):
        """获取用户个人转盘统计数据"""
        try:
            # 使用UTC+8北京时间
            today = datetime.now(settings.TZ).strftime("%Y-%m-%d")
            week_ago = (datetime.now(settings.TZ) - timedelta(days=7)).strftime(
                "%Y-%m-%d"
            )

            # 获取用户今日游戏次数
            today_spins = self.cur.execute(
                "SELECT COUNT(*) FROM wheel_stats WHERE tg_id = ? AND date = ?",
                (tg_id, today),
            ).fetchone()[0]

            # 获取用户总游戏次数
            total_spins = self.cur.execute(
                "SELECT COUNT(*) FROM wheel_stats WHERE tg_id = ?", (tg_id,)
            ).fetchone()[0]

            # 获取用户本周游戏次数
            week_spins = self.cur.execute(
                "SELECT COUNT(*) FROM wheel_stats WHERE tg_id = ? AND date >= ?",
                (tg_id, week_ago),
            ).fetchone()[0]

            # 获取用户总积分变化
            total_credits_change_result = self.cur.execute(
                "SELECT SUM(credits_change) FROM wheel_stats WHERE tg_id = ?", (tg_id,)
            ).fetchone()
            total_credits_change = (
                float(total_credits_change_result[0])
                if total_credits_change_result[0]
                else 0.0
            )

            # 获取用户今日积分变化
            today_credits_change_result = self.cur.execute(
                "SELECT SUM(credits_change) FROM wheel_stats WHERE tg_id = ? AND date = ?",
                (tg_id, today),
            ).fetchone()
            today_credits_change = (
                float(today_credits_change_result[0])
                if today_credits_change_result[0]
                else 0.0
            )

            # 获取用户本周积分变化
            week_credits_change_result = self.cur.execute(
                "SELECT SUM(credits_change) FROM wheel_stats WHERE tg_id = ? AND date >= ?",
                (tg_id, week_ago),
            ).fetchone()
            week_credits_change = (
                float(week_credits_change_result[0])
                if week_credits_change_result[0]
                else 0.0
            )

            # 获取用户通过转盘获得的邀请码数量
            invite_codes_earned = self.cur.execute(
                'SELECT COUNT(*) FROM wheel_stats WHERE tg_id = ? AND item_name = "邀请码 1 枚"',
                (tg_id,),
            ).fetchone()[0]

            # 获取用户今日获得的邀请码数量
            today_invite_codes = self.cur.execute(
                'SELECT COUNT(*) FROM wheel_stats WHERE tg_id = ? AND item_name = "邀请码 1 枚" AND date = ?',
                (tg_id, today),
            ).fetchone()[0]

            # 获取用户本周获得的邀请码数量
            week_invite_codes = self.cur.execute(
                'SELECT COUNT(*) FROM wheel_stats WHERE tg_id = ? AND item_name = "邀请码 1 枚" AND date >= ?',
                (tg_id, week_ago),
            ).fetchone()[0]

            # 获取用户最近5次游戏记录
            recent_games = self.cur.execute(
                """SELECT item_name, credits_change, date, timestamp 
                   FROM wheel_stats 
                   WHERE tg_id = ? 
                   ORDER BY timestamp DESC 
                   LIMIT 5""",
                (tg_id,),
            ).fetchall()

            recent_games_list = []
            for game in recent_games:
                recent_games_list.append(
                    {
                        "item_name": game[0],
                        "credits_change": game[1],
                        "date": game[2],
                        "timestamp": game[3],
                    }
                )

            return {
                "today_spins": today_spins,
                "total_spins": total_spins,
                "week_spins": week_spins,
                "total_credits_change": total_credits_change,
                "today_credits_change": today_credits_change,
                "week_credits_change": week_credits_change,
                "total_invite_codes": invite_codes_earned,
                "today_invite_codes": today_invite_codes,
                "week_invite_codes": week_invite_codes,
                "recent_games": recent_games_list,
            }
        except Exception as e:
            logger.error(f"Error getting user wheel stats: {e}")
            return {
                "today_spins": 0,
                "total_spins": 0,
                "week_spins": 0,
                "total_credits_change": 0.0,
                "today_credits_change": 0.0,
                "week_credits_change": 0.0,
                "total_invite_codes": 0,
                "today_invite_codes": 0,
                "week_invite_codes": 0,
                "recent_games": [],
            }

    def close(self):
        self.cur.close()
        self.con.close()

    def get_expired_premium_users(self):
        """获取所有 Premium 已过期的用户"""

        expired_users = []
        current_time = datetime.now(settings.TZ).isoformat()

        # 检查 Plex 用户
        plex_users = self.cur.execute(
            "SELECT tg_id, plex_username, premium_expiry_time, plex_line FROM user WHERE is_premium=1 AND premium_expiry_time IS NOT NULL AND premium_expiry_time < ?",
            (current_time,),
        ).fetchall()

        for user in plex_users:
            expired_users.append(
                {
                    "tg_id": user[0],
                    "username": user[1],
                    "service": "plex",
                    "expiry_time": user[2],
                    "line": user[3],
                }
            )

        # 检查 Emby 用户
        emby_users = self.cur.execute(
            "SELECT tg_id, emby_username, premium_expiry_time, emby_line FROM emby_user WHERE is_premium=1 AND premium_expiry_time IS NOT NULL AND premium_expiry_time < ?",
            (current_time,),
        ).fetchall()

        for user in emby_users:
            expired_users.append(
                {
                    "tg_id": user[0],
                    "username": user[1],
                    "service": "emby",
                    "expiry_time": user[2],
                    "line": user[3],
                }
            )

        return expired_users

    def update_expired_premium_status(self):
        """批量更新已过期的 Premium 用户状态"""

        current_time = datetime.now(settings.TZ).isoformat()

        # 更新 Plex 用户 - 清空过期时间
        plex_result = self.cur.execute(
            "UPDATE user SET is_premium=0, premium_expiry_time=NULL WHERE is_premium=1 AND premium_expiry_time IS NOT NULL AND premium_expiry_time < ?",
            (current_time,),
        )

        # 更新 Emby 用户 - 清空过期时间
        emby_result = self.cur.execute(
            "UPDATE emby_user SET is_premium=0, premium_expiry_time=NULL WHERE is_premium=1 AND premium_expiry_time IS NOT NULL AND premium_expiry_time < ?",
            (current_time,),
        )

        self.con.commit()

        total_updated = plex_result.rowcount + emby_result.rowcount
        return total_updated

    def get_premium_users_expiring_soon(self, days: int = 3):
        """获取即将过期的 Premium 用户（默认3天内）"""

        current_time = datetime.now(settings.TZ)
        warning_time = (current_time + timedelta(days=days)).isoformat()
        current_time_str = current_time.isoformat()

        expiring_users = []

        # 检查 Plex 用户
        plex_users = self.cur.execute(
            "SELECT tg_id, plex_username, premium_expiry_time FROM user WHERE is_premium=1 AND premium_expiry_time IS NOT NULL AND premium_expiry_time > ? AND premium_expiry_time <= ?",
            (current_time_str, warning_time),
        ).fetchall()

        for user in plex_users:
            expiry_dt = datetime.fromisoformat(user[2]).astimezone(settings.TZ)
            days_remaining = (expiry_dt - current_time).days
            expiring_users.append(
                {
                    "tg_id": user[0],
                    "username": user[1],
                    "service": "plex",
                    "expiry_time": user[2],
                    "days_remaining": days_remaining,
                }
            )

        # 检查 Emby 用户
        emby_users = self.cur.execute(
            "SELECT tg_id, emby_username, premium_expiry_time FROM emby_user WHERE is_premium=1 AND premium_expiry_time IS NOT NULL AND premium_expiry_time > ? AND premium_expiry_time <= ?",
            (current_time_str, warning_time),
        ).fetchall()

        for user in emby_users:
            expiry_dt = datetime.fromisoformat(user[2]).astimezone(settings.TZ)
            days_remaining = (expiry_dt - current_time).days
            expiring_users.append(
                {
                    "tg_id": user[0],
                    "username": user[1],
                    "service": "emby",
                    "expiry_time": user[2],
                    "days_remaining": days_remaining,
                }
            )

        return expiring_users

    def get_premium_statistics(self):
        """获取 Premium 用户统计信息"""
        try:
            current_time = datetime.now(settings.TZ).isoformat()

            # 总 Premium 用户数（包含 Plex 和 Emby，去重）
            total_premium_users_query = """
            SELECT COUNT(DISTINCT tg_id) FROM (
                SELECT tg_id FROM user WHERE is_premium=1 AND tg_id IS NOT NULL
                UNION
                SELECT tg_id FROM emby_user WHERE is_premium=1 AND tg_id IS NOT NULL
            )
            """
            total_premium_users = self.cur.execute(
                total_premium_users_query
            ).fetchone()[0]

            # 活跃 Premium 用户数（未过期的）
            active_premium_users_query = """
            SELECT COUNT(DISTINCT tg_id) FROM (
                SELECT tg_id FROM user 
                WHERE is_premium=1 AND tg_id IS NOT NULL 
                AND (premium_expiry_time IS NULL OR premium_expiry_time > ?)
                UNION
                SELECT tg_id FROM emby_user 
                WHERE is_premium=1 AND tg_id IS NOT NULL 
                AND (premium_expiry_time IS NULL OR premium_expiry_time > ?)
            )
            """
            active_premium_users = self.cur.execute(
                active_premium_users_query, (current_time, current_time)
            ).fetchone()[0]

            # Premium Plex 用户数（未过期的）
            premium_plex_users = self.cur.execute(
                """SELECT COUNT(*) FROM user 
                WHERE is_premium=1 
                AND (premium_expiry_time IS NULL OR premium_expiry_time > ?)""",
                (current_time,),
            ).fetchone()[0]

            # Premium Emby 用户数（未过期的）
            premium_emby_users = self.cur.execute(
                """SELECT COUNT(*) FROM emby_user 
                WHERE is_premium=1 
                AND (premium_expiry_time IS NULL OR premium_expiry_time > ?)""",
                (current_time,),
            ).fetchone()[0]

            return {
                "total_premium_users": total_premium_users,
                "active_premium_users": active_premium_users,
                "premium_plex_users": premium_plex_users,
                "premium_emby_users": premium_emby_users,
            }

        except Exception as e:
            logger.error(f"Error getting premium statistics: {e}")
            return {
                "total_premium_users": 0,
                "active_premium_users": 0,
                "premium_plex_users": 0,
                "premium_emby_users": 0,
            }

    def create_line_traffic_entry(
        self,
        line: str,
        send_bytes: int,
        service: str,
        username: str,
        user_id: str,
        timestamp: str,
    ):
        try:
            self.cur.execute(
                "INSERT INTO line_traffic_stats (line, send_bytes, service, username, user_id, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (line, send_bytes, service, username, user_id, timestamp),
            )
        except Exception as e:
            logger.error(f"Error creating line traffic entry: {e}")
            return False
        else:
            self.con.commit()
            return True

    def get_premium_line_traffic_statistics(self):
        """获取Premium线路流量统计信息"""
        try:
            now = datetime.now(settings.TZ)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=now.weekday())
            month_start = today_start.replace(day=1)

            # 获取Premium线路列表
            premium_lines = settings.PREMIUM_STREAM_BACKEND

            line_stats = []

            for line in premium_lines:
                # 计算今日流量
                today_traffic_query = """
                SELECT COALESCE(SUM(send_bytes), 0) as traffic
                FROM line_traffic_stats 
                WHERE line = ? AND timestamp >= ?
                """
                today_traffic = self.cur.execute(
                    today_traffic_query, (line, today_start.isoformat())
                ).fetchone()[0]

                # 计算本周流量
                week_traffic_query = """
                SELECT COALESCE(SUM(send_bytes), 0) as traffic
                FROM line_traffic_stats 
                WHERE line = ? AND timestamp >= ?
                """
                week_traffic = self.cur.execute(
                    week_traffic_query, (line, week_start.isoformat())
                ).fetchone()[0]

                # 计算本月流量
                month_traffic_query = """
                SELECT COALESCE(SUM(send_bytes), 0) as traffic
                FROM line_traffic_stats 
                WHERE line = ? AND timestamp >= ?
                """
                month_traffic = self.cur.execute(
                    month_traffic_query, (line, month_start.isoformat())
                ).fetchone()[0]

                # 获取当前线路流量排名前五的用户（基于本月数据）
                top_users_query = """
                SELECT username, SUM(send_bytes) as total_traffic
                FROM line_traffic_stats 
                WHERE line = ? AND timestamp >= ?
                GROUP BY username 
                ORDER BY total_traffic DESC 
                LIMIT 5
                """
                top_users_result = self.cur.execute(
                    top_users_query, (line, month_start.isoformat())
                ).fetchall()

                top_users = []
                for user_data in top_users_result:
                    username, traffic = user_data
                    top_users.append({"username": username, "traffic": traffic})

                line_stats.append(
                    {
                        "line": line,
                        "today_traffic": today_traffic,
                        "week_traffic": week_traffic,
                        "month_traffic": month_traffic,
                        "top_users": top_users,
                    }
                )

            return line_stats

        except Exception as e:
            logger.error(f"Error getting premium line traffic statistics: {e}")
            return []

    def get_user_daily_traffic(
        self,
        username: str,
        service: str = None,
        date: datetime = None,
        premium_only: bool = False,
    ):
        """获取用户指定日期的流量消耗，默认为今日

        Args:
            username: 用户名
            service: 服务类型 (plex/emby)
            date: 指定日期，默认为今日
            premium_only: 是否只统计 premium 线路流量，默认为 False
        """
        try:
            # 如果未指定日期，使用今日
            if date is None:
                date = datetime.now(settings.TZ)

            # 确保日期对象包含时区信息
            if date.tzinfo is None:
                date = date.replace(tzinfo=settings.TZ)
            else:
                date = date.astimezone(settings.TZ)

            # 计算指定日期的开始和结束时间
            day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = date.replace(hour=23, minute=59, second=59, microsecond=999999)

            # 构建查询条件
            base_conditions = "LOWER(username) = ? AND service = ? AND timestamp >= ? AND timestamp <= ?"
            params = [
                username.lower(),
                service,
                day_start.isoformat(),
                day_end.isoformat(),
            ]

            # 如果只统计 premium 线路
            if premium_only:
                premium_lines = settings.PREMIUM_STREAM_BACKEND
                if premium_lines:
                    # 构建线路过滤条件
                    line_conditions = " OR ".join(["line = ?" for _ in premium_lines])
                    base_conditions += f" AND ({line_conditions})"
                    params.extend(premium_lines)
                else:
                    # 如果没有配置 premium 线路，返回 0
                    return 0

            # 查询特定服务的指定日期流量
            query = f"""
            SELECT COALESCE(SUM(send_bytes), 0) as traffic
            FROM line_traffic_stats 
            WHERE {base_conditions}
            """
            result = self.cur.execute(query, params).fetchone()
            return result[0] if result else 0

        except Exception as e:
            logger.error(f"Error getting user daily traffic for {username}: {e}")
            return 0

    def get_traffic_statistics(self):
        """获取全面的流量统计信息，包括今日/本周/本月，按服务类型和线路分类"""
        try:
            now = datetime.now(settings.TZ)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today_start - timedelta(days=now.weekday())
            month_start = today_start.replace(day=1)

            # 获取所有服务类型的流量统计
            periods = [
                ("today", today_start.isoformat()),
                ("week", week_start.isoformat()),
                ("month", month_start.isoformat()),
            ]

            result = {}

            for period_name, start_time in periods:
                # 查询按服务类型分组的流量统计
                service_query = """
                SELECT 
                    service,
                    COALESCE(SUM(send_bytes), 0) as total_traffic
                FROM line_traffic_stats 
                WHERE timestamp >= ?
                GROUP BY service
                """
                service_results = self.cur.execute(
                    service_query, (start_time,)
                ).fetchall()

                # 查询按线路分组的流量统计
                line_query = """
                SELECT 
                    line,
                    COALESCE(SUM(send_bytes), 0) as total_traffic
                FROM line_traffic_stats 
                WHERE timestamp >= ?
                GROUP BY line
                ORDER BY total_traffic DESC
                """
                line_results = self.cur.execute(line_query, (start_time,)).fetchall()

                # 计算总流量
                total_query = """
                SELECT COALESCE(SUM(send_bytes), 0) as total_traffic
                FROM line_traffic_stats 
                WHERE timestamp >= ?
                """
                total_traffic = self.cur.execute(total_query, (start_time,)).fetchone()[
                    0
                ]

                # 构建期间数据
                period_data = {
                    "total": total_traffic,
                    "emby": 0,
                    "plex": 0,
                    "lines": [],
                }

                for service, traffic in service_results:
                    if service.lower() == "emby":
                        period_data["emby"] = traffic
                    elif service.lower() == "plex":
                        period_data["plex"] = traffic

                # 添加线路数据
                for line, traffic in line_results:
                    # 排除自定义线路
                    for _line in (
                        settings.STREAM_BACKEND + settings.PREMIUM_STREAM_BACKEND
                    ):
                        if line.lower() in _line.lower():
                            # 只统计已知的线路
                            period_data["lines"].append(
                                {"line": line, "traffic": traffic}
                            )
                            break

                result[period_name] = period_data

            return result

        except Exception as e:
            logger.error(f"Error getting comprehensive traffic statistics: {e}")
            return {
                "today": {"total": 0, "emby": 0, "plex": 0, "lines": []},
                "week": {"total": 0, "emby": 0, "plex": 0, "lines": []},
                "month": {"total": 0, "emby": 0, "plex": 0, "lines": []},
            }

    def get_plex_traffic_rank(self, start_date=None, end_date=None):
        """获取 Plex 流量排行榜

        Args:
            start_date: 开始日期 (datetime对象)，默认为今日开始
            end_date: 结束日期 (datetime对象)，默认为今日结束
        """
        try:
            # 使用北京时间
            now_beijing = datetime.now(settings.TZ)

            if start_date is None:
                # 默认为今日开始
                start_date = now_beijing.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            else:
                # 确保是当月的日期
                current_month_start = now_beijing.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
                if start_date < current_month_start:
                    start_date = current_month_start

            if end_date is None:
                # 默认为今日结束
                end_date = now_beijing.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            else:
                # 确保不超过今日
                today_end = now_beijing.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                if end_date > today_end:
                    end_date = today_end

            query = """
            SELECT u.plex_username, lts.user_id, SUM(lts.send_bytes) as total_traffic,
                   COALESCE(u.is_premium, 0) as is_premium,
                   u.tg_id
            FROM line_traffic_stats lts
            LEFT JOIN user u ON LOWER(lts.username) = LOWER(u.plex_username)
            WHERE lts.service = 'plex' 
                AND lts.timestamp >= ?
                AND lts.timestamp <= ?
                AND lts.username IS NOT NULL
                AND lts.username != ''
            GROUP BY LOWER(lts.username), lts.user_id, u.is_premium, u.tg_id
            ORDER BY total_traffic DESC
            LIMIT 50
            """

            result = self.cur.execute(
                query, (start_date.isoformat(), end_date.isoformat())
            ).fetchall()
            return result

        except Exception as e:
            logger.error(f"Error getting Plex traffic rank: {e}")
            return []

    def get_emby_traffic_rank(self, start_date=None, end_date=None):
        """获取 Emby 流量排行榜

        Args:
            start_date: 开始日期 (datetime对象)，默认为今日开始
            end_date: 结束日期 (datetime对象)，默认为今日结束
        """
        try:
            # 使用北京时间
            now_beijing = datetime.now(settings.TZ)

            if start_date is None:
                # 默认为今日开始
                start_date = now_beijing.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            else:
                # 确保是当月的日期
                current_month_start = now_beijing.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
                if start_date < current_month_start:
                    start_date = current_month_start

            if end_date is None:
                # 默认为今日结束
                end_date = now_beijing.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            else:
                # 确保不超过今日
                today_end = now_beijing.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
                if end_date > today_end:
                    end_date = today_end

            query = """
            SELECT eu.emby_username, lts.user_id, SUM(lts.send_bytes) as total_traffic,
                   COALESCE(eu.is_premium, 0) as is_premium,
                   eu.tg_id
            FROM line_traffic_stats lts
            LEFT JOIN emby_user eu ON LOWER(lts.username) = LOWER(eu.emby_username)
            WHERE lts.service = 'emby' 
                AND lts.timestamp >= ?
                AND lts.timestamp <= ?
                AND lts.username IS NOT NULL
                AND lts.username != ''
            GROUP BY LOWER(lts.username), lts.user_id, eu.is_premium, eu.tg_id
            ORDER BY total_traffic DESC
            LIMIT 50
            """

            result = self.cur.execute(
                query, (start_date.isoformat(), end_date.isoformat())
            ).fetchall()
            return result

        except Exception as e:
            logger.error(f"Error getting Emby traffic rank: {e}")
            return []
