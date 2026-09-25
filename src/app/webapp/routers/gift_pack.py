"""
礼包（Gift Pack）路由 —— 用户端与管理端

通知策略：只在里程碑与异常节点通知管理员（上线 / 限量领完 / 过期汇总 / 发放失败），
日常逐笔领取一律不通知——`notify_admins_by_url()` 是逐管理员逐条发 TG 消息，
按笔通知在运营活动的量级下会刷屏并触发 Telegram 限流。
"""

import asyncio
import json
from datetime import datetime
from html import escape
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    HTTPException,
    Request,
    status,
)

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.databases import db
from app.utils.utils import (
    get_user_name_from_tg_id,
    notify_admins_by_url,
    send_message_by_url,
)
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.routers.admin import check_admin_permission
from app.webapp.schemas import TelegramUser
from app.webapp.schemas.gift_pack import (
    GiftPackAdminItem,
    GiftPackAdminListResponse,
    GiftPackClaimRecordItem,
    GiftPackClaimRecordListResponse,
    GiftPackClaimResponse,
    GiftPackClaimRewardResult,
    GiftPackCreateRequest,
    GiftPackItem,
    GiftPackListResponse,
    GiftPackPromptCheckResponse,
    GiftPackPromptItem,
    GiftPackSetEnabledRequest,
    GiftPackStatsResponse,
    GiftPackTaskPromptItem,
    GiftPackUpdateRequest,
)

router = APIRouter(
    prefix="/api/gift-packs",
    tags=["gift-packs"],
    responses={404: {"description": "Not found"}},
)


# ==================== 通知 ====================


def _format_time(timestamp: int) -> str:
    """按服务端配置时区格式化时间，保证与管理端录入口径一致"""
    return datetime.fromtimestamp(int(timestamp), settings.TZ).strftime(
        "%Y-%m-%d %H:%M"
    )


def _format_rewards(rewards: list[dict]) -> str:
    return "、".join(db._gift_pack_reward_label(r) for r in rewards)


# 持有强引用，避免 fire-and-forget 的 task 被 GC 提前回收
_pending_notifications: set = set()


def _notify_detached(coro) -> None:
    """在异常路径上发通知

    不能用 `BackgroundTasks`：它只在响应正常返回后才执行，抛 `HTTPException`
    时整条后台任务链会被跳过——而发放失败恰恰是最需要通知的场景。
    """
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        # 没有运行中的事件循环（同步上下文），退回同步执行
        asyncio.run(coro)
        return
    _pending_notifications.add(task)
    task.add_done_callback(_pending_notifications.discard)


async def notify_gift_pack_created(pack: dict) -> None:
    """礼包上线通知"""
    try:
        quantity = (
            f"{pack['total_quantity']} 份" if pack.get("total_quantity") else "不限量"
        )
        text = (
            "🎁 <b>礼包已上线</b>\n\n"
            f"<b>标题：</b>{pack['title']}\n"
            f"<b>奖励：</b>{_format_rewards(pack['rewards'])}\n"
            f"<b>限量：</b>{quantity}\n"
            f"<b>时间窗：</b>{_format_time(pack['start_at'])} ~ {_format_time(pack['end_at'])}\n"
            f"<b>状态：</b>{'已启用' if pack.get('is_enabled') else '未启用'}"
        )
        await notify_admins_by_url(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"发送礼包上线通知失败 (pack_id={pack.get('id')}): {e}")


async def notify_gift_pack_sold_out(pack_id: int, title: str, total_quantity: int):
    """限量礼包领完通知

    并发下只有一个事务能把计数加到满，天然只触发一次。
    """
    try:
        text = (
            "🎁 <b>礼包已领完</b>\n\n"
            f"<b>标题：</b>{title}\n"
            f"<b>总份数：</b>{total_quantity} 份已全部领取"
        )
        await notify_admins_by_url(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"发送礼包领完通知失败 (pack_id={pack_id}): {e}")


async def notify_gift_pack_claim_failed(pack_id: int, tg_id: int, reason: str):
    """奖励发放失败的异常通知"""
    try:
        user_name = get_user_name_from_tg_id(tg_id) or str(tg_id)
        pack = db.get_gift_pack_by_id(pack_id)
        title = pack["title"] if pack else f"#{pack_id}"
        text = (
            "⚠️ <b>礼包发放失败</b>\n\n"
            f"<b>礼包：</b>{title} (ID: {pack_id})\n"
            f"<b>用户：</b>{user_name} ({tg_id})\n"
            f"<b>原因：</b>{reason}\n\n"
            "本次领取已整体回滚，未扣减余量、未记录领取。"
        )
        await notify_admins_by_url(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"发送礼包发放失败通知失败 (pack_id={pack_id}): {e}")


async def scan_expired_gift_packs() -> None:
    """周期扫描已过期且未通知的礼包，发送领取汇总后置 expiry_notified = 1

    用周期扫描而非创建时安排 date job：礼包的 end_at 是管理员可编辑的，
    date job 方案需要在每次编辑时重排，且漏排就永久丢失通知。
    """
    try:
        packs = db.get_expired_unnotified_gift_packs()
        if not packs:
            return
        logger.info(f"扫描到 {len(packs)} 个已过期待汇总的礼包")
        for pack in packs:
            try:
                stats = db.get_gift_pack_stats(pack["id"])
                if not stats:
                    continue
                quantity = (
                    f"{stats['claimed_users']} / {pack['total_quantity']} 份"
                    if pack.get("total_quantity")
                    else f"{stats['claimed_users']} 人（不限量）"
                )
                totals = (
                    "\n".join(
                        f"　• {item['label']}：{item['total']}"
                        + (
                            f"（{item['grants']} 次发放，{item['skipped']} 次{item['skipped_label']}）"
                            if item.get("skipped") and item.get("skipped_label")
                            else ""
                        )
                        for item in stats["reward_totals"]
                    )
                    or "　• 无发放记录"
                )
                text = (
                    "🎁 <b>礼包已结束 · 领取汇总</b>\n\n"
                    f"<b>标题：</b>{pack['title']}\n"
                    f"<b>结束时间：</b>{_format_time(pack['end_at'])}\n"
                    f"<b>领取情况：</b>{quantity}\n"
                    f"<b>被提醒人数：</b>{stats['prompted_users']}\n"
                    f"<b>奖励发放总量：</b>\n{totals}"
                )
                await notify_admins_by_url(text, parse_mode="HTML")
                db.mark_gift_pack_expiry_notified(pack["id"])
            except Exception as e:
                logger.error(f"发送礼包过期汇总失败 (pack_id={pack['id']}): {e}")
    except Exception as e:
        logger.error(f"扫描过期礼包任务失败: {e}")


async def scan_gift_pack_start_dms() -> None:
    """认领名单型礼包的开始私信，再逐条发送；失败不重新认领。"""
    try:
        # db 方法必须在同一事务内筛选并写入 start_dm_sent_at，提交后才返回。
        candidates = db.claim_gift_pack_start_dm_candidates(limit=200)
        if not candidates:
            return
        for index, candidate in enumerate(candidates):
            if index:
                await asyncio.sleep(0.5)
            try:
                text = (
                    "🎁 礼包已开始！\n\n"
                    f"礼包：{candidate['title']}\n"
                    f"奖励：{_format_rewards(candidate['rewards'])}\n"
                    f"领取条件：{candidate['requirements_summary'] or '无额外条件'}\n"
                    f"领取截止：{_format_time(candidate['end_at'])}（{settings.TZ}）\n\n"
                    "打开小程序的礼包中心领取。"
                )
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


async def notify_gift_pack_download_sync_failed(
    pack_id: int, tg_id: int, failures: list[dict]
) -> None:
    """下载权限已在数据库解锁、但同步到媒体服务器失败——需人工处理

    与「发放失败已回滚」是两回事：这里领取已经成功，不能混用文案。
    """
    try:
        user_name = get_user_name_from_tg_id(tg_id) or str(tg_id)
        pack = db.get_gift_pack_by_id(pack_id)
        title = pack["title"] if pack else f"#{pack_id}"
        details = "\n".join(
            f"　• {escape(str(f['service']).capitalize())}：{escape(str(f['error']))}"
            for f in failures
        )
        text = (
            "🔧 <b>礼包下载权限同步失败 · 需人工处理</b>\n\n"
            f"<b>礼包：</b>{escape(str(title))} (ID: {pack_id})\n"
            f"<b>用户：</b>{escape(str(user_name))} ({tg_id})\n"
            f"<b>失败服务：</b>\n{details}\n\n"
            "领取已成功，数据库中下载权限已记为解锁；"
            "请到对应媒体服务器为该用户手动开启下载权限。"
        )
        await notify_admins_by_url(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"发送礼包下载权限同步失败通知失败 (pack_id={pack_id}): {e}")


# ==================== 用户端 ====================


@router.post("/prompt-check", response_model=GiftPackPromptCheckResponse)
@require_telegram_auth
async def prompt_check(
    request: Request, telegram_user: TelegramUser = Depends(get_telegram_user)
):
    """开屏提醒判定：返回待提醒的礼包列表，并在返回的同时记账

    用 POST 而非 GET，因为它确实有副作用（prompt_count += 1）。
    返回空列表表示不弹窗。
    """
    try:
        result = db.prompt_check_gift_packs(telegram_user.id)
        return GiftPackPromptCheckResponse(
            packs=[GiftPackPromptItem(**pack) for pack in result["packs"]],
            task_packs=[
                GiftPackTaskPromptItem(**pack) for pack in result["task_packs"]
            ],
        )
    except Exception as e:
        logger.error(f"礼包提醒判定失败 (tg_id={telegram_user.id}): {e}")
        # 提醒是锦上添花，失败时静默返回空而不是打断用户的启动流程
        return GiftPackPromptCheckResponse(packs=[])


@router.get("", response_model=GiftPackListResponse)
@require_telegram_auth
async def list_gift_packs(
    request: Request, telegram_user: TelegramUser = Depends(get_telegram_user)
):
    """礼包中心列表：含每个礼包对当前用户的状态与余量"""
    try:
        packs = db.get_gift_packs_for_user(telegram_user.id)
        return GiftPackListResponse(
            packs=[GiftPackItem(**pack) for pack in packs], total=len(packs)
        )
    except Exception as e:
        logger.error(f"获取礼包列表失败 (tg_id={telegram_user.id}): {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取礼包列表失败"
        )


@router.post("/{pack_id}/claim", response_model=GiftPackClaimResponse)
@require_telegram_auth
async def claim_gift_pack(
    request: Request,
    pack_id: int,
    background_tasks: BackgroundTasks,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """领取礼包，返回逐项发放结果"""
    tg_id = telegram_user.id
    try:
        result = db.claim_gift_pack(pack_id, tg_id)
    except ValueError as e:
        # 领取条件变化时返回持锁事务内重新计算的结构化进度，供前端展示；
        # 其余业务拒绝沿用原有的中文 detail 文本。
        prefix = "不满足领取条件；当前进度："
        message = str(e)
        if message.startswith(prefix):
            try:
                progress = json.loads(message[len(prefix) :])
            except (TypeError, ValueError):
                pass
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"message": "不满足领取条件", "requirements": progress},
                ) from e
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=message
        ) from e
    except Exception as e:
        logger.error(f"领取礼包失败 (pack_id={pack_id}, tg_id={tg_id}): {e}")
        # 用 detached task 而非 BackgroundTasks：下面要抛 HTTPException，
        # BackgroundTasks 在异常路径上不会执行，通知会被静默吞掉
        _notify_detached(notify_gift_pack_claim_failed(pack_id, tg_id, str(e)))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="奖励发放失败，本次领取已回滚，请稍后重试或联系管理员",
        )

    # 下载权限同步失败：领取已成功，通知管理员人工补同步
    if result.get("download_sync_failed"):
        _notify_detached(
            notify_gift_pack_download_sync_failed(
                pack_id, tg_id, result["download_sync_failed"]
            )
        )

    # 限量领完：里程碑通知（并发下只有一个事务能把计数加到满，只会触发一次）
    if result["sold_out"]:
        background_tasks.add_task(
            notify_gift_pack_sold_out,
            pack_id,
            result["title"],
            result["total_quantity"],
        )

    results = [GiftPackClaimRewardResult(**item) for item in result["results"]]
    skipped = [r for r in results if r.skipped == "lifetime"]
    message = "领取成功"
    if skipped:
        services = "、".join((r.service or "").capitalize() for r in skipped)
        message = f"领取成功；{services} 为永久会员，Premium 天数部分未生效"

    return GiftPackClaimResponse(
        success=True,
        message=message,
        pack_id=pack_id,
        results=results,
        remaining=result["remaining"],
    )


# ==================== 管理端 ====================


@router.post("/admin/resolve-users")
@require_telegram_auth
async def admin_resolve_gift_pack_users(
    request: Request,
    text: Annotated[str, Body(embed=True, min_length=1)],
    telegram_user: Annotated[TelegramUser, Depends(get_telegram_user)],
) -> dict:
    """将混合粘贴的 Telegram ID / Plex / Emby 标识解析为 tg_id。"""
    check_admin_permission(telegram_user)
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="名单不能为空"
        )
    try:
        return db.resolve_gift_pack_users(text)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"解析礼包名单失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="解析名单失败"
        )


@router.get("/admin/list", response_model=GiftPackAdminListResponse)
@require_telegram_auth
async def admin_list_gift_packs(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """管理员：礼包列表"""
    check_admin_permission(telegram_user)
    try:
        packs, total = db.get_gift_packs_admin(page=page, page_size=page_size)
        return GiftPackAdminListResponse(
            packs=[GiftPackAdminItem(**pack) for pack in packs], total=total
        )
    except Exception as e:
        logger.error(f"获取礼包管理列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取礼包列表失败"
        )


@router.post("/admin", response_model=GiftPackAdminItem)
@require_telegram_auth
async def admin_create_gift_pack(
    request: Request,
    background_tasks: BackgroundTasks,
    data: GiftPackCreateRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """管理员：创建礼包"""
    check_admin_permission(telegram_user)
    try:
        pack_id = db.create_gift_pack(
            title=data.title,
            rewards=[r.model_dump() for r in data.rewards],
            start_at=data.start_at,
            end_at=data.end_at,
            description=data.description,
            audience=[c.model_dump() for c in data.audience] if data.audience else None,
            requirements=[c.model_dump() for c in data.requirements]
            if data.requirements
            else None,
            task_end_at=data.task_end_at,
            max_task_prompt_count=data.max_task_prompt_count,
            notify_audience_on_start=data.notify_audience_on_start,
            total_quantity=data.total_quantity,
            max_prompt_count=data.max_prompt_count,
            is_enabled=data.is_enabled,
            created_by=telegram_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"创建礼包失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="创建礼包失败"
        )

    pack = db.get_gift_pack_by_id(pack_id)
    if not pack:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="创建礼包失败"
        )
    # 礼包上线：里程碑通知
    background_tasks.add_task(notify_gift_pack_created, pack)
    return GiftPackAdminItem(**pack)


@router.put("/admin/{pack_id}", response_model=GiftPackAdminItem)
@require_telegram_auth
async def admin_update_gift_pack(
    request: Request,
    pack_id: int,
    data: GiftPackUpdateRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """管理员：编辑礼包"""
    check_admin_permission(telegram_user)
    try:
        fields = data.model_dump(exclude_unset=True)
        if "rewards" in fields and data.rewards is not None:
            fields["rewards"] = [r.model_dump() for r in data.rewards]
        for key in ("audience", "requirements"):
            if key in fields:
                values = getattr(data, key)
                fields[key] = [item.model_dump() for item in values] if values else None
        db.update_gift_pack(pack_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"编辑礼包失败 (pack_id={pack_id}): {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="编辑礼包失败"
        )

    pack = db.get_gift_pack_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="礼包不存在")
    return GiftPackAdminItem(**pack)


@router.post("/admin/{pack_id}/enabled", response_model=GiftPackAdminItem)
@require_telegram_auth
async def admin_set_gift_pack_enabled(
    request: Request,
    pack_id: int,
    data: GiftPackSetEnabledRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """管理员：启用 / 停用礼包"""
    check_admin_permission(telegram_user)
    if not db.set_gift_pack_enabled(pack_id, data.is_enabled):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="礼包不存在")
    pack = db.get_gift_pack_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="礼包不存在")
    return GiftPackAdminItem(**pack)


@router.delete("/admin/{pack_id}")
@require_telegram_auth
async def admin_delete_gift_pack(
    request: Request,
    pack_id: int,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """管理员：删除礼包（已有领取记录时拒绝，只能停用）"""
    check_admin_permission(telegram_user)
    try:
        db.delete_gift_pack(pack_id)
        return {"success": True, "message": "礼包已删除"}
    except ValueError as e:
        message = str(e)
        if "不存在" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    except Exception as e:
        logger.error(f"删除礼包失败 (pack_id={pack_id}): {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="删除礼包失败"
        )


@router.get("/admin/{pack_id}/stats", response_model=GiftPackStatsResponse)
@require_telegram_auth
async def admin_gift_pack_stats(
    request: Request,
    pack_id: int,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """管理员：礼包领取统计"""
    check_admin_permission(telegram_user)
    stats = db.get_gift_pack_stats(pack_id)
    if not stats:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="礼包不存在")
    return GiftPackStatsResponse(**stats)


@router.get("/admin/{pack_id}/records", response_model=GiftPackClaimRecordListResponse)
@require_telegram_auth
async def admin_gift_pack_records(
    request: Request,
    pack_id: int,
    page: int = 1,
    page_size: int = 20,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """管理员：礼包领取记录（分页）"""
    check_admin_permission(telegram_user)
    try:
        records, total = db.get_gift_pack_claim_records(
            pack_id, page=page, page_size=page_size
        )
        items: list[GiftPackClaimRecordItem] = []
        for record in records:
            username: str | None = None
            try:
                # 缓存未命中时该函数会退回返回 tg_id（int），统一转成字符串
                resolved = get_user_name_from_tg_id(record["tg_id"])
                username = str(resolved) if resolved is not None else None
            except Exception:
                username = None
            items.append(GiftPackClaimRecordItem(**record, tg_username=username))
        return GiftPackClaimRecordListResponse(records=items, total=total)
    except Exception as e:
        logger.error(f"获取礼包领取记录失败 (pack_id={pack_id}): {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取领取记录失败"
        )
