from typing import List, Optional

from pydantic import BaseModel, Field


class LuckyWheelItem(BaseModel):
    """幸运大转盘奖品项"""

    name: str = Field(..., description="奖品名称")
    probability: float = Field(..., ge=0, le=100, description="中奖概率（百分比）")


class LuckyWheelConfig(BaseModel):
    """幸运大转盘配置"""

    items: List[LuckyWheelItem] = Field(..., description="转盘奖品列表")
    cost_credits: int = Field(default=10, ge=1, description="参与转盘需要的积分")
    min_credits_required: int = Field(default=30, ge=1, description="最低积分要求")
    gen_privileged_code: bool = Field(default=False, description="是否生成特权邀请码")


class LuckyWheelSpinRequest(BaseModel):
    """转盘旋转请求"""

    pass  # 目前不需要额外参数


class LuckyWheelSpinResult(BaseModel):
    """转盘旋转结果"""

    item: LuckyWheelItem = Field(..., description="中奖奖品")
    credits_change: float = Field(..., description="积分变化（正数为增加，负数为减少）")
    current_credits: float = Field(..., description="当前剩余积分")


class LuckyWheelConfigUpdateRequest(BaseModel):
    """更新转盘配置请求"""

    items: List[LuckyWheelItem] = Field(..., description="转盘奖品列表")
    cost_credits: Optional[int] = Field(None, ge=1, description="参与转盘需要的积分")
    min_credits_required: Optional[int] = Field(None, ge=1, description="最低积分要求")
    gen_privileged_code: bool = Field(default=False, description="是否生成特权邀请码")
