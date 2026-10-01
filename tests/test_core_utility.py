"""Unit and behavior tests for core utilities and messaging integrations."""

from __future__ import annotations

import asyncio
from pathlib import Path

import filelock
import pytest

from app.core import byte_size
from app.core.cache import RedisCache
from app.core.config import _is_container
from app.core.legacy_env import LegacyEnvSource
from app.core.scheduler import Scheduler
from app.domains.identity import rules as identity_rules
from app.domains.treasure import rules as treasure_rules
from app.integrations.telegram import messaging, profiles

ROOT = Path(__file__).resolve().parents[1]
assert (ROOT / "src/app").is_dir()


def test_byte_and_media_labels_preserve_legacy_behavior() -> None:
    assert [byte_size.format_bytes(value) for value in (0, 1, 1023, 1024)] == [
        "0 B",
        "1 B",
        "1023 B",
        "1.00 KB",
    ]
    assert byte_size.format_bytes(1024**5) == "1024.00 TB"
    assert byte_size.format_bytes(-1) == "-1 B"
    assert identity_rules.get_service_label("plex") == ("PLEX", "🎬")
    assert identity_rules.get_service_label("PLEX") == ("PLEX", "📺")
    assert identity_rules.get_service_label("emby") == ("EMBY", "📺")


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (None, None, None),
        (None, 7, 7),
        (0, None, 0),
        (-1, None, (1 << 63) - 1),
        ((1 << 63) + 3, None, 3),
    ],
)
def test_external_random_b_preserves_low_signed_bigint_mapping(
    value: int | None, default: int | None, expected: int | None
) -> None:
    assert (
        treasure_rules.normalize_external_random_b(value, default=default) == expected
    )


def test_container_detection_keeps_file_before_environment_precedence(monkeypatch):
    class FakePath:
        def __init__(self, value):
            self.value = value

        def exists(self):
            return self.value == "/.dockerenv"

    monkeypatch.setattr("app.core.config.Path", FakePath)
    monkeypatch.setattr(
        "app.core.config.os.getenv",
        lambda key: "podman" if key == "container" else None,
    )
    assert _is_container() is True

    monkeypatch.setattr("app.core.config.os.getenv", lambda key: None)
    assert _is_container() is True

    monkeypatch.setattr("app.core.config.Path", lambda value: FakePath("other"))
    monkeypatch.setattr(
        "app.core.config.os.getenv",
        lambda key: "podman" if key == "container" else None,
    )
    assert _is_container() is True
    monkeypatch.setattr("app.core.config.os.getenv", lambda key: None)
    assert _is_container() is False


def test_scheduler_singleton_identity_is_stable() -> None:
    assert type(Scheduler).__name__ == "_SchedulerSingletonMeta"
    assert Scheduler() is Scheduler()


def test_redis_cache_mechanism_defaults_are_stable() -> None:
    cache = object.__new__(RedisCache)
    cache.capacity = 0
    cache.ttl_seconds = None
    cache._cache_key_prefix = "sample:"
    cache._cache_usage_key = None
    assert cache._get_cache_key("key") == "sample:key"


def test_legacy_env_source_preserves_priority_and_sequential_overrides(tmp_path: Path):
    data = tmp_path / "data.env"
    working = tmp_path / "working.env"
    data.write_text("COUNT=bad\nCOUNT=7\nFLAG=true\n", encoding="utf-8")
    working.write_text("COUNT=3\nFLAG=false\n", encoding="utf-8")
    source = LegacyEnvSource(
        {"COUNT": 0, "FLAG": False},
        data_path=data,
        working_path=working,
        environ={"COUNT": "5", "FLAG": "false"},
    )
    assert source.read("COUNT") == 5
    assert source.read("FLAG") is False
    assert source.present_keys() == {"COUNT", "FLAG"}


def test_telegram_profile_cache_is_local_read_only_and_has_string_batch_fallback(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(profiles.settings, "DATA_DIR", str(tmp_path))
    cache_path = profiles.settings.TG_USER_INFO_CACHE_PATH
    lock = filelock.FileLock(str(cache_path) + ".lock")
    profiles.save_tg_user_info_cache({1: {"first_name": "Alice", "added": 1}}, lock)
    assert profiles.get_user_info_from_tg_id(1) == {
        "first_name": "Alice",
        "added": 1,
    }
    assert profiles.get_user_name_from_tg_id(1) == "Alice"
    assert profiles.get_user_names_from_tg_ids([1, "2"]) == {1: "Alice", 2: "2"}
    assert profiles.get_user_avatar_from_tg_id(2) is None


class _FakeResponse:
    def __init__(self, status, payload=None, *, content_type="application/json"):
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self, **kwargs):
        return self._payload

    async def text(self):
        return str(self._payload)


class _FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.posts = []

    def post(self, url, data):
        self.posts.append((url, data))
        return next(self.responses)


async def _async_value(value):
    return value


async def _async_append(values, value):
    values.append(value)


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (200, {"ok": True}, True),
        (400, {"ok": False, "description": "bad request"}, False),
    ],
)
def test_telegram_url_sender_preserves_validation_and_terminal_status(
    status, payload, expected, monkeypatch
):
    session = _FakeSession([_FakeResponse(status, payload)])
    monkeypatch.setattr(
        messaging, "get_thread_safe_session", lambda: _async_value(session)
    )
    result = asyncio.run(
        messaging.send_message_by_url(
            chat_id="-1002003004", text="  hello  ", token="token", max_retries=1
        )
    )
    assert result is expected
    assert session.posts[0][1]["chat_id"] == -1002003004
    assert session.posts[0][1]["text"] == "hello"


def test_telegram_url_sender_retries_rate_limits_with_server_delay(monkeypatch):
    session = _FakeSession(
        [
            _FakeResponse(429, {"parameters": {"retry_after": 2}}),
            _FakeResponse(200, {"ok": True}),
        ]
    )
    sleeps = []
    monkeypatch.setattr(
        messaging, "get_thread_safe_session", lambda: _async_value(session)
    )
    monkeypatch.setattr(
        messaging.asyncio, "sleep", lambda seconds: _async_append(sleeps, seconds)
    )
    assert (
        asyncio.run(
            messaging.send_message_by_url(
                chat_id="@channel", text="hello", token="token", max_retries=2
            )
        )
        is True
    )
    assert sleeps == [2]
    assert len(session.posts) == 2


def test_telegram_url_sender_rejects_invalid_chat_and_payload(monkeypatch):
    monkeypatch.setattr(
        messaging, "get_thread_safe_session", lambda: _async_value(None)
    )
    with pytest.raises(ValueError, match="chat_id cannot be empty"):
        asyncio.run(messaging.send_message_by_url(None, "hello", token="token"))
    with pytest.raises(ValueError, match="text cannot be empty"):
        asyncio.run(messaging.send_message_by_url(1, " ", token="token"))
    with pytest.raises(ValueError, match="token cannot be empty"):
        asyncio.run(messaging.send_message_by_url(1, "hello", token=""))


def test_missing_telegram_profile_cache_is_an_empty_local_read(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(profiles.settings, "DATA_DIR", str(tmp_path))
    assert profiles.load_tg_user_info_cache() == {}
    assert profiles.get_user_names_from_tg_ids([]) == {}
