"""Ranking workflows exposed to interface modules."""

from app.domains.blackjack import service as blackjack_service
from app.domains.prediction import service as prediction_service


def get_blackjack_skill_ranks(min_hands: int | None = None) -> dict:
    return blackjack_service.get_blackjack_skill_ranks(min_hands)


def get_blackjack_max_win_rank() -> list:
    return blackjack_service.get_blackjack_max_win_rank()


def get_prediction_net_profit_rank() -> list[dict]:
    return prediction_service.get_prediction_net_profit_rank()


def get_prediction_win_rate_rank() -> list[dict]:
    return prediction_service.get_prediction_win_rate_rank()


__all__ = [
    "get_blackjack_max_win_rank",
    "get_blackjack_skill_ranks",
    "get_prediction_net_profit_rank",
    "get_prediction_win_rate_rank",
]
