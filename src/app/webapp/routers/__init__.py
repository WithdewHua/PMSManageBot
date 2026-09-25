from app.webapp.routers.donation import router as donation_router
from app.webapp.routers.premium import router as premium_router
from app.webapp.routers.rankings import router as rankings_router
from app.webapp.routers.system import router as system_router
from app.webapp.routers.user import router as user_router

__all__ = [
    "donation_router",
    "premium_router",
    "rankings_router",
    "system_router",
    "user_router",
]
