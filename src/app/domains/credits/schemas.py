"""HTTP value schemas owned by the credits domain."""

from pydantic import BaseModel, Field


class CreditsTransferRequest(BaseModel):
    """积分转移请求模型"""

    target_tg_id: int = Field(..., description="目标用户的 Telegram ID")
    amount: float = Field(
        ..., gt=0, le=10000, description="转移积分数量，必须大于0且不超过10000"
    )
    note: str | None = Field(None, max_length=200, description="转移备注，可选")


class CreditsTransferResponse(BaseModel):
    """积分转移响应模型"""

    success: bool
    message: str
    transferred_amount: float | None = None
    fee_amount: float | None = None
    current_credits: float | None = None
