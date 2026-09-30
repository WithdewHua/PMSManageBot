from typing import Any

from pydantic import BaseModel


class UserInfo(BaseModel):
    """用户完整信息模型"""

    tg_id: int
    credits: float = 0
    donation: float = 0
    invitee_count: int = 0
    invitation_codes: list[str] = []
    plex_info: dict[str, Any] | None = None
    emby_info: dict[str, Any] | None = None
    overseerr_info: dict[str, Any] | None = None
    is_admin: bool = False
