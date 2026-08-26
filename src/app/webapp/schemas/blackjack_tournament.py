"""21 点锦标赛的请求与响应模型

赛内手牌沿用现金局的 `BlackjackHandResponse`：庄家暗牌的裁剪、种子与游标的排除
都落在那个模型的 `from_hand()` 构造入口上，两侧共用同一道闸门，不在此另写一份
——另写一份就意味着信息隐藏有两套实现，改一处会漏另一处。

赛事本身的模型在此定义。`tournament_seed` 这个概念**不存在**（见 design 决策 6），
故无需考虑它的过滤。
"""

from typing import List, Optional

from app.webapp.schemas.blackjack import BlackjackHandResponse
from pydantic import BaseModel, Field


class TournamentEntryResponse(BaseModel):
    """某用户在某赛事中的报名状态"""

    tg_id: int = Field(..., description="报名者")
    chips: int = Field(..., description="当前赛内筹码")
    hands_played: int = Field(..., description="已打手数")
    status: int = Field(..., description="1=进行中 2=已打完 3=已淘汰")
    eligible: bool = Field(
        ...,
        description=(
            "是否具备派奖资格。仅已打完或已淘汰者具备——"
            "未打满且未被淘汰者不参与派奖，其报名费留在奖池中"
        ),
    )
    final_rank: Optional[int] = Field(None, description="最终名次；未结算为 null")
    prize_credits: Optional[float] = Field(
        None, description="派奖积分；未结算为 null，已结算但无派奖为 0"
    )
    registered_at_ms: int = Field(..., description="报名时点（毫秒），并列时的决胜依据")

    @classmethod
    def from_entry(cls, entry: dict) -> "TournamentEntryResponse":
        return cls(
            tg_id=int(entry["tg_id"]),
            chips=int(entry["chips"]),
            hands_played=int(entry["hands_played"]),
            status=int(entry["status"]),
            eligible=bool(entry.get("eligible")),
            final_rank=entry.get("final_rank"),
            prize_credits=entry.get("prize_credits"),
            registered_at_ms=int(entry["registered_at_ms"]),
        )


class TournamentStandingRow(TournamentEntryResponse):
    """排名行：在报名状态之上补展示用的昵称与临时位次"""

    display_name: str = Field("", description="展示用昵称")
    provisional_rank: Optional[int] = Field(
        None, description="进行中赛事的临时位次；已结算时为 null（以 final_rank 为准）"
    )


class TournamentResponse(BaseModel):
    """赛事详情"""

    id: int = Field(..., description="赛事 ID")
    title: str = Field(..., description="赛事名称")
    description: Optional[str] = Field(None, description="赛事说明")
    status: int = Field(..., description="1=报名中 2=进行中 3=已结算 4=已取消")
    buy_in_credits: int = Field(..., description="报名费（积分）")
    starting_chips: int = Field(..., description="起始筹码")
    total_hands: int = Field(..., description="总手数")
    min_bet_chips: int = Field(..., description="最小注（筹码）")
    max_bet_chips: int = Field(..., description="最大注（筹码）")
    bet_step_chips: int = Field(..., description="下注步进，注额须为其整数倍")
    min_entrants: int = Field(..., description="最低开赛人数")
    max_entrants: int = Field(..., description="人数上限，满员即开")
    entrant_count: int = Field(..., description="当前报名人数")
    payout_structure: List[float] = Field(
        ..., description="派奖档位百分比；具备资格者少于档位数时截断并重新归一"
    )
    prize_pool_gross: float = Field(..., description="奖池总额（含抽水）")
    prize_pool_net: float = Field(..., description="实际可派发额（已扣抽水）")
    rake_bp: int = Field(..., description="抽水比率（基点），该部分直接销毁")
    seeded_prize_credits: float = Field(
        0,
        description=(
            "管理员注入的奖池补贴。**必须暴露**：管理端编辑赛事时要用它回填表单，"
            "否则保存会把补贴静默重置为 0，奖池随之缩水而管理员毫无察觉"
        ),
    )
    dealer_hits_soft_17: bool = Field(..., description="庄家软 17 是否继续要牌")
    blackjack_payout: float = Field(..., description="天胡赔率")
    surrender_enabled: bool = Field(..., description="赛内是否可投降")
    hand_timeout_minutes: int = Field(..., description="单手超时时限（分钟）")
    register_deadline_ms: int = Field(..., description="报名截止（毫秒）")
    play_deadline_ms: int = Field(..., description="完赛截止（毫秒）")
    settled_at: Optional[int] = Field(None, description="结算时点（秒）")
    my_entry: Optional[TournamentEntryResponse] = Field(
        None, description="当前用户的报名；未报名为 null"
    )

    @classmethod
    def from_tournament(cls, t: dict) -> "TournamentResponse":
        entry = t.get("my_entry")
        return cls(
            id=int(t["id"]),
            title=t["title"],
            description=t.get("description"),
            status=int(t["status"]),
            buy_in_credits=int(t["buy_in_credits"]),
            starting_chips=int(t["starting_chips"]),
            total_hands=int(t["total_hands"]),
            min_bet_chips=int(t["min_bet_chips"]),
            max_bet_chips=int(t["max_bet_chips"]),
            bet_step_chips=int(t["bet_step_chips"]),
            min_entrants=int(t["min_entrants"]),
            max_entrants=int(t["max_entrants"]),
            entrant_count=int(t["entrant_count"]),
            payout_structure=list(t.get("payout_structure") or []),
            prize_pool_gross=float(t["prize_pool_gross"]),
            prize_pool_net=float(t["prize_pool_net"]),
            rake_bp=int(t["rake_bp"]),
            seeded_prize_credits=float(t.get("seeded_prize_credits") or 0),
            dealer_hits_soft_17=bool(t["dealer_hits_soft_17"]),
            blackjack_payout=float(t["blackjack_payout"]),
            surrender_enabled=bool(t["surrender_enabled"]),
            hand_timeout_minutes=int(t["hand_timeout_minutes"]),
            register_deadline_ms=int(t["register_deadline_ms"]),
            play_deadline_ms=int(t["play_deadline_ms"]),
            settled_at=t.get("settled_at"),
            my_entry=TournamentEntryResponse.from_entry(entry) if entry else None,
        )


class TournamentListResponse(BaseModel):
    """赛事列表"""

    success: bool = Field(True)
    tournaments: List[TournamentResponse] = Field(default_factory=list)


class TournamentStandingsResponse(BaseModel):
    """全场排名"""

    success: bool = Field(True)
    tournament_id: int = Field(...)
    status: int = Field(..., description="赛事状态，供前端判断是临时位次还是最终名次")
    standings: List[TournamentStandingRow] = Field(default_factory=list)


class TournamentRegisterResponse(BaseModel):
    """报名结果"""

    success: bool = Field(True)
    message: str = Field("")
    tournament: TournamentResponse = Field(...)
    entry: TournamentEntryResponse = Field(...)
    started: bool = Field(False, description="本次报名是否触发了满员开赛")
    current_credits: float = Field(..., description="扣除报名费后的积分")


class TournamentDealRequest(BaseModel):
    """赛内发牌请求"""

    bet_chips: int = Field(
        ..., ge=1, description="赛内注额，须在区间内且为步进的整数倍"
    )


class TournamentActionResponse(BaseModel):
    """赛内发牌与各动作的统一响应

    与现金局的动作响应刻意不同的两处：没有 `decision`（赛内不做基本策略评判），
    也没有 `jackpot_balance`（赛内不触发奖池）。多给这两个字段会让前端以为赛内
    也有这套语义。

    四个赛内状态字段**可为 null**：结算被他人抢先（十分钟一次的兜底扫描与用户
    自己的停牌撞在一起就会发生）时，这一份响应无从得知最新的筹码与进度。此时
    宁可留空让前端保持原值，也不能兜底成 0——那会把玩家的筹码栈显示成 0、进度
    回退到 0/N，看上去像资产凭空蒸发。
    """

    success: bool = Field(True)
    message: str = Field("")
    hand: BlackjackHandResponse = Field(..., description="手牌状态")
    settled: bool = Field(False, description="本次操作是否使手牌结算")
    chips: Optional[int] = Field(None, description="操作后的赛内筹码；未知则为 null")
    hands_played: Optional[int] = Field(None, description="已打手数；未知则为 null")
    hands_remaining: Optional[int] = Field(None, description="剩余手数；未知则为 null")
    entry_status: Optional[int] = Field(
        None, description="1=进行中 2=已打完 3=已淘汰；未知则为 null"
    )


class TournamentCurrentHandResponse(BaseModel):
    """赛内当前手牌与筹码状态"""

    success: bool = Field(True)
    tournament: TournamentResponse = Field(...)
    entry: TournamentEntryResponse = Field(...)
    hand: Optional[BlackjackHandResponse] = Field(
        None, description="进行中的赛内手牌；无则为 null"
    )
    hands_remaining: int = Field(..., description="剩余手数")


class TournamentCreateRequest(BaseModel):
    """管理员创建赛事"""

    title: Optional[str] = Field(
        None, description="赛事名称；留空则自动生成「21 点锦标赛 · 第 N 期」"
    )
    description: Optional[str] = Field(None, description="赛事说明")
    buy_in_credits: int = Field(..., gt=0, description="报名费（积分）")
    starting_chips: int = Field(..., gt=0, description="起始筹码")
    total_hands: int = Field(..., gt=0, description="总手数")
    min_bet_chips: int = Field(..., gt=0, description="最小注")
    max_bet_chips: int = Field(..., gt=0, description="最大注")
    bet_step_chips: int = Field(10, gt=0, description="下注步进")
    min_entrants: int = Field(..., gt=0, description="最低开赛人数")
    max_entrants: int = Field(..., gt=0, description="人数上限")
    rake_bp: int = Field(1000, ge=0, le=10000, description="抽水比率（基点）")
    seeded_prize_credits: float = Field(
        0, ge=0, description="管理员补贴，本变更的增发路径之一，须显式给出"
    )
    payout_structure: Optional[List[float]] = Field(
        None, description="派奖档位百分比，之和须为 100；不给则用默认 [50, 30, 20]"
    )
    register_deadline_ms: int = Field(..., description="报名截止（毫秒）")
    play_deadline_ms: int = Field(..., description="完赛截止（毫秒）")


class TournamentUpdateRequest(TournamentCreateRequest):
    """管理员修改赛事。仅报名中的赛事可改。

    `title` 在此**改回必填**：创建时留空的含义是「自动生成」，修改时留空的含义
    却是「清空名字」，后者应当被拒。不设 `min_length` 是为了让空串落到 DB 层，
    由那里抛出的业务错误被翻译成中文提示，而不是一条 422 的字段校验噪音。
    """

    title: str = Field(..., description="赛事名称；修改时必填")


class TournamentAdminResponse(BaseModel):
    """管理端的单场赛事响应"""

    success: bool = Field(True)
    message: str = Field("")
    tournament: TournamentResponse = Field(...)


class TournamentConsistencyResponse(BaseModel):
    """`entrant_count` 与 entry 实际行数的比对结果

    两者只在同一事务内一起变动，本不该漂移；但 `entrant_count` 是奖池推导的因子，
    一旦漂移会直接影响派奖金额，故提供一处显式校验。
    """

    success: bool = Field(True)
    tournament_id: int = Field(...)
    entrant_count: int = Field(..., description="赛事行上的计数")
    entry_rows: int = Field(..., description="entry 表的实际行数")
    consistent: bool = Field(..., description="两者是否一致")
