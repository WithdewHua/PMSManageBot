from typing import Optional

from pydantic import BaseModel, EmailStr


class VaultwardenRedeemInfoResponse(BaseModel):
    """Vaultwarden 兑换信息响应模型"""

    enabled: bool  # 是否启用 Vaultwarden 兑换功能
    required_credits: int  # 兑换所需积分
    current_credits: float  # 当前用户积分
    can_redeem: bool  # 是否可以兑换
    error_message: Optional[str] = None  # 错误信息


class VaultwardenRedeemRequest(BaseModel):
    """Vaultwarden 兑换请求模型"""

    email: EmailStr  # 注册邮箱


class VaultwardenRedeemResponse(BaseModel):
    """Vaultwarden 兑换响应模型"""

    success: bool
    message: str
    credits_deducted: Optional[float] = None  # 扣除的积分
    remaining_credits: Optional[float] = None  # 剩余积分
