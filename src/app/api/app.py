"""FastAPI application assembly with stable middleware and route order."""

import secrets

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.lifespan import lifespan
from app.api.static import setup_static_files
from app.core.config import settings
from app.core.errors import DomainError
from app.core.log import logger
from app.domains.accounts.admin_router import router as accounts_admin
from app.domains.accounts.router import router as accounts
from app.domains.auction.router import router as auction_router
from app.domains.badges.router import router as badge_router
from app.domains.blackjack.router import (
    cash_router as blackjack_router,
)
from app.domains.blackjack.router import (
    tournament_admin_router as blackjack_tournament_admin_router,
)
from app.domains.blackjack.router import (
    tournament_router as blackjack_tournament_router,
)
from app.domains.credits.admin_router import router as credits_admin
from app.domains.credits.router import router as credits
from app.domains.crypto_donation.admin_router import router as crypto_donation_admin
from app.domains.crypto_donation.router import router as crypto_donation_router
from app.domains.custom_lines.admin_router import router as custom_lines_admin
from app.domains.custom_lines.router import router as custom_lines
from app.domains.donation.admin_router import router as donation_admin
from app.domains.donation.router import router as donation_router
from app.domains.gift_pack.router import router as gift_pack_router
from app.domains.invitation.admin_router import router as invitation_admin
from app.domains.invitation.router import router as invitation_router
from app.domains.lines.admin_router import router as lines_admin
from app.domains.lines.router import router as lines
from app.domains.luckywheel.router import router as luckywheel_router
from app.domains.media_access.admin_router import router as media_access_admin
from app.domains.media_access.router import router as media_access
from app.domains.prediction.router import router as prediction_router
from app.domains.premium.admin_router import router as premium_admin
from app.domains.premium.router import router as premium_router
from app.domains.profile.router import router as profile
from app.domains.rankings.router import router as rankings_router
from app.domains.reports.admin_router import router as reports_admin
from app.domains.reports.router import router as system_router
from app.domains.traffic.admin_router import router as traffic_admin
from app.domains.treasure.router import router as treasure_router
from app.domains.vaultwarden.admin_router import router as vaultwarden_admin
from app.domains.vaultwarden.router import router as vaultwarden_router
from app.subscriptions import register_subscriptions
from app.transport.http.errors import domain_error_handler
from app.transport.http.middleware import TelegramAuthMiddleware

register_subscriptions()


def _resolve_session_secret_key() -> str:
    if settings.SESSION_SECRET_KEY:
        return settings.SESSION_SECRET_KEY
    logger.warning(
        "SESSION_SECRET_KEY is not configured; generated an ephemeral session key"
    )
    return secrets.token_urlsafe(32)


_session_secret_key = _resolve_session_secret_key()

app = FastAPI(
    title="PMSManageBot API",
    description="API for PMSManageBot WebApp",
    lifespan=lifespan,
)
app.add_exception_handler(DomainError, domain_error_handler)

app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret_key,
    session_cookie="pmsmanagebot_session",
    max_age=86400,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TelegramAuthMiddleware)


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "ok", "message": "PMSManageBot is running"}


def _include_named_routes(routers, names) -> None:
    """Include split route objects in their legacy declaration order."""
    routes = {
        route.name: route
        for router in routers
        for route in router.routes
        if getattr(route, "name", None)
    }
    missing = [name for name in names if name not in routes]
    if missing:
        raise RuntimeError(f"missing assembled route(s): {missing}")
    for name in names:
        app.include_router(APIRouter(routes=[routes[name]]))


_include_named_routes(
    (profile, accounts, lines, media_access, credits, custom_lines),
    (
        "get_user_info",
        "bind_plex_account",
        "bind_emby_account",
        "get_emby_lines",
        "bind_emby_line",
        "unbind_emby_line",
        "get_nsfw_info",
        "nsfw_operation",
        "get_plex_lines",
        "bind_plex_line",
        "unbind_plex_line",
        "get_lines_generic",
        "bind_line_generic",
        "unbind_line_generic",
        "auth_bind_line",
        "get_emby_lines_by_user",
        "get_plex_lines_by_user",
        "transfer_credits",
        "get_all_users",
        "get_current_bound_line",
        "check_line_schedule_unlock_status",
        "unlock_line_schedule",
        "get_line_schedules",
        "create_line_schedule",
        "update_line_schedule",
        "delete_line_schedule",
        "get_line_schedule_status",
        "get_download_permission_status",
        "unlock_download_permission",
        "submit_custom_line",
        "get_my_custom_lines",
        "get_approved_custom_lines",
        "get_custom_line_detail",
        "update_custom_line",
        "delete_custom_line",
        "offline_custom_line",
        "online_custom_line",
        "renew_custom_line",
    ),
)
app.include_router(rankings_router)
app.include_router(system_router)
app.include_router(invitation_router)
app.include_router(premium_router)
_include_named_routes(
    (
        reports_admin,
        accounts_admin,
        premium_admin,
        donation_admin,
        lines_admin,
        invitation_admin,
        media_access_admin,
        traffic_admin,
        credits_admin,
        custom_lines_admin,
        crypto_donation_admin,
        vaultwarden_admin,
    ),
    (
        "get_admin_settings",
        "set_plex_register",
        "set_emby_register",
        "set_premium_free",
        "set_emby_premium_free",
        "set_free_premium_lines",
        "set_emby_free_premium_lines",
        "submit_donation_record",
        "set_line_tags",
        "get_line_tags_admin",
        "get_all_line_tags",
        "delete_line_tags",
        "set_invitation_credits",
        "set_unlock_credits",
        "set_premium_daily_credits",
        "set_user_traffic_limit",
        "set_premium_user_traffic_limit",
        "set_premium_unlock_enabled",
        "set_credits_transfer_enabled",
        "set_line_schedule_unlock_credits",
        "set_download_unlock_credits",
        "set_credits_cost_per_10gb",
        "set_nsfw_libs",
        "set_donation_multiplier",
        "set_upay_crypto_types",
        "set_vaultwarden_enabled",
        "set_vaultwarden_redeem_credits",
        "get_lines_config",
        "add_normal_line_generic",
        "add_premium_line_generic",
        "delete_normal_line_generic",
        "delete_premium_line_generic",
        "get_emby_lines",
        "add_normal_line",
        "add_premium_line",
        "delete_normal_line",
        "delete_premium_line",
        "generate_admin_invite_codes",
        "get_all_custom_lines",
        "approve_custom_line",
        "admin_update_custom_line",
        "admin_offline_custom_line",
        "admin_delete_custom_line",
        "admin_set_custom_line_tags",
    ),
)
app.include_router(donation_router)
app.include_router(crypto_donation_router)
app.include_router(luckywheel_router, prefix="/api")
app.include_router(blackjack_router, prefix="/api")
app.include_router(blackjack_tournament_router, prefix="/api")
app.include_router(blackjack_tournament_admin_router, prefix="/api")
app.include_router(auction_router, prefix="/api")
app.include_router(treasure_router, prefix="/api")
app.include_router(prediction_router, prefix="/api")
app.include_router(vaultwarden_router)
app.include_router(badge_router)
app.include_router(gift_pack_router)

# Static files must be mounted after every API route.
setup_static_files(app)
