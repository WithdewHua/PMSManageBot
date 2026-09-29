"""Gift pack scheduled scans."""

import asyncio

from app.core.log import uvicorn_logger as logger
from app.domains.gift_pack import notifications
from app.domains.gift_pack import service as gift_pack_service
from app.integrations.telegram.messaging import send_message_by_url


async def scan_expired_gift_packs() -> None:
    """周期扫描已过期且未通知的礼包，发送领取汇总后置 expiry_notified = 1

    用周期扫描而非创建时安排 date job：礼包的 end_at 是管理员可编辑的，
    date job 方案需要在每次编辑时重排，且漏排就永久丢失通知。
    """
    try:
        packs = gift_pack_service.scan_expired_packs()
        if not packs:
            return
        logger.info(f"扫描到 {len(packs)} 个已过期待汇总的礼包")
        for pack in packs:
            try:
                stats = pack["stats"]
                if not stats:
                    continue
                text = notifications.format_expiry_summary(pack, stats)
                await notifications.notify_gift_pack_expiry_summary(
                    text, parse_mode="HTML"
                )
                gift_pack_service.mark_expiry_notified(pack["id"])
            except Exception as e:
                logger.error(f"发送礼包过期汇总失败 (pack_id={pack['id']}): {e}")
    except Exception as e:
        logger.error(f"扫描过期礼包任务失败: {e}")


async def scan_gift_pack_start_dms() -> None:
    """认领名单型礼包的开始私信，再逐条发送；失败不重新认领。"""
    try:
        # db 方法必须在同一事务内筛选并写入 start_dm_sent_at，提交后才返回。
        candidates = gift_pack_service.start_dm_candidates(limit=200)
        if not candidates:
            return
        for index, candidate in enumerate(candidates):
            if index:
                await asyncio.sleep(0.5)
            try:
                text = notifications.format_start_dm_text(candidate)
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
