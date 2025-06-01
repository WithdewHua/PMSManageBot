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
    invitation_codes: List[str] = []
    plex_info: Optional[Dict[str, Any]] = None
    emby_info: Optional[Dict[str, Any]] = None
    overseerr_info: Optional[Dict[str, Any]] = None
    is_admin: bool = False


class BaseResponse(BaseModel):
    """通用响应模型"""

    success: bool
    message: str


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


class EmbyLinesResponse(BaseModel):
    """Emby线路列表响应模型"""

    lines: List[EmbyLineInfo]


class PlexLinesResponse(BaseModel):
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
