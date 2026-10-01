"""Unit tests for scripts/migrate_redis_to_database.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.domains.luckywheel.schemas import LuckyWheelConfig
from scripts.migrate_redis_to_database import (
    main,
    migrate_free_premium_lines,
    migrate_line_tags,
    migrate_lucky_wheel_config,
)


def test_migrate_free_premium_lines_success() -> None:
    mock_redis = MagicMock()
    mock_redis.get.return_value = "line1, line2 , line3"

    with (
        patch("scripts.migrate_redis_to_database.Redis") as mock_redis_cls,
        patch(
            "scripts.migrate_redis_to_database.line_catalog.set_free_premium_lines",
            return_value=True,
        ) as mock_set_free,
    ):
        mock_redis_cls.return_value.get_connection.return_value = mock_redis
        migrate_free_premium_lines()

        mock_set_free.assert_called_once_with(["line1", "line2", "line3"])


def test_migrate_free_premium_lines_bytes() -> None:
    mock_redis = MagicMock()
    mock_redis.get.return_value = b"line_a, line_b"

    with (
        patch("scripts.migrate_redis_to_database.Redis") as mock_redis_cls,
        patch(
            "scripts.migrate_redis_to_database.line_catalog.set_free_premium_lines",
            return_value=True,
        ) as mock_set_free,
    ):
        mock_redis_cls.return_value.get_connection.return_value = mock_redis
        migrate_free_premium_lines()

        mock_set_free.assert_called_once_with(["line_a", "line_b"])


def test_migrate_free_premium_lines_empty() -> None:
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    with (
        patch("scripts.migrate_redis_to_database.Redis") as mock_redis_cls,
        patch(
            "scripts.migrate_redis_to_database.line_catalog.set_free_premium_lines"
        ) as mock_set_free,
    ):
        mock_redis_cls.return_value.get_connection.return_value = mock_redis
        migrate_free_premium_lines()

        mock_set_free.assert_not_called()


def test_migrate_free_premium_lines_handles_exception() -> None:
    with patch("scripts.migrate_redis_to_database.Redis") as mock_redis_cls:
        mock_redis_cls.side_effect = RuntimeError("Redis connection error")
        # Should not raise exception
        migrate_free_premium_lines()


def test_migrate_line_tags_success() -> None:
    mock_redis = MagicMock()
    mock_redis.scan_iter.return_value = [
        "emby_line_tags:line1",
        "emby_line_tags:line2",
    ]
    mock_redis.get.side_effect = ["tagA, tagB", "tagC"]

    with (
        patch("scripts.migrate_redis_to_database.Redis") as mock_redis_cls,
        patch(
            "scripts.migrate_redis_to_database.line_catalog.set_line_tags",
            return_value=True,
        ) as mock_set_tags,
    ):
        mock_redis_cls.return_value.get_connection.return_value = mock_redis
        migrate_line_tags()

        assert mock_set_tags.call_count == 2
        mock_set_tags.assert_any_call("line1", ["tagA", "tagB"])
        mock_set_tags.assert_any_call("line2", ["tagC"])


def test_migrate_line_tags_bytes() -> None:
    mock_redis = MagicMock()
    mock_redis.scan_iter.return_value = [b"emby_line_tags:line_bytes"]
    mock_redis.get.return_value = b"tag1, tag2"

    with (
        patch("scripts.migrate_redis_to_database.Redis") as mock_redis_cls,
        patch(
            "scripts.migrate_redis_to_database.line_catalog.set_line_tags",
            return_value=True,
        ) as mock_set_tags,
    ):
        mock_redis_cls.return_value.get_connection.return_value = mock_redis
        migrate_line_tags()

        mock_set_tags.assert_called_once_with("line_bytes", ["tag1", "tag2"])


def test_migrate_line_tags_handles_exception() -> None:
    with patch("scripts.migrate_redis_to_database.Redis") as mock_redis_cls:
        mock_redis_cls.side_effect = RuntimeError("Scan failure")
        migrate_line_tags()


def test_migrate_lucky_wheel_config_success() -> None:
    mock_redis = MagicMock()
    wheel_json = json.dumps(
        {
            "items": [
                {"name": "谢谢参与", "probability": 50.0},
                {"name": "积分 +10", "probability": 50.0},
            ],
            "cost_credits": 10,
            "min_credits_required": 20,
            "gen_privileged_code": False,
        }
    )
    randomness_json = json.dumps(
        {
            "use_weighted_protection": True,
            "protection_threshold": 2.0,
            "protection_factor": 1.2,
        }
    )

    def mock_get(key: str) -> str | None:
        if key == "luckywheel:config":
            return wheel_json
        if key == "luckywheel:randomness_config":
            return randomness_json
        return None

    mock_redis.get.side_effect = mock_get

    with (
        patch("scripts.migrate_redis_to_database.Redis") as mock_redis_cls,
        patch(
            "scripts.migrate_redis_to_database.luckywheel_service.save_wheel_config",
            return_value=True,
        ) as mock_save_wheel,
        patch(
            "scripts.migrate_redis_to_database.luckywheel_service.save_randomness_config",
            return_value=None,
        ) as mock_save_randomness,
    ):
        mock_redis_cls.return_value.get_connection.return_value = mock_redis
        migrate_lucky_wheel_config()

        mock_save_wheel.assert_called_once()
        saved_config = mock_save_wheel.call_args[0][0]
        assert isinstance(saved_config, LuckyWheelConfig)
        assert len(saved_config.items) == 2
        assert saved_config.cost_credits == 10

        mock_save_randomness.assert_called_once_with(
            {
                "use_weighted_protection": True,
                "protection_threshold": 2.0,
                "protection_factor": 1.2,
            }
        )


def test_migrate_lucky_wheel_config_bytes() -> None:
    mock_redis = MagicMock()
    wheel_bytes = json.dumps(
        {
            "items": [{"name": "积分 +10", "probability": 100.0}],
            "cost_credits": 5,
            "min_credits_required": 10,
            "gen_privileged_code": False,
        }
    ).encode("utf-8")
    randomness_bytes = json.dumps({"protection_threshold": 3.0}).encode("utf-8")

    def mock_get(key: str) -> bytes | None:
        if key == "luckywheel:config":
            return wheel_bytes
        if key == "luckywheel:randomness_config":
            return randomness_bytes
        return None

    mock_redis.get.side_effect = mock_get

    with (
        patch("scripts.migrate_redis_to_database.Redis") as mock_redis_cls,
        patch(
            "scripts.migrate_redis_to_database.luckywheel_service.save_wheel_config",
            return_value=True,
        ) as mock_save_wheel,
        patch(
            "scripts.migrate_redis_to_database.luckywheel_service.save_randomness_config",
            return_value=None,
        ) as mock_save_randomness,
    ):
        mock_redis_cls.return_value.get_connection.return_value = mock_redis
        migrate_lucky_wheel_config()

        mock_save_wheel.assert_called_once()
        mock_save_randomness.assert_called_once_with({"protection_threshold": 3.0})


def test_migrate_lucky_wheel_config_empty() -> None:
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    with (
        patch("scripts.migrate_redis_to_database.Redis") as mock_redis_cls,
        patch(
            "scripts.migrate_redis_to_database.luckywheel_service.save_wheel_config"
        ) as mock_save_wheel,
        patch(
            "scripts.migrate_redis_to_database.luckywheel_service.save_randomness_config"
        ) as mock_save_randomness,
    ):
        mock_redis_cls.return_value.get_connection.return_value = mock_redis
        migrate_lucky_wheel_config()

        mock_save_wheel.assert_not_called()
        mock_save_randomness.assert_not_called()


def test_main_calls_all_migrations() -> None:
    with (
        patch(
            "scripts.migrate_redis_to_database.migrate_free_premium_lines"
        ) as mock_free,
        patch("scripts.migrate_redis_to_database.migrate_line_tags") as mock_tags,
        patch(
            "scripts.migrate_redis_to_database.migrate_lucky_wheel_config"
        ) as mock_wheel,
    ):
        main()
        mock_free.assert_called_once()
        mock_tags.assert_called_once()
        mock_wheel.assert_called_once()
