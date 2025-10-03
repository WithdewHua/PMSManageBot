"""
Crypto 捐赠相关的 Pydantic 模型定义
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, validator


class CryptoType(str, Enum):
    """支持的加密货币类型枚举"""

    USDC_POLYGON = "USDC-Polygon"
    USDC_ARBITRUM = "USDC-ArbitrumOne"
    USDC_BSC = "USDC-BSC"
    USDT_POLYGON = "USDT-Polygon"
    USDT_ARBITRUM = "USDT-ArbitrumOne"
    USDT_BSC = "USDT-BSC"


class CryptoDonationOrderStatus(int, Enum):
    """Crypto 捐赠订单状态枚举"""

    PENDING = 1  # 等待支付
    PAID = 2  # 支付成功
    EXPIRED = 3  # 已过期


class CryptoDonationOrderCreate(BaseModel):
    """创建 Crypto 捐赠订单请求"""

    crypto_type: CryptoType = Field(..., description="加密货币类型")
    amount: float = Field(..., gt=0, description="捐赠金额（CNY），必须大于0")
    note: Optional[str] = Field(None, max_length=200, description="备注信息")

    @validator("amount")
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("捐赠金额必须大于0")
        if v > 99999:
            raise ValueError("捐赠金额过大")
        # 限制小数位数到2位
        return round(v, 2)


class CryptoDonationOrderResponse(BaseModel):
    """Crypto 捐赠订单响应"""

    id: int
    user_id: int
    order_id: str
    trade_id: Optional[str]
    crypto_type: CryptoType
    amount: float
    actual_amount: Optional[float]
    payment_address: Optional[str]
    block_transaction_id: Optional[str]
    status: CryptoDonationOrderStatus
    payment_url: Optional[str]
    expiration_time: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]
    paid_at: Optional[datetime]
    note: Optional[str]

    class Config:
        from_attributes = True


class CryptoDonationOrderCreateResponse(BaseModel):
    """创建 Crypto 捐赠订单响应"""

    success: bool = True
    message: str = "Crypto 捐赠订单创建成功"
    data: CryptoDonationOrderResponse


class CryptoDonationOrderListResponse(BaseModel):
    """Crypto 捐赠订单列表响应"""

    success: bool = True
    data: list[CryptoDonationOrderResponse]
    total: int
    page: int = 1
    per_page: int = 20


class UPayCreateOrderRequest(BaseModel):
    """UPAY 创建订单请求"""

    type: str = Field(..., description="加密货币类型")
    order_id: str = Field(..., description="商户订单号")
    amount: float = Field(..., description="订单金额（CNY）")
    notify_url: str = Field(..., description="异步通知地址")
    redirect_url: str = Field(..., description="支付完成后跳转地址")
    signature: str = Field(..., description="签名")


class UPayCreateOrderResponse(BaseModel):
    """UPAY 创建订单响应"""

    status_code: int
    message: str
    data: Optional[dict] = None


class UPayCallbackData(BaseModel):
    """UPAY 支付回调数据"""

    trade_id: str = Field(..., description="系统生成的交易订单号")
    order_id: str = Field(..., description="商户订单号")
    amount: float = Field(..., description="原始订单金额（CNY）")
    actual_amount: float = Field(..., description="实际支付金额（加密货币）")
    token: str = Field(..., description="收款钱包地址")
    block_transaction_id: str = Field(..., description="区块链交易哈希")
    status: int = Field(..., description="订单状态：2=支付成功")
    signature: str = Field(..., description="签名")

    @validator("status")
    def validate_status(cls, v):
        if v != 2:
            raise ValueError("只处理支付成功的回调")
        return v
