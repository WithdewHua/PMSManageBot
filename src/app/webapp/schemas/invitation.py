from pydantic import BaseModel, Field


class InvitePointsResponse(BaseModel):
    """邀请码积分信息响应模型"""

    required_points: int
    current_points: float
    can_generate: bool
    error_message: str | None = None


class GenerateInviteCodeResponse(BaseModel):
    """生成邀请码响应模型"""

    success: bool
    message: str
    code: str | None = None


class RedeemInviteCodeRequest(BaseModel):
    """兑换邀请码请求模型"""

    code: str
    email: str | None = None  # Plex 使用
    username: str | None = None  # Emby 使用
    password: str | None = None  # Emby 使用
    bind_to_telegram: bool | None = Field(
        False, alias="bindToTelegram"
    )  # 是否绑定到 Telegram 账号


class RedeemResponse(BaseModel):
    """兑换邀请码响应模型"""

    success: bool
    message: str
    telegram_bound: bool | None = None  # 是否成功绑定到 Telegram


class CheckPrivilegedCodeRequest(BaseModel):
    """检查特权邀请码请求模型"""

    code: str


class CheckPrivilegedCodeResponse(BaseModel):
    """检查特权邀请码响应模型"""

    privileged: bool


class BatchCheckPrivilegedCodesRequest(BaseModel):
    """批量检查特权邀请码请求模型"""

    codes: list[str]


class BatchCheckPrivilegedCodesResponse(BaseModel):
    """批量检查特权邀请码响应模型"""

    results: dict[str, bool]  # 邀请码 -> 是否为特权码的映射


class RedeemForCreditsRequest(BaseModel):
    """邀请码兑换积分请求模型"""

    code: str


class RedeemForCreditsResponse(BaseModel):
    """邀请码兑换积分响应模型"""

    success: bool
    message: str
    credits_earned: float | None = None
    current_credits: float | None = None
