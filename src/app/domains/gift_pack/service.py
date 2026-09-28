"""礼包领域的用例编排（design D7）。

router、jobs 和 notifications 只调用这里；repository 负责取数与写入，纯计算在
``rules``。提交后的副作用在这里执行，顺序是：积分缓存失效（已在 session 上登记）、
媒体权限同步、通知。通知一律以 detached、best-effort 方式派发，失败不影响已提交的
领取结果。
"""

from __future__ import annotations

import time

from app.core.log import logger
from app.domains.gift_pack import notifications
from app.domains.gift_pack import repository as gift_pack_repository
from app.domains.gift_pack.exceptions import GiftPackError

#: 领了但同步失败的下载解锁：读取快照条目并补一句面向用户的说明。
_DOWNLOAD_SYNC_MESSAGE = (
    "{service} 已解锁下载权限，但同步到媒体服务器未完成，管理员将尽快人工处理"
)


def _sync_after_claim(
    tg_id: int,
    pack_id: int,
    result: dict,
    pending_permission_sync: list[str],
    pending_download_sync: list[str],
) -> list[dict]:
    """事务提交后的媒体同步（best-effort），返回同步失败的服务列表。"""
    snapshot = result["results"]
    failures: list[dict] = []
    for service in pending_download_sync:
        try:
            from app.domains.premium.service import apply_download_unlock_to_media

            apply_download_unlock_to_media(tg_id, service)
        except Exception as error:
            logger.error(
                f"礼包下载权限解锁同步 {service} 失败 (pack_id={pack_id}, tg_id={tg_id}): {error}"
            )
            failures.append({"service": service, "error": str(error)})
            for item in snapshot:
                if (
                    item.get("type") == "download_unlock"
                    and item.get("service") == service
                ):
                    item["message"] = _DOWNLOAD_SYNC_MESSAGE.format(
                        service=service.capitalize()
                    )
    for service in pending_permission_sync:
        try:
            from app.domains.premium import service as premium_service

            premium_service.sync_premium_media_access(tg_id, (service,))
        except Exception as error:
            logger.warning(
                f"礼包领取后同步 {service} 权限失败 (pack_id={pack_id}, tg_id={tg_id}): {error}"
            )
    return failures


def claim_gift_pack(pack_id: int, tg_id: int) -> dict:
    """领取礼包：写入在 repository 的单个事务里，提交后在此做副作用与通知。"""
    result, pending_permission_sync, pending_download_sync = (
        gift_pack_repository.claim_gift_pack(pack_id, tg_id)
    )
    pack_title = result["title"]

    failures = _sync_after_claim(
        tg_id, pack_id, result, pending_permission_sync, pending_download_sync
    )
    result["download_sync_failed"] = failures
    if failures:
        notifications.dispatch_gift_pack_download_sync_failed(
            pack_id, tg_id, failures, pack_title
        )
    if result["sold_out"]:
        # 并发下只有一个事务能把计数加到满，因此这里只会触发一次
        notifications.dispatch_gift_pack_sold_out(
            pack_id, result["title"], result["total_quantity"]
        )
    return result


def notify_claim_failed(pack_id: int, tg_id: int, reason: str) -> None:
    """领取在提交前失败（已回滚）时通知管理员，供 router 的 500 分支调用。"""
    pack = gift_pack_repository.get_gift_pack_by_id(pack_id)
    notifications.dispatch_gift_pack_claim_failed(
        pack_id, tg_id, reason, pack["title"] if pack else None
    )


def list_gift_packs_for_user(tg_id: int) -> list[dict]:
    """用户可见礼包列表。"""
    return gift_pack_repository.get_gift_packs_for_user(tg_id)


def prompt_check(tg_id: int) -> dict:
    """开屏提醒：沿用原有的默认返回（无礼包或无积分信息时返回空）。"""
    return gift_pack_repository.prompt_check_gift_packs(tg_id)


def admin_list(page: int, page_size: int) -> tuple[list[dict], int]:
    return gift_pack_repository.get_gift_packs_admin(page=page, page_size=page_size)


def admin_get(pack_id: int) -> dict | None:
    return gift_pack_repository.get_gift_pack_by_id(pack_id)


def admin_create(**fields) -> int:
    """新建礼包并在提交后通知创建结果。"""
    pack_id = gift_pack_repository.create_gift_pack(**fields)
    pack = gift_pack_repository.get_gift_pack_by_id(pack_id)
    if pack is not None:
        notifications.dispatch_gift_pack_created(pack)
    return pack_id


def admin_update(pack_id: int, **fields) -> bool:
    return gift_pack_repository.update_gift_pack(pack_id, **fields)


def admin_set_enabled(pack_id: int, is_enabled: bool) -> bool:
    return gift_pack_repository.set_gift_pack_enabled(pack_id, is_enabled)


def admin_delete(pack_id: int) -> None:
    gift_pack_repository.delete_gift_pack(pack_id)


def admin_stats(pack_id: int) -> dict:
    return gift_pack_repository.get_gift_pack_stats(pack_id)


def admin_claim_records(
    pack_id: int, *, page: int, page_size: int
) -> tuple[list[dict], int]:
    return gift_pack_repository.get_gift_pack_claim_records(
        pack_id, page=page, page_size=page_size
    )


def admin_resolve_users(text: str) -> dict:
    return gift_pack_repository.resolve_gift_pack_users(text)


def scan_expired_packs(limit: int | None = None) -> list[dict]:
    """过期扫描：取候选并在提交后派发汇总通知。"""
    packs = gift_pack_repository.get_expired_unnotified_gift_packs(
        **({"limit": limit} if limit else {})
    )
    pending: list[dict] = []
    for pack in packs:
        stats = gift_pack_repository.get_gift_pack_stats(pack["id"])
        pending.append({**pack, "stats": stats})
    return pending


def mark_expiry_notified(pack_id: int) -> bool:
    return gift_pack_repository.mark_gift_pack_expiry_notified(pack_id)


def start_dm_candidates(limit: int = 200) -> list[dict]:
    return gift_pack_repository.claim_gift_pack_start_dm_candidates(limit=limit)


def _now() -> int:
    """保留给用例内的时间读取（便于测试固定时钟）。"""
    return int(time.time())


__all__ = [
    "GiftPackError",
    "admin_claim_records",
    "admin_create",
    "admin_delete",
    "admin_get",
    "admin_list",
    "admin_resolve_users",
    "admin_set_enabled",
    "admin_stats",
    "admin_update",
    "claim_gift_pack",
    "list_gift_packs_for_user",
    "mark_expiry_notified",
    "notify_claim_failed",
    "prompt_check",
    "scan_expired_packs",
    "start_dm_candidates",
]
