"""Account binding request schemas."""

from pydantic import BaseModel, EmailStr, Field


class BindPlexRequest(BaseModel):
    """绑定Plex请求模型"""

    email: EmailStr


class BindEmbyRequest(BaseModel):
    """绑定Emby请求模型"""

    username: str = Field(..., min_length=2)
