"""
Web API 模型定义
"""

from .invitation import (
    GenerateInviteCodeResponse,
    InvitePointsResponse,
    RedeemInviteCodeRequest,
    RedeemResponse,
)
from .ranking import RankingInfo
from .user import (
    BaseResponse,
    BindEmbyRequest,
    BindPlexRequest,
    EmbyLineRequest,
    EmbyLinesResponse,
    TelegramUser,
    UserInfo,
)

__all__ = [
    # 邀请码相关模型
    "InvitePointsResponse",
    "GenerateInviteCodeResponse",
    "RedeemInviteCodeRequest",
    "RedeemResponse",
    # 用户相关模型
    "TelegramUser",
    "UserInfo",
    "BaseResponse",
    "BindPlexRequest",
    "BindEmbyRequest",
    "EmbyLineRequest",
    "EmbyLinesResponse",
    # 排行榜相关模型
    "RankingInfo",
]
