"""Unit tests for the Emby integration client."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

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


@pytest.fixture
def creation_requests(monkeypatch):
    policy = {
        "IsAdministrator": False,
        "IsDisabled": False,
        "IsHidden": False,
        "EnableAudioPlaybackTranscoding": False,
        "EnableVideoPlaybackTranscoding": False,
        "EnablePlaybackRemuxing": False,
        "EnableContentDownloading": False,
        "SimultaneousStreamLimit": 3,
        "RemoteClientBitrateLimit": 20000000,
        "EnableAllFolders": False,
        "EnabledFolders": ["allowed-library"],
        "ExcludedSubFolders": ["restricted-subfolder"],
    }

    def response(body=None, status=200):
        result = Mock(status_code=status)
        result.json.return_value = body
        if status >= 400:
            result.raise_for_status.side_effect = RuntimeError(f"HTTP {status}")
        return result

    template = {"Id": "tpl_uid", "Name": "UserTemplate", "Policy": policy}
    created = {"Id": "new_uid", "Name": "testuser", "Policy": deepcopy(policy)}
    read = Mock(
        side_effect=[
            response({"Items": [template]}),
            response(template),
            response(created),
        ]
    )
    write = Mock(side_effect=[response(created), response(status=204)])
    delete = Mock(return_value=response(status=204))
    monkeypatch.setattr("app.integrations.emby.requests.get", read)
    monkeypatch.setattr("app.integrations.emby.requests.post", write)
    monkeypatch.setattr("app.integrations.emby.requests.delete", delete)
    return read, write, delete, response, template, created


def test_emby_add_user_success(emby_client, creation_requests, monkeypatch) -> None:
    read, write, delete, _, template, _ = creation_requests
    monkeypatch.setattr(
        emby_client,
        "get_uid_from_username",
        Mock(side_effect=AssertionError("Do not use cached/filtered lookup")),
    )

    assert emby_client.add_user("testuser", "secretpass", "UserTemplate") == (
        True,
        "new_uid",
    )

    assert write.call_args_list[0].kwargs["json"] == {
        "Name": "testuser",
        "CopyFromUserId": "tpl_uid",
        "UserCopyOptions": ["userpolicy"],
    }
    assert read.call_args_list[0].kwargs["params"] == {
        "NameStartsWithOrGreater": "UserTemplate",
        "Limit": 1,
        "SortOrder": "Ascending",
    }
    assert template["Policy"]["SimultaneousStreamLimit"] == 3
    assert read.call_count == 3
    assert write.call_args_list[1].kwargs["json"] == {
        "Id": "new_uid",
        "NewPw": "secretpass",
        "ResetPassword": False,
    }
    for call in read.call_args_list + write.call_args_list:
        assert call.kwargs["timeout"] == 30
        assert call.kwargs["headers"]["X-Emby-Token"] == "test-token"
        assert "api_key" not in call.kwargs["url"]
    delete.assert_not_called()


@pytest.mark.parametrize("name", ["", " "])
def test_empty_template_never_creates(emby_client, creation_requests, name) -> None:
    read, write, delete, *_ = creation_requests
    assert not emby_client.add_user("testuser", "secretpass", name)[0]
    read.assert_not_called()
    write.assert_not_called()
    delete.assert_not_called()


@pytest.mark.parametrize(
    "items",
    [[], [{"Id": "wrong", "Name": "UserTemplate2"}], [{"Name": "UserTemplate"}]],
)
def test_missing_or_invalid_template_never_creates(
    emby_client, creation_requests, items
) -> None:
    read, write, delete, response, *_ = creation_requests
    read.side_effect = [response({"Items": items})]
    assert not emby_client.add_user("testuser", "secretpass", "UserTemplate")[0]
    write.assert_not_called()
    delete.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [("IsAdministrator", True), ("IsDisabled", True), ("IsAdministrator", None)],
)
def test_unsafe_template_never_creates(
    emby_client, creation_requests, field, value
) -> None:
    _, write, delete, _, template, _ = creation_requests
    template["Policy"][field] = value
    assert not emby_client.add_user("testuser", "secretpass", "UserTemplate")[0]
    write.assert_not_called()
    delete.assert_not_called()


@pytest.mark.parametrize(
    "template_change",
    [{"Id": "another_id"}, {"Name": "another_name"}, {"Policy": {}}, {"Policy": None}],
)
def test_template_detail_must_match(
    emby_client, creation_requests, template_change
) -> None:
    read, write, delete, response, template, _ = creation_requests
    read.side_effect = [
        response({"Items": [template]}),
        response({**template, **template_change}),
    ]
    assert not emby_client.add_user("testuser", "secretpass", "UserTemplate")[0]
    write.assert_not_called()
    delete.assert_not_called()


def test_template_read_failure_never_creates(emby_client, creation_requests) -> None:
    read, write, delete, *_ = creation_requests
    read.side_effect = TimeoutError("template request failed")
    assert not emby_client.add_user("testuser", "secretpass", "UserTemplate")[0]
    write.assert_not_called()
    delete.assert_not_called()


def test_emby_add_user_http_error(emby_client, creation_requests) -> None:
    _, write, delete, response, *_ = creation_requests
    write.side_effect = [response(status=400)]
    success, msg = emby_client.add_user("testuser", "secretpass", "UserTemplate")
    assert not success
    assert "HTTP 400" in msg
    delete.assert_not_called()


def test_emby_add_user_network_exception(emby_client, creation_requests) -> None:
    _, write, delete, *_ = creation_requests
    write.side_effect = ConnectionError("Host unreachable")
    success, msg = emby_client.add_user("testuser", "secretpass", "UserTemplate")
    assert not success
    assert "Host unreachable" in msg
    delete.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("EnableAudioPlaybackTranscoding", True),
        ("EnableVideoPlaybackTranscoding", True),
        ("EnablePlaybackRemuxing", True),
        ("SimultaneousStreamLimit", 0),
        ("EnableAllFolders", True),
        ("EnabledFolders", []),
        ("ExcludedSubFolders", []),
        ("EnableContentDownloading", True),
        ("RemoteClientBitrateLimit", 0),
        ("NewUnexpectedPermission", True),
    ],
)
def test_policy_mismatch_deletes_new_user(
    emby_client, creation_requests, field, value
) -> None:
    read, _, delete, response, template, created = creation_requests
    created["Policy"][field] = value
    read.side_effect = [
        response({"Items": [template]}),
        response(template),
        response(created),
        response(status=404),
    ]
    success, msg = emby_client.add_user("testuser", "secretpass", "UserTemplate")
    assert not success
    assert "权限与模板不一致" in msg
    delete.assert_called_once_with(
        url="http://fake-emby:8096/Users/new_uid",
        headers={"accept": "application/json", "X-Emby-Token": "test-token"},
        timeout=30,
    )
    assert read.call_count == 4


def test_failed_policy_readback_deletes_new_user(
    emby_client, creation_requests
) -> None:
    read, _, delete, response, template, _ = creation_requests
    read.side_effect = [
        response({"Items": [template]}),
        response(template),
        TimeoutError("readback failed"),
        response(status=404),
    ]
    assert not emby_client.add_user("testuser", "secretpass", "UserTemplate")[0]
    delete.assert_called_once()


def test_emby_add_user_password_change_failure(emby_client, creation_requests) -> None:
    read, write, delete, response, template, created = creation_requests
    write.side_effect = [response(created), response(status=500)]
    read.side_effect = [
        response({"Items": [template]}),
        response(template),
        response(status=404),
    ]
    success, msg = emby_client.add_user("testuser", "secretpass", "UserTemplate")
    assert not success
    assert "密码失败" in msg
    delete.assert_called_once()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"Id": "tpl_uid", "Name": "testuser"},
        {"Id": "other_id", "Name": "someone_else"},
    ],
)
def test_invalid_creation_response_never_changes_or_deletes_other_user(
    emby_client, creation_requests, body
) -> None:
    _, write, delete, response, *_ = creation_requests
    write.side_effect = [response(body)]
    assert not emby_client.add_user("testuser", "secretpass", "UserTemplate")[0]
    assert write.call_count == 1
    delete.assert_not_called()


@pytest.mark.parametrize("gone", [False, True])
def test_failed_creation_cleanup_requires_confirmed_absence(
    emby_client, creation_requests, gone
) -> None:
    read, write, delete, response, template, created = creation_requests
    write.side_effect = [response(created), response(status=500)]
    delete.side_effect = TimeoutError("delete timeout")
    read.side_effect = [
        response({"Items": [template]}),
        response(template),
        response(status=404 if gone else 200),
    ]
    success, msg = emby_client.add_user("testuser", "secretpass", "UserTemplate")
    assert not success
    assert ("清理失败" in msg) is not gone


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


@pytest.fixture
def download_requests(monkeypatch):
    from unittest.mock import Mock

    def response(policy: dict, *, user_id: str = "user_123"):
        result = Mock()
        result.json.return_value = {"Id": user_id, "Name": "member", "Policy": policy}
        return result

    read = Mock()
    write = Mock(return_value=Mock(status_code=204))
    monkeypatch.setattr("app.integrations.emby.requests.get", read)
    monkeypatch.setattr("app.integrations.emby.requests.post", write)
    return read, write, response


@pytest.mark.parametrize("allowed", [False, True])
def test_download_permission_already_satisfied_is_read_only(
    emby_client, download_requests, allowed
) -> None:
    read, write, response = download_requests
    read.return_value = response(
        {"EnableContentDownloading": allowed, "EnabledFolders": ["restricted"]}
    )

    assert emby_client.update_download_permission_for_user("user_123", allowed) == (
        True,
        "ok",
    )

    write.assert_not_called()
    read.assert_called_once()
    assert read.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize("allowed", [False, True])
def test_download_write_preserves_policy_and_verifies_fresh_state(
    emby_client, download_requests, allowed
) -> None:
    read, write, response = download_requests
    other = {
        "EnabledFolders": ["restricted"],
        "EnableAllFolders": False,
        "IsAdministrator": False,
        "EnableRemoteAccess": True,
    }
    before = {**other, "EnableContentDownloading": not allowed}
    after = {**other, "EnableContentDownloading": allowed}
    read.side_effect = [response(before), response(after)]

    assert emby_client.update_download_permission_for_user("user_123", allowed) == (
        True,
        "ok",
    )

    assert write.call_args.kwargs["json"] == after
    assert before["EnableContentDownloading"] is not allowed
    assert write.call_args.kwargs["timeout"] == 30
    assert write.call_args.kwargs["headers"]["X-Emby-Token"] == "test-token"
    assert read.call_count == 2


@pytest.mark.parametrize(
    "policy",
    [{}, {"EnableContentDownloading": None}, {"EnableContentDownloading": "false"}],
)
def test_unknown_download_state_does_not_write(
    emby_client, download_requests, policy
) -> None:
    read, write, response = download_requests
    read.return_value = response(policy)

    assert (
        emby_client.update_download_permission_for_user("user_123", False)[0] is False
    )

    write.assert_not_called()


def test_wrong_user_policy_does_not_write(emby_client, download_requests) -> None:
    read, write, response = download_requests
    read.return_value = response(
        {"EnableContentDownloading": False}, user_id="other-user"
    )

    assert emby_client.update_download_permission_for_user("user_123", True)[0] is False

    write.assert_not_called()


def test_successful_http_without_permission_change_is_failure(
    emby_client, download_requests
) -> None:
    read, write, response = download_requests
    read.return_value = response({"EnableContentDownloading": False})

    assert emby_client.update_download_permission_for_user("user_123", True)[0] is False

    write.assert_called_once()
    assert read.call_count == 2


def test_other_policy_change_is_not_reported_as_success(
    emby_client, download_requests
) -> None:
    read, _, response = download_requests
    read.side_effect = [
        response({"EnableContentDownloading": False, "EnableAllFolders": False}),
        response({"EnableContentDownloading": True, "EnableAllFolders": True}),
    ]

    assert emby_client.update_download_permission_for_user("user_123", True)[0] is False


@pytest.mark.parametrize("target_reached", [False, True])
def test_timeout_requires_confirmed_actual_target(
    emby_client, download_requests, target_reached
) -> None:
    read, write, response = download_requests
    write.side_effect = TimeoutError("request timed out")
    read.side_effect = [
        response({"EnableContentDownloading": False}),
        response({"EnableContentDownloading": target_reached}),
    ]

    assert (
        emby_client.update_download_permission_for_user("user_123", True)[0]
        is target_reached
    )


def test_failed_readback_after_write_is_not_success(
    emby_client, download_requests
) -> None:
    read, _, response = download_requests
    read.side_effect = [
        response({"EnableContentDownloading": False}),
        TimeoutError("readback failed"),
    ]

    assert emby_client.update_download_permission_for_user("user_123", True)[0] is False


@pytest.mark.parametrize("hidden", [False, True])
def test_template_visibility_does_not_filter_creation(
    emby_client, creation_requests, hidden
) -> None:
    _, _, _, _, template, created = creation_requests
    template["Policy"]["IsHidden"] = hidden
    created["Policy"]["IsHidden"] = hidden
    assert emby_client.add_user("testuser", "secretpass", "UserTemplate") == (
        True,
        "new_uid",
    )


@pytest.mark.parametrize(
    "change", [{"Id": "another_id"}, {"Name": "another_user"}, {"Policy": {}}]
)
def test_new_user_readback_identity_and_policy_must_be_valid(
    emby_client, creation_requests, change
) -> None:
    read, _, delete, response, template, created = creation_requests
    read.side_effect = [
        response({"Items": [template]}),
        response(template),
        response({**created, **change}),
        response(status=404),
    ]
    assert not emby_client.add_user("testuser", "secretpass", "UserTemplate")[0]
    assert delete.call_args.kwargs["url"].endswith(f"/Users/{created['Id']}")


def test_delete_success_without_confirmed_absence_still_reports_cleanup_failure(
    emby_client, creation_requests
) -> None:
    read, write, _, response, template, created = creation_requests
    write.side_effect = [response(created), response(status=500)]
    read.side_effect = [
        response({"Items": [template]}),
        response(template),
        response(created),
    ]
    success, msg = emby_client.add_user("testuser", "secretpass", "UserTemplate")
    assert not success
    assert "清理失败" in msg
