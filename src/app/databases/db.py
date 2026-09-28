"""
ORM-based database operations using SQLAlchemy
"""

from app.core.kv import SystemConfigRepository
from app.domains.auction.repository import AuctionRepository
from app.domains.badges.repository import BadgesRepository
from app.domains.crypto_donation.repository import CryptoDonationRepository
from app.domains.donation.repository import DonationRepository
from app.domains.identity.repository import IdentityRepository
from app.domains.invitation.repository import InvitationRepository
from app.domains.lines.repository import LinesRepository
from app.domains.luckywheel.repository import LuckywheelRepository
from app.domains.media_access.repository import MediaAccessRepository
from app.domains.prediction.repository import PredictionRepository
from app.domains.premium.repository import PremiumRepository
from app.domains.rankings.repository import RankingsRepository
from app.domains.reports.repository import ReportsRepository
from app.domains.tg_rebind.repository import TgRebindRepository
from app.domains.traffic.repository import TrafficRepository
from app.domains.treasure.repository import TreasureRepository
from app.domains.watch_rewards.repository import WatchRewardsRepository


class DatabaseORM(
    IdentityRepository,
    ReportsRepository,
    PremiumRepository,
    DonationRepository,
    InvitationRepository,
    TgRebindRepository,
    MediaAccessRepository,
    TreasureRepository,
    PredictionRepository,
    RankingsRepository,
    LinesRepository,
    LuckywheelRepository,
    AuctionRepository,
    TrafficRepository,
    CryptoDonationRepository,
    SystemConfigRepository,
    BadgesRepository,
    WatchRewardsRepository,
):
    """
    基于 ORM 的数据库操作类
    """


# 创建全局实例
db = DatabaseORM()

__all__ = ["DatabaseORM", "db"]
