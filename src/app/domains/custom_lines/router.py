from time import time

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.core.log import uvicorn_logger as logger
from app.domains.custom_lines import service
from app.domains.custom_lines.schemas import (
    CustomLineDetailResponse,
    CustomLineInfo,
    CustomLineListResponse,
    CustomLineOnlineRequest,
    CustomLineRenewRequest,
    CustomLineSubmitRequest,
    CustomLineUpdateRequest,
)
from app.integrations.telegram.messaging import send_message_by_url  # noqa: F401
from app.transport.http.auth import get_telegram_user, require_telegram_auth
from app.transport.http.schemas import BaseResponse, TelegramUser

router = APIRouter(prefix="/api/user", tags=["user"])


def _info(line: dict) -> CustomLineInfo:
    return CustomLineInfo(**line)


def _list_response(
    lines: list[dict], message: str = "获取成功"
) -> CustomLineListResponse:
    values = [_info(line) for line in lines]
    return CustomLineListResponse(
        success=True, message=message, lines=values, total=len(values)
    )


@router.post("/custom-lines/submit")
@require_telegram_auth
async def submit_custom_line(
    request: Request,
    background_tasks: BackgroundTasks,
    data: CustomLineSubmitRequest,
    user: TelegramUser = Depends(get_telegram_user),
):
    result = await service.submit_custom_line(data, user.id, now=int(time()))
    if not result["ok"]:
        return BaseResponse(success=False, message=result["message"])
    return BaseResponse(success=True, message=result["message"])


@router.get("/custom-lines/my-lines")
@require_telegram_auth
async def get_my_custom_lines(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    try:
        return _list_response(service.get_my_custom_lines(user.id))
    except Exception:
        logger.exception("获取用户自定义线路失败")
        return CustomLineListResponse(
            success=False, message="获取失败，请稍后再试", lines=[], total=0
        )


@router.get("/custom-lines/approved")
@require_telegram_auth
async def get_approved_custom_lines(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    try:
        lines = service.get_approved_custom_lines()
        values = []
        for line in lines:
            tags = ["用户分享", *(line.get("tags") or [])]
            values.append({"name": line["domain"], "tags": tags})
        return {
            "success": True,
            "message": "获取成功",
            "lines": values,
            "total": len(values),
        }
    except Exception:
        logger.exception("获取已批准自定义线路失败")
        return {
            "success": False,
            "message": "获取失败，请稍后再试",
            "lines": [],
            "total": 0,
        }


@router.get("/custom-lines/{line_id}")
@require_telegram_auth
async def get_custom_line_detail(
    request: Request, line_id: int, user: TelegramUser = Depends(get_telegram_user)
):
    try:
        line = service.get_custom_line_detail(line_id)
        if line is None:
            return CustomLineDetailResponse(
                success=False, message="线路不存在", line=None
            )
        if line["tg_id"] != user.id:
            return CustomLineDetailResponse(
                success=False, message="无权查看此线路", line=None
            )
        return CustomLineDetailResponse(
            success=True, message="获取成功", line=_info(line)
        )
    except Exception:
        logger.exception("获取自定义线路详情失败")
        return CustomLineDetailResponse(
            success=False, message="获取失败，请稍后再试", line=None
        )


@router.put("/custom-lines/{line_id}")
@require_telegram_auth
async def update_custom_line(
    request: Request,
    line_id: int,
    data: CustomLineUpdateRequest,
    user: TelegramUser = Depends(get_telegram_user),
):
    result = service.update_custom_line(data, line_id, user.id, now=int(time()))
    return BaseResponse(success=result["ok"], message=result["message"])


@router.delete("/custom-lines/{line_id}")
@require_telegram_auth
async def delete_custom_line(
    request: Request,
    line_id: int,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    result = await service.delete_custom_line(line_id, owner_tg_id=user.id)
    return BaseResponse(success=result["ok"], message=result["message"])


@router.post("/custom-lines/{line_id}/offline")
@require_telegram_auth
async def offline_custom_line(
    request: Request,
    line_id: int,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    result = await service.offline_custom_line(
        line_id, owner_tg_id=user.id, reason="已被所有者下线"
    )
    return BaseResponse(success=result["ok"], message=result["message"])


@router.post("/custom-lines/{line_id}/online")
@require_telegram_auth
async def online_custom_line(
    request: Request,
    line_id: int,
    data: CustomLineOnlineRequest,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    result = await service.online_custom_line(data, line_id, user.id)
    return BaseResponse(success=result["ok"], message=result["message"])


@router.post("/custom-lines/{line_id}/renew")
@require_telegram_auth
async def renew_custom_line(
    request: Request,
    line_id: int,
    data: CustomLineRenewRequest,
    user: TelegramUser = Depends(get_telegram_user),
):
    result = await service.renew_custom_line(line_id, data.valid_days, user.id)
    return BaseResponse(success=result["ok"], message=result["message"])
