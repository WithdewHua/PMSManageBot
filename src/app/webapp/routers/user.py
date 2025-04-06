from app.db import DB
from app.emby import Emby
from app.log import uvicorn_logger as logger
from app.plex import Plex
from app.tautulli import Tautulli
from app.utils import get_user_total_duration
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.models import TelegramUser, UserInfo
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

router = APIRouter(prefix="/api/user", tags=["user"])


class BindResponse(BaseModel):
    """绑定响应模型"""

    success: bool
    message: str


class BindPlexRequest(BaseModel):
    """绑定Plex请求模型"""

    email: EmailStr


class BindEmbyRequest(BaseModel):
    """绑定Emby请求模型"""

    username: str = Field(..., min_length=2)


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
        user_info = UserInfo(tg_id=tg_id)

        # 获取Plex信息
        try:
            logger.debug(f"正在查询用户 {tg_id} 的Plex信息")
            plex_info = db.get_plex_info_by_tg_id(tg_id)
            if plex_info:
                user_info.plex_info = {
                    "username": plex_info[4],
                    "email": plex_info[3],
                    "watched_time": plex_info[7],
                    "all_lib": plex_info[5] == 1,
                }
                logger.debug(f"用户 {tg_id} 的Plex信息获取成功")
            else:
                logger.debug(f"用户 {tg_id} 没有关联的Plex账户")
        except Exception as e:
            logger.error(f"获取用户 {tg_id} 的Plex信息失败: {str(e)}")

        # 获取Emby信息
        try:
            logger.debug(f"正在查询用户 {tg_id} 的Emby信息")
            emby_info = db.get_emby_info_by_tg_id(tg_id)
            if emby_info:
                user_info.emby_info = {
                    "username": emby_info[0],
                    "watched_time": emby_info[5],
                    "all_lib": emby_info[3] == 1,
                    "line": emby_info[7],
                }
                logger.debug(f"用户 {tg_id} 的Emby信息获取成功")
            else:
                logger.debug(f"用户 {tg_id} 没有关联的Emby账户")
        except Exception as e:
            logger.error(f"获取用户 {tg_id} 的Emby信息失败: {str(e)}")

        # 获取统计信息
        try:
            logger.debug(f"正在查询用户 {tg_id} 的统计信息")
            stats_info = db.get_stats_by_tg_id(tg_id)
            if stats_info:
                user_info.credits = stats_info[2]
                user_info.donation = stats_info[1]
                logger.debug(f"用户 {tg_id} 的统计信息获取成功")
            else:
                logger.debug(f"用户 {tg_id} 没有统计信息")
        except Exception as e:
            logger.error(f"获取用户 {tg_id} 的统计信息失败: {str(e)}")

        # 获取Overseerr信息
        try:
            logger.debug(f"正在查询用户 {tg_id} 的Overseerr信息")
            overseerr_info = db.get_overseerr_info_by_tg_id(tg_id)
            if overseerr_info:
                user_info.overseerr_info = {
                    "user_id": overseerr_info[0],
                    "email": overseerr_info[1],
                }
                logger.debug(f"用户 {tg_id} 的Overseerr信息获取成功")
            else:
                logger.debug(f"用户 {tg_id} 没有关联的Overseerr账户")
        except Exception as e:
            logger.error(f"获取用户 {tg_id} 的Overseerr信息失败: {str(e)}")

        # 获取邀请码
        try:
            logger.debug(f"正在查询用户 {tg_id} 的邀请码")
            codes = db.get_invitation_code_by_owner(tg_id)
            if codes:
                user_info.invitation_codes = codes
                logger.debug(f"用户 {tg_id} 的邀请码获取成功，共 {len(codes)} 个")
            else:
                logger.debug(f"用户 {tg_id} 没有邀请码")
        except Exception as e:
            logger.error(f"获取用户 {tg_id} 的邀请码失败: {str(e)}")

        logger.info(f"用户 {user_name or user_id} 的信息获取完成")
        return user_info
    except Exception as e:
        logger.error(f"获取用户信息时发生未预期的错误: {str(e)}")
        raise HTTPException(status_code=500, detail="获取用户信息失败")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")


@router.post("/bind/plex", response_model=BindResponse)
@require_telegram_auth
async def bind_plex_account(
    request: Request,
    data: BindPlexRequest = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """绑定Plex账户"""
    tg_id = telegram_user.id
    email = data.email

    logger.info(f"用户 {telegram_user.username or tg_id} 尝试绑定 Plex 账户 {email}")

    _db = DB()
    try:
        # 检查用户是否已绑定Plex
        _info = _db.get_plex_info_by_tg_id(tg_id)
        if _info:
            logger.warning(f"用户 {telegram_user.username or tg_id} 已绑定 Plex 账户")
            return BindResponse(
                success=False, message="您已绑定 Plex 账户，请勿重复操作"
            )

        _plex = Plex()
        plex_id = _plex.get_user_id_by_email(email)

        # 用户不存在
        if plex_id == 0:
            logger.warning(f"无法找到 Plex 用户 {email}")
            return BindResponse(
                success=False, message="该邮箱无 Plex 权限，请检查输入的邮箱"
            )

        # 检查该plex_id是否已绑定其他TG账户
        plex_info = _db.get_plex_info_by_plex_id(plex_id)
        if plex_info:
            tg_id_bound = plex_info[1]
            if tg_id_bound:
                logger.warning(
                    f"Plex账户 {email} 已被其他 Telegram 账户 {tg_id_bound} 绑定"
                )
                return BindResponse(
                    success=False,
                    message="该 Plex 账户已经绑定 Telegram 账户 {tg_id_bound}",
                )

            # 更新已存在用户的tg_id
            rslt = _db.update_user_tg_id(tg_id, plex_id=plex_id)
            if not rslt:
                logger.error(f"更新用户 {tg_id} 的 Plex 绑定失败")
                return BindResponse(success=False, message="数据库更新失败，请稍后再试")

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
                return BindResponse(
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
                logger.error(f"添加用户 {tg_id} 的 Plex 信息失败")
                return BindResponse(success=False, message="数据库更新失败，请稍后再试")

        # 获取用户数据表信息并更新积分
        stats_info = _db.get_stats_by_tg_id(tg_id)
        if stats_info:
            tg_user_credits = stats_info[2] + plex_credits
            _db.update_user_credits(tg_user_credits, tg_id=tg_id)
        else:
            _db.add_user_data(tg_id, credits=plex_credits)

        _db.con.commit()
        logger.info(
            f"用户 {telegram_user.username or tg_id} 成功绑定 Plex 账户 {email}"
        )
        return BindResponse(success=True, message=f"绑定 Plex 账户 {email} 成功！")

    except Exception as e:
        logger.error(f"绑定Plex账户时发生错误: {str(e)}")
        return BindResponse(success=False, message="绑定失败，发生未知错误")
    finally:
        _db.close()
        logger.debug("数据库连接已关闭")


@router.post("/bind/emby", response_model=BindResponse)
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
        f"用户 {telegram_user.username or tg_id} 尝试绑定 Emby 账户 {emby_username}"
    )

    db = DB()
    try:
        # 检查用户是否已绑定Emby
        info = db.get_emby_info_by_tg_id(tg_id)
        if info:
            logger.warning(f"用户 {telegram_user.username or tg_id} 已绑定Emby账户")
            return BindResponse(
                success=False, message="您已绑定 Emby 账户，请勿重复操作"
            )

        emby = Emby()
        # 检查emby用户是否存在
        uid = emby.get_uid_from_username(emby_username)
        if not uid:
            logger.warning(f"无法找到Emby用户 {emby_username}")
            return BindResponse(success=False, message=f"用户 {emby_username} 不存在")

        # 检查emby用户是否已被绑定
        emby_info = db.get_emby_info_by_emby_username(emby_username)
        if emby_info:
            # 该emby用户存在于数据库
            if emby_info[2]:  # tg_id字段
                logger.warning(f"Emby账户 {emby_username} 已被其他Telegram账户绑定")
                return BindResponse(
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
            f"用户 {telegram_user.username or tg_id} 成功绑定Emby账户 {emby_username}"
        )
        return BindResponse(
            success=True, message=f"绑定 Emby 账户 {emby_username} 成功！"
        )

    except Exception as e:
        logger.error(f"绑定Emby账户时发生错误: {str(e)}")
        return BindResponse(success=False, message="绑定失败，发生未知错误")
    finally:
        db.close()
        logger.debug("数据库连接已关闭")
