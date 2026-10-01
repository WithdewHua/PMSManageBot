"""Application-facing service for the manual Telegram ID rebind command."""

from __future__ import annotations

from app.core.config import settings
from app.core.log import logger
from app.domains.identity import service as identity_service
from app.domains.tg_rebind import repository
from app.domains.tg_rebind.types import RebindReport


def rebind(
    new_tg_id: int,
    *,
    from_tg_id: int | None = None,
    plex_email: str | None = None,
    emby_username: str | None = None,
    dry_run: bool = False,
) -> RebindReport:
    """Run the atomic rebind and annotate administrator configuration impact."""
    report = repository.rebind_tg_id(
        new_tg_id=int(new_tg_id),
        from_tg_id=from_tg_id,
        plex_email=plex_email,
        emby_username=emby_username,
        dry_run=dry_run,
    )
    if not report.dry_run:
        try:
            identity_service.refresh_user_info_for_tg(report.new_tg_id)
        except Exception as error:  # post-commit cache refresh must not undo success
            logger.warning("TG rebind cache refresh failed: %s", error)
    return RebindReport(
        old_tg_id=report.old_tg_id,
        new_tg_id=report.new_tg_id,
        dry_run=report.dry_run,
        counts=report.counts,
        admin_configuration_warning=report.old_tg_id in settings.TG_ADMIN_CHAT_ID,
    )


__all__ = ["rebind"]
