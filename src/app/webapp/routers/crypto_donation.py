"""
Crypto 捐赠相关 API 路由
"""

from app.config import settings
from app.databases.db import DB
from app.log import logger
from app.modules.upay import UPayService
from app.utils.utils import get_user_name_from_tg_id, send_message_by_url
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.routers.admin import check_admin_permission
from app.webapp.schemas import TelegramUser
from app.webapp.schemas.crypto_donation import (
    CryptoDonationOrderCreate,
    CryptoDonationOrderCreateResponse,
    CryptoDonationOrderListResponse,
    CryptoDonationOrderResponse,
    CryptoTypesResponse,
    UPayCallbackData,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter(prefix="/api/crypto-donations", tags=["crypto-donations"])


def check_user_binding(user_id: int) -> bool:
    """检查用户是否绑定了 emby 或 plex 账号"""
    try:
        db = DB()

        # 检查 emby 绑定
        emby_result = db.cur.execute(
            "SELECT emby_id FROM emby_user WHERE tg_id = ?", (user_id,)
        ).fetchone()

        # 检查 plex 绑定
        plex_result = db.cur.execute(
            "SELECT plex_id FROM user WHERE tg_id = ?", (user_id,)
        ).fetchone()

        db.close()

        return bool(emby_result or plex_result)
    except Exception as e:
        logger.error(f"检查用户绑定状态失败: {e}")
        return False


@router.get("/crypto-types", response_model=CryptoTypesResponse)
async def get_crypto_types():
    """获取支持的加密货币类型"""
    try:
        return CryptoTypesResponse(data=settings.UPAY_CRYPTO_TYPES)
    except Exception as e:
        logger.error(f"获取加密货币类型失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取加密货币类型失败",
        )


@router.post("/create", response_model=CryptoDonationOrderCreateResponse)
@require_telegram_auth
async def create_crypto_donation_order(
    request: Request,
    order_data: CryptoDonationOrderCreate,
    user: TelegramUser = Depends(get_telegram_user),
):
    """创建 Crypto 捐赠订单"""
    try:
        user_id = user.id
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="用户信息不完整"
            )

        # 检查用户是否绑定了 emby 或 plex 账号
        if not check_user_binding(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="不接受无帐号捐赠，请先绑定 Emby 或 Plex 账号后再进行捐赠",
            )

        db = DB()
        upay_service = UPayService()

        # 生成唯一订单ID
        order_id = upay_service.generate_order_id()

        # 创建本地订单记录
        success = db.create_crypto_donation_order(
            user_id=user_id,
            order_id=order_id,
            crypto_type=order_data.crypto_type,
            amount=order_data.amount,
            note=order_data.note,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="创建订单失败",
            )

        # 调用 UPAY 创建订单
        upay_result = await upay_service.create_order(
            crypto_type=order_data.crypto_type,
            amount=order_data.amount,
            order_id=order_id,
        )

        if not upay_result:
            # 删除本地订单记录
            db.cur.execute(
                "DELETE FROM crypto_donation_orders WHERE order_id = ?", (order_id,)
            )
            db.con.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="创建支付订单失败，请稍后重试",
            )

        # 更新订单的 UPAY 信息
        db.update_crypto_donation_order_upay_info(
            order_id=order_id,
            trade_id=upay_result.get("trade_id"),
            actual_amount=upay_result.get("actual_amount"),
            payment_address=upay_result.get("token"),
            payment_url=upay_result.get("payment_url"),
            expiration_time=upay_result.get("expiration_time"),
        )

        # 获取更新后的订单
        updated_order = db.get_crypto_donation_order_by_order_id(order_id)
        db.close()

        if not updated_order:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="获取订单信息失败",
            )

        # 构造响应
        order_response = CryptoDonationOrderResponse(**updated_order)

        # 发送管理员通知 - 用户创建了新的 Crypto 捐赠订单
        try:
            user_name = get_user_name_from_tg_id(user_id)
            admin_message = f"""
💰 <b>新的 Crypto 捐赠订单</b>

👤 用户: {user_name} ({user_id})
🆔 订单号: {order_id}
💳 加密货币: {order_data.crypto_type}
💵 金额: {order_data.amount:.2f} CNY
📝 备注: {order_data.note or '无'}

💰 支付地址: <code>{upay_result.get('token', '未获取')}</code>
🔗 支付链接: {upay_result.get('payment_url', '未获取')}
⏰ 创建时间: {updated_order.get('created_at', '未知')}
"""

            for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
                try:
                    await send_message_by_url(
                        chat_id=admin_chat_id, text=admin_message, parse_mode="HTML"
                    )
                except Exception as e:
                    logger.warning(f"发送管理员通知失败 {admin_chat_id}: {e}")

            logger.info(f"已向管理员发送 Crypto 捐赠订单创建通知，订单ID: {order_id}")

        except Exception as e:
            logger.warning(f"发送 Crypto 捐赠订单创建通知失败: {e}")
            # 即使通知发送失败，也不影响主要业务逻辑

        return CryptoDonationOrderCreateResponse(
            message="Crypto 捐赠订单创建成功，请完成支付", data=order_response
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建 Crypto 捐赠订单失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建订单失败",
        )


@router.get("/orders/all", response_model=CryptoDonationOrderListResponse)
@require_telegram_auth
async def get_all_crypto_donation_orders_admin(
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
    page: int = 1,
    per_page: int = 20,
    status_filter: str = None,
):
    """获取所有 Crypto 捐赠订单列表（管理员专用）"""
    try:
        # 检查管理员权限
        check_admin_permission(user)

        # 限制分页参数
        per_page = min(max(per_page, 1), 100)
        page = max(page, 1)
        offset = (page - 1) * per_page

        db = DB()

        # 获取订单列表
        orders = db.get_all_crypto_donation_orders(
            limit=per_page, offset=offset, status_filter=status_filter
        )

        # 获取总数
        total = db.get_crypto_donation_orders_count(status_filter=status_filter)

        db.close()

        order_responses = [CryptoDonationOrderResponse(**order) for order in orders]

        return CryptoDonationOrderListResponse(
            data=order_responses, total=total, page=page, per_page=per_page
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取所有 Crypto 捐赠订单失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取订单列表失败",
        )


@router.get("/orders", response_model=CryptoDonationOrderListResponse)
@require_telegram_auth
async def get_user_crypto_donation_orders(
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取用户的 Crypto 捐赠订单列表"""
    try:
        user_id = user.id
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="用户信息不完整"
            )

        db = DB()
        orders = db.get_crypto_donation_orders_by_user(user_id, limit=50)
        db.close()

        order_responses = [CryptoDonationOrderResponse(**order) for order in orders]

        return CryptoDonationOrderListResponse(
            data=order_responses, total=len(order_responses)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户 Crypto 捐赠订单失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取订单列表失败",
        )


@router.get("/orders/{order_id}", response_model=CryptoDonationOrderResponse)
@require_telegram_auth
async def get_crypto_donation_order(
    order_id: str,
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
):
    """获取特定的 Crypto 捐赠订单详情"""
    try:
        user_id = user.id
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="用户信息不完整"
            )

        db = DB()
        order = db.get_crypto_donation_order_by_order_id(order_id)
        db.close()

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="订单不存在",
            )

        # 检查订单所有权
        if order["user_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权访问此订单",
            )

        return CryptoDonationOrderResponse(**order)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 Crypto 捐赠订单详情失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取订单详情失败",
        )


@router.post("/callback")
async def upay_payment_callback(request: Request):
    """UPAY 支付完成回调"""
    try:
        # 获取回调数据
        callback_data = await request.json()
        logger.info(f"接收到 UPAY 回调: {callback_data}")

        # 验证回调数据
        upay_service = UPayService()
        if not upay_service.verify_callback_signature(callback_data):
            logger.error("UPAY 回调签名验证失败")
            return JSONResponse(
                status_code=400, content={"error": "signature verification failed"}
            )

        # 解析回调数据
        try:
            callback = UPayCallbackData(**callback_data)
        except Exception as e:
            logger.error(f"解析 UPAY 回调数据失败: {e}")
            return JSONResponse(
                status_code=400, content={"error": "invalid callback data"}
            )

        # 只处理支付成功的回调
        if callback.status != 2:
            logger.warning(f"接收到非支付成功回调，状态: {callback.status}")
            return PlainTextResponse(content="ok")

        db = DB()

        # 查找订单
        order = db.get_crypto_donation_order_by_trade_id(callback.trade_id)
        if not order:
            logger.error(f"找不到交易ID为 {callback.trade_id} 的订单")
            db.close()
            return JSONResponse(status_code=404, content={"error": "order not found"})

        # 检查订单是否已经处理过
        if order["status"] == 2:
            logger.info(f"订单 {callback.order_id} 已经处理过，跳过")
            db.close()
            return PlainTextResponse(content="ok")

        # 更新订单状态为已支付
        success = db.complete_crypto_donation_order(
            trade_id=callback.trade_id,
            block_transaction_id=callback.block_transaction_id,
            actual_amount=callback.actual_amount,
        )

        if not success:
            logger.error(f"更新订单 {callback.order_id} 状态失败")
            db.close()
            return JSONResponse(
                status_code=500, content={"error": "failed to update order status"}
            )

        # 获取用户当前捐赠金额和积分
        user_id = order["user_id"]
        stats_info = db.get_stats_by_tg_id(user_id)

        if stats_info:
            current_donation = stats_info[1] if stats_info[1] else 0
            current_credits = stats_info[2] if stats_info[2] else 0

            # 直接使用订单金额作为人民币捐赠金额（订单已经是人民币）
            donation_amount_cny = callback.amount  # 使用原始订单金额，因为已经是人民币
            new_donation = round(current_donation + donation_amount_cny, 2)

            # 计算新的积分（捐赠金额的积分奖励，应用捐赠倍数）
            credits_reward = round(
                donation_amount_cny * settings.DONATION_MULTIPLIER, 2
            )
            new_credits = round(current_credits + credits_reward, 2)

            # 更新用户捐赠金额和积分
            donation_success = db.update_user_donation(new_donation, user_id)
            credits_success = db.update_user_credits(new_credits, user_id)

            if donation_success and credits_success:
                logger.info(
                    f"用户 {user_id} Crypto 捐赠处理成功: "
                    f"捐赠金额 {donation_amount_cny:.2f} CNY, 积分奖励 {credits_reward} (倍数: {settings.DONATION_MULTIPLIER})"
                )

                # 发送用户通知 - 支付成功
                try:
                    user_name = get_user_name_from_tg_id(user_id)
                    user_message = f"""
🎉 <b>Crypto 捐赠支付成功</b>

感谢您的捐赠！

🆔 订单号: {callback.order_id}
💳 加密货币: {order['crypto_type']}
💵 支付金额: {donation_amount_cny:.2f} CNY
🏆 获得积分: {credits_reward}
💰 累计捐赠: {new_donation:.2f} CNY
⭐ 当前积分: {new_credits:.2f}

您的支持是我们前进的动力！
"""

                    await send_message_by_url(
                        chat_id=user_id, text=user_message, parse_mode="HTML"
                    )

                    logger.info(
                        f"已向用户 {user_name}({user_id}) 发送 Crypto 捐赠支付成功通知"
                    )

                except Exception as e:
                    logger.warning(f"发送用户 Crypto 捐赠支付成功通知失败: {e}")

                # 发送管理员通知 - 订单支付完成
                try:
                    user_name = get_user_name_from_tg_id(user_id)
                    admin_message = f"""
✅ <b>Crypto 捐赠订单支付完成</b>

👤 用户: {user_name} ({user_id})
🆔 订单号: {callback.order_id}
💳 加密货币: {order['crypto_type']}
💵 支付金额: {donation_amount_cny:.2f} CNY
🏆 积分奖励: {credits_reward}
💰 用户累计捐赠: {new_donation:.2f} CNY
⭐ 用户当前积分: {new_credits:.2f}

🔗 区块链交易: <code>{callback.block_transaction_id or '未提供'}</code>
⏰ 完成时间: {callback.time or '未知'}
"""

                    for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
                        try:
                            await send_message_by_url(
                                chat_id=admin_chat_id,
                                text=admin_message,
                                parse_mode="HTML",
                            )
                        except Exception as e:
                            logger.warning(
                                f"发送管理员完成通知失败 {admin_chat_id}: {e}"
                            )

                    logger.info(
                        f"已向管理员发送 Crypto 捐赠订单完成通知，订单ID: {callback.order_id}"
                    )

                except Exception as e:
                    logger.warning(f"发送 Crypto 捐赠订单完成通知失败: {e}")

            else:
                logger.error(f"更新用户 {user_id} 捐赠金额或积分失败")
        else:
            logger.error(f"找不到用户 {user_id} 的统计信息")

        db.close()

        logger.info(f"UPAY 回调处理完成，订单 {callback.order_id} 支付成功")
        return PlainTextResponse(content="ok")

    except Exception as e:
        logger.error(f"处理 UPAY 回调失败: {e}")
        return JSONResponse(status_code=500, content={"error": "internal server error"})


@router.get("/payment-success")
async def payment_success_redirect():
    """支付完成后的重定向处理"""
    return {"success": True, "message": "支付成功，感谢您的捐赠！"}
