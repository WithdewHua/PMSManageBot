from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class TreasureIssueItem(BaseModel):
    id: int
    title: str
    prize_credits: int
    total_credits_required: int
    credits_per_share: int
    total_shares: int
    start_number: int
    shares_sold: int
    status: int
    winner_number: Optional[int] = None
    winner_tg_id: Optional[int] = None
    created_at: datetime


class TreasureIssueListResponse(BaseModel):
    issues: List[TreasureIssueItem]
    total: int


class TreasureIssueDetailResponse(BaseModel):
    issue: TreasureIssueItem
    description: Optional[str] = None
    external_random_b: Optional[int] = None
    settled_at: Optional[int] = None


class TreasureParticipationItem(BaseModel):
    id: int
    issue_id: int
    issue_seq: int
    tg_id: int
    tg_username: Optional[str] = None
    lucky_number: int
    cost_credits: int
    created_at_ms: int
    created_at: datetime


class TreasureParticipationListResponse(BaseModel):
    participations: List[TreasureParticipationItem]
    total: int


class TreasureCreateIssueRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    prize_credits: int = Field(..., gt=0)
    total_credits_required: int = Field(..., gt=0)
    credits_per_share: int = Field(10, gt=0)
    start_number: Optional[int] = Field(None, gt=0)


class TreasureJoinRequest(BaseModel):
    quantity: int = Field(1, ge=1, le=100, description="一次购买份数")


class TreasureJoinResponse(BaseModel):
    success: bool
    message: str
    participation: Optional[dict] = None
    participations: Optional[List[dict]] = None
    issue: Optional[dict] = None
    settled: bool = False
    winner_number: Optional[int] = None
    winner_tg_id: Optional[int] = None
