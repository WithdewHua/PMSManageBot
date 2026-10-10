"""Exercise real SDK authentication and XML parsing without changing live shares."""

from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree.ElementTree import Element, SubElement, tostring

import pytest
import requests
from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer

from app.integrations.plex import Plex

SHARE_URL = "https://clients.plex.tv/api/v2/shared_servers/44"
LIBRARY_IDS = [301, 302]
OTHER_SETTINGS = {"allowTuners": "1", "filterMovies": "contentRating=G|PG"}


def _response(text: str, status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = text.encode()
    response.headers["Content-Type"] = "application/xml"
    response.url = SHARE_URL
    return response


def _share_response(
    allowed: bool = False,
    *,
    all_libraries: bool = False,
    library_ids: list[int] | None = None,
    setting_overrides: dict[str, str | None] | None = None,
    identity_overrides: dict[str, str] | None = None,
) -> requests.Response:
    root = Element(
        "sharedServer",
        {
            "id": "44",
            "invitedId": "123",
            "machineIdentifier": "current-machine",
            "allLibraries": str(int(all_libraries)),
            **(identity_overrides or {}),
        },
    )
    attributes = {**OTHER_SETTINGS, "allowSync": str(int(allowed))}
    for name, value in (setting_overrides or {}).items():
        if value is None:
            attributes.pop(name, None)
        else:
            attributes[name] = value
    SubElement(root, "sharingSettings", attributes)
    libraries = SubElement(root, "libraries")
    for library_id in LIBRARY_IDS if library_ids is None else library_ids:
        SubElement(libraries, "library", {"id": str(library_id)})
    return _response(tostring(root, encoding="unicode"))


@pytest.fixture
def plex_client():
    http = Mock(spec=requests.Session)
    for method in (http.get, http.post, http.put, http.delete):
        method.__name__ = "mock_request"
    http.get.return_value = _share_response()
    http.post.return_value = _share_response(False)
    http.post.return_value.status_code = 201

    account = object.__new__(MyPlexAccount)
    account._token = "test-token"
    account._timeout = 5
    account._session = http
    account.updateFriend = Mock(side_effect=AssertionError("must not call broken API"))
    account.users = Mock(
        return_value=[
            SimpleNamespace(
                id=123,
                email="user@example.com",
                username="test-user",
                # Deliberately stale: sharedServer GET, not this object, is authoritative.
                allowSync=True,
                servers=[
                    SimpleNamespace(id=55, machineIdentifier="other-machine"),
                    SimpleNamespace(id=44, machineIdentifier="current-machine"),
                ],
            )
        ]
    )
    client = object.__new__(Plex)
    client.my_plex_account = account
    client.plex_server = object.__new__(PlexServer)
    client.plex_server.machineIdentifier = "current-machine"
    client.users = [
        SimpleNamespace(id=999, email="user@example.com", username="stale-cached-user")
    ]
    return client, http


@pytest.mark.parametrize("allow_sync", [False, True])
def test_sync_uses_v2_and_preserves_scope_and_restrictions(
    plex_client, caplog, allow_sync
) -> None:
    client, http = plex_client
    http.get.side_effect = [
        _share_response(not allow_sync),
        _share_response(allow_sync),
    ]

    assert client.update_sync_for_user(" USER@Example.com ", allow_sync=allow_sync)

    client.my_plex_account.users.assert_called_once_with()
    http.post.assert_called_once()
    args, kwargs = http.post.call_args
    assert args == (SHARE_URL,)
    assert kwargs["json"] == {
        "machineIdentifier": "current-machine",
        "invitedId": 123,
        "librarySectionIds": LIBRARY_IDS,
        "settings": {**OTHER_SETTINGS, "allowSync": int(allow_sync)},
    }
    assert kwargs["headers"]["X-Plex-Token"] == "test-token"
    assert "params" not in kwargs
    assert "data" not in kwargs
    assert http.get.call_count == 2
    assert all(call.args == (SHARE_URL,) for call in http.get.call_args_list)
    assert client.users == []
    client.my_plex_account.updateFriend.assert_not_called()
    http.put.assert_not_called()
    http.delete.assert_not_called()
    assert "Section name" not in caplog.text


@pytest.mark.parametrize("allow_sync", [False, True])
def test_sync_already_satisfied_is_a_fresh_read_only_noop(
    plex_client, allow_sync
) -> None:
    client, http = plex_client
    http.get.return_value = _share_response(allow_sync)

    assert client.update_sync_for_user("user@example.com", allow_sync=allow_sync)

    http.get.assert_called_once()
    http.post.assert_not_called()
    client.my_plex_account.users.assert_called_once_with()


def test_sync_preserves_all_library_policy(plex_client) -> None:
    client, http = plex_client
    http.get.side_effect = [
        _share_response(False, all_libraries=True),
        _share_response(True, all_libraries=True),
    ]

    assert client.update_sync_for_user("user@example.com", allow_sync=True)

    payload = http.post.call_args.kwargs["json"]
    # A list fixes the scope to today's libraries; omission retains allLibraries=1.
    assert "librarySectionIds" not in payload
    assert payload["settings"] == {**OTHER_SETTINGS, "allowSync": 1}


@pytest.mark.parametrize("status_code", [401, 403, 404, 500])
def test_sync_logs_actual_error_when_state_did_not_change(
    plex_client, caplog, status_code
) -> None:
    client, http = plex_client
    http.post.return_value = _response("permission request rejected", status_code)

    assert client.update_sync_for_user("user@example.com", allow_sync=True) is False

    assert str(status_code) in caplog.text
    assert "permission request rejected" in caplog.text
    assert any(record.exc_info for record in caplog.records)
    assert http.get.call_count == 2
    http.post.assert_called_once()


@pytest.mark.parametrize("error_kind", ["404", "timeout"])
def test_sync_accepts_ambiguous_request_only_after_fresh_confirmation(
    plex_client, caplog, error_kind
) -> None:
    client, http = plex_client
    http.get.side_effect = [_share_response(False), _share_response(True)]
    if error_kind == "404":
        http.post.return_value = _response("not found", 404)
    else:
        http.post.side_effect = requests.Timeout("write response timed out")

    assert client.update_sync_for_user("user@example.com", allow_sync=True)

    assert "新请求已确认" in caplog.text
    assert not any(record.levelname == "ERROR" for record in caplog.records)
    assert http.get.call_count == 2


def test_sync_does_not_trust_a_successful_post_response(plex_client, caplog) -> None:
    client, http = plex_client
    # Even a POST XML saying allowSync=1 is insufficient; GET still says 0.
    http.post.return_value = _share_response(True)

    assert client.update_sync_for_user("user@example.com", allow_sync=True) is False

    assert "回读未达到目标" in caplog.text
    assert http.get.call_count == 2


def test_sync_handles_user_lookup_failure(plex_client, caplog) -> None:
    client, http = plex_client
    client.my_plex_account.users.side_effect = requests.Timeout("user lookup timed out")

    assert client.update_sync_for_user("user@example.com", allow_sync=False) is False

    assert "user lookup timed out" in caplog.text
    assert any(record.exc_info for record in caplog.records)
    http.post.assert_not_called()
    http.get.assert_not_called()


def test_sync_missing_user_does_not_write(plex_client) -> None:
    client, http = plex_client

    assert client.update_sync_for_user("missing@example.com", allow_sync=False) is False

    http.get.assert_not_called()
    http.post.assert_not_called()


@pytest.mark.parametrize(
    "servers", [[], [SimpleNamespace(id=44, machineIdentifier="elsewhere")]]
)
def test_sync_never_creates_a_new_share(plex_client, servers) -> None:
    client, http = plex_client
    client.my_plex_account.users.return_value[0].servers = servers

    assert client.update_sync_for_user("user@example.com", allow_sync=True) is False

    http.get.assert_not_called()
    http.post.assert_not_called()


@pytest.mark.parametrize(
    "identity_overrides",
    [{"id": "55"}, {"invitedId": "999"}, {"machineIdentifier": "elsewhere"}],
)
def test_sync_rejects_wrong_share_identity(plex_client, identity_overrides) -> None:
    client, http = plex_client
    http.get.return_value = _share_response(identity_overrides=identity_overrides)

    assert client.update_sync_for_user("user@example.com", allow_sync=True) is False

    http.post.assert_not_called()


@pytest.mark.parametrize("value", [None, "", "unknown"])
def test_sync_unknown_permission_is_not_treated_as_disabled(plex_client, value) -> None:
    client, http = plex_client
    http.get.return_value = _share_response(setting_overrides={"allowSync": value})

    assert client.update_sync_for_user("user@example.com", allow_sync=False) is False

    http.post.assert_not_called()


@pytest.mark.parametrize(
    "response",
    [
        _response("<unexpected />"),
        _share_response(identity_overrides={"allLibraries": ""}),
        _share_response(library_ids=[]),
        _share_response(library_ids=[0]),
    ],
)
def test_sync_rejects_incomplete_or_unsafe_initial_scope(plex_client, response) -> None:
    client, http = plex_client
    http.get.return_value = response

    assert client.update_sync_for_user("user@example.com", allow_sync=True) is False

    http.post.assert_not_called()


@pytest.mark.parametrize(
    "response",
    [
        _share_response(True, all_libraries=True),
        _share_response(True, library_ids=[*LIBRARY_IDS, 303]),
        _share_response(True, setting_overrides={"allowTuners": "0"}),
    ],
)
def test_sync_rejects_collateral_scope_or_restriction_changes(
    plex_client, caplog, response
) -> None:
    client, http = plex_client
    http.get.side_effect = [_share_response(False), response]

    assert client.update_sync_for_user("user@example.com", allow_sync=True) is False

    assert "媒体库范围或其他限制发生变化" in caplog.text


@pytest.mark.parametrize("post_failed", [False, True])
def test_sync_failed_readback_never_confirms_success(
    plex_client, caplog, post_failed
) -> None:
    client, http = plex_client
    http.get.side_effect = [
        _share_response(False),
        requests.Timeout("readback timed out"),
    ]
    if post_failed:
        http.post.return_value = _response("write request rejected", 404)

    assert client.update_sync_for_user("user@example.com", allow_sync=True) is False

    assert "readback timed out" in caplog.text
    if post_failed:
        assert "write request rejected" in caplog.text


def test_sync_unknown_readback_permission_is_not_success(plex_client) -> None:
    client, http = plex_client
    http.get.side_effect = [
        _share_response(True),
        _share_response(setting_overrides={"allowSync": None}),
    ]

    assert client.update_sync_for_user("user@example.com", allow_sync=False) is False


def test_sync_uses_configured_cloud_url(plex_client, monkeypatch) -> None:
    from app.core.config import settings

    client, http = plex_client
    monkeypatch.setattr(settings, "PLEX_TV_BASE_URL", "https://cloud.example.test/")
    http.get.side_effect = [_share_response(False), _share_response(True)]

    assert client.update_sync_for_user("user@example.com", allow_sync=True)

    assert http.post.call_args.args == (
        "https://cloud.example.test/api/v2/shared_servers/44",
    )
