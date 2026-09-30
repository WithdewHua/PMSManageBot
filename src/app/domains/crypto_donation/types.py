"""Pure payment commands and callback values, without configuration access."""

from dataclasses import dataclass

from pydantic import BaseModel, Field, validator


@dataclass(frozen=True, slots=True)
class NewOrder:
    crypto_type: str
    amount: float
    note: str | None = None


class UPayCallbackData(BaseModel):
    """UPAY 支付回调数据"""

    trade_id: str = Field(..., description="系统生成的交易订单号")
    order_id: str = Field(..., description="商户订单号")
    amount: float = Field(..., description="原始订单金额（CNY）")
    actual_amount: float = Field(..., description="实际支付金额（加密货币）")
    token: str = Field(..., description="收款钱包地址")
    block_transaction_id: str | None = Field(None, description="区块链交易哈希")
    status: int = Field(..., description="订单状态：2=支付成功")
    time: str | None = Field(None, description="支付完成时间")
    signature: str = Field(..., description="签名")

    @validator("status")
    def validate_status(cls, v):
        if v != 2:
            raise ValueError("只处理支付成功的回调")
        return v
