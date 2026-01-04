from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


class TelegramUser(BaseModel):
    """Telegram 用户信息模型"""

    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    is_bot: bool = False
    is_premium: bool = False


class UserInfo(BaseModel):
    """用户完整信息模型"""

    tg_id: int
    credits: float = 0
    donation: float = 0
    invitee_count: int = 0  # 邀请人数
    invitation_codes: List[str] = []
    plex_info: Optional[Dict[str, Any]] = None
    emby_info: Optional[Dict[str, Any]] = None
    overseerr_info: Optional[Dict[str, Any]] = None
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
    tags: List[str] = []
    is_premium: bool = False


class PlexLineInfo(BaseModel):
    """Plex线路信息模型"""

    name: str
    tags: List[str] = []
    is_premium: bool = False


class EmbyLinesResponse(BaseResponse):
    """Emby线路列表响应模型"""

    lines: List[EmbyLineInfo]


class PlexLinesResponse(BaseResponse):
    """Plex线路列表响应模型"""

    lines: List[PlexLineInfo]


class LineTagRequest(BaseModel):
    """线路标签请求模型"""

    line_name: str = Field(..., min_length=1)
    tags: List[str] = Field(..., min_items=0)


class LineTagResponse(BaseModel):
    """线路标签响应模型"""

    line_name: str
    tags: List[str]


class AllLineTagsResponse(BaseModel):
    """所有线路标签响应模型"""

    lines: Dict[str, List[str]]


class AuthBindLineRequest(BaseModel):
    """认证并绑定线路的请求模型"""

    username: str = Field(..., min_length=1, description="用户名或邮箱")
    password: Optional[str] = Field(None, description="密码")
    line: str = Field(..., min_length=1, description="要绑定的线路名称")
    token: Optional[str] = Field(None, description="用户认证令牌")
    auth_method: Optional[str] = Field(
        None, description="认证方法，支持 'password' 或 'token'"
    )


class CreditsTransferRequest(BaseModel):
    """积分转移请求模型"""

    target_tg_id: int = Field(..., description="目标用户的 Telegram ID")
    amount: float = Field(
        ..., gt=0, le=10000, description="转移积分数量，必须大于0且不超过10000"
    )
    note: Optional[str] = Field(None, max_length=200, description="转移备注，可选")


class CreditsTransferResponse(BaseModel):
    """积分转移响应模型"""

    success: bool
    message: str
    transferred_amount: Optional[float] = None
    fee_amount: Optional[float] = None
    current_credits: Optional[float] = None


class CurrentLineResponse(BaseModel):
    """当前绑定线路响应模型"""

    success: bool
    message: str
    line: Optional[str] = None


class LineScheduleCreate(BaseModel):
    """创建线路调度请求模型"""

    service: str = Field(..., description="服务类型: plex 或 emby")
    line: str = Field(..., min_length=1, description="线路名称")
    days_of_week: List[int] = Field(
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

    line: Optional[str] = Field(None, min_length=1, description="线路名称")
    days_of_week: Optional[List[int]] = Field(
        None, min_items=1, max_items=7, description="星期几列表 (0=周一, 6=周日)"
    )
    start_time: Optional[str] = Field(
        None, pattern=r"^([01]\d|2[0-3]):([0-5]\d)$", description="开始时间 HH:MM"
    )
    end_time: Optional[str] = Field(
        None, pattern=r"^([01]\d|2[0-3]):([0-5]\d)$", description="结束时间 HH:MM"
    )
    priority: Optional[int] = Field(None, ge=0, description="优先级")
    is_enabled: Optional[bool] = Field(None, description="是否启用")


class LineScheduleInfo(BaseModel):
    """线路调度信息模型"""

    id: int
    service: str
    line: str
    days_of_week: List[int]
    start_time: str
    end_time: str
    priority: int
    is_enabled: bool
    created_at: int
    updated_at: int


class LineScheduleListResponse(BaseResponse):
    """线路调度列表响应模型"""

    schedules: List[LineScheduleInfo] = []


class LineScheduleUnlockResponse(BaseResponse):
    """线路调度功能解锁响应模型"""

    is_unlocked: bool = False
    is_premium: bool = False
    unlock_time: Optional[int] = None
    credits_cost: Optional[float] = None


class LineScheduleUnlockRequest(BaseModel):
    """线路调度功能解锁请求模型"""

    service: str = Field(..., description="服务类型 (emby/plex)")
    confirm: bool = Field(default=True, description="确认解锁")


class LineScheduleStatusResponse(BaseResponse):
    """线路调度状态响应模型"""

    is_unlocked: bool = False
    is_premium: bool = False
    has_schedules: bool = False
    current_schedule: Optional[LineScheduleInfo] = None
