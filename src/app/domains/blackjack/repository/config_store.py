"""Blackjack repository compatibility wrappers for runtime configuration."""

import json

from app.core import kv as core_kv
from app.core.db import get_session, register_post_commit
from app.core.log import logger
from app.domains.blackjack.config import BLACKJACK_CONFIG


class _BlackjackRepositoryConfigStore:
    def get_blackjack_config_tx(
        self, session, config_key: str = "config"
    ) -> str | None:
        return core_kv.get_tx(session, "blackjack", config_key)

    def set_blackjack_config_tx(
        self, session, config_key: str, config_json: str
    ) -> bool:
        core_kv.upsert_tx(session, "blackjack", config_key, config_json)
        register_post_commit(
            session,
            "domain-config:blackjack.game",
            BLACKJACK_CONFIG.invalidate,
        )
        return True

    def get_blackjack_config_dict_tx(self, session) -> dict:
        return BLACKJACK_CONFIG.get_tx(session).model_dump(mode="python")

    def get_blackjack_config(self, config_key: str = "config") -> str | None:
        """Return the raw legacy JSON value for compatibility callers."""
        return core_kv.get("blackjack", config_key)

    def set_blackjack_config(self, config_key: str, config_json: str) -> bool:
        """Persist the raw legacy JSON value and invalidate the domain cache."""
        try:
            # Validate the primary document before replacing it, while retaining
            # extra keys accepted by the legacy JSON contract.
            if config_key == "config":
                BLACKJACK_CONFIG.model.model_validate(json.loads(config_json))
            with get_session() as session:
                core_kv.upsert_tx(session, "blackjack", config_key, config_json)
            if config_key == "config":
                BLACKJACK_CONFIG.invalidate()
            return True
        except Exception as error:
            logger.error(f"保存 21 点配置失败: {error}")
            return False

    def get_blackjack_config_dict(self) -> dict:
        """Return the typed configuration, seeding only a missing document."""
        return BLACKJACK_CONFIG.get().model_dump(mode="python")
