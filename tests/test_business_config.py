from __future__ import annotations

from app.business_config import CONFIGS, LEGACY_ENV, seed_all
from app.core import kv
from app.core.db import get_session
from app.domains.accounts.config import ACCOUNTS_CONFIG
from app.domains.donation import service as donation_service
from app.domains.invitation.config import INVITATION_CONFIG
from app.domains.media_access import service as media_access_service
from app.domains.premium import service as premium_service
from app.domains.traffic import service as traffic_service
from app.domains.vaultwarden import service as vaultwarden_service


def _clear_config_caches() -> None:
    for config in CONFIGS:
        config.invalidate()


def test_seed_all_is_idempotent_and_uses_legacy_defaults(session_env) -> None:
    _clear_config_caches()
    first = seed_all()
    assert sum(report.inserted for report in first) > 0

    with get_session() as session:
        assert kv.get_tx(session, "config.accounts", "plex_register") == "false"
        assert kv.get_tx(session, "config.invitation", "invitation_credits") == "288"

    second = seed_all()
    assert all(report.inserted == 0 for report in second)


def test_seed_uses_legacy_value_and_warns_for_residual_key(session_env, caplog) -> None:
    _clear_config_caches()
    LEGACY_ENV.data_path.write_text("INVITATION_CREDITS=321\n", encoding="utf-8")
    try:
        report = INVITATION_CONFIG.seed()
        assert report.inserted == 1
        assert INVITATION_CONFIG.get().invitation_credits == 321
        LEGACY_ENV.warn_migrated_keys()
        assert "INVITATION_CREDITS" in caplog.text
    finally:
        LEGACY_ENV.data_path.unlink(missing_ok=True)
        INVITATION_CONFIG.invalidate()


def test_migrated_domain_updates_are_read_on_next_call(session_env) -> None:
    _clear_config_caches()
    premium_service.set_credits_cost_per_10gb(7)
    media_access_service.set_nsfw_libs(["Private"])
    donation_service.set_donation_multiplier(9)
    traffic_service.set_user_traffic_limit(123)
    vaultwarden_service.set_redeem_credits(456)

    assert premium_service.get_credits_cost_per_10gb() == 7
    assert media_access_service.get_nsfw_libs() == ["Private"]
    assert donation_service.get_donation_multiplier() == 9
    assert traffic_service.get_user_traffic_limit() == 123
    assert vaultwarden_service.get_redeem_credits() == 456


def test_existing_database_value_wins_over_legacy_source(session_env) -> None:
    _clear_config_caches()
    ACCOUNTS_CONFIG.seed()
    INVITATION_CONFIG.seed()
    ACCOUNTS_CONFIG.update(plex_register=True)
    INVITATION_CONFIG.update(invitation_credits=999)

    assert ACCOUNTS_CONFIG.get().plex_register is True
    assert INVITATION_CONFIG.get().invitation_credits == 999
