"""Identity-owned scheduled entry points."""

from app.domains.identity import service as identity_service


def write_user_info_cache() -> None:
    """Refresh the identity-owned Redis user snapshots."""
    identity_service.write_user_info_cache()


__all__ = ["write_user_info_cache"]
