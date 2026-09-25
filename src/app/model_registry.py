"""Explicit registration of every SQLAlchemy model before metadata use."""

from __future__ import annotations

from sqlalchemy import MetaData

from app.core import kv as core_kv
from app.core.db import Base
from app.domains.auction import models as auction_models
from app.domains.badges import models as badges_models
from app.domains.blackjack import models as blackjack_models
from app.domains.crypto_donation import models as crypto_donation_models
from app.domains.custom_lines import models as custom_lines_models
from app.domains.donation import models as donation_models
from app.domains.gift_pack import models as gift_pack_models
from app.domains.identity import models as identity_models
from app.domains.invitation import models as invitation_models
from app.domains.lines import models as lines_models
from app.domains.luckywheel import models as luckywheel_models
from app.domains.prediction import models as prediction_models
from app.domains.traffic import models as traffic_models
from app.domains.treasure import models as treasure_models
from app.domains.vaultwarden import models as vaultwarden_models
from app.domains.watch_rewards import models as watch_rewards_models

# Explicit references make missing model modules detectable at import time.
MODEL_MODULES = (
    core_kv,
    auction_models,
    badges_models,
    blackjack_models,
    crypto_donation_models,
    custom_lines_models,
    donation_models,
    gift_pack_models,
    identity_models,
    invitation_models,
    lines_models,
    luckywheel_models,
    prediction_models,
    traffic_models,
    treasure_models,
    vaultwarden_models,
    watch_rewards_models,
)
metadata: MetaData = Base.metadata


def init_db() -> None:
    """Create all registered tables using the existing application engine."""
    from app.core.db import init_db as initialize_session_db

    initialize_session_db()


__all__ = ["MODEL_MODULES", "init_db", "metadata"]
