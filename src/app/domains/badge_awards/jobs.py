"""Scheduled bulk badge checks (persistent job import paths remain stable)."""

from app.domains.badge_awards import service


async def check_and_award_supreme_contributor_badge(
    user_id: int | None = None,
) -> bool | None:
    return await service.check_and_award_supreme_contributor_badge(user_id)


async def check_and_award_game_king_badge(user_id: int | None = None) -> bool | None:
    return await service.check_and_award_game_king_badge(user_id)
