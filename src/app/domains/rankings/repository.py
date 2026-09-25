from sqlalchemy import case, func, select
from sqlalchemy.orm import joinedload

from app.core.db import get_session
from app.core.log import logger
from app.domains.badges.models import UserBadge
from app.domains.blackjack.models import BlackjackHand
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.invitation.models import Invitation
from app.domains.luckywheel.models import WheelStats
from app.domains.treasure.models import TreasureIssue


class RankingsRepository:
    def get_credits_rank(self) -> list:
        """获取积分排行"""
        with get_session() as session:
            stmt = select(Statistics.tg_id, Statistics.credits).order_by(
                Statistics.credits.desc()
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1]) for r in results]

    def get_donation_rank(self) -> list:
        """获取捐赠排行"""
        with get_session() as session:
            stmt = select(Statistics.tg_id, Statistics.donation).order_by(
                Statistics.donation.desc()
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1]) for r in results]

    def get_plex_watched_time_rank(self) -> list:
        """获取 Plex 观看时长排行"""
        with get_session() as session:
            stmt = select(
                PlexUser.plex_id,
                PlexUser.tg_id,
                PlexUser.plex_username,
                PlexUser.watched_time,
                PlexUser.is_premium,
            ).order_by(PlexUser.watched_time.desc())
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

    def get_emby_watched_time_rank(self) -> list:
        """获取 Emby 观看时长排行"""
        with get_session() as session:
            stmt = select(
                EmbyUser.emby_id,
                EmbyUser.emby_username,
                EmbyUser.emby_watched_time,
                EmbyUser.is_premium,
                EmbyUser.tg_id,
            ).order_by(EmbyUser.emby_watched_time.desc())
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1], r[2], r[3], r[4]) for r in results]

    def get_invitation_rank(self) -> list:
        """获取邀请排行榜数据"""
        with get_session() as session:
            stmt = (
                select(
                    Invitation.owner,
                    func.count(func.distinct(Invitation.used_by)).label("invite_count"),
                )
                .where(Invitation.is_used == 1, Invitation.used_by.isnot(None))
                .group_by(Invitation.owner)
                .order_by(func.count(func.distinct(Invitation.used_by)).desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], r[1]) for r in results]

    def get_wheel_credits_rank(self) -> list:
        """获取幸运大转盘积分变动排行榜（统计所有游戏结果）"""
        with get_session() as session:
            total_credits_change = func.sum(WheelStats.credits_change).label(
                "total_credits_change"
            )
            play_count = func.count(WheelStats.id).label("play_count")
            stmt = (
                select(WheelStats.tg_id, total_credits_change, play_count)
                .group_by(WheelStats.tg_id)
                .order_by(total_credits_change.desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], float(r[1] or 0), int(r[2] or 0)) for r in results]

    def get_wheel_invite_code_rank(self) -> list:
        """获取幸运大转盘邀请码获得排行榜"""
        with get_session() as session:
            invite_count = func.count(WheelStats.id).label("invite_count")
            stmt = (
                select(WheelStats.tg_id, invite_count)
                .where(WheelStats.item_name == "邀请码 1 枚")
                .group_by(WheelStats.tg_id)
                .order_by(invite_count.desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], int(r[1] or 0)) for r in results if int(r[1] or 0) > 0]

    def _blackjack_rank_rows(self, session, min_hands: int) -> list:
        """一次扫描算出准确率榜与胜率榜共用的聚合。

        两个榜单的口径只差排序字段，分开查会对同一张表做两次全表扫描。

        胜率的分母是**已结束的手数**，分子是判为玩家胜的手数（含天胡胜）；平局
        既不计胜也不计负，但仍计入分母——它确实消耗了一手。投降同一待遇：
        `"surrender"` 不在 `win_flag` 里故不计入分子，其 status 是已结算故自动
        计入分母与手数门槛，本方法因此无需为投降加任何分支。

        **只统计现金局手牌**（`tournament_id IS NULL`）：锦标赛以名次而非单手
        期望为目标，落后者在末几手会做出单手期望为负但对名次正确的选择，按基本
        策略评判会惩罚打得对的人；赛内手数计入门槛也会让只打锦标赛的用户挤进
        技巧榜。赛内手牌的决策计数恒为 0，是漏掉本过滤时的第二层防御。
        """
        from app.domains.blackjack import rules as engine

        win_flag = case(
            (
                BlackjackHand.outcome.in_(
                    [engine.OUTCOME_WIN, engine.OUTCOME_BLACKJACK]
                ),
                1,
            ),
            else_=0,
        )
        hand_count = func.count(BlackjackHand.id).label("hand_count")
        wins = func.sum(win_flag).label("wins")
        dec_total = func.sum(BlackjackHand.decisions_total).label("dec_total")
        dec_correct = func.sum(BlackjackHand.decisions_correct).label("dec_correct")

        stmt = (
            select(BlackjackHand.tg_id, hand_count, wins, dec_total, dec_correct)
            .where(
                BlackjackHand.status.in_(engine.TERMINAL_STATUSES),
                BlackjackHand.tournament_id.is_(None),
            )
            .group_by(BlackjackHand.tg_id)
            .having(func.count(BlackjackHand.id) >= int(min_hands))
        )
        rows = []
        for r in session.execute(stmt).all():
            hands = int(r[1] or 0)
            dt = int(r[3] or 0)
            rows.append(
                {
                    "tg_id": r[0],
                    "hand_count": hands,
                    "win_rate": round(float(r[2] or 0) / hands * 100, 2)
                    if hands
                    else 0.0,
                    "decisions_total": dt,
                    "accuracy": round(float(r[4] or 0) / dt * 100, 2) if dt else 0.0,
                }
            )
        return rows

    def get_blackjack_skill_ranks(self, min_hands: int | None = None) -> dict:
        """一次扫描同时算出准确率榜与胜率榜，返回 `{accuracy, win_rate}`。

        榜单接口两个榜都要，分别调用 `get_blackjack_accuracy_rank()` 与
        `get_blackjack_win_rate_rank()` 会各开一个 session、各跑一遍同样的
        GROUP BY 全表聚合，还会各读一次配置——正是 `_blackjack_rank_rows`
        当初想避免的两次扫描。故路由层应当调用本方法。
        """
        if min_hands is None:
            min_hands = int(self.get_blackjack_config_dict().get("rank_min_hands", 100))
        try:
            with get_session() as session:
                rows = self._blackjack_rank_rows(session, min_hands)
            return {
                # 没做过任何决策的用户（全是开局天胡）不入准确率榜
                "accuracy": sorted(
                    [r for r in rows if r["decisions_total"] > 0],
                    key=lambda r: r["accuracy"],
                    reverse=True,
                ),
                "win_rate": sorted(rows, key=lambda r: r["win_rate"], reverse=True),
            }
        except Exception as e:
            logger.error(f"获取 21 点技巧类排行失败: {e}")
            return {"accuracy": [], "win_rate": []}

    def get_blackjack_accuracy_rank(self, min_hands: int | None = None) -> list:
        """决策准确率排行榜——21 点游戏榜的主榜。

        准确率是本游戏里唯一**零方差**的口径：同一局面的基本策略建议恒定，故它
        纯粹反映技巧，不受运气影响。这正是它取代净积分变动榜作为主榜的原因。

        设最低手数门槛，样本量不足的用户不入榜。同时需要两个榜时改用
        `get_blackjack_skill_ranks()`，避免重复扫描。

        Returns: [{tg_id, accuracy, win_rate, hand_count, decisions_total}, ...] 按准确率降序
        """
        return self.get_blackjack_skill_ranks(min_hands)["accuracy"]

    def get_blackjack_win_rate_rank(self, min_hands: int | None = None) -> list:
        """胜率排行榜。按量归一化，故不奖励刷量；设最低手数门槛。

        同时需要两个榜时改用 `get_blackjack_skill_ranks()`，避免重复扫描。

        Returns: [{tg_id, win_rate, accuracy, hand_count}, ...] 按胜率降序
        """
        return self.get_blackjack_skill_ranks(min_hands)["win_rate"]

    def get_blackjack_max_win_rank(self) -> list:
        """获取 21 点单手最大赢利排行榜

        单手净赢利 = payout − 该手总押注。**不含奖池派彩**——并入的话这个榜会
        退化成奖池中奖者名单，失去「谁打出过最漂亮的一手」的意义。

        只统计已结束的手牌，且只保留净赢利为正的用户。本榜不设手数门槛：它是
        高光时刻展示而非技术排名，一手也可以上榜。

        **只统计现金局手牌**（`tournament_id IS NULL`）：赛内筹码不是积分，
        把它与积分赢利并列排名没有意义。

        Returns: [(tg_id, max_win, hand_count), ...] 按单手最大赢利降序
        """
        from app.domains.blackjack import rules as engine

        with get_session() as session:
            total_stake = case(
                (BlackjackHand.doubled == 1, BlackjackHand.bet_credits * 2),
                else_=BlackjackHand.bet_credits,
            )
            max_win = func.max(
                func.coalesce(BlackjackHand.payout_credits, 0) - total_stake
            ).label("max_win")
            hand_count = func.count(BlackjackHand.id).label("hand_count")
            stmt = (
                select(BlackjackHand.tg_id, max_win, hand_count)
                .where(
                    BlackjackHand.status.in_(engine.TERMINAL_STATUSES),
                    BlackjackHand.tournament_id.is_(None),
                )
                .group_by(BlackjackHand.tg_id)
                .order_by(max_win.desc())
            )
            results = session.execute(stmt).fetchall()
            return [
                (r[0], round(float(r[1] or 0), 2), int(r[2] or 0))
                for r in results
                if float(r[1] or 0) > 0
            ]

    def get_treasure_win_issue_rank(self) -> list:
        """获取夺宝奇兵中奖期数排行榜"""
        with get_session() as session:
            win_count = func.count(TreasureIssue.id).label("win_count")
            stmt = (
                select(TreasureIssue.winner_tg_id, win_count)
                .where(
                    TreasureIssue.status == 2,
                    TreasureIssue.winner_tg_id.isnot(None),
                )
                .group_by(TreasureIssue.winner_tg_id)
                .order_by(win_count.desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], int(r[1] or 0)) for r in results if int(r[1] or 0) > 0]

    def get_treasure_win_credits_rank(self) -> list:
        """获取夺宝奇兵中奖积分排行榜"""
        with get_session() as session:
            win_credits = func.sum(TreasureIssue.prize_credits).label("win_credits")
            stmt = (
                select(TreasureIssue.winner_tg_id, win_credits)
                .where(
                    TreasureIssue.status == 2,
                    TreasureIssue.winner_tg_id.isnot(None),
                )
                .group_by(TreasureIssue.winner_tg_id)
                .order_by(win_credits.desc())
            )
            results = session.execute(stmt).fetchall()
            return [(r[0], int(r[1] or 0)) for r in results if int(r[1] or 0) > 0]

    def get_badge_rank(self) -> list[dict]:
        """
        获取勋章排行榜数据（按用户拥有的勋章数量排序）

        Returns:
            用户勋章排行数据列表，包含 tg_id, badge_count, badges 信息
        """
        try:
            with get_session() as session:
                # 查询每个用户拥有的勋章数量，并获取勋章详情
                stmt = (
                    select(
                        UserBadge.tg_id,
                        func.count(UserBadge.id).label("badge_count"),
                    )
                    .where(UserBadge.is_active == 1)
                    .group_by(UserBadge.tg_id)
                    .order_by(func.count(UserBadge.id).desc())
                )
                results = session.execute(stmt).fetchall()

                rank_data = []
                for row in results:
                    tg_id = row[0]
                    badge_count = row[1]

                    # 获取该用户的所有勋章详情
                    badges_stmt = (
                        select(UserBadge)
                        .options(joinedload(UserBadge.badge))
                        .where(UserBadge.tg_id == tg_id, UserBadge.is_active == 1)
                        .order_by(UserBadge.redeemed_at.desc())
                    )
                    user_badges = session.execute(badges_stmt).scalars().unique().all()

                    rank_data.append(
                        {
                            "tg_id": tg_id,
                            "badge_count": badge_count,
                            "badges": [
                                self._user_badge_to_dict(ub) for ub in user_badges
                            ],
                        }
                    )

                return rank_data
        except Exception as e:
            logger.error(f"获取勋章排行榜失败: {e}")
            return []
