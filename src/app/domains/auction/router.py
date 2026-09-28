from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.core.schemas import TelegramUser
from app.domains.auction import exceptions as auction_exceptions
from app.domains.auction import service as auction_service
from app.domains.auction.schemas import (
    AuctionBid,
    AuctionDetailResponse,
    AuctionItem,
    AuctionListResponse,
    AuctionStatsResponse,
    CreateAuctionRequest,
    PlaceBidRequest,
    PlaceBidResponse,
)

router = APIRouter(prefix="/auction", tags=["auction"])


def _auction_item(data: dict) -> AuctionItem:
    return AuctionItem(
        id=data["id"],
        title=data["title"],
        description=data["description"],
        starting_price=data["starting_price"],
        current_price=data["current_price"],
        end_time=datetime.fromtimestamp(data["end_time"], tz=settings.TZ),
        created_by=data["created_by"],
        created_at=datetime.fromtimestamp(data["created_at"], tz=settings.TZ),
        is_active=bool(data["is_active"]),
        winner_id=data.get("winner_id"),
        bid_count=data.get("bid_count", 0),
        status=data.get("status"),
    )


def _auction_error(error: auction_exceptions.AuctionError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.message)


@router.get("/list", response_model=AuctionListResponse)
@require_telegram_auth
async def get_auction_list(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    try:
        items = [_auction_item(data) for data in auction_service.get_auction_list()]
        return AuctionListResponse(auctions=items, total=len(items))
    except auction_exceptions.AuctionError as error:
        raise _auction_error(error) from error
    except Exception as error:
        logger.error(f"获取竞拍列表失败: {error}")
        raise HTTPException(status_code=500, detail="获取竞拍列表失败") from error


@router.get("/stats", response_model=AuctionStatsResponse)
@require_telegram_auth
async def get_auction_stats(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    try:
        check_admin_permission(current_user)
        return AuctionStatsResponse(**auction_service.get_auction_stats())
    except HTTPException:
        raise
    except auction_exceptions.AuctionError as error:
        raise _auction_error(error) from error
    except Exception as error:
        logger.error(f"获取竞拍统计失败: {error}")
        raise HTTPException(status_code=500, detail="获取统计数据失败") from error


@router.get("/{auction_id}", response_model=AuctionDetailResponse)
@require_telegram_auth
async def get_auction_detail(
    auction_id: int,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        result = auction_service.get_auction_detail(
            auction_id=int(auction_id), user_id=int(current_user.id)
        )
        auction = _auction_item(result["auction"])
        recent_bids = [
            AuctionBid(
                id=bid["id"],
                auction_id=bid["auction_id"],
                bidder_id=bid["bidder_id"],
                bid_amount=bid["bid_amount"],
                bid_time=datetime.fromtimestamp(bid["bid_time"], tz=settings.TZ),
            )
            for bid in result["recent_bids"]
        ]
        return AuctionDetailResponse(
            auction=auction,
            recent_bids=recent_bids,
            user_can_bid=(
                auction.is_active
                and auction.end_time > datetime.now(settings.TZ)
                and current_user.id != auction.created_by
            ),
            user_highest_bid=result["user_highest_bid"],
        )
    except auction_exceptions.AuctionError as error:
        raise _auction_error(error) from error
    except Exception as error:
        logger.error(f"获取竞拍详情失败: {error}")
        raise HTTPException(status_code=500, detail="获取竞拍详情失败") from error


@router.post("/create")
@require_telegram_auth
async def create_auction(
    request_data: CreateAuctionRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        check_admin_permission(current_user)
        result = await auction_service.create_auction(
            title=request_data.title,
            description=request_data.description,
            starting_price=request_data.starting_price,
            duration_hours=request_data.duration_hours,
            created_by=int(current_user.id),
        )
        return {
            "success": True,
            "message": "竞拍创建成功",
            "auction_id": result["auction_id"],
        }
    except HTTPException:
        raise
    except auction_exceptions.AuctionError as error:
        raise _auction_error(error) from error
    except Exception as error:
        logger.error(f"创建竞拍失败: {error}")
        raise HTTPException(status_code=500, detail="创建竞拍失败") from error


@router.post("/bid", response_model=PlaceBidResponse)
@require_telegram_auth
async def place_bid(
    bid_request: PlaceBidRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        result = auction_service.place_bid(
            auction_id=int(bid_request.auction_id),
            bidder_id=int(current_user.id),
            bid_amount=float(bid_request.bid_amount),
        )
        auction = result["auction"]
        background_tasks.add_task(
            auction_service.notify_bid_placed,
            auction_id=int(bid_request.auction_id),
            bidder_id=int(current_user.id),
            bid_amount=float(bid_request.bid_amount),
            auction_title=str(auction.get("title")),
            bid_count=int(result["bid_count"]),
            participant_ids=result["participant_ids"],
        )
        return PlaceBidResponse(
            success=True,
            message="出价成功",
            current_price=result["current_price"],
            user_credits=result["user_credits"],
        )
    except auction_exceptions.AuctionError as error:
        raise _auction_error(error) from error
    except Exception as error:
        logger.error(f"出价失败: {error}")
        raise HTTPException(status_code=500, detail="出价失败") from error


@router.post("/finish-expired")
@require_telegram_auth
async def finish_expired_auctions(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    try:
        check_admin_permission(current_user)
        finished = await auction_service.finish_expired_auctions()
        return {
            "success": True,
            "message": f"已结束 {len(finished)} 个过期竞拍",
            "finished_auctions": finished,
        }
    except HTTPException:
        raise
    except auction_exceptions.AuctionError as error:
        raise _auction_error(error) from error
    except Exception as error:
        logger.error(f"结束过期竞拍失败: {error}")
        raise HTTPException(status_code=500, detail="结束过期竞拍失败") from error


@router.get("/admin/list")
@require_telegram_auth
async def get_all_auctions_admin(
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
    status_filter: str | None = None,
    page: int = 1,
    limit: int = 20,
):
    try:
        check_admin_permission(current_user)
        data = auction_service.get_all_auctions(
            status=status_filter, limit=int(limit), offset=(int(page) - 1) * int(limit)
        )
        return {"auctions": [_auction_item(item) for item in data], "total": len(data)}
    except HTTPException:
        raise
    except auction_exceptions.AuctionError as error:
        raise _auction_error(error) from error
    except Exception as error:
        logger.error(f"获取所有竞拍失败: {error}")
        raise HTTPException(status_code=500, detail="获取所有竞拍失败") from error


@router.put("/admin/{auction_id}")
@require_telegram_auth
async def update_auction_admin(
    auction_id: int,
    update_data: CreateAuctionRequest,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        check_admin_permission(current_user)
        auction_service.update_auction(
            auction_id=int(auction_id),
            update_data={
                "title": update_data.title,
                "description": update_data.description,
                "starting_price": update_data.starting_price,
            },
            duration_hours=update_data.duration_hours,
        )
        return {"success": True, "message": "竞拍更新成功"}
    except HTTPException:
        raise
    except auction_exceptions.AuctionError as error:
        raise _auction_error(error) from error
    except Exception as error:
        logger.error(f"更新竞拍失败: {error}")
        raise HTTPException(status_code=500, detail="更新竞拍失败") from error


@router.delete("/admin/{auction_id}")
@require_telegram_auth
async def delete_auction_admin(
    auction_id: int,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        check_admin_permission(current_user)
        auction_service.delete_auction(auction_id=int(auction_id))
        return {"success": True, "message": "竞拍删除成功"}
    except HTTPException:
        raise
    except auction_exceptions.AuctionError as error:
        raise _auction_error(error) from error
    except Exception as error:
        logger.error(f"删除竞拍失败: {error}")
        raise HTTPException(status_code=500, detail="删除竞拍失败") from error


@router.post("/admin/{auction_id}/finish")
@require_telegram_auth
async def finish_auction_admin(
    auction_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        check_admin_permission(current_user)
        success, winner = await auction_service.finish_auction(
            auction_id=int(auction_id), remove_task=True
        )
        return {
            "success": success,
            "message": "竞拍已结束",
            "finished_auctions": [winner],
        }
    except HTTPException:
        raise
    except auction_exceptions.AuctionError as error:
        raise _auction_error(error) from error
    except Exception as error:
        logger.error(f"结束竞拍失败: {error}")
        raise HTTPException(status_code=500, detail="结束竞拍失败") from error


@router.get("/admin/{auction_id}/bids")
@require_telegram_auth
async def get_auction_bids_admin(
    auction_id: int,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
    limit: int = 50,
):
    try:
        check_admin_permission(current_user)
        bids = auction_service.get_auction_bids(
            auction_id=int(auction_id), limit=int(limit)
        )
        return {"bids": bids, "total": len(bids)}
    except HTTPException:
        raise
    except auction_exceptions.AuctionError as error:
        raise _auction_error(error) from error
    except Exception as error:
        logger.error(f"获取竞拍出价历史失败: {error}")
        raise HTTPException(status_code=500, detail="获取出价历史失败") from error


@router.get("/admin/user/{user_id}/history")
@require_telegram_auth
async def get_user_auction_history_admin(
    user_id: int,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
    limit: int = 20,
):
    try:
        check_admin_permission(current_user)
        auctions = auction_service.get_user_auction_history(
            user_id=int(user_id), limit=int(limit)
        )
        return {"auctions": auctions, "total": len(auctions)}
    except HTTPException:
        raise
    except auction_exceptions.AuctionError as error:
        raise _auction_error(error) from error
    except Exception as error:
        logger.error(f"获取用户竞拍历史失败: {error}")
        raise HTTPException(status_code=500, detail="获取用户竞拍历史失败") from error


@router.get("/admin/detailed-stats")
@require_telegram_auth
async def get_detailed_auction_stats_admin(
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
    start_date: int | None = None,
    end_date: int | None = None,
):
    try:
        check_admin_permission(current_user)
        return auction_service.get_detailed_auction_stats(
            start_date=start_date, end_date=end_date
        )
    except HTTPException:
        raise
    except auction_exceptions.AuctionError as error:
        raise _auction_error(error) from error
    except Exception as error:
        logger.error(f"获取详细竞拍统计失败: {error}")
        raise HTTPException(status_code=500, detail="获取详细统计失败") from error
