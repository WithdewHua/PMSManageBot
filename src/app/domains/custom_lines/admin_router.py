from fastapi import APIRouter, BackgroundTasks, Body, Depends, Request

from app.core.log import uvicorn_logger as logger
from app.domains.custom_lines import service
from app.domains.custom_lines.schemas import (
    AdminCustomLineUpdateRequest,
    CustomLineApproveRequest,
    CustomLineInfo,
    CustomLineListResponse,
)
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import BaseResponse, TelegramUser

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _info(line: dict) -> CustomLineInfo:
    return CustomLineInfo(**line)


@router.get("/custom-lines")
@require_telegram_auth
async def get_all_custom_lines(
    request: Request,
    status: str | None = None,
    user: TelegramUser = Depends(get_telegram_user),
):
    check_admin_permission(user)
    if status and status not in (
        "pending",
        "approved",
        "rejected",
        "expired",
        "offline",
    ):
        return CustomLineListResponse(
            success=False, message="无效的状态", lines=[], total=0
        )
    try:
        lines = service.repository.list_admin_lines(status)
        values = [_info(line) for line in lines]
        return CustomLineListResponse(
            success=True, message="获取成功", lines=values, total=len(values)
        )
    except Exception:
        logger.exception("获取自定义线路列表失败")
        return CustomLineListResponse(
            success=False, message="获取失败，请稍后再试", lines=[], total=0
        )


@router.post("/custom-lines/{line_id}/approve")
@require_telegram_auth
async def approve_custom_line(
    request: Request,
    line_id: int,
    background_tasks: BackgroundTasks,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    check_admin_permission(user)
    try:
        request_data = CustomLineApproveRequest(**data)
        if request_data.action not in ("approve", "reject"):
            return BaseResponse(success=False, message="无效的操作")
        result = await service.approve_custom_line(
            request_data, line_id, user.id, user.username
        )
        return BaseResponse(success=result["ok"], message=result["message"])
    except Exception:
        logger.exception("审批自定义线路失败")
        return BaseResponse(success=False, message="审批失败，请稍后再试")


@router.put("/custom-lines/{line_id}")
@require_telegram_auth
async def admin_update_custom_line(
    request: Request,
    line_id: int,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    check_admin_permission(user)
    try:
        result = await service.admin_update_custom_line(
            AdminCustomLineUpdateRequest(**data), line_id
        )
        return BaseResponse(success=result["ok"], message=result["message"])
    except Exception:
        logger.exception("管理员更新自定义线路失败")
        return BaseResponse(success=False, message="更新失败，请稍后再试")


@router.post("/custom-lines/{line_id}/offline")
@require_telegram_auth
async def admin_offline_custom_line(
    request: Request,
    line_id: int,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    check_admin_permission(user)
    result = await service.offline_custom_line(
        line_id, owner_tg_id=None, reason="已被管理员下线"
    )
    return BaseResponse(
        success=result["ok"],
        message=(
            f"已下线线路: {result['line']['domain']}"
            if result["ok"]
            else result["message"]
        ),
    )


@router.delete("/custom-lines/{line_id}")
@require_telegram_auth
async def admin_delete_custom_line(
    request: Request,
    line_id: int,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    check_admin_permission(user)
    result = await service.delete_custom_line(line_id, owner_tg_id=None, is_admin=True)
    return BaseResponse(success=result["ok"], message=result["message"])


@router.post("/custom-lines/{line_id}/tags")
@require_telegram_auth
async def admin_set_custom_line_tags(
    request: Request,
    line_id: int,
    tags: list[str],
    user: TelegramUser = Depends(get_telegram_user),
):
    check_admin_permission(user)
    result = await service.set_custom_line_tags(line_id, tags)
    return BaseResponse(
        success=result["ok"], message=result["message"], data=result.get("data")
    )
