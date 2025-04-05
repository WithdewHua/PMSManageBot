from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class TelegramUser(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    is_bot: bool = False
    is_premium: bool = False


class UserInfo(BaseModel):
    tg_id: int
    credits: float = 0
    donation: float = 0
    invitation_codes: List[str] = []
    plex_info: Optional[Dict[str, Any]] = None
    emby_info: Optional[Dict[str, Any]] = None
    overseerr_info: Optional[Dict[str, Any]] = None


class RankingInfo(BaseModel):
    credits_rank: List[Dict[str, Any]] = []
    donation_rank: List[Dict[str, Any]] = []
    watched_time_rank_plex: List[Dict[str, Any]] = []
    watched_time_rank_emby: List[Dict[str, Any]] = []
