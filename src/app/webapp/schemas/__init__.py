"""
Web API 模型定义
"""

# ruff: noqa
from .auction import (
    AuctionItem,
    AuctionBid,
    CreateAuctionRequest,
    PlaceBidRequest,
    AuctionListResponse,
    AuctionDetailResponse,
    PlaceBidResponse,
    AuctionStatsResponse,
)
from .invitation import (
    GenerateInviteCodeResponse,
    InvitePointsResponse,
    RedeemInviteCodeRequest,
    RedeemResponse,
    CheckPrivilegedCodeRequest,
    CheckPrivilegedCodeResponse,
    RedeemForCreditsRequest,
    RedeemForCreditsResponse,
)
from .ranking import RankingInfo
from .user import (
    AllLineTagsResponse,
    AuthBindLineRequest,
    BaseResponse,
    BindEmbyRequest,
    BindPlexRequest,
    CreditsTransferRequest,
    CreditsTransferResponse,
    CurrentLineResponse,
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
