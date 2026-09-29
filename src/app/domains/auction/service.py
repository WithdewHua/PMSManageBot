"""Auction workflows, task scheduling, and post-commit notifications."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from app.core.config import settings
from app.core.log import logger
from app.core.scheduler import Scheduler, schedule_task
from app.domains.auction import exceptions as auction_exceptions
from app.domains.auction import notifications as auction_notifications
from app.domains.auction import repository as auction_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.integrations.telegram.profiles import get_user_name_from_tg_id


def _job_id(auction_id: int) -> str:
    return f"finish_auction_{int(auction_id)}"


def schedule_finish(*, auction_id: int, end_time: int | datetime) -> None:
    run_date = (
        end_time
        if isinstance(end_time, datetime)
        else datetime.fromtimestamp(int(end_time), tz=settings.TZ)
    )
    schedule_task(
        "auction.finish",
        run_date=run_date,
        job_id=_job_id(int(auction_id)),
        kwargs={"auction_id": int(auction_id)},
        misfire_grace_time=60,
        jobstore="default",
        replace_existing=True,
        max_instances=1,
    )


def remove_finish_auction(*, auction_id: int) -> None:
    Scheduler().remove_job(_job_id(int(auction_id)), jobstore="default")


def get_auction_list() -> list[dict]:
    try:
        return auction_repository.get_active_auctions()
    except Exception as error:
        raise auction_exceptions.operation_failed("获取竞拍列表失败") from error


def get_auction_stats() -> dict:
    try:
        return auction_repository.get_auction_stats()
    except Exception as error:
        raise auction_exceptions.operation_failed("获取统计数据失败") from error


def get_auction_detail(*, auction_id: int, user_id: int) -> dict:
    try:
        auction = auction_repository.get_auction_by_id(int(auction_id))
        if not auction:
            raise auction_exceptions.not_found()
        return {
            "auction": auction,
            "recent_bids": auction_repository.get_auction_bids(
                auction_id=int(auction_id), limit=10
            ),
            "user_highest_bid": auction_repository.get_user_highest_bid(
                int(auction_id), int(user_id)
            ),
        }
    except auction_exceptions.AuctionError:
        raise
    except Exception as error:
        raise auction_exceptions.operation_failed("获取竞拍详情失败") from error


async def create_auction(
    *,
    title: str,
    description: str,
    starting_price: float,
    duration_hours: int,
    created_by: int,
) -> dict:
    end_time = datetime.now(settings.TZ) + timedelta(hours=int(duration_hours))
    auction_id = auction_repository.create_auction(
        title=title,
        description=description,
        starting_price=float(starting_price),
        end_time=int(end_time.timestamp()),
        created_by=int(created_by),
    )
    if not auction_id:
        raise auction_exceptions.create_failed()
    schedule_finish(auction_id=int(auction_id), end_time=end_time)
    await auction_notifications.send_auction_created_notification(
        title=title,
        description=description,
        starting_price=float(starting_price),
        end_time_text=end_time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    logger.info(
        f"管理员 {get_user_name_from_tg_id(created_by)} 创建了竞拍: {title}，"
        f"将在 {end_time} 自动结束"
    )
    return {"auction_id": int(auction_id), "end_time": end_time}


def place_bid(*, auction_id: int, bidder_id: int, bid_amount: float) -> dict:
    auction = auction_repository.get_auction_by_id(int(auction_id))
    if not auction:
        raise auction_exceptions.not_found()
    if not auction["is_active"]:
        raise auction_exceptions.ended()
    if int(auction["end_time"]) <= int(time.time()):
        raise auction_exceptions.expired()
    if int(auction["created_by"]) == int(bidder_id):
        raise auction_exceptions.own_auction()
    if float(bid_amount) <= float(auction["current_price"]):
        raise auction_exceptions.bid_too_low(float(auction["current_price"]))

    user_credits = credits_service.read_optional(CreditAccount.tg(int(bidder_id)))
    if not user_credits:
        raise auction_exceptions.credits_unavailable()
    if float(user_credits) < float(bid_amount):
        raise auction_exceptions.insufficient_credits(
            float(user_credits), float(bid_amount)
        )
    if not auction_repository.place_bid(
        auction_id=int(auction_id),
        bidder_id=int(bidder_id),
        bid_amount=float(bid_amount),
    ):
        raise auction_exceptions.bid_failed()

    return {
        "auction": auction,
        "user_credits": float(user_credits),
        "current_price": float(bid_amount),
        "bid_count": int(auction.get("bid_count") or 0) + 1,
        "participant_ids": auction_repository.get_auction_participants(
            int(auction_id), exclude_user_id=int(bidder_id)
        ),
    }


async def notify_bid_placed(
    *,
    auction_id: int,
    bidder_id: int,
    bid_amount: float,
    auction_title: str,
    bid_count: int,
    participant_ids: list[int],
) -> None:
    await auction_notifications.send_bid_notifications(
        auction_id=auction_id,
        bidder_id=bidder_id,
        bid_amount=bid_amount,
        auction_title=auction_title,
        bid_count=bid_count,
        participant_ids=participant_ids,
    )


def restore_auction_schedules() -> None:
    """Restore every active auction after process startup."""
    try:
        active_auctions = auction_repository.get_active_auctions()
        current_time = int(time.time())
        for auction in active_auctions:
            auction_id = int(auction["id"])
            end_time = int(auction["end_time"])
            if end_time <= current_time:
                logger.warning(f"竞拍 {auction_id} 已过期，将由兜底任务处理")
                continue
            end_datetime = datetime.fromtimestamp(end_time, tz=settings.TZ)
            schedule_finish(auction_id=auction_id, end_time=end_datetime)
            logger.info(f"恢复竞拍 {auction_id} 的定时任务，结束时间: {end_datetime}")
        logger.info(
            f"已恢复 {len([item for item in active_auctions if item['end_time'] > current_time])} 个竞拍的定时任务"
        )
    except Exception as error:
        logger.error(f"恢复竞拍定时任务失败: {error}")


async def finish_expired_auctions() -> list[dict]:
    finished: list[dict] = []
    for auction_id in auction_repository.get_expired_auction_ids():
        try:
            result = await finish_auction(
                auction_id=auction_id, remove_task=False, notify_winner=True
            )
            if result[0] and isinstance(result[1], dict):
                finished.append(result[1])
        except Exception:
            logger.exception("结束过期竞拍 %s 失败", auction_id)
    return finished


async def finish_auction(
    *, auction_id: int, remove_task: bool = True, notify_winner: bool = True
) -> tuple[bool, dict | str | None]:
    if remove_task:
        try:
            remove_finish_auction(auction_id=int(auction_id))
        except Exception as error:
            logger.warning(f"移除竞拍 {auction_id} 定时任务失败: {error}")
    success, winner = auction_repository.finish_auction_by_id(int(auction_id))
    if not success:
        if str(winner) == "竞拍已结束":
            raise auction_exceptions.ended()
        if "不存在" in str(winner):
            raise auction_exceptions.not_found()
        raise auction_exceptions.finish_failed()
    try:
        await auction_notifications.send_auction_finished_notifications(
            title=str(winner.get("title")),
            winner_id=winner.get("winner_id"),
            final_price=winner.get("final_price"),
            credits_reduced=bool(winner.get("credits_reduced", False)),
            notify_winner=notify_winner,
        )
    except Exception:
        logger.exception("竞拍 %s 结束通知失败", auction_id)
    return True, winner


async def finish_single_auction_job(*, auction_id: int) -> None:
    try:
        await finish_auction(auction_id=int(auction_id), remove_task=False)
        logger.info(f"竞拍 {auction_id} 自动结束成功")
    except auction_exceptions.AuctionError as error:
        if error.code in {"auction.not_found", "auction.ended"}:
            logger.info(f"竞拍 {auction_id} 不存在或已结束，跳过自动结束任务")
        else:
            logger.error(f"自动结束竞拍 {auction_id} 失败: {error}")
    except Exception as error:
        logger.error(f"自动结束竞拍 {auction_id} 失败: {error}")


def get_all_auctions(*, status: str | None = None, limit: int = 50, offset: int = 0):
    try:
        return auction_repository.get_all_auctions(
            status=status, limit=int(limit), offset=int(offset)
        )
    except Exception as error:
        raise auction_exceptions.operation_failed("获取竞拍列表失败") from error


def update_auction(
    *, auction_id: int, update_data: dict, duration_hours: int | None = None
) -> bool:
    if not auction_repository.get_auction_by_id(int(auction_id)):
        raise auction_exceptions.not_found()
    if duration_hours:
        end_time = datetime.now(settings.TZ) + timedelta(hours=int(duration_hours))
        update_data = {**update_data, "end_time": int(end_time.timestamp())}
        try:
            remove_finish_auction(auction_id=int(auction_id))
        except Exception as error:
            logger.warning(f"移除竞拍 {auction_id} 旧定时任务失败: {error}")
        schedule_finish(auction_id=int(auction_id), end_time=end_time)
    if not auction_repository.update_auction(int(auction_id), update_data):
        raise auction_exceptions.update_failed()
    return True


def delete_auction(*, auction_id: int) -> bool:
    if not auction_repository.get_auction_by_id(int(auction_id)):
        raise auction_exceptions.not_found()
    try:
        remove_finish_auction(auction_id=int(auction_id))
    except Exception as error:
        logger.warning(f"移除竞拍 {auction_id} 定时任务失败: {error}")
    if not auction_repository.delete_auction(int(auction_id)):
        raise auction_exceptions.delete_failed()
    return True


def get_auction_bids(*, auction_id: int, limit: int = 50) -> list[dict]:
    if not auction_repository.get_auction_by_id(int(auction_id)):
        raise auction_exceptions.not_found()
    return auction_repository.get_auction_bids(int(auction_id), limit=int(limit))


def get_user_auction_history(*, user_id: int, limit: int = 20) -> list[dict]:
    return auction_repository.get_user_auction_history(int(user_id), limit=int(limit))


def get_detailed_auction_stats(
    *, start_date: int | None = None, end_date: int | None = None
) -> dict:
    return auction_repository.get_detailed_auction_stats(
        start_date=start_date, end_date=end_date
    )


__all__ = [
    "create_auction",
    "delete_auction",
    "finish_auction",
    "finish_expired_auctions",
    "finish_single_auction_job",
    "get_all_auctions",
    "get_auction_bids",
    "get_auction_detail",
    "get_auction_list",
    "get_auction_stats",
    "get_detailed_auction_stats",
    "get_user_auction_history",
    "notify_bid_placed",
    "place_bid",
    "remove_finish_auction",
    "restore_auction_schedules",
    "schedule_finish",
    "update_auction",
]
