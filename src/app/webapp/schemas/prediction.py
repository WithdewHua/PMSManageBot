from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PredictionMarketItem(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    status: int
    result_option: Optional[int] = None
    betting_deadline: Optional[int] = None
    real_yes_pool: int
    real_no_pool: int
    virtual_yes_pool: int
    virtual_no_pool: int
    yes_odds: float
    no_odds: float
    max_bet_per_user: int
    created_at: datetime


class PredictionMarketListResponse(BaseModel):
    markets: list[PredictionMarketItem]
    total: int


class PredictionMarketDetailResponse(BaseModel):
    market: PredictionMarketItem
    my_yes_amount: int = 0
    my_no_amount: int = 0
    fee_rate_bp: int
    fee_burn_bp: int
    fee_glory_bp: int
    resolution_note: Optional[str] = None
    total_fee_collected: int
    fee_burned: int
    fee_to_glory: int


class PredictionBetItem(BaseModel):
    id: int
    market_id: int
    tg_id: int
    tg_username: Optional[str] = None
    option: int
    amount: int
    created_at: datetime


class PredictionBetListResponse(BaseModel):
    bets: list[PredictionBetItem]
    total: int


class PredictionCreateMarketRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    betting_deadline: int = Field(..., description="押注截止时间（Unix秒时间戳）")
    virtual_yes_pool: int = Field(500, ge=0)
    virtual_no_pool: int = Field(500, ge=0)
    max_bet_per_user: int = Field(500, gt=0)


class PredictionBetRequest(BaseModel):
    option: int = Field(..., ge=0, le=1, description="1=YES, 0=NO")
    amount: int = Field(..., gt=0, le=500)


class PredictionResolveRequest(BaseModel):
    result_option: int = Field(..., ge=0, le=1)
    resolution_note: Optional[str] = Field(None, max_length=2000)
