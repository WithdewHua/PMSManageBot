from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class AuctionItem(BaseModel):
    """竞拍物品"""

    id: Optional[int] = Field(None, description="竞拍ID")
    title: str = Field(..., min_length=1, max_length=100, description="竞拍标题")
    description: str = Field(..., min_length=1, max_length=500, description="竞拍描述")
    starting_price: float = Field(..., gt=0, description="起始价格")
    current_price: float = Field(..., gt=0, description="当前价格")
    end_time: datetime = Field(..., description="竞拍结束时间")
    created_by: int = Field(..., description="创建者TG ID")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    is_active: bool = Field(True, description="是否激活")
    winner_id: Optional[int] = Field(None, description="获胜者TG ID")
    bid_count: int = Field(0, description="竞拍次数")
    status: Optional[str] = Field(None, description="竞拍状态")


class AuctionBid(BaseModel):
    """竞拍出价"""

    id: Optional[int] = Field(None, description="出价ID")
    auction_id: int = Field(..., description="竞拍ID")
    bidder_id: int = Field(..., description="出价者TG ID")
    bid_amount: float = Field(..., gt=0, description="出价金额")
    bid_time: Optional[datetime] = Field(None, description="出价时间")


class CreateAuctionRequest(BaseModel):
    """创建竞拍请求"""

    title: str = Field(..., min_length=1, max_length=100, description="竞拍标题")
    description: str = Field(..., min_length=1, max_length=500, description="竞拍描述")
    starting_price: float = Field(..., gt=0, le=10000, description="起始价格")
    duration_hours: int = Field(..., ge=1, le=168, description="竞拍持续时间(小时)")


class PlaceBidRequest(BaseModel):
    """出价请求"""

    auction_id: int = Field(..., description="竞拍ID")
    bid_amount: float = Field(..., gt=0, description="出价金额")


class AuctionListResponse(BaseModel):
    """竞拍列表响应"""

    auctions: List[AuctionItem]
    total: int


class AuctionDetailResponse(BaseModel):
    """竞拍详情响应"""

    auction: AuctionItem
    recent_bids: List[AuctionBid]
    user_can_bid: bool
    user_highest_bid: Optional[float] = None


class PlaceBidResponse(BaseModel):
    """出价响应"""

    success: bool
    message: str
    current_price: Optional[float] = None
    user_credits: Optional[float] = None


class AuctionStatsResponse(BaseModel):
    """竞拍统计响应"""

    total_auctions: int
    active_auctions: int
    total_bids: int
    total_value: float
