"""
Web API 模型定义
"""

from .invitation import GenerateInviteCodeResponse, InvitePointsResponse
from .ranking import RankingInfo
from .user import TelegramUser, UserInfo

__all__ = [
    # 邀请码相关模型
    "InvitePointsResponse",
    "GenerateInviteCodeResponse",
    # 用户相关模型
    "TelegramUser",
    "UserInfo",
    # 排行榜相关模型
    "RankingInfo",
]
