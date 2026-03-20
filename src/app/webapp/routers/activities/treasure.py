from app.config import settings
from app.databases import db
from app.log import uvicorn_logger as logger
from app.utils.number import normalize_external_random_b
from app.utils.utils import get_user_name_from_tg_id
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.routers.admin import check_admin_permission
from app.webapp.schemas import TelegramUser
from app.webapp.schemas.treasure import (
    TreasureCreateIssueRequest,
    TreasureIssueDetailResponse,
    TreasureIssueItem,
    TreasureIssueListResponse,
    TreasureJoinRequest,
    TreasureJoinResponse,
    TreasureParticipationItem,
    TreasureParticipationListResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status


async def _auto_create_next_treasure_issue_from(*, source_issue_id: int) -> None:
    """在指定期数开奖后，自动创建“同规格”的下一期。"""

    try:
        source = db.get_treasure_issue_by_id(int(source_issue_id))
        if not source:
            logger.warning(
                f"Treasure auto reopen: source issue not found: {source_issue_id}"
            )
            return
        if int(source.get("status") or 0) != 2:
            logger.info(
                f"Treasure auto reopen: source issue not settled; skip: {source_issue_id}"
            )
            return

        from datetime import datetime

        now = datetime.now(settings.TZ).strftime("%Y-%m-%d-%H:%M:%S")
        # 标题不强制与上一期相同，避免列表中难以区分；规格（积分配置）保持一致。
        title = f"夺宝奇兵 {now}"

        issue_id = db.create_treasure_issue(
            title=title,
            description=source.get("description"),
            prize_credits=int(source.get("prize_credits") or 0),
            total_credits_required=int(source.get("total_credits_required") or 0),
            credits_per_share=int(source.get("credits_per_share") or 10),
            start_number=None,  # 新一期重新随机起始号
            created_by=source.get("created_by"),
        )

        try:
            created = db.get_treasure_issue_by_id(int(issue_id))
            if created:
                await notify_treasure_issue_created(
                    issue_id=int(issue_id),
                    title=str(created.get("title")),
                    total_shares=int(created.get("total_shares")),
                    credits_per_share=int(created.get("credits_per_share")),
                    prize_credits=int(created.get("prize_credits")),
                )
        except Exception as e:
            logger.warning(f"Treasure auto reopen notify failed: {e}")

        logger.info(
            f"Treasure auto reopen: created next issue {issue_id} from {source_issue_id}"
        )
    except Exception as e:
        logger.error(f"Treasure auto reopen failed (source={source_issue_id}): {e}")


def schedule_auto_reopen_treasure_issue(*, source_issue_id: int) -> None:
    """安排在开奖后 N 分钟自动开新一期。"""

    delay_min = 10
    if delay_min <= 0:
        # 允许配置为 0 表示立即创建（仍通过调度器走异步）
        delay_min = 0

    try:
        from datetime import datetime, timedelta

        from app.scheduler import Scheduler

        run_date = datetime.now(settings.TZ) + timedelta(minutes=int(delay_min))
        job_id = f"treasure_auto_reopen_{int(source_issue_id)}"
        Scheduler().add_async_job(
            func=_auto_create_next_treasure_issue_from,
            trigger="date",
            id=job_id,
            replace_existing=True,
            max_instances=1,
            run_date=run_date,
            kwargs={"source_issue_id": int(source_issue_id)},
            jobstore="sqlalchemy",  # 使用持久化存储，避免服务重启导致任务丢失
        )
        logger.info(
            f"Treasure auto reopen scheduled: source={source_issue_id}, delay_min={delay_min}"
        )
    except Exception as e:
        logger.error(f"Treasure auto reopen schedule failed: {e}")


def _get_group_chat_id() -> str | None:
    """获取用于群组通知的 chat_id。

    群组通知明确使用 TG_GROUP（可以是数字 ID 或 @username）。
    未配置则跳过群组通知。
    """
    from app.config import settings

    if getattr(settings, "TG_GROUP_ID", None):
        return str(settings.TG_GROUP_ID)
    return None


async def notify_treasure_issue_created(
    *,
    issue_id: int,
    title: str,
    total_shares: int,
    credits_per_share: int,
    prize_credits: int,
) -> None:
    """新期数创建后群组通知（若 TG_GROUP 未配置则跳过）。"""

    from app.utils.utils import send_message_by_url

    chat_id = _get_group_chat_id()
    if not chat_id:
        logger.info("TG_GROUP not configured; skip treasure created notification")
        return

    text = (
        f"🎁 <b>夺宝奇兵</b> 新期数已开启\n"
        f"期数ID：{issue_id}\n"
        f"标题：{title}\n"
        f"每份：{credits_per_share} 积分\n"
        f"总份数：{total_shares}\n"
        f"奖池：{prize_credits} 积分\n"
        f"入口：WebApp 活动页 → 夺宝奇兵"
    )
    await send_message_by_url(chat_id=chat_id, text=text, parse_mode="HTML")


async def notify_treasure_settled(
    *,
    issue_id: int,
    title: str,
    winner_tg_id: int,
    winner_number: int,
    prize_credits: int,
) -> None:
    """开奖结算后的通知：中奖者私聊 + 群组公告（若 TG_GROUP 未配置则跳过）。"""

    from app.utils.utils import send_message_by_url

    # 1) 通知中奖者（私聊）
    try:
        text_user = (
            f"🎉 恭喜你中奖！\n"
            f"期数ID：{issue_id}\n"
            f"标题：{title}\n"
            f"中奖号码：{winner_number}\n"
            f"已发放奖池：{prize_credits} 积分"
        )
        await send_message_by_url(chat_id=winner_tg_id, text=text_user)
    except Exception as e:
        logger.warning(f"Notify winner failed: {e}")

    # 2) 群组公告
    chat_id = _get_group_chat_id()
    if not chat_id:
        return
    text_group = (
        f"🏁 <b>夺宝奇兵</b> 已开奖\n"
        f"期数ID：{issue_id}\n"
        f"标题：{title}\n"
        f"中奖号码：{winner_number}\n"
        f"中奖用户：<code>{get_user_name_from_tg_id(winner_tg_id)}</code>\n"
        f"奖池：{prize_credits} 积分"
    )
    await send_message_by_url(chat_id=chat_id, text=text_group, parse_mode="HTML")


async def notify_treasure_not_full_after_join(
    *,
    issue_id: int,
    title: str | None,
    joiner_tg_id: int,
    bought_shares: int,
    shares_sold: int,
    total_shares: int,
    prize_credits: int,
) -> None:
    """用户参与后，若未满员则群组通知当前进度与距离开奖剩余人数/份数。"""

    from app.utils.utils import send_message_by_url

    chat_id = _get_group_chat_id()
    if not chat_id:
        return

    try:
        remaining = max(0, int(total_shares) - int(shares_sold))
    except Exception:
        remaining = 0

    # 仅在未满员时通知（remaining==0 的情况由开奖公告覆盖）
    if remaining <= 0:
        return

    text = (
        f"🧩 <b>夺宝奇兵 #{int(issue_id)}</b> 有新参与\n"
        f"标题：{title or 'N/A'}\n"
        f"奖池：{prize_credits} 积分\n"
        f"参与用户：<code>{get_user_name_from_tg_id(joiner_tg_id) or joiner_tg_id}</code>\n"
        f"已购买份数：{bought_shares}\n"
        f"距离开奖还差：{int(remaining)} 份"
    )
    await send_message_by_url(chat_id=chat_id, text=text, parse_mode="HTML")


async def _get_eth_latest_block_hash_int() -> int:
    """获取以太坊最新区块哈希并转为整数 B。

    说明：这里用最轻量的 JSON-RPC 调用，不引入额外依赖；RPC URL 从环境读取。
    """
    import aiohttp
    from app.config import settings

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
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(rpc_url, json=payload) as resp:
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

                        from app.config import settings

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
                        ).encode("utf-8")

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
