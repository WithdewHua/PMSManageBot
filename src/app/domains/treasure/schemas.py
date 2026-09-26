from datetime import datetime

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
    winner_number: int | None = None
    winner_tg_id: int | None = None
    created_at: datetime


class TreasureIssueListResponse(BaseModel):
    issues: list[TreasureIssueItem]
    total: int


class TreasureIssueDetailResponse(BaseModel):
    issue: TreasureIssueItem
    description: str | None = None
    external_random_b: int | None = None
    settled_at: int | None = None


class TreasureParticipationItem(BaseModel):
    id: int
    issue_id: int
    issue_seq: int
    tg_id: int
    tg_username: str | None = None
    lucky_number: int
    cost_credits: int
    created_at_ms: int
    created_at: datetime


class TreasureParticipationListResponse(BaseModel):
    participations: list[TreasureParticipationItem]
    total: int


class TreasureCreateIssueRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    prize_credits: int = Field(..., gt=0)
    total_credits_required: int = Field(..., gt=0)
    credits_per_share: int = Field(10, gt=0)
    start_number: int | None = Field(None, gt=0)


class TreasureJoinRequest(BaseModel):
    quantity: int = Field(1, ge=1, le=100, description="一次购买份数")


class TreasureJoinResponse(BaseModel):
    success: bool
    message: str
    participation: dict | None = None
    participations: list[dict] | None = None
    issue: dict | None = None
    settled: bool = False
    winner_number: int | None = None
    winner_tg_id: int | None = None
