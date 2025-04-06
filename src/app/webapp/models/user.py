from typing import Any, Dict, List, Optional

from pydantic import BaseModel


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
