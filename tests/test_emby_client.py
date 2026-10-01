"""Unit tests for the Emby integration client."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import filelock
import pytest

from app.integrations.emby import Emby


@pytest.fixture
def emby_client(tmp_path: Path, monkeypatch) -> Emby:
    cache_file = tmp_path / "emby_user_info.cache"
    lock_file = filelock.FileLock(str(cache_file) + ".lock")
    monkeypatch.setattr(Emby, "cache", cache_file)
    monkeypatch.setattr(Emby, "cache_lock", lock_file)
    return Emby(base_url="http://fake-emby:8096", api_token="test-token")


def test_emby_client_initialization_and_sentinel(emby_client: Emby) -> None:
    assert emby_client.base_url == "http://fake-emby:8096"
    assert emby_client.api_token == "test-token"
    assert Emby.FETCH_TIMEOUT is not None


def test_emby_add_user_success(emby_client: Emby, monkeypatch) -> None:
    monkeypatch.setattr(emby_client, "get_uid_from_username", lambda name: "tpl_uid")
    monkeypatch.setattr(
        emby_client, "change_user_password", lambda uid, new_password: True
    )

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"Id": "created_emby_id"}

    with patch("requests.post", return_value=fake_resp) as mock_post:
        success, emby_id = emby_client.add_user(
            "testuser", "secretpass", "template_user"
        )
        assert success is True
        assert emby_id == "created_emby_id"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        data = json.loads(call_kwargs["data"])
        assert data["Name"] == "testuser"
        assert data["CopyFromUserId"] == "tpl_uid"


def test_emby_add_user_http_error(emby_client: Emby, monkeypatch) -> None:
    monkeypatch.setattr(emby_client, "get_uid_from_username", lambda name: "tpl_uid")

    fake_resp = MagicMock()
    fake_resp.status_code = 400
    fake_resp.text = "Username already exists"

    with patch("requests.post", return_value=fake_resp):
        success, msg = emby_client.add_user("testuser", "secretpass")
        assert success is False
        assert msg == "Username already exists"


def test_emby_add_user_password_change_failure(emby_client: Emby, monkeypatch) -> None:
    monkeypatch.setattr(emby_client, "get_uid_from_username", lambda name: "tpl_uid")
    monkeypatch.setattr(
        emby_client, "change_user_password", lambda uid, new_password: False
    )

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"Id": "new_uid"}

    with patch("requests.post", return_value=fake_resp):
        success, msg = emby_client.add_user("testuser", "secretpass")
        assert success is False
        assert msg == "Failed to change user password"


def test_emby_add_user_network_exception(emby_client: Emby, monkeypatch) -> None:
    monkeypatch.setattr(emby_client, "get_uid_from_username", lambda name: "tpl_uid")

    with patch("requests.post", side_effect=ConnectionError("Host unreachable")):
        success, msg = emby_client.add_user("testuser", "secretpass")
        assert success is False
        assert "Host unreachable" in msg


def test_emby_change_user_password_success(emby_client: Emby) -> None:
    fake_resp = MagicMock()
    fake_resp.status_code = 204

    with patch("requests.post", return_value=fake_resp):
        assert emby_client.change_user_password("user_123", "new_pwd") is True


def test_emby_change_user_password_failure(emby_client: Emby) -> None:
    fake_resp = MagicMock()
    fake_resp.status_code = 500
    fake_resp.text = "Internal error"

    with patch("requests.post", return_value=fake_resp):
        assert emby_client.change_user_password("user_123", "new_pwd") is False


def test_emby_get_uid_from_username(emby_client: Emby, monkeypatch) -> None:
    monkeypatch.setattr(
        emby_client, "get_user_info_from_username", lambda name: {"id": "uid_456"}
    )
    assert emby_client.get_uid_from_username("alice") == "uid_456"

    monkeypatch.setattr(emby_client, "get_user_info_from_username", lambda name: {})
    assert emby_client.get_uid_from_username("bob") is None


def test_emby_get_user_info_from_username_found(emby_client: Emby) -> None:
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "Items": [
            {
                "Id": "emby_uid_99",
                "Name": "Charlie",
                "PrimaryImageTag": "tag_abc",
                "DateCreated": "2025-01-01T00:00:00.0000000Z",
            }
        ]
    }

    with patch("requests.get", return_value=fake_resp):
        info = emby_client.get_user_info_from_username("Charlie")
        assert info["id"] == "emby_uid_99"
        assert info["name"] == "Charlie"
        assert "tag_abc" in info["avatar"]

        # Second call hits cache (no requests.get call)
        with patch("requests.get", side_effect=AssertionError("Should hit cache")):
            cached = emby_client.get_user_info_from_username("Charlie")
            assert cached["id"] == "emby_uid_99"


def test_emby_get_user_info_from_username_not_found(emby_client: Emby) -> None:
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"Items": []}

    with patch("requests.get", return_value=fake_resp):
        info = emby_client.get_user_info_from_username("NonExistent")
        assert info == {}
