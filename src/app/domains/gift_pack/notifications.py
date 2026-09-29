"""Gift pack milestone and failure notifications."""

import asyncio
from datetime import datetime
from html import escape

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.domains.gift_pack import rules
from app.integrations.telegram.profiles import get_user_name_from_tg_id
from app.transport.telegram.admin import notify_admins_by_url


def _format_time(timestamp: int) -> str:
    """按服务端配置时区格式化时间，保证与管理端录入口径一致"""
    return datetime.fromtimestamp(int(timestamp), settings.TZ).strftime(
        "%Y-%m-%d %H:%M"
    )


def _format_rewards(rewards: list[dict]) -> str:
    return "、".join(rules._gift_pack_reward_label(r) for r in rewards)


# 持有强引用，避免 fire-and-forget 的 task 被 GC 提前回收
_pending_notifications: set = set()
#: 主事件循环：定时任务在线程池里派发通知时用它提交协程。
_main_loop: asyncio.AbstractEventLoop | None = None


def _notify_detached(coro) -> None:
    """best-effort 派发通知，事件循环线程与线程池都能调用

    不能用 `BackgroundTasks`：它只在响应正常返回后才执行，抛 `HTTPException`
    时整条后台任务链会被跳过——而发放失败恰恰是最需要通知的场景。
    """
    global _main_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        _main_loop = loop
        task = loop.create_task(coro)
        _pending_notifications.add(task)
        task.add_done_callback(_pending_notifications.discard)
        return
    if _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, _main_loop)
        return
    # 完全没有事件循环（脚本、测试）时同步执行
    asyncio.run(coro)


async def notify_gift_pack_expiry_summary(text: str, **kwargs) -> None:
    await notify_admins_by_url(text, **kwargs)


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


async def notify_gift_pack_claim_failed(
    pack_id: int, tg_id: int, reason: str, title: str | None = None
):
    """奖励发放失败的异常通知（礼包标题由 service 传入，这里不读数据）"""
    try:
        user_name = get_user_name_from_tg_id(tg_id) or str(tg_id)
        title = title or f"#{pack_id}"
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
    pack_id: int, tg_id: int, failures: list[dict], title: str | None = None
) -> None:
    """下载权限已在数据库解锁、但同步到媒体服务器失败——需人工处理

    与「发放失败已回滚」是两回事：这里领取已经成功，不能混用文案。
    """
    try:
        user_name = get_user_name_from_tg_id(tg_id) or str(tg_id)
        title = title or f"#{pack_id}"
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


def format_expiry_summary(pack: dict, stats: dict) -> str:
    """过期汇总文案（数据由 service 传入）"""
    quantity = (
        f"{stats['claimed_users']} / {pack['total_quantity']} 份"
        if pack.get("total_quantity")
        else f"{stats['claimed_users']} 人（不限量）"
    )
    totals = (
        "\n".join(
            f"　• {item['label']}：{item['total']}"
            + (
                f"（{item['grants']} 次发放，{item['skipped']} 次{item['skipped_label']}）"
                if item.get("skipped") and item.get("skipped_label")
                else ""
            )
            for item in stats["reward_totals"]
        )
        or "　• 无发放记录"
    )
    return (
        "🎁 <b>礼包已结束 · 领取汇总</b>\n\n"
        f"<b>标题：</b>{pack['title']}\n"
        f"<b>结束时间：</b>{_format_time(pack['end_at'])}\n"
        f"<b>领取情况：</b>{quantity}\n"
        f"<b>被提醒人数：</b>{stats['prompted_users']}\n"
        f"<b>奖励发放总量：</b>\n{totals}"
    )


def format_start_dm_text(candidate: dict) -> str:
    """开始私信文案（候选人数据由 service 传入）"""
    return (
        "🎁 礼包已开始！\n\n"
        f"礼包：{candidate['title']}\n"
        f"奖励：{_format_rewards(candidate['rewards'])}\n"
        f"领取条件：{candidate['requirements_summary'] or '无额外条件'}\n"
        f"领取截止：{_format_time(candidate['end_at'])}（{settings.TZ}）\n\n"
        "打开小程序的礼包中心领取。"
    )


def dispatch_gift_pack_created(pack: dict) -> None:
    """创建通知：service 在提交后调用。"""
    _notify_detached(notify_gift_pack_created(pack))


def dispatch_gift_pack_sold_out(pack_id: int, title: str, total_quantity: int) -> None:
    _notify_detached(notify_gift_pack_sold_out(pack_id, title, total_quantity))


def dispatch_gift_pack_claim_failed(
    pack_id: int, tg_id: int, reason: str, title: str | None = None
) -> None:
    _notify_detached(notify_gift_pack_claim_failed(pack_id, tg_id, reason, title))


def dispatch_gift_pack_download_sync_failed(
    pack_id: int, tg_id: int, failures: list[dict], title: str | None = None
) -> None:
    _notify_detached(
        notify_gift_pack_download_sync_failed(pack_id, tg_id, failures, title)
    )


__all__ = [
    "dispatch_gift_pack_claim_failed",
    "dispatch_gift_pack_created",
    "dispatch_gift_pack_download_sync_failed",
    "dispatch_gift_pack_sold_out",
    "format_expiry_summary",
    "format_start_dm_text",
    "notify_gift_pack_claim_failed",
    "notify_gift_pack_created",
    "notify_gift_pack_download_sync_failed",
    "notify_gift_pack_sold_out",
]
