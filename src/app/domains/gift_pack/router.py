"""
礼包（Gift Pack）路由 —— 用户端与管理端

通知策略：只在里程碑与异常节点通知管理员（上线 / 限量领完 / 过期汇总 / 发放失败），
日常逐笔领取一律不通知——`notify_admins_by_url()` 是逐管理员逐条发 TG 消息，
按笔通知在运营活动的量级下会刷屏并触发 Telegram 限流。
"""

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

from app.core.log import uvicorn_logger as logger
from app.domains.gift_pack import service as gift_pack_service
from app.domains.gift_pack.exceptions import GiftPackError
from app.domains.gift_pack.schemas import (
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
from app.integrations.telegram.profiles import get_user_name_from_tg_id
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import TelegramUser

router = APIRouter(
    prefix="/api/gift-packs",
    tags=["gift-packs"],
    responses={404: {"description": "Not found"}},
)


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
        result = gift_pack_service.prompt_check(telegram_user.id)
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
        packs = gift_pack_service.list_gift_packs_for_user(telegram_user.id)
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
        result = gift_pack_service.claim_gift_pack(pack_id, tg_id)
    except GiftPackError as e:
        # 类型化拒绝自带状态码与 detail：条件不满足时 detail 是逐项进度对象
        raise HTTPException(
            status_code=e.status_code, detail=e.payload["detail"]
        ) from e
    except ValueError as e:
        # 过渡期：外域仍抛裸 ValueError，按业务拒绝处理
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except Exception as e:
        logger.error(f"领取礼包失败 (pack_id={pack_id}, tg_id={tg_id}): {e}")
        # 用 detached task 而非 BackgroundTasks：下面要抛 HTTPException，
        # BackgroundTasks 在异常路径上不会执行，通知会被静默吞掉
        gift_pack_service.notify_claim_failed(pack_id, tg_id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="奖励发放失败，本次领取已回滚，请稍后重试或联系管理员",
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
        return gift_pack_service.admin_resolve_users(text)
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
        packs, total = gift_pack_service.admin_list(page=page, page_size=page_size)
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
        pack_id = gift_pack_service.admin_create(
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

    pack = gift_pack_service.admin_get(pack_id)
    if not pack:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="创建礼包失败"
        )
    # 礼包上线：里程碑通知
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
        gift_pack_service.admin_update(pack_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"编辑礼包失败 (pack_id={pack_id}): {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="编辑礼包失败"
        )

    pack = gift_pack_service.admin_get(pack_id)
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
    if not gift_pack_service.admin_set_enabled(pack_id, data.is_enabled):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="礼包不存在")
    pack = gift_pack_service.admin_get(pack_id)
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
        gift_pack_service.admin_delete(pack_id)
        return {"success": True, "message": "礼包已删除"}
    except GiftPackError as e:
        raise HTTPException(
            status_code=e.status_code, detail=e.payload["detail"]
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
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
    stats = gift_pack_service.admin_stats(pack_id)
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
        records, total = gift_pack_service.admin_claim_records(
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
