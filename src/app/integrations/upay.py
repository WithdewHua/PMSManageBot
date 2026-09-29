"""
UPAY 支付服务模块
"""

import hashlib
import hmac
import uuid

import httpx

from app.core.config import settings
from app.core.log import logger


def upay_secret_configured() -> bool:
    """Return whether a non-empty UPay signing secret is configured."""
    return bool(settings.UPAY_SECRET_KEY.strip())


def warn_if_secret_missing() -> None:
    """Warn once per application startup when UPay signing is disabled."""
    if not upay_secret_configured():
        logger.warning(
            "UPAY_SECRET_KEY is not configured; crypto donations are disabled"
        )


class UPayService:
    """UPAY 支付服务"""

    def __init__(self):
        self.base_url = getattr(settings, "UPAY_BASE_URL", "http://localhost:8090")
        self.secret_key = settings.UPAY_SECRET_KEY.strip()
        self.notify_url = (
            f"{settings.WEBAPP_URL.rstrip('/')}/api/crypto-donations/callback"
        )
        self.redirect_url = (
            f"{settings.WEBAPP_URL.rstrip('/')}/api/crypto-donations/payment-success"
        )

    def generate_order_id(self) -> str:
        """生成订单ID"""
        return f"CRYPTO_DONATION_{uuid.uuid4().hex[:16].upper()}"

    def generate_signature(self, params: dict) -> str:
        """生成签名"""
        try:
            # 按照 UPAY 文档要求的参数顺序
            sorted_params = []
            for key in sorted(params.keys()):
                if key != "signature":
                    # 特殊处理金额字段，去除尾随零
                    if key == "amount" and isinstance(params[key], (int, float)):
                        value_str = f"{float(params[key]):.2f}".rstrip("0").rstrip(".")
                    elif key == "actual_amount" and isinstance(
                        params[key], (int, float)
                    ):
                        value_str = f"{float(params[key]):.4f}".rstrip("0").rstrip(".")
                    else:
                        # 将参数值转换为字符串进行签名计算
                        value_str = str(params[key])

                    sorted_params.append(f"{key}={value_str}")

            # 拼接参数和密钥
            sign_string = "&".join(sorted_params) + self.secret_key

            # MD5 加密；签名原文和签名本身都不得进入日志。
            return hashlib.md5(sign_string.encode("utf-8")).hexdigest()
        except Exception as e:
            logger.error(f"生成签名失败: {e}")
            return ""

    def verify_callback_signature(self, data: dict) -> bool:
        """验证回调签名"""
        try:
            if not self.secret_key:
                return False
            received_signature = str(data.get("signature", ""))
            if not received_signature:
                return False

            # 构建签名参数（排除 signature 字段）
            params = {}
            for key, value in data.items():
                if key != "signature":
                    # 特殊处理金额相关字段，去除尾随零
                    if key == "amount" and isinstance(value, (int, float, str)):
                        try:
                            params[key] = f"{float(value):.2f}".rstrip("0").rstrip(".")
                        except (ValueError, TypeError):
                            params[key] = str(value)
                    elif key == "actual_amount" and isinstance(
                        value, (int, float, str)
                    ):
                        try:
                            params[key] = f"{float(value):.4f}".rstrip("0").rstrip(".")
                        except (ValueError, TypeError):
                            params[key] = str(value)
                    else:
                        params[key] = str(value)

            # 生成预期签名
            expected_signature = self.generate_signature(params)

            return hmac.compare_digest(received_signature, expected_signature)
        except Exception as e:
            logger.error(f"验证回调签名失败: {e}")
            return False

    async def create_order(
        self,
        crypto_type: str,
        amount: float,
        order_id: str | None = None,
    ) -> dict | None:
        """创建 UPAY 订单"""
        try:
            if not self.secret_key:
                logger.error("UPAY_SECRET_KEY is not configured")
                return None
            if not order_id:
                order_id = self.generate_order_id()

            # 构建请求参数
            params = {
                "type": crypto_type,
                "order_id": order_id,
                "amount": amount,  # 保持为数值类型，不转换为字符串
                "notify_url": self.notify_url,
                "redirect_url": self.redirect_url,
            }

            # 生成签名
            signature = self.generate_signature(params)
            params["signature"] = signature

            logger.info(
                "创建 UPAY 订单: order_id=%s type=%s amount=%.2f",
                order_id,
                crypto_type,
                amount,
            )

            # 发送请求
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/create_order",
                    json=params,
                    headers={"Content-Type": "application/json"},
                )

                response_data = response.json()
                logger.info(
                    "UPAY 响应: status_code=%s message=%s",
                    response_data.get("status_code"),
                    response_data.get("message"),
                )

                if response_data.get("status_code") == 200:
                    return response_data.get("data")
                else:
                    logger.error(f"UPAY 创建订单失败: {response_data.get('message')}")
                    return None

        except Exception as e:
            logger.error(f"创建 UPAY 订单异常: {e}")
            return None
