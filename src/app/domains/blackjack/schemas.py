"""21 点活动的请求与响应模型

**信息隐藏在本层强制**（设计决策 10）：响应模型不复用手牌行的 dump，而是显式
列出字段——`deck_seed` 与 `next_card_index` 根本不在模型里，任何路径都无法把它们
带进响应；`dealer_cards` 由 `from_hand()` 这个唯一构造入口在玩家回合裁剪为仅首张。

不依赖「路由里记得过滤」——那是最容易在后续改动中被绕过的写法。
"""

from pydantic import BaseModel, Field

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
    player_cards: list[str] = Field(..., description="玩家牌面")
    dealer_cards: list[str] = Field(..., description="庄家牌面；玩家回合期间仅含明牌")
    player_total: int = Field(..., description="玩家有效点数")
    dealer_total: int | None = Field(
        None, description="庄家有效点数；玩家回合期间为 null（暗牌未公开）"
    )
    dealer_step_totals: list[int] = Field(
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
    outcome: str | None = Field(
        None,
        description="blackjack / win / push / lose / bust / surrender；未结算为 null",
    )
    payout_credits: float | None = Field(
        None, description="结算入账积分（含返还本金，已扣抽水）；不含奖池派彩"
    )
    rake_credits: float | None = Field(None, description="本手抽水总额")
    jackpot_won: float | None = Field(None, description="幸运奖池派彩，与赔付分别记账")
    relief_credits: float | None = Field(
        None, description="连败救济金额，与赔付/奖池分别记账；未触发为 null"
    )
    jackpot_trigger: str | None = Field(
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
    settled_at: int | None = Field(None, description="结算时间戳（秒）")

    @classmethod
    def from_hand(cls, hand: dict) -> "BlackjackHandResponse":
        """由 `db._blackjack_hand_to_dict()` 的结果构造响应。

        这是唯一的构造入口，庄家暗牌的裁剪落在此处：玩家回合期间庄家牌面只保留
        首张明牌，点数亦不返回（否则可反推暗牌）。种子与游标不在模型字段里，
        故即使入参含有也不会进入响应。
        """
        from app.domains.blackjack import rules as engine

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
            relief_credits=hand.get("relief_credits"),
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


class BlackjackFreespinGrant(BaseModel):
    """打满手数达到阈值时发放的免费大转盘机会"""

    expires_at_ms: int = Field(
        ..., description="过期时刻（毫秒时间戳）；过期后自动作废（发放记录保留作台账）"
    )


class BlackjackActionResponse(BaseModel):
    """发牌与各动作的统一响应"""

    success: bool = Field(True, description="是否成功")
    message: str = Field("", description="提示信息")
    hand: BlackjackHandResponse = Field(..., description="手牌状态")
    settled: bool = Field(..., description="本次操作是否已使手牌结算")
    current_credits: float = Field(..., description="操作后用户的当前积分")
    decision: BlackjackDecisionFeedback | None = Field(
        None, description="本次动作的基本策略评判；发牌无决策，故为 null"
    )
    jackpot_balance: float = Field(0, description="幸运奖池的当前余额")
    relief_credits: float = Field(0, description="本手触发的连败救济金额；未触发为 0")
    freespin_grants: list[BlackjackFreespinGrant] = Field(
        default_factory=list,
        description=(
            "本手结算使累计手数达到阈值而发放的免费大转盘机会；"
            "通常至多一张（单手只 +1），管理员调低阈值后可能连发至周配额上限"
        ),
    )


class BlackjackCurrentHandResponse(BaseModel):
    """当前进行中手牌的查询响应"""

    hand: BlackjackHandResponse | None = Field(
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
    bet_options: list[int] = Field(..., description="可选注额档位")
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
    relief_enabled: bool = Field(True, description="连败救济是否启用")
    relief_threshold: int = Field(8, description="连败 N 手触发救济")
    relief_multiplier: float = Field(
        1.0, description="救济倍数：补偿 = 该手基础注额 × 此值"
    )
    cashback_enabled: bool = Field(True, description="周损失返还是否启用")
    cashback_rate: float = Field(0.15, description="周净亏损的返还比例")
    freespins_enabled: bool = Field(True, description="打满送免费大转盘是否启用")
    freespins_hand_threshold: int = Field(
        20, description="每累计 N 手已结算现金局 → 1 次免费大转盘机会"
    )
    freespins_weekly_cap: int = Field(5, description="每周最多获得的免费机会次数")
    freespins_expiry_days: int = Field(7, description="免费机会有效期（自然日）")


class BlackjackAdminConfig(BaseModel):
    """管理员可见与可改的完整配置"""

    enabled: bool = Field(..., description="服务端停用开关")
    bet_options: list[int] = Field(..., min_length=1, description="注额档位")
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
    # ---- 留存三机制（openspec: add-blackjack-retention）----
    # 经济护栏（design.md D1，调整任一参数后按预算表重算）：
    # freespins_hand_threshold 不应低于 20、freespins_weekly_cap 不应高于 5，
    # 否则 15 分注玩家在截断区的合计让利会超过抽耗而翻正
    relief_enabled: bool = Field(True, description="连败救济开关")
    relief_threshold: int = Field(
        8, ge=1, description="连败 N 手触发救济；平局与投降不改变计数"
    )
    relief_multiplier: float = Field(
        1.0,
        gt=0,
        description="救济倍数：补偿 = 该手基础注额 × 此值（加倍手牌也按基础注额）",
    )
    cashback_enabled: bool = Field(True, description="周损失返还开关")
    cashback_rate: float = Field(
        0.15, gt=0, le=1, description="周净亏损的返还比例；返还进争霸赛余额而非积分"
    )
    cashback_min_payout: float = Field(
        1.0, ge=0, description="低于此金额不发放（避免尘埃级事务与通知）"
    )
    freespins_enabled: bool = Field(True, description="打满送免费大转盘开关")
    freespins_hand_threshold: int = Field(
        20,
        ge=1,
        description="每累计 N 手已结算现金局 → 1 次免费大转盘机会（不应低于 20，见经济护栏）",
    )
    freespins_weekly_cap: int = Field(
        5, ge=0, description="每周最多获得次数（不应高于 5，见经济护栏）"
    )
    freespins_expiry_days: int = Field(
        7, ge=1, description="机会有效期（自然日），过期未用自动作废"
    )
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
    final_rank: int | None = Field(None, description="最终名次；未结算为 null")
    prize_credits: float | None = Field(
        None, description="派奖积分；未结算为 null，已结算但无派奖为 0"
    )
    wallet_paid_credits: float = Field(0, description="报名费中由争霸赛余额支付的部分")
    credits_paid_credits: float = Field(
        0, description="报名费中由积分支付的部分；两者之和恒等于报名费全额"
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
            wallet_paid_credits=float(entry.get("wallet_paid_credits") or 0),
            credits_paid_credits=float(entry.get("credits_paid_credits") or 0),
            registered_at_ms=int(entry["registered_at_ms"]),
        )


class TournamentStandingRow(TournamentEntryResponse):
    """排名行：在报名状态之上补展示用的昵称与临时位次"""

    display_name: str = Field("", description="展示用昵称")
    provisional_rank: int | None = Field(
        None, description="进行中赛事的临时位次；已结算时为 null（以 final_rank 为准）"
    )


class TournamentResponse(BaseModel):
    """赛事详情"""

    id: int = Field(..., description="赛事 ID")
    title: str = Field(..., description="赛事名称")
    description: str | None = Field(None, description="赛事说明")
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
    payout_structure: list[float] = Field(
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
    settled_at: int | None = Field(None, description="结算时点（秒）")
    my_entry: TournamentEntryResponse | None = Field(
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
    tournaments: list[TournamentResponse] = Field(default_factory=list)


class TournamentStandingsResponse(BaseModel):
    """全场排名"""

    success: bool = Field(True)
    tournament_id: int = Field(...)
    status: int = Field(..., description="赛事状态，供前端判断是临时位次还是最终名次")
    standings: list[TournamentStandingRow] = Field(default_factory=list)


class TournamentRegisterResponse(BaseModel):
    """报名结果"""

    success: bool = Field(True)
    message: str = Field("")
    tournament: TournamentResponse = Field(...)
    entry: TournamentEntryResponse = Field(...)
    started: bool = Field(False, description="本次报名是否触发了满员开赛")
    current_credits: float = Field(..., description="扣除报名费后的积分")
    tournament_wallet_credits: float = Field(
        0, description="扣除报名费后的争霸赛余额（周损失返还的发放去向）"
    )


class TournamentWalletResponse(BaseModel):
    """争霸赛余额查询响应"""

    tournament_wallet_credits: float = Field(
        0,
        description=(
            "争霸赛余额：21 点周损失返还的发放去向，"
            "仅可支付锦标赛报名费，不可提现、兑换或转移"
        ),
    )


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
    chips: int | None = Field(None, description="操作后的赛内筹码；未知则为 null")
    hands_played: int | None = Field(None, description="已打手数；未知则为 null")
    hands_remaining: int | None = Field(None, description="剩余手数；未知则为 null")
    entry_status: int | None = Field(
        None, description="1=进行中 2=已打完 3=已淘汰；未知则为 null"
    )


class TournamentCurrentHandResponse(BaseModel):
    """赛内当前手牌与筹码状态"""

    success: bool = Field(True)
    tournament: TournamentResponse = Field(...)
    entry: TournamentEntryResponse = Field(...)
    hand: BlackjackHandResponse | None = Field(
        None, description="进行中的赛内手牌；无则为 null"
    )
    hands_remaining: int = Field(..., description="剩余手数")


class TournamentCreateRequest(BaseModel):
    """管理员创建赛事"""

    title: str | None = Field(
        None, description="赛事名称；留空则自动生成「21 点锦标赛 · 第 N 期」"
    )
    description: str | None = Field(None, description="赛事说明")
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
    payout_structure: list[float] | None = Field(
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
