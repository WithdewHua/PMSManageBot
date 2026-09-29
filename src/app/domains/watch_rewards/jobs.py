import asyncio

from app.core.config import settings
from app.domains.watch_rewards.notifications import (
    _format_ghost_session_summary,
    _format_premium_traffic_deduction_summary,
)
from app.domains.watch_rewards.service import (
    clean_tautulli_ghost_sessions,
    update_emby_credits,
    update_plex_credits,
)
from app.integrations.telegram.messaging import send_message_by_url


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
