from __future__ import annotations

from datetime import UTC

from app.domains.traffic import rules


def test_parse_nginx_access_log_with_optional_upstream_fields():
    parsed = rules.parse_access_log(
        "127.0.0.1 - - [23/Jun/2025:15:43:03 +0000] "
        '"GET /stream?service=plex&token=abc HTTP/1.1" 200 123 "-" '
        '"agent" "-" "upstream: 127.0.0.1:32400" "ups_resp_time: 0.3"'
    )
    assert parsed == {
        "access_time": "23/Jun/2025:15:43:03 +0000",
        "url": "/stream?service=plex&token=abc",
        "status_code": 200,
        "bytes_sent": 123,
        "upstream": "127.0.0.1:32400",
        "upstream_response_time": "0.3",
    }


def test_parse_legacy_nginx_access_log():
    parsed = rules.parse_access_log(
        "127.0.0.1 - - [23/Jun/2025:15:43:03 +0000] "
        '"GET /stream?service=plex&token=abc HTTP/1.1" 200 123 "-" "agent" "-"'
    )
    assert parsed is not None
    assert parsed["upstream"] is None
    assert parsed["upstream_response_time"] is None


def test_parse_stream_access_log():
    parsed = rules.parse_access_log(
        "127.0.0.1 [23/Jun/2025:15:43:03 +0000] "
        '"GET /stream?service=emby&token=abc HTTP/1.1" 206 123 '
        'rt=1.0 uct=0.1 uht=0.2 urt=0.3 ua="127.0.0.1:8096" us="206"'
    )
    assert parsed is not None
    assert parsed["status_code"] == 206
    assert parsed["bytes_sent"] == 123
    assert parsed["upstream"] == "127.0.0.1:8096"
    assert parsed["upstream_response_time"] == "0.3"


def test_request_identity_accepts_api_key_and_selects_custom_line():
    parsed = rules.select_request_identity(
        "/stream/items?id=42&api_key=secret&line=custom.example", "origin.example"
    )
    assert parsed == {
        "service": "emby",
        "token": "secret",
        "line": "custom.example",
        "request_uri": "/stream/items",
    }


def test_request_identity_uses_token_service_and_backend_fallback():
    parsed = rules.select_request_identity(
        "/stream/a%20b?service=plex&token=tok", "origin.example"
    )
    assert parsed == {
        "service": "plex",
        "token": "tok",
        "line": "origin.example",
        "request_uri": "/stream/a b",
    }
    assert rules.select_request_identity("/stream?token=x", "line") is None
    assert rules.select_request_identity("/stream?service=plex&token=x", None) is None


def test_stream_request_and_timestamp_fallback():
    assert rules.is_stream_request("/stream/foo")
    assert rules.is_stream_request("/library/Original.mkv")
    assert not rules.is_stream_request("/health")
    assert (
        rules.format_access_timestamp("23/Jun/2025:15:43:03 +0000", timezone=UTC)
        == "2025-06-23T15:43:03+00:00"
    )
    assert rules.format_access_timestamp("bad", timezone=UTC) == ""
    assert (
        rules.format_access_timestamp("bad", "2025-06-23T15:43:03+00:00", timezone=UTC)
        == "2025-06-23T15:43:03+00:00"
    )


def test_event_hash_matches_legacy_canonical_payload_and_is_stable():
    event_hash = rules.build_event_hash(
        line="line.example",
        service="plex",
        username="user",
        user_id=42,
        timestamp="2025-06-23T23:43:03+08:00",
        request_uri="/stream/a",
        send_bytes=123,
        upstream=None,
        upstream_response_time=None,
    )
    assert (
        event_hash == "e57582d68d193d294cad765e5ca28b54e635c911df1855d06012935f86dbc381"
    )
    assert event_hash == rules.build_event_hash(
        line="line.example",
        service="plex",
        username="user",
        user_id=42,
        timestamp="2025-06-23T23:43:03+08:00",
        request_uri="/stream/a",
        send_bytes=123,
    )
