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
    CryptoTypesResponse,
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
from .gift_pack import (
    CreditsReward,
    PremiumDaysReward,
    GiftPackEligibility,
    GiftPackCreateRequest,
    GiftPackUpdateRequest,
    GiftPackSetEnabledRequest,
    GiftPackRewardView,
    GiftPackItem,
    GiftPackListResponse,
    GiftPackPromptItem,
    GiftPackPromptCheckResponse,
    GiftPackClaimRewardResult,
    GiftPackClaimResponse,
    GiftPackAdminItem,
    GiftPackAdminListResponse,
    GiftPackStatsResponse,
    GiftPackClaimRecordItem,
    GiftPackClaimRecordListResponse,
)
from .ranking import RankingInfo
from .user import (
    AdminCustomLineUpdateRequest,
    AllLineTagsResponse,
    AuthBindLineRequest,
    BaseResponse,
    BindEmbyRequest,
    BindPlexRequest,
    CreditsTransferRequest,
    CreditsTransferResponse,
    CurrentLineResponse,
    CustomLineApproveRequest,
    CustomLineDetailResponse,
    CustomLineInfo,
    CustomLineListResponse,
    CustomLineOnlineRequest,
    CustomLineRenewRequest,
    CustomLineSubmitRequest,
    CustomLineUpdateRequest,
    EmbyLineInfo,
    PlexLineInfo,
    PlexLineRequest,
    PlexLinesResponse,
    EmbyLineRequest,
    EmbyLinesResponse,
    LineScheduleCreate,
    LineScheduleInfo,
    LineScheduleListResponse,
    LineScheduleStatusResponse,
    LineScheduleUnlockRequest,
    LineScheduleUnlockResponse,
    LineScheduleUpdate,
    LineTagRequest,
    LineTagResponse,
    TelegramUser,
    UserInfo,
)
from .vaultwarden import (
    VaultwardenRedeemInfoResponse,
    VaultwardenRedeemRequest,
    VaultwardenRedeemResponse,
)
from .prediction import *
from .treasure import *
