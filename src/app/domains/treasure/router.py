from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.core.number import normalize_external_random_b
from app.core.schemas import TelegramUser
from app.databases import db
from app.domains.badge_awards.jobs import check_and_award_game_king_badge
from app.domains.treasure.jobs import schedule_auto_reopen_treasure_issue
from app.domains.treasure.notifications import (
    notify_treasure_issue_created,
    notify_treasure_not_full_after_join,
    notify_treasure_settled,
)
from app.domains.treasure.schemas import (
    TreasureCreateIssueRequest,
    TreasureIssueDetailResponse,
    TreasureIssueItem,
    TreasureIssueListResponse,
    TreasureJoinRequest,
    TreasureJoinResponse,
    TreasureParticipationItem,
    TreasureParticipationListResponse,
)


async def _get_eth_latest_block_hash_int() -> int:
    """获取以太坊最新区块哈希并转为整数 B。

    说明：这里用最轻量的 JSON-RPC 调用，不引入额外依赖；RPC URL 从环境读取。
    """
    import aiohttp

    from app.core.config import settings

    rpc_url = getattr(settings, "ETH_RPC_URL", "")
    if not rpc_url:
        raise RuntimeError("ETH_RPC_URL not configured")

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBlockByNumber",
        "params": ["latest", False],
    }

    timeout = aiohttp.ClientTimeout(total=6)
    async with (
        aiohttp.ClientSession(timeout=timeout) as session,
        session.post(rpc_url, json=payload) as resp,
    ):
        resp.raise_for_status()
        data = await resp.json()
        result = data.get("result") or {}
        block_hash = result.get("hash")
        if not block_hash or not isinstance(block_hash, str):
            raise RuntimeError("failed to get latest block hash")

        # hash like '0xabc...'; normalize to signed BIGINT-safe non-negative range.
        return normalize_external_random_b(int(block_hash, 16), default=0) or 0


router = APIRouter(prefix="/treasure", tags=["夺宝奇兵"])


@router.get("/user-stats")
@require_telegram_auth
async def get_user_treasure_stats(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取用户个人夺宝统计数据。"""
    try:
        stats = db.get_user_treasure_stats(int(current_user.id))
        return {"success": True, "data": stats}
    except Exception as e:
        logger.error(f"获取用户夺宝统计失败: {e}")
        raise HTTPException(status_code=500, detail="获取用户夺宝统计失败")


@router.get("/list", response_model=TreasureIssueListResponse)
@require_telegram_auth
async def list_issues(
    request: Request,
    include_closed: bool = True,
    limit: int = 50,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        issues = db.list_treasure_issues(limit=limit, include_closed=include_closed)
        items = [TreasureIssueItem(**i) for i in issues]
        return TreasureIssueListResponse(issues=items, total=len(items))
    except Exception as e:
        logger.error(f"获取夺宝期数列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取夺宝期数列表失败")


@router.get("/{issue_id}", response_model=TreasureIssueDetailResponse)
@require_telegram_auth
async def get_issue_detail(
    request: Request,
    issue_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    issue = db.get_treasure_issue_by_id(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="期数不存在")

    item = TreasureIssueItem(**issue)
    return TreasureIssueDetailResponse(
        issue=item,
        description=issue.get("description"),
        external_random_b=issue.get("external_random_b"),
        settled_at=issue.get("settled_at"),
    )


@router.get(
    "/{issue_id}/participations",
    response_model=TreasureParticipationListResponse,
)
@require_telegram_auth
async def list_participations(
    request: Request,
    issue_id: int,
    limit: int = 100,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        rows = db.list_treasure_participations(issue_id=issue_id, limit=limit)
        items = [TreasureParticipationItem(**r) for r in rows]
        return TreasureParticipationListResponse(participations=items, total=len(items))
    except Exception as e:
        logger.error(f"获取参与记录失败: {e}")
        raise HTTPException(status_code=500, detail="获取参与记录失败")


@router.post("/{issue_id}/join", response_model=TreasureJoinResponse)
@require_telegram_auth
async def join_issue(
    request: Request,
    issue_id: int,
    background_tasks: BackgroundTasks,
    data: TreasureJoinRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    try:
        eth_b = None
        # 不要求每次都拉：仅作为“更强的外部B”来源，当满员触发开奖时 DB 层会用到。
        # 这里先尝试拉取并传入，拉取失败不会阻塞参与（仅日志记录）。
        try:
            eth_b = await _get_eth_latest_block_hash_int()
        except Exception as e:
            logger.warning(f"获取以太坊最新区块hash失败: {e}")

        # 如果用户没有提供 external_random_b 且 ETH hash 也取不到，避免最后开奖落到 B=0。
        # 只在“本次参与会触发满员开奖”时生成随机 B，避免每次参与都消耗一次随机数。
        fallback_b = None
        if eth_b is None:
            try:
                issue = db.get_treasure_issue_by_id(issue_id)
                if issue:
                    qty = int(getattr(data, "quantity", 1))
                    remaining = int(issue.get("total_shares", 0)) - int(
                        issue.get("shares_sold", 0)
                    )
                    if remaining > 0 and qty >= remaining:
                        import hashlib
                        import hmac
                        import time

                        from app.core.config import settings

                        # 兜底B需要：可复现（同样输入 -> 同样输出）、不可预测（依赖服务器密钥）。
                        # 说明：这里的材料选用“触发开奖时”在服务端可确定的一组字段，
                        # 并把参与请求时间戳纳入，避免不同轮次碰撞。
                        secret = getattr(settings, "TG_API_TOKEN", "")
                        if not secret:
                            raise RuntimeError("TG_API_TOKEN not configured")

                        ts_ms = int(
                            getattr(data, "timestamp_ms", 0) or int(time.time() * 1000)
                        )
                        msg = (
                            f"treasure|fallback_b|issue_id={int(issue_id)}|"
                            f"total={int(issue.get('total_shares', 0))}|"
                            f"sold={int(issue.get('shares_sold', 0))}|"
                            f"qty={int(qty)}|tg_id={int(current_user.id)}|ts_ms={int(ts_ms)}"
                        ).encode()

                        digest = hmac.new(
                            secret.encode("utf-8"), msg, hashlib.sha256
                        ).digest()
                        fallback_b = normalize_external_random_b(
                            int.from_bytes(digest[:8], "big", signed=False)
                        )
                        logger.info(
                            "ETH hash unavailable; using deterministic fallback B for settlement"
                        )
            except Exception as e:
                logger.warning(f"生成随机兜底B失败，将继续使用默认B=0: {e}")

        safe_external_b = normalize_external_random_b(
            eth_b if eth_b is not None else fallback_b
        )

        res = db.join_treasure_issue(
            issue_id=issue_id,
            tg_id=int(current_user.id),
            external_random_b=safe_external_b,
            quantity=int(getattr(data, "quantity", 1)),
        )

        # 若未满员：发送群组进度通知（失败不影响接口返回）
        if not res.get("settled"):
            try:
                issue_full = db.get_treasure_issue_by_id(issue_id)
                bought_shares = len(res.get("participations") or [])
                issue_state = res.get("issue") or {}

                await notify_treasure_not_full_after_join(
                    issue_id=int(issue_id),
                    title=str(issue_full.get("title")) if issue_full else None,
                    joiner_tg_id=int(current_user.id),
                    bought_shares=int(bought_shares) if bought_shares else 1,
                    shares_sold=int(issue_state.get("shares_sold") or 0),
                    total_shares=int(issue_state.get("total_shares") or 0),
                    prize_credits=int(issue_full.get("prize_credits")),
                )
            except Exception as e:
                logger.warning(f"Treasure progress notify failed: {e}")

        # 若本次触发结算：发送 TG 通知 + 安排 10 分钟后自动续期（失败不影响接口返回）
        if res.get("settled"):
            issue = db.get_treasure_issue_by_id(issue_id)

            if issue and issue.get("winner_tg_id") and issue.get("winner_number"):
                try:
                    await notify_treasure_settled(
                        issue_id=int(issue_id),
                        title=str(issue.get("title")),
                        winner_tg_id=int(issue.get("winner_tg_id")),
                        winner_number=int(issue.get("winner_number")),
                        prize_credits=int(issue.get("prize_credits")),
                    )
                except Exception as e:
                    logger.warning(f"Treasure settle notify failed: {e}")

            try:
                # 结算成功后，延时创建下一期（同规格）
                schedule_auto_reopen_treasure_issue(source_issue_id=int(issue_id))
            except Exception as e:
                logger.warning(f"Treasure auto reopen schedule failed: {e}")

        background_tasks.add_task(
            check_and_award_game_king_badge,
            user_id=int(current_user.id),
        )

        return TreasureJoinResponse(
            success=True,
            message="参与成功",
            participation=res.get("participation"),
            participations=res.get("participations"),
            issue=res.get("issue"),
            settled=bool(res.get("settled")),
            winner_number=res.get("winner_number"),
            winner_tg_id=res.get("winner_tg_id"),
        )
    except ValueError as e:
        msg = str(e)
        msg_l = msg.lower()
        if "insufficient" in msg:
            raise HTTPException(status_code=400, detail="积分不足")
        if "not active" in msg:
            raise HTTPException(status_code=400, detail="本期已结束")
        if "full" in msg:
            raise HTTPException(status_code=400, detail="本期已满员")
        if "not found" in msg:
            raise HTTPException(status_code=404, detail="期数不存在")

        # join 参数/限制类错误
        if "quantity must be" in msg_l:
            raise HTTPException(status_code=400, detail="参与份数必须大于0")
        if "quantity too large" in msg_l:
            raise HTTPException(status_code=400, detail="参与份数过大")
        if "purchase limit exceeded" in msg_l:
            raise HTTPException(status_code=400, detail="超过单用户购买上限")
        if "user stats not found" in msg_l:
            raise HTTPException(status_code=400, detail="用户积分信息不存在")

        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        logger.error(f"参与夺宝失败: {e}")
        raise HTTPException(status_code=500, detail="参与失败")


@router.post("/create", response_model=dict)
@require_telegram_auth
async def create_issue(
    request: Request,
    data: TreasureCreateIssueRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    # 管理员创建
    check_admin_permission(current_user)
    try:
        title = (getattr(data, "title", None) or "").strip()
        if not title:
            from datetime import datetime

            now = datetime.now(settings.TZ).strftime("%Y-%m-%d-%H:%M:%S")
            title = f"夺宝奇兵 {now}"

        issue_id = db.create_treasure_issue(
            title=title,
            description=data.description,
            prize_credits=data.prize_credits,
            total_credits_required=data.total_credits_required,
            credits_per_share=data.credits_per_share,
            start_number=data.start_number,
            created_by=int(current_user.id),
        )

        # 新期数群组通知（失败不影响创建）
        try:
            created = db.get_treasure_issue_by_id(issue_id)
            if created:
                await notify_treasure_issue_created(
                    issue_id=int(issue_id),
                    title=str(created.get("title")),
                    total_shares=int(created.get("total_shares")),
                    credits_per_share=int(created.get("credits_per_share")),
                    prize_credits=int(created.get("prize_credits")),
                )
        except Exception as e:
            logger.warning(f"Treasure create notify failed: {e}")

        return {"success": True, "issue_id": issue_id}
    except ValueError as e:
        msg = str(e)
        msg_l = msg.lower()
        if "total_shares" in msg_l and "must be" in msg_l:
            raise HTTPException(status_code=400, detail="总份数必须大于0")
        if "divisible" in msg_l and "credits_per_share" in msg_l:
            raise HTTPException(
                status_code=400, detail="总所需积分必须能被每份积分整除"
            )
        if "invalid credits settings" in msg_l:
            raise HTTPException(
                status_code=400, detail="积分配置不合法（奖池必须大于0且不超过总积分）"
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    except Exception as e:
        logger.error(f"创建夺宝期数失败: {e}")
        raise HTTPException(status_code=500, detail="创建失败")


@router.post("/{issue_id}/cancel", response_model=dict)
@require_telegram_auth
async def cancel_issue(
    request: Request,
    issue_id: int,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """管理员取消进行中的夺宝期数，并退还参与者积分。"""

    check_admin_permission(current_user)
    try:
        res = db.cancel_treasure_issue(issue_id=issue_id)
        return {"success": True, **res}
    except ValueError as e:
        msg = str(e).lower()
        if "not found" in msg:
            raise HTTPException(status_code=404, detail="期数不存在")
        if "not active" in msg:
            raise HTTPException(status_code=400, detail="仅进行中的期数可删除")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"取消夺宝期数失败: {e}")
        raise HTTPException(status_code=500, detail="删除失败")
