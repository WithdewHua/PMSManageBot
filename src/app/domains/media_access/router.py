from time import time

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request

from app.core.auth import get_telegram_user, require_telegram_auth
from app.core.formatting import get_service_label
from app.core.log import uvicorn_logger as logger
from app.core.schemas import BaseResponse, TelegramUser
from app.core.telegram import get_user_name_from_tg_id, notify_admins_by_url
from app.databases import db
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.media_access import service as media_access_service
from app.domains.media_access.rules import caculate_credits_fund
from app.integrations.emby import Emby
from app.integrations.plex import Plex

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/nsfw-info")
@require_telegram_auth
async def get_nsfw_info(
    request: Request,
    service: str,
    operation: str,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取NSFW操作所需积分或可退回积分"""
    tg_id = user.id

    if service not in ["plex", "emby"]:
        raise HTTPException(status_code=400, detail="不支持的服务类型")

    if operation not in ["unlock", "lock"]:
        raise HTTPException(status_code=400, detail="不支持的操作类型")

    try:
        if operation == "unlock":
            # 解锁操作返回所需积分
            return {"cost": media_access_service.get_unlock_credits()}
        else:
            # 锁定操作计算可返还积分
            if service == "plex":
                info = db.get_plex_info_by_tg_id(tg_id)
                if not info or info[5] != 1:
                    raise HTTPException(status_code=400, detail="您尚未解锁 NSFW 内容")
                unlock_time = info[6]
            else:
                info = db.get_emby_info_by_tg_id(tg_id)
                if not info or info[3] != 1:
                    raise HTTPException(status_code=400, detail="您尚未解锁 NSFW 内容")
                unlock_time = info[4]

            # 计算可返还积分
            credits_fund = caculate_credits_fund(
                unlock_time, media_access_service.get_unlock_credits()
            )
            return {"refund": credits_fund}
    except Exception as e:
        logger.error(f"获取 NSFW 信息时发生错误: {e!s}")
        raise HTTPException(status_code=500, detail="获取NSFW信息失败")


@router.post("/nsfw/{operation}")
@require_telegram_auth
async def nsfw_operation(
    request: Request,
    background_tasks: BackgroundTasks,
    operation: str,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """执行NSFW权限操作"""
    if operation not in ["unlock", "lock"]:
        raise HTTPException(status_code=400, detail="不支持的操作类型")

    service = data.get("service")
    if service not in ["plex", "emby"]:
        raise HTTPException(status_code=400, detail="不支持的服务类型")

    tg_id = user.id

    try:
        # 获取用户统计信息
        stats_info = db.get_stats_by_tg_id(tg_id)
        if not stats_info:
            raise HTTPException(status_code=404, detail="用户不存在")

        credits = stats_info[2]

        if operation == "unlock":
            # 解锁操作
            if service == "plex":
                # 获取Plex信息
                plex_info = db.get_plex_info_by_tg_id(tg_id)
                if not plex_info:
                    raise HTTPException(status_code=404, detail="Plex账户未绑定")

                plex_id = plex_info[0]
                all_lib = plex_info[5]

                if all_lib == 1:
                    raise HTTPException(status_code=400, detail="您已拥有全部库权限")

                if credits < media_access_service.get_unlock_credits():
                    raise HTTPException(status_code=400, detail="积分不足")

                # 更新权限
                _plex = Plex()
                try:
                    _plex.update_user_shared_libs(plex_id, _plex.get_libraries())
                except Exception as e:
                    logger.error(f"更新权限失败: {e!s}")
                    raise HTTPException(status_code=500, detail="更新权限失败")

                # 解锁时间
                unlock_time = time()

                # 更新数据库
                try:
                    credits = credits_service.deduct(
                        CreditAccount.tg(int(tg_id)),
                        media_access_service.get_unlock_credits(),
                    ).after
                except Exception as error:
                    raise HTTPException(
                        status_code=500, detail="更新积分失败"
                    ) from error

                if not db.update_all_lib_flag(
                    all_lib=1, unlock_time=unlock_time, plex_id=plex_id
                ):
                    raise HTTPException(status_code=500, detail="更新权限状态失败")

            else:
                # 获取Emby信息
                emby_info = db.get_emby_info_by_tg_id(tg_id)
                if not emby_info:
                    raise HTTPException(status_code=404, detail="Emby账户未绑定")

                emby_id = emby_info[1]
                all_lib = emby_info[3]

                if all_lib == 1:
                    raise HTTPException(status_code=400, detail="您已拥有全部库权限")

                if credits < media_access_service.get_unlock_credits():
                    raise HTTPException(status_code=400, detail="积分不足")

                # 更新权限
                _emby = Emby()
                flag, msg = _emby.add_user_library(
                    user_id=emby_id, library=media_access_service.get_nsfw_libs()
                )
                if not flag:
                    raise HTTPException(status_code=500, detail=f"更新权限失败: {msg}")

                # 解锁时间
                unlock_time = time()

                # 更新数据库
                try:
                    credits = credits_service.deduct(
                        CreditAccount.tg(int(tg_id)),
                        media_access_service.get_unlock_credits(),
                    ).after
                except Exception as error:
                    raise HTTPException(
                        status_code=500, detail="更新积分失败"
                    ) from error

                if not db.update_all_lib_flag(
                    all_lib=1, unlock_time=unlock_time, tg_id=tg_id, media_server="emby"
                ):
                    raise HTTPException(status_code=500, detail="更新权限状态失败")

        else:
            # 锁定操作
            if service == "plex":
                # 获取Plex信息
                plex_info = db.get_plex_info_by_tg_id(tg_id)
                if not plex_info:
                    raise HTTPException(status_code=404, detail="Plex账户未绑定")

                plex_id = plex_info[0]
                all_lib = plex_info[5]
                unlock_time = plex_info[6]

                if all_lib == 0:
                    raise HTTPException(status_code=400, detail="您未解锁NSFW内容")

                # 计算返还积分
                credits_fund = caculate_credits_fund(
                    unlock_time, media_access_service.get_unlock_credits()
                )
                credits += credits_fund

                # 更新权限
                _plex = Plex()
                sections = _plex.get_libraries()
                for section in media_access_service.get_nsfw_libs():
                    if section in sections:
                        sections.remove(section)

                try:
                    _plex.update_user_shared_libs(plex_id, sections)
                except Exception as e:
                    logger.error(f"更新权限失败: {e!s}")
                    raise HTTPException(status_code=500, detail="更新权限失败")

                # 更新数据库
                try:
                    credits = credits_service.add(
                        CreditAccount.tg(int(tg_id)), credits_fund
                    ).after
                except Exception as error:
                    raise HTTPException(
                        status_code=500, detail="更新积分失败"
                    ) from error

                if not db.update_all_lib_flag(
                    all_lib=0, unlock_time=None, plex_id=plex_id
                ):
                    raise HTTPException(status_code=500, detail="更新权限状态失败")

            else:
                # 获取Emby信息
                emby_info = db.get_emby_info_by_tg_id(tg_id)
                if not emby_info:
                    raise HTTPException(status_code=404, detail="Emby账户未绑定")

                emby_id = emby_info[1]
                all_lib = emby_info[3]
                unlock_time = emby_info[4]

                if all_lib == 0:
                    raise HTTPException(status_code=400, detail="您未解锁NSFW内容")

                # 计算返还积分
                credits_fund = caculate_credits_fund(
                    unlock_time, media_access_service.get_unlock_credits()
                )
                credits += credits_fund

                # 更新权限
                _emby = Emby()
                flag, msg = _emby.remove_user_library(
                    user_id=emby_id, library=media_access_service.get_nsfw_libs()
                )
                if not flag:
                    raise HTTPException(status_code=500, detail=f"更新权限失败: {msg}")

                # 更新数据库
                try:
                    credits = credits_service.add(
                        CreditAccount.tg(int(tg_id)), credits_fund
                    ).after
                except Exception as error:
                    raise HTTPException(
                        status_code=500, detail="更新积分失败"
                    ) from error

                if not db.update_all_lib_flag(
                    all_lib=0, unlock_time=None, tg_id=tg_id, media_server="emby"
                ):
                    raise HTTPException(status_code=500, detail="更新权限状态失败")

        if operation == "unlock":
            service_name, service_emoji = get_service_label(service)
            user_name = get_user_name_from_tg_id(tg_id)
            background_tasks.add_task(
                notify_admins_by_url,
                f"""🔞 NSFW 权限解锁通知

👤 用户: {user_name}（TG ID: {tg_id}）
{service_emoji} 服务: {service_name}
💎 花费: {media_access_service.get_unlock_credits()} 积分
💰 剩余: {credits:.2f} 积分""",
            )

        return {
            "success": True,
            "message": f"NSFW 内容已{'解锁' if operation == 'unlock' else '锁定'}",
            "credits": credits,
        }

    except HTTPException:
        # 向上传递HTTP异常
        raise
    except Exception as e:
        logger.error(f"执行 NSFW 操作时发生错误: {e!s}")
        raise HTTPException(status_code=500, detail="操作失败，请稍后再试")


@router.get("/download-permission/status/{service}")
@require_telegram_auth
async def get_download_permission_status(
    service: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取下载权限状态"""
    if service not in ["plex", "emby"]:
        raise HTTPException(status_code=400, detail="服务类型必须是 'plex' 或 'emby'")

    try:
        unlock_status = db.check_download_unlock(user.id, service)
        return {
            "success": True,
            "is_unlocked": unlock_status["is_unlocked"],
            "is_premium": unlock_status["is_premium"],
            "unlock_time": unlock_status["unlock_time"],
            "unlock_cost": media_access_service.get_download_unlock_credits(),
        }
    except Exception as e:
        logger.error(f"获取下载权限状态失败: {e}")
        raise HTTPException(status_code=500, detail="获取下载权限状态失败")


@router.post("/download-permission/unlock/{service}")
@require_telegram_auth
async def unlock_download_permission(
    service: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    """解锁下载权限"""
    if service not in ["plex", "emby"]:
        raise HTTPException(status_code=400, detail="服务类型必须是 'plex' 或 'emby'")

    tg_id = user.id

    try:
        # 检查是否已解锁
        unlock_status = db.check_download_unlock(tg_id, service)
        if unlock_status["is_unlocked"]:
            if unlock_status["is_premium"]:
                return BaseResponse(
                    success=False, message="Premium 用户已自动拥有下载权限，无需解锁"
                )
            else:
                return BaseResponse(
                    success=False, message="下载权限已解锁，无需重复解锁"
                )

        # 扣除积分
        success, msg, remaining_credits = db.deduct_credits_for_download_unlock(tg_id)
        if not success:
            return BaseResponse(success=False, message=msg)

        # 更新数据库解锁状态
        if not db.set_download_unlocked(tg_id, service):
            logger.error(f"用户 {tg_id} 下载权限数据库更新失败")
            return BaseResponse(success=False, message="解锁失败，请联系管理员")

        # 应用到媒体服务器
        try:
            if service == "plex":
                plex_info = db.get_plex_info_by_tg_id(tg_id)
                if plex_info and plex_info[3]:  # plex_email
                    plex = Plex()
                    plex.update_sync_for_user(plex_info[3], allow_sync=True)
            elif service == "emby":
                emby_info = db.get_emby_info_by_tg_id(tg_id)
                if emby_info and emby_info[1]:  # emby_id
                    emby = Emby()
                    emby.update_download_permission_for_user(
                        emby_info[1], allow_download=True
                    )
        except Exception as e:
            logger.warning(f"应用下载权限到媒体服务器失败: {e}，但数据库已更新")

        logger.info(
            f"用户 {get_user_name_from_tg_id(tg_id)} 解锁 {service} 下载权限，"
            f"消耗 {media_access_service.get_download_unlock_credits()} 积分"
        )

        # 发送管理员通知
        service_name, service_emoji = get_service_label(service)
        user_name = get_user_name_from_tg_id(tg_id)

        admin_notification = f"""📥 下载权限解锁通知

👤 用户: {user_name}（TG ID: {tg_id}）
{service_emoji} 服务: {service_name}
💎 花费: {media_access_service.get_download_unlock_credits()} 积分
💰 剩余: {remaining_credits:.2f} 积分"""

        background_tasks.add_task(
            notify_admins_by_url,
            admin_notification,
        )

        return BaseResponse(
            success=True,
            message=f"解锁成功！消耗 {media_access_service.get_download_unlock_credits()} 积分，剩余 {remaining_credits:.2f} 积分",
        )

    except Exception as e:
        logger.error(f"解锁下载权限失败: {e}")
        return BaseResponse(success=False, message=f"解锁失败: {e!s}，请联系管理员")
