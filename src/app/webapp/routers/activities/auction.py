from datetime import datetime, timedelta

from app.config import settings
from app.db import DB
from app.log import uvicorn_logger as logger
from app.update_db import finish_expired_auctions_job
from app.utils import get_user_name_from_tg_id, send_message_by_url
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.routers.admin import check_admin_permission
from app.webapp.schemas import (
    AuctionDetailResponse,
    AuctionItem,
    AuctionListResponse,
    AuctionStatsResponse,
    CreateAuctionRequest,
    PlaceBidRequest,
    PlaceBidResponse,
    TelegramUser,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status

router = APIRouter(prefix="/auction", tags=["auction"])


@router.get("/list", response_model=AuctionListResponse)
@require_telegram_auth
async def get_auction_list(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取竞拍列表"""
    try:
        db = DB()
        auctions_data = db.get_active_auctions()

        auctions = []
        for auction_data in auctions_data:
            auction = AuctionItem(
                id=auction_data["id"],
                title=auction_data["title"],
                description=auction_data["description"],
                starting_price=auction_data["starting_price"],
                current_price=auction_data["current_price"],
                end_time=datetime.fromtimestamp(auction_data["end_time"]),
                created_by=auction_data["created_by"],
                created_at=datetime.fromtimestamp(auction_data["created_at"]),
                is_active=bool(auction_data["is_active"]),
                winner_id=auction_data["winner_id"],
                bid_count=auction_data["bid_count"],
            )
            auctions.append(auction)

        return AuctionListResponse(auctions=auctions, total=len(auctions))

    except Exception as e:
        logger.error(f"获取竞拍列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取竞拍列表失败"
        )
    finally:
        if "db" in locals():
            db.close()


@router.get("/stats", response_model=AuctionStatsResponse)
@require_telegram_auth
async def get_auction_stats(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取竞拍统计数据（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        db = DB()
        stats = db.get_auction_stats()

        return AuctionStatsResponse(
            total_auctions=stats["total_auctions"],
            active_auctions=stats["active_auctions"],
            total_bids=stats["total_bids"],
            total_value=stats["total_value"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取竞拍统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取统计数据失败"
        )
    finally:
        if "db" in locals():
            db.close()


@router.get("/{auction_id}", response_model=AuctionDetailResponse)
@require_telegram_auth
async def get_auction_detail(
    auction_id: int,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """获取竞拍详情"""
    try:
        db = DB()
        auction_data = db.get_auction_by_id(auction_id)

        if not auction_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="竞拍不存在"
            )

        # 获取竞拍详情
        auction = AuctionItem(
            id=auction_data["id"],
            title=auction_data["title"],
            description=auction_data["description"],
            starting_price=auction_data["starting_price"],
            current_price=auction_data["current_price"],
            end_time=datetime.fromtimestamp(auction_data["end_time"]),
            created_by=auction_data["created_by"],
            created_at=datetime.fromtimestamp(auction_data["created_at"]),
            is_active=bool(auction_data["is_active"]),
            winner_id=auction_data["winner_id"],
            bid_count=auction_data["bid_count"],
        )

        # 获取最近的出价记录
        bids_data = db.get_auction_bids(auction_id, limit=10)
        recent_bids = []
        for bid_data in bids_data:
            bid = {
                "id": bid_data["id"],
                "auction_id": bid_data["auction_id"],
                "bidder_id": bid_data["bidder_id"],
                "bid_amount": bid_data["bid_amount"],
                "bid_time": datetime.fromtimestamp(bid_data["bid_time"]),
                "bidder_name": get_user_name_from_tg_id(bid_data["bidder_id"]),
            }
            recent_bids.append(bid)

        # 检查用户是否可以出价
        user_can_bid = (
            auction.is_active
            and auction.end_time > datetime.now()
            and current_user.id != auction.created_by
        )

        # 获取用户最高出价
        user_highest_bid = db.get_user_highest_bid(auction_id, current_user.id)

        return AuctionDetailResponse(
            auction=auction,
            recent_bids=recent_bids,
            user_can_bid=user_can_bid,
            user_highest_bid=user_highest_bid,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取竞拍详情失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取竞拍详情失败"
        )
    finally:
        if "db" in locals():
            db.close()


@router.post("/create")
@require_telegram_auth
async def create_auction(
    request_data: CreateAuctionRequest,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """创建竞拍（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        db = DB()

        # 计算结束时间
        end_time = datetime.now() + timedelta(hours=request_data.duration_hours)
        end_timestamp = int(end_time.timestamp())

        # 创建竞拍
        auction_id = db.create_auction(
            title=request_data.title,
            description=request_data.description,
            starting_price=request_data.starting_price,
            end_time=end_timestamp,
            created_by=current_user.id,
        )

        if auction_id:
            logger.info(
                f"管理员 {get_user_name_from_tg_id(current_user.id)} 创建了竞拍: {request_data.title}"
            )
            return {
                "success": True,
                "message": "竞拍创建成功",
                "auction_id": auction_id,
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="创建竞拍失败"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建竞拍失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="创建竞拍失败"
        )
    finally:
        if "db" in locals():
            db.close()


@router.post("/bid", response_model=PlaceBidResponse)
@require_telegram_auth
async def place_bid(
    bid_request: PlaceBidRequest,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """出价"""
    try:
        db = DB()

        # 检查竞拍是否存在
        auction_data = db.get_auction_by_id(bid_request.auction_id)
        if not auction_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="竞拍不存在"
            )

        # 检查竞拍是否活跃且未过期
        if not auction_data["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="竞拍已结束"
            )

        import time

        if auction_data["end_time"] <= int(time.time()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="竞拍已过期"
            )

        # 检查用户不能对自己创建的竞拍出价
        if auction_data["created_by"] == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能对自己创建的竞拍出价",
            )

        # 检查出价是否高于当前价格
        if bid_request.bid_amount <= auction_data["current_price"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"出价必须高于当前价格 {auction_data['current_price']}",
            )

        # 检查用户积分是否足够
        user_credits_result = db.get_user_credits(current_user.id)
        if not user_credits_result[0]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="无法获取用户积分信息"
            )

        user_credits = user_credits_result[1]
        if user_credits < bid_request.bid_amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"积分不足，当前积分: {user_credits}，需要: {bid_request.bid_amount}",
            )

        # 出价
        success = db.place_bid(
            bid_request.auction_id, current_user.id, bid_request.bid_amount
        )

        if success:
            # 暂时不扣除积分，只在竞拍结束且获胜时才扣除
            logger.info(
                f"用户 {get_user_name_from_tg_id(current_user.id)} 对竞拍 {bid_request.auction_id} 出价 {bid_request.bid_amount}"
            )

            return PlaceBidResponse(
                success=True,
                message="出价成功",
                current_price=bid_request.bid_amount,
                user_credits=user_credits,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="出价失败"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"出价失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="出价失败"
        )
    finally:
        if "db" in locals():
            db.close()


@router.post("/finish-expired")
@require_telegram_auth
async def finish_expired_auctions(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """结束过期竞拍（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        finished_auctions = await finish_expired_auctions_job()

        logger.info(
            f"管理员 {get_user_name_from_tg_id(current_user.id)} 结束了 {len(finished_auctions)} 个过期竞拍"
        )

        return {
            "success": True,
            "message": f"已结束 {len(finished_auctions)} 个过期竞拍",
            "finished_auctions": finished_auctions,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"结束过期竞拍失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="结束过期竞拍失败"
        )


# 管理员专用路由
@router.get("/admin/list")
@require_telegram_auth
async def get_all_auctions_admin(
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
    status_filter: str = None,
    page: int = 1,
    limit: int = 20,
):
    """获取所有竞拍活动列表（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        db = DB()
        offset = (page - 1) * limit

        auctions_data = db.get_all_auctions(
            status=status_filter, limit=limit, offset=offset
        )

        auctions = []
        for auction_data in auctions_data:
            auction = AuctionItem(
                id=auction_data["id"],
                title=auction_data["title"],
                description=auction_data["description"],
                starting_price=auction_data["starting_price"],
                current_price=auction_data["current_price"],
                end_time=datetime.fromtimestamp(auction_data["end_time"]),
                created_by=auction_data["created_by"],
                created_at=datetime.fromtimestamp(auction_data["created_at"]),
                is_active=auction_data["is_active"],
                winner_id=auction_data["winner_id"],
                bid_count=auction_data["bid_count"],
            )
            # 添加状态字段
            auction.status = auction_data["status"]
            auctions.append(auction)

        return AuctionListResponse(auctions=auctions, total=len(auctions))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取竞拍列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取竞拍列表失败"
        )
    finally:
        if "db" in locals():
            db.close()


@router.put("/admin/{auction_id}")
@require_telegram_auth
async def update_auction_admin(
    auction_id: int,
    update_data: CreateAuctionRequest,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """更新竞拍活动（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        db = DB()

        # 检查竞拍是否存在
        existing_auction = db.get_auction_by_id(auction_id)
        if not existing_auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="竞拍不存在"
            )

        # 准备更新数据
        update_dict = {
            "title": update_data.title,
            "description": update_data.description,
            "starting_price": update_data.starting_price,
        }

        # 如果更新了时长，重新计算结束时间
        if hasattr(update_data, "duration_hours") and update_data.duration_hours:
            new_end_time = datetime.now() + timedelta(hours=update_data.duration_hours)
            update_dict["end_time"] = int(new_end_time.timestamp())

        success = db.update_auction(auction_id, update_dict)

        if success:
            logger.info(
                f"管理员 {get_user_name_from_tg_id(current_user.id)} 更新了竞拍 {auction_id}"
            )
            return {"success": True, "message": "竞拍更新成功"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新竞拍失败"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新竞拍失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新竞拍失败"
        )
    finally:
        if "db" in locals():
            db.close()


@router.delete("/admin/{auction_id}")
@require_telegram_auth
async def delete_auction_admin(
    auction_id: int,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """删除竞拍活动（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        db = DB()

        # 检查竞拍是否存在
        existing_auction = db.get_auction_by_id(auction_id)
        if not existing_auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="竞拍不存在"
            )

        success = db.delete_auction(auction_id)

        if success:
            logger.info(
                f"管理员 {get_user_name_from_tg_id(current_user.id)} 删除了竞拍 {auction_id}"
            )
            return {"success": True, "message": "竞拍删除成功"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除竞拍失败"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除竞拍失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除竞拍失败"
        )
    finally:
        if "db" in locals():
            db.close()


@router.post("/admin/{auction_id}/finish")
@require_telegram_auth
async def finish_auction_admin(
    auction_id: int,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """手动结束竞拍活动（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        db = DB()

        # 检查竞拍是否存在且处于活跃状态
        existing_auction = db.get_auction_by_id(auction_id)
        if not existing_auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="竞拍不存在"
            )

        if not existing_auction["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="竞拍已结束"
            )

        success, winner = db.finish_auction_by_id(auction_id)

        if success:
            logger.info(
                f"管理员 {get_user_name_from_tg_id(current_user.id)} 手动结束了竞拍 {auction_id}"
            )
            # 通知用户
            if winner:
                await send_message_by_url(
                    winner.get("winner_id"),
                    f"恭喜你，竞拍 {existing_auction['title']} 获胜！最终出价为 {winner.get('final_price')} 积分",
                )
                if not winner.get("credits_reduced", False):
                    # 如果未扣除积分，通知管理员
                    for chat_id in settings.ADMIN_CHAT_ID:
                        await send_message_by_url(
                            chat_id=chat_id,
                            text=f"用户 {winner.get('winner_id')} 在竞拍 {existing_auction['title']} 中获胜，但未扣除积分。",
                        )
            return {
                "success": True,
                "message": "竞拍已结束",
                "finished_auctions": [winner],
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="结束竞拍失败"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"结束竞拍失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="结束竞拍失败"
        )
    finally:
        if "db" in locals():
            db.close()


@router.get("/admin/{auction_id}/bids")
@require_telegram_auth
async def get_auction_bids_admin(
    auction_id: int,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
    limit: int = 50,
):
    """获取竞拍出价历史（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        db = DB()

        # 检查竞拍是否存在
        existing_auction = db.get_auction_by_id(auction_id)
        if not existing_auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="竞拍不存在"
            )

        bids_data = db.get_auction_bids(auction_id, limit=limit)

        bids = []
        for bid_data in bids_data:
            bid = {
                "id": bid_data["id"],
                "auction_id": bid_data["auction_id"],
                "bidder_id": bid_data["bidder_id"],
                "bid_amount": bid_data["bid_amount"],
                "bid_time": datetime.fromtimestamp(bid_data["bid_time"]),
                "bidder_name": bid_data.get(
                    "bidder_name", f"用户{bid_data['bidder_id']}"
                ),
            }
            bids.append(bid)

        return {"bids": bids, "total": len(bids)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取竞拍出价历史失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取出价历史失败"
        )
    finally:
        if "db" in locals():
            db.close()


@router.get("/admin/user/{user_id}/history")
@require_telegram_auth
async def get_user_auction_history_admin(
    user_id: int,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
    limit: int = 20,
):
    """获取用户竞拍历史（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        db = DB()
        auctions_data = db.get_user_auction_history(user_id, limit=limit)

        auctions = []
        for auction_data in auctions_data:
            auction = {
                "id": auction_data["id"],
                "title": auction_data["title"],
                "description": auction_data["description"],
                "starting_price": auction_data["starting_price"],
                "current_price": auction_data["current_price"],
                "end_time": datetime.fromtimestamp(auction_data["end_time"]),
                "created_at": datetime.fromtimestamp(auction_data["created_at"]),
                "is_active": auction_data["is_active"],
                "user_highest_bid": auction_data["user_highest_bid"],
                "is_winner": auction_data["is_winner"],
            }
            auctions.append(auction)

        return {"auctions": auctions, "total": len(auctions)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户竞拍历史失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户竞拍历史失败",
        )
    finally:
        if "db" in locals():
            db.close()


@router.get("/admin/detailed-stats")
@require_telegram_auth
async def get_detailed_auction_stats_admin(
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
    start_date: int = None,
    end_date: int = None,
):
    """获取详细竞拍统计（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        db = DB()
        stats = db.get_detailed_auction_stats(start_date=start_date, end_date=end_date)

        return stats

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取详细竞拍统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取详细统计失败"
        )
    finally:
        if "db" in locals():
            db.close()
