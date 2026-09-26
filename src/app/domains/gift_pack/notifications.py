"""Gift pack milestone and failure notifications."""

import asyncio
from datetime import datetime
from html import escape

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.databases import db
from app.utils.utils import get_user_name_from_tg_id, notify_admins_by_url


def _format_time(timestamp: int) -> str:
    """按服务端配置时区格式化时间，保证与管理端录入口径一致"""
    return datetime.fromtimestamp(int(timestamp), settings.TZ).strftime(
        "%Y-%m-%d %H:%M"
    )


def _format_rewards(rewards: list[dict]) -> str:
    return "、".join(db._gift_pack_reward_label(r) for r in rewards)


# 持有强引用，避免 fire-and-forget 的 task 被 GC 提前回收
_pending_notifications: set = set()


def _notify_detached(coro) -> None:
    """在异常路径上发通知

    不能用 `BackgroundTasks`：它只在响应正常返回后才执行，抛 `HTTPException`
    时整条后台任务链会被跳过——而发放失败恰恰是最需要通知的场景。
    """
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        # 没有运行中的事件循环（同步上下文），退回同步执行
        asyncio.run(coro)
        return
    _pending_notifications.add(task)
    task.add_done_callback(_pending_notifications.discard)


async def notify_gift_pack_created(pack: dict) -> None:
    """礼包上线通知"""
    try:
        quantity = (
            f"{pack['total_quantity']} 份" if pack.get("total_quantity") else "不限量"
        )
        text = (
            "🎁 <b>礼包已上线</b>\n\n"
            f"<b>标题：</b>{pack['title']}\n"
            f"<b>奖励：</b>{_format_rewards(pack['rewards'])}\n"
            f"<b>限量：</b>{quantity}\n"
            f"<b>时间窗：</b>{_format_time(pack['start_at'])} ~ {_format_time(pack['end_at'])}\n"
            f"<b>状态：</b>{'已启用' if pack.get('is_enabled') else '未启用'}"
        )
        await notify_admins_by_url(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"发送礼包上线通知失败 (pack_id={pack.get('id')}): {e}")


async def notify_gift_pack_sold_out(pack_id: int, title: str, total_quantity: int):
    """限量礼包领完通知

    并发下只有一个事务能把计数加到满，天然只触发一次。
    """
    try:
        text = (
            "🎁 <b>礼包已领完</b>\n\n"
            f"<b>标题：</b>{title}\n"
            f"<b>总份数：</b>{total_quantity} 份已全部领取"
        )
        await notify_admins_by_url(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"发送礼包领完通知失败 (pack_id={pack_id}): {e}")


async def notify_gift_pack_claim_failed(pack_id: int, tg_id: int, reason: str):
    """奖励发放失败的异常通知"""
    try:
        user_name = get_user_name_from_tg_id(tg_id) or str(tg_id)
        pack = db.get_gift_pack_by_id(pack_id)
        title = pack["title"] if pack else f"#{pack_id}"
        text = (
            "⚠️ <b>礼包发放失败</b>\n\n"
            f"<b>礼包：</b>{title} (ID: {pack_id})\n"
            f"<b>用户：</b>{user_name} ({tg_id})\n"
            f"<b>原因：</b>{reason}\n\n"
            "本次领取已整体回滚，未扣减余量、未记录领取。"
        )
        await notify_admins_by_url(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"发送礼包发放失败通知失败 (pack_id={pack_id}): {e}")


async def notify_gift_pack_download_sync_failed(
    pack_id: int, tg_id: int, failures: list[dict]
) -> None:
    """下载权限已在数据库解锁、但同步到媒体服务器失败——需人工处理

    与「发放失败已回滚」是两回事：这里领取已经成功，不能混用文案。
    """
    try:
        user_name = get_user_name_from_tg_id(tg_id) or str(tg_id)
        pack = db.get_gift_pack_by_id(pack_id)
        title = pack["title"] if pack else f"#{pack_id}"
        details = "\n".join(
            f"　• {escape(str(f['service']).capitalize())}：{escape(str(f['error']))}"
            for f in failures
        )
        text = (
            "🔧 <b>礼包下载权限同步失败 · 需人工处理</b>\n\n"
            f"<b>礼包：</b>{escape(str(title))} (ID: {pack_id})\n"
            f"<b>用户：</b>{escape(str(user_name))} ({tg_id})\n"
            f"<b>失败服务：</b>\n{details}\n\n"
            "领取已成功，数据库中下载权限已记为解锁；"
            "请到对应媒体服务器为该用户手动开启下载权限。"
        )
        await notify_admins_by_url(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"发送礼包下载权限同步失败通知失败 (pack_id={pack_id}): {e}")
