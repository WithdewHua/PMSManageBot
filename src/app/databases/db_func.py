import asyncio
import hashlib
import json
import math
import re
import traceback
from datetime import datetime, timedelta
from time import time
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse
from uuid import NAMESPACE_URL, uuid3

from app.config import settings
from app.databases.cache import (
    emby_api_key_cache,
    emby_last_user_defined_line_cache,
    emby_user_defined_line_cache,
    plex_last_user_defined_line_cache,
    plex_token_cache,
    plex_user_defined_line_cache,
    stream_traffic_cache,
    user_credits_cache,
    user_info_cache,
)
from app.databases.db import db
from app.databases.session import get_session
from app.log import logger
from app.models.models import (
    BlackjackHand,
    EmbyUser,
    PlexUser,
    PredictionBet,
    PredictionMarket,
    Statistics,
    TreasureParticipation,
    UserBadge,
    WheelStats,
)
from app.modules.emby import Emby
from app.modules.plex import Plex
from app.modules.tautulli import Tautulli
from app.utils.tautulli_history import (
    STATUS_GHOST,
    STATUS_UNDETERMINED,
    scan_history,
)
from app.utils.utils import (
    format_traffic_size,
    get_user_name_from_tg_id,
    get_user_total_duration,
    is_binded_premium_line,
    send_message_by_url,
)
from sqlalchemy import distinct, func, or_, select, union
from sqlalchemy import update as sql_update

# 幽灵会话扫描窗口（天）。Tautulli 的 get_history 按 stopped 过滤，而幽灵会话
# 落库时 stopped 即落库时刻，因此只要落库后 3 天内扫过一次就必定命中，
# 无需为「started 很早」的记录扩大窗口。留 3 天是为了容忍某轮任务失败。
GHOST_SCAN_DAYS = 3

# 积分结算水位线：记录已经完成结算的最后一个日期（YYYY-MM-DD）。
# 幽灵会话的补偿判定必须依赖它而非当前时刻——清理任务既会在结算前被调用，
# 也会作为独立定时任务在白天运行，只有水位线能稳定回答「这天结算过没有」。
GHOST_SETTLEMENT_CONFIG_TYPE = "ghost_session"
GHOST_SETTLEMENT_CONFIG_KEY = "settled_through_date"


def _get_settled_through_date() -> str:
    """取已完成结算的最后一个日期

    未初始化时保守地视为「昨天及以前都已结算」：首次部署时库里可能残留早已
    按被夸大的时长结算过的幽灵记录，此时宁可少补也不能重复补——重复补偿会把
    时长二次计入，比不补更糟。水位线随首次结算完成后即进入正常推进。
    """
    stored = db.get_system_config(
        GHOST_SETTLEMENT_CONFIG_TYPE, GHOST_SETTLEMENT_CONFIG_KEY
    )
    if stored:
        return stored
    return (datetime.now(settings.TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


def _set_settled_through_date(date_str: str) -> None:
    """结算完成后推进水位线"""
    db.set_system_config(
        GHOST_SETTLEMENT_CONFIG_TYPE, GHOST_SETTLEMENT_CONFIG_KEY, date_str
    )


def _get_premium_daily_limit(is_premium: bool) -> int:
    return (
        settings.PREMIUM_USER_TRAFFIC_LIMIT
        if is_premium
        else settings.USER_TRAFFIC_LIMIT
    )


def _get_traffic_cost_credits(chargeable_bytes: int) -> float:
    if chargeable_bytes <= 0:
        return 0

    gb_tiers = math.ceil(chargeable_bytes / (10 * 1024 * 1024 * 1024))
    return round(gb_tiers * settings.CREDITS_COST_PER_10GB, 2)


def _format_premium_traffic_deduction_summary(deduction_records: list[dict]) -> str:
    settlement_date = (datetime.now(settings.TZ) - timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )
    total_credits = sum(record["deducted_credits"] for record in deduction_records)
    total_chargeable_bytes = sum(
        record["chargeable_bytes"] for record in deduction_records
    )
    message_parts = [
        "💳 Premium 流量扣分汇总",
        f"⏰ 结算日期: {settlement_date}",
        "─" * 40,
    ]

    for service, title in (
        ("Plex", "🎬 Plex 扣分用户:"),
        ("Emby", "📺 Emby 扣分用户:"),
    ):
        service_records = [
            record for record in deduction_records if record["service"] == service
        ]
        if not service_records:
            continue

        message_parts.extend(["", title])
        for record in service_records:
            tg_id = record.get("tg_id")
            message_parts.append(
                f"  • {record['username']} | TG: {get_user_name_from_tg_id(tg_id) if tg_id else '未绑定 TG'} | "
                f"扣除积分: {record['deducted_credits']:.2f} | "
                f"扣费流量: {format_traffic_size(record['chargeable_bytes'])}"
            )

    message_parts.extend(
        [
            "",
            "📋 总计:",
            f"扣分用户: {len(deduction_records)} 人",
            f"扣除积分: {total_credits:.2f}",
            f"扣费流量: {format_traffic_size(total_chargeable_bytes)}",
        ]
    )
    return "\n".join(message_parts)


def _parse_debt_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None

    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=settings.TZ)
    except ValueError:
        return None


def _resolve_premium_status_for_settlement(
    current_is_premium: bool,
    premium_status_updated_at: Optional[int],
    settlement_date: datetime,
) -> bool:
    if not premium_status_updated_at:
        return current_is_premium

    status_updated_at = datetime.fromtimestamp(
        premium_status_updated_at, tz=settings.TZ
    )
    settlement_day_end = settlement_date.replace(
        hour=23, minute=59, second=59, microsecond=999999
    )
    if status_updated_at > settlement_day_end:
        return not current_is_premium

    return current_is_premium


def _settle_premium_traffic_usage(
    traffic_usage_premium: int,
    is_premium: bool,
    debt_bytes: int,
    debt_updated_date: Optional[str],
    settlement_date: datetime,
) -> dict:
    daily_limit = _get_premium_daily_limit(is_premium)
    max_debt_bytes = daily_limit * 2
    previous_debt = max(int(debt_bytes or 0), 0)
    debt_date = _parse_debt_date(debt_updated_date)
    gap_days = 0

    if debt_date and debt_date.date() < settlement_date.date():
        gap_days = (settlement_date.date() - debt_date.date()).days - 1
        gap_days = max(gap_days, 0)

    recovered_before_today = min(previous_debt, gap_days * daily_limit)
    debt_before_today = max(previous_debt - recovered_before_today, 0)
    effective_limit = max(daily_limit - debt_before_today, 0)
    end_of_day_debt_raw = max(
        debt_before_today + traffic_usage_premium - daily_limit, 0
    )
    chargeable_bytes = max(end_of_day_debt_raw - max_debt_bytes, 0)
    next_debt_bytes = min(end_of_day_debt_raw, max_debt_bytes)
    exceed_bytes = max(traffic_usage_premium - effective_limit, 0)
    traffic_cost_credits = _get_traffic_cost_credits(chargeable_bytes)

    return {
        "daily_limit": daily_limit,
        "effective_limit": effective_limit,
        "debt_before_today": debt_before_today,
        "recovered_before_today": recovered_before_today,
        "exceed_bytes": exceed_bytes,
        "chargeable_debt_excess": chargeable_bytes,
        "next_debt_bytes": next_debt_bytes,
        "chargeable_bytes": chargeable_bytes,
        "traffic_cost_credits": traffic_cost_credits,
        "next_debt_updated_date": settlement_date.strftime("%Y-%m-%d"),
    }


def clean_tautulli_ghost_sessions(scan_days: int = GHOST_SCAN_DAYS) -> dict:
    """清理 Tautulli 中的幽灵会话记录

    Plex 在部分版本下不发送 WebSocket stop 事件，Tautulli 会保持会话开启直到
    超时或重启才写入 history，产生一条时长被严重夸大的记录，污染观看时长与积分。
    Tautulli 官方对此的处置方式即为删除错误记录。

    处理顺序是「先留档、再删除、后标记」：
      - 留档失败则不删除，下轮重试；
      - 删除失败则停在 deleted=0，不会被补偿，下轮由自愈逻辑重试；
      - 记录一旦从 Tautulli 删除便无法回溯，补偿时长只能依赖留档表。

    必须在积分结算之前执行，否则 get_home_stats 取到的仍是脏数据。

    Returns
    -------
    dict
        本次清理的汇总，供管理员通知使用。
    """
    logger.info(f"开始清理 Tautulli 幽灵会话（扫描最近 {scan_days} 天）")
    summary = {
        "scanned": 0,
        "ghosts": [],
        "undetermined": [],
        "deleted": 0,
        "failed": [],
        "retried": 0,
    }

    try:
        tautulli = Tautulli()

        # 自愈：上一轮留档成功但未确认删除的记录，先重试一次
        stale_row_ids = db.get_undeleted_ghost_row_ids()
        if stale_row_ids:
            logger.warning(f"发现 {len(stale_row_ids)} 条未确认删除的幽灵会话，重试")
            if tautulli.delete_history(stale_row_ids):
                db.mark_ghost_sessions_deleted(stale_row_ids)
                summary["retried"] = len(stale_row_ids)
            else:
                logger.error(f"重试删除幽灵会话失败: {stale_row_ids}")

        after = (datetime.now(settings.TZ) - timedelta(days=scan_days)).strftime(
            "%Y-%m-%d"
        )
        scanned, verdicts = scan_history(tautulli, after=after)
        summary["scanned"] = scanned

        ghosts = [v for v in verdicts if v.status == STATUS_GHOST and v.row_id]
        summary["undetermined"] = [
            {
                "row_id": v.row_id,
                "friendly_name": v.friendly_name,
                "title": v.title,
                "raw_seconds": v.raw_seconds,
            }
            for v in verdicts
            if v.status == STATUS_UNDETERMINED
        ]

        if not ghosts:
            logger.info(f"未发现幽灵会话（共扫描 {scanned} 条记录）")
            return summary

        # 跳过已经处理过的，避免重复删除与重复补偿
        logged = db.get_logged_ghost_row_ids([v.row_id for v in ghosts])
        ghosts = [v for v in ghosts if v.row_id not in logged]
        if not ghosts:
            logger.info("检出的幽灵会话均已留档处理过，跳过")
            return summary

        staged_row_ids = []
        # 结算水位线之前（含当天）的记录已经按被夸大的时长结算过了，
        # 此时再补偿等于把时长二次计入，因此这类记录只删除、不补偿。
        # 水位线为空表示还没跑过任何结算，此时全部记录都可补偿。
        settled_through = _get_settled_through_date()
        for v in ghosts:
            play_date = (
                datetime.fromtimestamp(v.started, settings.TZ).strftime("%Y-%m-%d")
                if v.started
                else datetime.now(settings.TZ).strftime("%Y-%m-%d")
            )
            already_settled = bool(settled_through) and play_date <= settled_through
            record = {
                "row_id": v.row_id,
                "user_id": v.user_id,
                "friendly_name": v.friendly_name,
                "title": v.title,
                "rating_key": v.rating_key,
                "started": v.started,
                "stopped": v.stopped,
                "play_date": play_date,
                "raw_seconds": v.raw_seconds,
                "media_seconds": v.media_seconds,
                "percent_complete": v.percent_complete,
                "compensated_seconds": v.compensated_seconds,
                "compensated": 1 if already_settled else 0,
            }
            # 留档必须先于删除：删掉之后这条记录就再也拿不回来了
            if db.add_ghost_session_log(record):
                staged_row_ids.append(v.row_id)
                summary["ghosts"].append(
                    {
                        "row_id": v.row_id,
                        "user_id": v.user_id,
                        "friendly_name": v.friendly_name,
                        "title": v.title,
                        "raw_seconds": v.raw_seconds,
                        "media_seconds": v.media_seconds,
                        "percent_complete": v.percent_complete,
                        "compensated_seconds": v.compensated_seconds,
                        "play_date": play_date,
                        "already_settled": already_settled,
                    }
                )
            else:
                summary["failed"].append(v.row_id)
                logger.error(f"幽灵会话 row_id={v.row_id} 留档失败，跳过删除")

        if staged_row_ids:
            if tautulli.delete_history(staged_row_ids):
                if db.mark_ghost_sessions_deleted(staged_row_ids):
                    summary["deleted"] = len(staged_row_ids)
                else:
                    # 已从 Tautulli 删除但标记失败，补偿会被推迟到下轮自愈
                    logger.error(
                        f"幽灵会话已删除但标记失败，需人工核查: {staged_row_ids}"
                    )
            else:
                summary["failed"].extend(staged_row_ids)
                logger.error(f"删除幽灵会话失败: {staged_row_ids}")

        for item in summary["ghosts"]:
            logger.info(
                f"清理幽灵会话 row_id={item['row_id']} 用户={item['friendly_name']} "
                f"《{item['title']}》 原始 {item['raw_seconds'] / 3600:.2f}h -> "
                f"补偿 {item['compensated_seconds'] / 3600:.2f}h"
            )
        logger.info(
            f"幽灵会话清理完成：扫描 {scanned} 条，删除 {summary['deleted']} 条，"
            f"失败 {len(summary['failed'])} 条"
        )

    except Exception as e:
        logger.error(f"清理 Tautulli 幽灵会话失败: {e}")
        traceback.print_exc()

    return summary


def _format_ghost_session_summary(summary: dict) -> str:
    """把清理结果拼成管理员通知文本"""
    lines = [
        "Tautulli 幽灵会话清理报告",
        "====================",
        "",
        f"扫描记录: {summary['scanned']} 条",
        f"清理删除: {summary['deleted']} 条",
    ]
    if summary.get("retried"):
        lines.append(f"补删遗留: {summary['retried']} 条")

    if summary["ghosts"]:
        compensated = [g for g in summary["ghosts"] if not g.get("already_settled")]
        settled = [g for g in summary["ghosts"] if g.get("already_settled")]

        def _detail(item):
            return (
                f"· {item['friendly_name']}《{item['title']}》\n"
                f"  {item['play_date']} 原始 {item['raw_seconds'] / 3600:.2f}h → "
                f"补偿 {item['compensated_seconds'] / 3600:.2f}h "
                f"(媒体 {(item['media_seconds'] or 0) / 3600:.2f}h, "
                f"进度 {item['percent_complete']}%)"
            )

        if compensated:
            lines.append("")
            lines.append("--- 已删除并补偿时长 ---")
            lines.extend(_detail(item) for item in compensated)

        if settled:
            lines.append("")
            lines.append("--- 已删除，不补偿（该日积分已结算，补偿会二次计入）---")
            lines.extend(
                f"· {item['friendly_name']}《{item['title']}》 {item['play_date']} "
                f"原始 {item['raw_seconds'] / 3600:.2f}h"
                for item in settled
            )

    if summary["undetermined"]:
        lines.append("")
        lines.append("--- 无法判定，需人工确认 ---")
        for item in summary["undetermined"]:
            lines.append(
                f"· {item['friendly_name']}《{item['title']}》 "
                f"{item['raw_seconds'] / 3600:.2f}h (媒体元数据缺失)"
            )

    if summary["failed"]:
        lines.append("")
        lines.append(f"--- 处理失败 {len(summary['failed'])} 条 ---")
        lines.append(f"row_ids: {summary['failed']}")

    lines.append("")
    lines.append("====================")
    return "\n".join(lines)


def update_plex_credits():
    """更新积分及观看时长"""
    logger.info("开始更新 Plex 用户积分及观看时长")
    notification_tasks = []
    deduction_records = []
    ghost_compensation: dict = {}
    # 邀请人奖励累积字典: {inviter_tg_id: {"total_bonus": float, "details": [{"username": str, "base_credits": float, "bonus": float}]}}
    inviter_rewards: dict = {}
    try:
        # 先更新用户信息
        update_plex_info(plex_name=True, plex_id=False, plex_avatar=False)

        # 获取一天内的观看时长
        duration = get_user_total_duration(
            Tautulli().get_home_stats(
                1, "duration", len(Plex().users_by_id), "top_users"
            )
        )
        # 加回被清理掉的幽灵会话时长：这些记录已从 Tautulli 删除，
        # get_home_stats 不再包含它们，只能从留档表按真实播放进度补回，
        # 否则用户这部分观看时长就白丢了
        ghost_compensation = db.get_pending_ghost_compensation()
        for ghost_user_id, ghost_hours in ghost_compensation.items():
            # duration 的 key 直接来自 Tautulli，为 int 型 user_id
            key = (
                int(ghost_user_id)
                if str(ghost_user_id).lstrip("-").isdigit()
                else ghost_user_id
            )
            duration[key] = duration.get(key, 0) + ghost_hours
            logger.info(
                f"用户 {ghost_user_id} 补回幽灵会话观看时长 {round(ghost_hours, 2)} 小时"
            )
        # update credits and watched_time
        with get_session() as session:
            stmt = select(PlexUser.plex_id).where(PlexUser.plex_id.isnot(None))
            plex_ids = session.execute(stmt).scalars().all()

        for plex_id in plex_ids:
            play_duration = round(min(float(duration.get(plex_id, 0)), 24), 2)
            # 最大记 8h
            credits_inc = min(play_duration, 8)

            with get_session() as session:
                stmt = select(
                    PlexUser.credits,
                    PlexUser.watched_time,
                    PlexUser.tg_id,
                    PlexUser.plex_username,
                    PlexUser.is_premium,
                    PlexUser.premium_status_updated_at,
                    PlexUser.premium_traffic_debt_bytes,
                    PlexUser.premium_traffic_debt_updated_date,
                ).where(PlexUser.plex_id == plex_id)
                res = session.execute(stmt).fetchone()
            if not res:
                continue
            watched_time_init = res[1]
            tg_id = res[2]
            plex_username = res[3]
            is_premium = res[4]
            premium_status_updated_at = res[5]
            debt_bytes = int(res[6] or 0)
            debt_updated_date = res[7]
            settlement_date = datetime.now(settings.TZ) - timedelta(days=1)
            is_premium_for_settlement = _resolve_premium_status_for_settlement(
                current_is_premium=bool(is_premium),
                premium_status_updated_at=premium_status_updated_at,
                settlement_date=settlement_date,
            )
            # 获取用户昨日的 premium 流量使用情况（用于流量费用计算）
            traffic_usage_premium = db.get_user_daily_traffic(
                user_id=str(plex_id),
                service="plex",
                date=settlement_date,
                premium_only=True,
            )
            # 获取用户昨日的总流量（用于流量惩罚计算）
            traffic_usage_total = db.get_user_daily_traffic(
                user_id=str(plex_id),
                service="plex",
                date=settlement_date,
                premium_only=False,
            )

            premium_traffic_result = _settle_premium_traffic_usage(
                traffic_usage_premium=traffic_usage_premium,
                is_premium=is_premium_for_settlement,
                debt_bytes=debt_bytes,
                debt_updated_date=debt_updated_date,
                settlement_date=settlement_date,
            )
            traffic_usage_exceed = premium_traffic_result["exceed_bytes"]
            traffic_cost_credits = premium_traffic_result["traffic_cost_credits"]
            if traffic_cost_credits > 0:
                deduction_records.append(
                    {
                        "service": "Plex",
                        "username": plex_username,
                        "tg_id": tg_id,
                        "deducted_credits": traffic_cost_credits,
                        "chargeable_bytes": premium_traffic_result["chargeable_bytes"],
                    }
                )

            if (
                play_duration == 0
                and traffic_usage_total == 0
                and premium_traffic_result["debt_before_today"] == 0
                and premium_traffic_result["next_debt_bytes"] == 0
            ):
                if debt_bytes > 0 or debt_updated_date:
                    with get_session() as session:
                        stmt = (
                            sql_update(PlexUser)
                            .where(PlexUser.plex_id == plex_id)
                            .values(
                                premium_traffic_debt_bytes=premium_traffic_result[
                                    "next_debt_bytes"
                                ],
                                premium_traffic_debt_updated_date=premium_traffic_result[
                                    "next_debt_updated_date"
                                ],
                            )
                        )
                        session.execute(stmt)
                continue

            # 计算超长观看惩罚 (TimePenalty)
            time_penalty = 0
            if play_duration > 8 * 1.2:
                time_penalty = (play_duration - 8 * 1.2) * 0.5

            # 计算超额流量惩罚 (DataPenalty)
            data_penalty = 0
            data_ratio = 0
            expected_data = play_duration * 10 * 1024 * 1024 * 1024  # 10 GB/小时
            if traffic_usage_total > 0 and expected_data > 0:
                data_ratio = float(traffic_usage_total) / float(expected_data)
                if data_ratio > 1.2:
                    data_penalty = float(credits_inc) * (data_ratio - 1.2) * 0.5

            # 应用惩罚到基础积分
            final_daily_score = max(
                0, min(credits_inc - time_penalty - data_penalty, 8)
            )
            # 保存原始 credits_inc 用于显示
            original_credits_inc = credits_inc
            credits_inc = final_daily_score
            # 计算勋章加成
            badge_bonus = 0
            badge_bonus_details = []
            if tg_id:
                active_badges = db.get_user_active_badges_with_bonus(tg_id)
                for badge_info in active_badges:
                    bonus_percentage = float(badge_info["bonus_percentage"])
                    bonus_credits = float(credits_inc) * bonus_percentage
                    badge_bonus += bonus_credits
                    badge_bonus_details.append(
                        {
                            "name": badge_info["badge"]["name"],
                            "percentage": bonus_percentage * 100,
                            "credits": round(bonus_credits, 2),
                        }
                    )

            if not tg_id:
                credits_init = res[0]
                credits = credits_init + credits_inc - traffic_cost_credits
                watched_time = watched_time_init + play_duration
                with get_session() as session:
                    stmt = (
                        sql_update(PlexUser)
                        .where(PlexUser.plex_id == plex_id)
                        .values(
                            credits=credits,
                            watched_time=watched_time,
                            premium_traffic_debt_bytes=premium_traffic_result[
                                "next_debt_bytes"
                            ],
                            premium_traffic_debt_updated_date=premium_traffic_result[
                                "next_debt_updated_date"
                            ],
                        )
                    )
                    session.execute(stmt)
            else:
                with get_session() as session:
                    stmt = select(Statistics.credits).where(Statistics.tg_id == tg_id)
                    credits_init = session.execute(stmt).scalar()
                # 加上勋章加成
                credits = (
                    credits_init + credits_inc + badge_bonus - traffic_cost_credits
                )
                watched_time = watched_time_init + play_duration
                with get_session() as session:
                    stmt1 = (
                        sql_update(PlexUser)
                        .where(PlexUser.plex_id == plex_id)
                        .values(
                            watched_time=watched_time,
                            premium_traffic_debt_bytes=premium_traffic_result[
                                "next_debt_bytes"
                            ],
                            premium_traffic_debt_updated_date=premium_traffic_result[
                                "next_debt_updated_date"
                            ],
                        )
                    )
                    stmt2 = (
                        sql_update(Statistics)
                        .where(Statistics.tg_id == tg_id)
                        .values(credits=credits)
                    )
                    session.execute(stmt1)
                    session.execute(stmt2)

            # 邀请人奖励：被邀请人基础积分的 10%，与被邀请人是否绑定 tg 无关
            # 累积到字典，循环结束后统一发通知
            inviter_tg_id = db.get_inviter_tg_id_by_plex_id(plex_id)
            inviter_bonus = 0.0
            # 排除邀请人是自己的情况
            if inviter_tg_id and inviter_tg_id != tg_id and credits_inc > 0:
                inviter_bonus = round(credits_inc * 0.1, 2)
                if inviter_tg_id not in inviter_rewards:
                    inviter_rewards[inviter_tg_id] = {"total_bonus": 0.0, "details": []}
                inviter_rewards[inviter_tg_id]["total_bonus"] = round(
                    inviter_rewards[inviter_tg_id]["total_bonus"] + inviter_bonus, 2
                )
                inviter_rewards[inviter_tg_id]["details"].append(
                    {
                        "username": plex_username,
                        "base_credits": round(credits_inc, 2),
                        "bonus": inviter_bonus,
                    }
                )
                logger.info(
                    f"累积邀请人 {inviter_tg_id} 的奖励积分: +{inviter_bonus} (来自用户 {plex_username} ({plex_id}))"
                )

            if tg_id and play_duration > 0:
                # 构建勋章加成信息 - 只显示总加成积分
                badge_bonus_text = ""
                if badge_bonus > 0:
                    badge_bonus_text = f"\n勋章加成积分: +{round(badge_bonus, 2)}"

                # 构建惩罚信息 - 只显示总惩罚分数
                total_penalty = time_penalty + data_penalty
                penalty_text = ""
                if total_penalty > 0:
                    penalty_text = f"\n观看消耗积分: -{round(total_penalty, 2)}"

                # 构建邀请人奖励信息
                inviter_bonus_text = ""
                if inviter_bonus > 0:
                    inviter_bonus_text = (
                        f"\n邀请人额外奖励: +{inviter_bonus} (已发放给邀请人)"
                    )

                # 需要发送通知
                notification_tasks.append(
                    (
                        tg_id,
                        f"""
Plex 观看积分更新通知
====================

新增观看时长: {round(play_duration, 2)} 小时
基础观看积分: {round(original_credits_inc, 2)}{penalty_text}{badge_bonus_text}{inviter_bonus_text}
Premium 流量使用情况: {round(traffic_usage_premium / (1024 * 1024 * 1024), 2)} GB
Premium 当日可用免费额度: {round(premium_traffic_result["effective_limit"] / (1024 * 1024 * 1024), 2)} GB
Premium 当日前待偿还额度: {round(premium_traffic_result["debt_before_today"] / (1024 * 1024 * 1024), 2)} GB
Premium 自动偿还额度: {round(premium_traffic_result["recovered_before_today"] / (1024 * 1024 * 1024), 2)} GB
Premium 当日超额流量: {max(round(traffic_usage_exceed / (1024 * 1024 * 1024), 2), 0)} GB
Premium 结转待偿还额度: {round(premium_traffic_result["next_debt_bytes"] / (1024 * 1024 * 1024), 2)} GB
Premium 实际扣费流量: {round(premium_traffic_result["chargeable_bytes"] / (1024 * 1024 * 1024), 2)} GB
Premium 流量消耗积分: {round(traffic_cost_credits, 2)}

积分变化: {round(credits_inc + badge_bonus - traffic_cost_credits, 2):+.2f}

--------------------

当前总积分: {round(credits, 2)}
当前总观看时长: {round(watched_time, 2)} 小时

====================""",
                    )
                )

            logger.info(
                f"更新 Plex 用户 {plex_username} ({plex_id}) 的积分和观看时长: "
                f"新增观看时长 {round(play_duration, 2)} 小时，新增观看积分 {round(credits_inc, 2)} (原始: {round(original_credits_inc, 2)}, 时长惩罚: {round(time_penalty, 2)}, 流量惩罚: {round(data_penalty, 2)}), 流量消耗积分 {round(traffic_cost_credits, 2)}"
            )

        # 循环结束后，统一更新邀请人积分并发送汇总通知
        for inviter_tg_id, reward_info in inviter_rewards.items():
            total_bonus = reward_info["total_bonus"]
            details = reward_info["details"]
            inviter_credits_now = db.get_user_credits(inviter_tg_id)
            if inviter_credits_now is None:
                logger.warning(
                    f"邀请人 {inviter_tg_id} 在 statistics 表中无记录，跳过奖励"
                )
                continue
            db.update_user_credits(
                inviter_credits_now + total_bonus, tg_id=inviter_tg_id
            )
            logger.info(
                f"邀请人 {inviter_tg_id} 共获得 Plex 邀请奖励积分: +{total_bonus}"
            )
            # 构建明细行
            detail_lines = "\n".join(
                f"  · {d['username']}: 基础积分 {d['base_credits']} → 奖励 +{d['bonus']}"
                for d in details
            )
            stat_date = (datetime.now(settings.TZ) - timedelta(days=1)).strftime(
                "%Y-%m-%d"
            )
            notification_tasks.append(
                (
                    inviter_tg_id,
                    f"""
Plex 邀请奖励通知
====================

{stat_date} 共 {len(details)} 位被邀请用户有新增观看记录:
{detail_lines}

本次邀请奖励积分: +{total_bonus}

--------------------

当前总积分: {round(inviter_credits_now + total_bonus, 2)}

====================""",
                )
            )

    except Exception as e:
        logger.error(f"更新 Plex 用户积分及观看时长失败: {e}")
        for chat_id in settings.TG_ADMIN_CHAT_ID:
            notification_tasks.append(
                (
                    chat_id,
                    f"更新 Plex 用户积分及观看时长失败: {e}",
                )
            )
        return notification_tasks, deduction_records
    else:
        # 补偿时长已确实写入积分与观看时长，此时才允许标记结算，
        # 中途失败则保持未结算状态，留到下一轮补上
        if ghost_compensation:
            db.mark_ghost_compensation_settled()
            logger.info(f"已结算 {len(ghost_compensation)} 个用户的幽灵会话补偿时长")
        # 推进结算水位线：本次处理的是前一天的数据。之后再检出该日期及更早的
        # 幽灵会话时，清理任务据此判定为「已结算」，只删除不补偿。
        _set_settled_through_date(
            (datetime.now(settings.TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        )
        logger.info("Plex 用户积分及观看时长更新完成")
        return notification_tasks, deduction_records


def update_emby_credits():
    """更新 emby 积分及观看时长"""
    logger.info("开始更新 Emby 用户积分及观看时长")
    # 获取所有用户的观看时长
    emby = Emby()
    notification_tasks = []
    deduction_records = []
    # 邀请人奖励累积字典: {inviter_tg_id: {"total_bonus": float, "details": [{"username": str, "base_credits": float, "bonus": float}]}}
    inviter_rewards: dict = {}
    try:
        duration = emby.get_user_total_play_time()
        # 获取数据库中的观看时长信息
        with get_session() as session:
            stmt = select(
                EmbyUser.emby_id,
                EmbyUser.tg_id,
                EmbyUser.emby_watched_time,
                EmbyUser.emby_credits,
                EmbyUser.emby_username,
                EmbyUser.is_premium,
                EmbyUser.premium_status_updated_at,
                EmbyUser.premium_traffic_debt_bytes,
                EmbyUser.premium_traffic_debt_updated_date,
            )
            users = session.execute(stmt).fetchall()
        for user in users:
            playduration = round(float(duration.get(user[0], 0)) / 3600, 2)
            # 最大记 8
            daily_play_duration = playduration - user[2]
            credits_inc = min(daily_play_duration, 8)
            next_watched_time = max(playduration, user[2])
            emby_username, is_premium = user[4], user[5]
            premium_status_updated_at = user[6]
            debt_bytes = int(user[7] or 0)
            debt_updated_date = user[8]
            settlement_date = datetime.now(settings.TZ) - timedelta(days=1)
            is_premium_for_settlement = _resolve_premium_status_for_settlement(
                current_is_premium=bool(is_premium),
                premium_status_updated_at=premium_status_updated_at,
                settlement_date=settlement_date,
            )
            # 获取用户昨日的 premium 流量使用情况（用于流量费用计算）
            traffic_usage_premium = db.get_user_daily_traffic(
                username=emby_username,
                service="emby",
                date=settlement_date,
                premium_only=True,
            )
            # 获取用户昨日的总流量（用于流量惩罚计算）
            traffic_usage_total = db.get_user_daily_traffic(
                username=emby_username,
                service="emby",
                date=settlement_date,
                premium_only=False,
            )

            premium_traffic_result = _settle_premium_traffic_usage(
                traffic_usage_premium=traffic_usage_premium,
                is_premium=is_premium_for_settlement,
                debt_bytes=debt_bytes,
                debt_updated_date=debt_updated_date,
                settlement_date=settlement_date,
            )
            traffic_usage_exceed = premium_traffic_result["exceed_bytes"]
            traffic_cost_credits = premium_traffic_result["traffic_cost_credits"]
            if traffic_cost_credits > 0:
                deduction_records.append(
                    {
                        "service": "Emby",
                        "username": emby_username,
                        "tg_id": user[1],
                        "deducted_credits": traffic_cost_credits,
                        "chargeable_bytes": premium_traffic_result["chargeable_bytes"],
                    }
                )

            if (
                daily_play_duration <= 0
                and traffic_usage_total == 0
                and premium_traffic_result["debt_before_today"] == 0
                and premium_traffic_result["next_debt_bytes"] == 0
            ):
                if debt_bytes > 0 or debt_updated_date:
                    with get_session() as session:
                        stmt = (
                            sql_update(EmbyUser)
                            .where(EmbyUser.emby_id == user[0])
                            .values(
                                premium_traffic_debt_bytes=premium_traffic_result[
                                    "next_debt_bytes"
                                ],
                                premium_traffic_debt_updated_date=premium_traffic_result[
                                    "next_debt_updated_date"
                                ],
                            )
                        )
                        session.execute(stmt)
                continue

            # 计算超长观看惩罚 (TimePenalty)
            time_penalty = 0
            if daily_play_duration > 8 * 1.2:
                time_penalty = (daily_play_duration - 8 * 1.2) * 0.5

            # 计算超额流量惩罚 (DataPenalty) - 使用非premium流量
            data_penalty = 0
            data_ratio = 0
            expected_data = daily_play_duration * 10 * 1024 * 1024 * 1024  # 10 GB/小时
            if traffic_usage_total > 0 and expected_data > 0:
                data_ratio = float(traffic_usage_total) / float(expected_data)
                if data_ratio > 1.2:
                    data_penalty = float(credits_inc) * (data_ratio - 1.2) * 0.5

            # 应用惩罚到基础积分
            final_daily_score = max(
                0, min(credits_inc - time_penalty - data_penalty, 8)
            )
            # 保存原始 credits_inc 用于显示
            original_credits_inc = credits_inc
            credits_inc = final_daily_score

            # 计算勋章加成
            badge_bonus = 0
            badge_bonus_details = []
            if user[1]:
                active_badges = db.get_user_active_badges_with_bonus(user[1])
                for badge_info in active_badges:
                    bonus_percentage = float(badge_info["bonus_percentage"])
                    bonus_credits = float(credits_inc) * bonus_percentage
                    badge_bonus += bonus_credits
                    badge_bonus_details.append(
                        {
                            "name": badge_info["badge"]["name"],
                            "percentage": bonus_percentage * 100,
                            "credits": round(bonus_credits, 2),
                        }
                    )

            if not user[1]:
                _credits = user[3] + credits_inc - traffic_cost_credits
                with get_session() as session:
                    stmt = (
                        sql_update(EmbyUser)
                        .where(EmbyUser.emby_id == user[0])
                        .values(
                            emby_watched_time=next_watched_time,
                            emby_credits=_credits,
                            premium_traffic_debt_bytes=premium_traffic_result[
                                "next_debt_bytes"
                            ],
                            premium_traffic_debt_updated_date=premium_traffic_result[
                                "next_debt_updated_date"
                            ],
                        )
                    )
                    session.execute(stmt)
            else:
                stats_info = db.get_stats_by_tg_id(user[1])
                # statistics 表中有数据
                if stats_info:
                    credits_init = stats_info[2]
                    # 加上勋章加成
                    _credits = (
                        credits_init + credits_inc + badge_bonus - traffic_cost_credits
                    )
                    db.update_user_credits(_credits, tg_id=user[1])
                else:
                    # 清空 emby_user 表中积分信息
                    db.update_user_credits(0, emby_id=user[0])
                    # 在 statistic 表中增加用户数据
                    _credits = (
                        user[3] + credits_inc + badge_bonus - traffic_cost_credits
                    )
                    db.add_user_data(user[1], credits=_credits)
                # 更新 emby_user 表中观看时间
                with get_session() as session:
                    stmt = (
                        sql_update(EmbyUser)
                        .where(EmbyUser.emby_id == user[0])
                        .values(
                            emby_watched_time=next_watched_time,
                            premium_traffic_debt_bytes=premium_traffic_result[
                                "next_debt_bytes"
                            ],
                            premium_traffic_debt_updated_date=premium_traffic_result[
                                "next_debt_updated_date"
                            ],
                        )
                    )
                    session.execute(stmt)

            # 邀请人奖励：被邀请人基础积分的 10%，与被邀请人是否绑定 tg 无关
            # 累积到字典，循环结束后统一发通知
            inviter_tg_id = db.get_inviter_tg_id_by_emby_id(user[0])
            inviter_bonus = 0.0
            # 排除邀请人是自己的情况
            if inviter_tg_id and inviter_tg_id != user[1] and credits_inc > 0:
                inviter_bonus = round(credits_inc * 0.1, 2)
                if inviter_tg_id not in inviter_rewards:
                    inviter_rewards[inviter_tg_id] = {"total_bonus": 0.0, "details": []}
                inviter_rewards[inviter_tg_id]["total_bonus"] = round(
                    inviter_rewards[inviter_tg_id]["total_bonus"] + inviter_bonus, 2
                )
                inviter_rewards[inviter_tg_id]["details"].append(
                    {
                        "username": emby_username,
                        "base_credits": round(credits_inc, 2),
                        "bonus": inviter_bonus,
                    }
                )
                logger.info(
                    f"累积邀请人 {inviter_tg_id} 的奖励积分: +{inviter_bonus} (来自用户 {emby_username} ({user[0]}))"
                )

            if user[1] and (playduration - user[2]) > 0:
                # 构建勋章加成信息 - 只显示总加成积分
                badge_bonus_text = ""
                if badge_bonus > 0:
                    badge_bonus_text = f"\n勋章加成积分: +{round(badge_bonus, 2)}"

                # 构建惩罚信息 - 只显示总惩罚分数
                total_penalty = time_penalty + data_penalty
                penalty_text = ""
                if total_penalty > 0:
                    penalty_text = f"\n观看消耗积分: -{round(total_penalty, 2)}"

                # 构建邀请人奖励信息
                inviter_bonus_text = ""
                if inviter_bonus > 0:
                    inviter_bonus_text = (
                        f"\n邀请人额外奖励: +{inviter_bonus} (已发放给邀请人)"
                    )

                # 需要发送消息通知
                notification_tasks.append(
                    (
                        user[1],
                        f"""
Emby 观看积分更新通知
====================

新增观看时长: {round(playduration - user[2], 2)} 小时
基础观看积分: {round(original_credits_inc, 2)}{penalty_text}{badge_bonus_text}{inviter_bonus_text}
Premium 流量使用情况: {round(traffic_usage_premium / (1024 * 1024 * 1024), 2)} GB
Premium 当日可用免费额度: {round(premium_traffic_result["effective_limit"] / (1024 * 1024 * 1024), 2)} GB
Premium 当日前待偿还额度: {round(premium_traffic_result["debt_before_today"] / (1024 * 1024 * 1024), 2)} GB
Premium 自动偿还额度: {round(premium_traffic_result["recovered_before_today"] / (1024 * 1024 * 1024), 2)} GB
Premium 当日超额流量: {max(round(traffic_usage_exceed / (1024 * 1024 * 1024), 2), 0)} GB
Premium 结转待偿还额度: {round(premium_traffic_result["next_debt_bytes"] / (1024 * 1024 * 1024), 2)} GB
Premium 实际扣费流量: {round(premium_traffic_result["chargeable_bytes"] / (1024 * 1024 * 1024), 2)} GB
Premium 流量消耗积分: {round(traffic_cost_credits, 2)}

积分变化: {round(credits_inc + badge_bonus - traffic_cost_credits, 2):+.2f}

--------------------

当前总积分: {round(_credits, 2)}
当前总观看时长: {round(playduration, 2)} 小时

====================""",
                    )
                )

            logger.info(
                f"更新 Emby 用户 {emby_username} ({user[0]}) 的积分和观看时长: "
                f"新增观看时长 {round(playduration - user[2], 2)} 小时，新增观看积分 {round(credits_inc, 2)} (原始: {round(original_credits_inc, 2)}, 时长惩罚: {round(time_penalty, 2)}, 流量惩罚: {round(data_penalty, 2)}), 流量消耗积分 {round(traffic_cost_credits, 2)}"
            )

        # 循环结束后，统一更新邀请人积分并发送汇总通知
        for inviter_tg_id, reward_info in inviter_rewards.items():
            total_bonus = reward_info["total_bonus"]
            details = reward_info["details"]
            inviter_credits_now = db.get_user_credits(inviter_tg_id)
            if inviter_credits_now is None:
                logger.warning(
                    f"邀请人 {inviter_tg_id} 在 statistics 表中无记录，跳过奖励"
                )
                continue
            db.update_user_credits(
                inviter_credits_now + total_bonus, tg_id=inviter_tg_id
            )
            logger.info(
                f"邀请人 {inviter_tg_id} 共获得 Emby 邀请奖励积分: +{total_bonus}"
            )
            # 构建明细行
            detail_lines = "\n".join(
                f"  · {d['username']}: 基础积分 {d['base_credits']} → 奖励 +{d['bonus']}"
                for d in details
            )
            stat_date = (datetime.now(settings.TZ) - timedelta(days=1)).strftime(
                "%Y-%m-%d"
            )
            notification_tasks.append(
                (
                    inviter_tg_id,
                    f"""
Emby 邀请奖励通知
====================

{stat_date} 共 {len(details)} 位被邀请用户有新增观看记录:
{detail_lines}

本次邀请奖励积分: +{total_bonus}

--------------------

当前总积分: {round(inviter_credits_now + total_bonus, 2)}

====================""",
                )
            )

    except Exception as e:
        logger.error(f"更新 Emby 用户积分及观看时长失败: {e}")
        for chat_id in settings.TG_ADMIN_CHAT_ID:
            notification_tasks.append(
                (
                    chat_id,
                    f"更新 Emby 用户积分及观看时长失败: {e}",
                )
            )
        return notification_tasks, deduction_records
    else:
        logger.info("Emby 用户积分及观看时长更新完成")
        return notification_tasks, deduction_records


async def update_credits():
    """更新 Plex 和 Emby 用户积分及观看时长"""
    # 必须先清理幽灵会话：否则 get_home_stats 取到的仍是被夸大的脏数据。
    # 清理任务自身已吞掉异常，失败不会阻断后续结算。
    ghost_summary = clean_tautulli_ghost_sessions()

    notification_tasks, deduction_records = update_plex_credits()
    emby_notification_tasks, emby_deduction_records = update_emby_credits()
    notification_tasks.extend(emby_notification_tasks)
    deduction_records.extend(emby_deduction_records)

    if deduction_records and settings.TG_ADMIN_CHAT_ID:
        admin_message = _format_premium_traffic_deduction_summary(deduction_records)
        for chat_id in settings.TG_ADMIN_CHAT_ID:
            notification_tasks.append((chat_id, admin_message))

    # 有清理动作或有待人工确认的记录时才打扰管理员
    if (
        ghost_summary["ghosts"]
        or ghost_summary["undetermined"]
        or ghost_summary["failed"]
    ) and settings.TG_ADMIN_CHAT_ID:
        ghost_message = _format_ghost_session_summary(ghost_summary)
        for chat_id in settings.TG_ADMIN_CHAT_ID:
            notification_tasks.append((chat_id, ghost_message))

    for tg_id, text in notification_tasks:
        # 发送通知消息，静默模式
        await send_message_by_url(chat_id=tg_id, text=text, disable_notification=True)
        await asyncio.sleep(1)


async def clean_ghost_sessions_job():
    """独立的幽灵会话清理任务（高频）

    与结算前那次清理是同一套逻辑，区别只在于不接结算：幽灵记录在被清掉之前会
    污染 webapp 的时长展示与观看时长榜，靠这个任务把脏数据的暴露窗口从一天
    缩短到几小时。补偿与否由结算水位线判定，与本任务何时运行无关。
    """
    summary = clean_tautulli_ghost_sessions()

    if not (summary["ghosts"] or summary["failed"]):
        # 无事发生就不打扰管理员；「无法判定」留给结算前那次汇总一并报告
        return

    if not settings.TG_ADMIN_CHAT_ID:
        return

    message = _format_ghost_session_summary(summary)
    for chat_id in settings.TG_ADMIN_CHAT_ID:
        await send_message_by_url(
            chat_id=chat_id, text=message, disable_notification=True
        )
        await asyncio.sleep(1)


def update_plex_info(
    plex_name=True, plex_id=True, plex_avatar=True, target_email: Optional[str] = None
):
    """更新 plex 用户信息"""
    _plex = Plex()
    try:
        if plex_name:
            users = _plex.users_by_id
            cache_clear_users = []
            for uid, user in users.items():
                email = user[1].email
                username = user[0]
                with get_session() as session:
                    existing_user = session.execute(
                        select(PlexUser).where(PlexUser.plex_id == uid)
                    ).fetchone()
                    if (
                        existing_user
                        and existing_user[0].plex_username == username
                        and existing_user[0].plex_email == email
                    ):
                        logger.info(
                            f"Plex 用户 {username}({uid}) 的用户名和邮箱未发生变化，跳过更新"
                        )
                        continue
                    plex_username = existing_user[0].plex_username
                    cache_clear_users.append(plex_username)
                    stmt = (
                        sql_update(PlexUser)
                        .where(PlexUser.plex_id == uid)
                        .values(plex_username=username, plex_email=email)
                    )
                    session.execute(stmt)
                logger.info(
                    f"成功更新 Plex 用户 {uid} 的用户名: {username}, 邮箱: {email}"
                )
                # 更新流量表中的用户名
                if not db.update_traffic_username(
                    old_username=plex_username,
                    new_username=username,
                ):
                    logger.error(
                        f"更新流量表中的用户名失败: {plex_username} -> {username}"
                    )
            # 清除缓存中的用户信息
            if cache_clear_users:
                plex_token_dict = plex_token_cache.get_all_key_values()
                for token, _plex_username in plex_token_dict.items():
                    if _plex_username in cache_clear_users:
                        plex_token_cache.delete(token)
                        logger.info(f"已清除 Plex 用户 {_plex_username} 的 Token 缓存")

        if plex_id:
            # 检查是否存在 plex_id 为空的用户
            with get_session() as session:
                if target_email:
                    # 如果指定了目标邮箱,只处理该邮箱
                    stmt = select(PlexUser.plex_email).where(
                        PlexUser.plex_id.is_(None), PlexUser.plex_email == target_email
                    )
                else:
                    # 处理所有 plex_id 为空的用户
                    stmt = select(PlexUser.plex_email).where(PlexUser.plex_id.is_(None))
                empty_plex_users = session.execute(stmt).fetchall()

            for user in empty_plex_users:
                email = user[0]
                # 处理 plex_id 为空的用户
                plex_id = _plex.get_user_id_by_email(email)
                plex_username = (
                    _plex.get_username_by_user_id(plex_id) if plex_id else None
                )
                if plex_id and plex_username:
                    with get_session() as session:
                        stmt = (
                            sql_update(PlexUser)
                            .where(PlexUser.plex_email == email)
                            .values(plex_id=plex_id, plex_username=plex_username)
                        )
                        session.execute(stmt)
                    logger.info(f"成功更新 Plex 用户 {email} 的 plex_id: {plex_id}")

                    # 同步更新 invitation 表中对应邀请码的 plex_id
                    if db.update_invitation_plex_id(plex_email=email, plex_id=plex_id):
                        logger.info(
                            f"成功更新邀请码记录中 Plex 用户 {email} 的 plex_id: {plex_id}"
                        )
                    else:
                        logger.warning(
                            f"更新邀请码记录中 Plex 用户 {email} 的 plex_id 失败或无需更新"
                        )

                    # 如果是针对特定邮箱的调度任务，且成功获取到 plex_id，则标记任务待删除
                    if target_email and email.lower() == target_email.lower():
                        # 使用延迟删除，避免在任务执行过程中删除自己
                        import threading

                        def delayed_job_removal():
                            try:
                                import time

                                # 等待当前任务执行完成
                                time.sleep(2)
                                from app.scheduler import Scheduler

                                scheduler = Scheduler()
                                job_id = f"update_plex_info_for_{target_email}"
                                scheduler.remove_job(job_id)
                                logger.info(f"成功删除调度任务: {job_id}")
                            except Exception as e:
                                logger.warning(f"延迟删除调度任务失败: {e}")

                        # 在新线程中执行删除操作
                        threading.Thread(
                            target=delayed_job_removal, daemon=True
                        ).start()
                        logger.info(
                            f"已标记删除调度任务: update_plex_info_for_{target_email}"
                        )
                else:
                    logger.warning(
                        f"无法找到 Plex 用户 {email} 的 ID 或用户名，跳过更新。"
                    )
        # 更新所有用户的头像
        if plex_avatar:
            _plex.update_all_user_avatars()
    except Exception as e:
        print(e)


def update_all_lib():
    """更新用户资料库权限状态"""
    _plex = Plex()
    try:
        users = _plex.users_by_email
        all_libs = _plex.get_libraries()
        for email, user in users.items():
            if not email:
                continue
            with get_session() as session:
                stmt = select(PlexUser).where(PlexUser.plex_email == email)
                _info = session.execute(stmt).fetchone()
            if not _info:
                continue
            cur_libs = _plex.get_user_shared_libs_by_id(user[0])
            all_lib_flag = 1 if not set(all_libs).difference(set(cur_libs)) else 0
            with get_session() as session:
                stmt = (
                    sql_update(PlexUser)
                    .where(PlexUser.plex_email == email)
                    .values(all_lib=all_lib_flag)
                )
                session.execute(stmt)
    except Exception as e:
        print(e)


def add_all_plex_user():
    """将所有 plex 用户均加入到数据库中"""

    duration = get_user_total_duration(
        Tautulli().get_home_stats(
            36500, "duration", len(Plex().users_by_id), "top_users"
        )
    )
    _plex = Plex()
    users = [user for user in _plex.my_plex_account.users()]
    users.append(_plex.my_plex_account)
    all_libs = Plex().get_libraries()
    try:
        with get_session() as session:
            stmt = select(PlexUser.plex_id)
            existing_users = [user[0] for user in session.execute(stmt).fetchall()]
        for user in users:
            # 已存在用户及未接受邀请用户跳过
            if user.id in existing_users or (not user.email):
                continue
            watched_time = duration.get(user.id, 0)
            try:
                cur_libs = _plex.get_user_shared_libs_by_id(user.id)
            # 跳过分享给我的用户
            except Exception as e:
                print(e)
                continue
            all_lib_flag = 1 if not set(all_libs).difference(set(cur_libs)) else 0
            db.add_plex_user(
                plex_id=user.id,
                tg_id=None,
                plex_email=user.email,
                plex_username=user.username,
                credits=watched_time,
                all_lib=all_lib_flag,
                watched_time=watched_time,
            )

    except Exception as e:
        print(e)


def update_donation_credits(old_multiplier, new_multiplier):
    """
    更新捐赠积分

    Args:
        old_multiplier: 旧的积分倍数
        new_multiplier: 新的积分倍数
    """
    try:
        # 获取所有捐赠记录
        with get_session() as session:
            stmt = select(
                Statistics.tg_id, Statistics.donation, Statistics.credits
            ).where(Statistics.donation > 0)
            donations = session.execute(stmt).fetchall()

        for tg_id, donation, credits in donations:
            # 计算新的积分
            new_credits = round(
                credits + donation * (new_multiplier - old_multiplier), 2
            )
            # 更新数据库
            with get_session() as session:
                stmt = (
                    sql_update(Statistics)
                    .where(Statistics.tg_id == tg_id)
                    .values(credits=new_credits)
                )
                session.execute(stmt)
            logger.info(
                f"用户 {tg_id} 捐赠：{donation}, 更新积分: {credits} -> {new_credits}"
            )

    except Exception as e:
        logger.error(str(e))


def add_redeem_code(tg_id=None, num=1, is_privileged=False):
    """
    生成邀请码

    Args:
        tg_id: 用户ID，None表示为所有用户生成
        num: 生成数量
        is_privileged: 是否生成特权邀请码
    """
    from app.config import settings

    if tg_id is None:
        with get_session() as session:
            stmt = select(Statistics.tg_id)
            tg_id = [u[0] for u in session.execute(stmt).fetchall()]
    elif not isinstance(tg_id, list):
        tg_id = [tg_id]
    try:
        for uid in tg_id:
            for _ in range(num):
                code = uuid3(NAMESPACE_URL, str(uid + time())).hex
                db.add_invitation_code(code, owner=uid)

                # 如果是特权邀请码，添加到特权码列表
                if is_privileged:
                    if code not in settings.PRIVILEGED_CODES:
                        settings.PRIVILEGED_CODES.append(code)
                        # 保存到配置文件
                        settings.save_config_to_env_file(
                            {"PRIVILEGED_CODES": ",".join(settings.PRIVILEGED_CODES)}
                        )
                        logger.info(
                            f"添加特权邀请码 {code} 给用户 {get_user_name_from_tg_id(uid)}"
                        )
                else:
                    logger.info(
                        f"添加邀请码 {code} 给用户 {get_user_name_from_tg_id(uid)}"
                    )
    except Exception as e:
        print(e)


async def finish_expired_auctions_job():
    """定时任务：结束过期的竞拍活动"""
    try:
        finished_auctions = db.finish_expired_auctions()
        # 通知用户
        for autction in finished_auctions:
            await send_message_by_url(
                autction.get("winner_id"),
                f"恭喜你，竞拍 {autction['title']} 获胜！最终出价为 {autction['final_price']} 积分",
            )
            if not autction.get("credits_reduced", False):
                # 如果未扣除积分，通知管理员
                for chat_id in settings.TG_ADMIN_CHAT_ID:
                    await send_message_by_url(
                        chat_id=chat_id,
                        text=f"用户 {autction.get('winner_id')} 在竞拍 {autction['title']} 中获胜，但未扣除积分。",
                    )
        return finished_auctions
    except Exception as e:
        logger.error(f"自动结束过期竞拍失败: {e}")


async def check_prediction_markets_closing_soon_job() -> list[dict]:
    """定时任务：每小时检查押注中且 6 小时内截止的大预言家题目，并发送群组汇总通知。"""
    try:
        now_ts = int(time())
        deadline_upper_ts = int(now_ts + 6 * 3600)

        with get_session() as session:
            rows = (
                session.execute(
                    select(PredictionMarket)
                    .where(
                        PredictionMarket.status == 1,
                        PredictionMarket.betting_deadline.is_not(None),
                        PredictionMarket.betting_deadline > int(now_ts),
                        PredictionMarket.betting_deadline <= int(deadline_upper_ts),
                    )
                    .order_by(PredictionMarket.betting_deadline.asc())
                )
                .scalars()
                .all()
            )

            markets = [
                {
                    "id": int(m.id),
                    "title": str(m.title or ""),
                    "betting_deadline": int(m.betting_deadline),
                }
                for m in rows
                if m.betting_deadline is not None
            ]

            if not markets:
                logger.info("大预言家截止提醒检查完成：未来 6 小时内无押注截止题目")
                return []

        from app.webapp.routers.activities.prediction import (
            notify_prediction_markets_closing_soon,
        )

        await notify_prediction_markets_closing_soon(
            markets=markets,
            threshold_hours=6,
        )
        logger.info(
            f"大预言家截止提醒已发送：count={len(markets)}, window=(now, now+6h]"
        )
        return markets
    except Exception as e:
        logger.error(f"检查大预言家题目截止提醒失败: {e}")
        return []


async def monthly_traffic_data_migration():
    """定时任务：月度流量数据迁移聚合"""
    try:
        # 检查今天是否是每月1号
        now = datetime.now(settings.TZ)
        if now.day != 1:
            logger.info(
                f"今天不是每月1号，跳过月度流量数据迁移任务。当前日期: {now.strftime('%Y-%m-%d')}"
            )
            return

        # 获取上个月的年月字符串
        last_month = now.replace(day=1) - timedelta(days=1)
        target_month = last_month.strftime("%Y-%m")

        logger.info(f"开始执行月度流量数据迁移任务，目标月份: {target_month}")

        # 第一步：聚合上个月的数据
        success, message = db.aggregate_monthly_traffic_data(target_month)

        if success:
            logger.info(f"数据聚合成功: {message}")

            # 第二步：清理原始数据
            cleanup_success, cleanup_message = db.cleanup_monthly_traffic_data(
                target_month
            )

            if cleanup_success:
                logger.info(f"数据清理成功: {cleanup_message}")

                # 通知管理员成功
                notification_message = f"""
月度流量数据迁移完成
=====================

目标月份：{target_month}
聚合结果：{message}
清理结果：{cleanup_message}

====================="""

                for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
                    await send_message_by_url(
                        chat_id=admin_chat_id,
                        text=notification_message,
                        disable_notification=True,
                    )
            else:
                # 聚合成功但清理失败
                error_message = f"月度流量数据聚合成功，但清理失败: {cleanup_message}"
                logger.error(error_message)

                for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
                    await send_message_by_url(
                        chat_id=admin_chat_id,
                        text=f"⚠️ {error_message}",
                    )
        else:
            # 聚合失败
            error_message = f"月度流量数据聚合失败: {message}"
            logger.error(error_message)

            for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
                await send_message_by_url(
                    chat_id=admin_chat_id,
                    text=f"❌ {error_message}",
                )

        return success, message

    except Exception as e:
        error_msg = f"月度流量数据迁移任务执行失败: {e}"
        logger.error(error_msg)

        for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
            await send_message_by_url(
                chat_id=admin_chat_id,
                text=f"❌ {error_msg}",
            )

        return False, error_msg


async def update_line_traffic_stats(
    count: int = settings.REDIS_LINE_TRAFFIC_STATS_HANDLE_SIZE,
):
    """
    更新线路的流量数据
    """

    source_queue = "filebeat_nginx_stream_logs"
    processing_queue = "filebeat_nginx_stream_logs_processing"

    def _build_line_traffic_event_hash(
        backend: str,
        service: str,
        username: str,
        user_id: Optional[str],
        formatted_timestamp: str,
        decoded_uri: str,
        bytes_sent: int,
        upstream: Optional[str],
        upstream_response_time: Optional[str],
    ) -> str:
        raw = json.dumps(
            {
                "line": backend,
                "service": service,
                "username": username,
                "user_id": user_id or "",
                "timestamp": formatted_timestamp,
                "request_uri": decoded_uri,
                "send_bytes": int(bytes_sent),
                "upstream": upstream or "",
                "upstream_response_time": upstream_response_time or "",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _move_source_logs_to_processing_queue(fetch_count: int) -> list[str]:
        if fetch_count <= 0:
            return []

        move_script = """
local source_queue = KEYS[1]
local processing_queue = KEYS[2]
local fetch_count = tonumber(ARGV[1]) or 0
local moved = {}

if fetch_count <= 0 then
    return moved
end

for i = 1, fetch_count do
    local value = redis.call('LPOP', source_queue)
    if not value then
        break
    end
    moved[#moved + 1] = value
    redis.call('RPUSH', processing_queue, value)
end

return moved
"""

        result = stream_traffic_cache.redis_client.eval(
            move_script,
            2,
            source_queue,
            processing_queue,
            fetch_count,
        )
        return result or []

    def _finalize_processing_logs(
        processed_log_count: int, failed_positions: list[int]
    ) -> None:
        if processed_log_count <= 0:
            return

        finalize_script = """
local processing_queue = KEYS[1]
local processed_log_count = tonumber(ARGV[1]) or 0
local failed_positions = {}
local failed_values = {}

for i = 2, #ARGV do
    failed_positions[tonumber(ARGV[i])] = true
end

for i = 1, processed_log_count do
    local value = redis.call('LPOP', processing_queue)
    if not value then
        break
    end

    if failed_positions[i] then
        failed_values[#failed_values + 1] = value
    end
end

for i = 1, #failed_values do
    redis.call('RPUSH', processing_queue, failed_values[i])
end

return #failed_values
"""

        args = [processed_log_count, *failed_positions]
        stream_traffic_cache.redis_client.eval(
            finalize_script,
            1,
            processing_queue,
            *args,
        )

    values = []
    transferred_count = 0
    emby = None
    try:
        remaining = max(int(count), 0)
        if remaining > 0:
            processing_values = stream_traffic_cache.redis_client.lrange(
                processing_queue, 0, remaining - 1
            )
            if processing_values:
                values.extend(processing_values)
                remaining -= len(processing_values)
                logger.info(f"从处理中队列获取 {len(processing_values)} 条日志")

        if remaining > 0:
            source_values = _move_source_logs_to_processing_queue(remaining)
            if source_values:
                logger.info(f"从源队列获取 {len(source_values)} 条日志")
                values.extend(source_values)
                transferred_count += len(source_values)
                remaining -= len(source_values)
    except Exception as e:
        logger.error(f"从 Redis 转移流量日志到处理中队列失败: {e}")
        traceback.print_exc()
        return

    if not values:
        logger.info("没有新的流量日志数据")
        return

    processed_count = 0
    acknowledged_count = 0
    duplicate_count = 0
    skipped_count = 0
    failed_positions = []

    plex_username_to_id = {}
    emby_username_to_id = {}

    try:
        with get_session() as session:
            # 加载所有 Plex 用户名到 ID 的映射
            stmt = select(PlexUser.plex_username, PlexUser.plex_id).where(
                PlexUser.plex_username.isnot(None), PlexUser.plex_id.isnot(None)
            )
            plex_users = session.execute(stmt).fetchall()
            plex_username_to_id = {
                username.lower(): plex_id
                for username, plex_id in plex_users
                if username
            }

            # 加载所有 Emby 用户名到 ID 的映射
            stmt = select(EmbyUser.emby_username, EmbyUser.emby_id).where(
                EmbyUser.emby_username.isnot(None), EmbyUser.emby_id.isnot(None)
            )
            emby_users = session.execute(stmt).fetchall()
            emby_username_to_id = {
                username.lower(): emby_id
                for username, emby_id in emby_users
                if username
            }
    except Exception as e:
        logger.error(f"加载用户ID映射失败: {e}")
        return

    try:
        # 阶段0：逐条解析（纯 CPU），收集待处理记录与各类计数
        parsed_records = []
        for index, raw_log in enumerate(values, start=1):
            try:
                # 解析 JSON 日志
                if isinstance(raw_log, bytes):
                    raw_log = raw_log.decode("utf-8")
                log_data = json.loads(raw_log)
            except json.JSONDecodeError as e:
                logger.error(f"JSON 解析错误: {e}, 原始数据: {raw_log}")
                failed_positions.append(index)
                continue
            except Exception as e:
                logger.error(f"处理日志时发生错误: {e}, 原始数据: {raw_log}")
                failed_positions.append(index)
                continue

            # 提取时间戳
            timestamp = log_data.get("@timestamp", "")
            # 提取后端服务器信息（线路）
            backend = log_data.get("backend", "")
            # 解析 message 字段中的 nginx 访问日志
            message = log_data.get("message", "")

            # 使用正则表达式解析 nginx 访问日志格式
            # 旧格式：'$remote_addr - $remote_user [$time_local] "$request" ' '$status $body_bytes_sent "$http_referer" ' '"$http_user_agent" "$http_x_forwarded_for"'
            # 新格式：'$remote_addr - $remote_user [$time_local] "$request" ' '$status $body_bytes_sent "$http_referer" ' '"$http_user_agent" "$http_x_forwarded_for" ' '"upstream: $upstream_addr" ' '"ups_resp_time: $upstream_response_time"'
            log_pattern = r'(\S+) - \S+? \[([^\]]+)\] "(\S+) ([^"]+) ([^"]+)" (\d+) (\d+) "([^"]*)"(?: "[^"]*" "[^"]*" "upstream: ([^"]*)" "ups_resp_time: ([^"]*)")?'
            match = re.match(log_pattern, message)

            if match:
                # 提取需要的字段
                access_time = match.group(2)
                url = match.group(4)
                status_code = int(match.group(6))
                bytes_sent = int(match.group(7))
                # 新格式的可选字段（旧格式时为 None）
                upstream = match.group(9)
                upstream_response_time = match.group(10)
            else:
                # stream 格式：'$remote_addr [$time_local] "$request" $status $body_bytes_sent '
                # 'rt=$request_time uct=$upstream_connect_time uht=$upstream_header_time urt=$upstream_response_time '
                # 'ua="$upstream_addr" us="$upstream_status" ...'
                stream_log_pattern = (
                    r'(\S+) \[([^\]]+)\] "(\S+) ([^"]+) ([^"]+)" (\d+) (\d+) '
                    r"rt=(\S+) uct=(\S+) uht=(\S+) urt=(\S+) "
                    r'ua="([^"]*)" us="([^"]*)"'
                )
                stream_match = re.match(stream_log_pattern, message)

                if not stream_match:
                    logger.warning(f"无法解析日志格式: {message}")
                    acknowledged_count += 1
                    skipped_count += 1
                    continue

                access_time = stream_match.group(2)
                url = stream_match.group(4)
                status_code = int(stream_match.group(6))
                bytes_sent = int(stream_match.group(7))
                upstream = stream_match.group(12)
                upstream_response_time = stream_match.group(11)

            # 只处理成功的请求 (2xx 状态码)
            if status_code < 200 or status_code >= 300:
                acknowledged_count += 1
                skipped_count += 1
                continue

            if not url.startswith("/stream") and not re.search(
                r"[Oo]riginal\.|[Ss]tream\.?", url
            ):
                # 只处理 /stream 路径的请求
                # 或者包含 "Original." 的请求（兼容下 emby 反代）
                logger.info(f"跳过非流媒体请求: {url}")
                acknowledged_count += 1
                skipped_count += 1
                continue

            # 解析 URL 获取服务信息
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            # URL 解码请求 URI（只保留路径部分，不包含查询参数）
            decoded_uri = unquote(parsed_url.path)

            # 检查服务和 token
            service_list = query_params.get("service")
            token_list = query_params.get("token")
            line_list = query_params.get("line")
            if not service_list or not token_list:
                if query_params.get("api_key"):
                    # 兼容 emby 反代
                    logger.warning(
                        f"缺少必要的参数 service 或 token，但发现 api_key: {url}"
                    )
                    service_list = ["emby"]
                    token_list = query_params.get("api_key")
                else:
                    # 如果没有 service 或 token，跳过此条记录
                    logger.warning(f"缺少必要的参数 service 或 token: {url}")
                    acknowledged_count += 1
                    skipped_count += 1
                    continue

            service = service_list[0]
            token = token_list[0]
            # 优先使用 line 参数，如果没有则使用 backend
            # line 可能是自定义线路，仍会统计到，只是在线路流量统计中不会显示
            backend = line_list[0] if line_list else backend
            if not backend:
                logger.warning(f"缺少 backend 信息: {url}")
                acknowledged_count += 1
                skipped_count += 1
                continue

            # 转换时间格式为 ISO 格式
            try:
                # 将 nginx 时间格式转换为 datetime 对象
                # 格式: 23/Jun/2025:15:43:03 +0000
                dt = datetime.strptime(access_time, "%d/%b/%Y:%H:%M:%S %z").astimezone(
                    settings.TZ
                )
                formatted_timestamp = dt.isoformat()
            except ValueError:
                # 如果解析失败，使用原始的 @timestamp
                formatted_timestamp = (
                    datetime.fromisoformat(timestamp)
                    .astimezone(settings.TZ)
                    .isoformat()
                    if timestamp
                    else ""
                )

            parsed_records.append(
                {
                    "index": index,
                    "line": backend,
                    "service": service,
                    "token": token,
                    "bytes_sent": bytes_sent,
                    "decoded_uri": decoded_uri,
                    "formatted_timestamp": formatted_timestamp,
                    "upstream": upstream,
                    "upstream_response_time": upstream_response_time,
                }
            )

        # 阶段1：解析 token -> username
        plex_tokens = {r["token"] for r in parsed_records if r["service"] == "plex"}
        emby_tokens = {r["token"] for r in parsed_records if r["service"] == "emby"}

        # 逐个查询去重后的 token：真正的优化是去重（同一 token 不再每条日志重复查），
        # 而非合并成一次 mget。逐条小请求对高延迟/抖动的远程 Redis 更稳健——
        # 单次卡顿只影响一个 token 并可重试，不会像一次大 mget 那样拖垮整批。
        plex_token_to_name = {t: plex_token_cache.get(t) for t in plex_tokens}
        emby_token_to_name = {t: emby_api_key_cache.get(t) for t in emby_tokens}

        emby_timeout_tokens = set()
        emby_miss_tokens = [t for t in emby_tokens if not emby_token_to_name.get(t)]
        if emby_miss_tokens:
            if emby is None:
                emby = Emby()
            fetched = await emby.get_emby_usernames_from_api_keys(emby_miss_tokens)
            for token, username in fetched.items():
                if username is Emby.FETCH_TIMEOUT:
                    emby_timeout_tokens.add(token)
                elif username:
                    emby_token_to_name[token] = username

        # 阶段2：组装待入库记录并分类
        to_insert = []  # (index, row, event_hash)
        for r in parsed_records:
            service = r["service"]
            token = r["token"]
            if service == "plex":
                username = plex_token_to_name.get(token)
            else:
                username = emby_token_to_name.get(token)

            # 如果无法获取到用户信息
            if not username:
                if token in emby_timeout_tokens:
                    # emby 查询超时，保留重试
                    failed_positions.append(r["index"])
                else:
                    logger.warning(f"无法找到 token 对应的用户名: {token}")
                    acknowledged_count += 1
                    skipped_count += 1
                continue

            # 使用内存缓存查询 user_id，避免数据库查询
            if service == "plex":
                user_id = plex_username_to_id.get(username.lower())
            else:
                user_id = emby_username_to_id.get(username.lower())

            event_hash = _build_line_traffic_event_hash(
                backend=r["line"],
                service=service,
                username=username,
                user_id=user_id,
                formatted_timestamp=r["formatted_timestamp"],
                decoded_uri=r["decoded_uri"],
                bytes_sent=r["bytes_sent"],
                upstream=r["upstream"],
                upstream_response_time=r["upstream_response_time"],
            )
            row = {
                "line": r["line"],
                "send_bytes": r["bytes_sent"],
                "service": service,
                "username": username,
                "user_id": user_id,
                "timestamp": r["formatted_timestamp"],
                "event_hash": event_hash,
                "request_uri": r["decoded_uri"],
                "upstream": r["upstream"],
                "upstream_response_time": r["upstream_response_time"],
            }
            to_insert.append((r["index"], row, event_hash))

        # 阶段3：批量写库并回填每条结果
        if to_insert:
            hash_status = db.bulk_create_line_traffic_entries(
                [row for _, row, _ in to_insert]
            )
            # 批内同一 event_hash 多条：首条按状态计数，其余计为重复，
            # 避免重复计入 processed（实际只入库一条）
            seen_hashes = set()
            for index, row, event_hash in to_insert:
                status = hash_status.get(event_hash, "failed")
                if status == "inserted":
                    if event_hash in seen_hashes:
                        duplicate_count += 1
                    else:
                        processed_count += 1
                    acknowledged_count += 1
                elif status == "duplicate":
                    duplicate_count += 1
                    acknowledged_count += 1
                else:
                    logger.error(
                        f"流量日志入库失败，将保留在处理中队列重试: event_hash={event_hash}"
                    )
                    failed_positions.append(index)
                seen_hashes.add(event_hash)

        if values:
            try:
                _finalize_processing_logs(
                    processed_log_count=len(values),
                    failed_positions=failed_positions,
                )
            except Exception as e:
                logger.error(f"批量确认处理完成的流量日志时发生错误: {e}")

        logger.info(
            f"流量日志处理完成: 本次转移 {transferred_count} 条, 成功新增 {processed_count} 条, 业务跳过 {skipped_count} 条, 重复跳过 {duplicate_count} 条, 已确认 {acknowledged_count} 条, 留待重试 {len(failed_positions)} 条"
        )

    except Exception as e:
        logger.error(f"更新线路流量统计时发生错误: {e}")


def rewrite_users_credits_to_redis():
    """
    将用户积分信息写入 redis 缓存
    """
    try:
        # 从 statistics 表中获取所有用户的积分信息
        with get_session() as session:
            stmt = select(Statistics.tg_id, Statistics.credits)
            stats = session.execute(stmt).fetchall()
        user_stats = {tg_id: credits for tg_id, credits in stats}
        # 获取 Plex 用户信息
        with get_session() as session:
            stmt = select(
                PlexUser.plex_id,
                PlexUser.tg_id,
                PlexUser.credits,
                PlexUser.plex_username,
            )
            plex_users = session.execute(stmt).fetchall()
        for user in plex_users:
            # 未接受邀请，此时数据库中的 plex_id 为空
            if not user[0]:
                continue
            tg_id = user[1]
            credits = user[2]
            plex_username = user[3]
            if tg_id:
                credits = user_stats.get(tg_id, 0)
            user_credits_cache.put(f"plex:{plex_username.lower()}", credits)
        # 获取 Emby 用户信息
        with get_session() as session:
            stmt = select(
                EmbyUser.emby_id,
                EmbyUser.tg_id,
                EmbyUser.emby_credits,
                EmbyUser.emby_username,
            )
            emby_users = session.execute(stmt).fetchall()
        for user in emby_users:
            tg_id = user[1]
            credits = user[2]
            emby_username = user[3]
            if tg_id:
                credits = user_stats.get(tg_id, 0)
            user_credits_cache.put(f"emby:{emby_username.lower()}", credits)
    except Exception as e:
        logger.error(f"检查用户积分时发生错误: {e}")


def write_user_info_cache():
    """
    将 user info 写入 redis 缓存
    """
    try:
        # 获取 Plex 用户信息
        with get_session() as session:
            stmt = select(
                PlexUser.plex_id,
                PlexUser.tg_id,
                PlexUser.plex_username,
                PlexUser.plex_email,
                PlexUser.is_premium,
                PlexUser.plex_line,
            )
            plex_users = session.execute(stmt).fetchall()
        for user in plex_users:
            plex_id = user[0]
            # 未接受邀请，此时数据库中的 plex_id 为空
            if not plex_id:
                continue
            tg_id = user[1]
            plex_username = user[2]
            plex_email = user[3]
            is_premium = user[4]
            plex_line = user[5]
            if plex_username:
                user_info_cache.put(
                    f"plex:{plex_username.lower()}",
                    json.dumps(
                        {
                            "plex_id": plex_id,
                            "tg_id": tg_id,
                            "plex_username": plex_username,
                            "plex_email": plex_email,
                            "is_premium": is_premium,
                        }
                    ),
                )
                if plex_line:
                    plex_user_defined_line_cache.put(
                        str(plex_username).lower(), plex_line
                    )
        # 获取 Emby 用户信息
        with get_session() as session:
            stmt = select(
                EmbyUser.emby_id,
                EmbyUser.tg_id,
                EmbyUser.emby_username,
                EmbyUser.is_premium,
                EmbyUser.emby_line,
            )
            emby_users = session.execute(stmt).fetchall()
        for user in emby_users:
            emby_id = user[0]
            tg_id = user[1]
            emby_username = user[2]
            is_premium = user[3]
            emby_line = user[4]
            if emby_username:
                user_info_cache.put(
                    f"emby:{emby_username.lower()}",
                    json.dumps(
                        {
                            "emby_id": emby_id,
                            "tg_id": tg_id,
                            "emby_username": emby_username,
                            "is_premium": is_premium,
                        }
                    ),
                )
                if emby_line:
                    emby_user_defined_line_cache.put(
                        str(emby_username).lower(), emby_line
                    )
    except Exception as e:
        logger.error(f"写入用户信息缓存时发生错误: {e}")


async def check_expired_crypto_donation_orders():
    """定时任务：检查并更新过期的 crypto 捐赠订单状态"""
    try:
        logger.info("开始检查过期的 crypto 捐赠订单")

        # 获取过期的订单（用于通知）
        expired_orders = db.get_expired_crypto_donation_orders()

        if not expired_orders:
            logger.info("没有找到过期的 crypto 捐赠订单")
            return

        # 更新过期订单状态
        updated_count = db.update_expired_crypto_donation_orders()

        if updated_count > 0:
            logger.info(f"成功更新 {updated_count} 个过期的 crypto 捐赠订单状态")

            # 准备通知消息
            notification_messages = []

            # 通知用户订单已过期
            for order in expired_orders:
                user_id = order["user_id"]
                order_id = order["order_id"]
                amount = order["amount"]
                crypto_type = order["crypto_type"]

                user_message = f"""
💰 Crypto 捐赠订单过期通知

订单号：{order_id}
金额：{amount:.2f} CNY
加密货币类型：{crypto_type}
状态：已过期

很抱歉，您的 Crypto 捐赠订单已超过有效期。如需继续捐赠，请重新创建订单。

感谢您对项目的支持！
"""

                notification_messages.append((user_id, user_message))

            # 通知管理员
            admin_message = f"""
📊 Crypto 捐赠订单过期统计

共处理过期订单：{updated_count} 个

详情：
"""
            for order in expired_orders:
                user_name = get_user_name_from_tg_id(order["user_id"])
                admin_message += f"• 用户：{user_name} ({order['user_id']}) - {order['amount']:.2f} CNY ({order['crypto_type']})\n"

            # 发送用户通知
            for user_id, message in notification_messages:
                try:
                    await send_message_by_url(
                        chat_id=user_id, text=message, disable_notification=False
                    )
                    await asyncio.sleep(0.5)  # 避免发送过于频繁
                except Exception as e:
                    logger.warning(f"向用户 {user_id} 发送过期订单通知失败: {e}")

            # 发送管理员通知
            for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
                try:
                    await send_message_by_url(
                        chat_id=admin_chat_id,
                        text=admin_message,
                        disable_notification=True,
                    )
                except Exception as e:
                    logger.warning(
                        f"向管理员 {admin_chat_id} 发送过期订单统计失败: {e}"
                    )

    except Exception as e:
        logger.error(f"检查过期 crypto 捐赠订单失败: {e}")


async def auto_switch_user_lines(
    tg_id: Optional[int] = None, service: Optional[str] = None
):
    """
    自动切换用户线路调度

    Args:
        tg_id: 可选，指定用户 ID，如果不指定则处理所有用户
        service: 可选，指定服务类型 ('plex' 或 'emby')，如果不指定则处理两种服务
    """
    try:
        switched_count = 0

        # 确定要处理的服务类型
        services_to_process = []
        if service:
            if service.lower() not in ["plex", "emby"]:
                logger.error(f"不支持的服务类型: {service}")
                return
            services_to_process = [service.lower()]
        else:
            services_to_process = ["plex", "emby"]

        # 获取所有解锁了线路调度功能的 Plex 用户（包括 premium 用户和解锁用户）
        with get_session() as session:
            # 处理 Plex 用户
            if "plex" in services_to_process:
                # 查询所有解锁了线路调度的 Plex 用户（包括 premium 用户）
                plex_query = select(
                    PlexUser.tg_id, PlexUser.plex_line, PlexUser.plex_username
                ).where(
                    or_(PlexUser.line_schedule_unlocked == 1, PlexUser.is_premium == 1)
                )

                # 如果指定了用户 ID，添加过滤条件
                if tg_id is not None:
                    plex_query = plex_query.where(PlexUser.tg_id == tg_id)

                plex_users = session.execute(plex_query).fetchall()
            else:
                plex_users = []

            for user_tg_id, current_line, plex_username in plex_users:
                logger.debug(f"开始处理 Plex 用户 {plex_username} 的线路调度任务")
                # 获取当前生效的调度
                active_schedule = db.get_current_active_schedule(user_tg_id, "plex")

                if active_schedule:
                    # 有生效的调度，使用调度指定的线路
                    # 线路可能为具体线路名，也可能为 'auto'（表示自动选择）
                    target_line = active_schedule["line"]
                else:
                    # 没有生效的调度，跳过不做修改
                    continue

                # 检查是否需要切换
                if current_line != target_line:
                    # 执行切换
                    if db.set_plex_line(line=target_line, tg_id=user_tg_id):
                        # 更新 Redis 缓存
                        if plex_username:
                            if target_line is None or target_line == "auto":
                                # 切换到自动选择，删除 Redis 缓存
                                plex_user_defined_line_cache.delete(
                                    str(plex_username).lower()
                                )
                            else:
                                # 切换到指定线路
                                binded_line = plex_user_defined_line_cache.get(
                                    str(plex_username).lower()
                                )
                                if binded_line and not is_binded_premium_line(
                                    binded_line
                                ):
                                    # 满足如下条件：
                                    # 1. 缓存中存在绑定的线路，且该线路不是高级线路；
                                    # 将其记录到上一次使用的普通线路缓存中
                                    logger.debug(
                                        f"记录用户 {plex_username} 上一次使用的普通线路 {binded_line}"
                                    )
                                    plex_last_user_defined_line_cache.put(
                                        str(plex_username).lower(), binded_line
                                    )
                                plex_user_defined_line_cache.put(
                                    str(plex_username).lower(), target_line
                                )

                        switched_count += 1
                        logger.info(
                            f"自动切换 Plex 用户 {plex_username} 的线路: {current_line or 'AUTO'} -> {target_line if target_line != 'auto' else 'AUTO'}"
                        )

            # 处理 Emby 用户
            if "emby" in services_to_process:
                # 查询所有解锁了线路调度的 Emby 用户（包括 premium 用户）
                emby_query = select(
                    EmbyUser.tg_id, EmbyUser.emby_line, EmbyUser.emby_username
                ).where(
                    or_(EmbyUser.line_schedule_unlocked == 1, EmbyUser.is_premium == 1)
                )

                # 如果指定了用户 ID，添加过滤条件
                if tg_id is not None:
                    emby_query = emby_query.where(EmbyUser.tg_id == tg_id)

                emby_users = session.execute(emby_query).fetchall()
            else:
                emby_users = []

            for user_tg_id, current_line, emby_username in emby_users:
                logger.debug(f"开始处理 Emby 用户 {emby_username} 的线路调度任务")
                # 获取当前生效的调度
                active_schedule = db.get_current_active_schedule(user_tg_id, "emby")

                if active_schedule:
                    # 有生效的调度，使用调度指定的线路
                    # 线路可能为具体线路名，也可能为 'auto'（表示自动选择）
                    target_line = active_schedule["line"]
                else:
                    # 没有生效的调度，跳过不做修改
                    continue

                # 检查是否需要切换
                if current_line != target_line:
                    # 执行切换
                    if db.set_emby_line(line=target_line, tg_id=user_tg_id):
                        # 更新 Redis 缓存
                        if emby_username:
                            if target_line is None or target_line == "auto":
                                # 切换到自动选择，删除 Redis 缓存
                                emby_user_defined_line_cache.delete(
                                    str(emby_username).lower()
                                )
                            else:
                                # 切换到指定线路
                                binded_line = emby_user_defined_line_cache.get(
                                    str(emby_username).lower()
                                )
                                if binded_line and not is_binded_premium_line(
                                    binded_line
                                ):
                                    # 满足如下条件：
                                    # 1. 缓存中存在绑定的线路，且该线路不是高级线路；
                                    # 将其记录到上一次使用的普通线路缓存中
                                    logger.debug(
                                        f"记录用户 {emby_username} 上一次使用的普通线路 {binded_line}"
                                    )
                                    emby_last_user_defined_line_cache.put(
                                        str(emby_username).lower(), binded_line
                                    )
                                emby_user_defined_line_cache.put(
                                    str(emby_username).lower(), target_line
                                )

                        switched_count += 1
                        logger.info(
                            f"自动切换 Emby 用户 {emby_username} 的线路: {current_line or 'AUTO'} -> {target_line if target_line != 'auto' else 'AUTO'}"
                        )
        # 生成详细的日志信息
        if tg_id is not None:
            user_info = f"用户 {get_user_name_from_tg_id(tg_id)} (ID: {tg_id})"
        else:
            user_info = "所有符合条件的用户"

        if service:
            service_info = f"{service.upper()} 服务"
        else:
            service_info = "Plex 和 Emby 服务"

        if switched_count > 0:
            logger.info(
                f"自动切换线路任务完成 - "
                f"处理范围: {user_info} | "
                f"服务类型: {service_info} | "
                f"成功切换: {switched_count} 条线路"
            )
        else:
            logger.info("自动切换线路任务完成，没有需要切换的线路")

    except Exception as e:
        logger.error(f"自动切换用户线路失败: {e}")


def update_emby_users_last_viewed_at():
    """更新所有Emby用户的最后观看时间"""
    logger.info("开始更新 Emby 用户最后观看时间")
    try:
        emby = Emby()
        # 获取所有用户的最后活动时间
        user_activities = emby.get_all_users_last_activity()

        if not user_activities:
            logger.warning("未获取到任何用户的最后活动时间")
            return

        # 批量更新数据库
        updated_count = 0
        with get_session() as session:
            for user_id, last_activity in user_activities.items():
                if last_activity is not None:
                    stmt = (
                        sql_update(EmbyUser)
                        .where(EmbyUser.emby_id == user_id)
                        .values(last_viewed_at=last_activity)
                    )
                    result = session.execute(stmt)
                    if result.rowcount > 0:
                        updated_count += 1

        logger.info(f"Emby 用户最后观看时间更新完成，共更新 {updated_count} 个用户")

    except Exception as e:
        logger.error(f"更新 Emby 用户最后观看时间失败: {e}")


def update_plex_users_last_viewed_at():
    """更新所有 Plex 用户的最后观看时间"""
    logger.info("开始更新 Plex 用户的最后观看时间")
    try:
        _plex = Plex()

        # 获取所有用户的最后观看时间
        last_viewed_dict = _plex.get_all_users_last_viewed_at()

        updated_count = 0
        with get_session() as session:
            for plex_id, last_viewed_at in last_viewed_dict.items():
                if last_viewed_at > 0:
                    stmt = (
                        sql_update(PlexUser)
                        .where(PlexUser.plex_id == plex_id)
                        .values(last_viewed_at=last_viewed_at)
                    )
                    result = session.execute(stmt)
                    if result.rowcount > 0:
                        updated_count += 1

        logger.info(f"成功更新 {updated_count} 个 Plex 用户的最后观看时间")

    except Exception as e:
        logger.error(f"更新 Plex 用户最后观看时间失败: {e}")


def update_users_last_viewed():
    """更新所有用户的最后观看时间"""
    from concurrent.futures import ThreadPoolExecutor, wait

    with ThreadPoolExecutor() as executor:
        future1 = executor.submit(update_plex_users_last_viewed_at)
        future2 = executor.submit(update_emby_users_last_viewed_at)
        wait([future1, future2])


async def check_and_award_supreme_contributor_badge(user_id: int = None):
    """
    检查并授予至尊贡献者勋章

    Args:
        user_id: 可选，指定用户的 Telegram ID。如果提供，只检查该用户；否则检查所有符合条件的用户。

    Returns:
        bool: 当指定 user_id 时，返回是否成功授予勋章；批量检查时返回 None
    """
    DONATION_THRESHOLD = 1688
    BADGE_TYPE = "supreme_contributor"

    if user_id:
        logger.info(f"检查用户 {user_id} 的至尊贡献者勋章资格...")
    else:
        logger.info("开始检查并授予至尊贡献者勋章...")

    try:
        # 1. 检查勋章是否存在，不存在则创建
        badge_info = db.get_badge_by_type(BADGE_TYPE)
        if not badge_info:
            logger.info(f"勋章 '{BADGE_TYPE}' 不存在，正在创建...")
            badge_info = db.create_badge(
                badge_type=BADGE_TYPE,
                name="至尊贡献者勋章",
                description="此勋章授予对平台有特殊贡献的用户",
                icon_url="/badges/supreme_contributor.svg",
                credits_cost=0,  # 由系统自动授予，不需要积分
                bonus_percentage=0.18,  # 18% 每日积分加成
                valid_days=36500,  # 约 100 年有效期
                is_enabled=0,  # 禁用兑换，仅由系统授予
            )
            if not badge_info:
                logger.error("创建至尊贡献者勋章失败")
                return False if user_id else None
            logger.info(f"成功创建至尊贡献者勋章，ID: {badge_info['id']}")

        badge_id = badge_info["id"]
        badge_name = badge_info.get("name", "至尊贡献者勋章")
        bonus_percentage = badge_info.get("bonus_percentage", 0.18)
        valid_days = badge_info.get("valid_days", 36500)

        # 2. 查询符合条件的用户
        with get_session() as session:
            if user_id:
                # 单用户模式：只查询指定用户
                user_donation = session.execute(
                    select(Statistics.donation).where(Statistics.tg_id == user_id)
                ).scalar_one_or_none()

                if user_donation is None or user_donation <= DONATION_THRESHOLD:
                    logger.info(
                        f"用户 {user_id} 捐赠金额 {user_donation} 未达到至尊贡献者门槛 {DONATION_THRESHOLD}"
                    )
                    return False

                eligible_users = [(user_id, user_donation)]
            else:
                # 批量模式：查询所有符合条件的用户
                stmt = select(Statistics.tg_id, Statistics.donation).where(
                    Statistics.donation > DONATION_THRESHOLD
                )
                eligible_users = session.execute(stmt).fetchall()

        if not eligible_users:
            if not user_id:
                logger.info(f"没有找到捐赠金额超过 {DONATION_THRESHOLD} 的用户")
            return False if user_id else None

        if not user_id:
            logger.info(f"找到 {len(eligible_users)} 位符合条件的用户")

        # 3. 为符合条件的用户授予勋章
        notification_tasks = []
        awarded_count = 0

        for tg_id, donation in eligible_users:
            try:
                with get_session() as session:
                    # 检查用户是否已拥有该勋章
                    existing = session.execute(
                        select(UserBadge).where(
                            UserBadge.tg_id == tg_id, UserBadge.badge_id == badge_id
                        )
                    ).scalar_one_or_none()

                    if existing:
                        if user_id:
                            logger.info(f"用户 {tg_id} 已拥有至尊贡献者勋章")
                            return False
                        continue

                    # 创建用户勋章记录
                    current_time = int(time())
                    expires_at = current_time + (valid_days * 24 * 3600)

                    user_badge_record = UserBadge(
                        tg_id=tg_id,
                        badge_id=badge_id,
                        credits_cost=0,
                        redeemed_at=current_time,
                        expires_at=expires_at,
                        is_active=1,
                    )
                    session.add(user_badge_record)

                    awarded_count += 1
                    logger.info(
                        f"已授予用户 {tg_id} (捐赠: {donation:.2f}) 至尊贡献者勋章"
                    )

                    # 添加用户通知任务
                    notification_tasks.append(
                        (
                            tg_id,
                            f"""🏆 恭喜获得勋章！
====================

勋章名称：{badge_name}
勋章权益：每日观看积分 +{bonus_percentage * 100:.0f}%
有效期限：永久

感谢您的支持与贡献！

====================""",
                        )
                    )

            except Exception as e:
                logger.error(f"授予用户 {tg_id} 勋章失败: {e}")
                if user_id:
                    return False
                continue

        if not user_id:
            if awarded_count > 0:
                logger.info(f"本次共授予 {awarded_count} 位用户至尊贡献者勋章")
            else:
                logger.info("所有符合条件的用户都已拥有至尊贡献者勋章")

        # 发送用户通知
        for tg_id, text in notification_tasks:
            try:
                await send_message_by_url(
                    chat_id=tg_id, text=text, disable_notification=False
                )
                if not user_id:
                    await asyncio.sleep(0.5)  # 批量模式下避免发送过于频繁
            except Exception as e:
                logger.warning(f"向用户 {tg_id} 发送勋章授予通知失败: {e}")

        return awarded_count > 0 if user_id else None

    except Exception as e:
        logger.error(f"检查并授予至尊贡献者勋章失败: {e}")
        return False if user_id else None


async def check_and_award_game_king_badge(
    user_id: Optional[int] = None,
) -> Optional[bool]:
    """
    检查并授予游戏王勋章。

    获取条件（满足任一）：
    - 幸运大转盘累计游戏次数 >= 5000 次
    - 夺宝奇兵累计参与期数 >= 500 期
    - 大预言家累计参与预测次数 >= 500 次
    - 21 点累计手数 >= 2000 手**且**决策准确率 >= 80%

    Args:
        user_id: 可选，指定用户的 Telegram ID。如果提供，只检查该用户；否则检查所有符合条件的用户。

    Returns:
        bool: 当指定 user_id 时，返回是否成功授予勋章；批量检查时返回 None。
    """
    WHEEL_SPIN_THRESHOLD = 5000
    TREASURE_ISSUE_THRESHOLD = 500
    PREDICTION_BET_THRESHOLD = 500
    # 21 点按平均注额 15 计，等价投入量约 3300 手；取 2000 手略低于等价投入量，
    # 因为单手需多次交互、耗时显著长于转盘一次点击，按投入量对等设定会形同虚设。
    #
    # 但**单以手数为条件是负期望游戏里的纯刷量激励**（2000 手 @ 注 15 的期望代价
    # 是 −720 积分）。叠加决策准确率后，这条件奖励的变成「把牌打好」而非「打得多」。
    # 80% 是刻意留出余地的阈值：严格照基本策略打是 100%，凭直觉打大约 70–85%。
    #
    # 两个阈值取自 21 点配置而非写死：spec 要求管理员可在线调整，SHALL NOT 需要
    # 重新部署。其余三个活动的阈值本就不属于 21 点，维持原样。
    _bj_config = db.get_blackjack_config_dict()
    BLACKJACK_HAND_THRESHOLD = int(_bj_config.get("badge_min_hands", 2000))
    BLACKJACK_ACCURACY_THRESHOLD = float(_bj_config.get("badge_min_accuracy", 80))
    # 终态集合以引擎常量为单一来源，避免与 db 层的口径各自漂移
    from app.blackjack_engine import TERMINAL_STATUSES as BLACKJACK_TERMINAL_STATUSES

    BADGE_TYPE = "game_king"

    if user_id:
        logger.info(f"检查用户 {user_id} 的游戏王勋章资格...")
    else:
        logger.info("开始批量检查并授予游戏王勋章...")

    try:
        # 1. 检查勋章是否存在，不存在则创建
        badge_info = db.get_badge_by_type(BADGE_TYPE)
        if not badge_info:
            logger.info(f"勋章 '{BADGE_TYPE}' 不存在，正在创建...")
            badge_info = db.create_badge(
                badge_type=BADGE_TYPE,
                name="游戏王勋章",
                description=(
                    f"此勋章授予游戏达人：大转盘累计游戏 {WHEEL_SPIN_THRESHOLD} 次，"
                    f"或夺宝奇兵累计参与 {TREASURE_ISSUE_THRESHOLD} 期，"
                    f"或大预言家累计参与预测 {PREDICTION_BET_THRESHOLD} 次，"
                    f"或 21 点累计 {BLACKJACK_HAND_THRESHOLD} 手"
                    f"且决策准确率达 {int(BLACKJACK_ACCURACY_THRESHOLD)}%"
                ),
                icon_url="/badges/game_king.svg",
                credits_cost=0,
                bonus_percentage=0,
                valid_days=36500,  # 约 100 年，永久有效
                is_enabled=0,  # 禁用兑换，仅由系统授予
            )
            if not badge_info:
                logger.error("创建游戏王勋章失败")
                return False if user_id else None
            logger.info(f"成功创建游戏王勋章，ID: {badge_info['id']}")

        badge_id = badge_info["id"]
        badge_name = badge_info.get("name", "游戏王勋章")
        valid_days = badge_info.get("valid_days", 36500)

        # 21 点的双条件统计在**开启事务之前**取好：get_user_blackjack_stats 自带
        # 一个 get_session()，在下方的 with 块内调用会同时占用两个连接。
        blackjack_count = 0
        blackjack_accuracy = 0.0
        if user_id:
            blackjack_stats = db.get_user_blackjack_stats(user_id)
            blackjack_count = int(blackjack_stats.get("total_hands") or 0)
            blackjack_accuracy = float(blackjack_stats.get("accuracy") or 0)

        # 2. 查询符合条件的用户
        with get_session() as session:
            if user_id:
                # 单用户模式：分别检查大转盘次数、夺宝参与期数、大预言家预测次数、21 点手数
                wheel_count = (
                    session.execute(
                        select(func.count(WheelStats.id)).where(
                            WheelStats.tg_id == user_id
                        )
                    ).scalar()
                    or 0
                )
                treasure_count = (
                    session.execute(
                        select(
                            func.count(distinct(TreasureParticipation.issue_id))
                        ).where(TreasureParticipation.tg_id == user_id)
                    ).scalar()
                    or 0
                )
                prediction_count = (
                    session.execute(
                        select(func.count(PredictionBet.id)).where(
                            PredictionBet.tg_id == user_id
                        )
                    ).scalar()
                    or 0
                )
                # 21 点为双条件：手数 + 决策准确率，两者须同时满足。
                # 统计已在事务外取好，见上方注释。
                blackjack_ok = (
                    blackjack_count >= BLACKJACK_HAND_THRESHOLD
                    and blackjack_accuracy >= BLACKJACK_ACCURACY_THRESHOLD
                )

                if (
                    wheel_count < WHEEL_SPIN_THRESHOLD
                    and treasure_count < TREASURE_ISSUE_THRESHOLD
                    and prediction_count < PREDICTION_BET_THRESHOLD
                    and not blackjack_ok
                ):
                    logger.info(
                        f"用户 {user_id} 不满足游戏王条件："
                        f"大转盘 {wheel_count}/{WHEEL_SPIN_THRESHOLD} 次，"
                        f"夺宝期数 {treasure_count}/{TREASURE_ISSUE_THRESHOLD} 期，"
                        f"大预言家预测 {prediction_count}/{PREDICTION_BET_THRESHOLD} 次，"
                        f"21 点 {blackjack_count}/{BLACKJACK_HAND_THRESHOLD} 手 "
                        f"且准确率 {blackjack_accuracy:.1f}%/{BLACKJACK_ACCURACY_THRESHOLD}%"
                    )
                    return False

                eligible_tg_ids = [user_id]
            else:
                # 批量模式：用 UNION 合并大转盘、夺宝奇兵、大预言家、21 点四个子查询
                wheel_subq = (
                    select(WheelStats.tg_id)
                    .group_by(WheelStats.tg_id)
                    .having(func.count(WheelStats.id) >= WHEEL_SPIN_THRESHOLD)
                )
                treasure_subq = (
                    select(TreasureParticipation.tg_id)
                    .group_by(TreasureParticipation.tg_id)
                    .having(
                        func.count(distinct(TreasureParticipation.issue_id))
                        >= TREASURE_ISSUE_THRESHOLD
                    )
                )
                prediction_subq = (
                    select(PredictionBet.tg_id)
                    .group_by(PredictionBet.tg_id)
                    .having(func.count(PredictionBet.id) >= PREDICTION_BET_THRESHOLD)
                )
                # 21 点为双条件：手数达标**且**准确率达标。准确率在 SQL 里算，
                # 避免把全部达手数的用户拉回 Python 再逐个查
                blackjack_subq = (
                    select(BlackjackHand.tg_id)
                    .where(BlackjackHand.status.in_(BLACKJACK_TERMINAL_STATUSES))
                    .group_by(BlackjackHand.tg_id)
                    .having(
                        func.count(BlackjackHand.id) >= BLACKJACK_HAND_THRESHOLD,
                        func.sum(BlackjackHand.decisions_total) > 0,
                        func.sum(BlackjackHand.decisions_correct) * 100.0
                        >= func.sum(BlackjackHand.decisions_total)
                        * BLACKJACK_ACCURACY_THRESHOLD,
                    )
                )
                union_stmt = union(
                    wheel_subq, treasure_subq, prediction_subq, blackjack_subq
                )
                rows = session.execute(union_stmt).fetchall()
                eligible_tg_ids = [row[0] for row in rows]

        if not eligible_tg_ids:
            if not user_id:
                logger.info("没有找到符合游戏王条件的用户")
            return False if user_id else None

        if not user_id:
            logger.info(f"找到 {len(eligible_tg_ids)} 位符合游戏王条件的用户")

        # 3. 为符合条件的用户授予勋章
        notification_tasks = []
        awarded_count = 0

        for tg_id in eligible_tg_ids:
            try:
                with get_session() as session:
                    # 检查用户是否已拥有该勋章（幂等保护）
                    existing = session.execute(
                        select(UserBadge).where(
                            UserBadge.tg_id == tg_id, UserBadge.badge_id == badge_id
                        )
                    ).scalar_one_or_none()

                    if existing:
                        if user_id:
                            logger.info(f"用户 {tg_id} 已拥有游戏王勋章")
                            return False
                        continue

                    # 创建用户勋章记录
                    current_time = int(time())
                    expires_at = current_time + (valid_days * 24 * 3600)

                    user_badge_record = UserBadge(
                        tg_id=tg_id,
                        badge_id=badge_id,
                        credits_cost=0,
                        redeemed_at=current_time,
                        expires_at=expires_at,
                        is_active=1,
                    )
                    session.add(user_badge_record)

                    awarded_count += 1
                    logger.info(f"已授予用户 {tg_id} 游戏王勋章")

                    notification_tasks.append(
                        (
                            tg_id,
                            f"🎮 恭喜获得勋章！\n"
                            f"====================\n\n"
                            f"勋章名称：{badge_name}\n"
                            f"有效期限：永久\n\n"
                            f"感谢您的热情参与！\n\n"
                            f"====================",
                        )
                    )

            except Exception as e:
                logger.error(f"授予用户 {tg_id} 游戏王勋章失败: {e}")
                if user_id:
                    return False
                continue

        if not user_id:
            if awarded_count > 0:
                logger.info(f"本次共授予 {awarded_count} 位用户游戏王勋章")
            else:
                logger.info("所有符合条件的用户都已拥有游戏王勋章")

        # 4. 发送用户通知
        for tg_id, text in notification_tasks:
            try:
                await send_message_by_url(
                    chat_id=tg_id, text=text, disable_notification=False
                )
                if not user_id:
                    await asyncio.sleep(0.5)  # 批量模式下避免发送过于频繁
            except Exception as e:
                logger.warning(f"向用户 {tg_id} 发送游戏王勋章通知失败: {e}")

        return awarded_count > 0 if user_id else None

    except Exception as e:
        logger.error(f"检查并授予游戏王勋章失败: {e}")
        return False if user_id else None


if __name__ == "__main__":
    update_plex_credits()
    update_plex_info()
    # add_all_plex_user()
    update_emby_credits()
    # 测试流量统计更新
    # update_line_traffic_stats()
