from time import time

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import select

from app.core.auth import get_telegram_user, require_telegram_auth
from app.core.config import settings
from app.core.db import get_session
from app.core.log import uvicorn_logger as logger
from app.core.schemas import BaseResponse, TelegramUser
from app.domains.custom_lines.models import CustomLine
from app.domains.profile.schemas import (
    CustomLineDetailResponse,
    CustomLineInfo,
    CustomLineListResponse,
    CustomLineOnlineRequest,
    CustomLineRenewRequest,
    CustomLineSubmitRequest,
    CustomLineUpdateRequest,
)
from app.utils.utils import (
    get_user_name_from_tg_id,
    send_message_by_url,
)

router = APIRouter(prefix="/api/user", tags=["user"])


@router.post("/custom-lines/submit")
@require_telegram_auth
async def submit_custom_line(
    request: Request,
    background_tasks: BackgroundTasks,
    data: CustomLineSubmitRequest,
    user: TelegramUser = Depends(get_telegram_user),
):
    """用户提交自定义线路"""
    try:
        tg_id = user.id
        current_time = int(time())

        # 验证流量类型
        if data.traffic_type not in ["one_way", "two_way"]:
            return BaseResponse(success=False, message="无效的流量类型")

        # 验证分享限制不能大于总流量
        if (
            data.traffic_limit is not None
            and data.total_traffic is not None
            and data.traffic_limit > data.total_traffic
        ):
            return BaseResponse(
                success=False,
                message=f"分享限制 ({data.traffic_limit}GB) 不能大于总流量 ({data.total_traffic}GB)",
            )

        # 检查域名是否已存在
        with get_session() as session:
            # 检查是否已有相同域名的线路（pending、approved 或 offline 状态）
            stmt = select(CustomLine).where(
                CustomLine.domain == data.domain,
                CustomLine.status.in_(["pending", "approved", "offline"]),
            )
            result = session.execute(stmt)
            existing_line = result.scalar_one_or_none()

            if existing_line:
                return BaseResponse(
                    success=False,
                    message=f"域名 '{data.domain}' 已存在，请使用其他域名",
                )

            # 计算过期时间
            expires_at = None
            if not data.is_permanent and data.valid_days:
                expires_at = current_time + (data.valid_days * 24 * 60 * 60)

            # 创建新的自定义线路
            new_line = CustomLine(
                tg_id=tg_id,
                domain=data.domain,
                network_info=data.network_info,
                price_monthly=data.price_monthly,
                price_yearly=data.price_yearly,
                traffic_limit=data.traffic_limit,
                traffic_type=data.traffic_type,
                total_traffic=data.total_traffic,
                valid_days=data.valid_days,
                is_permanent=1 if data.is_permanent else 0,
                status="pending",
                user_note=data.user_note,
                expires_at=expires_at,
                created_at=current_time,
                updated_at=current_time,
            )

            session.add(new_line)
            session.commit()
            session.refresh(new_line)

            logger.info(
                f"用户 {get_user_name_from_tg_id(tg_id)} 提交自定义线路: {data.domain}"
            )

            # 发送管理员通知
            user_name = get_user_name_from_tg_id(tg_id)
            price_info = []
            if data.price_monthly:
                price_info.append(f"月付: ¥{data.price_monthly}")
            if data.price_yearly:
                price_info.append(f"年付: ¥{data.price_yearly}")
            price_str = " / ".join(price_info) if price_info else "未提供"

            traffic_parts = []
            if data.traffic_limit:
                traffic_parts.append(f"月限 {data.traffic_limit}GB")
            if data.total_traffic:
                traffic_parts.append(f"总量 {data.total_traffic}GB")
            traffic_info = (
                f"{' | '.join(traffic_parts)} ({data.traffic_type})"
                if traffic_parts
                else "未提供"
            )
            valid_info = "长期可用" if data.is_permanent else f"{data.valid_days}天"

            admin_notification = f"""🛣️ 新的自定义线路提交

👤 提交用户: {user_name} (ID: {tg_id})
🌐 域名: {data.domain}
📡 网络情况: {data.network_info}
💰 价格: {price_str}
📊 流量: {traffic_info}
⏰ 有效期: {valid_info}
📝 备注: {data.user_note or "无"}

"""

            # 异步发送通知
            for admin_id in settings.TG_ADMIN_IDS:
                background_tasks.add_task(
                    send_message_by_url,
                    chat_id=admin_id,
                    text=admin_notification,
                )

            return BaseResponse(
                success=True,
                message=f"自定义线路 '{data.domain}' 提交成功，请等待管理员审核",
            )

    except Exception as e:
        logger.error(f"提交自定义线路失败: {e}")
        return BaseResponse(success=False, message=f"提交失败: {e!s}")


@router.get("/custom-lines/my-lines")
@require_telegram_auth
async def get_my_custom_lines(
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取当前用户提交的自定义线路列表"""
    try:
        tg_id = user.id

        with get_session() as session:
            stmt = (
                select(CustomLine)
                .where(CustomLine.tg_id == tg_id)
                .order_by(CustomLine.created_at.desc())
            )
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
        logger.error(f"获取用户自定义线路失败: {e}")
        return CustomLineListResponse(
            success=False, message=f"获取失败: {e!s}", lines=[], total=0
        )


@router.get("/custom-lines/approved")
@require_telegram_auth
async def get_approved_custom_lines(
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取所有已批准的自定义线路（供所有用户使用）"""
    try:
        with get_session() as session:
            # 获取所有已批准的自定义线路
            stmt = (
                select(CustomLine)
                .where(CustomLine.status == "approved")
                .order_by(CustomLine.domain.asc())
            )
            result = session.execute(stmt)
            lines = result.scalars().all()

            # 返回简化的线路信息（仅 domain 和 tags）
            lines_data = []
            for line in lines:
                tags = ["用户分享"]
                # 如果有管理员设置的标签，也添加进来
                if line.tags:
                    try:
                        import json

                        line_tags = (
                            json.loads(line.tags)
                            if isinstance(line.tags, str)
                            else line.tags
                        )
                        if isinstance(line_tags, list):
                            tags.extend(line_tags)
                    except (json.JSONDecodeError, TypeError):
                        pass

                lines_data.append({"name": line.domain, "tags": tags})

            return {
                "success": True,
                "message": "获取成功",
                "lines": lines_data,
                "total": len(lines_data),
            }

    except Exception as e:
        logger.error(f"获取已批准自定义线路失败: {e}")
        return {
            "success": False,
            "message": f"获取失败: {e!s}",
            "lines": [],
            "total": 0,
        }


@router.get("/custom-lines/{line_id}")
@require_telegram_auth
async def get_custom_line_detail(
    request: Request,
    line_id: int,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取自定义线路详情（仅限线路所有者）"""
    try:
        tg_id = user.id

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return CustomLineDetailResponse(
                    success=False, message="线路不存在", line=None
                )

            # 检查权限：只有线路所有者可以查看
            if line.tg_id != tg_id:
                return CustomLineDetailResponse(
                    success=False, message="无权查看此线路", line=None
                )

            line_data = CustomLineInfo(
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
                approved_at=line.approved_at,
                approved_by=line.approved_by,
                expires_at=line.expires_at,
                created_at=line.created_at,
                updated_at=line.updated_at,
                total_traffic=line.total_traffic,
            )

            return CustomLineDetailResponse(
                success=True, message="获取成功", line=line_data
            )

    except Exception as e:
        logger.error(f"获取自定义线路详情失败: {e}")
        return CustomLineDetailResponse(
            success=False, message=f"获取失败: {e!s}", line=None
        )


@router.put("/custom-lines/{line_id}")
@require_telegram_auth
async def update_custom_line(
    request: Request,
    line_id: int,
    data: CustomLineUpdateRequest,
    user: TelegramUser = Depends(get_telegram_user),
):
    """更新自定义线路（仅限pending状态且为线路所有者）"""
    try:
        tg_id = user.id
        current_time = int(time())

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            # 检查权限
            if line.tg_id != tg_id:
                return BaseResponse(success=False, message="无权修改此线路")

            # 只能修改 pending 状态的线路
            if line.status != "pending":
                return BaseResponse(
                    success=False,
                    message=f"只能修改待审核的线路，当前状态: {line.status}",
                )

            # 更新字段
            if data.domain is not None:
                # 检查新域名是否已被使用（pending、approved 或 offline 状态）
                stmt_check = select(CustomLine).where(
                    CustomLine.domain == data.domain,
                    CustomLine.id != line_id,
                    CustomLine.status.in_(["pending", "approved", "offline"]),
                )
                result_check = session.execute(stmt_check)
                if result_check.scalar_one_or_none():
                    return BaseResponse(
                        success=False, message=f"域名 '{data.domain}' 已被使用"
                    )
                line.domain = data.domain
            if data.network_info is not None:
                line.network_info = data.network_info
            if data.price_monthly is not None:
                line.price_monthly = data.price_monthly
            if data.price_yearly is not None:
                line.price_yearly = data.price_yearly
            if data.traffic_limit is not None:
                line.traffic_limit = data.traffic_limit
            if data.traffic_type is not None:
                if data.traffic_type not in ["one_way", "two_way"]:
                    return BaseResponse(success=False, message="无效的流量类型")
                line.traffic_type = data.traffic_type
            if data.total_traffic is not None:
                line.total_traffic = data.total_traffic
            if data.valid_days is not None:
                line.valid_days = data.valid_days
            if data.is_permanent is not None:
                line.is_permanent = 1 if data.is_permanent else 0
            if data.user_note is not None:
                line.user_note = data.user_note

            # 验证分享限制不能大于总流量
            if (
                line.traffic_limit is not None
                and line.total_traffic is not None
                and line.traffic_limit > line.total_traffic
            ):
                return BaseResponse(
                    success=False,
                    message=f"分享限制 ({line.traffic_limit}GB) 不能大于总流量 ({line.total_traffic}GB)",
                )

            # 重新计算过期时间
            if data.is_permanent is not None or data.valid_days is not None:
                if line.is_permanent:
                    line.expires_at = None
                elif line.valid_days:
                    line.expires_at = current_time + (line.valid_days * 24 * 60 * 60)

            line.updated_at = current_time

            session.commit()

            logger.info(
                f"用户 {get_user_name_from_tg_id(tg_id)} 更新自定义线路: {line.domain}"
            )

            return BaseResponse(success=True, message="更新成功")

    except Exception as e:
        logger.error(f"更新自定义线路失败: {e}")
        return BaseResponse(success=False, message=f"更新失败: {e!s}")


@router.delete("/custom-lines/{line_id}")
@require_telegram_auth
async def delete_custom_line(
    request: Request,
    line_id: int,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    """删除自定义线路（只能删除非 approved 状态的线路，approved 状态需先下线）"""
    try:
        tg_id = user.id

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            # 检查权限
            if line.tg_id != tg_id:
                return BaseResponse(success=False, message="无权删除此线路")

            domain = line.domain
            line_status = line.status

            # 不能直接删除已批准的线路，需要先下线
            if line_status == "approved":
                return BaseResponse(
                    success=False,
                    message="不能直接删除已上线的线路，请先下线后再删除",
                )

            # 立即结算当月流量积分（如果线路配置了流量价格）
            if line_status in ["offline", "expired"]:
                logger.info(f"开始为删除的线路 {domain} 结算当月流量积分")
                try:
                    from app.modules.custom_line import settle_custom_line_traffic

                    await settle_custom_line_traffic(
                        line_domain=domain, force_current_month=True
                    )
                    logger.info(f"线路 {domain} 当月流量结算完成")
                except Exception as e:
                    logger.error(f"结算线路 {domain} 流量失败: {e}")

            session.delete(line)
            session.commit()

            logger.info(
                f"用户 {get_user_name_from_tg_id(tg_id)} 删除自定义线路: {domain} (原状态: {line_status})"
            )

            return BaseResponse(success=True, message="删除成功")

    except Exception as e:
        logger.error(f"删除自定义线路失败: {e}")
        return BaseResponse(success=False, message=f"删除失败: {e!s}")


@router.post("/custom-lines/{line_id}/offline")
@require_telegram_auth
async def offline_custom_line(
    request: Request,
    line_id: int,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    """下线自定义线路（仅限已批准的线路且为线路所有者）"""
    try:
        tg_id = user.id
        current_time = int(time())

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            # 检查权限
            if line.tg_id != tg_id:
                return BaseResponse(success=False, message="无权下线此线路")

            # 只能下线已批准的线路
            if line.status != "approved":
                return BaseResponse(
                    success=False,
                    message=f"只能下线已批准的线路，当前状态: {line.status}",
                )

            domain = line.domain

            # 解绑所有使用该线路的用户
            logger.info(f"用户下线线路 {domain}，开始解绑所有用户")
            unbind_count = 0
            try:
                from app.domains.lines.service import (
                    unbind_specified_line_for_all_users,
                )

                success, unbind_count = await unbind_specified_line_for_all_users(
                    domain, "已被所有者下线"
                )
                if success and unbind_count > 0:
                    logger.info(f"已解绑 {unbind_count} 个用户的线路 {domain}")
            except Exception as e:
                logger.error(f"解绑用户失败: {e}")

            # 禁用所有使用该线路的调度规则并通知用户
            try:
                from app.domains.lines.service import disable_line_schedules_and_notify

                await disable_line_schedules_and_notify(
                    domain, "用户分享线路已被所有者下线"
                )
            except Exception as e:
                logger.error(f"禁用线路 {domain} 的调度规则失败: {e}")

            # 更新状态为 offline
            line.status = "offline"
            line.updated_at = current_time

            session.commit()

            logger.info(
                f"用户 {get_user_name_from_tg_id(tg_id)} 下线自定义线路: {domain}"
            )

            # 发送管理员通知
            from datetime import UTC, datetime

            user_name = get_user_name_from_tg_id(tg_id)
            # Keep the host's local time display while constructing an aware datetime.
            offline_time = (
                datetime.fromtimestamp(current_time, tz=UTC)
                .astimezone()
                .strftime("%Y-%m-%d %H:%M:%S")
            )
            admin_notification = f"""📴 自定义线路下线通知

👤 用户: {user_name}
🌐 线路: {domain}
📊 解绑用户数: {unbind_count}
⏰ 下线时间: {offline_time}"""

            for admin_id in settings.TG_ADMIN_CHAT_ID:
                background_tasks.add_task(
                    send_message_by_url,
                    chat_id=admin_id,
                    text=admin_notification,
                )

            return BaseResponse(success=True, message=f"线路 {domain} 已下线")

    except Exception as e:
        logger.error(f"下线自定义线路失败: {e}")
        return BaseResponse(success=False, message=f"下线失败: {e!s}")


@router.post("/custom-lines/{line_id}/online")
@require_telegram_auth
async def online_custom_line(
    request: Request,
    line_id: int,
    data: CustomLineOnlineRequest,
    background_tasks: BackgroundTasks,
    user: TelegramUser = Depends(get_telegram_user),
):
    """上线自定义线路（仅限已下线的线路且为线路所有者，可修改流量和有效期）"""
    try:
        tg_id = user.id
        current_time = int(time())

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            # 检查权限
            if line.tg_id != tg_id:
                return BaseResponse(success=False, message="无权上线此线路")

            # 只能上线已下线的线路
            if line.status != "offline":
                return BaseResponse(
                    success=False,
                    message=f"只能上线已下线的线路，当前状态: {line.status}",
                )

            # 获取最终的流量限制和总流量值（用于验证）
            final_traffic_limit = (
                data.traffic_limit
                if data.traffic_limit is not None
                else line.traffic_limit
            )
            final_total_traffic = (
                data.total_traffic
                if data.total_traffic is not None
                else line.total_traffic
            )

            # 验证分享限制不能大于总流量
            if (
                final_traffic_limit is not None
                and final_total_traffic is not None
                and final_traffic_limit > final_total_traffic
            ):
                return BaseResponse(
                    success=False,
                    message=f"分享限制 ({final_traffic_limit}GB) 不能大于总流量 ({final_total_traffic}GB)",
                )

            # 更新流量限制（如果提供）
            if data.traffic_limit is not None:
                line.traffic_limit = data.traffic_limit

            # 更新总流量包（如果提供）
            if data.total_traffic is not None:
                line.total_traffic = data.total_traffic

            # 更新有效期（如果提供）
            if data.valid_days is not None:
                if data.valid_days > 0:
                    line.valid_days = data.valid_days
                    line.is_permanent = 0
                    line.expires_at = current_time + (data.valid_days * 24 * 60 * 60)
                else:
                    return BaseResponse(success=False, message="有效天数必须大于0")
            elif data.is_permanent is not None:
                if data.is_permanent:
                    line.is_permanent = 1
                    line.expires_at = None
                else:
                    # 如果设为非永久但未提供天数，保持原有设置
                    if not line.is_permanent and line.valid_days:
                        # 重新计算过期时间
                        line.expires_at = current_time + (
                            line.valid_days * 24 * 60 * 60
                        )

            # 更新状态为 approved
            line.status = "approved"
            line.updated_at = current_time

            session.commit()

            logger.info(
                f"用户 {get_user_name_from_tg_id(tg_id)} 上线自定义线路: {line.domain}"
            )

            from datetime import datetime

            from app.core.config import config

            expire_info = (
                "长期可用"
                if line.is_permanent
                else (
                    datetime.fromtimestamp(
                        line.expires_at, tz=config.settings.TZ
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    if line.expires_at
                    else "未设置"
                )
            )

            # 发送频道通知
            if settings.TG_CHANNEL_ID:
                user_name = get_user_name_from_tg_id(tg_id)
                traffic_info = (
                    f"{line.traffic_limit} GB" if line.traffic_limit else "无限制"
                )

                channel_notification = f"""🎉 线路重新上线通知

🌐 线路: {line.domain}
🌍 网络信息: {line.network_info or "未提供"}
📊 流量限制: {traffic_info}
⏰ 有效期: {expire_info}

线路由 {user_name} 重新上线！感谢分享！"""

                background_tasks.add_task(
                    send_message_by_url,
                    chat_id=settings.TG_CHANNEL_ID,
                    text=channel_notification,
                )

            return BaseResponse(
                success=True,
                message=f"线路 {line.domain} 已上线\n"
                f"流量限制: {line.traffic_limit if line.traffic_limit else '无限制'} GB\n"
                f"过期时间: {expire_info}",
            )

    except Exception as e:
        logger.error(f"上线自定义线路失败: {e}")
        return BaseResponse(success=False, message=f"上线失败: {e!s}")


@router.post("/custom-lines/{line_id}/renew")
@require_telegram_auth
async def renew_custom_line(
    request: Request,
    line_id: int,
    data: CustomLineRenewRequest,
    user: TelegramUser = Depends(get_telegram_user),
):
    """续期自定义线路（仅限已批准的线路且为线路所有者）"""
    try:
        tg_id = user.id
        current_time = int(time())

        with get_session() as session:
            stmt = select(CustomLine).where(CustomLine.id == line_id)
            result = session.execute(stmt)
            line = result.scalar_one_or_none()

            if not line:
                return BaseResponse(success=False, message="线路不存在")

            # 检查权限
            if line.tg_id != tg_id:
                return BaseResponse(success=False, message="无权续期此线路")

            # 只能续期已批准或已过期的线路
            if line.status not in ["approved", "expired"]:
                return BaseResponse(
                    success=False,
                    message=f"只能续期已批准或已过期的线路，当前状态: {line.status}",
                )

            # 不能续期永久线路
            if line.is_permanent:
                return BaseResponse(success=False, message="永久线路无需续期")

            # 计算新的过期时间
            if line.expires_at and line.expires_at > current_time:
                # 如果还没过期，在当前过期时间基础上延长
                new_expires_at = line.expires_at + (data.valid_days * 24 * 60 * 60)
            else:
                # 如果已过期或没有过期时间，从当前时间开始计算
                new_expires_at = current_time + (data.valid_days * 24 * 60 * 60)

            old_expires_at = line.expires_at
            line.expires_at = new_expires_at
            line.updated_at = current_time

            # 如果线路是过期状态，续期后恢复为已批准状态
            if line.status == "expired":
                line.status = "approved"

            session.commit()

            logger.info(
                f"用户 {get_user_name_from_tg_id(tg_id)} 续期自定义线路 {line.domain}: "
                f"延长 {data.valid_days} 天，新过期时间: {new_expires_at}"
            )

            from datetime import datetime

            from app.core.config import config

            old_expires_str = (
                datetime.fromtimestamp(old_expires_at, tz=config.settings.TZ).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                if old_expires_at
                else "未设置"
            )
            new_expires_str = datetime.fromtimestamp(
                new_expires_at, tz=config.settings.TZ
            ).strftime("%Y-%m-%d %H:%M:%S")

            return BaseResponse(
                success=True,
                message=f"续期成功！延长 {data.valid_days} 天\n"
                f"原过期时间: {old_expires_str}\n"
                f"新过期时间: {new_expires_str}",
            )

    except Exception as e:
        logger.error(f"续期自定义线路失败: {e}")
        return BaseResponse(success=False, message=f"续期失败: {e!s}")
