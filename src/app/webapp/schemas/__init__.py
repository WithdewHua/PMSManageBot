"""
Web API 模型定义
"""

# ruff: noqa
from .invitation import (
    GenerateInviteCodeResponse,
    InvitePointsResponse,
    RedeemInviteCodeRequest,
    RedeemResponse,
)
from .ranking import RankingInfo
from .user import (
    AllLineTagsResponse,
    BaseResponse,
    BindEmbyRequest,
    BindPlexRequest,
    EmbyLineInfo,
    PlexLineInfo,
    PlexLineRequest,
    PlexLinesResponse,
    EmbyLineRequest,
    EmbyLinesResponse,
    LineTagRequest,
    LineTagResponse,
    TelegramUser,
    UserInfo,
)
