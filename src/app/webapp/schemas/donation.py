from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, validator


class PaymentMethod(str, Enum):
    """支付方式枚举"""

    WECHAT = "wechat"
    ALIPAY = "alipay"
    BANK = "bank"
    OTHER = "other"


class DonationRegistrationStatus(str, Enum):
    """捐赠登记状态枚举"""

    PENDING = "pending"  # 待处理
    APPROVED = "approved"  # 已批准
    REJECTED = "rejected"  # 已拒绝


class DonationRegistrationCreate(BaseModel):
    """创建捐赠登记请求"""

    payment_method: PaymentMethod = Field(..., description="支付方式")
    amount: float = Field(..., gt=0, description="捐赠金额，必须大于0")
    note: Optional[str] = Field(None, max_length=200, description="备注信息")
    is_donation_registration: bool = Field(
        False,
        description="是否为捐赠开号，True表示只记录捐赠金额，不增加积分，并生成邀请码",
    )

    @validator("amount")
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("捐赠金额必须大于0")
        if v > 999999:
            raise ValueError("捐赠金额过大")
        # 限制小数位数到2位
        return round(v, 2)


class DonationRegistrationUpdate(BaseModel):
    """更新捐赠登记请求"""

    approved: bool = Field(..., description="是否批准")
    admin_note: Optional[str] = Field(None, max_length=500, description="管理员备注")


class DonationRegistrationResponse(BaseModel):
    """捐赠登记响应"""

    id: int
    user_id: int
    payment_method: PaymentMethod
    amount: float
    note: Optional[str]
    status: DonationRegistrationStatus
    admin_note: Optional[str]
    created_at: datetime
    processed_at: Optional[datetime]
    processed_by: Optional[int]
    is_donation_registration: bool = False
    username: Optional[str]  # 用户名（从 tg_id 获取）
    processed_by_username: Optional[str]

    class Config:
        from_attributes = True


class DonationRegistrationListResponse(BaseModel):
    """捐赠登记列表响应"""

    success: bool = True
    data: list[DonationRegistrationResponse]
    total: int
    page: int = 1
    per_page: int = 20


class DonationRegistrationDetailResponse(BaseModel):
    """捐赠登记详情响应"""

    success: bool = True
    data: DonationRegistrationResponse


class DonationRegistrationCreateResponse(BaseModel):
    """创建捐赠登记响应"""

    success: bool = True
    message: str = "捐赠登记提交成功"
    data: DonationRegistrationResponse


class DonationRegistrationConfirmResponse(BaseModel):
    """确认捐赠登记响应"""

    success: bool = True
    message: str
    data: DonationRegistrationResponse
