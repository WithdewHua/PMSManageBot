"""Combined Blackjack cash-game and tournament routers."""

from app.domains.blackjack.router.cash import router as cash_router
from app.domains.blackjack.router.tournament import router as tournament_router
from app.domains.blackjack.router.tournament_admin import (
    router as tournament_admin_router,
)

__all__ = ["cash_router", "tournament_admin_router", "tournament_router"]
