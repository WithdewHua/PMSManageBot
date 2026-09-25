"""
礼包（Gift Pack）相关的 Web API 模型定义
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class WheelFreeSpinsReward(BaseModel):
    """大转盘免费机会奖励项：每次机会自领取时起 expiry_days 天内有效"""

    type: Literal["wheel_free_spins"] = "wheel_free_spins"
    count: int = Field(..., ge=1, le=100, description="发放的免费机会次数")
    expiry_days: int = Field(..., ge=1, le=365, description="每次机会的有效天数")


class TournamentWalletReward(BaseModel):
    """争霸赛余额奖励项：计入争霸赛余额，不计入积分"""

    type: Literal["tournament_wallet"] = "tournament_wallet"
    amount: float = Field(..., gt=0, le=100000, description="发放的争霸赛余额数量")


class InviteCodesReward(BaseModel):
    """邀请码奖励项"""

    type: Literal["invite_codes"] = "invite_codes"
    count: int = Field(..., ge=1, le=20, description="生成的邀请码数量")
    privileged: bool = Field(False, description="是否为特权邀请码")


class LineScheduleUnlockReward(BaseModel):
    """线路调度解锁奖励项：为所有已绑定的媒体服务永久解锁"""

    type: Literal["line_schedule_unlock"] = "line_schedule_unlock"


class DownloadUnlockReward(BaseModel):
    """下载权限解锁奖励项：为所有已绑定的媒体服务永久解锁"""

    type: Literal["download_unlock"] = "download_unlock"


RewardItem = Annotated[
    CreditsReward
    | PremiumDaysReward
    | WheelFreeSpinsReward
    | TournamentWalletReward
    | InviteCodesReward
    | LineScheduleUnlockReward
    | DownloadUnlockReward,
    Field(discriminator="type"),
]

# ==================== 受众与领取条件（D1/D2） ====================


class _ConditionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AllWindow(_ConditionModel):
    kind: Literal["all"] = "all"


class PackWindow(_ConditionModel):
    kind: Literal["pack"] = "pack"


class DaysWindow(_ConditionModel):
    kind: Literal["days"] = "days"
    days: int = Field(..., ge=1, le=365)


Window = Annotated[AllWindow | PackWindow | DaysWindow, Field(discriminator="kind")]


class UserListCondition(_ConditionModel):
    type: Literal["user_list"] = "user_list"
    mode: Literal["include", "exclude"]
    tg_ids: list[int] = Field(..., max_length=5000)


class PremiumCondition(_ConditionModel):
    type: Literal["premium"] = "premium"
    state: Literal["active", "none"]


class BoundCondition(_ConditionModel):
    type: Literal["bound"] = "bound"
    service: Literal["any", "plex", "emby"] = "any"


class CreditsCondition(_ConditionModel):
    type: Literal["credits"] = "credits"
    min: float | None = Field(None, ge=0)
    max: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _validate_range(self) -> "CreditsCondition":
        if self.min is None and self.max is None:
            raise ValueError("积分条件至少配置最低或最高积分")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("最低积分不能超过最高积分")
        return self


class BadgeCondition(_ConditionModel):
    type: Literal["badge"] = "badge"
    badge_id: int = Field(..., gt=0)


class ClaimedPackCondition(_ConditionModel):
    type: Literal["claimed_pack"] = "claimed_pack"
    pack_id: int = Field(..., gt=0)


class _CountCondition(_ConditionModel):
    min: int = Field(..., gt=0)
    window: Window = Field(default_factory=AllWindow)


class WheelSpinsCondition(_CountCondition):
    type: Literal["wheel_spins"] = "wheel_spins"
    paid_only: bool = True


class BlackjackHandsCondition(_CountCondition):
    type: Literal["blackjack_hands"] = "blackjack_hands"
    min_bet: float | None = Field(None, gt=0)
    min_accuracy: float | None = Field(None, ge=0, le=100)


class TreasureIssuesCondition(_CountCondition):
    type: Literal["treasure_issues"] = "treasure_issues"


class PredictionBetsCondition(_CountCondition):
    type: Literal["prediction_bets"] = "prediction_bets"


class AuctionParticipationsCondition(_CountCondition):
    type: Literal["auction_participations"] = "auction_participations"


class TournamentEntriesCondition(_CountCondition):
    type: Literal["tournament_entries"] = "tournament_entries"


class InviteesCondition(_CountCondition):
    type: Literal["invitees"] = "invitees"
    window: AllWindow = Field(default_factory=AllWindow)


class WatchedHoursCondition(_CountCondition):
    type: Literal["watched_hours"] = "watched_hours"
    min: float = Field(..., gt=0)
    window: AllWindow = Field(default_factory=AllWindow)


LeafCondition = Annotated[
    PremiumCondition
    | BoundCondition
    | CreditsCondition
    | BadgeCondition
    | ClaimedPackCondition
    | WheelSpinsCondition
    | BlackjackHandsCondition
    | TreasureIssuesCondition
    | PredictionBetsCondition
    | AuctionParticipationsCondition
    | TournamentEntriesCondition
    | InviteesCondition
    | WatchedHoursCondition,
    Field(discriminator="type"),
]


class AnyOf(_ConditionModel):
    type: Literal["any_of"] = "any_of"
    items: list[LeafCondition] = Field(..., min_length=2)


AudienceCondition = Annotated[
    UserListCondition
    | PremiumCondition
    | BoundCondition
    | CreditsCondition
    | BadgeCondition
    | ClaimedPackCondition
    | WheelSpinsCondition
    | BlackjackHandsCondition
    | TreasureIssuesCondition
    | PredictionBetsCondition
    | AuctionParticipationsCondition
    | TournamentEntriesCondition
    | InviteesCondition
    | WatchedHoursCondition
    | AnyOf,
    Field(discriminator="type"),
]
RequirementCondition = Annotated[LeafCondition | AnyOf, Field(discriminator="type")]


def _has_include_audience(items: list[AudienceCondition] | None) -> bool:
    return any(
        isinstance(item, UserListCondition) and item.mode == "include"
        for item in items or []
    )


# 保留旧模型的导出以兼容 schemas/__init__.py；新建/编辑请求不再接受 eligibility。
class GiftPackEligibility(BaseModel):
    """领取资格条件，全部为可选；未配置任何条件即对所有用户开放"""

    min_credits: float | None = Field(None, ge=0, description="最低积分要求")
    require_premium: bool = Field(False, description="是否要求 Premium 用户")
    require_binding: Literal["any", "plex", "emby"] | None = Field(
        None, description="要求已绑定媒体账号：any=不限服务，plex/emby=指定服务"
    )


# ==================== 管理端请求 ====================


class GiftPackCreateRequest(BaseModel):
    """创建礼包"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    rewards: list[RewardItem] = Field(..., min_length=1, description="至少一项奖励")
    audience: list[AudienceCondition] | None = None
    requirements: list[RequirementCondition] | None = None
    total_quantity: int | None = Field(
        None, gt=0, description="限量份数，不传表示不限量"
    )
    start_at: int = Field(..., gt=0, description="开始时间戳（epoch 秒）")
    end_at: int = Field(..., gt=0, description="结束时间戳（epoch 秒）")
    task_end_at: int | None = Field(None, gt=0, description="任务截止时间（epoch 秒）")
    max_task_prompt_count: int = Field(2, ge=0, le=100)
    notify_audience_on_start: bool = False
    max_prompt_count: int = Field(
        3, gt=0, le=100, description="对单个用户的提醒次数上限"
    )
    is_enabled: bool = Field(True, description="是否启用")

    @field_validator("rewards")
    @classmethod
    def _no_duplicate_reward_type(cls, v: list[RewardItem]) -> list[RewardItem]:
        types = [item.type for item in v]
        if len(types) != len(set(types)):
            raise ValueError("同一礼包内不能配置两个相同类型的奖励项")
        return v

    @field_validator("audience", "requirements")
    @classmethod
    def _empty_conditions_are_none(cls, v: list | None) -> list | None:
        return v or None

    @model_validator(mode="after")
    def _validate_window(self) -> "GiftPackCreateRequest":
        if self.end_at <= self.start_at:
            raise ValueError("结束时间必须晚于开始时间")
        if self.task_end_at is not None and not (
            self.start_at < self.task_end_at <= self.end_at
        ):
            raise ValueError("任务截止时间必须晚于开始时间且不晚于结束时间")
        if self.notify_audience_on_start and not _has_include_audience(self.audience):
            raise ValueError("开启开始通知要求受众顶层包含 include 指定名单")
        return self


class GiftPackUpdateRequest(BaseModel):
    """编辑礼包：所有字段可选，仅更新传入的字段"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    rewards: list[RewardItem] | None = Field(None, min_length=1)
    audience: list[AudienceCondition] | None = None
    requirements: list[RequirementCondition] | None = None
    total_quantity: int | None = Field(None, gt=0)
    start_at: int | None = Field(None, gt=0)
    end_at: int | None = Field(None, gt=0)
    task_end_at: int | None = Field(None, gt=0)
    max_task_prompt_count: int | None = Field(None, ge=0, le=100)
    notify_audience_on_start: bool | None = None
    max_prompt_count: int | None = Field(None, gt=0, le=100)
    is_enabled: bool | None = None

    @field_validator("rewards")
    @classmethod
    def _no_duplicate_reward_type(
        cls, v: list[RewardItem] | None
    ) -> list[RewardItem] | None:
        if v is None:
            return v
        types = [item.type for item in v]
        if len(types) != len(set(types)):
            raise ValueError("同一礼包内不能配置两个相同类型的奖励项")
        return v

    @field_validator("audience", "requirements")
    @classmethod
    def _empty_conditions_are_none(cls, v: list | None) -> list | None:
        return v or None

    @model_validator(mode="after")
    def _validate_window(self) -> "GiftPackUpdateRequest":
        # 部分更新缺失的值必须在 db 层与原有礼包合并后再次校验。
        if (
            self.start_at is not None
            and self.end_at is not None
            and self.end_at <= self.start_at
        ):
            raise ValueError("结束时间必须晚于开始时间")
        if self.task_end_at is not None and (
            (self.start_at is not None and self.task_end_at <= self.start_at)
            or (self.end_at is not None and self.task_end_at > self.end_at)
        ):
            raise ValueError("任务截止时间必须晚于开始时间且不晚于结束时间")
        if (
            self.notify_audience_on_start
            and "audience" in self.model_fields_set
            and not _has_include_audience(self.audience)
        ):
            raise ValueError("开启开始通知要求受众顶层包含 include 指定名单")
        return self


class GiftPackSetEnabledRequest(BaseModel):
    """启用/停用礼包"""

    is_enabled: bool


# ==================== 响应 ====================


class GiftPackRewardView(BaseModel):
    """展示用的奖励项（对前端统一成一种形状）"""

    type: str
    amount: float | None = None
    days: int | None = None
    count: int | None = None
    expiry_days: int | None = None
    privileged: bool | None = None
    label: str = Field(..., description="人类可读的奖励描述，如「100 积分」")


class RequirementSubProgress(BaseModel):
    label: str
    current: float
    target: float
    met: bool


class RequirementLeafProgress(BaseModel):
    type: Literal[
        "premium",
        "bound",
        "credits",
        "badge",
        "claimed_pack",
        "wheel_spins",
        "blackjack_hands",
        "treasure_issues",
        "prediction_bets",
        "auction_participations",
        "tournament_entries",
        "invitees",
        "watched_hours",
    ]
    label: str
    met: bool
    current: float | None = None
    target: float | None = None
    window: Window | None = None
    sub: list[RequirementSubProgress] = Field(default_factory=list)


class RequirementGroupProgress(BaseModel):
    type: Literal["any_of"] = "any_of"
    label: str = "任选其一"
    met: bool
    items: list[RequirementLeafProgress]


RequirementProgress = Annotated[
    RequirementLeafProgress | RequirementGroupProgress,
    Field(discriminator="type"),
]


class GiftPackItem(BaseModel):
    """礼包中心列表中的单个礼包"""

    id: int
    title: str
    description: str | None = None
    rewards: list[GiftPackRewardView]
    start_at: int
    end_at: int
    total_quantity: int | None = None
    claimed_count: int
    remaining: int | None = Field(None, description="剩余份数，不限量时为 None")
    lifecycle: Literal["upcoming", "active", "claim_only", "ended"] = Field(
        ..., description="礼包相对当前时间的生命周期状态"
    )
    status: Literal[
        "claimable",
        "in_progress",
        "claimed",
        "sold_out",
        "ended",
        "upcoming",
        "disabled",
    ] = Field(..., description="该礼包对当前用户的状态")
    requirements: list[RequirementProgress] = Field(default_factory=list)
    task_closed: bool = False
    task_end_at: int | None = None
    claimed_at: int | None = None
    reward_snapshot: list[dict] | None = Field(
        None, description="已领取时的实际发放内容"
    )


class GiftPackListResponse(BaseModel):
    packs: list[GiftPackItem]
    total: int


class GiftPackPromptItem(BaseModel):
    """开屏提醒弹窗中的单个礼包"""

    id: int
    title: str
    description: str | None = None
    rewards: list[GiftPackRewardView]
    end_at: int
    total_quantity: int | None = None
    remaining: int | None = None


class GiftPackTaskPromptItem(GiftPackPromptItem):
    """未达成礼包的任务提醒，附逐项进度。"""

    requirements: list[RequirementProgress] = Field(default_factory=list)


class GiftPackPromptCheckResponse(BaseModel):
    """开屏提醒判定结果；两类礼包均为空时不弹窗。"""

    packs: list[GiftPackPromptItem] = Field(default_factory=list)
    task_packs: list[GiftPackTaskPromptItem] = Field(default_factory=list)


class GiftPackClaimRewardResult(BaseModel):
    """单个奖励项的发放结果"""

    type: str
    label: str
    success: bool
    service: str | None = Field(None, description="Premium 奖励对应的媒体服务")
    new_expiry: str | None = Field(None, description="Premium 的新到期时间")
    amount: float | None = None
    days: int | None = None
    skipped: str | None = Field(
        None, description="跳过原因，如 lifetime 表示永久会员无需延长"
    )
    message: str | None = None
    count: int | None = Field(None, description="免费机会次数 / 邀请码枚数")
    expires_at: int | None = Field(None, description="免费机会到期时间（epoch 秒）")
    balance_after: float | None = Field(None, description="到账后的争霸赛余额")
    codes: list[str] | None = Field(None, description="本次生成的邀请码")
    privileged: bool | None = None


class GiftPackClaimResponse(BaseModel):
    success: bool
    message: str
    pack_id: int
    results: list[GiftPackClaimRewardResult] = Field(default_factory=list)
    remaining: int | None = None


# ==================== 管理端响应 ====================


class GiftPackAdminItem(BaseModel):
    """管理端礼包列表项"""

    id: int
    title: str
    description: str | None = None
    rewards: list[dict]
    audience: list[AudienceCondition] | None = None
    requirements: list[RequirementCondition] | None = None
    audience_summary: str = ""
    requirements_summary: str = ""
    audience_size: int | None = None
    claim_rate: float | None = None
    total_quantity: int | None = None
    claimed_count: int
    remaining: int | None = None
    start_at: int
    end_at: int
    task_end_at: int | None = None
    max_prompt_count: int
    max_task_prompt_count: int = 0
    notify_audience_on_start: bool = False
    task_prompted_users: int = 0
    is_enabled: bool
    lifecycle: Literal["upcoming", "active", "claim_only", "ended"]
    can_delete: bool = Field(..., description="无任何领取记录时才可删除")
    created_by: int | None = None
    created_at: int
    updated_at: int


class GiftPackAdminListResponse(BaseModel):
    packs: list[GiftPackAdminItem]
    total: int


class GiftPackStatsResponse(BaseModel):
    """单个礼包的领取统计"""

    pack_id: int
    title: str
    claimed_users: int = Field(..., description="领取人数")
    prompted_users: int = Field(..., description="收到领取提醒的人数")
    task_prompted_users: int = Field(0, description="收到任务提醒的人数")
    audience_size: int | None = None
    claim_rate: float | None = None
    total_quantity: int | None = None
    remaining: int | None = None
    reward_totals: list[dict] = Field(
        default_factory=list, description="各类奖励的发放总量"
    )


class GiftPackClaimRecordItem(BaseModel):
    """单条领取记录"""

    tg_id: int
    tg_username: str | None = None
    claimed_at: int
    reward_snapshot: list[dict] | None = None


class GiftPackClaimRecordListResponse(BaseModel):
    records: list[GiftPackClaimRecordItem]
    total: int
