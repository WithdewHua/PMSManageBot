from sqlalchemy import (
    BIGINT,
    SMALLINT,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class BlackjackWeeklyCashback(Base):
    """21 点周损失返还结算行 - 一行代表一位用户一个自然周的结算

    幂等的唯一防线：UNIQUE(tg_id, week_start_ms) 使重跑任务撞约束跳过，
    服务重启后既不漏周期也不重复入账。net_change 为该周现金局 21 点的
    积分净变动（含投注、赔付、抽水影响、彩池派彩与连败救济；不含转盘
    结果与争霸赛余额变动），为负时按比率返还进争霸赛余额。
    """

    __tablename__ = "blackjack_weekly_cashback"

    # Integer 理由同 luckywheel_free_spins：生产代码插入无显式 id
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("statistics.tg_id", onupdate="CASCADE"),
        nullable=False,
        info={"tg_id": "user"},
    )
    # 结算周期起始（该自然周一零点，settings.TZ）的毫秒时间戳
    week_start_ms: Mapped[int] = mapped_column(BIGINT, nullable=False)
    net_change: Mapped[float] = mapped_column(Float, nullable=False)
    cashback_credits: Mapped[float] = mapped_column(Float, nullable=False)
    created_at_ms: Mapped[int] = mapped_column(BIGINT, nullable=False)

    __table_args__ = (
        UniqueConstraint("tg_id", "week_start_ms", name="uq_blackjack_weekly_cashback"),
        # 任务重跑扫描「某周期已结算了谁」
        Index("idx_blackjack_weekly_cashback_week", "week_start_ms"),
    )


class BlackjackHand(Base):
    """21 点手牌 - 一行代表用户的一次对局

    牌靴不落库：只存随机种子与取牌游标，取第 N 张牌 = 用种子重建牌序后取
    下标 N。种子在发牌时确定并写入，故服务端无法中途换牌，且任一已结束手牌
    可凭种子完整复现以处理争议。`deck_seed` 与 `next_card_index` 绝不出现在
    面向用户的接口响应中。

    参数快照六列（rake_bp_on_profit / rake_jackpot_bp / blackjack_payout /
    dealer_hits_soft_17 / hand_timeout_minutes / surrender_enabled）记录发牌当时
    生效的配置，结算、超时判定与决策评判都读快照而非读当前配置，使管理员改配置
    不影响进行中的手牌。
    """

    __tablename__ = "blackjack_hand"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("statistics.tg_id", onupdate="CASCADE"),
        nullable=False,
        index=True,
        info={"tg_id": "user"},
    )

    # 状态：1=玩家回合 2=庄家回合 3=已结算 4=超时弃牌（3、4 为终态）
    status: Mapped[int] = mapped_column(SMALLINT, nullable=False, default=1)

    # 注额
    bet_credits: Mapped[int] = mapped_column(Integer, nullable=False)  # 基础注额
    doubled: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, default=0
    )  # 0=未加倍 1=已加倍（总押注为两份基础注额）

    # 牌靴
    deck_seed: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # 定序种子，仅供服务端复现，不对外暴露
    next_card_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 下一张待发牌在牌序中的下标，只增不减

    # 牌面（JSON 数组）
    player_cards: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    dealer_cards: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )  # 玩家回合期间响应层须裁剪为仅首张

    # 结算结果
    outcome: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # blackjack / win / push / lose / bust
    payout_credits: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # 实际入账积分（含返还本金，已扣抽水）；**不含奖池派彩**
    rake_credits: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # 本手抽水总额，仅作审计记录；销毁部分不另行落账
    jackpot_won: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # 幸运奖池派彩，与 payout_credits 分别记账——并入会使单手最大赢利榜
    # 退化成奖池中奖者名单
    relief_credits: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # 连败救济金额，与赔付/奖池分别记账：周返还的净变动口径需包含它，
    # 且对账脚本需逐手核对发放总额；加倍手牌触发救济时按基础注额记录

    # 决策评判：落在手牌而非用户上，与参数快照同一哲学——每手牌自带其评判依据
    # （当时的庄家规则），用户维度的准确率由聚合得到
    decisions_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decisions_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 是否为当日免抽水的那一手。与「快照 rake_bp_on_profit=0」信息重复，但仍单列：
    # 管理员把全局抽水调为 0 时两者会混淆，显式一列让审计无歧义
    rake_waived: Mapped[int] = mapped_column(SMALLINT, nullable=False, default=0)

    # 参数快照（发牌时生效的配置）
    rake_bp_on_profit: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    rake_jackpot_bp: Mapped[int] = mapped_column(
        Integer, nullable=False, default=120
    )  # 抽水中注入幸运奖池的部分（基点）
    blackjack_payout: Mapped[float] = mapped_column(Float, nullable=False, default=1.5)
    dealer_hits_soft_17: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, default=0
    )  # 0=软 17 停牌 1=软 17 继续要牌
    hand_timeout_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15
    )  # 超时时限；快照于此，故管理员调整时限不影响已发出的手牌
    surrender_enabled: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, server_default="0", default=0
    )  # 发牌时投降是否可用；存量手牌为 0，故其决策评判继续走不含投降的策略表

    # Phase 2 争霸赛预留：恒为 NULL，不设外键与索引
    tournament_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)

    created_at_ms: Mapped[int] = mapped_column(
        BIGINT, nullable=False
    )  # 毫秒时间戳，兼作发牌速率判定与当日首手判定的依据
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    settled_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)  # 秒时间戳

    __table_args__ = (
        CheckConstraint("bet_credits > 0", name="ck_blackjack_hand_bet_gt_0"),
        CheckConstraint("status IN (1,2,3,4)", name="ck_blackjack_hand_status"),
        CheckConstraint("doubled IN (0,1)", name="ck_blackjack_hand_doubled"),
        CheckConstraint(
            "surrender_enabled IN (0,1)", name="ck_blackjack_hand_surrender_enabled"
        ),
        CheckConstraint(
            "next_card_index >= 0", name="ck_blackjack_hand_next_card_index_nonneg"
        ),
        CheckConstraint(
            "hand_timeout_minutes > 0", name="ck_blackjack_hand_timeout_gt_0"
        ),
        CheckConstraint(
            "decisions_total >= 0", name="ck_blackjack_hand_decisions_total_nonneg"
        ),
        CheckConstraint(
            "decisions_correct >= 0 AND decisions_correct <= decisions_total",
            name="ck_blackjack_hand_decisions_correct_range",
        ),
        CheckConstraint("rake_waived IN (0,1)", name="ck_blackjack_hand_rake_waived"),
        CheckConstraint(
            "jackpot_won IS NULL OR jackpot_won >= 0",
            name="ck_blackjack_hand_jackpot_won_nonneg",
        ),
        CheckConstraint(
            "relief_credits IS NULL OR relief_credits >= 0",
            name="ck_blackjack_hand_relief_nonneg",
        ),
        # 「找该用户进行中的手牌」
        Index("idx_blackjack_hand_user_status", "tg_id", "status"),
        # 发牌速率判定、当日首手判定与各榜单
        Index("idx_blackjack_hand_user_time", "tg_id", "created_at_ms"),
        # 赛事清场（结算一场赛事的全部在局手牌）与赛内手牌归属查询
        Index("idx_blackjack_hand_tournament", "tournament_id", "tg_id"),
    )


class BlackjackTournament(Base):
    """21 点锦标赛 - 一行代表一场赛事

    异步筹码累积赛：报名扣积分换取赛内筹码，各自安排时间打完固定手数，按最终
    筹码在全场报名者中排名分取奖池。**锦标赛是事件而非技巧阶梯**——赛果不进入
    任何榜单，赛内手牌也不计入决策准确率等技巧口径（以名次为目标时，落后者在
    末几手会做出单手期望为负但对名次正确的选择，按基本策略评判会惩罚打得对的人）。

    奖池金额**不落列**：`entrant_count × buy_in_credits + seeded_prize_credits`
    恒等于真值，累加列会引入「报名成功但累加失败 / 退款后忘记回退 / 并发累加
    丢失」一整类漂移 bug。与幸运奖池刻意不同——那边增量来自每手不同的抽水份额，
    无法推导。

    参数快照四列（dealer_hits_soft_17 / blackjack_payout / surrender_enabled /
    hand_timeout_minutes）记录创建当时生效的全局配置，赛内全部手牌按该快照结算，
    使管理员改全局配置不影响已创建的赛事。

    每手牌仍各自持有独立的 `secrets` 种子（落在 `BlackjackHand.deck_seed` 上），
    本表**不存赛事级种子**：每手牌本来就能凭自己的种子复现，派生只是多一个必须
    保密的字段和一层无收益的间接。同一赛事的不同报名者因此天然使用不同牌序——
    复式赛制（全场同牌序）在异步作战下不可行，先打完的人在群里说一句就泄漏全部
    牌序与庄家暗牌。
    """

    __tablename__ = "blackjack_tournament"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 状态：1=报名中 2=进行中 3=已结算 4=已取消（3、4 为终态）。
    # 每次流转都靠条件 UPDATE（CAS）抢占，抢到的一方才发通知——五处通知里有三处
    # 存在多条触发路径，CAS 同时充当流转闸门与通知去重。
    status: Mapped[int] = mapped_column(SMALLINT, nullable=False, default=1)

    # 报名与筹码
    buy_in_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    starting_chips: Mapped[int] = mapped_column(Integer, nullable=False)
    total_hands: Mapped[int] = mapped_column(Integer, nullable=False)
    # 注额区间。赛内不用现金局的固定档位——下注额本身即为锦标赛的主要技巧，
    # 固定档位会让这项技巧无从施展
    min_bet_chips: Mapped[int] = mapped_column(Integer, nullable=False)
    max_bet_chips: Mapped[int] = mapped_column(Integer, nullable=False)
    bet_step_chips: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    min_entrants: Mapped[int] = mapped_column(Integer, nullable=False)
    max_entrants: Mapped[int] = mapped_column(Integer, nullable=False)
    # 报名占位的 CAS 依据，兼奖池推导的因子。与 entry 行数只在同一事务内一起
    # 变动；赛事进入进行中后不再改变
    entrant_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 奖池：抽水部分直接销毁，不落账（销毁即「不发给任何人」）
    rake_bp: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    # 管理员补贴。本变更两条增发路径之一，必须是显式操作而非自动行为
    seeded_prize_credits: Mapped[float] = mapped_column(
        Float, nullable=False, default=0
    )
    # 派奖档位百分比，JSON 数组如 [50, 30, 20]。具备派奖资格者少于档位数时
    # 截断至该数量并重新归一至 100%，确保奖池无残留
    payout_structure: Mapped[str] = mapped_column(
        Text, nullable=False, default="[50, 30, 20]"
    )

    # 参数快照（创建时生效的全局配置）
    dealer_hits_soft_17: Mapped[int] = mapped_column(
        SMALLINT, nullable=False, default=0
    )
    blackjack_payout: Mapped[float] = mapped_column(Float, nullable=False, default=1.5)
    surrender_enabled: Mapped[int] = mapped_column(SMALLINT, nullable=False, default=1)
    hand_timeout_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15
    )

    register_deadline_ms: Mapped[int] = mapped_column(BIGINT, nullable=False)
    # 完赛最晚边界。发牌与动作仍检查 `now < play_deadline_ms`，但不得只靠它
    # 挡新手牌：提前完赛发生在截止之前，CAS 之后靠 `status != 进行中`。
    # 发牌与结算对进行中行做条件 UPDATE，使截止边界上尚未提交的发牌无法
    # 插进已经派完奖的赛事；本列的固定时点不是那把锁。
    play_deadline_ms: Mapped[int] = mapped_column(BIGINT, nullable=False)

    # 完赛提醒的去重标记。提醒是**公平性保障而非便利**：未打满即失去派奖资格
    # 是一条硬规则，缺少提醒会使其等同于静默没收报名费
    reminder_sent_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)

    created_by: Mapped[int | None] = mapped_column(
        BIGINT, nullable=True, info={"tg_id": "admin"}
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    settled_at: Mapped[int | None] = mapped_column(BIGINT, nullable=True)  # 秒时间戳

    entries = relationship(
        "BlackjackTournamentEntry",
        back_populates="tournament",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("status IN (1,2,3,4)", name="ck_blackjack_tournament_status"),
        CheckConstraint(
            "buy_in_credits > 0", name="ck_blackjack_tournament_buy_in_gt_0"
        ),
        CheckConstraint(
            "starting_chips > 0", name="ck_blackjack_tournament_chips_gt_0"
        ),
        CheckConstraint("total_hands > 0", name="ck_blackjack_tournament_hands_gt_0"),
        CheckConstraint(
            "bet_step_chips > 0", name="ck_blackjack_tournament_bet_step_gt_0"
        ),
        CheckConstraint(
            "min_bet_chips > 0 AND min_bet_chips <= max_bet_chips",
            name="ck_blackjack_tournament_bet_range",
        ),
        CheckConstraint(
            "min_entrants > 0 AND min_entrants <= max_entrants",
            name="ck_blackjack_tournament_entrant_range",
        ),
        CheckConstraint(
            "entrant_count >= 0 AND entrant_count <= max_entrants",
            name="ck_blackjack_tournament_entrant_count",
        ),
        CheckConstraint(
            "rake_bp >= 0 AND rake_bp <= 10000",
            name="ck_blackjack_tournament_rake_bp",
        ),
        CheckConstraint(
            "seeded_prize_credits >= 0",
            name="ck_blackjack_tournament_seed_nonneg",
        ),
        CheckConstraint(
            "surrender_enabled IN (0,1)",
            name="ck_blackjack_tournament_surrender_enabled",
        ),
        CheckConstraint(
            "dealer_hits_soft_17 IN (0,1)",
            name="ck_blackjack_tournament_dealer_h17",
        ),
        CheckConstraint(
            "hand_timeout_minutes > 0",
            name="ck_blackjack_tournament_timeout_gt_0",
        ),
        CheckConstraint(
            "register_deadline_ms <= play_deadline_ms",
            name="ck_blackjack_tournament_deadline_order",
        ),
        # tick 任务按 (status, 各截止时点) 扫待处理的赛事
        Index("idx_blackjack_tournament_status_reg", "status", "register_deadline_ms"),
        Index("idx_blackjack_tournament_status_play", "status", "play_deadline_ms"),
    )


class BlackjackTournamentEntry(Base):
    """21 点锦标赛报名 - 一行代表一位用户在一场赛事中的参赛记录

    `chips` 是赛内结算适配层加锁与写入的对象，**替代现金局路径上的
    `Statistics.credits`**：赛内高频路径因此与积分行锁彻底解耦，一个人打 30 手
    赛内牌不会和自己的现金局、也不会和派奖抢同一行锁。全局锁序为
    `hand → tournament → entry → statistics → system_config`，各路径取到的都是
    这条全序的子序列。

    筹码为**整数**，赔付向下取整：注额约束为 `bet_step_chips` 的整数倍，故 3:2
    天胡赔率下 `2.5 × bet` 必为整数，取整实际不会触发；只有管理员把
    `blackjack_payout` 改成非常规值时才生效，量级在 1 筹码以内。好处是排名与
    展示不出现 `1247.5 筹码`，也不必在赛内重复现金局那套浮点收敛纪律。

    派奖结果落在本表（`final_rank` / `prize_credits`）而非另建流水表：一次派奖
    对一条 entry 恰好写一次，CAS 已保证不重复，流水表提供不了额外信息。
    """

    __tablename__ = "blackjack_tournament_entry"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("blackjack_tournament.id"),
        nullable=False,
        index=True,
    )
    tg_id: Mapped[int] = mapped_column(
        BIGINT,
        ForeignKey("statistics.tg_id", onupdate="CASCADE"),
        nullable=False,
        index=True,
        info={"tg_id": "user"},
    )

    chips: Mapped[int] = mapped_column(Integer, nullable=False)
    hands_played: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 状态：1=进行中 2=已打完（打满总手数） 3=已淘汰（筹码低于最小注）。
    # **只有 2 与 3 具备派奖资格**：21 点接近零期望，故不打牌的期望筹码高于打满
    # 全部手数的中位数——若无这道资格门，最优策略将是报名后什么都不做。
    status: Mapped[int] = mapped_column(SMALLINT, nullable=False, default=1)

    # 结算后写入。并列由报名时点决胜——它不可操纵且不奖励任何行为：以手数决胜
    # 会奖励少打，以最后一手时点决胜会奖励拖到截止前
    final_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prize_credits: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 报名费的实际支付拆分：优先扣争霸赛余额，不足部分从积分补足。两列之和
    # 恒等于报名费全额；取消退款按拆分原路退回（余额部分回余额，积分部分回
    # 积分），使返还的价值不会因路径改换而意外进入可挪用的积分
    wallet_paid_credits: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )
    credits_paid_credits: Mapped[float] = mapped_column(
        Float, nullable=False, default=0, server_default="0"
    )

    registered_at_ms: Mapped[int] = mapped_column(BIGINT, nullable=False)

    tournament = relationship("BlackjackTournament", back_populates="entries")

    __table_args__ = (
        # 重复报名的唯一防线：名额占位的 CAS 与本约束在同一事务内，插入撞约束时
        # 整个事务回滚、计数增量随之回退，不需要补偿性减一
        UniqueConstraint(
            "tournament_id", "tg_id", name="uq_blackjack_tournament_entry"
        ),
        CheckConstraint(
            "status IN (1,2,3)", name="ck_blackjack_tournament_entry_status"
        ),
        CheckConstraint(
            "chips >= 0", name="ck_blackjack_tournament_entry_chips_nonneg"
        ),
        CheckConstraint(
            "hands_played >= 0", name="ck_blackjack_tournament_entry_hands_nonneg"
        ),
        CheckConstraint(
            "prize_credits IS NULL OR prize_credits >= 0",
            name="ck_blackjack_tournament_entry_prize_nonneg",
        ),
        CheckConstraint(
            "wallet_paid_credits >= 0 AND credits_paid_credits >= 0",
            name="ck_blackjack_tournament_entry_paid_nonneg",
        ),
        # 排名（按 chips 降序）与「找某用户在某赛事的报名」
        Index(
            "idx_blackjack_tournament_entry_rank",
            "tournament_id",
            "chips",
        ),
    )
