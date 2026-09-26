from typing import Any

from pydantic import BaseModel


class RankingInfo(BaseModel):
    """排行榜信息模型"""

    credits_rank: list[dict[str, Any]] = []
    donation_rank: list[dict[str, Any]] = []
    watched_time_rank_plex: list[dict[str, Any]] = []
    watched_time_rank_emby: list[dict[str, Any]] = []
