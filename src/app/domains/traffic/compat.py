"""Temporary SQLAlchemy-free compatibility surface for ``DatabaseORM``."""

from __future__ import annotations

from app.domains.traffic import repository, service


class TrafficCompat:
    """Forward legacy ``db`` method names to traffic boundaries.

    This class is intentionally tiny and contains no SQL, ORM model, or
    session-management code.  It can be removed when remaining domains stop
    using the legacy database facade.
    """

    def create_line_traffic_entry(self, *args, **kwargs) -> tuple[bool, bool]:
        return repository.create_line_traffic_entry(*args, **kwargs)

    def bulk_create_line_traffic_entries(
        self, rows: list[dict], **kwargs
    ) -> dict[str, str]:
        return repository.bulk_create_line_traffic_entries(rows, **kwargs)

    def get_premium_line_traffic_statistics(self) -> list:
        return service.premium_line_statistics()

    def get_user_daily_traffic(self, *args, **kwargs) -> int:
        return service.daily_usage(*args, **kwargs)

    def get_plex_traffic_rank(self, start_date=None, end_date=None) -> list:
        return service.traffic_rank("plex", start_date, end_date)

    def get_emby_traffic_rank(self, start_date=None, end_date=None) -> list:
        return service.traffic_rank("emby", start_date, end_date)

    def aggregate_monthly_traffic_data(self, target_month: str | None = None) -> tuple:
        return service.aggregate_monthly_traffic_data(target_month)

    def cleanup_monthly_traffic_data(self, target_month: str) -> tuple:
        return service.cleanup_monthly_traffic_data(target_month)

    def update_traffic_username(self, old_username: str, new_username: str) -> bool:
        return service.rename_user(old_username, new_username)


__all__ = ["TrafficCompat"]
