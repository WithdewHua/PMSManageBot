"""Compatibility reader for business settings that are moving out of ``.env``."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.core.log import logger


class LegacyEnvSource:
    """Read migrated keys with the pre-migration precedence and codecs.

    The explicit mappings make this source deterministic in tests while the
    default constructor follows the application layout: ``data/.env`` wins over
    process environment, which wins over the working-directory ``.env``.
    """

    def __init__(
        self,
        defaults: Mapping[str, Any] | None = None,
        *,
        data_path: str | Path | None = None,
        working_path: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.defaults = dict(defaults or {})
        if data_path is None:
            data_root = os.environ.get("DATA_DIR") or str(
                Path(__file__).parents[3] / "data"
            )
            data_path = Path(data_root) / ".env"
        self.data_path = Path(data_path)
        self.working_path = (
            Path(working_path) if working_path is not None else Path.cwd() / ".env"
        )
        self.environ = dict(os.environ if environ is None else environ)

    @staticmethod
    def _parse_file(path: Path) -> dict[str, str]:
        """Parse the legacy loader's permissive dotenv lines, last key wins."""
        values: dict[str, str] = {}
        if not path.exists():
            return values
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
        return values

    def _data_overrides(self) -> dict[str, Any]:
        """Apply data/.env sequentially, stopping at the first bad value."""
        overrides: dict[str, Any] = {}
        if not self.data_path.exists():
            return overrides
        try:
            for raw_line in self.data_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, raw_value = line.split("=", 1)
                key = key.strip()
                if key not in self.defaults or key == "WEBAPP_URL":
                    continue
                value = raw_value.strip().strip('"').strip("'")
                overrides[key] = self._coerce(key, value, self.defaults[key])
        except Exception as error:
            logger.warning("读取迁出业务配置时遇到旧解析错误，保留此前值: %s", error)
        return overrides

    @staticmethod
    def _coerce(key: str, value: str, default: Any) -> Any:
        if isinstance(default, bool):
            return value.lower() in ("true", "1", "yes", "on")
        if isinstance(default, int) and not isinstance(default, bool):
            return int(value)
        if isinstance(default, list):
            values = [item.strip() for item in value.split(",") if item.strip()]
            if key == "TG_ADMIN_CHAT_ID":
                return [int(item) for item in values if item.isdigit()]
            return values
        return value

    def _sources(self) -> tuple[dict[str, str], Mapping[str, str], dict[str, str]]:
        data = self._parse_file(self.data_path)
        working = self._parse_file(self.working_path)
        return data, self.environ, working

    def read(self, key: str) -> Any:
        if key not in self.defaults:
            raise KeyError(key)
        _, environ, working = self._sources()
        data_overrides = self._data_overrides()
        if key in data_overrides:
            return data_overrides[key]
        raw = environ.get(key, working.get(key))
        if raw is None:
            return self.defaults[key]
        return self._coerce(key, raw, self.defaults[key])

    def present_keys(self) -> set[str]:
        data, environ, working = self._sources()
        migrated = set(self.defaults)
        return migrated & (set(data) | set(environ) | set(working))

    def warn_migrated_keys(self) -> None:
        for key in sorted(self.present_keys()):
            logger.warning("业务配置键 %s 已迁出 .env，将以数据库配置为准", key)


__all__ = ["LegacyEnvSource"]
