import asyncio

from app.core.config import settings
from app.domains.watch_rewards import notifications, service
from app.integrations.telegram.messaging import send_message_by_url


def _settle_all() -> tuple[dict, tuple[list, list], tuple[list, list]]:
    """Keep cleanup and both settlements ordered in a single worker thread."""
    ghost_summary = service.clean_tautulli_ghost_sessions()
    plex_result = service.update_plex_credits()
    emby_result = service.update_emby_credits()
    return ghost_summary, plex_result, emby_result


async def update_credits() -> None:
    """更新 Plex 和 Emby 用户积分及观看时长。"""
    ghost_summary, plex_result, emby_result = await asyncio.to_thread(_settle_all)
    notification_tasks, deduction_records = plex_result
    emby_notification_tasks, emby_deduction_records = emby_result
    notification_tasks.extend(emby_notification_tasks)
    deduction_records.extend(emby_deduction_records)

    if deduction_records and settings.TG_ADMIN_CHAT_ID:
        admin_message = notifications._format_premium_traffic_deduction_summary(
            deduction_records
        )
        notification_tasks.extend(
            (chat_id, admin_message) for chat_id in settings.TG_ADMIN_CHAT_ID
        )
    if (
        ghost_summary["ghosts"]
        or ghost_summary["undetermined"]
        or ghost_summary["failed"]
    ) and settings.TG_ADMIN_CHAT_ID:
        ghost_message = notifications._format_ghost_session_summary(ghost_summary)
        notification_tasks.extend(
            (chat_id, ghost_message) for chat_id in settings.TG_ADMIN_CHAT_ID
        )

    for tg_id, text in notification_tasks:
        await send_message_by_url(chat_id=tg_id, text=text, disable_notification=True)
        await asyncio.sleep(1)


async def clean_ghost_sessions_job() -> None:
    summary = await asyncio.to_thread(service.clean_tautulli_ghost_sessions)
    if not (summary["ghosts"] or summary["failed"]):
        return
    if not settings.TG_ADMIN_CHAT_ID:
        return
    message = notifications._format_ghost_session_summary(summary)
    for chat_id in settings.TG_ADMIN_CHAT_ID:
        await send_message_by_url(
            chat_id=chat_id, text=message, disable_notification=True
        )
        await asyncio.sleep(1)
