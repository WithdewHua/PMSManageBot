"""Application-level registrations that bridge optional domain providers."""

from app.core import events
from app.domains.accounts.events import PlexUserIdResolved
from app.domains.badge_awards import service as badge_awards_service
from app.domains.blackjack import events as blackjack_events
from app.domains.blackjack import service as blackjack_service
from app.domains.crypto_donation import events as crypto_donation_events
from app.domains.donation import events as donation_events
from app.domains.invitation import service as invitation_service
from app.domains.luckywheel import events as luckywheel_events
from app.domains.luckywheel import service as luckywheel_service
from app.domains.prediction import events as prediction_events
from app.domains.treasure import events as treasure_events


def _handle_plex_user_id_resolved(event: PlexUserIdResolved) -> None:
    invitation_service.update_invitation_plex_id(event.email, event.plex_id)


def register_all() -> None:
    """Register source-owned providers and post-commit domain handlers."""
    luckywheel_service.register_free_spin_progress_provider(
        blackjack_service.free_spin_progress
    )
    events.subscribe(PlexUserIdResolved, _handle_plex_user_id_resolved)
    for event_type in (
        blackjack_events.CashHandPlayed,
        luckywheel_events.WheelSpun,
        prediction_events.PredictionBetPlaced,
        treasure_events.TreasureJoined,
    ):
        events.subscribe_async(event_type, badge_awards_service.on_game_activity)
    for event_type in (
        donation_events.DonationApproved,
        crypto_donation_events.CryptoDonationCompleted,
    ):
        events.subscribe_async(event_type, badge_awards_service.on_donation)


register_subscriptions = register_all


__all__ = ["register_all", "register_subscriptions"]
