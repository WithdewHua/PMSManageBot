import asyncio

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request

from app.core.log import uvicorn_logger as logger
from app.domains.lines import catalog
from app.domains.lines import notifications as lines_notifications
from app.domains.lines import service as lines_service
from app.domains.lines.gateway_cache import (
    emby_last_user_defined_line_cache,
    emby_user_defined_line_cache,
    plex_last_user_defined_line_cache,
    plex_user_defined_line_cache,
)
from app.domains.lines.rules import is_binded_premium_line
from app.domains.lines.schemas import (
    AuthBindLineRequest,
    CurrentLineResponse,
    EmbyLineInfo,
    EmbyLineRequest,
    EmbyLinesResponse,
    LineScheduleCreate,
    LineScheduleInfo,
    LineScheduleListResponse,
    LineScheduleStatusResponse,
    LineScheduleUnlockRequest,
    LineScheduleUnlockResponse,
    LineScheduleUpdate,
    PlexLineInfo,
    PlexLineRequest,
    PlexLinesResponse,
)
from app.domains.lines.service import (
    _auth_bind_emby_line,
    _auth_bind_plex_line,
    auto_switch_user_lines,
    check_line_permission,
)
from app.integrations.telegram.profiles import get_user_name_from_tg_id
from app.transport.http.auth import get_telegram_user, require_telegram_auth
from app.transport.http.schemas import BaseResponse, TelegramUser

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/emby_lines", response_model=EmbyLinesResponse)
@require_telegram_auth
async def get_emby_lines(
    request: Request,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """获取可用的Emby线路列表"""

    # 获取 emby 用户信息，确认是否是 premium 用户
    emby_info = lines_service.get_user_emby_info(telegram_user.id)
    if not emby_info:
        logger.warning(
            f"用户 {telegram_user.username or telegram_user.id} 未绑定 Emby 账户"
        )
        return EmbyLinesResponse(
            success=False, message="您未绑定 Emby 账户，无法查看线路", lines=[]
        )
    is_premium = emby_info[8] == 1

    # 基础线路
    available_lines = catalog.normal_lines().copy()
    line_infos = []

    # 添加基础线路信息
    for line in available_lines:
        line_infos.append(
            EmbyLineInfo(name=line, tags=catalog.line_tags(line), is_premium=False)
        )

    # 如果是premium用户，直接添加所有高级线路
    if is_premium:
        for line in catalog.premium_lines():
            line_infos.append(
                EmbyLineInfo(
                    name=line,
                    tags=catalog.line_tags(line),
                    is_premium=True,
                )
            )
    # 如果不是premium用户，检查免费高级线路
    elif lines_service.is_premium_free_enabled():
        # 从数据库获取免费高级线路列表
        free_premium_lines = catalog.free_premium_lines()

        for line in free_premium_lines:
            line_infos.append(
                EmbyLineInfo(
                    name=line,
                    tags=catalog.line_tags(line) + ["PREMIUM"],
                    is_premium=True,
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

    try:
        # 检查用户是否绑定了Emby账户
        emby_info = lines_service.get_user_emby_info(tg_id)
        if not emby_info:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 未绑定 Emby 账户")
            return BaseResponse(success=False, message="您尚未绑定Emby账户，请先绑定")
        emby_username, emby_line = emby_info[0], emby_info[7]
        is_premium = emby_info[8] == 1

        if emby_line == line:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 已绑定该线路")
            return BaseResponse(success=False, message="该线路已绑定，请勿重复操作")

        # 检查线路权限
        has_permission, error_msg = check_line_permission(is_premium, line)
        if not has_permission:
            return BaseResponse(success=False, message=error_msg)

        success = lines_service.set_emby_line(line, tg_id=tg_id)

        if not success:
            logger.error(f"设置用户 {get_user_name_from_tg_id(tg_id)} 的 Emby 线路失败")
            return BaseResponse(success=False, message="设置线路失败")

        # 更新 redis 缓存
        binded_line = emby_user_defined_line_cache.get(str(emby_username).lower())
        if binded_line and not is_binded_premium_line(
            binded_line, catalog.premium_lines()
        ):
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
        return BaseResponse(
            success=True, message=f"绑定线路 {line} 成功！请重新播放以应用线路变更"
        )

    except Exception as e:
        logger.error(f"绑定Emby线路时发生错误: {e!s}")
        return BaseResponse(success=False, message=f"绑定失败: {e!s}")


@router.post("/unbind/emby_line", response_model=BaseResponse)
@require_telegram_auth
async def unbind_emby_line(
    request: Request,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """解绑Emby线路（恢复自动选择）"""
    tg_id = telegram_user.id

    logger.info(f"用户 {get_user_name_from_tg_id(tg_id)} 尝试解绑 Emby 线路")

    try:
        # 检查用户是否绑定了Emby账户
        emby_info = lines_service.get_user_emby_info(tg_id)
        if not emby_info:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 未绑定Emby账户")
            return BaseResponse(success=False, message="您尚未绑定 Emby 账户，请先绑定")
        emby_username, emby_line = emby_info[0], emby_info[7]
        if not emby_line:
            logger.warning(
                f"用户 {get_user_name_from_tg_id(tg_id)} 未绑定线路，无需解绑"
            )
            return BaseResponse(success=False, message="您未绑定线路，无需解绑")

        success = lines_service.set_emby_line(None, tg_id=tg_id)
        if not success:
            logger.error(f"重置用户 {get_user_name_from_tg_id(tg_id)} 的 Emby 线路失败")
            return BaseResponse(success=False, message="重置线路失败")
        from app.domains.lines.gateway_cache import emby_user_defined_line_cache

        # 删除 redis 缓存
        emby_user_defined_line_cache.delete(str(emby_username).lower())

        logger.info(f"用户 {get_user_name_from_tg_id(tg_id)} 成功解绑 Emby 线路")
        return BaseResponse(success=True, message="已切换到自动选择线路")

    except Exception as e:
        logger.error(f"解绑 Emby 线路时发生错误: {e!s}")
        return BaseResponse(success=False, message=f"解绑失败: {e!s}")


@router.get("/plex_lines", response_model=PlexLinesResponse)
@require_telegram_auth
async def get_plex_lines(
    request: Request,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """获取可用的Plex线路列表"""

    try:
        # 获取 plex 用户信息，确认是否绑定
        plex_info = lines_service.get_user_plex_info(telegram_user.id)
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
        available_lines = catalog.normal_lines().copy()
        premium_lines = catalog.premium_lines().copy()
        line_infos = []

        # 添加基础线路信息
        for line in available_lines:
            line_infos.append(
                PlexLineInfo(
                    name=line,
                    tags=catalog.line_tags(line),
                    is_premium=False,
                )
            )

        # 根据用户权限添加高级线路信息
        if is_premium_user:
            # 高级用户可以看到所有高级线路
            for line in premium_lines:
                line_infos.append(
                    PlexLineInfo(
                        name=line,
                        tags=catalog.line_tags(line),
                        is_premium=True,
                    )
                )
        elif lines_service.is_premium_free_enabled():
            # 普通用户在免费开放期间可以看到免费的高级线路
            free_premium_lines = catalog.free_premium_lines()

            for line in free_premium_lines:
                if line in premium_lines:
                    line_infos.append(
                        PlexLineInfo(
                            name=line,
                            tags=catalog.line_tags(line),
                            is_premium=True,
                        )
                    )

        return PlexLinesResponse(
            lines=line_infos, success=True, message="获取 Plex 线路列表成功"
        )
    except Exception as e:
        logger.error(f"获取 Plex 线路列表时发生错误: {e!s}")
        return PlexLinesResponse(
            success=False, message="获取 Plex 线路列表失败", lines=[]
        )


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

    try:
        # 检查用户是否绑定了Plex账户
        plex_info = lines_service.get_user_plex_info(tg_id)
        if not plex_info:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 未绑定 Plex 账户")
            return BaseResponse(success=False, message="您尚未绑定Plex账户，请先绑定")

        plex_username, plex_line = plex_info[4], plex_info[8]
        is_premium = plex_info[9] == 1

        # 可能存在 plex 用户信息还没更新的情况
        if not plex_username:
            logger.error(f"用户 {get_user_name_from_tg_id(tg_id)} 的 Plex 用户名为空")
            return BaseResponse(
                success=False, message="Plex 用户信息异常，暂时无法绑定线路"
            )
        if plex_line == line:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 已绑定该线路")
            return BaseResponse(success=False, message="该线路已绑定，请勿重复操作")

        # 检查线路权限
        has_permission, error_msg = check_line_permission(is_premium, line)
        if not has_permission:
            return BaseResponse(success=False, message=error_msg)

        success = lines_service.set_plex_line(line, tg_id=tg_id)
        if not success:
            logger.error(f"设置用户 {get_user_name_from_tg_id(tg_id)} 的 Plex 线路失败")
            return BaseResponse(success=False, message="设置线路失败")

        # 更新 redis 缓存
        binded_line = plex_user_defined_line_cache.get(str(plex_username).lower())
        if binded_line and not is_binded_premium_line(
            binded_line, catalog.premium_lines()
        ):
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
        return BaseResponse(
            success=True, message=f"绑定线路 {line} 成功！请重新播放以应用线路变更"
        )

    except Exception as e:
        logger.error(f"绑定 Plex 线路时发生错误: {e!s}")
        return BaseResponse(success=False, message=f"绑定失败: {e!s}")


@router.post("/unbind/plex_line", response_model=BaseResponse)
@require_telegram_auth
async def unbind_plex_line(
    request: Request,
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """解绑Plex线路（恢复自动选择）"""
    tg_id = telegram_user.id

    logger.info(f"用户 {get_user_name_from_tg_id(tg_id)} 尝试解绑 Plex 线路")

    try:
        # 检查用户是否绑定了Plex账户
        plex_info = lines_service.get_user_plex_info(tg_id)
        if not plex_info:
            logger.warning(f"用户 {get_user_name_from_tg_id(tg_id)} 未绑定Plex账户")
            return BaseResponse(success=False, message="您尚未绑定 Plex 账户，请先绑定")

        plex_username, plex_line = plex_info[4], plex_info[8]
        if not plex_line:
            logger.warning(
                f"用户 {get_user_name_from_tg_id(tg_id)} 未绑定线路，无需解绑"
            )
            return BaseResponse(success=False, message="您未绑定线路，无需解绑")

        success = lines_service.set_plex_line(None, tg_id=tg_id)
        if not success:
            logger.error(f"重置用户 {tg_id} 的 Plex 线路失败")
            return BaseResponse(success=False, message="重置线路失败")

        # 删除 redis 缓存
        plex_user_defined_line_cache.delete(str(plex_username).lower())

        logger.info(f"用户 {get_user_name_from_tg_id(tg_id)} 成功解绑 Plex 线路")
        return BaseResponse(success=True, message="已切换到自动选择线路")

    except Exception as e:
        logger.error(f"解绑 Plex 线路时发生错误: {e!s}")
        return BaseResponse(success=False, message=f"解绑失败: {e!s}")


@router.get("/lines/{service}")
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

    try:
        if service == "emby":
            if password is None:
                return BaseResponse(success=False, message="Emby 认证需要密码")
            success, message = await _auth_bind_emby_line(
                tg_id, username, password, line
            )
        else:
            success, message = await _auth_bind_plex_line(
                tg_id, username, line, token=token, password=password
            )
        return BaseResponse(success=success, message=message)
    except Exception as e:
        logger.error(f"认证绑定{service}线路时发生错误: {e!s}")
        return BaseResponse(success=False, message=f"认证绑定失败: {e!s}")


@router.post("/lines/emby/available", response_model=EmbyLinesResponse)
@require_telegram_auth
async def get_emby_lines_by_user(
    request: Request,
    data: dict = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """基于用户名获取可用的Emby线路列表（无需认证，仅查询数据库中的用户信息）"""
    username = data.get("username")

    if not username:
        return EmbyLinesResponse(success=False, message="用户名不能为空", lines=[])

    try:
        # 直接从数据库查询用户信息，无需进行Emby服务器认证
        emby_info = lines_service.get_emby_info_by_username(username)
        is_self = bool(emby_info and emby_info[2] == telegram_user.id)
        is_premium = bool(emby_info and is_self and emby_info[8] == 1)
        if not is_self:
            is_premium = True

        # 基础线路
        available_lines = catalog.normal_lines().copy()
        line_infos = []

        # 添加基础线路信息
        for line in available_lines:
            line_infos.append(
                EmbyLineInfo(
                    name=line,
                    tags=catalog.line_tags(line),
                    is_premium=False,
                )
            )

        # 如果是premium用户,直接添加所有高级线路
        if is_premium:
            for line in catalog.premium_lines():
                line_infos.append(
                    EmbyLineInfo(
                        name=line,
                        tags=catalog.line_tags(line),
                        is_premium=True,
                    )
                )
        # 如果不是premium用户,检查免费高级线路
        elif lines_service.is_premium_free_enabled():
            # 从数据库获取免费高级线路列表
            free_premium_lines = catalog.free_premium_lines()

            for line in free_premium_lines:
                if line in catalog.premium_lines():
                    line_infos.append(
                        EmbyLineInfo(
                            name=line,
                            tags=catalog.line_tags(line),
                            is_premium=True,
                        )
                    )

        logger.info(f"为 Emby 用户 {username} 返回 {len(line_infos)} 条线路信息")
        return EmbyLinesResponse(
            success=True, lines=line_infos, message="获取线路列表成功"
        )

    except Exception as e:
        logger.error(f"获取 Emby 用户 {username} 的线路列表时发生错误: {e!s}")
        return EmbyLinesResponse(
            success=False, message="获取线路列表失败，请稍后再试", lines=[]
        )


@router.post("/lines/plex/available", response_model=PlexLinesResponse)
@require_telegram_auth
async def get_plex_lines_by_user(
    request: Request,
    data: dict = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """基于邮箱获取可用的Plex线路列表（无需认证，仅查询数据库中的用户信息）"""
    email = data.get("email")

    if not email:
        return PlexLinesResponse(success=False, message="邮箱不能为空", lines=[])

    try:
        # 直接从数据库查询用户信息，无需进行Plex服务器认证
        plex_info = lines_service.get_plex_info_by_email(email)
        is_self = bool(plex_info and plex_info[1] == telegram_user.id)
        # 预览他人账号时返回完整目录；查询自己时保留会员过滤。
        is_premium_user = bool(plex_info and is_self and plex_info[9] == 1)
        if not is_self:
            is_premium_user = True

        # 获取基础线路和高级线路
        available_lines = catalog.normal_lines().copy()
        premium_lines = catalog.premium_lines().copy()
        line_infos = []

        # 添加基础线路信息
        for line in available_lines:
            line_infos.append(
                PlexLineInfo(
                    name=line,
                    tags=catalog.line_tags(line),
                    is_premium=False,
                )
            )

        # 根据用户权限添加高级线路信息
        if is_premium_user:
            # 高级用户可以看到所有高级线路
            for line in premium_lines:
                line_infos.append(
                    PlexLineInfo(
                        name=line,
                        tags=catalog.line_tags(line),
                        is_premium=True,
                    )
                )
        elif lines_service.is_premium_free_enabled():
            # 普通用户在免费开放期间可以看到免费的高级线路
            free_premium_lines = catalog.free_premium_lines()

            for line in free_premium_lines:
                if line in premium_lines:
                    line_infos.append(
                        PlexLineInfo(
                            name=line,
                            tags=catalog.line_tags(line),
                            is_premium=True,
                        )
                    )

        logger.info(f"为 Plex 用户 {email} 返回 {len(line_infos)} 条线路信息")
        return PlexLinesResponse(
            success=True, lines=line_infos, message="获取线路列表成功"
        )

    except Exception as e:
        logger.error(f"获取 Plex 用户 {email} 的线路列表时发生错误: {e!s}")
        return PlexLinesResponse(
            success=False, message="获取线路列表失败，请稍后再试", lines=[]
        )


@router.post("/lines/{service}/current", response_model=CurrentLineResponse)
@require_telegram_auth
async def get_current_bound_line(
    service: str,
    request: Request,
    data: dict = Body(...),
    telegram_user: TelegramUser = Depends(get_telegram_user),
):
    """获取用户当前绑定的线路信息（基于用户名/邮箱）"""
    if service not in ["emby", "plex"]:
        raise HTTPException(status_code=400, detail="服务类型必须是 'emby' 或 'plex'")

    try:
        if service == "emby":
            username = data.get("username")
            if not username:
                return CurrentLineResponse(success=False, message="用户名不能为空")

            # 查询Emby用户信息
            emby_info = lines_service.get_emby_info_by_username(username)
            if not emby_info or emby_info[2] != telegram_user.id:
                return CurrentLineResponse(
                    success=True, line=None, message=f"用户 {username} 未绑定任何线路"
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
            plex_info = lines_service.get_plex_info_by_email(email)
            if not plex_info or plex_info[1] != telegram_user.id:
                return CurrentLineResponse(
                    success=True, line=None, message=f"用户 {email} 未绑定任何线路"
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
        logger.error(f"获取用户当前绑定线路时发生错误: {e!s}")
        return CurrentLineResponse(
            success=False, message="获取当前绑定线路失败，请稍后再试"
        )


@router.get("/line-schedules/unlock-status/{service}")
@require_telegram_auth
async def check_line_schedule_unlock_status(
    service: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """检查用户是否解锁了线路调度功能"""
    if service not in ["emby", "plex"]:
        raise HTTPException(status_code=400, detail="服务类型必须是 'emby' 或 'plex'")

    try:
        result = lines_service.check_line_schedule_unlock(user.id, service)
        return {
            "success": True,
            "is_unlocked": result["is_unlocked"],
            "is_premium": result["is_premium"],
            "unlock_time": result["unlock_time"],
            "unlock_credits": lines_service.get_line_schedule_unlock_credits(),
        }
    except Exception as e:
        logger.error(f"检查线路调度解锁状态失败: {e}")
        raise HTTPException(status_code=500, detail="检查解锁状态失败")


@router.post("/line-schedules/unlock", response_model=LineScheduleUnlockResponse)
@require_telegram_auth
async def unlock_line_schedule(
    request: Request,
    background_tasks: BackgroundTasks,
    data: LineScheduleUnlockRequest,
    user: TelegramUser = Depends(get_telegram_user),
):
    """解锁线路调度功能（消耗积分）"""
    service = data.service
    if service not in ["emby", "plex"]:
        return LineScheduleUnlockResponse(
            success=False, message="服务类型必须是 'emby' 或 'plex'"
        )

    try:
        # 检查是否已经解锁
        unlock_status = lines_service.check_line_schedule_unlock(user.id, service)
        if unlock_status["is_unlocked"]:
            return LineScheduleUnlockResponse(
                success=True,
                message="您已经解锁了线路调度功能"
                if unlock_status["is_premium"]
                else "线路调度功能已解锁",
            )

        # 解锁线路调度功能并在同一事务中扣除积分
        success, message, credits_needed, new_credits = (
            lines_service.unlock_line_schedule_flow(user.id, service)
        )
        if not success:
            return LineScheduleUnlockResponse(success=False, message=message)

        logger.info(
            f"用户 {get_user_name_from_tg_id(user.id)} 消耗 {credits_needed} 积分解锁 {service} 线路调度功能"
        )

        service_name, service_emoji = lines_service.get_service_label(service)
        user_name = get_user_name_from_tg_id(user.id)
        background_tasks.add_task(
            lines_notifications.notify_schedule_unlocked,
            f"""🗓️ 线路调度解锁通知

👤 用户: {user_name}（TG ID: {user.id}）
{service_emoji} 服务: {service_name}
💎 花费: {credits_needed} 积分
💰 剩余: {new_credits:.2f} 积分""",
        )

        return LineScheduleUnlockResponse(success=True, message=message)

    except Exception as e:
        logger.error(f"解锁线路调度功能失败: {e}")
        return LineScheduleUnlockResponse(success=False, message="解锁失败")


@router.get("/line-schedules/{service}", response_model=LineScheduleListResponse)
@require_telegram_auth
async def get_line_schedules(
    service: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取用户的线路调度列表"""
    if service not in ["emby", "plex"]:
        raise HTTPException(status_code=400, detail="服务类型必须是 'emby' 或 'plex'")

    try:
        schedules = lines_service.get_user_line_schedules(user.id, service)
        return LineScheduleListResponse(
            success=True,
            schedules=[LineScheduleInfo(**schedule) for schedule in schedules],
        )
    except Exception as e:
        logger.error(f"获取线路调度列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取线路调度列表失败")


@router.post("/line-schedules", response_model=BaseResponse)
@require_telegram_auth
async def create_line_schedule(
    request: Request,
    data: LineScheduleCreate,
    user: TelegramUser = Depends(get_telegram_user),
):
    """创建线路调度"""
    service = data.service
    if service not in ["emby", "plex"]:
        return BaseResponse(success=False, message="服务类型必须是 'emby' 或 'plex'")

    try:
        # 检查是否解锁
        unlock_status = lines_service.check_line_schedule_unlock(user.id, service)
        if not unlock_status["is_unlocked"]:
            return BaseResponse(success=False, message="请先解锁线路调度功能")

        # 获取用户信息并检查线路权限
        user_info = lines_service.get_line_schedule_account(user.id, service)
        if not user_info:
            account_name = "Emby" if service == "emby" else "Plex"
            return BaseResponse(
                success=False, message=f"您尚未绑定 {account_name} 账户"
            )
        is_premium = user_info["is_premium"]

        has_permission, error_msg = check_line_permission(is_premium, data.line)
        if not has_permission:
            return BaseResponse(success=False, message=f"{error_msg}，无法创建调度")

        # 创建调度
        schedule_id = lines_service.create_line_schedule(
            user.id,
            service,
            data.line,
            data.days_of_week,
            data.start_time,
            data.end_time,
            data.priority,
        )

        if schedule_id:
            # 创建成功后立即执行一次调度检查
            asyncio.create_task(auto_switch_user_lines(tg_id=user.id, service=service))
            return BaseResponse(success=True, message="创建线路调度成功")
        else:
            return BaseResponse(success=False, message="创建线路调度失败")

    except Exception as e:
        logger.error(f"创建线路调度失败: {e}")
        return BaseResponse(success=False, message="创建线路调度失败")


@router.put("/line-schedules/{schedule_id}", response_model=BaseResponse)
@require_telegram_auth
async def update_line_schedule(
    schedule_id: int,
    request: Request,
    data: LineScheduleUpdate,
    user: TelegramUser = Depends(get_telegram_user),
):
    """更新线路调度"""
    try:
        # 获取原有调度信息
        schedules = lines_service.get_user_line_schedules(user.id)
        schedule = next((s for s in schedules if s["id"] == schedule_id), None)
        if not schedule:
            return BaseResponse(success=False, message="调度不存在")

        # 构建更新参数
        update_kwargs = {}
        if data.line is not None:
            update_kwargs["line"] = data.line

            # 如果修改了线路，检查用户是否有权使用该线路
            service = schedule["service"]

            # 获取用户信息并检查线路权限
            user_info = lines_service.get_line_schedule_account(user.id, service)
            if not user_info:
                account_name = "Emby" if service == "emby" else "Plex"
                return BaseResponse(
                    success=False, message=f"您尚未绑定 {account_name} 账户"
                )
            is_premium = user_info["is_premium"]

            has_permission, error_msg = check_line_permission(is_premium, data.line)
            if not has_permission:
                return BaseResponse(success=False, message=f"{error_msg}，无法更新调度")

        if data.days_of_week is not None:
            update_kwargs["days_of_week"] = data.days_of_week
        if data.start_time is not None:
            update_kwargs["start_time"] = data.start_time
        if data.end_time is not None:
            update_kwargs["end_time"] = data.end_time
        if data.priority is not None:
            update_kwargs["priority"] = data.priority
        if data.is_enabled is not None:
            update_kwargs["is_enabled"] = data.is_enabled

        # 执行更新
        if lines_service.update_line_schedule(schedule_id, user.id, **update_kwargs):
            # 更新成功后立即执行一次调度检查
            asyncio.create_task(
                auto_switch_user_lines(tg_id=user.id, service=schedule["service"])
            )
            return BaseResponse(success=True, message="更新线路调度成功")
        else:
            return BaseResponse(success=False, message="更新线路调度失败")

    except Exception as e:
        logger.error(f"更新线路调度失败: {e}")
        return BaseResponse(success=False, message="更新线路调度失败")


@router.delete("/line-schedules/{schedule_id}", response_model=BaseResponse)
@require_telegram_auth
async def delete_line_schedule(
    schedule_id: int,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """删除线路调度"""
    try:
        if lines_service.delete_line_schedule(schedule_id, user.id):
            return BaseResponse(success=True, message="删除线路调度成功")
        else:
            return BaseResponse(success=False, message="删除线路调度失败或无权限")
    except Exception as e:
        logger.error(f"删除线路调度失败: {e}")
        return BaseResponse(success=False, message="删除线路调度失败")


@router.get(
    "/line-schedules/status/{service}", response_model=LineScheduleStatusResponse
)
@require_telegram_auth
async def get_line_schedule_status(
    service: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取当前生效的线路调度状态"""
    if service not in ["emby", "plex"]:
        raise HTTPException(status_code=400, detail="服务类型必须是 'emby' 或 'plex'")

    try:
        # 检查是否解锁
        unlock_status = lines_service.check_line_schedule_unlock(user.id, service)

        # 获取当前生效的调度
        active_schedule = None
        if unlock_status["is_unlocked"]:
            active_schedule = lines_service.get_current_active_schedule(
                user.id, service
            )

        # 检查是否有调度
        schedules = lines_service.get_user_line_schedules(user.id, service)
        has_schedules = len(schedules) > 0

        return LineScheduleStatusResponse(
            success=True,
            is_unlocked=unlock_status["is_unlocked"],
            is_premium=unlock_status.get("is_premium", False),
            has_schedules=has_schedules,
            current_schedule=(
                LineScheduleInfo(**active_schedule) if active_schedule else None
            ),
        )

    except Exception as e:
        logger.error(f"获取线路调度状态失败: {e}")
        raise HTTPException(status_code=500, detail="获取线路调度状态失败")
