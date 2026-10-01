"""
ORM-based database operations using SQLAlchemy
"""

from app.domains.identity.compat import IdentityRepository
from app.domains.invitation.repository import InvitationRepository
from app.domains.lines.compat import LinesCompat
from app.domains.media_access.compat import MediaAccessCompat
from app.domains.premium.compat import PremiumCompat
from app.domains.traffic.compat import TrafficCompat
from app.domains.watch_rewards.repository import WatchRewardsRepository


class DatabaseORM(
    IdentityRepository,
    PremiumCompat,
    InvitationRepository,
    MediaAccessCompat,
    LinesCompat,
    TrafficCompat,
    WatchRewardsRepository,
):
    """
    基于 ORM 的数据库操作类
    """


# 创建全局实例
db = DatabaseORM()

__all__ = ["DatabaseORM", "db"]
