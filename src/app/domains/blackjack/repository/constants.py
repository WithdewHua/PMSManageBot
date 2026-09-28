"""Persistent blackjack state keys owned by the repository layer."""

JACKPOT_CONFIG_TYPE = "blackjack"
JACKPOT_CONFIG_KEY = "jackpot_fund"
JACKPOT_NOTIFY_CURSOR_KEY = "jackpot_notify_cursor"
CASHBACK_CURSOR_KEY = "cashback_settled_through"
FREESPIN_NOTIFY_CURSOR_KEY = "freespin_notify_cursor"

__all__ = [
    "CASHBACK_CURSOR_KEY",
    "FREESPIN_NOTIFY_CURSOR_KEY",
    "JACKPOT_CONFIG_KEY",
    "JACKPOT_CONFIG_TYPE",
    "JACKPOT_NOTIFY_CURSOR_KEY",
]
