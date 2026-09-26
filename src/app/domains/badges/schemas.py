from pydantic import BaseModel, Field


class BadgeBase(BaseModel):
    """勋章基础模型"""

    badge_type: str = Field(..., description="勋章类型，如 anniversary_4")
    name: str = Field(..., description="勋章名称")
    description: str = Field(..., description="勋章描述")
    icon_url: str = Field(..., description="勋章图标URL或SVG路径")
    credits_cost: float = Field(..., ge=0, description="兑换所需积分")
    bonus_percentage: float = Field(
        ..., ge=0, le=1, description="每日积分加成百分比，如 0.18 表示 18%"
    )
    valid_days: int = Field(..., gt=0, description="有效天数")
    is_enabled: int = Field(..., description="是否启用，1=启用，0=禁用")


class BadgeCreate(BadgeBase):
    """创建勋章请求模型"""


class BadgeUpdate(BaseModel):
    """更新勋章请求模型"""

    name: str | None = None
    description: str | None = None
    icon_url: str | None = None
    credits_cost: float | None = Field(None, ge=0)
    bonus_percentage: float | None = Field(None, ge=0, le=1)
    valid_days: int | None = Field(None, gt=0)
    is_enabled: int | None = None


class BadgeResponse(BadgeBase):
    """勋章响应模型"""

    id: int
    created_at: int
    updated_at: int

    class Config:
        from_attributes = True


class UserBadgeBase(BaseModel):
    """用户勋章基础模型"""

    tg_id: int
    badge_id: int
    credits_cost: float = Field(..., ge=0)
    redeemed_at: int
    expires_at: int
    is_active: int
    bonus_active: bool = Field(..., description="积分加成是否有效")


class UserBadgeResponse(UserBadgeBase):
    """用户勋章响应模型"""

    id: int
    badge: BadgeResponse | None = None

    class Config:
        from_attributes = True


class BadgeRedeemRequest(BaseModel):
    """勋章兑换请求模型"""

    badge_id: int = Field(..., description="要兑换的勋章ID")


class BadgeRedeemResponse(BaseModel):
    """勋章兑换响应模型"""

    success: bool
    message: str
    user_badge: UserBadgeResponse | None = None
    credits_deducted: float | None = None
    remaining_credits: float | None = None


class BadgeListResponse(BaseModel):
    """勋章列表响应模型"""

    badges: list[BadgeResponse]
    user_credits: float
    user_badges: list[UserBadgeResponse]


class BadgeCenterConfigResponse(BaseModel):
    """勋章中心配置响应模型"""

    enabled: bool  # 是否启用勋章中心
    message: str | None = None  # 提示信息


class BadgeCenterConfigUpdate(BaseModel):
    """勋章中心配置更新请求模型"""

    enabled: bool = Field(..., description="是否启用勋章中心")
    message: str | None = Field(None, description="提示信息")
