"""Gift pack scheduled scans."""

import asyncio

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.core.telegram import notify_admins_by_url, send_message_by_url
from app.databases import db
from app.domains.gift_pack.notifications import _format_rewards, _format_time


async def scan_expired_gift_packs() -> None:
    """周期扫描已过期且未通知的礼包，发送领取汇总后置 expiry_notified = 1

    用周期扫描而非创建时安排 date job：礼包的 end_at 是管理员可编辑的，
    date job 方案需要在每次编辑时重排，且漏排就永久丢失通知。
    """
    try:
        packs = db.get_expired_unnotified_gift_packs()
        if not packs:
            return
        logger.info(f"扫描到 {len(packs)} 个已过期待汇总的礼包")
        for pack in packs:
            try:
                stats = db.get_gift_pack_stats(pack["id"])
                if not stats:
                    continue
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
                text = (
                    "🎁 <b>礼包已结束 · 领取汇总</b>\n\n"
                    f"<b>标题：</b>{pack['title']}\n"
                    f"<b>结束时间：</b>{_format_time(pack['end_at'])}\n"
                    f"<b>领取情况：</b>{quantity}\n"
                    f"<b>被提醒人数：</b>{stats['prompted_users']}\n"
                    f"<b>奖励发放总量：</b>\n{totals}"
                )
                await notify_admins_by_url(text, parse_mode="HTML")
                db.mark_gift_pack_expiry_notified(pack["id"])
            except Exception as e:
                logger.error(f"发送礼包过期汇总失败 (pack_id={pack['id']}): {e}")
    except Exception as e:
        logger.error(f"扫描过期礼包任务失败: {e}")


async def scan_gift_pack_start_dms() -> None:
    """认领名单型礼包的开始私信，再逐条发送；失败不重新认领。"""
    try:
        # db 方法必须在同一事务内筛选并写入 start_dm_sent_at，提交后才返回。
        candidates = db.claim_gift_pack_start_dm_candidates(limit=200)
        if not candidates:
            return
        for index, candidate in enumerate(candidates):
            if index:
                await asyncio.sleep(0.5)
            try:
                text = (
                    "🎁 礼包已开始！\n\n"
                    f"礼包：{candidate['title']}\n"
                    f"奖励：{_format_rewards(candidate['rewards'])}\n"
                    f"领取条件：{candidate['requirements_summary'] or '无额外条件'}\n"
                    f"领取截止：{_format_time(candidate['end_at'])}（{settings.TZ}）\n\n"
                    "打开小程序的礼包中心领取。"
                )
                sent = await send_message_by_url(
                    chat_id=int(candidate["tg_id"]), text=text, max_retries=1
                )
                if not sent:
                    logger.error(
                        f"礼包开始私信发送失败 (pack_id={candidate['pack_id']}, "
                        f"tg_id={candidate['tg_id']})"
                    )
            except Exception as e:
                logger.error(
                    f"礼包开始私信发送异常 (pack_id={candidate.get('pack_id')}, "
                    f"tg_id={candidate.get('tg_id')}): {e}"
                )
        logger.info(f"礼包开始私信本轮处理 {len(candidates)} 位用户")
    except Exception as e:
        logger.error(f"扫描礼包开始私信任务失败: {e}")
