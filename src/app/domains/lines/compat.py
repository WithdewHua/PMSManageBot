"""SQLAlchemy-free compatibility facade for legacy line database calls."""

from __future__ import annotations

from app.domains.lines import repository


class LinesCompat:
    """Forward the legacy ``DatabaseORM`` lines API to module repositories.

    The class is intentionally a transport-only compatibility boundary. New
    lines code should import :mod:`app.domains.lines.repository` directly (or
    the service for orchestration) instead of adding methods here.
    """

    def set_emby_line(
        self, line: str, tg_id: int | None = None, emby_id: str | None = None
    ) -> bool:
        return repository.set_emby_line(line, tg_id=tg_id, emby_id=emby_id)

    def get_emby_line(self, tg_id: int) -> str | None:
        return repository.get_emby_line(tg_id)

    def get_emby_user_with_binded_line(self) -> list:
        return repository.get_emby_user_with_binded_line()

    def set_plex_line(
        self, line: str, tg_id: int | None = None, plex_id: int | None = None
    ) -> bool:
        return repository.set_plex_line(line, tg_id=tg_id, plex_id=plex_id)

    def get_plex_line(self, tg_id: int) -> str | None:
        return repository.get_plex_line(tg_id)

    def get_plex_user_with_binded_line(self) -> list:
        return repository.get_plex_user_with_binded_line()

    def get_free_premium_lines(self) -> list[str]:
        return repository.get_free_premium_lines()

    def set_free_premium_lines(self, lines: list[str]) -> bool:
        return repository.set_free_premium_lines(lines)

    def is_free_premium_line(self, line_name: str) -> bool:
        return repository.is_free_premium_line(line_name)

    def get_line_tags(self, line_name: str) -> list[str]:
        return repository.get_line_tags(line_name)

    def set_line_tags(self, line_name: str, tags: list[str]) -> bool:
        return repository.set_line_tags(line_name, tags)

    def delete_line_tags(self, line_name: str) -> bool:
        return repository.delete_line_tags(line_name)

    def get_all_line_tags(self) -> dict:
        return repository.get_all_line_tags()

    def check_line_schedule_unlock(self, tg_id: int, service: str) -> dict:
        return repository.check_line_schedule_unlock(tg_id, service)

    def unlock_line_schedule_with_credit(
        self, tg_id: int, service: str, cost: float
    ) -> bool:
        return repository.unlock_line_schedule_with_credit(tg_id, service, cost)

    def unlock_line_schedule(self, tg_id: int, service: str) -> bool:
        return repository.unlock_line_schedule(tg_id, service)

    def create_line_schedule(
        self,
        tg_id: int,
        service: str,
        line: str,
        days_of_week: list[int],
        start_time: str,
        end_time: str,
        priority: int = 0,
    ) -> int | None:
        return repository.create_line_schedule(
            tg_id,
            service,
            line,
            days_of_week,
            start_time,
            end_time,
            priority,
        )

    def get_user_line_schedules(
        self,
        tg_id: int,
        service: str | None = None,
        enabled_only: bool = False,
    ) -> list[dict]:
        return repository.get_user_line_schedules(tg_id, service, enabled_only)

    def update_line_schedule(self, schedule_id: int, tg_id: int, **kwargs) -> bool:
        return repository.update_line_schedule(schedule_id, tg_id, **kwargs)

    def delete_line_schedule(self, schedule_id: int, tg_id: int) -> bool:
        return repository.delete_line_schedule(schedule_id, tg_id)

    def check_schedule_conflict(
        self,
        tg_id: int,
        service: str,
        days_of_week: list[int],
        start_time: str,
        end_time: str,
        exclude_id: int | None = None,
    ) -> bool:
        return repository.check_schedule_conflict(
            tg_id, service, days_of_week, start_time, end_time, exclude_id
        )

    def get_current_active_schedule(self, tg_id: int, service: str) -> dict | None:
        return repository.get_current_active_schedule(tg_id, service)

    def disable_schedules_by_line(
        self, line_name: str, only_non_premium: bool = False
    ) -> tuple[bool, int, list[dict]]:
        return repository.disable_schedules_by_line(
            line_name, only_non_premium=only_non_premium
        )

    def get_users_with_line_schedule(self, line_name: str) -> list[dict]:
        return repository.get_users_with_line_schedule(line_name)


__all__ = ["LinesCompat"]
