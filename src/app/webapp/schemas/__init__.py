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
from .crypto_donation import (
    CryptoType,
    CryptoDonationOrderStatus,
    CryptoDonationOrderCreate,
    CryptoDonationOrderResponse,
    CryptoDonationOrderCreateResponse,
    CryptoDonationOrderListResponse,
    UPayCreateOrderRequest,
    UPayCreateOrderResponse,
    UPayCallbackData,
)
from .invitation import (
    GenerateInviteCodeResponse,
    InvitePointsResponse,
    RedeemInviteCodeRequest,
    RedeemResponse,
    CheckPrivilegedCodeRequest,
    CheckPrivilegedCodeResponse,
    BatchCheckPrivilegedCodesRequest,
    BatchCheckPrivilegedCodesResponse,
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
