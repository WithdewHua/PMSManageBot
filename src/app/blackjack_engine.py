#!/usr/bin/env python3
"""21 点规则引擎 - 纯函数，无 IO、无积分概念

本模块只负责牌与规则：牌靴定序、点数计算、动作合法性、庄家补牌、胜负判定。
它不读写数据库、不接触积分，胜负结果以**赔付倍率**返回而非积分数——倍率到
积分的换算发生在 `db.py` 的结算适配层。这是 Phase 2 争霸赛的接缝：换一个
适配层把倍率作用于赛内筹码，本模块一行不动。

牌靴不落库：`build_deck(seed)` 由种子确定性地重建整个牌序，手牌行只存种子与
取牌游标。同种子恒得同牌序，故任一已结束手牌可完整复现以处理争议；牌序在发牌
时即由种子锁定，服务端无法在要牌时挑牌。
"""

import random
from typing import Optional

# 状态常量，与 BlackjackHand.status 一致
STATUS_PLAYER_TURN = 1  # 玩家回合
STATUS_DEALER_TURN = 2  # 庄家回合
STATUS_SETTLED = 3  # 已结算
STATUS_ABANDONED = 4  # 超时弃牌
TERMINAL_STATUSES = (STATUS_SETTLED, STATUS_ABANDONED)

# 结果常量，与 BlackjackHand.outcome 一致
OUTCOME_BLACKJACK = "blackjack"  # 天胡胜
OUTCOME_WIN = "win"  # 普通胜
OUTCOME_PUSH = "push"  # 平局
OUTCOME_LOSE = "lose"  # 判负（含庄家点数更高、仅庄家天胡）
OUTCOME_BUST = "bust"  # 玩家爆牌判负

BLACKJACK_TOTAL = 21
DEALER_STAND_TOTAL = 17
DECK_SIZE = 52

RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
SUITS = ("S", "H", "D", "C")  # 黑桃 红心 方块 梅花

# 牌面点数：A 先按 11 计，超过 21 时由 hand_total 逐张降为 1
RANK_VALUES = {
    "A": 11,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "10": 10,
    "J": 10,
    "Q": 10,
    "K": 10,
}


class BlackjackRuleError(ValueError):
    """规则层面的非法操作。由适配层翻译为面向用户的中文提示。"""


def card_rank(card: str) -> str:
    """取牌的点数标识。牌的表示为 `<rank><suit>`，如 `AS`、`10H`。"""
    return card[:-1]


def build_deck(seed: str) -> list[str]:
    """由种子确定性地生成一副定序好的 52 张牌。

    用 `random.Random(seed)` 而非 `secrets.SystemRandom()`：后者无法设种子、
    不可复现，与「争议可复现」直接冲突。种子本身来自 `secrets`，故牌序对用户
    不可预测；洗牌算法只需确定性，不需要密码学强度。

    每手牌使用独立定序的完整牌靴，手牌之间不延续牌序。
    """
    deck = [f"{rank}{suit}" for suit in SUITS for rank in RANKS]
    rng = random.Random(seed)
    # Fisher-Yates
    for i in range(len(deck) - 1, 0, -1):
        j = rng.randint(0, i)
        deck[i], deck[j] = deck[j], deck[i]
    return deck


def hand_total(cards: list[str]) -> int:
    """计算一手牌的有效点数：不超过 21 的最大可能点数。

    A 先全部按 11 计，总点数超过 21 时逐张降为 1，直至不超过 21 或已无可降级的 A。
    A+6+9 → 16、A+A → 12、A+7 → 18。
    """
    total = 0
    aces = 0
    for card in cards:
        rank = card_rank(card)
        total += RANK_VALUES[rank]
        if rank == "A":
            aces += 1
    while total > BLACKJACK_TOTAL and aces > 0:
        total -= 10  # 一张 A 由 11 降为 1
        aces -= 1
    return total


def is_soft(cards: list[str]) -> bool:
    """该手牌是否为软牌（含一张按 11 点计入的 A）。"""
    aces = sum(1 for card in cards if card_rank(card) == "A")
    if aces == 0:
        return False
    # 硬点数（全部 A 按 1 计）与有效点数相差 10，说明有一张 A 仍按 11 计
    hard_total = sum(
        1 if card_rank(card) == "A" else RANK_VALUES[card_rank(card)] for card in cards
    )
    return hand_total(cards) == hard_total + 10


def is_bust(cards: list[str]) -> bool:
    """是否爆牌。"""
    return hand_total(cards) > BLACKJACK_TOTAL


def is_natural_blackjack(cards: list[str]) -> bool:
    """是否天胡：**初始两张牌**合计 21 点。

    三张以上凑成的 21 点不是天胡，不享受天胡赔率。
    """
    return len(cards) == 2 and hand_total(cards) == BLACKJACK_TOTAL


def deal_initial(deck: list[str]) -> tuple[list[str], list[str], int]:
    """发初始牌：玩家两张、庄家两张（第二张为暗牌）。

    返回 `(player_cards, dealer_cards, next_card_index)`。
    庄家暗牌是否对用户可见由响应层裁剪，不在本模块处理。
    """
    player_cards = [deck[0], deck[2]]
    dealer_cards = [deck[1], deck[3]]
    return player_cards, dealer_cards, 4


def can_double(cards: list[str], status: int) -> bool:
    """能否加倍：仅在玩家回合、且手中恰为初始两张牌时。要牌后即不可加倍。"""
    return status == STATUS_PLAYER_TURN and len(cards) == 2


def can_hit(cards: list[str], status: int) -> bool:
    """能否要牌：玩家回合且未爆牌。"""
    return status == STATUS_PLAYER_TURN and not is_bust(cards)


def draw_card(deck: list[str], next_card_index: int) -> tuple[str, int]:
    """按游标取下一张牌，返回该牌与推进后的游标。

    取牌只是「翻开」发牌时既已确定的牌序，不重新生成、不改变牌面。
    """
    if next_card_index >= len(deck):
        # 单手最多用到十余张，52 张牌不可能耗尽；此处仅为防御性检查
        raise BlackjackRuleError("牌靴已耗尽")
    return deck[next_card_index], next_card_index + 1


def play_dealer(
    deck: list[str],
    dealer_cards: list[str],
    next_card_index: int,
    hits_soft_17: bool = False,
) -> tuple[list[str], int]:
    """庄家按规则补牌，返回补完后的牌面与游标。

    点数达到 17 即停牌，含软 17（如 A+6）；`hits_soft_17=True` 时软 17 继续要牌。
    庄家行为完全由规则决定，不依赖玩家身份、玩家点数或账户状态——本函数的入参
    里根本没有玩家信息。
    """
    cards = list(dealer_cards)
    index = next_card_index
    while True:
        total = hand_total(cards)
        if total > DEALER_STAND_TOTAL:
            break
        if total == DEALER_STAND_TOTAL and not (hits_soft_17 and is_soft(cards)):
            break
        card, index = draw_card(deck, index)
        cards.append(card)
    return cards, index


def resolve(
    player_cards: list[str],
    dealer_cards: list[str],
    doubled: bool,
    blackjack_payout: float = 1.5,
) -> tuple[str, float, float]:
    """判定胜负，返回 `(outcome, return_multiplier, profit_multiplier)`。

    两个倍率均**相对基础注额 B**（非总押注）：

    | 情形       | 总押注 | return | profit |
    |------------|--------|--------|--------|
    | 判负       | B      | 0      | 0      |
    | 平局       | B      | 1      | 0      |
    | 普通胜     | B      | 2      | 1      |
    | 天胡胜     | B      | 2.5    | 1.5    |
    | 加倍后判负 | 2B     | 0      | 0      |
    | 加倍后平局 | 2B     | 2      | 0      |
    | 加倍后胜   | 2B     | 4      | 2      |

    加倍胜是最易错的一格：总押注 2B，胜时返还本金 2B 加赢利 2B，故 return=4。
    适配层用 `profit_multiplier` 算抽水、用 `return_multiplier` 算入账。

    天胡不可能与加倍并存（加倍要求手中恰为两张且未天胡时才会进入玩家回合），
    故天胡分支不考虑 `doubled`。
    """
    stake = 2.0 if doubled else 1.0

    player_total = hand_total(player_cards)
    dealer_total = hand_total(dealer_cards)
    player_bj = is_natural_blackjack(player_cards)
    dealer_bj = is_natural_blackjack(dealer_cards)

    # 玩家爆牌判负，不论庄家结果——庄家此时根本不补牌
    if player_total > BLACKJACK_TOTAL:
        return OUTCOME_BUST, 0.0, 0.0

    # 开局天胡
    if player_bj or dealer_bj:
        if player_bj and dealer_bj:
            return OUTCOME_PUSH, stake, 0.0
        if player_bj:
            return OUTCOME_BLACKJACK, 1.0 + blackjack_payout, blackjack_payout
        return OUTCOME_LOSE, 0.0, 0.0

    if dealer_total > BLACKJACK_TOTAL:
        return OUTCOME_WIN, stake * 2, stake

    if player_total > dealer_total:
        return OUTCOME_WIN, stake * 2, stake
    if player_total < dealer_total:
        return OUTCOME_LOSE, 0.0, 0.0
    return OUTCOME_PUSH, stake, 0.0


def evaluate_initial_deal(
    player_cards: list[str],
    dealer_cards: list[str],
    blackjack_payout: float = 1.5,
) -> Optional[tuple[str, float, float]]:
    """判定开局是否直接结算（任一方天胡）。

    返回 `None` 表示双方均未天胡，手牌进入玩家回合；否则返回与 `resolve`
    同形的三元组，手牌直接进入已结算，不经玩家回合。

    四种组合：仅玩家天胡→天胡胜；仅庄家天胡→判负；双方天胡→平局；均无→None。
    """
    if not (is_natural_blackjack(player_cards) or is_natural_blackjack(dealer_cards)):
        return None
    return resolve(
        player_cards, dealer_cards, doubled=False, blackjack_payout=blackjack_payout
    )


# ============================================================
# 基本策略
# ============================================================

# 建议动作，与玩家的三个可用动作对应
ACTION_HIT = "hit"
ACTION_STAND = "stand"
ACTION_DOUBLE = "double"

# 策略表内部用的记号：
#   "D"  = 能加倍就加倍，否则要牌
#   "Ds" = 能加倍就加倍，否则**停牌**（软 18 对 3–6 是这一类）
# 两者的回退方向不同，混为一谈会在三张牌以上的局面给出错误建议。
_D_ELSE_HIT = "D"
_D_ELSE_STAND = "Ds"


def upcard_value(card: str) -> int:
    """庄家明牌用于查表的点数：A 记 11，10/J/Q/K 记 10，其余为面值。"""
    rank = card_rank(card)
    if rank == "A":
        return 11
    return RANK_VALUES[rank]


def _hard_strategy(total: int, up: int, hits_soft_17: bool) -> str:
    """硬手（无按 11 计的 A）的基本策略。`up` 为 2–11，其中 11 表示 A。"""
    if total >= 17:
        return ACTION_STAND
    if total >= 13:
        # 13–16：庄家亮小牌（2–6）易爆，停牌等他爆
        return ACTION_STAND if up <= 6 else ACTION_HIT
    if total == 12:
        # 12 只对 4–6 停牌：对 2、3 停牌的期望反而更差
        return ACTION_STAND if 4 <= up <= 6 else ACTION_HIT
    if total == 11:
        if up <= 10:
            return _D_ELSE_HIT
        # 对 A：S17 下要牌，H17 下加倍
        return _D_ELSE_HIT if hits_soft_17 else ACTION_HIT
    if total == 10:
        return _D_ELSE_HIT if up <= 9 else ACTION_HIT
    if total == 9:
        return _D_ELSE_HIT if 3 <= up <= 6 else ACTION_HIT
    # 5–8：怎么补都不会爆，一律要牌
    return ACTION_HIT


def _soft_strategy(total: int, up: int, hits_soft_17: bool) -> str:
    """软手（含一张按 11 计的 A）的基本策略。`up` 为 2–11，其中 11 表示 A。"""
    if total >= 20:
        return ACTION_STAND
    if total == 19:
        # 软 19 只在 H17 且庄家亮 6 时加倍
        if hits_soft_17 and up == 6:
            return _D_ELSE_STAND
        return ACTION_STAND
    if total == 18:
        if 3 <= up <= 6:
            return _D_ELSE_STAND
        if hits_soft_17 and up == 2:
            return _D_ELSE_STAND
        if up in (2, 7, 8):
            return ACTION_STAND
        # 对 9、10、A：软 18 不够看，要牌
        return ACTION_HIT
    if total == 17:
        return _D_ELSE_HIT if 3 <= up <= 6 else ACTION_HIT
    if total in (15, 16):
        return _D_ELSE_HIT if 4 <= up <= 6 else ACTION_HIT
    if total in (13, 14):
        return _D_ELSE_HIT if 5 <= up <= 6 else ACTION_HIT
    # 软 12 只可能是 A,A（本活动不分牌）：要牌
    return ACTION_HIT


def recommend_action(
    player_cards: list[str],
    dealer_upcard: str,
    can_double: bool,
    hits_soft_17: bool = False,
) -> str:
    """给出基本策略在当前局面下的建议动作。

    采用标准的「不分牌、不投降、不保险」基本策略表——本活动的动作集正是如此。
    `hits_soft_17` 须取自**该手牌的参数快照**而非当前配置，否则管理员改了庄家
    规则会让历史手牌的评判口径跟着变。

    这是一个纯函数：同一局面恒得同一建议，**零方差**。决策准确率因此是本游戏
    里唯一完全不受运气影响的指标，这正是它适合作为主榜口径的原因。

    `can_double` 为假时（手中已超过两张牌），建议会按各自的回退方向落到要牌或
    停牌，绝不会返回一个当前不可执行的动作。
    """
    total = hand_total(player_cards)
    up = upcard_value(dealer_upcard)

    if is_soft(player_cards):
        rec = _soft_strategy(total, up, hits_soft_17)
    else:
        rec = _hard_strategy(total, up, hits_soft_17)

    if rec == _D_ELSE_HIT:
        return ACTION_DOUBLE if can_double else ACTION_HIT
    if rec == _D_ELSE_STAND:
        return ACTION_DOUBLE if can_double else ACTION_STAND
    return rec


# ============================================================
# 幸运奖池的触发牌型
# ============================================================

# 10 值牌，用于判定同花天胡
TEN_RANKS = ("10", "J", "Q", "K")


def is_suited_blackjack(cards: list[str]) -> bool:
    """同花天胡：初始两张为 A 与**同花色**的 10、J、Q、K。

    与 `is_natural_blackjack` 的区别仅在于是否同花——后者不要求花色一致。
    """
    if len(cards) != 2:
        return False
    if cards[0][-1] != cards[1][-1]:
        return False
    ranks = {card_rank(cards[0]), card_rank(cards[1])}
    return "A" in ranks and bool(ranks & set(TEN_RANKS))


def is_triple_seven(cards: list[str]) -> bool:
    """三张 7：手中恰为三张 7，合计 21 点。"""
    return len(cards) == 3 and all(card_rank(c) == "7" for c in cards)
