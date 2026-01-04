from typing import List, Optional

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

    pass


class BadgeUpdate(BaseModel):
    """更新勋章请求模型"""

    name: Optional[str] = None
    description: Optional[str] = None
    icon_url: Optional[str] = None
    credits_cost: Optional[float] = Field(None, ge=0)
    bonus_percentage: Optional[float] = Field(None, ge=0, le=1)
    valid_days: Optional[int] = Field(None, gt=0)
    is_enabled: Optional[int] = None


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
    badge: Optional[BadgeResponse] = None

    class Config:
        from_attributes = True


class BadgeRedeemRequest(BaseModel):
    """勋章兑换请求模型"""

    badge_id: int = Field(..., description="要兑换的勋章ID")


class BadgeRedeemResponse(BaseModel):
    """勋章兑换响应模型"""

    success: bool
    message: str
    user_badge: Optional[UserBadgeResponse] = None
    credits_deducted: Optional[float] = None
    remaining_credits: Optional[float] = None


class BadgeListResponse(BaseModel):
    """勋章列表响应模型"""

    badges: List[BadgeResponse]
    user_credits: float
    user_badges: List[UserBadgeResponse]


class BadgeCenterConfigResponse(BaseModel):
    """勋章中心配置响应模型"""

    enabled: bool  # 是否启用勋章中心
    message: Optional[str] = None  # 提示信息


class BadgeCenterConfigUpdate(BaseModel):
    """勋章中心配置更新请求模型"""

    enabled: bool = Field(..., description="是否启用勋章中心")
    message: Optional[str] = Field(None, description="提示信息")
