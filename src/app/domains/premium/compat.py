"""SQL-free compatibility facade for legacy ``DatabaseORM`` callers."""

from app.domains.premium import service


class PremiumCompat:
    """Forward the legacy premium facade surface to the premium service."""

    def get_plex_premium_quota_status(self, plex_id: int) -> dict:
        return service.get_plex_premium_quota_status(plex_id)

    def get_emby_premium_quota_status(self, emby_username: str) -> dict:
        return service.get_emby_premium_quota_status(emby_username)

    def get_expired_premium_users(self) -> list:
        return service.get_expired_premium_users()

    def update_expired_premium_status(self) -> int:
        return service.update_expired_premium_status()

    def get_premium_users_expiring_soon(self, days: int = 3) -> list:
        return service.get_premium_users_expiring_soon(days)

    def get_premium_statistics(self) -> dict:
        return service.get_premium_statistics()

    def get_all_active_premium_users(self) -> list:
        return service.get_all_active_premium_users()

    def get_all_premium_traffic_debt_users(self) -> list:
        return service.get_all_premium_traffic_debt_users()
