"""Shared API schemas used by authentication and domain routers."""

from pydantic import BaseModel


class TelegramUser(BaseModel):
    """Telegram 用户信息模型"""

    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    is_bot: bool = False
    is_premium: bool = False


class BaseResponse(BaseModel):
    """通用响应模型"""

    success: bool
    message: str = ""
