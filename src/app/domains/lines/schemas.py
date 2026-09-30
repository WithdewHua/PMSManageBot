"""HTTP schemas owned by the lines domain."""

from pydantic import BaseModel, Field

from app.transport.http.schemas import BaseResponse


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

    schedules: list[LineScheduleInfo] = Field(default=[])


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
