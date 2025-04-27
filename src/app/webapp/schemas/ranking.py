from typing import Any, Dict, List

from pydantic import BaseModel


class RankingInfo(BaseModel):
    """排行榜信息模型"""

    credits_rank: List[Dict[str, Any]] = []
    donation_rank: List[Dict[str, Any]] = []
    watched_time_rank_plex: List[Dict[str, Any]] = []
    watched_time_rank_emby: List[Dict[str, Any]] = []
