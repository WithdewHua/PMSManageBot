"""21 点 repository：配置行的读写（由 part_N 机械拆分）。"""

import json
import time

from sqlalchemy import select

from app.core.kv import SystemConfig
from app.core.log import logger
from app.domains.blackjack.config import DEFAULT_BLACKJACK_CONFIG


class _BlackjackRepositoryConfigStore:
    def get_blackjack_config_tx(
        self, session, config_key: str = "config"
    ) -> str | None:
        return session.execute(
            select(SystemConfig.config_value).where(
                SystemConfig.config_type == "blackjack",
                SystemConfig.config_key == config_key,
            )
        ).scalar_one_or_none()

    def set_blackjack_config_tx(
        self, session, config_key: str, config_json: str
    ) -> bool:
        current_time = int(time.time())
        existing = (
            session.execute(
                select(SystemConfig)
                .where(
                    SystemConfig.config_type == "blackjack",
                    SystemConfig.config_key == config_key,
                )
                .with_for_update()
            )
            .scalars()
            .one_or_none()
        )
        if existing is None:
            session.add(
                SystemConfig(
                    config_type="blackjack",
                    config_key=config_key,
                    config_value=config_json,
                    created_at=current_time,
                    updated_at=current_time,
                )
            )
        else:
            existing.config_value = config_json
            existing.updated_at = current_time
        return True

    def get_blackjack_config_dict_tx(self, session) -> dict:
        raw = self.get_blackjack_config_tx(session, "config")
        config = dict(DEFAULT_BLACKJACK_CONFIG)
        if raw:
            try:
                stored = json.loads(raw)
                if isinstance(stored, dict):
                    config.update(stored)
            except Exception as e:
                logger.error(f"解析 21 点配置失败，回退默认配置: {e}")
        else:
            self.set_blackjack_config_tx(
                session, "config", json.dumps(config, ensure_ascii=False)
            )
        return config

    def get_blackjack_config(self, config_key: str = "config") -> str | None:
        """
        获取 21 点配置

        Args:
            config_key: 配置键 (config)

        Returns:
            配置的 JSON 字符串
        """
        return self.get_system_config("blackjack", config_key)

    def set_blackjack_config(self, config_key: str, config_json: str) -> bool:
        """
        设置 21 点配置

        Args:
            config_key: 配置键 (config)
            config_json: 配置的 JSON 字符串

        Returns:
            是否成功
        """
        return self.set_system_config("blackjack", config_key, config_json)

    def get_blackjack_config_dict(self) -> dict:
        """
        获取 21 点配置字典，缺失项以默认值补全；首次读取时把默认配置落库。

        每手牌在发牌时会把其中的关键参数快照到手牌行上，结算读快照而非读本方法，
        故管理员改配置不影响进行中的手牌。
        """
        raw = self.get_blackjack_config("config")
        config = dict(DEFAULT_BLACKJACK_CONFIG)
        if raw:
            try:
                stored = json.loads(raw)
                if isinstance(stored, dict):
                    config.update(stored)
            except Exception as e:
                logger.error(f"解析 21 点配置失败，回退默认配置: {e}")
        else:
            # 首次读取时落库，便于管理员在面板上看到完整的初始配置
            self.set_blackjack_config("config", json.dumps(config, ensure_ascii=False))
        return config
