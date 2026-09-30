"""
Crypto 捐赠相关 API 路由
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.log import logger
from app.domains.crypto_donation import exceptions as crypto_errors
from app.domains.crypto_donation import service as crypto_donation_service
from app.domains.crypto_donation.schemas import (
    CryptoDonationOrderCreate,
    CryptoDonationOrderCreateResponse,
    CryptoDonationOrderListResponse,
    CryptoDonationOrderResponse,
    CryptoTypesResponse,
)
from app.domains.crypto_donation.types import NewOrder
from app.integrations.telegram.profiles import get_user_name_from_tg_id
from app.transport.http.auth import (
    check_admin_permission,
    get_telegram_user,
    require_telegram_auth,
)
from app.transport.http.schemas import TelegramUser

router = APIRouter(prefix="/api/crypto-donations", tags=["crypto-donations"])


@router.get("/crypto-types", response_model=CryptoTypesResponse)
async def get_crypto_types():
    """获取支持的加密货币类型"""
    try:
        return CryptoTypesResponse(
            data=crypto_donation_service.get_supported_crypto_types()
        )
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
        order = await crypto_donation_service.create_order(
            user.id,
            NewOrder(order_data.crypto_type, order_data.amount, order_data.note),
        )
        return CryptoDonationOrderCreateResponse(
            message="Crypto 捐赠订单创建成功，请完成支付",
            data=CryptoDonationOrderResponse(**order),
        )
    except crypto_errors.CryptoDonationError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    except HTTPException:
        raise
    except Exception:
        logger.exception("创建 Crypto 捐赠订单失败")
        raise HTTPException(status_code=500, detail="创建订单失败")


@router.get("/orders/all", response_model=CryptoDonationOrderListResponse)
@require_telegram_auth
async def get_all_crypto_donation_orders(
    request: Request,
    user: TelegramUser = Depends(get_telegram_user),
    page: int = 1,
    per_page: int = 20,
    status_filter: str | None = None,
):
    """获取所有 Crypto 捐赠订单列表（管理员专用）"""
    try:
        # 检查管理员权限
        check_admin_permission(user)

        # 限制分页参数
        per_page = min(max(per_page, 1), 100)
        page = max(page, 1)
        offset = (page - 1) * per_page

        # 获取订单列表
        orders = crypto_donation_service.get_all_orders(
            limit=per_page, offset=offset, status_filter=status_filter
        )

        # 获取总数
        total = crypto_donation_service.get_order_count(status_filter=status_filter)

        # 为每个订单添加用户名信息
        order_responses = []
        for order in orders:
            # 添加用户名到订单数据
            order_with_username = {
                **order,
                "username": get_user_name_from_tg_id(order.get("user_id")),
            }
            order_responses.append(CryptoDonationOrderResponse(**order_with_username))

        return CryptoDonationOrderListResponse(
            data=order_responses, total=total, page=page, per_page=per_page
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取所有 Crypto 捐赠订单失败: {e!s}")
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

        orders = crypto_donation_service.get_user_orders(user_id, limit=50)

        order_responses = [CryptoDonationOrderResponse(**order) for order in orders]

        return CryptoDonationOrderListResponse(
            data=order_responses, total=len(order_responses)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户 Crypto 捐赠订单失败: {e!s}")
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

        order = crypto_donation_service.get_order(order_id)

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
        logger.error(f"获取 Crypto 捐赠订单详情失败: {e!s}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取订单详情失败",
        )


@router.post("/callback")
async def upay_payment_callback(request: Request):
    """UPAY 支付完成回调"""
    try:
        await crypto_donation_service.process_callback(await request.json())
        return PlainTextResponse(content="ok")
    except crypto_errors.CryptoDonationError as error:
        return JSONResponse(
            status_code=error.status_code, content={"error": str(error)}
        )
    except Exception:
        logger.exception("处理 UPAY 回调失败")
        return JSONResponse(status_code=500, content={"error": "internal server error"})


@router.get("/payment-success")
async def payment_success_redirect():
    """支付完成后的重定向处理"""
    return {"success": True, "message": "支付成功，感谢您的捐赠！"}
