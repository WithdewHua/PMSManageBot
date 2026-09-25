from typing import Any

from pydantic import BaseModel, EmailStr, Field


class TelegramUser(BaseModel):
    """Telegram 用户信息模型"""

    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    is_bot: bool = False
    is_premium: bool = False


class UserInfo(BaseModel):
    """用户完整信息模型"""

    tg_id: int
    credits: float = 0
    donation: float = 0
    invitee_count: int = 0  # 邀请人数
    invitation_codes: list[str] = []
    plex_info: dict[str, Any] | None = None
    emby_info: dict[str, Any] | None = None
    overseerr_info: dict[str, Any] | None = None
    is_admin: bool = False


class BaseResponse(BaseModel):
    """通用响应模型"""

    success: bool
    message: str = ""


class BindPlexRequest(BaseModel):
    """绑定Plex请求模型"""

    email: EmailStr


class BindEmbyRequest(BaseModel):
    """绑定Emby请求模型"""

    username: str = Field(..., min_length=2)


class EmbyLineRequest(BaseModel):
    """Emby线路请求模型"""

    line: str = Field(..., min_length=1)


class PlexLineRequest(BaseModel):
    """Plex线路请求模型"""

    line: str = Field(..., min_length=1)


class EmbyLineInfo(BaseModel):
    """Emby线路信息模型"""

    name: str
    tags: list[str] = []
    is_premium: bool = False


class PlexLineInfo(BaseModel):
    """Plex线路信息模型"""

    name: str
    tags: list[str] = []
    is_premium: bool = False


class EmbyLinesResponse(BaseResponse):
    """Emby线路列表响应模型"""

    lines: list[EmbyLineInfo]


class PlexLinesResponse(BaseResponse):
    """Plex线路列表响应模型"""

    lines: list[PlexLineInfo]


class LineTagRequest(BaseModel):
    """线路标签请求模型"""

    line_name: str = Field(..., min_length=1)
    tags: list[str] = Field(..., min_items=0)


class LineTagResponse(BaseModel):
    """线路标签响应模型"""

    line_name: str
    tags: list[str]


class AllLineTagsResponse(BaseModel):
    """所有线路标签响应模型"""

    lines: dict[str, list[str]]


class AuthBindLineRequest(BaseModel):
    """认证并绑定线路的请求模型"""

    username: str = Field(..., min_length=1, description="用户名或邮箱")
    password: str | None = Field(None, description="密码")
    line: str = Field(..., min_length=1, description="要绑定的线路名称")
    token: str | None = Field(None, description="用户认证令牌")
    auth_method: str | None = Field(
        None, description="认证方法，支持 'password' 或 'token'"
    )


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


class CurrentLineResponse(BaseModel):
    """当前绑定线路响应模型"""

    success: bool
    message: str
    line: str | None = None


class LineScheduleCreate(BaseModel):
    """创建线路调度请求模型"""

    service: str = Field(..., description="服务类型: plex 或 emby")
    line: str = Field(..., min_length=1, description="线路名称")
    days_of_week: list[int] = Field(
        ..., min_items=1, max_items=7, description="星期几列表 (0=周一, 6=周日)"
    )
    start_time: str = Field(
        ..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$", description="开始时间 HH:MM"
    )
    end_time: str = Field(
        ..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$", description="结束时间 HH:MM"
    )
    priority: int = Field(default=0, ge=0, description="优先级 (数字越小优先级越高)")


class LineScheduleUpdate(BaseModel):
    """更新线路调度请求模型"""

    line: str | None = Field(None, min_length=1, description="线路名称")
    days_of_week: list[int] | None = Field(
        None, min_items=1, max_items=7, description="星期几列表 (0=周一, 6=周日)"
    )
    start_time: str | None = Field(
        None, pattern=r"^([01]\d|2[0-3]):([0-5]\d)$", description="开始时间 HH:MM"
    )
    end_time: str | None = Field(
        None, pattern=r"^([01]\d|2[0-3]):([0-5]\d)$", description="结束时间 HH:MM"
    )
    priority: int | None = Field(None, ge=0, description="优先级")
    is_enabled: bool | None = Field(None, description="是否启用")


class LineScheduleInfo(BaseModel):
    """线路调度信息模型"""

    id: int
    service: str
    line: str
    days_of_week: list[int]
    start_time: str
    end_time: str
    priority: int
    is_enabled: bool
    created_at: int
    updated_at: int


class LineScheduleListResponse(BaseResponse):
    """线路调度列表响应模型"""

    schedules: list[LineScheduleInfo] = []


class LineScheduleUnlockResponse(BaseResponse):
    """线路调度功能解锁响应模型"""

    is_unlocked: bool = False
    is_premium: bool = False
    unlock_time: int | None = None
    credits_cost: float | None = None


class LineScheduleUnlockRequest(BaseModel):
    """线路调度功能解锁请求模型"""

    service: str = Field(..., description="服务类型 (emby/plex)")
    confirm: bool = Field(default=True, description="确认解锁")


class LineScheduleStatusResponse(BaseResponse):
    """线路调度状态响应模型"""

    is_unlocked: bool = False
    is_premium: bool = False
    has_schedules: bool = False
    current_schedule: LineScheduleInfo | None = None


# ==================== 自定义线路相关模型 ====================


class CustomLineSubmitRequest(BaseModel):
    """自定义线路提交请求模型"""

    domain: str = Field(..., min_length=1, max_length=255, description="线路域名")
    network_info: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="三网线路情况（电信/联通/移动等）",
    )
    price_monthly: float | None = Field(None, ge=0, description="月付价格")
    price_yearly: float | None = Field(None, ge=0, description="年付价格")
    traffic_limit: float | None = Field(None, ge=0, description="每月流量限制 (GB)")
    traffic_type: str = Field(
        default="one_way",
        description="流量计算类型: one_way=单向, two_way=双向",
    )
    total_traffic: float = Field(..., gt=0, description="总流量包 (GB)")
    valid_days: int | None = Field(None, ge=1, description="可使用天数")
    is_permanent: bool = Field(default=False, description="是否长期可用")
    user_note: str | None = Field(None, max_length=500, description="用户备注")


class CustomLineInfo(BaseModel):
    """自定义线路信息模型"""

    id: int
    tg_id: int
    domain: str
    network_info: str
    price_monthly: float | None = None
    price_yearly: float | None = None
    traffic_limit: float | None = None
    traffic_type: str
    valid_days: int | None = None
    is_permanent: bool
    status: str
    admin_note: str | None = None
    user_note: str | None = None
    tags: list[str] | None = None
    approved_at: int | None = None
    approved_by: int | None = None
    expires_at: int | None = None
    created_at: int
    updated_at: int
    total_traffic: float | None = None


class CustomLineListResponse(BaseResponse):
    """自定义线路列表响应模型"""

    lines: list[CustomLineInfo] = []
    total: int = 0


class CustomLineDetailResponse(BaseResponse):
    """自定义线路详情响应模型"""

    line: CustomLineInfo | None = None


class CustomLineApproveRequest(BaseModel):
    """管理员审批自定义线路请求模型"""

    action: str = Field(..., description="审批动作: approve=批准, reject=拒绝")
    admin_note: str | None = Field(None, max_length=500, description="管理员备注")
    valid_days: int | None = Field(
        None, ge=1, description="管理员设定的有效天数（覆盖用户提交的值）"
    )
    is_permanent: bool | None = Field(
        None, description="是否设为长期可用（覆盖用户提交的值）"
    )


class CustomLineUpdateRequest(BaseModel):
    """更新自定义线路请求模型（用户或管理员）"""

    domain: str | None = Field(
        None, min_length=1, max_length=255, description="线路域名"
    )
    network_info: str | None = Field(
        None, min_length=1, max_length=500, description="三网线路情况"
    )
    price_monthly: float | None = Field(None, ge=0, description="月付价格")
    price_yearly: float | None = Field(None, ge=0, description="年付价格")
    traffic_limit: float | None = Field(None, ge=0, description="每月流量限制 (GB)")
    traffic_type: str | None = Field(None, description="流量计算类型")
    total_traffic: float | None = Field(None, ge=0, description="总流量包 (GB)")
    valid_days: int | None = Field(None, ge=1, description="可使用天数")
    is_permanent: bool | None = Field(None, description="是否长期可用")
    user_note: str | None = Field(None, max_length=500, description="用户备注")


class AdminCustomLineUpdateRequest(BaseModel):
    """管理员更新自定义线路请求模型"""

    domain: str | None = Field(
        None, min_length=1, max_length=255, description="线路域名"
    )
    network_info: str | None = Field(
        None, min_length=1, max_length=500, description="三网线路情况"
    )
    price_monthly: float | None = Field(None, ge=0, description="月付价格")
    price_yearly: float | None = Field(None, ge=0, description="年付价格")
    traffic_limit: float | None = Field(None, ge=0, description="每月流量限制 (GB)")
    traffic_type: str | None = Field(None, description="流量计算类型")
    total_traffic: float | None = Field(None, ge=0, description="总流量包 (GB)")
    valid_days: int | None = Field(None, ge=1, description="可使用天数")
    is_permanent: bool | None = Field(None, description="是否长期可用")
    admin_note: str | None = Field(None, max_length=500, description="管理员备注")
    status: str | None = Field(
        None,
        description="状态: pending=待审批/approved=已批准/rejected=已拒绝/offline=已下线/expired=已过期",
    )


class CustomLineRenewRequest(BaseModel):
    """续期自定义线路请求模型"""

    valid_days: int = Field(..., ge=1, le=365 * 3, description="续期天数（1-1095天）")


class CustomLineOnlineRequest(BaseModel):
    """上线自定义线路请求模型"""

    traffic_limit: float | None = Field(None, ge=0, description="每月流量限制 (GB)")
    total_traffic: float | None = Field(None, ge=0, description="总流量包 (GB)")
    valid_days: int | None = Field(None, ge=1, description="可使用天数")
    is_permanent: bool | None = Field(None, description="是否长期可用")
