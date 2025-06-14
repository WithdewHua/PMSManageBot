from typing import Optional

from pydantic import BaseModel


class InvitePointsResponse(BaseModel):
    """邀请码积分信息响应模型"""

    required_points: int
    current_points: float
    can_generate: bool
    error_message: Optional[str] = None


class GenerateInviteCodeResponse(BaseModel):
    """生成邀请码响应模型"""

    success: bool
    message: str
    code: Optional[str] = None


class RedeemInviteCodeRequest(BaseModel):
    """兑换邀请码请求模型"""

    code: str
    email: Optional[str] = None  # Plex 使用
    username: Optional[str] = None  # Emby 使用


class RedeemResponse(BaseModel):
    """兑换邀请码响应模型"""

    success: bool
    message: str


class CheckPrivilegedCodeRequest(BaseModel):
    """检查特权邀请码请求模型"""

    code: str


class CheckPrivilegedCodeResponse(BaseModel):
    """检查特权邀请码响应模型"""

    privileged: bool


class RedeemForCreditsRequest(BaseModel):
    """邀请码兑换积分请求模型"""

    code: str


class RedeemForCreditsResponse(BaseModel):
    """邀请码兑换积分响应模型"""

    success: bool
    message: str
    credits_earned: Optional[float] = None
    current_credits: Optional[float] = None
