"""Ranking workflows exposed to interface modules."""

from app.domains.blackjack import service as blackjack_service
from app.domains.prediction import service as prediction_service
from app.domains.rankings import repository as rankings_repository


def get_wheel_credits_rank() -> list:
    return rankings_repository.rankings_repository.get_wheel_credits_rank()


def get_wheel_invite_code_rank() -> list:
    return rankings_repository.rankings_repository.get_wheel_invite_code_rank()


def get_treasure_win_issue_rank() -> list:
    return rankings_repository.rankings_repository.get_treasure_win_issue_rank()


def get_treasure_win_credits_rank() -> list:
    return rankings_repository.rankings_repository.get_treasure_win_credits_rank()


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
    "get_treasure_win_credits_rank",
    "get_treasure_win_issue_rank",
    "get_wheel_credits_rank",
    "get_wheel_invite_code_rank",
]
