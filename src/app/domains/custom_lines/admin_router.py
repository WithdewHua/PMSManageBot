from fastapi import APIRouter, BackgroundTasks, Body, Depends, Request

from app.core.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.core.schemas import TelegramUser
from app.core.telegram import get_user_name_from_tg_id, send_message_by_url
from app.domains.lines.service import unbind_specified_line_for_all_users

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/custom-lines")
@require_telegram_auth
async def get_all_custom_lines(
    request: Request,
    status: str | None = None,
    user: TelegramUser = Depends(get_telegram_user),
):
    """管理员获取所有自定义线路列表（可按状态过滤）"""
    check_admin_permission(user)

    try:
        import json

        from sqlalchemy import select

        from app.core.db import get_session
        from app.domains.custom_lines.models import CustomLine
        from app.domains.profile.schemas import CustomLineInfo, CustomLineListResponse

        with get_session() as session:
            stmt = select(CustomLine)

            # 按状态过滤
            if status:
                if status not in ["pending", "approved", "rejected", "expired"]:
                    return CustomLineListResponse(
                        success=False, message="无效的状态", lines=[], total=0
                    )
                stmt = stmt.where(CustomLine.status == status)

            stmt = stmt.order_by(CustomLine.created_at.desc())
            result = session.execute(stmt)
            lines = result.scalars().all()

            lines_data = [
                CustomLineInfo(
                    id=line.id,
                    tg_id=line.tg_id,
                    domain=line.domain,
                    network_info=line.network_info,
                    price_monthly=line.price_monthly,
                    price_yearly=line.price_yearly,
                    traffic_limit=line.traffic_limit,
                    traffic_type=line.traffic_type,
                    valid_days=line.valid_days,
                    is_permanent=bool(line.is_permanent),
                    status=line.status,
                    admin_note=line.admin_note,
                    user_note=line.user_note,
                    tags=(
                        json.loads(line.tags)
                        if isinstance(line.tags, str) and line.tags
                        else (line.tags or [])
                    ),
                    approved_at=line.approved_at,
                    approved_by=line.approved_by,
                    expires_at=line.expires_at,
                    created_at=line.created_at,
                    updated_at=line.updated_at,
                    total_traffic=line.total_traffic,
                )
                for line in lines
            ]

            return CustomLineListResponse(
                success=True,
                message="获取成功",
                lines=lines_data,
                total=len(lines_data),
            )

    except Exception as e:
        logger.error(f"获取自定义线路列表失败: {e}")
        from app.domains.profile.schemas import CustomLineListResponse

        return CustomLineListResponse(
            success=False, message=f"获取失败: {e!s}", lines=[], total=0
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
    """管理员审批自定义线路（批准或拒绝）"""
    check_admin_permission(user)

    try:
        from time import time

        from sqlalchemy import select

        from app.core.db import get_session
        from app.core.schemas import BaseResponse
        from app.domains.custom_lines.models import CustomLine
        from app.domains.profile.schemas import CustomLineApproveRequest

        # 解析请求数据
        approve_req = CustomLineApproveRequest(**data)

        if approve_req.action not in ["approve", "reject"]:
            return BaseResponse(success=False, message="无效的操作")

        admin_id = user.id
        current_time = int(time())

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            # 只能审批 pending 状态的线路
            if line.status != "pending":
                return BaseResponse(
                    success=False,
                    message=f"只能审批待审核的线路，当前状态: {line.status}",
                )

            domain = line.domain
            submitter_id = line.tg_id
            submitter_name = get_user_name_from_tg_id(submitter_id)

            if approve_req.action == "approve":
                line.status = "approved"
                line.approved_at = current_time
                line.approved_by = admin_id

                # 管理员可以覆盖用户提交的有效期设置
                if approve_req.is_permanent is not None:
                    line.is_permanent = 1 if approve_req.is_permanent else 0
                if approve_req.valid_days is not None:
                    line.valid_days = approve_req.valid_days

                # 重新计算过期时间
                if line.is_permanent:
                    line.expires_at = None
                elif line.valid_days:
                    line.expires_at = current_time + (line.valid_days * 24 * 60 * 60)

                if approve_req.admin_note:
                    line.admin_note = approve_req.admin_note

                line.updated_at = current_time

                session.commit()

                logger.info(
                    f"管理员 {user.username or user.id} 批准了用户 {submitter_name} 的自定义线路: {domain}"
                )

                # 通知用户
                traffic_info = (
                    f"{line.traffic_limit} GB" if line.traffic_limit else "无限制"
                )

                user_notification = f"""✅ 您的自定义线路已通过审核

🌐 域名: {line.domain}
📊 流量限制: {traffic_info}
⏰ 有效期: {"长期可用" if line.is_permanent else f"{line.valid_days}天"}
"""
                if approve_req.admin_note:
                    user_notification += f"\n📝 管理员备注: {approve_req.admin_note}"

                background_tasks.add_task(
                    send_message_by_url,
                    chat_id=submitter_id,
                    text=user_notification,
                )

                # 发送频道通知，让其他用户知晓新线路
                if settings.TG_CHANNEL_ID:
                    channel_notification = f"""🎉 新线路上线通知

🌐 线路: {line.domain}
🌍 网络信息: {line.network_info or "未提供"}
📊 流量限制: {traffic_info}
⏰ 有效期: {"长期可用" if line.is_permanent else f"{line.valid_days} 天"}

感谢 {submitter_name} 分享线路！"""

                    background_tasks.add_task(
                        send_message_by_url,
                        chat_id=settings.TG_CHANNEL_ID,
                        text=channel_notification,
                    )

                return BaseResponse(success=True, message=f"已批准线路: {domain}")

            else:  # reject
                line.status = "rejected"
                if approve_req.admin_note:
                    line.admin_note = approve_req.admin_note
                line.updated_at = current_time

                session.commit()

                logger.info(
                    f"管理员 {user.username or user.id} 拒绝了用户 {submitter_name} 的自定义线路: {domain}"
                )

                # 通知用户
                user_notification = f"""❌ 您的自定义线路未通过审核

🌐 域名: {line.domain}
"""
                if approve_req.admin_note:
                    user_notification += f"\n📝 拒绝原因: {approve_req.admin_note}"

                background_tasks.add_task(
                    send_message_by_url,
                    chat_id=submitter_id,
                    text=user_notification,
                )

                return BaseResponse(success=True, message=f"已拒绝线路: {domain}")

    except Exception as e:
        logger.error(f"审批自定义线路失败: {e}")
        from app.core.schemas import BaseResponse

        return BaseResponse(success=False, message=f"审批失败: {e!s}")


@router.put("/custom-lines/{line_id}")
@require_telegram_auth
async def admin_update_custom_line(
    request: Request,
    line_id: int,
    data: dict = Body(...),
    user: TelegramUser = Depends(get_telegram_user),
):
    """管理员更新自定义线路"""
    check_admin_permission(user)

    try:
        from time import time

        from sqlalchemy import select

        from app.core.db import get_session
        from app.core.schemas import BaseResponse
        from app.domains.custom_lines.models import CustomLine
        from app.domains.profile.schemas import AdminCustomLineUpdateRequest

        # 解析请求数据
        update_req = AdminCustomLineUpdateRequest(**data)

        current_time = int(time())

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            # 更新字段
            if update_req.domain is not None:
                # 检查新域名是否已被使用（pending、approved 或 offline 状态）
                stmt_check = select(CustomLine).where(
                    CustomLine.domain == update_req.domain,
                    CustomLine.id != line_id,
                    CustomLine.status.in_(["pending", "approved", "offline"]),
                )
                result_check = session.execute(stmt_check)
                if result_check.scalar_one_or_none():
                    return BaseResponse(
                        success=False, message=f"域名 '{update_req.domain}' 已被使用"
                    )
                line.domain = update_req.domain
            if update_req.network_info is not None:
                line.network_info = update_req.network_info
            if update_req.price_monthly is not None:
                line.price_monthly = update_req.price_monthly
            if update_req.price_yearly is not None:
                line.price_yearly = update_req.price_yearly
            if update_req.traffic_limit is not None:
                line.traffic_limit = update_req.traffic_limit
            if update_req.traffic_type is not None:
                if update_req.traffic_type not in ["one_way", "two_way"]:
                    return BaseResponse(success=False, message="无效的流量类型")
                line.traffic_type = update_req.traffic_type
            if update_req.total_traffic is not None:
                line.total_traffic = update_req.total_traffic
            if update_req.valid_days is not None:
                line.valid_days = update_req.valid_days
            if update_req.is_permanent is not None:
                line.is_permanent = 1 if update_req.is_permanent else 0
            if update_req.admin_note is not None:
                line.admin_note = update_req.admin_note
            if update_req.status is not None:
                if update_req.status not in [
                    "pending",
                    "approved",
                    "rejected",
                    "expired",
                ]:
                    return BaseResponse(success=False, message="无效的状态")
                line.status = update_req.status

            # 重新计算过期时间
            if update_req.is_permanent is not None or update_req.valid_days is not None:
                if line.is_permanent:
                    line.expires_at = None
                elif line.valid_days:
                    # 如果线路已批准，从批准时间开始计算
                    base_time = line.approved_at if line.approved_at else current_time
                    line.expires_at = base_time + (line.valid_days * 24 * 60 * 60)

            line.updated_at = current_time

            session.commit()

            logger.info(
                f"管理员 {user.username or user.id} 更新了自定义线路: {line.domain}"
            )

            return BaseResponse(success=True, message="更新成功")

    except Exception as e:
        logger.error(f"管理员更新自定义线路失败: {e}")
        from app.core.schemas import BaseResponse

        return BaseResponse(success=False, message=f"更新失败: {e!s}")


@router.post("/custom-lines/{line_id}/offline")
@require_telegram_auth
async def admin_offline_custom_line(
    request: Request,
    line_id: int,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    """管理员下线自定义线路"""
    check_admin_permission(user)

    try:
        from time import time

        from sqlalchemy import select

        from app.core.db import get_session
        from app.core.schemas import BaseResponse
        from app.domains.custom_lines.models import CustomLine

        current_time = int(time())

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            # 只能下线已批准的线路
            if line.status != "approved":
                return BaseResponse(
                    success=False,
                    message=f"只能下线已批准的线路，当前状态: {line.status}",
                )

            domain = line.domain
            submitter_id = line.tg_id
            submitter_name = get_user_name_from_tg_id(submitter_id)

            # 解绑所有使用该线路的用户
            logger.info(f"管理员下线线路 {domain}，开始解绑所有用户")
            try:
                success, unbind_count = await unbind_specified_line_for_all_users(
                    domain, "已被管理员下线"
                )
                if success and unbind_count > 0:
                    logger.info(f"已解绑 {unbind_count} 个用户的线路 {domain}")
            except Exception as e:
                logger.error(f"解绑用户失败: {e}")

            # 更新状态为 offline
            line.status = "offline"
            line.updated_at = current_time

            session.commit()

            logger.info(
                f"管理员 {user.username or user.id} 下线了用户 {submitter_name} 的自定义线路: {domain}"
            )

            # 通知用户
            user_notification = f"""📢 您的自定义线路已被管理员下线

🌐 域名: {line.domain}

您可以随时重新上线该线路。
如有疑问，请联系管理员。"""

            background_tasks.add_task(
                send_message_by_url,
                chat_id=submitter_id,
                text=user_notification,
            )

            return BaseResponse(success=True, message=f"已下线线路: {domain}")

    except Exception as e:
        logger.error(f"管理员下线自定义线路失败: {e}")
        from app.core.schemas import BaseResponse

        return BaseResponse(success=False, message=f"下线失败: {e!s}")


@router.delete("/custom-lines/{line_id}")
@require_telegram_auth
async def admin_delete_custom_line(
    request: Request,
    line_id: int,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    """管理员删除自定义线路（从数据库中删除，可删除任何状态的线路）"""
    check_admin_permission(user)

    try:
        from sqlalchemy import select

        from app.core.db import get_session
        from app.core.schemas import BaseResponse
        from app.domains.custom_lines.models import CustomLine
        from app.domains.custom_lines.service import settle_custom_line_traffic

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            domain = line.domain
            submitter_id = line.tg_id
            submitter_name = get_user_name_from_tg_id(submitter_id)
            line_status = line.status

            # 如果线路已批准，先解绑所有用户
            if line_status == "approved":
                logger.info(f"线路 {domain} 状态为 {line_status}，开始解绑所有用户")
                try:
                    success, unbind_count = await unbind_specified_line_for_all_users(
                        domain, "已被管理员删除"
                    )
                    if success and unbind_count > 0:
                        logger.info(f"已解绑 {unbind_count} 个用户的线路 {domain}")
                except Exception as e:
                    logger.error(f"解绑用户失败: {e}")

            # 立即结算当月流量积分
            logger.info(f"开始为删除的线路 {domain} 结算当月流量积分")
            try:
                await settle_custom_line_traffic(
                    line_domain=domain, force_current_month=True
                )
                logger.info(f"线路 {domain} 当月流量结算完成")
            except Exception as e:
                logger.error(f"结算线路 {domain} 流量失败: {e}")

            session.delete(line)
            session.commit()

            logger.info(
                f"管理员 {user.username or user.id} 删除了用户 {submitter_name} 的自定义线路: {domain} (原状态: {line_status})"
            )

            # 通知用户
            user_notification = f"""⚠️ 您的自定义线路已被管理员删除

🌐 域名: {line.domain}

如有疑问，请联系管理员。"""

            background_tasks.add_task(
                send_message_by_url,
                chat_id=submitter_id,
                text=user_notification,
            )

            return BaseResponse(success=True, message=f"已删除线路: {domain}")

    except Exception as e:
        logger.error(f"管理员删除自定义线路失败: {e}")
        from app.core.schemas import BaseResponse

        return BaseResponse(success=False, message=f"删除失败: {e!s}")


@router.post("/custom-lines/{line_id}/tags")
@require_telegram_auth
async def admin_set_custom_line_tags(
    request: Request,
    line_id: int,
    tags: list[str],
    user: TelegramUser = Depends(get_telegram_user),
):
    """管理员设置自定义线路的标签"""
    check_admin_permission(user)

    try:
        from datetime import datetime

        from sqlalchemy import select

        from app.core.db import get_session
        from app.core.schemas import BaseResponse
        from app.domains.custom_lines.models import CustomLine

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            # 更新标签
            line.tags = tags if tags else []
            line.updated_at = int(datetime.now(settings.TZ).timestamp())

            session.commit()

            logger.info(
                f"管理员 {user.username or user.id} 为自定义线路 {line.domain} 设置标签: {tags}"
            )

            return BaseResponse(
                success=True, message="已更新线路标签", data={"tags": tags}
            )

    except Exception as e:
        logger.error(f"管理员设置自定义线路标签失败: {e}")
        from app.core.schemas import BaseResponse

        return BaseResponse(success=False, message=f"设置标签失败: {e!s}")
