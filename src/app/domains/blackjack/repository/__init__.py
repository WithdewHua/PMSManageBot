from app.domains.blackjack.config import (
    BLACKJACK_CONFIG,
    CHAMPION_BADGE_BONUS,
    CHAMPION_BADGE_TYPE,
    CHAMPION_BADGE_VALID_DAYS,
    DEFAULT_BLACKJACK_CONFIG,
    ENTRY_ELIGIBLE,
    ENTRY_ELIMINATED,
    ENTRY_FINISHED,
    ENTRY_PLAYING,
    TOURNAMENT_CANCELLED,
    TOURNAMENT_REGISTERING,
    TOURNAMENT_RUNNING,
    TOURNAMENT_SETTLED,
)

from .config_store import _BlackjackRepositoryConfigStore
from .constants import (
    CASHBACK_CURSOR_KEY,
    FREESPIN_NOTIFY_CURSOR_KEY,
    JACKPOT_CONFIG_KEY,
    JACKPOT_CONFIG_TYPE,
    JACKPOT_NOTIFY_CURSOR_KEY,
)
from .hands import _BlackjackRepositoryHands
from .jackpot import _BlackjackRepositoryJackpot
from .retention import _BlackjackRepositoryRetention
from .settlement import _BlackjackRepositorySettlement
from .stats import _BlackjackRepositoryStats
from .tournament_entries import _BlackjackRepositoryTournamentEntries
from .tournament_play import _BlackjackRepositoryTournamentPlay
from .tournaments import _BlackjackRepositoryTournaments
from .wallet import _BlackjackRepositoryWallet


class _BlackjackRepositoryImplementation(
    _BlackjackRepositoryHands,
    _BlackjackRepositorySettlement,
    _BlackjackRepositoryJackpot,
    _BlackjackRepositoryRetention,
    _BlackjackRepositoryWallet,
    _BlackjackRepositoryStats,
    _BlackjackRepositoryTournaments,
    _BlackjackRepositoryTournamentEntries,
    _BlackjackRepositoryTournamentPlay,
    _BlackjackRepositoryConfigStore,
):
    """Private compatibility implementation for the module-level API."""


_repository = _BlackjackRepositoryImplementation()


def settle_blackjack_weekly_cashback() -> dict:
    return _repository.settle_blackjack_weekly_cashback()


def get_blackjack_tournament_wallet(tg_id: int) -> float:
    return _repository.get_blackjack_tournament_wallet(tg_id)


def credit_tournament_wallet_tx(session, tg_id: int, amount: float) -> float:
    """给争霸赛余额记账（调用方持有事务），返回记完后的余额。"""
    return _repository.credit_tournament_wallet_tx(session, tg_id, amount)


def read_fund_balance(session, config_type: str, config_key: str) -> float:
    return _repository.read_fund_balance(session, config_type, config_key)


def get_blackjack_jackpot() -> float:
    return _repository.get_blackjack_jackpot()


def seed_blackjack_jackpot(amount: float) -> float:
    return _repository.seed_blackjack_jackpot(amount)


def claim_unannounced_jackpot_wins() -> list[dict]:
    return _repository.claim_unannounced_jackpot_wins()


def sweep_timed_out_blackjack_hands(tg_id: int | None = None) -> int:
    return _repository.sweep_timed_out_blackjack_hands(tg_id)


def get_blackjack_free_hands_remaining(tg_id: int) -> int:
    return _repository.get_blackjack_free_hands_remaining(tg_id)


def create_blackjack_hand(tg_id: int, bet_credits: int) -> dict:
    return _repository.create_blackjack_hand(tg_id, bet_credits)


def blackjack_hit(tg_id: int, hand_id: int) -> dict:
    return _repository.blackjack_hit(tg_id, hand_id)


def blackjack_stand(tg_id: int, hand_id: int) -> dict:
    return _repository.blackjack_stand(tg_id, hand_id)


def blackjack_double(tg_id: int, hand_id: int) -> dict:
    return _repository.blackjack_double(tg_id, hand_id)


def blackjack_surrender(tg_id: int, hand_id: int) -> dict:
    return _repository.blackjack_surrender(tg_id, hand_id)


def settle_blackjack_hand_by_timeout(hand_id: int) -> dict:
    return _repository.settle_blackjack_hand_by_timeout(hand_id)


def get_current_blackjack_hand(tg_id: int) -> dict | None:
    return _repository.get_current_blackjack_hand(tg_id)


def list_active_blackjack_hands() -> list[dict]:
    return _repository.list_active_blackjack_hands()


def get_user_blackjack_stats(tg_id: int) -> dict:
    return _repository.get_user_blackjack_stats(tg_id)


def get_blackjack_admin_stats() -> dict:
    return _repository.get_blackjack_admin_stats()


def create_blackjack_tournament(params: dict, created_by: int | None = None) -> dict:
    return _repository.create_blackjack_tournament(params, created_by)


def update_blackjack_tournament(tournament_id: int, params: dict) -> dict:
    return _repository.update_blackjack_tournament(tournament_id, params)


def register_blackjack_tournament(tg_id: int, tournament_id: int) -> dict:
    return _repository.register_blackjack_tournament(tg_id, tournament_id)


def start_blackjack_tournament(tournament_id: int) -> dict:
    return _repository.start_blackjack_tournament(tournament_id)


def cancel_blackjack_tournament(
    tournament_id: int, reason: str = "insufficient_entrants"
) -> dict:
    return _repository.cancel_blackjack_tournament(tournament_id, reason)


def claim_tournament_reminder(tournament_id: int) -> dict:
    return _repository.claim_tournament_reminder(tournament_id)


def get_blackjack_tournament(
    tournament_id: int, tg_id: int | None = None
) -> dict | None:
    return _repository.get_blackjack_tournament(tournament_id, tg_id)


def list_blackjack_tournaments(
    tg_id: int | None = None,
    statuses: tuple | None = None,
    limit: int = 20,
) -> list[dict]:
    return _repository.list_blackjack_tournaments(tg_id, statuses, limit)


def list_blackjack_tournaments_with_playing_entries(
    tournament_ids: list[int],
) -> list[dict]:
    return _repository.list_blackjack_tournaments_with_playing_entries(tournament_ids)


def count_registering_blackjack_tournaments(now_ms: int) -> int | None:
    return _repository.count_registering_blackjack_tournaments(now_ms)


def get_blackjack_tournament_standings(tournament_id: int) -> list[dict]:
    return _repository.get_blackjack_tournament_standings(tournament_id)


def get_user_blackjack_tournament_entry(tg_id: int, tournament_id: int) -> dict | None:
    return _repository.get_user_blackjack_tournament_entry(tg_id, tournament_id)


def count_user_blackjack_tournament_titles(tg_id: int) -> int:
    return _repository.count_user_blackjack_tournament_titles(tg_id)


def check_blackjack_tournament_consistency(tournament_id: int) -> dict | None:
    return _repository.check_blackjack_tournament_consistency(tournament_id)


def create_blackjack_tournament_hand(
    tg_id: int, tournament_id: int, bet_chips: int
) -> dict:
    return _repository.create_blackjack_tournament_hand(tg_id, tournament_id, bet_chips)


def blackjack_tournament_hit(tg_id: int, hand_id: int) -> dict:
    return _repository.blackjack_tournament_hit(tg_id, hand_id)


def blackjack_tournament_stand(tg_id: int, hand_id: int) -> dict:
    return _repository.blackjack_tournament_stand(tg_id, hand_id)


def blackjack_tournament_double(tg_id: int, hand_id: int) -> dict:
    return _repository.blackjack_tournament_double(tg_id, hand_id)


def blackjack_tournament_surrender(tg_id: int, hand_id: int) -> dict:
    return _repository.blackjack_tournament_surrender(tg_id, hand_id)


def force_settle_tournament_hands(tournament_id: int) -> dict:
    return _repository.force_settle_tournament_hands(tournament_id)


def settle_blackjack_tournament(tournament_id: int) -> dict:
    return _repository.settle_blackjack_tournament(tournament_id)


def get_blackjack_config(config_key: str = "config") -> str | None:
    return _repository.get_blackjack_config(config_key)


def set_blackjack_config(config_key: str, config_json: str) -> bool:
    return _repository.set_blackjack_config(config_key, config_json)


def get_blackjack_config_dict() -> dict:
    return _repository.get_blackjack_config_dict()


def free_spin_progress(tg_id: int):
    return _repository.free_spin_progress(tg_id)


# analytics 是只读聚合模块，导入必须排在包级包装函数之后（它反过来要用
# get_blackjack_config_dict），否则会形成部分初始化循环导入。
from . import analytics


def cash_hand_metrics_tx(
    session,
    tg_id: int,
    since: int,
    until: int,
    *,
    min_bet: float | None = None,
    min_accuracy: float | None = None,
):
    """手牌口径的条件计数（调用方持有事务）。"""
    return analytics.cash_hand_metrics_tx(
        session,
        tg_id,
        since,
        until,
        min_bet=min_bet,
        min_accuracy=min_accuracy,
    )


def count_tournament_entries_tx(session, tg_id: int, since: int, until: int) -> int:
    """锦标赛参赛次数的条件计数（已取消赛事不计，调用方持有事务）。"""
    return analytics.count_tournament_entries_tx(session, tg_id, since, until)


__all__ = [
    "BLACKJACK_CONFIG",
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
    "apply_blackjack_retention_tx",
    "blackjack_double",
    "blackjack_double_tx",
    "blackjack_hit",
    "blackjack_hit_tx",
    "blackjack_stand",
    "blackjack_stand_tx",
    "blackjack_surrender",
    "blackjack_surrender_tx",
    "blackjack_tournament_double",
    "blackjack_tournament_double_tx",
    "blackjack_tournament_hit",
    "blackjack_tournament_hit_tx",
    "blackjack_tournament_stand",
    "blackjack_tournament_stand_tx",
    "blackjack_tournament_surrender",
    "blackjack_tournament_surrender_tx",
    "cancel_blackjack_tournament",
    "cash_hand_metrics_tx",
    "check_blackjack_tournament_consistency",
    "claim_tournament_reminder",
    "claim_unannounced_jackpot_wins",
    "count_registering_blackjack_tournaments",
    "count_tournament_entries_tx",
    "count_user_blackjack_tournament_titles",
    "create_blackjack_hand",
    "create_blackjack_hand_tx",
    "create_blackjack_tournament",
    "create_blackjack_tournament_hand",
    "create_blackjack_tournament_hand_tx",
    "credit_tournament_wallet_tx",
    "force_settle_tournament_hands",
    "free_spin_progress",
    "get_blackjack_admin_stats",
    "get_blackjack_admin_stats_tx",
    "get_blackjack_config",
    "get_blackjack_config_dict",
    "get_blackjack_config_dict_tx",
    "get_blackjack_config_tx",
    "get_blackjack_free_hands_remaining",
    "get_blackjack_jackpot",
    "get_blackjack_tournament",
    "get_blackjack_tournament_standings",
    "get_blackjack_tournament_wallet",
    "get_current_blackjack_hand",
    "get_user_blackjack_stats",
    "get_user_blackjack_stats_tx",
    "get_user_blackjack_tournament_entry",
    "list_active_blackjack_hands",
    "list_blackjack_tournaments",
    "list_blackjack_tournaments_with_playing_entries",
    "read_fund_balance",
    "register_blackjack_tournament",
    "register_blackjack_tournament_tx",
    "seed_blackjack_jackpot",
    "set_blackjack_config",
    "set_blackjack_config_tx",
    "settle_blackjack_hand_by_timeout",
    "settle_blackjack_hand_by_timeout_tx",
    "settle_blackjack_tournament",
    "settle_blackjack_tournament_tx",
    "settle_blackjack_weekly_cashback",
    "start_blackjack_tournament",
    "sweep_timed_out_blackjack_hands",
    "update_blackjack_tournament",
]


def apply_blackjack_retention_tx(
    session,
    hand,
    stats,
    *,
    outcome: str,
    config: dict,
    now_ts: int,
) -> dict:
    return _repository.apply_blackjack_retention_tx(
        session,
        hand,
        stats,
        outcome=outcome,
        config=config,
        now_ts=now_ts,
    )


def create_blackjack_hand_tx(
    session, tg_id: int, bet_credits: int, *, config: dict, now_ms: int
) -> dict:
    return _repository.create_blackjack_hand_tx(
        session, tg_id, bet_credits, config=config, now_ms=now_ms
    )


def blackjack_hit_tx(
    session, tg_id: int, hand_id: int, *, jackpot_config: dict
) -> dict:
    return _repository.blackjack_hit_tx(
        session, tg_id, hand_id, jackpot_config=jackpot_config
    )


def blackjack_stand_tx(
    session, tg_id: int, hand_id: int, *, jackpot_config: dict
) -> dict:
    return _repository.blackjack_stand_tx(
        session, tg_id, hand_id, jackpot_config=jackpot_config
    )


def blackjack_double_tx(
    session, tg_id: int, hand_id: int, *, jackpot_config: dict
) -> dict:
    return _repository.blackjack_double_tx(
        session, tg_id, hand_id, jackpot_config=jackpot_config
    )


def blackjack_surrender_tx(session, tg_id: int, hand_id: int, *, config: dict) -> dict:
    return _repository.blackjack_surrender_tx(session, tg_id, hand_id, config=config)


def settle_blackjack_hand_by_timeout_tx(
    session, hand_id: int, *, jackpot_config: dict
) -> dict:
    return _repository.settle_blackjack_hand_by_timeout_tx(
        session, hand_id, jackpot_config=jackpot_config
    )


def create_blackjack_tournament_hand_tx(
    session,
    tg_id: int,
    tournament_id: int,
    bet_chips: int,
    *,
    config: dict,
) -> dict:
    return _repository.create_blackjack_tournament_hand_tx(
        session, tg_id, tournament_id, bet_chips, config=config
    )


def blackjack_tournament_hit_tx(session, tg_id: int, hand_id: int) -> dict:
    return _repository.blackjack_tournament_hit_tx(session, tg_id, hand_id)


def blackjack_tournament_stand_tx(session, tg_id: int, hand_id: int) -> dict:
    return _repository.blackjack_tournament_stand_tx(session, tg_id, hand_id)


def blackjack_tournament_double_tx(session, tg_id: int, hand_id: int) -> dict:
    return _repository.blackjack_tournament_double_tx(session, tg_id, hand_id)


def blackjack_tournament_surrender_tx(session, tg_id: int, hand_id: int) -> dict:
    return _repository.blackjack_tournament_surrender_tx(session, tg_id, hand_id)


def settle_blackjack_tournament_tx(session, tournament_id: int) -> dict:
    return _repository.settle_blackjack_tournament_tx(session, tournament_id)


def get_user_blackjack_stats_tx(session, tg_id: int) -> dict:
    return _repository.get_user_blackjack_stats_tx(session, tg_id)


def get_blackjack_admin_stats_tx(session) -> dict:
    return _repository.get_blackjack_admin_stats_tx(session)


def get_blackjack_config_tx(session, config_key: str = "config") -> str | None:
    return _repository.get_blackjack_config_tx(session, config_key)


def get_blackjack_config_dict_tx(session) -> dict:
    return _repository.get_blackjack_config_dict_tx(session)


def set_blackjack_config_tx(session, config_key: str, config_json: str) -> bool:
    return _repository.set_blackjack_config_tx(session, config_key, config_json)


def register_blackjack_tournament_tx(
    session,
    tg_id: int,
    tournament_id: int,
    *,
    config: dict,
    now_ms: int,
) -> dict:
    return _repository.register_blackjack_tournament_tx(
        session, tg_id, tournament_id, config=config, now_ms=now_ms
    )


def tournament_to_dict(tournament) -> dict:
    return _repository._tournament_to_dict(tournament)


def tournament_entry_to_dict(entry) -> dict:
    return _repository._tournament_entry_to_dict(entry)


def blackjack_week_start_ms(*, now=None) -> int:
    return _repository._blackjack_week_start_ms(now=now)


def lock_running_tournament(session, tournament_id: int):
    return _repository._lock_running_tournament(session, tournament_id)
