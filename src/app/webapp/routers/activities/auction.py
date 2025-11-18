from datetime import datetime, timedelta

from app.config import settings
from app.databases import db
from app.databases.db_func import finish_expired_auctions_job
from app.log import uvicorn_logger as logger
from app.scheduler import Scheduler
from app.utils.utils import get_user_name_from_tg_id, send_message_by_url
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
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

router = APIRouter(prefix="/auction", tags=["auction"])


async def finish_single_auction_job(auction_id: int):
    """
    单个竞拍结束任务
    """
    try:
        # 检查竞拍是否存在且处于活跃状态
        auction_data = db.get_auction_by_id(auction_id)
        if not auction_data or not auction_data["is_active"]:
            logger.info(f"竞拍 {auction_id} 不存在或已结束，跳过自动结束任务")
            return

        # 结束竞拍
        success, winner = db.finish_auction_by_id(auction_id)

        if success and winner:
            # 通知用户
            await send_message_by_url(
                winner.get("winner_id"),
                f"恭喜你，竞拍 {auction_data['title']} 获胜！最终出价为 {winner.get('final_price')} 积分",
            )
            if not winner.get("credits_reduced", False):
                # 如果未扣除积分，通知管理员
                for chat_id in settings.TG_ADMIN_CHAT_ID:
                    await send_message_by_url(
                        chat_id=chat_id,
                        text=f"用户 {winner.get('winner_id')} 在竞拍 {auction_data['title']} 中获胜，但未扣除积分。",
                    )
            logger.info(f"竞拍 {auction_id} 自动结束成功")
        else:
            logger.warning(f"竞拍 {auction_id} 自动结束失败")

    except Exception as e:
        logger.error(f"自动结束竞拍 {auction_id} 失败: {e}")


def restore_auction_schedules():
    """
    启动时恢复现有活跃竞拍的定时任务
    """
    try:
        scheduler = Scheduler()

        # 获取所有活跃的竞拍
        active_auctions = db.get_active_auctions()

        import time

        current_time = int(time.time())

        for auction_data in active_auctions:
            auction_id = auction_data["id"]
            end_time = auction_data["end_time"]

            # 跳过已过期的竞拍（这些会被兜底任务处理）
            if end_time <= current_time:
                logger.warning(f"竞拍 {auction_id} 已过期，将由兜底任务处理")
                continue

            # 为未过期的竞拍创建定时任务
            job_id = f"finish_auction_{auction_id}"
            end_datetime = datetime.fromtimestamp(end_time)

            scheduler.add_async_job(
                func=finish_single_auction_job,
                args=[auction_id],
                trigger="date",
                run_date=end_datetime,
                id=job_id,
                replace_existing=True,
                max_instances=1,
            )

            logger.info(f"恢复竞拍 {auction_id} 的定时任务，结束时间: {end_datetime}")

        logger.info(
            f"已恢复 {len([a for a in active_auctions if a['end_time'] > current_time])} 个竞拍的定时任务"
        )

    except Exception as e:
        logger.error(f"恢复竞拍定时任务失败: {e}")


async def send_bid_notifications(
    auction_id: int,
    bidder_id: int,
    bid_amount: float,
    auction_title: str,
    bid_count: int,
):
    """
    后台任务：发送出价通知给其他参与者和管理员
    """
    try:
        # 获取该拍卖的其他参与者
        other_participants = db.get_auction_participants(
            auction_id, exclude_user_id=bidder_id
        )

        # 准备通知消息
        bidder_name = get_user_name_from_tg_id(bidder_id)

        # 通知其他参与者
        participant_message = (
            f"🔔 竞拍更新通知\n\n"
            f"📝 竞拍: {auction_title}\n"
            f"👤 最新出价 {bid_amount} 积分\n\n"
            f"快来查看详情并参与竞拍吧！"
        )

        for participant_id in other_participants:
            try:
                await send_message_by_url(
                    chat_id=participant_id, text=participant_message
                )
            except Exception as e:
                logger.warning(f"发送通知给参与者 {participant_id} 失败: {e}")

        # 通知管理员
        admin_message = (
            f"🎯 拍卖新出价通知\n\n"
            f"📝 竞拍: {auction_title}\n"
            f"👤 出价者: {bidder_name} (ID: {bidder_id})\n"
            f"💰 出价金额: {bid_amount} 积分\n"
            f"📊 总出价次数: {bid_count}"
        )

        for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
            try:
                await send_message_by_url(chat_id=admin_chat_id, text=admin_message)
            except Exception as e:
                logger.warning(f"发送通知给管理员 {admin_chat_id} 失败: {e}")

        logger.info(f"成功发送出价通知，竞拍ID: {auction_id}, 出价者: {bidder_id}")

    except Exception as e:
        logger.error(f"发送出价通知失败: {e}")


@router.get("/list", response_model=AuctionListResponse)
@require_telegram_auth
async def get_auction_list(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取竞拍列表"""
    try:
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


@router.get("/stats", response_model=AuctionStatsResponse)
@require_telegram_auth
async def get_auction_stats(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取竞拍统计数据（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

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


@router.get("/{auction_id}", response_model=AuctionDetailResponse)
@require_telegram_auth
async def get_auction_detail(
    auction_id: int,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """获取竞拍详情"""
    try:
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
            # 添加定时任务：在竞拍结束时间自动结束竞拍
            scheduler = Scheduler()
            job_id = f"finish_auction_{auction_id}"

            scheduler.add_async_job(
                func=finish_single_auction_job,
                args=[auction_id],
                trigger="date",
                run_date=end_time,
                id=job_id,
                replace_existing=True,
                max_instances=1,
            )

            logger.info(
                f"管理员 {get_user_name_from_tg_id(current_user.id)} 创建了竞拍: {request_data.title}，"
                f"将在 {end_time} 自动结束"
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


@router.post("/bid", response_model=PlaceBidResponse)
@require_telegram_auth
async def place_bid(
    bid_request: PlaceBidRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """出价"""
    try:
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

            # 添加后台任务发送通知
            auction_title = auction_data.get("title", f"竞拍 #{bid_request.auction_id}")
            background_tasks.add_task(
                send_bid_notifications,
                auction_id=bid_request.auction_id,
                bidder_id=current_user.id,
                bid_amount=bid_request.bid_amount,
                auction_title=auction_title,
                bid_count=auction_data["bid_count"] + 1,
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

        scheduler = Scheduler()
        old_job_id = f"finish_auction_{auction_id}"

        # 如果更新了时长，重新计算结束时间
        if hasattr(update_data, "duration_hours") and update_data.duration_hours:
            new_end_time = datetime.now() + timedelta(hours=update_data.duration_hours)
            update_dict["end_time"] = int(new_end_time.timestamp())

            # 移除旧的定时任务
            try:
                scheduler.remove_job(old_job_id)
                logger.info(f"移除竞拍 {auction_id} 的旧定时任务")
            except Exception as e:
                logger.warning(f"移除竞拍 {auction_id} 旧定时任务失败: {e}")

            # 添加新的定时任务
            scheduler.add_async_job(
                func=finish_single_auction_job,
                args=[auction_id],
                trigger="date",
                run_date=new_end_time,
                id=old_job_id,
                replace_existing=True,
                max_instances=1,
            )
            logger.info(f"为竞拍 {auction_id} 设置新的结束时间: {new_end_time}")

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

        # 检查竞拍是否存在
        existing_auction = db.get_auction_by_id(auction_id)
        if not existing_auction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="竞拍不存在"
            )

        # 移除对应的定时任务
        scheduler = Scheduler()
        job_id = f"finish_auction_{auction_id}"
        try:
            scheduler.remove_job(job_id)
            logger.info(f"移除竞拍 {auction_id} 的定时任务")
        except Exception as e:
            logger.warning(f"移除竞拍 {auction_id} 定时任务失败: {e}")

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

        # 移除对应的定时任务
        scheduler = Scheduler()
        job_id = f"finish_auction_{auction_id}"
        try:
            scheduler.remove_job(job_id)
            logger.info(f"移除竞拍 {auction_id} 的定时任务（手动结束）")
        except Exception as e:
            logger.warning(f"移除竞拍 {auction_id} 定时任务失败: {e}")

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
                    for chat_id in settings.TG_ADMIN_CHAT_ID:
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
                "bidder_name": get_user_name_from_tg_id(bid_data["bidder_id"]),
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

        stats = db.get_detailed_auction_stats(start_date=start_date, end_date=end_date)

        return stats

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取详细竞拍统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取详细统计失败"
        )
