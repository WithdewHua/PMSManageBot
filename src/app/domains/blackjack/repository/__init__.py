# 21 点默认配置。首次读取时落库，之后由管理员在面板上调整。
# 首次上线默认停用（enabled=False），待管理员核对配置与小范围试玩后再开放。
DEFAULT_BLACKJACK_CONFIG = {
    "enabled": False,  # 服务端停用开关：停用时拒绝新发牌，进行中手牌仍可正常结算
    "bet_options": [5, 15, 30],  # 注额档位，档位之外的注额一律拒绝
    "min_credits": 30,  # 参与门槛
    "rake_bp_on_profit": 300,  # 抽水比率（基点），仅对净赢利计取；300 = 3%
    "rake_burn_bp": 180,  # 抽水中直接销毁的部分（基点），180/300 = 60%
    "rake_jackpot_bp": 120,  # 抽水中注入幸运奖池的部分（基点），120/300 = 40%
    "dealer_hits_soft_17": False,  # 庄家软 17 是否继续要牌；False 即软 17 停牌
    "blackjack_payout": 1.5,  # 天胡赔率，3:2
    # 投降开关。返还比例**固定为基础注额的二分之一，不设配置项**：基本策略的
    # 投降建议正是按 0.5 推导的（只有期望低于 −0.5 的局面才该投降），比例若可调，
    # 该投降的格子集合就得跟着重算——而策略表是决策准确率的依据，准确率又是主榜
    # 口径与游戏王勋章的条件，一个比例旋钮会让整条评判链失去稳定依据。
    "surrender_enabled": True,
    "hand_timeout_minutes": 15,  # 手牌超时时限（分钟），超时按停牌自动结算
    "min_deal_interval_seconds": 1,  # 两次发牌的最小间隔，压制脚本化高频刷牌
    # 幸运奖池：由抽水供养、不增发积分，双层触发
    "jackpot_enabled": True,
    "jackpot_suited_bj_pct": 10,  # 同花天胡派发余额的百分比（约 83 手一次）
    # 三张 7 派发全部余额（约 5525 手一次），无需比例参数
    "jackpot_notify_enabled": True,  # 中奖时向群组播报，用于吸引更多人参与
    # 每日免抽水手数：低成本的习惯钩子，无条件发放，不需下注解锁
    "free_hands_per_day": 1,
    # ---- 留存三机制（openspec: add-blackjack-retention）----
    # 三项合计的目标：主力注额玩家有效期望从 ~2.3% 收窄到 ~0.5%~1%，仍是
    # 回收器但重度玩家失血速度降至原来的 1/4~1/2。参数护栏见 openspec
    # add-blackjack-retention/design.md D1：手数阈值 ≥ 20、周上限 ≤ 5，
    # 任一参数或转盘奖池调整后须按预算表重算
    "relief_enabled": True,
    "relief_threshold": 8,  # 连败 N 手触发救济；平局与投降不改变计数
    "relief_multiplier": 1.0,  # 补偿 = 该手基础注额 × 倍数（加倍手牌也按基础注额）
    "cashback_enabled": True,
    "cashback_rate": 0.15,  # 周净亏损的返还比例；返还进争霸赛余额而非积分
    "cashback_min_payout": 1.0,  # 低于此金额不发放（避免尘埃级事务与通知）
    "freespins_enabled": True,
    "freespins_hand_threshold": 20,  # 每累计 N 手已结算现金局 → 1 次免费大转盘机会
    "freespins_weekly_cap": 5,  # 每周最多获得次数（对刷量与触顶让利的双重封顶）
    "freespins_expiry_days": 7,  # 机会有效期（自然日），过期由查询过滤作废（行保留作台账）
    # 榜单最低手数门槛：样本量不足的用户不入准确率榜与胜率榜
    "rank_min_hands": 100,
    # 游戏王勋章的 21 点双条件
    "badge_min_hands": 2000,
    "badge_min_accuracy": 80,  # 决策准确率（百分比）
    # ---- 锦标赛 ----
    # 赛事通知开关。关闭时仍照常推进 reminder_sent_at 与各状态 CAS，只是不发送
    # ——若关闭时直接跳过流转，积压的通知会在重新打开的那一刻一次性倾泻
    "tournament_notify_enabled": True,
    # 完赛提醒的提前量（小时）。这不是便利而是**公平性保障**：未打满即失去派奖
    # 资格是一条硬规则，缺少提醒会使其等同于静默没收报名费
    "tournament_remind_lead_hours": 6,
    # 冠军勋章加成的累积上限（天），防止持续夺冠者无限累积
    "tournament_badge_cap_days": 90,
    # 每周一 09:00 自动创建周赛（报名截止周三 18:00、完赛截止周日 23:59，
    # 时点写在任务的 cron 注册与计算里，不设配置项）。赛制参数取 tournament_defaults
    "tournament_auto_create_enabled": True,
    # 创建赛事时的默认参数：管理员表单预填与每周自动开赛共用这一份
    "tournament_defaults": {
        "buy_in_credits": 30,
        "starting_chips": 1000,
        "total_hands": 30,
        "min_bet_chips": 10,
        "max_bet_chips": 500,
        "bet_step_chips": 10,
        "min_entrants": 6,
        "max_entrants": 20,
        "rake_bp": 1000,
        "payout_structure": [50, 30, 20],
    },
}

# 冠军勋章。照既有 game_king 的形状：缺失时自动创建，故不需要预置数据或迁移。
#
# 带 5% 每日观看积分加成、30 天有效期，再次夺冠时**续期而非重置**。这是一条
# 增发路径（0.4 积分/天/人），量级相对大转盘的回收可忽略，但原设计对增发很严格，
# 故在此显式记账。
CHAMPION_BADGE_TYPE = "blackjack_champion"

CHAMPION_BADGE_BONUS = 0.05

CHAMPION_BADGE_VALID_DAYS = 30

# 幸运奖池余额的存放位置。与大预言家的荣耀奖池
# `(prediction_market, glory_fund)` **完全无关**：21 点的抽水只进这个池子。
JACKPOT_CONFIG_TYPE = "blackjack"

JACKPOT_CONFIG_KEY = "jackpot_fund"

# 群播报的进度游标：已播报到的手牌 ID。
#
# 为什么用游标轮询而不在结算处挂钩子：奖池派彩散落在发牌（同花天胡直接结算）、
# 停牌、加倍、超时任务、定时兜底、以及发牌与查询时的惰性清理共六条路径上，
# 逐条挂钩既啰嗦又极易漏——而漏掉的恰恰会是最该播报的那次。游标把「谁结算的」
# 这件事完全解耦：只要派彩落了库，下一轮轮询必然看见它，且看见且仅看见一次。
JACKPOT_NOTIFY_CURSOR_KEY = "jackpot_notify_cursor"


from .part_1 import _BlackjackRepositoryPart1
from .part_2 import _BlackjackRepositoryPart2
from .part_3 import _BlackjackRepositoryPart3
from .part_4 import _BlackjackRepositoryPart4
from .part_5 import _BlackjackRepositoryPart5
from .part_6 import _BlackjackRepositoryPart6
from .part_7 import _BlackjackRepositoryPart7


class BlackjackRepository(
    _BlackjackRepositoryPart1,
    _BlackjackRepositoryPart2,
    _BlackjackRepositoryPart3,
    _BlackjackRepositoryPart4,
    _BlackjackRepositoryPart5,
    _BlackjackRepositoryPart6,
    _BlackjackRepositoryPart7,
):
    pass
