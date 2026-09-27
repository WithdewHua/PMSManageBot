"""Blackjack-owned runtime configuration and stable accounting constants."""

# 21 点默认配置。首次读取时落库，之后由管理员在面板上调整。
# 首次上线默认停用（enabled=False），待管理员核对配置与小范围试玩后再开放。
DEFAULT_BLACKJACK_CONFIG = {
    "enabled": False,
    "bet_options": [5, 15, 30],
    "min_credits": 30,
    "rake_bp_on_profit": 300,
    "rake_burn_bp": 180,
    "rake_jackpot_bp": 120,
    "dealer_hits_soft_17": False,
    "blackjack_payout": 1.5,
    "surrender_enabled": True,
    "hand_timeout_minutes": 15,
    "min_deal_interval_seconds": 1,
    "jackpot_enabled": True,
    "jackpot_suited_bj_pct": 10,
    "jackpot_notify_enabled": True,
    "free_hands_per_day": 1,
    "relief_enabled": True,
    "relief_threshold": 8,
    "relief_multiplier": 1.0,
    "cashback_enabled": True,
    "cashback_rate": 0.15,
    "cashback_min_payout": 1.0,
    "freespins_enabled": True,
    "freespins_hand_threshold": 20,
    "freespins_weekly_cap": 5,
    "freespins_expiry_days": 7,
    "rank_min_hands": 100,
    "badge_min_hands": 2000,
    "badge_min_accuracy": 80,
    "tournament_notify_enabled": True,
    "tournament_remind_lead_hours": 6,
    "tournament_badge_cap_days": 90,
    "tournament_auto_create_enabled": True,
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

# 冠军勋章配置。再次夺冠时续期而非重置。
CHAMPION_BADGE_TYPE = "blackjack_champion"
CHAMPION_BADGE_BONUS = 0.05
CHAMPION_BADGE_VALID_DAYS = 30

# 幸运奖池余额的存放位置，与其他 domain 的奖池完全隔离。
JACKPOT_CONFIG_TYPE = "blackjack"
JACKPOT_CONFIG_KEY = "jackpot_fund"
JACKPOT_NOTIFY_CURSOR_KEY = "jackpot_notify_cursor"
CASHBACK_CURSOR_KEY = "cashback_settled_through"
FREESPIN_NOTIFY_CURSOR_KEY = "freespin_notify_cursor"

# Persisted tournament status values shared by interfaces and repository queries.
TOURNAMENT_REGISTERING = 1
TOURNAMENT_RUNNING = 2
TOURNAMENT_SETTLED = 3
TOURNAMENT_CANCELLED = 4
ENTRY_PLAYING = 1
ENTRY_FINISHED = 2
ENTRY_ELIMINATED = 3
ENTRY_ELIGIBLE = (ENTRY_FINISHED, ENTRY_ELIMINATED)

__all__ = [
    "CASHBACK_CURSOR_KEY",
    "CHAMPION_BADGE_BONUS",
    "CHAMPION_BADGE_TYPE",
    "CHAMPION_BADGE_VALID_DAYS",
    "DEFAULT_BLACKJACK_CONFIG",
    "ENTRY_ELIGIBLE",
    "ENTRY_ELIMINATED",
    "ENTRY_FINISHED",
    "ENTRY_PLAYING",
    "FREESPIN_NOTIFY_CURSOR_KEY",
    "JACKPOT_CONFIG_KEY",
    "JACKPOT_CONFIG_TYPE",
    "JACKPOT_NOTIFY_CURSOR_KEY",
    "TOURNAMENT_CANCELLED",
    "TOURNAMENT_REGISTERING",
    "TOURNAMENT_RUNNING",
    "TOURNAMENT_SETTLED",
]
