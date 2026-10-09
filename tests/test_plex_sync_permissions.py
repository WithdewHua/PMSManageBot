"""Plex permission changes must never rewrite shared libraries or hide failures."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from plexapi.myplex import MyPlexAccount

from app.integrations.plex import Plex


@pytest.fixture
def plex_client():
    """Use the real SDK request/exception handling without making HTTP calls."""
    http = Mock(spec=requests.Session)
    # PlexAPI logs the HTTP callable's name before issuing its request.
    http.put.__name__ = "put"
    http.put.return_value = SimpleNamespace(
        status_code=204,
        text="",
        headers={},
        url="https://plex.tv/api/friends/123?allowSync=0",
    )
    account = object.__new__(MyPlexAccount)
    account._token = "test-token"
    account._timeout = 5
    account._session = http
    account.updateFriend = Mock(side_effect=AssertionError("must not modify shares"))

    client = object.__new__(Plex)
    client.my_plex_account = account
    client.users = [
        SimpleNamespace(id=123, email="user@example.com", username="test-user")
    ]
    return client, http


@pytest.mark.parametrize("allow_sync", [False, True])
def test_sync_updates_only_the_permission(plex_client, caplog, allow_sync) -> None:
    client, http = plex_client

    assert client.update_sync_for_user("USER@Example.com", allow_sync=allow_sync)

    http.put.assert_called_once()
    args, kwargs = http.put.call_args
    assert args == (client.my_plex_account.FRIENDUPDATE.format(userId=123),)
    assert kwargs["params"] == {"allowSync": int(allow_sync)}
    assert "json" not in kwargs
    client.my_plex_account.updateFriend.assert_not_called()
    http.get.assert_not_called()
    http.post.assert_not_called()
    http.delete.assert_not_called()
    assert "Section name" not in caplog.text


@pytest.mark.parametrize("status_code", [401, 403, 500])
def test_sync_logs_the_actual_plex_error(plex_client, caplog, status_code) -> None:
    client, http = plex_client
    http.put.return_value.status_code = status_code
    http.put.return_value.text = "permission request rejected"

    assert client.update_sync_for_user("user@example.com", allow_sync=False) is False

    assert str(status_code) in caplog.text
    assert "permission request rejected" in caplog.text
    assert any(record.exc_info for record in caplog.records)
    http.put.assert_called_once()


def test_sync_handles_user_lookup_failure(plex_client, monkeypatch, caplog) -> None:
    client, http = plex_client
    monkeypatch.setattr(
        client, "get_users", Mock(side_effect=requests.Timeout("user lookup timed out"))
    )

    assert client.update_sync_for_user("user@example.com", allow_sync=False) is False

    assert "user lookup timed out" in caplog.text
    assert any(record.exc_info for record in caplog.records)
    http.put.assert_not_called()


def test_sync_missing_user_does_not_send_a_request(plex_client) -> None:
    client, http = plex_client

    assert client.update_sync_for_user("missing@example.com", allow_sync=False) is False

    http.put.assert_not_called()
    client.my_plex_account.updateFriend.assert_not_called()
