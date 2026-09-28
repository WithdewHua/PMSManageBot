"""Treasure workflows and post-commit side effects."""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.core.number import normalize_external_random_b
from app.domains.treasure import exceptions as treasure_exceptions
from app.domains.treasure import notifications as treasure_notifications
from app.domains.treasure import repository as treasure_repository
from app.integrations import eth_rpc


def get_user_treasure_stats(tg_id: int) -> dict:
    try:
        return treasure_repository.get_user_treasure_stats(int(tg_id))
    except treasure_exceptions.TreasureError:
        raise
    except Exception as error:
        raise treasure_exceptions.operation_failed("获取用户夺宝统计失败") from error


def list_treasure_issues(*, limit: int = 50, include_closed: bool = True) -> list[dict]:
    try:
        return treasure_repository.list_treasure_issues(
            limit=int(limit), include_closed=bool(include_closed)
        )
    except treasure_exceptions.TreasureError:
        raise
    except Exception as error:
        raise treasure_exceptions.operation_failed("获取夺宝期数列表失败") from error


def get_treasure_issue(issue_id: int) -> dict | None:
    try:
        return treasure_repository.get_treasure_issue_by_id(int(issue_id))
    except treasure_exceptions.TreasureError:
        raise
    except Exception as error:
        raise treasure_exceptions.operation_failed("获取夺宝期数失败") from error


def list_treasure_participations(
    issue_id: int, *, limit: int = 100, offset: int = 0
) -> list[dict]:
    try:
        return treasure_repository.list_treasure_participations(
            int(issue_id), limit=int(limit), offset=int(offset)
        )
    except treasure_exceptions.TreasureError:
        raise
    except Exception as error:
        raise treasure_exceptions.operation_failed("获取参与记录失败") from error


def _fallback_external_random_b(
    *,
    issue_id: int,
    issue: dict | None,
    quantity: int,
    tg_id: int,
    timestamp_ms: int,
) -> int | None:
    if not issue:
        return None
    total_shares = int(issue.get("total_shares", 0))
    shares_sold = int(issue.get("shares_sold", 0))
    remaining = total_shares - shares_sold
    if remaining <= 0 or int(quantity) < remaining:
        return None

    secret = getattr(settings, "TG_API_TOKEN", "")
    if not secret:
        raise RuntimeError("TG_API_TOKEN not configured")
    message = (
        f"treasure|fallback_b|issue_id={int(issue_id)}|"
        f"total={total_shares}|sold={shares_sold}|qty={int(quantity)}|"
        f"tg_id={int(tg_id)}|ts_ms={int(timestamp_ms)}"
    ).encode()
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return normalize_external_random_b(int.from_bytes(digest[:8], "big", signed=False))


async def join_treasure_issue(*, issue_id: int, tg_id: int, quantity: int = 1) -> dict:
    external_random_b: int | None = None
    try:
        external_random_b = await eth_rpc.latest_block_hash_int()
    except Exception as error:
        logger.warning(f"获取以太坊最新区块hash失败: {error}")

    timestamp_ms = int(time.time() * 1000)
    fallback_b = None
    if external_random_b is None:
        try:
            issue = treasure_repository.get_treasure_issue_by_id(int(issue_id))
            fallback_b = _fallback_external_random_b(
                issue_id=int(issue_id),
                issue=issue,
                quantity=int(quantity),
                tg_id=int(tg_id),
                timestamp_ms=timestamp_ms,
            )
            if fallback_b is not None:
                logger.info(
                    "ETH hash unavailable; using deterministic fallback B for settlement"
                )
        except Exception as error:
            logger.warning(f"生成随机兜底B失败，将继续使用默认B=0: {error}")

    safe_external_b = normalize_external_random_b(
        external_random_b if external_random_b is not None else fallback_b
    )
    result = treasure_repository.join_treasure_issue(
        issue_id=int(issue_id),
        tg_id=int(tg_id),
        external_random_b=safe_external_b,
        timestamp_ms=timestamp_ms,
        quantity=int(quantity),
    )

    issue = treasure_repository.get_treasure_issue_by_id(int(issue_id))
    if not result.get("settled"):
        try:
            issue_state = result.get("issue") or {}
            await treasure_notifications.notify_treasure_not_full_after_join(
                issue_id=int(issue_id),
                title=str(issue.get("title")) if issue else None,
                joiner_tg_id=int(tg_id),
                bought_shares=len(result.get("participations") or []) or 1,
                shares_sold=int(issue_state.get("shares_sold") or 0),
                total_shares=int(issue_state.get("total_shares") or 0),
                prize_credits=int(issue.get("prize_credits") or 0) if issue else 0,
            )
        except Exception as error:
            logger.warning(f"Treasure progress notify failed: {error}")
    elif issue and issue.get("winner_tg_id") and issue.get("winner_number"):
        try:
            winner_tg_id = int(issue.get("winner_tg_id") or 0)
            winner_number = int(issue.get("winner_number") or 0)
            await treasure_notifications.notify_treasure_settled(
                issue_id=int(issue_id),
                title=str(issue.get("title")),
                winner_tg_id=winner_tg_id,
                winner_number=winner_number,
                prize_credits=int(issue.get("prize_credits") or 0),
            )
        except Exception as error:
            logger.warning(f"Treasure settle notify failed: {error}")
        try:
            schedule_auto_reopen_treasure_issue(source_issue_id=int(issue_id))
        except Exception as error:
            logger.warning(f"Treasure auto reopen schedule failed: {error}")

    return result


async def create_treasure_issue(
    *,
    title: str | None,
    description: str | None,
    prize_credits: int,
    total_credits_required: int,
    credits_per_share: int,
    start_number: int | None,
    created_by: int | None,
) -> int:
    normalized_title = (title or "").strip()
    if not normalized_title:
        normalized_title = f"夺宝奇兵 {datetime.now(settings.TZ):%Y-%m-%d-%H:%M:%S}"
    issue_id = treasure_repository.create_treasure_issue(
        title=normalized_title,
        description=description,
        prize_credits=int(prize_credits),
        total_credits_required=int(total_credits_required),
        credits_per_share=int(credits_per_share),
        start_number=start_number,
        created_by=int(created_by) if created_by is not None else None,
    )
    try:
        issue = treasure_repository.get_treasure_issue_by_id(int(issue_id))
        if issue:
            await treasure_notifications.notify_treasure_issue_created(
                issue_id=int(issue_id),
                title=str(issue.get("title")),
                total_shares=int(issue.get("total_shares") or 0),
                credits_per_share=int(issue.get("credits_per_share") or 0),
                prize_credits=int(issue.get("prize_credits") or 0),
            )
    except Exception as error:
        logger.warning(f"Treasure create notify failed: {error}")
    return int(issue_id)


def schedule_auto_reopen_treasure_issue(*, source_issue_id: int) -> None:
    """Schedule the named auto-reopen task after a committed settlement."""
    from app.core.scheduler import schedule_task

    run_date = datetime.now(settings.TZ) + timedelta(minutes=10)
    schedule_task(
        "treasure.open_next_issue",
        run_date=run_date,
        job_id=f"treasure_auto_reopen_{int(source_issue_id)}",
        kwargs={"source_issue_id": int(source_issue_id)},
        misfire_grace_time=60,
        replace_existing=True,
        max_instances=1,
    )


def cancel_treasure_issue(*, issue_id: int) -> dict:
    return treasure_repository.cancel_treasure_issue(issue_id=int(issue_id))


__all__ = [
    "cancel_treasure_issue",
    "create_treasure_issue",
    "get_treasure_issue",
    "get_user_treasure_stats",
    "join_treasure_issue",
    "list_treasure_issues",
    "list_treasure_participations",
    "schedule_auto_reopen_treasure_issue",
]
