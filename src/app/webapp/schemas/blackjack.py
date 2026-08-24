"""21 点活动的请求与响应模型

**信息隐藏在本层强制**（设计决策 10）：响应模型不复用手牌行的 dump，而是显式
列出字段——`deck_seed` 与 `next_card_index` 根本不在模型里，任何路径都无法把它们
带进响应；`dealer_cards` 由 `from_hand()` 这个唯一构造入口在玩家回合裁剪为仅首张。

不依赖「路由里记得过滤」——那是最容易在后续改动中被绕过的写法。
"""

from typing import List, Optional

from pydantic import BaseModel, Field

# 与 blackjack_engine / BlackjackHand.status 一致
_STATUS_PLAYER_TURN = 1


class BlackjackDealRequest(BaseModel):
    """发牌请求"""

    bet_credits: int = Field(..., ge=1, description="基础注额，须为配置档位之一")


class BlackjackJackpotSeedRequest(BaseModel):
    """管理员注入奖池种子余额的请求"""

    amount: float = Field(..., gt=0, description="注入金额，须为正数")


class BlackjackHandResponse(BaseModel):
    """手牌状态。

    只经 `from_hand()` 构造，以确保庄家暗牌的裁剪无法被绕过。
    """

    id: int = Field(..., description="手牌 ID")
    status: int = Field(..., description="1=玩家回合 2=庄家回合 3=已结算 4=超时弃牌")
    bet_credits: int = Field(..., description="基础注额")
    doubled: bool = Field(..., description="是否已加倍")
    player_cards: List[str] = Field(..., description="玩家牌面")
    dealer_cards: List[str] = Field(..., description="庄家牌面；玩家回合期间仅含明牌")
    player_total: int = Field(..., description="玩家有效点数")
    dealer_total: Optional[int] = Field(
        None, description="庄家有效点数；玩家回合期间为 null（暗牌未公开）"
    )
    dealer_step_totals: List[int] = Field(
        default_factory=list,
        description=(
            "庄家每揭开一张牌后的累计点数，与 dealer_cards 一一对应。"
            "供前端回放补牌过程时显示中间点数，使其无需自行实现点数规则"
        ),
    )
    dealer_hidden: bool = Field(..., description="庄家是否仍有暗牌未公开")
    can_hit: bool = Field(..., description="当前是否可要牌")
    can_stand: bool = Field(..., description="当前是否可停牌")
    can_double: bool = Field(
        ..., description="当前是否可加倍（未含余额判定，余额由前端另行校验）"
    )
    can_surrender: bool = Field(
        False,
        description=(
            "当前是否可投降。由该手牌快照的投降开关与当前牌面共同判定，"
            "前端不必自行推导——管理员中途关闭开关不影响进行中的手牌"
        ),
    )
    outcome: Optional[str] = Field(
        None,
        description="blackjack / win / push / lose / bust / surrender；未结算为 null",
    )
    payout_credits: Optional[float] = Field(
        None, description="结算入账积分（含返还本金，已扣抽水）；不含奖池派彩"
    )
    rake_credits: Optional[float] = Field(None, description="本手抽水总额")
    jackpot_won: Optional[float] = Field(
        None, description="幸运奖池派彩，与赔付分别记账"
    )
    jackpot_trigger: Optional[str] = Field(
        None,
        description=(
            "命中奖池的牌型：triple_seven / suited_blackjack；未中奖为 null。"
            "由服务端判定，前端不得从牌面自行推断"
        ),
    )
    rake_waived: bool = Field(False, description="本手是否免抽水（当日首手）")
    decisions_total: int = Field(0, description="本手的决策次数")
    decisions_correct: int = Field(0, description="其中与基本策略一致的次数")
    created_at_ms: int = Field(..., description="发牌时间戳（毫秒）")
    settled_at: Optional[int] = Field(None, description="结算时间戳（秒）")

    @classmethod
    def from_hand(cls, hand: dict) -> "BlackjackHandResponse":
        """由 `db._blackjack_hand_to_dict()` 的结果构造响应。

        这是唯一的构造入口，庄家暗牌的裁剪落在此处：玩家回合期间庄家牌面只保留
        首张明牌，点数亦不返回（否则可反推暗牌）。种子与游标不在模型字段里，
        故即使入参含有也不会进入响应。
        """
        from app import blackjack_engine as engine

        status = int(hand.get("status") or 0)
        player_cards = list(hand.get("player_cards") or [])
        all_dealer_cards = list(hand.get("dealer_cards") or [])

        in_player_turn = status == _STATUS_PLAYER_TURN
        if in_player_turn:
            # 玩家回合：只公开庄家首张明牌，暗牌与点数一律不返回
            dealer_cards = all_dealer_cards[:1]
            dealer_total = None
            dealer_hidden = len(all_dealer_cards) > 1
        else:
            # 庄家回合与终态：公开全部庄家牌面
            dealer_cards = all_dealer_cards
            dealer_total = engine.hand_total(all_dealer_cards)
            dealer_hidden = False

        # 逐张的累计点数由已裁剪的 dealer_cards 算出，故玩家回合期间只会有明牌
        # 那一项，不会泄露暗牌。前端回放补牌过程时直接取用，无需自己实现点数规则。
        dealer_step_totals = [
            engine.hand_total(dealer_cards[: i + 1]) for i in range(len(dealer_cards))
        ]

        # 命中奖池的牌型在服务端判定：触发条件是本活动自己的规则（且随配置演进），
        # 让前端从牌面反推等于把这套规则实现两遍，改一处就会与另一处失配。
        jackpot_trigger = None
        if float(hand.get("jackpot_won") or 0) > 0:
            if engine.is_triple_seven(player_cards):
                jackpot_trigger = "triple_seven"
            elif engine.is_suited_blackjack(player_cards):
                jackpot_trigger = "suited_blackjack"

        return cls(
            id=int(hand["id"]),
            status=status,
            bet_credits=int(hand.get("bet_credits") or 0),
            doubled=int(hand.get("doubled") or 0) == 1,
            player_cards=player_cards,
            dealer_cards=dealer_cards,
            player_total=engine.hand_total(player_cards),
            dealer_total=dealer_total,
            dealer_step_totals=dealer_step_totals,
            dealer_hidden=dealer_hidden,
            can_hit=engine.can_hit(player_cards, status),
            can_stand=in_player_turn,
            can_double=engine.can_double(player_cards, status),
            can_surrender=bool(hand.get("surrender_enabled"))
            and engine.can_surrender(
                player_cards, status, int(hand.get("doubled") or 0) == 1
            ),
            outcome=hand.get("outcome"),
            payout_credits=hand.get("payout_credits"),
            rake_credits=hand.get("rake_credits"),
            jackpot_won=hand.get("jackpot_won"),
            jackpot_trigger=jackpot_trigger,
            rake_waived=bool(hand.get("rake_waived")),
            decisions_total=int(hand.get("decisions_total") or 0),
            decisions_correct=int(hand.get("decisions_correct") or 0),
            created_at_ms=int(hand.get("created_at_ms") or 0),
            settled_at=hand.get("settled_at"),
        )


class BlackjackDecisionFeedback(BaseModel):
    """单次决策的基本策略评判。仅供事后反馈，系统不据此阻止或替代玩家的选择。"""

    action: str = Field(..., description="玩家实际执行的动作")
    recommended: str = Field(..., description="基本策略在该局面下建议的动作")
    correct: bool = Field(..., description="两者是否一致")


class BlackjackActionResponse(BaseModel):
    """发牌与各动作的统一响应"""

    success: bool = Field(True, description="是否成功")
    message: str = Field("", description="提示信息")
    hand: BlackjackHandResponse = Field(..., description="手牌状态")
    settled: bool = Field(..., description="本次操作是否已使手牌结算")
    current_credits: float = Field(..., description="操作后用户的当前积分")
    decision: Optional[BlackjackDecisionFeedback] = Field(
        None, description="本次动作的基本策略评判；发牌无决策，故为 null"
    )
    jackpot_balance: float = Field(0, description="幸运奖池的当前余额")


class BlackjackCurrentHandResponse(BaseModel):
    """当前进行中手牌的查询响应"""

    hand: Optional[BlackjackHandResponse] = Field(
        None, description="进行中的手牌；无则为 null"
    )
    current_credits: float = Field(..., description="用户当前积分")
    jackpot_balance: float = Field(0, description="幸运奖池的当前余额")
    free_hands_remaining: int = Field(
        0, description="今日剩余的免抽水手数，仅供下注界面标示"
    )


class BlackjackUserStatsResponse(BaseModel):
    """用户的 21 点个人统计"""

    total_hands: int = Field(..., description="累计手数（已结束）")
    net_credits: float = Field(..., description="累计净积分变动（不含奖池派彩）")
    max_win: float = Field(..., description="单手最大净赢利（不含奖池派彩）")
    win_rate: float = Field(0, description="胜率（百分比）")
    accuracy: float = Field(0, description="决策准确率（百分比）")
    decisions_total: int = Field(0, description="累计决策次数")
    jackpot_total: float = Field(0, description="累计奖池派彩")
    surrender_hands: int = Field(
        0, description="累计投降手数；计入胜率分母，不计入分子"
    )


class BlackjackPublicConfigResponse(BaseModel):
    """对用户公开的参数，供牌桌与规则说明渲染。

    只含用户需要知道的项，不含 `rake_burn_bp` 等运营内部口径。前端不得硬编码
    这些数字，一律取自本接口，以免与后端配置漂移。
    """

    enabled: bool = Field(..., description="活动是否开放")
    bet_options: List[int] = Field(..., description="可选注额档位")
    min_credits: int = Field(..., description="参与门槛")
    blackjack_payout: float = Field(..., description="天胡赔率（净赢利倍数）")
    rake_percent_on_profit: float = Field(
        ..., description="抽水比率（百分比），仅对净赢利计取"
    )
    dealer_hits_soft_17: bool = Field(..., description="庄家软 17 是否继续要牌")
    surrender_enabled: bool = Field(
        True,
        description=(
            "投降是否开放，供前端决定是否渲染投降按钮与规则条目。"
            "返还比例固定为基础注额的一半，不可配置"
        ),
    )
    hand_timeout_minutes: int = Field(..., description="手牌超时时限（分钟）")
    free_hands_per_day: int = Field(0, description="每日免抽水手数")
    jackpot_enabled: bool = Field(True, description="幸运奖池是否启用")
    jackpot_balance: float = Field(0, description="幸运奖池的当前余额")
    jackpot_suited_bj_pct: float = Field(
        10, description="同花天胡派发奖池余额的百分比；三张 7 派发全额"
    )


class BlackjackAdminConfig(BaseModel):
    """管理员可见与可改的完整配置"""

    enabled: bool = Field(..., description="服务端停用开关")
    bet_options: List[int] = Field(..., min_length=1, description="注额档位")
    min_credits: int = Field(..., ge=1, description="参与门槛")
    rake_bp_on_profit: int = Field(
        ..., ge=0, le=10000, description="抽水比率（基点），仅对净赢利"
    )
    rake_burn_bp: int = Field(
        ..., ge=0, le=10000, description="抽水中销毁的部分（基点）"
    )
    rake_jackpot_bp: int = Field(
        ..., ge=0, le=10000, description="抽水中注入幸运奖池的部分（基点）"
    )
    dealer_hits_soft_17: bool = Field(..., description="庄家软 17 是否继续要牌")
    surrender_enabled: bool = Field(
        True,
        description=(
            "投降开关。关闭后仅影响此后发出的手牌——进行中的手牌按其发牌时的"
            "快照仍可投降。返还比例固定为一半，不设配置项"
        ),
    )
    blackjack_payout: float = Field(..., gt=0, description="天胡赔率")
    hand_timeout_minutes: int = Field(..., ge=1, description="手牌超时时限（分钟）")
    min_deal_interval_seconds: float = Field(
        ..., ge=0, description="两次发牌的最小间隔（秒）"
    )
    jackpot_enabled: bool = Field(True, description="幸运奖池是否启用")
    jackpot_suited_bj_pct: float = Field(
        10, ge=0, le=100, description="同花天胡派发奖池余额的百分比"
    )
    jackpot_notify_enabled: bool = Field(
        True, description="中奖时是否向群组播报（需配置 TG_GROUP_ID）"
    )
    free_hands_per_day: int = Field(1, ge=0, description="每日免抽水手数")
    rank_min_hands: int = Field(
        100, ge=1, description="入榜的最低手数（准确率榜与胜率榜）"
    )
    badge_min_hands: int = Field(2000, ge=1, description="游戏王勋章的手数阈值")
    badge_min_accuracy: float = Field(
        80, ge=0, le=100, description="游戏王勋章的决策准确率阈值（百分比）"
    )


class BlackjackConfigUpdateRequest(BlackjackAdminConfig):
    """更新 21 点配置请求：字段与管理员可见配置完全一致"""


class BlackjackAdminStatsResponse(BaseModel):
    """21 点的运营聚合统计，仅管理员可见。

    金额项只统计终态手牌，故 `active_hands` 对应的押注尚未反映在
    `total_wagered` 与 `net_credits` 中。
    """

    total_hands: int = Field(..., description="累计已结束手数")
    active_hands: int = Field(..., description="当前进行中手数")
    total_players: int = Field(..., description="参与过的去重用户数")
    today_hands: int = Field(..., description="今日发出的手数（含进行中）")
    total_wagered: float = Field(..., description="累计押注（加倍手计两份注额）")
    total_rake: float = Field(..., description="累计抽水总额")
    net_credits: float = Field(
        ...,
        description="玩家视角的净积分变动（含奖池派彩）；为负表示活动在净回收积分",
    )
    jackpot_paid: float = Field(..., description="累计奖池派彩")
    jackpot_balance: float = Field(..., description="幸运奖池当前余额")
