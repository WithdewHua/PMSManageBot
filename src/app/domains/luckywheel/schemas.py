from pydantic import BaseModel, Field


class LuckyWheelItem(BaseModel):
    """幸运大转盘奖品项"""

    name: str = Field(..., description="奖品名称")
    probability: float = Field(..., ge=0, le=100, description="中奖概率（百分比）")


class LuckyWheelConfig(BaseModel):
    """幸运大转盘配置"""

    items: list[LuckyWheelItem] = Field(..., description="转盘奖品列表")
    cost_credits: int = Field(default=10, ge=1, description="参与转盘需要的积分")
    min_credits_required: int = Field(default=30, ge=1, description="最低积分要求")
    gen_privileged_code: bool = Field(default=False, description="是否生成特权邀请码")


class LuckyWheelSpinRequest(BaseModel):
    """转盘旋转请求"""


class LuckyWheelSpinResult(BaseModel):
    """转盘旋转结果"""

    item: LuckyWheelItem = Field(..., description="中奖奖品")
    credits_change: float = Field(..., description="积分变化（正数为增加，负数为减少）")
    current_credits: float = Field(..., description="当前剩余积分")
    used_free_spin: bool = Field(
        False,
        description=(
            "本次是否消耗了免费机会（任何来源：21 点打满手数、礼包等；"
            "免参与费、不受最低积分限制）"
        ),
    )
    free_spin_source: str | None = Field(
        None,
        description="消耗的免费机会来源：blackjack / gift_pack；未使用免费机会时为空",
    )


class LuckyWheelFreespinSummaryResponse(BaseModel):
    """21 点联动免费机会概览（转盘页展示）"""

    enabled: bool = Field(..., description="打满送免费机会机制是否启用")
    available: int = Field(..., ge=0, description="当前可用次数（未用且未过期）")
    expires_at_ms_list: list[int] = Field(
        default_factory=list, description="各张机会的到期时间（毫秒，升序）"
    )
    hands_since_freespin: int = Field(
        ..., ge=0, description="自上次转换后的已结算现金局手数（进度条分子）"
    )
    hand_threshold: int = Field(
        ..., ge=0, description="打满手数阈值（进度条分母）；机制停用时为 0"
    )


class LuckyWheelTenSpinResult(BaseModel):
    """转盘十连抽结果"""

    results: list[LuckyWheelSpinResult] = Field(..., description="十连抽每次结果")
    total_credits_change: float = Field(..., description="十连抽总积分变化")
    current_credits: float = Field(..., description="十连抽后当前剩余积分")


class LuckyWheelConfigUpdateRequest(BaseModel):
    """更新转盘配置请求"""

    items: list[LuckyWheelItem] = Field(..., description="转盘奖品列表")
    cost_credits: int | None = Field(None, ge=1, description="参与转盘需要的积分")
    min_credits_required: int | None = Field(None, ge=1, description="最低积分要求")
    gen_privileged_code: bool = Field(default=False, description="是否生成特权邀请码")
