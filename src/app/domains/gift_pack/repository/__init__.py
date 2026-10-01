"""礼包 repository 包：模块级函数接口。

纯计算在 ``app.domains.gift_pack.rules``；这里按子主题组合取数与写入的 mixin，
并对外暴露模块级函数。公开函数各自完成一次
事务，``*_tx`` 助手只接受调用方的 session、绝不吞异常。
"""

from .claims import _GiftPackRepositoryClaims
from .conditions import _GiftPackRepositoryConditions
from .notices import _GiftPackRepositoryNotices
from .packs import _GiftPackRepositoryPacks
from .reassign import (
    REASSIGNED_TG_ID_COLUMNS,
    check_tg_id_reassign_tx,
    reassign_tg_id_tx,
)
from .rewards import _GiftPackRepositoryRewards


class GiftPackRepository(
    _GiftPackRepositoryConditions,
    _GiftPackRepositoryRewards,
    _GiftPackRepositoryPacks,
    _GiftPackRepositoryClaims,
    _GiftPackRepositoryNotices,
):
    """礼包数据访问门面，按子主题组合五个 mixin。"""


_repository = GiftPackRepository()


def create_gift_pack(
    title: str,
    rewards: list[dict],
    start_at: int,
    end_at: int,
    description: str | None = None,
    eligibility: dict | None = None,
    total_quantity: int | None = None,
    max_prompt_count: int = 3,
    is_enabled: bool = True,
    created_by: int | None = None,
    audience: list[dict] | None = None,
    requirements: list[dict] | None = None,
    task_end_at: int | None = None,
    max_task_prompt_count: int = 2,
    notify_audience_on_start: bool = False,
) -> int:
    return _repository.create_gift_pack(
        title,
        rewards,
        start_at,
        end_at,
        description,
        eligibility,
        total_quantity,
        max_prompt_count,
        is_enabled,
        created_by,
        audience,
        requirements,
        task_end_at,
        max_task_prompt_count,
        notify_audience_on_start,
    )


def update_gift_pack(pack_id: int, **fields) -> bool:
    return _repository.update_gift_pack(pack_id, **fields)


def set_gift_pack_enabled(pack_id: int, is_enabled: bool) -> bool:
    return _repository.set_gift_pack_enabled(pack_id, is_enabled)


def delete_gift_pack(pack_id: int) -> bool:
    return _repository.delete_gift_pack(pack_id)


def get_gift_pack_by_id(pack_id: int) -> dict | None:
    return _repository.get_gift_pack_by_id(pack_id)


def get_gift_packs_admin(page: int = 1, page_size: int = 20) -> tuple[list[dict], int]:
    return _repository.get_gift_packs_admin(page, page_size)


def get_gift_pack_stats(pack_id: int) -> dict | None:
    return _repository.get_gift_pack_stats(pack_id)


def resolve_gift_pack_users(
    text: str, *, tg_cache: dict[int, dict] | None = None
) -> dict:
    return _repository.resolve_gift_pack_users(text, tg_cache=tg_cache)


def get_gift_pack_claim_records(
    pack_id: int, page: int = 1, page_size: int = 20
) -> tuple[list[dict], int]:
    return _repository.get_gift_pack_claim_records(pack_id, page, page_size)


def get_gift_packs_for_user(tg_id: int) -> list[dict]:
    return _repository.get_gift_packs_for_user(tg_id)


def claim_gift_pack(pack_id: int, tg_id: int) -> dict:
    return _repository.claim_gift_pack(pack_id, tg_id)


def prompt_check_gift_packs(tg_id: int) -> dict:
    return _repository.prompt_check_gift_packs(tg_id)


def claim_gift_pack_start_dm_candidates(limit: int = 200) -> list[dict]:
    return _repository.claim_gift_pack_start_dm_candidates(limit)


def get_expired_unnotified_gift_packs() -> list[dict]:
    return _repository.get_expired_unnotified_gift_packs()


def mark_gift_pack_expiry_notified(pack_id: int) -> bool:
    return _repository.mark_gift_pack_expiry_notified(pack_id)


__all__ = [
    "REASSIGNED_TG_ID_COLUMNS",
    "check_tg_id_reassign_tx",
    "claim_gift_pack",
    "claim_gift_pack_start_dm_candidates",
    "create_gift_pack",
    "delete_gift_pack",
    "get_expired_unnotified_gift_packs",
    "get_gift_pack_by_id",
    "get_gift_pack_claim_records",
    "get_gift_pack_stats",
    "get_gift_packs_admin",
    "get_gift_packs_for_user",
    "mark_gift_pack_expiry_notified",
    "prompt_check_gift_packs",
    "reassign_tg_id_tx",
    "resolve_gift_pack_users",
    "set_gift_pack_enabled",
    "update_gift_pack",
]
