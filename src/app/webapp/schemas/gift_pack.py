"""
礼包（Gift Pack）相关的 Web API 模型定义
"""

from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

# ==================== 奖励项 ====================


class CreditsReward(BaseModel):
    """积分奖励项"""

    type: Literal["credits"] = "credits"
    amount: float = Field(..., gt=0, description="发放的积分数量")


class PremiumDaysReward(BaseModel):
    """Premium 天数奖励项

    发放给用户**所有已绑定**的媒体服务，Plex 与 Emby 各自独立计算到期时间。
    """

    type: Literal["premium_days"] = "premium_days"
    days: int = Field(..., gt=0, le=3650, description="延长的 Premium 天数")


RewardItem = Annotated[
    Union[CreditsReward, PremiumDaysReward],
    Field(discriminator="type"),
]

# ==================== 领取资格 ====================


class GiftPackEligibility(BaseModel):
    """领取资格条件，全部为可选；未配置任何条件即对所有用户开放"""

    min_credits: Optional[float] = Field(None, ge=0, description="最低积分要求")
    require_premium: bool = Field(False, description="是否要求 Premium 用户")
    require_binding: Optional[Literal["any", "plex", "emby"]] = Field(
        None, description="要求已绑定媒体账号：any=不限服务，plex/emby=指定服务"
    )


# ==================== 管理端请求 ====================


class GiftPackCreateRequest(BaseModel):
    """创建礼包"""

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    rewards: List[RewardItem] = Field(..., min_length=1, description="至少一项奖励")
    eligibility: Optional[GiftPackEligibility] = None
    total_quantity: Optional[int] = Field(
        None, gt=0, description="限量份数，不传表示不限量"
    )
    start_at: int = Field(..., gt=0, description="开始时间戳（epoch 秒）")
    end_at: int = Field(..., gt=0, description="结束时间戳（epoch 秒）")
    max_prompt_count: int = Field(
        3, gt=0, le=100, description="对单个用户的提醒次数上限"
    )
    is_enabled: bool = Field(True, description="是否启用")

    @field_validator("rewards")
    @classmethod
    def _no_duplicate_reward_type(cls, v: List[RewardItem]) -> List[RewardItem]:
        types = [item.type for item in v]
        if len(types) != len(set(types)):
            raise ValueError("同一礼包内不能配置两个相同类型的奖励项")
        return v

    @model_validator(mode="after")
    def _validate_window(self) -> "GiftPackCreateRequest":
        if self.end_at <= self.start_at:
            raise ValueError("结束时间必须晚于开始时间")
        return self


class GiftPackUpdateRequest(BaseModel):
    """编辑礼包：所有字段可选，仅更新传入的字段"""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    rewards: Optional[List[RewardItem]] = Field(None, min_length=1)
    eligibility: Optional[GiftPackEligibility] = None
    total_quantity: Optional[int] = Field(None, gt=0)
    start_at: Optional[int] = Field(None, gt=0)
    end_at: Optional[int] = Field(None, gt=0)
    max_prompt_count: Optional[int] = Field(None, gt=0, le=100)
    is_enabled: Optional[bool] = None

    @field_validator("rewards")
    @classmethod
    def _no_duplicate_reward_type(
        cls, v: Optional[List[RewardItem]]
    ) -> Optional[List[RewardItem]]:
        if v is None:
            return v
        types = [item.type for item in v]
        if len(types) != len(set(types)):
            raise ValueError("同一礼包内不能配置两个相同类型的奖励项")
        return v

    @model_validator(mode="after")
    def _validate_window(self) -> "GiftPackUpdateRequest":
        # 两端都传时在此校验；只传其一时由业务层与库中现值比对后校验
        if (
            self.start_at is not None
            and self.end_at is not None
            and self.end_at <= self.start_at
        ):
            raise ValueError("结束时间必须晚于开始时间")
        return self


class GiftPackSetEnabledRequest(BaseModel):
    """启用/停用礼包"""

    is_enabled: bool


# ==================== 响应 ====================


class GiftPackRewardView(BaseModel):
    """展示用的奖励项（对前端统一成一种形状）"""

    type: str
    amount: Optional[float] = None
    days: Optional[int] = None
    label: str = Field(..., description="人类可读的奖励描述，如「100 积分」")


class GiftPackItem(BaseModel):
    """礼包中心列表中的单个礼包"""

    id: int
    title: str
    description: Optional[str] = None
    rewards: List[GiftPackRewardView]
    start_at: int
    end_at: int
    total_quantity: Optional[int] = None
    claimed_count: int
    remaining: Optional[int] = Field(None, description="剩余份数，不限量时为 None")
    lifecycle: Literal["upcoming", "active", "ended"] = Field(
        ..., description="礼包相对当前时间的生命周期状态"
    )
    status: Literal[
        "claimable",
        "ineligible",
        "claimed",
        "sold_out",
        "ended",
        "upcoming",
        "disabled",
    ] = Field(..., description="该礼包对当前用户的状态")
    ineligible_reasons: List[str] = Field(
        default_factory=list, description="未满足领取条件的具体原因"
    )
    claimed_at: Optional[int] = None
    reward_snapshot: Optional[List[dict]] = Field(
        None, description="已领取时的实际发放内容"
    )


class GiftPackListResponse(BaseModel):
    packs: List[GiftPackItem]
    total: int


class GiftPackPromptItem(BaseModel):
    """开屏提醒弹窗中的单个礼包"""

    id: int
    title: str
    description: Optional[str] = None
    rewards: List[GiftPackRewardView]
    end_at: int
    total_quantity: Optional[int] = None
    remaining: Optional[int] = None


class GiftPackPromptCheckResponse(BaseModel):
    """开屏提醒判定结果；packs 为空表示不弹窗"""

    packs: List[GiftPackPromptItem] = Field(default_factory=list)


class GiftPackClaimRewardResult(BaseModel):
    """单个奖励项的发放结果"""

    type: str
    label: str
    success: bool
    service: Optional[str] = Field(None, description="Premium 奖励对应的媒体服务")
    new_expiry: Optional[str] = Field(None, description="Premium 的新到期时间")
    amount: Optional[float] = None
    days: Optional[int] = None
    skipped: Optional[str] = Field(
        None, description="跳过原因，如 lifetime 表示永久会员无需延长"
    )
    message: Optional[str] = None


class GiftPackClaimResponse(BaseModel):
    success: bool
    message: str
    pack_id: int
    results: List[GiftPackClaimRewardResult] = Field(default_factory=list)
    remaining: Optional[int] = None


# ==================== 管理端响应 ====================


class GiftPackAdminItem(BaseModel):
    """管理端礼包列表项"""

    id: int
    title: str
    description: Optional[str] = None
    rewards: List[dict]
    eligibility: Optional[dict] = None
    total_quantity: Optional[int] = None
    claimed_count: int
    remaining: Optional[int] = None
    start_at: int
    end_at: int
    max_prompt_count: int
    is_enabled: bool
    lifecycle: Literal["upcoming", "active", "ended"]
    can_delete: bool = Field(..., description="无任何领取记录时才可删除")
    created_by: Optional[int] = None
    created_at: int
    updated_at: int


class GiftPackAdminListResponse(BaseModel):
    packs: List[GiftPackAdminItem]
    total: int


class GiftPackStatsResponse(BaseModel):
    """单个礼包的领取统计"""

    pack_id: int
    title: str
    claimed_users: int = Field(..., description="领取人数")
    prompted_users: int = Field(..., description="被提醒过的人数")
    total_quantity: Optional[int] = None
    remaining: Optional[int] = None
    reward_totals: List[dict] = Field(
        default_factory=list, description="各类奖励的发放总量"
    )


class GiftPackClaimRecordItem(BaseModel):
    """单条领取记录"""

    tg_id: int
    tg_username: Optional[str] = None
    claimed_at: int
    reward_snapshot: Optional[List[dict]] = None


class GiftPackClaimRecordListResponse(BaseModel):
    records: List[GiftPackClaimRecordItem]
    total: int
