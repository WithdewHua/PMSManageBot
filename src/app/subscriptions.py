"""Application-level registrations that bridge optional domain providers."""

from app.core.events import subscribe
from app.domains.accounts.events import PlexUserIdResolved
from app.domains.blackjack import service as blackjack_service
from app.domains.invitation import service as invitation_service
from app.domains.luckywheel import service as luckywheel_service


def _handle_plex_user_id_resolved(event: PlexUserIdResolved) -> None:
    invitation_service.update_invitation_plex_id(event.email, event.plex_id)


def register_all() -> None:
    """Register source-owned providers and post-commit domain handlers."""
    luckywheel_service.register_free_spin_progress_provider(
        blackjack_service.free_spin_progress
    )
    subscribe(PlexUserIdResolved, _handle_plex_user_id_resolved)


register_subscriptions = register_all


__all__ = ["register_all", "register_subscriptions"]
