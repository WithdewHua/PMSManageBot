"""Application-level registrations that bridge optional domain providers."""

from app.domains.blackjack import service as blackjack_service
from app.domains.luckywheel import service as luckywheel_service


def register_subscriptions() -> None:
    """Register source-owned progress providers before serving requests."""
    luckywheel_service.register_free_spin_progress_provider(
        blackjack_service.free_spin_progress
    )


__all__ = ["register_subscriptions"]
