"""Luckywheel configuration declarations and atomic state switches."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from app.core import kv as core_kv
from app.core.domain_config import DomainConfig, JsonDocument
from app.domains.luckywheel.schemas import LuckyWheelConfig, LuckyWheelItem

CONFIG_TYPE = "lucky_wheel"
CONFIG_KEY = "config"
RANDOMNESS_CONFIG_KEY = "randomness_config"

DEFAULT_WHEEL_CONFIG = LuckyWheelConfig(
    items=[
        LuckyWheelItem(name="谢谢参与", probability=15.0),
        LuckyWheelItem(name="积分 +10", probability=25.0),
        LuckyWheelItem(name="积分 -10", probability=20.0),
        LuckyWheelItem(name="积分 +30", probability=15.0),
        LuckyWheelItem(name="积分 -30", probability=10.0),
        LuckyWheelItem(name="邀请码 1 枚", probability=0.3),
        LuckyWheelItem(name="积分 +50", probability=7),
        LuckyWheelItem(name="积分 -50", probability=6),
        LuckyWheelItem(name="积分翻倍", probability=1),
        LuckyWheelItem(name="积分减半", probability=0.7),
    ],
    cost_credits=10,
    min_credits_required=30,
)


class RandomnessConfigModel(BaseModel):
    """Typed defaults for random-selection tuning; unknown keys remain valid."""

    model_config = ConfigDict(frozen=True, extra="allow")

    use_weighted_protection: bool = True
    protection_threshold: float = Field(2.0, gt=0, le=50)
    protection_factor: float = Field(1.2, ge=1.0, le=3.0)
    use_time_seed_mixing: bool = True
    use_user_seed_mixing: bool = True


WHEEL_CONFIG = DomainConfig(
    "luckywheel.wheel",
    LuckyWheelConfig,
    JsonDocument(CONFIG_TYPE, CONFIG_KEY),
    default=DEFAULT_WHEEL_CONFIG,
)
RANDOMNESS_CONFIG = DomainConfig(
    "luckywheel.randomness",
    RandomnessConfigModel,
    JsonDocument(CONFIG_TYPE, RANDOMNESS_CONFIG_KEY),
)


def get_wheel_config() -> LuckyWheelConfig:
    """Read the typed wheel document, seeding it only when absent."""
    return WHEEL_CONFIG.get()


def get_randomness_config() -> dict:
    """Read the latest randomness document without process-level state."""
    return RANDOMNESS_CONFIG.get().model_dump(mode="python")


def save_randomness_config(config: dict) -> bool:
    """Persist a randomness document, merging arbitrary legacy keys."""
    RANDOMNESS_CONFIG.update(**config)
    return True


def save_wheel_config(config: LuckyWheelConfig) -> bool:
    """Persist the complete wheel configuration in its domain-owned document."""
    WHEEL_CONFIG.update(**config.model_dump(mode="python"))
    return True


def ensure_wheel_config_tx(session, config: LuckyWheelConfig) -> None:
    """Create the config row for legacy/test databases that do not have one yet."""
    if core_kv.get_tx(session, CONFIG_TYPE, CONFIG_KEY) is None:
        stored = core_kv.insert_if_absent_tx(
            session,
            CONFIG_TYPE,
            CONFIG_KEY,
            json.dumps(config.model_dump(mode="python"), ensure_ascii=False),
        )
        # The row may have been created by another transaction; either way the
        # current transaction must not leave a stale process-local document.
        if stored:
            WHEEL_CONFIG.invalidate_after_commit(session)


def consume_privileged_code_toggle_tx(session) -> bool:
    """Atomically consume the one-shot privileged-invite switch."""
    return core_kv.compare_and_update_tx(
        session,
        CONFIG_TYPE,
        CONFIG_KEY,
        lambda document: document.get("gen_privileged_code") is True,
        gen_privileged_code=False,
    )


__all__ = [
    "CONFIG_KEY",
    "CONFIG_TYPE",
    "DEFAULT_WHEEL_CONFIG",
    "RANDOMNESS_CONFIG",
    "RANDOMNESS_CONFIG_KEY",
    "WHEEL_CONFIG",
    "RandomnessConfigModel",
    "consume_privileged_code_toggle_tx",
    "ensure_wheel_config_tx",
    "get_randomness_config",
    "get_wheel_config",
    "save_randomness_config",
    "save_wheel_config",
]
