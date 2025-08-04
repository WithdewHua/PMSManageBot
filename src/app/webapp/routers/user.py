from time import time
from typing import Optional

from app.cache import (
    emby_last_user_defined_line_cache,
    emby_user_defined_line_cache,
    get_line_tags,
    plex_last_user_defined_line_cache,
    plex_user_defined_line_cache,
)
from app.config import settings
from app.db import DB
from app.emby import Emby
from app.log import uvicorn_logger as logger
from app.plex import Plex
from app.tautulli import Tautulli
from app.utils import (
    caculate_credits_fund,
    get_user_info_from_tg_id,
    get_user_name_from_tg_id,
    get_user_total_duration,
    is_binded_premium_line,
    send_message_by_url,
)
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.schemas import (
    AuthBindLineRequest,
    BaseResponse,
    BindEmbyRequest,
    BindPlexRequest,
    CreditsTransferRequest,
    CreditsTransferResponse,
    CurrentLineResponse,
    EmbyLineInfo,
    EmbyLineRequest,
    EmbyLinesResponse,
    PlexLineInfo,
    PlexLineRequest,
    PlexLinesResponse,
    TelegramUser,
    UserInfo,
)
from fastapi import APIRouter, Body, Depends, HTTPException, Request

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/info")
@require_telegram_auth
async def get_user_info(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取用户信息"""
    user_id = user.id
    user_name = user.username or user.first_name
    # 从数据库获取更多用户信息
    logger.info(f"开始获取用户 {user_name or user_id} 的详细信息")
    # 连接数据库
    db = DB()
    try:
        tg_id = user_id
        is_admin = False
        if tg_id in settings.ADMIN_CHAT_ID:
            is_admin = True
        user_info = UserInfo(tg_id=tg_id, is_admin=is_admin)

        # 获取Plex信息
        try:
            logger.debug(f"正在查询用户 {get_user_name_from_tg_id(tg_id)} 的Plex信息")
            plex_info = db.get_plex_info_by_tg_id(tg_id)
            if plex_info:
                # 获取今日流量消耗
                daily_traffic = db.get_user_daily_traffic(plex_info[4], "plex")
                # 获取今日 Premium 线路流量消耗
                daily_premium_traffic = db.get_user_daily_traffic(
                    plex_info[4], "plex", premium_only=True
                )

                user_info.plex_info = {
                    "username": plex_info[4],
                    "email": plex_info[3],
                    "watched_time": plex_info[7],
                    "all_lib": plex_info[5] == 1,
                    "line": plex_info[8],
                    "is_premium": plex_info[9] == 1,
                    "premium_expiry": plex_info[10],
                    "daily_traffic": daily_traffic,
                    "daily_premium_traffic": daily_premium_traffic,
                }
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 的 Plex 信息获取成功，今日流量: {daily_traffic} bytes, Premium流量: {daily_premium_traffic} bytes"
                )
            else:
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 没有关联的 Plex 账户"
                )
        except Exception as e:
            logger.error(
                f"获取用户 {get_user_name_from_tg_id(tg_id)} 的 Plex 信息失败: {str(e)}"
            )

        # 获取Emby信息
        try:
            logger.debug(f"正在查询用户 {get_user_name_from_tg_id(tg_id)} 的 Emby 信息")
            emby_info = db.get_emby_info_by_tg_id(tg_id)
            if emby_info:
                # 获取今日流量消耗
                daily_traffic = db.get_user_daily_traffic(emby_info[0], "emby")
                # 获取今日 Premium 线路流量消耗
                daily_premium_traffic = db.get_user_daily_traffic(
                    emby_info[0], "emby", premium_only=True
                )

                user_info.emby_info = {
                    "username": emby_info[0],
                    "watched_time": emby_info[5],
                    "all_lib": emby_info[3] == 1,
                    "line": emby_info[7],
                    "is_premium": emby_info[8] == 1,
                    "premium_expiry": emby_info[9],
                    "daily_traffic": daily_traffic,
                    "daily_premium_traffic": daily_premium_traffic,
                }
                created_at = (
                    Emby().get_user_info_from_username(emby_info[0]).get("date_created")
                )
                if created_at:
                    created_at = created_at.split("T")[0]  # 只保留日期部分
                user_info.emby_info["created_at"] = created_at
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 的 Emby 信息获取成功，今日流量: {daily_traffic} bytes, Premium流量: {daily_premium_traffic} bytes"
                )
            else:
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 没有关联的 Emby 账户"
                )
        except Exception as e:
            logger.error(
                f"获取用户 {get_user_name_from_tg_id(tg_id)} 的 Emby 信息失败: {str(e)}"
            )

        # 获取统计信息
        try:
            logger.debug(f"正在查询用户 {get_user_name_from_tg_id(tg_id)} 的统计信息")
            stats_info = db.get_stats_by_tg_id(tg_id)
            if stats_info:
                user_info.credits = stats_info[2]
                user_info.donation = stats_info[1]
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 的统计信息获取成功"
                )
            else:
                logger.debug(f"用户 {get_user_name_from_tg_id(tg_id)} 没有统计信息")
        except Exception as e:
            logger.error(
                f"获取用户 {get_user_name_from_tg_id(tg_id)} 的统计信息失败: {str(e)}"
            )

        # 获取Overseerr信息
        try:
            logger.debug(
                f"正在查询用户 {get_user_name_from_tg_id(tg_id)} 的Overseerr信息"
            )
            overseerr_info = db.get_overseerr_info_by_tg_id(tg_id)
            if overseerr_info:
                user_info.overseerr_info = {
                    "user_id": overseerr_info[0],
                    "email": overseerr_info[1],
                }
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 的Overseerr信息获取成功"
                )
            else:
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 没有关联的Overseerr账户"
                )
        except Exception as e:
            logger.error(
                f"获取用户 {get_user_name_from_tg_id(tg_id)} 的Overseerr信息失败: {str(e)}"
            )

        # 获取邀请码
        try:
            logger.debug(f"正在查询用户 {get_user_name_from_tg_id(tg_id)} 的邀请码")
            codes = db.get_invitation_code_by_owner(tg_id)
            if codes:
                user_info.invitation_codes = codes
                logger.debug(
                    f"用户 {get_user_name_from_tg_id(tg_id)} 的邀请码获取成功，共 {len(codes)} 个"
                )
            else:
                logger.debug(f"用户 {get_user_name_from_tg_id(tg_id)} 没有邀请码")
        except Exception as e:
            logger.error(
                f"获取用户 {get_user_name_from_tg_id(tg_id)} 的邀请码失败: {str(e)}"
            )

        logger.info(f"用户 {user_name or user_id} 的信息获取完成")
        return user_info
    except Exception as e:
        logger.error(f"获取用户信息时发生未预期的错误: {str(e)}")
        raise HTTPException(status_code=500, detail="获取用户信息失败")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


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

    _db = DB()
    try:
        # 检查用户是否已绑定Plex
        _info = _db.get_plex_info_by_tg_id(tg_id)
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

        # 检查该plex_id是否已绑定其他TG账户
        plex_info = _db.get_plex_info_by_plex_id(plex_id)
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
            rslt = _db.update_user_tg_id(tg_id, plex_id=plex_id)
            if not rslt:
                logger.error(
                    f"更新用户 {get_user_name_from_tg_id(tg_id)} 的 Plex 绑定失败"
                )
                return BaseResponse(success=False, message="数据库更新失败，请稍后再试")

            # 清空 plex 用户表中积分信息
            _db.update_user_credits(0, plex_id=plex_info[0])
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
                logger.error(f"获取用户观看时长失败: {str(e)}")
                return BaseResponse(
                    success=False, message="获取用户观看时长失败，请稍后再试"
                )

            # 写入数据库
            rslt = _db.add_plex_user(
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
        stats_info = _db.get_stats_by_tg_id(tg_id)
        if stats_info:
            tg_user_credits = stats_info[2] + plex_credits
            _db.update_user_credits(tg_user_credits, tg_id=tg_id)
        else:
            _db.add_user_data(tg_id, credits=plex_credits)

        _db.con.commit()
        logger.info(
            f"用户 {get_user_name_from_tg_id(tg_id)} 成功绑定 Plex 账户 {email}"
        )
        return BaseResponse(success=True, message=f"绑定 Plex 账户 {email} 成功！")

    except Exception as e:
        logger.error(f"绑定Plex账户时发生错误: {str(e)}")
        return BaseResponse(success=False, message="绑定失败，发生未知错误")
    finally:
        _db.close()
        logger.debug("数据库连接已关闭")


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

    db = DB()
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

        db.con.commit()
        logger.info(
            f"用户 {get_user_name_from_tg_id(tg_id)} 成功绑定Emby账户 {emby_username}"
        )
        return BaseResponse(
            success=True, message=f"绑定 Emby 账户 {emby_username} 成功！"
        )

    except Exception as e:
        logger.error(f"绑定Emby账户时发生错误: {str(e)}")
        return BaseResponse(success=False, message="绑定失败，发生未知错误")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


@router.get("/emby_lines", response_model=EmbyLinesResponse)
@require_telegram_auth
async def get_emby_lines(
    request: Request,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """获取可用的Emby线路列表"""
    db = DB()
    # 获取 emby 用户信息，确认是否是 premium 用户
    emby_info = db.get_emby_info_by_tg_id(telegram_user.id)
    if not emby_info:
        logger.warning(
            f"用户 {telegram_user.username or telegram_user.id} 未绑定 Emby 账户"
        )
        return EmbyLinesResponse(
            success=False, message="您未绑定 Emby 账户，无法查看线路", lines=[]
        )
    is_premium = emby_info[8] == 1

    # 基础线路
    available_lines = settings.STREAM_BACKEND.copy()
    line_infos = []

    # 添加基础线路信息
    for line in available_lines:
        line_infos.append(
            EmbyLineInfo(name=line, tags=get_line_tags(line), is_premium=False)
        )

    # 如果是premium用户，直接添加所有高级线路
    if is_premium:
        for line in settings.PREMIUM_STREAM_BACKEND:
            line_infos.append(
                EmbyLineInfo(name=line, tags=get_line_tags(line), is_premium=True)
            )
    # 如果不是premium用户，检查免费高级线路
    elif settings.PREMIUM_FREE:
        # 从Redis缓存获取免费高级线路列表
        from app.cache import free_premium_lines_cache

        free_premium_lines = free_premium_lines_cache.get("free_lines")
        free_premium_lines = free_premium_lines.split(",") if free_premium_lines else []

        for line in free_premium_lines:
            line_infos.append(
                EmbyLineInfo(
                    name=line, tags=get_line_tags(line) + ["PREMIUM"], is_premium=True
                )
            )

    return EmbyLinesResponse(
        lines=line_infos, success=True, message="获取 Emby 线路列表成功"
    )


@router.post("/bind/emby_line", response_model=BaseResponse)
@require_telegram_auth
async def bind_emby_line(
    request: Request,
    data: EmbyLineRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """绑定Emby线路"""
    tg_id = telegram_user.id
    line = data.line

    logger.info(f"用户 {get_user_name_from_tg_id(tg_id)} 尝试绑定 Emby 线路 {line}")

    db = DB()
    try:
        # 检查用户是否绑定了Emby账户
        emby_info = db.get_emby_info_by_tg_id(tg_id)
        if not emby_info:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 未绑定 Emby 账户")
            return BaseResponse(success=False, message="您尚未绑定Emby账户，请先绑定")
        emby_username, emby_line = emby_info[0], emby_info[7]
        if emby_line == line:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 已绑定该线路")
            return BaseResponse(success=False, message="该线路已绑定，请勿重复操作")

        # 更新用户线路设置
        is_premium = emby_info[8] == 1

        # 如果不是premium用户，需要检查线路权限
        if not is_premium:
            is_premium_line_flag = is_binded_premium_line(line)
            if is_premium_line_flag:
                # 检查该高级线路是否在免费列表中
                if settings.PREMIUM_FREE:
                    from app.cache import free_premium_lines_cache

                    free_premium_lines = free_premium_lines_cache.get("free_lines")
                    free_premium_lines = (
                        free_premium_lines.split(",") if free_premium_lines else []
                    )
                    if line not in free_premium_lines:
                        return BaseResponse(
                            success=False, message="该高级线路暂未开放免费使用"
                        )
                else:
                    return BaseResponse(
                        success=False, message="您不是 premium 用户，无法绑定该线路"
                    )
        success = db.set_emby_line(line, tg_id=tg_id)

        if not success:
            logger.error(f"设置用户 {get_user_name_from_tg_id(tg_id)} 的 Emby 线路失败")
            return BaseResponse(success=False, message="设置线路失败")

        # 更新 redis 缓存
        binded_line = emby_user_defined_line_cache.get(str(emby_username).lower())
        if binded_line and not is_binded_premium_line(binded_line):
            # 满足如下条件：
            # 1. 缓存中存在绑定的线路，且该线路不是高级线路；
            # 将其记录到上一次使用的普通线路缓存中
            logger.debug(f"记录用户 {emby_username} 上一次使用的普通线路 {binded_line}")
            emby_last_user_defined_line_cache.put(
                str(emby_username).lower(), binded_line
            )
        emby_user_defined_line_cache.put(str(emby_username).lower(), line)

        logger.info(
            f"用户 {get_user_name_from_tg_id(tg_id)} 成功绑定 Emby 线路 {line}，原线路：{binded_line}"
        )
        return BaseResponse(success=True, message=f"绑定线路 {line} 成功！")

    except Exception as e:
        logger.error(f"绑定Emby线路时发生错误: {str(e)}")
        return BaseResponse(success=False, message=f"绑定失败: {str(e)}")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


@router.post("/unbind/emby_line", response_model=BaseResponse)
@require_telegram_auth
async def unbind_emby_line(
    request: Request,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """解绑Emby线路（恢复自动选择）"""
    tg_id = telegram_user.id

    logger.info(f"用户 {get_user_name_from_tg_id(tg_id)} 尝试解绑 Emby 线路")

    db = DB()
    try:
        # 检查用户是否绑定了Emby账户
        emby_info = db.get_emby_info_by_tg_id(tg_id)
        if not emby_info:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 未绑定Emby账户")
            return BaseResponse(success=False, message="您尚未绑定 Emby 账户，请先绑定")
        emby_username, emby_line = emby_info[0], emby_info[7]
        if not emby_line:
            logger.warning(
                f"用户 {get_user_name_from_tg_id(tg_id)} 未绑定线路，无需解绑"
            )
            return BaseResponse(success=False, message="您未绑定线路，无需解绑")

        success = db.set_emby_line(None, tg_id=tg_id)
        if not success:
            logger.error(f"重置用户 {get_user_name_from_tg_id(tg_id)} 的 Emby 线路失败")
            return BaseResponse(success=False, message="重置线路失败")
        from app.cache import emby_user_defined_line_cache

        # 删除 redis 缓存
        emby_user_defined_line_cache.delete(str(emby_username).lower())

        logger.info(f"用户 {get_user_name_from_tg_id(tg_id)} 成功解绑 Emby 线路")
        return BaseResponse(success=True, message="已切换到自动选择线路")

    except Exception as e:
        logger.error(f"解绑 Emby 线路时发生错误: {str(e)}")
        return BaseResponse(success=False, message=f"解绑失败: {str(e)}")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


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

    _db = DB()
    try:
        if operation == "unlock":
            # 解锁操作返回所需积分
            return {"cost": settings.UNLOCK_CREDITS}
        else:
            # 锁定操作计算可返还积分
            if service == "plex":
                info = _db.get_plex_info_by_tg_id(tg_id)
                if not info or info[5] != 1:
                    raise HTTPException(status_code=400, detail="您尚未解锁 NSFW 内容")
                unlock_time = info[6]
            else:
                info = _db.get_emby_info_by_tg_id(tg_id)
                if not info or info[3] != 1:
                    raise HTTPException(status_code=400, detail="您尚未解锁 NSFW 内容")
                unlock_time = info[4]

            # 计算可返还积分
            credits_fund = caculate_credits_fund(unlock_time, settings.UNLOCK_CREDITS)
            return {"refund": credits_fund}
    except Exception as e:
        logger.error(f"获取 NSFW 信息时发生错误: {str(e)}")
        raise HTTPException(status_code=500, detail="获取NSFW信息失败")
    finally:
        _db.close()


@router.post("/nsfw/{operation}")
@require_telegram_auth
async def nsfw_operation(
    request: Request,
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
    _db = DB()

    try:
        # 获取用户统计信息
        stats_info = _db.get_stats_by_tg_id(tg_id)
        if not stats_info:
            raise HTTPException(status_code=404, detail="用户不存在")

        credits = stats_info[2]

        if operation == "unlock":
            # 解锁操作
            if service == "plex":
                # 获取Plex信息
                plex_info = _db.get_plex_info_by_tg_id(tg_id)
                if not plex_info:
                    raise HTTPException(status_code=404, detail="Plex账户未绑定")

                plex_id = plex_info[0]
                all_lib = plex_info[5]

                if all_lib == 1:
                    raise HTTPException(status_code=400, detail="您已拥有全部库权限")

                if credits < settings.UNLOCK_CREDITS:
                    raise HTTPException(status_code=400, detail="积分不足")

                # 扣除积分
                credits -= settings.UNLOCK_CREDITS

                # 更新权限
                _plex = Plex()
                try:
                    _plex.update_user_shared_libs(plex_id, _plex.get_libraries())
                except Exception:
                    raise HTTPException(status_code=500, detail="更新权限失败")

                # 解锁时间
                unlock_time = time()

                # 更新数据库
                if not _db.update_user_credits(credits, tg_id=tg_id):
                    raise HTTPException(status_code=500, detail="更新积分失败")

                if not _db.update_all_lib_flag(
                    all_lib=1, unlock_time=unlock_time, plex_id=plex_id
                ):
                    raise HTTPException(status_code=500, detail="更新权限状态失败")

            else:
                # 获取Emby信息
                emby_info = _db.get_emby_info_by_tg_id(tg_id)
                if not emby_info:
                    raise HTTPException(status_code=404, detail="Emby账户未绑定")

                emby_id = emby_info[1]
                all_lib = emby_info[3]

                if all_lib == 1:
                    raise HTTPException(status_code=400, detail="您已拥有全部库权限")

                if credits < settings.UNLOCK_CREDITS:
                    raise HTTPException(status_code=400, detail="积分不足")

                # 扣除积分
                credits -= settings.UNLOCK_CREDITS

                # 更新权限
                _emby = Emby()
                flag, msg = _emby.add_user_library(user_id=emby_id)
                if not flag:
                    raise HTTPException(status_code=500, detail=f"更新权限失败: {msg}")

                # 解锁时间
                unlock_time = time()

                # 更新数据库
                if not _db.update_user_credits(credits, tg_id=tg_id):
                    raise HTTPException(status_code=500, detail="更新积分失败")

                if not _db.update_all_lib_flag(
                    all_lib=1, unlock_time=unlock_time, tg_id=tg_id, media_server="emby"
                ):
                    raise HTTPException(status_code=500, detail="更新权限状态失败")

        else:
            # 锁定操作
            if service == "plex":
                # 获取Plex信息
                plex_info = _db.get_plex_info_by_tg_id(tg_id)
                if not plex_info:
                    raise HTTPException(status_code=404, detail="Plex账户未绑定")

                plex_id = plex_info[0]
                all_lib = plex_info[5]
                unlock_time = plex_info[6]

                if all_lib == 0:
                    raise HTTPException(status_code=400, detail="您未解锁NSFW内容")

                # 计算返还积分
                credits_fund = caculate_credits_fund(
                    unlock_time, settings.UNLOCK_CREDITS
                )
                credits += credits_fund

                # 更新权限
                _plex = Plex()
                sections = _plex.get_libraries()
                for section in settings.NSFW_LIBS:
                    if section in sections:
                        sections.remove(section)

                try:
                    _plex.update_user_shared_libs(plex_id, sections)
                except Exception:
                    raise HTTPException(status_code=500, detail="更新权限失败")

                # 更新数据库
                if not _db.update_user_credits(credits, tg_id=tg_id):
                    raise HTTPException(status_code=500, detail="更新积分失败")

                if not _db.update_all_lib_flag(
                    all_lib=0, unlock_time=None, plex_id=plex_id
                ):
                    raise HTTPException(status_code=500, detail="更新权限状态失败")

            else:
                # 获取Emby信息
                emby_info = _db.get_emby_info_by_tg_id(tg_id)
                if not emby_info:
                    raise HTTPException(status_code=404, detail="Emby账户未绑定")

                emby_id = emby_info[1]
                all_lib = emby_info[3]
                unlock_time = emby_info[4]

                if all_lib == 0:
                    raise HTTPException(status_code=400, detail="您未解锁NSFW内容")

                # 计算返还积分
                credits_fund = caculate_credits_fund(
                    unlock_time, settings.UNLOCK_CREDITS
                )
                credits += credits_fund

                # 更新权限
                _emby = Emby()
                flag, msg = _emby.remove_user_library(user_id=emby_id)
                if not flag:
                    raise HTTPException(status_code=500, detail=f"更新权限失败: {msg}")

                # 更新数据库
                if not _db.update_user_credits(credits, tg_id=tg_id):
                    raise HTTPException(status_code=500, detail="更新积分失败")

                if not _db.update_all_lib_flag(
                    all_lib=0, unlock_time=None, tg_id=tg_id, media_server="emby"
                ):
                    raise HTTPException(status_code=500, detail="更新权限状态失败")

        return {
            "success": True,
            "message": f"NSFW 内容已{'解锁' if operation == 'unlock' else '锁定'}",
            "credits": credits,
        }

    except HTTPException:
        # 向上传递HTTP异常
        raise
    except Exception as e:
        logger.error(f"执行 NSFW 操作时发生错误: {str(e)}")
        raise HTTPException(status_code=500, detail="操作失败，请稍后再试")
    finally:
        _db.close()


@router.get("/plex_lines", response_model=PlexLinesResponse)
@require_telegram_auth
async def get_plex_lines(
    request: Request,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """获取可用的Plex线路列表"""
    db = DB()
    try:
        # 获取 plex 用户信息，确认是否绑定
        plex_info = db.get_plex_info_by_tg_id(telegram_user.id)
        if not plex_info:
            logger.warning(
                f"用户 {telegram_user.username or telegram_user.id} 未绑定 Plex 账户"
            )
            return PlexLinesResponse(
                success=False, message="您未绑定 Plex 账户，无法查看线路", lines=[]
            )

        # 检查用户是否为高级用户
        is_premium_user = plex_info[9] == 1  # 假设 is_premium 字段在索引 9

        # 获取基础线路和高级线路
        available_lines = settings.STREAM_BACKEND.copy()
        premium_lines = settings.PREMIUM_STREAM_BACKEND.copy()
        line_infos = []

        # 添加基础线路信息
        for line in available_lines:
            line_infos.append(
                PlexLineInfo(name=line, tags=get_line_tags(line), is_premium=False)
            )

        # 根据用户权限添加高级线路信息
        if is_premium_user:
            # 高级用户可以看到所有高级线路
            for line in premium_lines:
                line_infos.append(
                    PlexLineInfo(name=line, tags=get_line_tags(line), is_premium=True)
                )
        elif settings.PREMIUM_FREE:
            # 普通用户在免费开放期间可以看到免费的高级线路
            from app.cache import free_premium_lines_cache

            free_premium_lines = free_premium_lines_cache.get("free_lines")
            free_premium_lines = (
                free_premium_lines.split(",") if free_premium_lines else []
            )

            for line in free_premium_lines:
                if line in premium_lines:
                    line_infos.append(
                        PlexLineInfo(
                            name=line, tags=get_line_tags(line), is_premium=True
                        )
                    )

        return PlexLinesResponse(
            lines=line_infos, success=True, message="获取 Plex 线路列表成功"
        )
    finally:
        db.close()


@router.post("/bind/plex_line", response_model=BaseResponse)
@require_telegram_auth
async def bind_plex_line(
    request: Request,
    data: PlexLineRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """绑定Plex线路"""
    tg_id = telegram_user.id
    line = data.line

    logger.info(f"用户 {get_user_name_from_tg_id(tg_id)} 尝试绑定 Plex 线路 {line}")

    db = DB()
    try:
        # 检查用户是否绑定了Plex账户
        plex_info = db.get_plex_info_by_tg_id(tg_id)
        if not plex_info:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 未绑定 Plex 账户")
            return BaseResponse(success=False, message="您尚未绑定Plex账户，请先绑定")

        plex_username, plex_line = plex_info[4], plex_info[8]
        if plex_line == line:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 已绑定该线路")
            return BaseResponse(success=False, message="该线路已绑定，请勿重复操作")

        # 检查线路是否存在于可用线路中
        # if (
        #     line not in settings.STREAM_BACKEND
        #     and line not in settings.PREMIUM_STREAM_BACKEND
        # ):
        #     return BaseResponse(success=False, message="该线路不存在或不可用")

        # 更新用户线路设置
        is_premium = plex_info[9] == 1

        # 如果不是premium用户，需要检查线路权限
        if not is_premium:
            is_premium_line_flag = is_binded_premium_line(line)
            if is_premium_line_flag:
                # 检查该高级线路是否在免费列表中
                if settings.PREMIUM_FREE:
                    from app.cache import free_premium_lines_cache

                    free_premium_lines = free_premium_lines_cache.get("free_lines")
                    free_premium_lines = (
                        free_premium_lines.split(",") if free_premium_lines else []
                    )
                    if line not in free_premium_lines:
                        return BaseResponse(
                            success=False, message="该高级线路暂未开放免费使用"
                        )
                else:
                    return BaseResponse(
                        success=False, message="您不是 premium 用户，无法绑定该线路"
                    )

        success = db.set_plex_line(line, tg_id=tg_id)
        if not success:
            logger.error(f"设置用户 {get_user_name_from_tg_id(tg_id)} 的 Plex 线路失败")
            return BaseResponse(success=False, message="设置线路失败")

        # 更新 redis 缓存
        binded_line = plex_user_defined_line_cache.get(str(plex_username).lower())
        if binded_line and not is_binded_premium_line(binded_line):
            # 满足如下条件：
            # 1. 缓存中存在绑定的线路，且该线路不是高级线路；
            # 将其记录到上一次使用的普通线路缓存中
            logger.debug(f"记录用户 {plex_username} 上一次使用的普通线路 {binded_line}")
            plex_last_user_defined_line_cache.put(
                str(plex_username).lower(), binded_line
            )
        plex_user_defined_line_cache.put(str(plex_username).lower(), line)

        logger.info(
            f"用户 {get_user_name_from_tg_id(tg_id)} 成功绑定 Plex 线路 {line}，原线路：{binded_line}"
        )
        return BaseResponse(success=True, message=f"绑定线路 {line} 成功！")

    except Exception as e:
        logger.error(f"绑定 Plex 线路时发生错误: {str(e)}")
        return BaseResponse(success=False, message=f"绑定失败: {str(e)}")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


@router.post("/unbind/plex_line", response_model=BaseResponse)
@require_telegram_auth
async def unbind_plex_line(
    request: Request,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """解绑Plex线路（恢复自动选择）"""
    tg_id = telegram_user.id

    logger.info(f"用户 {get_user_name_from_tg_id(tg_id)} 尝试解绑 Plex 线路")

    db = DB()
    try:
        # 检查用户是否绑定了Plex账户
        plex_info = db.get_plex_info_by_tg_id(tg_id)
        if not plex_info:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 未绑定Plex账户")
            return BaseResponse(success=False, message="您尚未绑定 Plex 账户，请先绑定")

        plex_username, plex_line = plex_info[4], plex_info[8]
        if not plex_line:
            logger.warning(
                f"用户 {get_user_name_from_tg_id(tg_id)} 未绑定线路，无需解绑"
            )
            return BaseResponse(success=False, message="您未绑定线路，无需解绑")

        success = db.set_plex_line(None, tg_id=tg_id)
        if not success:
            logger.error(f"重置用户 {tg_id} 的 Plex 线路失败")
            return BaseResponse(success=False, message="重置线路失败")

        # 删除 redis 缓存
        plex_user_defined_line_cache.delete(str(plex_username).lower())

        logger.info(f"用户 {get_user_name_from_tg_id(tg_id)} 成功解绑 Plex 线路")
        return BaseResponse(success=True, message="已切换到自动选择线路")

    except Exception as e:
        logger.error(f"解绑 Plex 线路时发生错误: {str(e)}")
        return BaseResponse(success=False, message=f"解绑失败: {str(e)}")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


# ==================== 通用线路管理API ====================


@router.get("/lines/{service}", response_model=dict)
@require_telegram_auth
async def get_lines_generic(
    service: str,
    request: Request,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """获取可用的线路列表（通用，同时支持Plex和Emby）"""
    if service not in ["emby", "plex"]:
        raise HTTPException(status_code=400, detail="服务类型必须是 'emby' 或 'plex'")

    if service == "emby":
        return await get_emby_lines(request, telegram_user)
    else:
        return await get_plex_lines(request, telegram_user)


@router.post("/lines/{service}/bind", response_model=BaseResponse)
@require_telegram_auth
async def bind_line_generic(
    service: str,
    request: Request,
    data: dict = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """绑定线路（通用，同时支持Plex和Emby）"""
    if service not in ["emby", "plex"]:
        raise HTTPException(status_code=400, detail="服务类型必须是 'emby' 或 'plex'")

    line = data.get("line")
    if not line:
        raise HTTPException(status_code=400, detail="线路名称不能为空")

    if service == "emby":
        emby_data = EmbyLineRequest(line=line)
        return await bind_emby_line(request, emby_data, telegram_user)
    else:
        plex_data = PlexLineRequest(line=line)
        return await bind_plex_line(request, plex_data, telegram_user)


@router.post("/lines/{service}/unbind", response_model=BaseResponse)
@require_telegram_auth
async def unbind_line_generic(
    service: str,
    request: Request,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """解绑线路（通用，同时支持Plex和Emby）"""
    if service not in ["emby", "plex"]:
        raise HTTPException(status_code=400, detail="服务类型必须是 'emby' 或 'plex'")

    if service == "emby":
        return await unbind_emby_line(request, telegram_user)
    else:
        return await unbind_plex_line(request, telegram_user)


@router.post("/auth-bind/{service}", response_model=BaseResponse)
@require_telegram_auth
async def auth_bind_line(
    service: str,
    request: Request,
    data: AuthBindLineRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """认证并绑定线路（通用，同时支持Plex和Emby）"""
    if service not in ["emby", "plex"]:
        raise HTTPException(status_code=400, detail="服务类型必须是 'emby' 或 'plex'")

    tg_id = telegram_user.id
    username = data.username
    password = data.password
    token = data.token
    line = data.line

    logger.info(
        f"用户 {get_user_name_from_tg_id(tg_id)} 尝试认证并绑定 {service} 线路 {line}"
    )

    db = DB()
    try:
        if service == "emby":
            return await _auth_bind_emby_line(
                db, tg_id, telegram_user, username, password, line
            )
        else:
            return await _auth_bind_plex_line(
                db, tg_id, telegram_user, username, line, token=token, password=password
            )
    except Exception as e:
        logger.error(f"认证绑定{service}线路时发生错误: {str(e)}")
        return BaseResponse(success=False, message=f"认证绑定失败: {str(e)}")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


async def _auth_bind_emby_line(
    db: DB,
    tg_id: int,
    telegram_user: TelegramUser,
    username: str,
    password: str,
    line: str,
) -> BaseResponse:
    """认证并绑定Emby线路的内部方法"""
    from app.cache import (
        emby_last_user_defined_line_cache,
        emby_user_defined_line_cache,
    )

    # 验证 Emby 用户名和密码
    emby = Emby()
    auth_success, emby_id = emby.authenticate_user(username, password)
    if not auth_success:
        logger.warning(f"Emby用户 {username} 认证失败")
        return BaseResponse(success=False, message="用户名或密码错误")

    # 检查线路权限 - 获取用户信息以确定是否为premium用户
    existing_emby_info = db.get_emby_info_by_emby_username(username)
    is_premium = existing_emby_info[8] == 1 if existing_emby_info else False

    if not is_premium:
        is_premium_line_flag = is_binded_premium_line(line)
        if is_premium_line_flag:
            if settings.PREMIUM_FREE:
                from app.cache import free_premium_lines_cache

                free_premium_lines = free_premium_lines_cache.get("free_lines")
                free_premium_lines = (
                    free_premium_lines.split(",") if free_premium_lines else []
                )
                if line not in free_premium_lines:
                    return BaseResponse(
                        success=False, message="该高级线路暂未开放免费使用"
                    )
            else:
                return BaseResponse(
                    success=False, message="您不是 premium 用户，无法绑定该线路"
                )

    # 设置线路到数据库（如果用户存在于数据库中）
    if existing_emby_info:
        success = db.set_emby_line(line, emby_id=emby_id)
        if not success:
            logger.error(f"设置 Emby 用户 {username} 的线路失败")
            return BaseResponse(success=False, message="设置线路失败")

    # 更新 redis 缓存 - 记录线路绑定
    binded_line = emby_user_defined_line_cache.get(str(username).lower())
    if binded_line and not is_binded_premium_line(binded_line):
        logger.debug(f"记录用户 {username} 上一次使用的普通线路 {binded_line}")
        emby_last_user_defined_line_cache.put(str(username).lower(), binded_line)
    emby_user_defined_line_cache.put(str(username).lower(), line)

    logger.info(
        f"用户 {get_user_name_from_tg_id(tg_id)} 为 {username} 成功认证并绑定Emby线路 {line}"
    )
    return BaseResponse(success=True, message=f"认证并绑定 Emby 线路 {line} 成功！")


async def _auth_bind_plex_line(
    db: DB,
    tg_id: int,
    telegram_user: TelegramUser,
    username: str,
    line: str,
    password: Optional[str] = None,
    token: Optional[str] = None,
) -> BaseResponse:
    """认证并绑定Plex线路的内部方法"""
    from app.cache import (
        plex_last_user_defined_line_cache,
        plex_user_defined_line_cache,
    )

    # 验证Plex用户名和密码
    plex = Plex()
    auth_success, plex_id = plex.authenticate_user(
        username=username, password=password, token=token
    )
    if not auth_success:
        logger.warning(f"Plex 用户 {username} 认证失败")
        return BaseResponse(success=False, message="用户名或密码错误")

    # 检查线路权限 - 获取用户信息以确定是否为premium用户
    existing_plex_info = db.get_plex_info_by_plex_id(plex_id)
    is_premium = existing_plex_info[9] == 1 if existing_plex_info else False

    if not is_premium:
        is_premium_line_flag = is_binded_premium_line(line)
        if is_premium_line_flag:
            if settings.PREMIUM_FREE:
                from app.cache import free_premium_lines_cache

                free_premium_lines = free_premium_lines_cache.get("free_lines")
                free_premium_lines = (
                    free_premium_lines.split(",") if free_premium_lines else []
                )
                if line not in free_premium_lines:
                    return BaseResponse(
                        success=False, message="该高级线路暂未开放免费使用"
                    )
            else:
                return BaseResponse(
                    success=False, message="您不是 premium 用户，无法绑定该线路"
                )

    # 如果用户已存在，更新数据库中的线路设置
    if existing_plex_info:
        success = db.set_plex_line(line, plex_id=plex_id)
        if not success:
            logger.error(
                f"{get_user_name_from_tg_id(tg_id)} 为 {username} 设置 Plex 线路失败"
            )
            return BaseResponse(success=False, message="设置线路失败")

    # 更新 redis 缓存 - 记录线路绑定
    plex_username = plex.get_username_by_user_id(plex_id)
    binded_line = plex_user_defined_line_cache.get(str(plex_username).lower())
    if binded_line and not is_binded_premium_line(binded_line):
        logger.debug(f"记录用户 {plex_username} 上一次使用的普通线路 {binded_line}")
        plex_last_user_defined_line_cache.put(str(plex_username).lower(), binded_line)
    plex_user_defined_line_cache.put(str(plex_username).lower(), line)

    logger.info(
        f"用户 {get_user_name_from_tg_id(tg_id)} 为 {plex_username} 成功认证并绑定 Plex 线路 {line}"
    )
    return BaseResponse(success=True, message=f"认证并绑定 Plex 线路 {line} 成功！")


@router.post("/lines/emby/available", response_model=EmbyLinesResponse)
@require_telegram_auth
async def get_emby_lines_by_user(
    request: Request,
    data: dict = Body(...),
):
    """基于用户名获取可用的Emby线路列表（无需认证，仅查询数据库中的用户信息）"""
    username = data.get("username")

    if not username:
        return EmbyLinesResponse(success=False, message="用户名不能为空", lines=[])

    db = DB()
    try:
        # 直接从数据库查询用户信息，无需进行Emby服务器认证
        emby_info = db.get_emby_info_by_emby_username(username)
        if not emby_info:
            logger.warning(f"Emby用户 {username} 未在数据库中找到记录")
            return EmbyLinesResponse(
                success=False, message="该用户未在系统中注册", lines=[]
            )

        is_premium = emby_info[8] == 1

        # 基础线路
        available_lines = settings.STREAM_BACKEND.copy()
        line_infos = []

        # 添加基础线路信息
        for line in available_lines:
            line_infos.append(
                EmbyLineInfo(name=line, tags=get_line_tags(line), is_premium=False)
            )

        # 如果是premium用户，直接添加所有高级线路
        if is_premium:
            for line in settings.PREMIUM_STREAM_BACKEND:
                line_infos.append(
                    EmbyLineInfo(name=line, tags=get_line_tags(line), is_premium=True)
                )
        # 如果不是premium用户，检查免费高级线路
        elif settings.PREMIUM_FREE:
            # 从Redis缓存获取免费高级线路列表
            from app.cache import free_premium_lines_cache

            free_premium_lines = free_premium_lines_cache.get("free_lines")
            free_premium_lines = (
                free_premium_lines.split(",") if free_premium_lines else []
            )

            for line in free_premium_lines:
                if line in settings.PREMIUM_STREAM_BACKEND:
                    line_infos.append(
                        EmbyLineInfo(
                            name=line, tags=get_line_tags(line), is_premium=True
                        )
                    )

        logger.info(f"为 Emby 用户 {username} 返回 {len(line_infos)} 条线路信息")
        return EmbyLinesResponse(
            success=True, lines=line_infos, message="获取线路列表成功"
        )

    except Exception as e:
        logger.error(f"获取 Emby 用户 {username} 的线路列表时发生错误: {str(e)}")
        return EmbyLinesResponse(
            success=False, message=f"获取线路列表失败: {str(e)}", lines=[]
        )
    finally:
        db.close()


@router.post("/lines/plex/available", response_model=PlexLinesResponse)
@require_telegram_auth
async def get_plex_lines_by_user(
    request: Request,
    data: dict = Body(...),
):
    """基于邮箱获取可用的Plex线路列表（无需认证，仅查询数据库中的用户信息）"""
    email = data.get("email")

    if not email:
        return PlexLinesResponse(success=False, message="邮箱不能为空", lines=[])

    db = DB()
    try:
        # 直接从数据库查询用户信息，无需进行Plex服务器认证
        plex_info = db.get_plex_info_by_plex_email(email)
        if not plex_info:
            logger.warning(f"Plex 用户 {email} 未在数据库中找到记录")
            return PlexLinesResponse(
                success=False, message="该用户未在系统中注册", lines=[]
            )

        # 检查用户是否为高级用户
        is_premium_user = plex_info[9] == 1

        # 获取基础线路和高级线路
        available_lines = settings.STREAM_BACKEND.copy()
        premium_lines = settings.PREMIUM_STREAM_BACKEND.copy()
        line_infos = []

        # 添加基础线路信息
        for line in available_lines:
            line_infos.append(
                PlexLineInfo(name=line, tags=get_line_tags(line), is_premium=False)
            )

        # 根据用户权限添加高级线路信息
        if is_premium_user:
            # 高级用户可以看到所有高级线路
            for line in premium_lines:
                line_infos.append(
                    PlexLineInfo(name=line, tags=get_line_tags(line), is_premium=True)
                )
        elif settings.PREMIUM_FREE:
            # 普通用户在免费开放期间可以看到免费的高级线路
            from app.cache import free_premium_lines_cache

            free_premium_lines = free_premium_lines_cache.get("free_lines")
            free_premium_lines = (
                free_premium_lines.split(",") if free_premium_lines else []
            )

            for line in free_premium_lines:
                if line in premium_lines:
                    line_infos.append(
                        PlexLineInfo(
                            name=line, tags=get_line_tags(line), is_premium=True
                        )
                    )

        logger.info(f"为 Plex 用户 {email} 返回 {len(line_infos)} 条线路信息")
        return PlexLinesResponse(
            success=True, lines=line_infos, message="获取线路列表成功"
        )

    except Exception as e:
        logger.error(f"获取 Plex 用户 {email} 的线路列表时发生错误: {str(e)}")
        return PlexLinesResponse(
            success=False, message=f"获取线路列表失败: {str(e)}", lines=[]
        )
    finally:
        db.close()


@router.post("/transfer-credits", response_model=CreditsTransferResponse)
@require_telegram_auth
async def transfer_credits(
    request: Request,
    data: CreditsTransferRequest = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """
    积分转移功能

    转移积分给其他用户，收取手续费
    """
    try:
        # 检查积分转移功能是否开启
        if not settings.CREDITS_TRANSFER_ENABLED:
            return CreditsTransferResponse(success=False, message="积分转移功能已关闭")

        sender_id = user.id
        target_tg_id = data.target_tg_id
        amount = data.amount
        note = data.note

        # 验证不能给自己转移积分
        if sender_id == target_tg_id:
            return CreditsTransferResponse(success=False, message="不能向自己转移积分")

        # 验证转移数量
        if amount <= 0:
            return CreditsTransferResponse(
                success=False, message="转移积分数量必须大于0"
            )

        if amount > 10000:
            return CreditsTransferResponse(
                success=False, message="单次转移积分不能超过10000"
            )

        _db = DB()

        try:
            # 获取发送方当前积分
            sender_stats = _db.get_stats_by_tg_id(sender_id)
            if not sender_stats:
                return CreditsTransferResponse(
                    success=False, message="您尚未绑定 Plex/Emby 账户"
                )

            sender_credits = sender_stats[2]

            # 计算手续费 (5%)
            fee_amount = amount * 0.05
            total_deduction = amount + fee_amount

            # 检查余额是否足够
            if sender_credits < total_deduction:
                return CreditsTransferResponse(
                    success=False,
                    message=f"积分不足，需要 {total_deduction:.2f} 积分（包含 {fee_amount:.2f} 手续费）",
                )

            # 获取接收方信息
            target_stats = _db.get_stats_by_tg_id(target_tg_id)
            if not target_stats:
                return CreditsTransferResponse(
                    success=False, message="目标用户不存在或未绑定账户"
                )

            target_credits = target_stats[2]

            # 执行转移
            new_sender_credits = sender_credits - total_deduction
            new_target_credits = target_credits + amount

            # 更新发送方积分
            sender_success = _db.update_user_credits(
                new_sender_credits, tg_id=sender_id
            )
            if not sender_success:
                return CreditsTransferResponse(
                    success=False, message="更新发送方积分失败，请稍后再试"
                )

            # 更新接收方积分
            target_success = _db.update_user_credits(
                new_target_credits, tg_id=target_tg_id
            )
            if not target_success:
                # 如果接收方更新失败，回滚发送方积分
                _db.update_user_credits(sender_credits, tg_id=sender_id)
                return CreditsTransferResponse(
                    success=False, message="更新接收方积分失败，操作已回滚"
                )

            # 记录转移日志
            from app.utils import get_user_name_from_tg_id

            sender_name = get_user_name_from_tg_id(sender_id)
            target_name = get_user_name_from_tg_id(target_tg_id)

            logger.info(
                f"积分转移成功: {sender_name}({sender_id}) -> {target_name}({target_tg_id}), "
                f"金额: {amount}, 手续费: {fee_amount:.2f}"
                + (f", 备注: {note}" if note else "")
            )

            # 可以在这里发送通知给接收方用户
            try:
                await send_message_by_url(
                    chat_id=target_tg_id,
                    text=f"""
您收到了来自 {sender_name} 的积分转移: {amount} 积分
"""
                    + (f"""备注: {note}""" if note else ""),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning(f"发送积分转移通知失败: {str(e)}")

            return CreditsTransferResponse(
                success=True,
                message=f"成功转移 {amount} 积分给用户 {target_name}",
                transferred_amount=amount,
                fee_amount=fee_amount,
                current_credits=new_sender_credits,
            )

        finally:
            _db.close()

    except Exception as e:
        logger.error(f"积分转移失败: {str(e)}")
        return CreditsTransferResponse(
            success=False, message="转移过程出错，请稍后再试"
        )


@router.get("/users")
@require_telegram_auth
async def get_all_users(
    request: Request, user: TelegramUser = Depends(get_telegram_user)
):
    """获取所有用户信息（用于用户选择）"""

    db = DB()
    try:
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
            f"用户 {get_user_name_from_tg_id(user.id)} 获取了 {len(user_list)} 个用户信息"
        )
        return user_list

    except Exception as e:
        logger.error(f"获取用户列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取用户列表失败")
    finally:
        db.close()


@router.post("/lines/{service}/current", response_model=CurrentLineResponse)
@require_telegram_auth
async def get_current_bound_line(
    service: str,
    request: Request,
    data: dict = Body(...),
):
    """获取用户当前绑定的线路信息（基于用户名/邮箱）"""
    if service not in ["emby", "plex"]:
        raise HTTPException(status_code=400, detail="服务类型必须是 'emby' 或 'plex'")

    db = DB()
    try:
        if service == "emby":
            username = data.get("username")
            if not username:
                return CurrentLineResponse(success=False, message="用户名不能为空")

            # 查询Emby用户信息
            emby_info = db.get_emby_info_by_emby_username(username)
            if not emby_info:
                return CurrentLineResponse(
                    success=False, message="该用户未在系统中注册"
                )

            current_line = emby_info[7]  # emby_line字段是第8列(索引7)
            if current_line:
                return CurrentLineResponse(
                    success=True,
                    line=current_line,
                    message=f"用户 {username} 当前绑定线路: {current_line}",
                )
            else:
                return CurrentLineResponse(
                    success=True, line=None, message=f"用户 {username} 未绑定任何线路"
                )

        else:  # plex
            email = data.get("email")
            if not email:
                return CurrentLineResponse(success=False, message="邮箱不能为空")

            # 查询Plex用户信息
            plex_info = db.get_plex_info_by_plex_email(email)
            if not plex_info:
                return CurrentLineResponse(
                    success=False, message="该用户未在系统中注册"
                )

            current_line = plex_info[8]  # plex_line字段是第9列(索引8)
            if current_line:
                return CurrentLineResponse(
                    success=True,
                    line=current_line,
                    message=f"用户 {email} 当前绑定线路: {current_line}",
                )
            else:
                return CurrentLineResponse(
                    success=True, line=None, message=f"用户 {email} 未绑定任何线路"
                )

    except Exception as e:
        logger.error(f"获取用户当前绑定线路时发生错误: {str(e)}")
        return CurrentLineResponse(
            success=False, message=f"获取当前绑定线路失败: {str(e)}"
        )
    finally:
        db.close()
