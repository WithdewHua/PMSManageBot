#!/usr/bin/env python3
"""Tautulli 幽灵会话（ghost session）识别

Plex 在部分版本下不会通过 WebSocket 发送 stop 事件，Tautulli 会一直保持会话开启，
直到超时或重启才写入 history —— 此时 stopped 记的是"重启时刻"而非真实停止时刻，
于是产生一条时长被严重夸大的记录，污染观看时长统计与积分计算。
这是 Tautulli 官方 FAQ 记录的已知问题，官方给出的处置方式即为删除错误记录。

由于 stopped 本身就是真实墙钟时间，任何基于墙钟的校验都无效。唯一可信的参照是
Plex 上报的播放进度 percent_complete —— 幽灵会话卡住时它停在最后一次更新的值，
不受此 bug 影响。因此：

    判定：play_duration > media_duration * GHOST_DURATION_RATIO + GHOST_DURATION_SLACK
    补偿：media_duration * percent_complete / 100
"""

from dataclasses import dataclass
from typing import Optional

from app.log import logger

# 粗筛阈值：只有播放时长超过该值的记录才值得去查媒体元数据，避免对全量记录发起请求。
# 判定阈值为「媒体时长 * RATIO + SLACK」，一集 20 分钟的剧集对应 1.0h，
# 因此这里取 1h 才能兜住常见短剧集的幽灵会话；真正合法的长媒体（电影、演唱会）
# 会在细查阶段用自身时长判定为正常，不会误伤。
# 实测 34173 条历史记录中，超过 1h 的仅 1258 条（3.7%），细查开销可忽略。
COARSE_FILTER_SECONDS = 3600

# 细查判定：播放时长超过「媒体时长 * RATIO + SLACK」即判为幽灵会话。
# paused_counter 已从播放时长中扣除，所以正常观看（哪怕中途长时间暂停）不会触发。
GHOST_DURATION_RATIO = 1.5
GHOST_DURATION_SLACK = 1800

# 直播没有固定媒体时长，用固定上限兜底
LIVE_MAX_SECONDS = 6 * 3600

STATUS_GHOST = "ghost"
STATUS_NORMAL = "normal"
STATUS_UNDETERMINED = "undetermined"


@dataclass
class HistoryVerdict:
    """单条 history 记录的判定结果"""

    row_id: Optional[int]
    user_id: Optional[int]
    friendly_name: str
    title: str
    rating_key: Optional[str]
    started: int
    stopped: int
    raw_seconds: int
    media_seconds: Optional[int]
    percent_complete: int
    is_live: bool
    status: str
    compensated_seconds: int
    reason: str

    @property
    def is_ghost(self) -> bool:
        return self.status == STATUS_GHOST

    @property
    def inflated_seconds(self) -> int:
        """被虚增的时长（秒）"""
        return max(self.raw_seconds - self.compensated_seconds, 0)


class MediaDurationResolver:
    """rating_key -> 媒体自身时长（秒），带进程内缓存

    Tautulli 的 get_metadata 返回的 duration 单位是毫秒。
    """

    def __init__(self, tautulli) -> None:
        self._tautulli = tautulli
        self._cache: dict[str, Optional[int]] = {}

    def get(self, rating_key) -> Optional[int]:
        if not rating_key:
            return None
        key = str(rating_key)
        if key in self._cache:
            return self._cache[key]

        duration = None
        try:
            metadata = self._tautulli.get_metadata(key)
            raw = (metadata or {}).get("duration")
            if raw:
                duration = int(int(raw) / 1000)
        except Exception as e:
            logger.warning(f"获取 rating_key {key} 的媒体时长失败: {e}")

        self._cache[key] = duration
        return duration


def get_row_play_seconds(row: dict) -> int:
    """取记录的实际播放时长（秒）

    home_stats 的 total_duration 口径为 SUM((stopped - started) - paused_counter)，
    对应 history 行的 play_duration；旧版本仅有 duration 字段。
    取两者较大值，避免因版本差异漏判。
    """
    values = []
    for key in ("play_duration", "duration"):
        value = row.get(key)
        if value is None:
            continue
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            continue
    return max(values) if values else 0


def clamp_percent(value) -> int:
    """把播放进度百分比归一到 [0, 100]"""
    try:
        percent = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(percent, 100))


def _to_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_active_session(row: dict) -> bool:
    """判断是否为「正在播放」的活动会话，而非已落库的历史记录

    Tautulli 的 get_history 默认会把当前活动会话一并返回（include_activity），
    这类记录尚未写入数据库：没有 row_id、stopped 为空、时长还在增长。
    它们既无法判定（会话没结束）也无法删除（没有 row_id），必须先剔除。
    """
    if row.get("state"):
        return True
    if not row.get("stopped"):
        return True
    if _to_int(row.get("row_id")) is None and _to_int(row.get("id")) is None:
        return True
    return False


def judge_row(row: dict, resolver: MediaDurationResolver) -> HistoryVerdict:
    """判定单条 history 记录是否为幽灵会话，并给出补偿时长"""
    play_seconds = get_row_play_seconds(row)
    is_live = bool(_to_int(row.get("live")) or 0)
    percent = clamp_percent(row.get("percent_complete"))
    media_seconds = None if is_live else resolver.get(row.get("rating_key"))

    if is_live:
        # 直播无媒体时长可比，只能用固定上限截断
        if play_seconds > LIVE_MAX_SECONDS:
            status = STATUS_GHOST
            compensated = LIVE_MAX_SECONDS
            reason = f"直播记录超过固定上限 {LIVE_MAX_SECONDS // 3600}h"
        else:
            status = STATUS_NORMAL
            compensated = play_seconds
            reason = "直播记录，时长在上限内"
    elif not media_seconds:
        # 元数据取不到（媒体已删除、rating_key 失效等），不做任何自动处置
        status = STATUS_UNDETERMINED
        compensated = play_seconds
        reason = "取不到媒体时长，无法判定，需人工确认"
    else:
        threshold = media_seconds * GHOST_DURATION_RATIO + GHOST_DURATION_SLACK
        if play_seconds > threshold:
            status = STATUS_GHOST
            compensated = int(media_seconds * percent / 100)
            reason = (
                f"播放时长 {play_seconds}s 超过阈值 {int(threshold)}s "
                f"(媒体时长 {media_seconds}s)"
            )
        else:
            status = STATUS_NORMAL
            compensated = play_seconds
            reason = "时长与媒体时长相符"

    return HistoryVerdict(
        row_id=_to_int(row.get("row_id")) or _to_int(row.get("id")),
        user_id=_to_int(row.get("user_id")),
        friendly_name=row.get("friendly_name") or row.get("user") or "",
        title=row.get("full_title") or row.get("title") or "",
        rating_key=(
            str(row["rating_key"]) if row.get("rating_key") is not None else None
        ),
        started=_to_int(row.get("started")) or 0,
        stopped=_to_int(row.get("stopped")) or 0,
        raw_seconds=play_seconds,
        media_seconds=media_seconds,
        percent_complete=percent,
        is_live=is_live,
        status=status,
        compensated_seconds=max(compensated, 0),
        reason=reason,
    )


def scan_history(
    tautulli,
    after: str = None,
    before: str = None,
    coarse_filter_seconds: int = COARSE_FILTER_SECONDS,
    max_records: int = None,
) -> tuple[int, list[HistoryVerdict]]:
    """扫描指定区间的 history，返回 (扫描总条数, 细查判定结果)

    只有播放时长超过 coarse_filter_seconds 的记录才会进入细查（查媒体元数据），
    其余直接视为正常。返回的列表仅包含进入细查的记录。

    必须以 grouping=0 拉取：合并后 percent_complete 取 MAX 而时长取 SUM，
    两者不再对应同一次播放，判定会失真。同时以 include_activity=0 排除
    正在播放的活动会话——它们没有 row_id，无法判定也无法删除。
    """
    resolver = MediaDurationResolver(tautulli)
    verdicts: list[HistoryVerdict] = []
    total = 0

    for row in tautulli.iter_history(
        grouping=0,
        include_activity=0,
        after=after,
        before=before,
        max_records=max_records,
    ):
        if is_active_session(row):
            continue
        total += 1
        if get_row_play_seconds(row) < coarse_filter_seconds:
            continue
        verdicts.append(judge_row(row, resolver))

    return total, verdicts
