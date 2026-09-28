"""Luckywheel configuration access and atomic one-shot switches."""

from __future__ import annotations

import json

from app.core import kv as core_kv

_config_repository = core_kv.SystemConfigRepository()
from app.core.log import logger
from app.domains.luckywheel import rules as luckywheel_rules
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


def get_wheel_config() -> LuckyWheelConfig:
    """Read the wheel configuration, creating the default document if needed."""
    try:
        raw = _config_repository.get_system_config(CONFIG_TYPE, CONFIG_KEY)
        if raw:
            return LuckyWheelConfig(**json.loads(raw))
        _config_repository.set_system_config(
            CONFIG_TYPE, CONFIG_KEY, DEFAULT_WHEEL_CONFIG.model_dump_json()
        )
        return DEFAULT_WHEEL_CONFIG.model_copy(deep=True)
    except Exception as error:
        logger.error(f"获取转盘配置失败: {error}")
        return DEFAULT_WHEEL_CONFIG.model_copy(deep=True)


def get_randomness_config() -> dict:
    """Read the latest randomness document for transactional spin selection."""
    try:
        raw = _config_repository.get_system_config(CONFIG_TYPE, RANDOMNESS_CONFIG_KEY)
        if raw:
            document = json.loads(raw)
            if isinstance(document, dict):
                return document
    except Exception as error:
        logger.error(f"获取随机性配置失败: {error}")
    return luckywheel_rules.RandomnessConfig.to_dict()


def save_randomness_config(config: dict) -> bool:
    """Persist the runtime randomness document in the wheel domain."""
    return _config_repository.set_system_config(
        CONFIG_TYPE, RANDOMNESS_CONFIG_KEY, json.dumps(config)
    )


def save_wheel_config(config: LuckyWheelConfig) -> bool:
    """Persist the complete wheel configuration in its domain-owned document."""
    try:
        return _config_repository.set_system_config(
            CONFIG_TYPE, CONFIG_KEY, config.model_dump_json()
        )
    except Exception as error:
        logger.error(f"保存转盘配置失败: {error}")
        return False


def ensure_wheel_config_tx(session, config: LuckyWheelConfig) -> None:
    """Create the config row for legacy/test databases that do not have one yet."""
    if core_kv.get_tx(session, CONFIG_TYPE, CONFIG_KEY) is None:
        core_kv.upsert_tx(session, CONFIG_TYPE, CONFIG_KEY, config.model_dump_json())


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
    "RANDOMNESS_CONFIG_KEY",
    "consume_privileged_code_toggle_tx",
    "ensure_wheel_config_tx",
    "get_randomness_config",
    "get_wheel_config",
    "save_randomness_config",
    "save_wheel_config",
]
