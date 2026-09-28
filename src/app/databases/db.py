"""
ORM-based database operations using SQLAlchemy
"""

from app.domains.badges.repository import BadgesRepository
from app.domains.crypto_donation.repository import CryptoDonationRepository
from app.domains.donation.repository import DonationRepository
from app.domains.identity.repository import IdentityRepository
from app.domains.invitation.repository import InvitationRepository
from app.domains.lines.repository import LinesRepository
from app.domains.media_access.repository import MediaAccessRepository
from app.domains.premium.repository import PremiumRepository
from app.domains.rankings.repository import RankingsRepository
from app.domains.reports.repository import ReportsRepository
from app.domains.tg_rebind.repository import TgRebindRepository
from app.domains.traffic.repository import TrafficRepository
from app.domains.watch_rewards.repository import WatchRewardsRepository


class DatabaseORM(
    IdentityRepository,
    ReportsRepository,
    PremiumRepository,
    DonationRepository,
    InvitationRepository,
    TgRebindRepository,
    MediaAccessRepository,
    RankingsRepository,
    LinesRepository,
    TrafficRepository,
    CryptoDonationRepository,
    BadgesRepository,
    WatchRewardsRepository,
):
    """
    基于 ORM 的数据库操作类
    """


# 创建全局实例
db = DatabaseORM()

__all__ = ["DatabaseORM", "db"]
