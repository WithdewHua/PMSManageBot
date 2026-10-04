from pydantic import BaseModel, ConfigDict, Field


class LuckyWheelItem(BaseModel):
    """幸运大转盘奖品项（内部配置与管理员使用）。"""

    name: str = Field(..., description="奖品名称")
    probability: float = Field(..., ge=0, le=100, description="中奖概率（百分比）")


class LuckyWheelConfig(BaseModel):
    """幸运大转盘完整内部配置。"""

    model_config = ConfigDict(frozen=True)

    items: list[LuckyWheelItem] = Field(..., description="转盘奖品列表")
    cost_credits: int = Field(default=10, ge=1, description="参与转盘需要的积分")
    min_credits_required: int = Field(default=30, ge=1, description="最低积分要求")
    gen_privileged_code: bool = Field(default=False, description="是否生成特权邀请码")


class LuckyWheelSpinRequest(BaseModel):
    """转盘旋转请求"""


class LuckyWheelSpinResult(BaseModel):
    """转盘内部结算结果；HTTP 响应使用公开 DTO。"""

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
    """免费机会账本概览（转盘页展示）"""

    enabled: bool = Field(..., description="已注册的免费机会来源进度机制是否启用")
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
    """转盘十连抽内部结算结果。"""

    results: list[LuckyWheelSpinResult] = Field(..., description="十连抽每次结果")
    total_credits_change: float = Field(..., description="十连抽总积分变化")
    current_credits: float = Field(..., description="十连抽后当前剩余积分")


class LuckyWheelConfigUpdateRequest(BaseModel):
    """更新转盘配置请求"""

    items: list[LuckyWheelItem] = Field(..., description="转盘奖品列表")
    cost_credits: int | None = Field(None, ge=1, description="参与转盘需要的积分")
    min_credits_required: int | None = Field(None, ge=1, description="最低积分要求")
    gen_privileged_code: bool = Field(default=False, description="是否生成特权邀请码")


class PublicLuckyWheelItem(BaseModel):
    """User-visible prize; selection weights are never serialized."""

    model_config = ConfigDict(from_attributes=True)
    name: str


class PublicLuckyWheelConfig(BaseModel):
    """Allowlisted configuration required to render and use the wheel."""

    model_config = ConfigDict(from_attributes=True)
    items: list[PublicLuckyWheelItem]
    cost_credits: int
    min_credits_required: int


class PublicLuckyWheelSpinResult(BaseModel):
    """Final result without probabilities or quota decision metadata."""

    model_config = ConfigDict(from_attributes=True)
    item: PublicLuckyWheelItem
    credits_change: float
    current_credits: float
    used_free_spin: bool = False
    free_spin_source: str | None = None


class PublicLuckyWheelTenSpinResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    results: list[PublicLuckyWheelSpinResult]
    total_credits_change: float
    current_credits: float


class LuckyWheelInviteQuotaConfig(BaseModel):
    """Administrator-only document; zero disables invitation issuance."""

    model_config = ConfigDict(extra="forbid")
    global_weekly_limit: int = Field(..., ge=0, le=2_147_483_647, strict=True)
    personal_weekly_limit: int = Field(..., ge=0, le=2_147_483_647, strict=True)


class LuckyWheelInviteQuotaUserStats(BaseModel):
    tg_id: int
    issued: int = Field(..., ge=0)


class LuckyWheelInviteQuotaSourceStats(BaseModel):
    source: str | None
    issued: int = Field(..., ge=0)


class LuckyWheelInviteQuotaStats(BaseModel):
    """Administrator accounting; unknown historical timestamps stay null."""

    initialized: bool
    week_start_ms: int
    week_end_ms: int
    global_used: int = Field(..., ge=0)
    global_limit: int = Field(..., ge=0)
    personal_limit: int = Field(..., ge=0)
    historical_issued: int = Field(..., ge=0)
    new_issued: int = Field(..., ge=0)
    global_blocked_count: int = Field(..., ge=0)
    personal_blocked_count: int = Field(..., ge=0)
    both_blocked_count: int = Field(..., ge=0)
    first_exhausted_at_ms: int | None
    users: list[LuckyWheelInviteQuotaUserStats]
    sources: list[LuckyWheelInviteQuotaSourceStats]
