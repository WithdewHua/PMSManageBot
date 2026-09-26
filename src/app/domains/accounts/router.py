from fastapi import APIRouter, Body, Depends, Request

from app.core.auth import get_telegram_user, require_telegram_auth
from app.core.log import uvicorn_logger as logger
from app.core.schemas import BaseResponse, TelegramUser
from app.databases import db
from app.domains.profile.schemas import BindEmbyRequest, BindPlexRequest
from app.integrations.emby import Emby
from app.integrations.plex import Plex
from app.integrations.tautulli import Tautulli
from app.utils.utils import (
    get_user_name_from_tg_id,
    get_user_total_duration,
)

router = APIRouter(prefix="/api/user", tags=["user"])


@router.post("/bind/plex", response_model=BaseResponse)
@require_telegram_auth
async def bind_plex_account(
    request: Request,
    data: BindPlexRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """绑定Plex账户"""
    tg_id = telegram_user.id
    email = data.email

    logger.info(f"用户 {get_user_name_from_tg_id(tg_id)} 尝试绑定 Plex 账户 {email}")

    try:
        # 检查用户是否已绑定Plex
        _info = db.get_plex_info_by_tg_id(tg_id)
        if _info:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 已绑定 Plex 账户")
            return BaseResponse(
                success=False, message="您已绑定 Plex 账户，请勿重复操作"
            )

        _plex = Plex()
        plex_id = _plex.get_user_id_by_email(email)

        # 用户不存在
        if plex_id == 0:
            logger.warning(f"无法找到 Plex 用户 {email}")
            return BaseResponse(
                success=False, message="该邮箱无 Plex 权限，请检查输入的邮箱"
            )

        # 检查该用户是否已绑定其他TG账户
        # 邮箱可能修改，所以用 plex_id 来判断
        # 但如果是刚接受邀请且兑换邀请码选择了绑定，则可能数据库中没有该 plex_id 的记录
        # 所以使用 email 再检查一次
        plex_info = db.get_plex_info_by_plex_id(
            plex_id
        ) or db.get_plex_info_by_plex_email(email)
        if plex_info:
            tg_id_bound = plex_info[1]
            if tg_id_bound:
                logger.warning(
                    f"Plex 账户 {email} 已被其他 Telegram 账户 {tg_id_bound} 绑定"
                )
                return BaseResponse(
                    success=False,
                    message=f"该 Plex 账户已经绑定 Telegram 账户 {tg_id_bound}",
                )
            # 更新已存在用户的tg_id
            rslt = db.update_user_tg_id(tg_id, plex_id=plex_id)
            if not rslt:
                logger.error(
                    f"更新用户 {get_user_name_from_tg_id(tg_id)} 的 Plex 绑定失败"
                )
                return BaseResponse(success=False, message="数据库更新失败，请稍后再试")

            # 清空 plex 用户表中积分信息
            db.update_user_credits(0, plex_id=plex_info[0])
            plex_credits = plex_info[2]
        else:
            # 添加新用户
            plex_username = _plex.get_username_by_user_id(plex_id)
            plex_cur_libs = _plex.get_user_shared_libs_by_id(plex_id)
            plex_all_lib = (
                1
                if not set(_plex.get_libraries()).difference(set(plex_cur_libs))
                else 0
            )

            # 初始化积分
            try:
                user_total_duration = get_user_total_duration(
                    Tautulli().get_home_stats(
                        1365, "duration", len(_plex.users_by_id), stat_id="top_users"
                    )
                )
                plex_credits = user_total_duration.get(plex_id, 0)
            except Exception as e:
                logger.error(f"获取用户观看时长失败: {e!s}")
                return BaseResponse(
                    success=False, message="获取用户观看时长失败，请稍后再试"
                )

            # 写入数据库
            rslt = db.add_plex_user(
                plex_id=plex_id,
                tg_id=tg_id,
                plex_email=email,
                plex_username=plex_username,
                credits=0,
                all_lib=plex_all_lib,
                watched_time=plex_credits,
            )

            if not rslt:
                logger.error(
                    f"添加用户 {get_user_name_from_tg_id(tg_id)} 的 Plex 信息失败"
                )
                return BaseResponse(success=False, message="数据库更新失败，请稍后再试")

        # 获取用户数据表信息并更新积分
        stats_info = db.get_stats_by_tg_id(tg_id)
        if stats_info:
            tg_user_credits = stats_info[2] + plex_credits
            db.update_user_credits(tg_user_credits, tg_id=tg_id)
        else:
            db.add_user_data(tg_id, credits=plex_credits)

        logger.info(
            f"用户 {get_user_name_from_tg_id(tg_id)} 成功绑定 Plex 账户 {email}"
        )
        return BaseResponse(success=True, message=f"绑定 Plex 账户 {email} 成功！")

    except Exception as e:
        logger.error(f"绑定Plex账户时发生错误: {e!s}")
        return BaseResponse(success=False, message="绑定失败，发生未知错误")


@router.post("/bind/emby", response_model=BaseResponse)
@require_telegram_auth
async def bind_emby_account(
    request: Request,
    data: BindEmbyRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """绑定Emby账户"""
    tg_id = telegram_user.id
    emby_username = data.username

    logger.info(
        f"用户 {get_user_name_from_tg_id(tg_id)} 尝试绑定 Emby 账户 {emby_username}"
    )

    try:
        # 检查用户是否已绑定Emby
        info = db.get_emby_info_by_tg_id(tg_id)
        if info:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 已绑定Emby账户")
            return BaseResponse(
                success=False, message="您已绑定 Emby 账户，请勿重复操作"
            )

        emby = Emby()
        # 检查emby用户是否存在
        uid = emby.get_uid_from_username(emby_username)
        if not uid:
            logger.warning(f"无法找到 Emby 用户 {emby_username}")
            return BaseResponse(success=False, message=f"用户 {emby_username} 不存在")

        # 检查emby用户是否已被绑定
        emby_info = db.get_emby_info_by_emby_username(emby_username)
        if emby_info:
            # 该emby用户存在于数据库
            if emby_info[2]:  # tg_id字段
                logger.warning(f"Emby账户 {emby_username} 已被其他Telegram账户绑定")
                return BaseResponse(
                    success=False,
                    message=f"该 Emby 账户已经绑定 Telegram 账户 {emby_info[2]}",
                )

            # 更新tg_id
            emby_credits = emby_info[6]
            db.update_user_tg_id(tg_id, emby_id=uid)
            # 清空emby用户表中的积分信息
            db.update_user_credits(0, emby_id=uid)
        else:
            # 添加新用户
            emby_credits = 0
            db.add_emby_user(emby_username, emby_id=uid, tg_id=tg_id)

        # 更新用户数据表中的积分
        stats_info = db.get_stats_by_tg_id(tg_id)
        if stats_info:
            tg_user_credits = stats_info[2] + emby_credits
            db.update_user_credits(tg_user_credits, tg_id=tg_id)
        else:
            db.add_user_data(tg_id, credits=emby_credits)

        logger.info(
            f"用户 {get_user_name_from_tg_id(tg_id)} 成功绑定Emby账户 {emby_username}"
        )
        return BaseResponse(
            success=True, message=f"绑定 Emby 账户 {emby_username} 成功！"
        )

    except Exception as e:
        logger.error(f"绑定Emby账户时发生错误: {e!s}")
        return BaseResponse(success=False, message="绑定失败，发生未知错误")
