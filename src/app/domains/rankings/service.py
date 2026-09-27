"""Ranking workflows exposed to interface modules."""

from app.domains.blackjack import service as blackjack_service


def get_blackjack_skill_ranks(min_hands: int | None = None) -> dict:
    return blackjack_service.get_blackjack_skill_ranks(min_hands)


def get_blackjack_max_win_rank() -> list:
    return blackjack_service.get_blackjack_max_win_rank()


__all__ = ["get_blackjack_max_win_rank", "get_blackjack_skill_ranks"]
