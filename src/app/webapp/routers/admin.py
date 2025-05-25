from app.cache import emby_last_user_defined_line_cache, emby_user_defined_line_cache
from app.config import settings
from app.db import DB
from app.log import uvicorn_logger as logger
from app.utils import (
    get_user_info_from_tg_id,
    get_user_name_from_tg_id,
    send_message_by_url,
)
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.schemas import BaseResponse, TelegramUser
from fastapi import APIRouter, Body, Depends, HTTPException, Request

router = APIRouter(prefix="/api/admin", tags=["admin"])


def check_admin_permission(user: TelegramUser):
    """检查用户是否为管理员"""
    if user.id not in settings.ADMIN_CHAT_ID:
        raise HTTPException(status_code=403, detail="权限不足，需要管理员权限")
    return True


@router.get("/settings")
@require_telegram_auth
async def get_admin_settings(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取管理员设置"""
    check_admin_permission(user)

    try:
        settings_data = {
            "plex_register": settings.PLEX_REGISTER,
            "emby_register": settings.EMBY_REGISTER,
            "emby_premium_free": settings.EMBY_PREMIUM_FREE,
        }

        logger.info(f"管理员 {user.username or user.id} 获取系统设置")
        return settings_data
    except Exception as e:
        logger.error(f"获取管理员设置失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取设置失败")


@router.post("/settings/plex-register")
@require_telegram_auth
async def set_plex_register(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置Plex注册开关"""
    check_admin_permission(user)

    try:
        enabled = data.get("enabled", False)
        settings.PLEX_REGISTER = bool(enabled)

        logger.info(
            f"管理员 {user.username or user.id} 设置 Plex 注册状态为: {enabled}"
        )
        return BaseResponse(
            success=True, message=f"Plex 注册已{'开启' if enabled else '关闭'}"
        )
    except Exception as e:
        logger.error(f"设置 Plex 注册状态失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/emby-register")
@require_telegram_auth
async def set_emby_register(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置Emby注册开关"""
    check_admin_permission(user)

    try:
        enabled = data.get("enabled", False)
        settings.EMBY_REGISTER = bool(enabled)

        logger.info(
            f"管理员 {user.username or user.id} 设置 Emby 注册状态为: {enabled}"
        )
        return BaseResponse(
            success=True, message=f"Emby 注册已{'开启' if enabled else '关闭'}"
        )
    except Exception as e:
        logger.error(f"设置 Emby 注册状态失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


@router.post("/settings/emby-premium-free")
@require_telegram_auth
async def set_emby_premium_free(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """设置Emby高级线路免费使用开关"""
    check_admin_permission(user)

    try:
        enabled = data.get("enabled", False)
        old_status = settings.EMBY_PREMIUM_FREE
        settings.EMBY_PREMIUM_FREE = bool(enabled)

        # 如果从开启变为关闭，需要处理现有用户的高级线路绑定
        if old_status and not enabled:
            # 调用解绑所有普通用户的premium线路的函数
            flag, msg = await unbind_emby_premium_free()
            if not flag:
                return BaseResponse(success=False, message=msg)

        logger.info(
            f"管理员 {user.username or user.id} 设置 Emby 高级线路免费使用状态为: {enabled}"
        )
        return BaseResponse(
            success=True,
            message=f"Emby 高级线路免费使用已{'开启' if enabled else '关闭'}",
        )
    except Exception as e:
        logger.error(f"设置 Emby 高级线路免费使用状态失败: {str(e)}")
        return BaseResponse(success=False, message="设置失败")


async def unbind_emby_premium_free():
    """解绑所有 Emby Premium Free（恢复普通用户）"""

    if settings.EMBY_PREMIUM_FREE:
        logger.info("Emby Premium Free 功能未启用，跳过解绑操作")
        return True, None
    db = DB()
    try:
        # 获取所有绑定了 Emby 线路的用户
        users = db.get_emby_user_with_binded_line()
        for user in users:
            emby_username, tg_id, emby_line, is_premium = user
            if is_premium:
                continue
            # 如果是普通用户，检查是否是高级线路
            is_premium_line = False
            for _line in settings.EMBY_PREMIUM_STREAM_BACKEND:
                if _line in emby_line:
                    is_premium_line = True
                    break
            if not is_premium_line:
                # 如果不是高级线路，跳过
                continue
            # 获取上一次绑定的非 premium 线路
            last_line = emby_last_user_defined_line_cache.get(
                str(emby_username).lower()
            )
            # 更新用户的 Emby 线路，last_line 为空则自动选择
            db.set_emby_line(last_line, tg_id=tg_id)
            # 更新缓存
            if last_line:
                emby_user_defined_line_cache.put(str(emby_username).lower(), last_line)
                emby_last_user_defined_line_cache.delete(str(emby_username).lower())
                await send_message_by_url(
                    chat_id=tg_id,
                    text=f"通知：高级线路开放通道关闭，您绑定的线路已切换为 `{last_line}`",
                )
            else:
                emby_user_defined_line_cache.delete(str(emby_username).lower())
                await send_message_by_url(
                    chat_id=tg_id,
                    text="通知：高级线路开放通道已关闭，您绑定的线路已切换为 `AUTO`",
                )

        return True, None
    except Exception as e:
        logger.error(f"解绑所有普通用户的 premium 线路时发生错误: {str(e)}")
        return False, f"解绑所有普通用户的 premium 线路时发生错误: {str(e)}"
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


@router.get("/users")
@require_telegram_auth
async def get_all_users(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取所有用户信息（用于捐赠管理）"""
    check_admin_permission(user)

    try:
        db = DB()

        # 从 statistics 表获取所有用户
        stats_users = db.cur.execute(
            "SELECT tg_id, donation, credits FROM statistics"
        ).fetchall()

        user_list = []
        for tg_id, donation, credits in stats_users:
            if tg_id:  # 确保tg_id不为空
                # 获取用户的Telegram信息
                tg_info = get_user_info_from_tg_id(tg_id)

                user_list.append(
                    {
                        "tg_id": tg_id,
                        "display_name": tg_info.get("first_name")
                        or tg_info.get("username")
                        or str(tg_id),
                        "photo_url": tg_info.get("photo_url"),
                        "current_donation": float(donation) if donation else 0.0,
                        "current_credits": float(credits) if credits else 0.0,
                    }
                )

        logger.info(
            f"管理员 {user.username or user.id} 获取了 {len(user_list)} 个用户信息"
        )
        return user_list

    except Exception as e:
        logger.error(f"获取用户列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取用户列表失败")
    finally:
        db.close()


@router.post("/donation")
@require_telegram_auth
async def submit_donation_record(
    request: Request,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """提交捐赠记录"""
    check_admin_permission(user)

    try:
        tg_id = data.get("tg_id")
        amount = data.get("amount", 0)
        note = data.get("note", "")

        if not tg_id or amount <= 0:
            return BaseResponse(success=False, message="参数错误")

        db = DB()

        # 获取当前捐赠金额
        stats_info = db.get_stats_by_tg_id(tg_id)
        if not stats_info:
            return BaseResponse(success=False, message="用户不存在")

        current_donation = stats_info[1] if stats_info[1] else 0
        new_donation = current_donation + float(amount)
        current_credits = stats_info[2] if stats_info[2] else 0
        new_credits = current_credits + float(amount) * 2  # 捐赠金额的两倍作为积分

        # 更新捐赠金额
        success = db.update_user_donation(new_donation, tg_id)

        if success:
            # 更新积分
            db.update_user_credits(new_credits, tg_id=tg_id)

            # 获取用户显示名称
            user_name = get_user_name_from_tg_id(tg_id)

            logger.info(
                f"管理员 {user.username or user.id} 为用户 {user_name}({tg_id}) 添加捐赠记录: {amount}元"
                + (f", 备注: {note}" if note else "")
            )

            # 发送通知给用户
            try:
                await send_message_by_url(
                    chat_id=tg_id,
                    text=f"""
感谢您的捐赠！

💰 本次捐赠: {amount}元
💳 累计捐赠: {new_donation}元
"""
                    + (f"""📝 备注: {note}""" if note else ""),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning(f"发送捐赠通知失败: {str(e)}")

            return BaseResponse(
                success=True, message=f"成功为 {user_name} 添加 {amount}元 捐赠记录"
            )
        else:
            return BaseResponse(success=False, message="更新捐赠记录失败")

    except Exception as e:
        logger.error(f"提交捐赠记录失败: {str(e)}")
        return BaseResponse(success=False, message="提交失败")
    finally:
        db.close()
