"""Pure parsing and identity rules for traffic ingestion."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, tzinfo
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


def normalize_line_domain(line_domain: str) -> str:
    """Normalize a line URL to the host(:port) persisted in traffic tables."""
    domain = line_domain.strip()
    if "://" not in domain:
        domain = "dummy://" + domain
    parsed = urlparse(domain)
    return parsed.netloc or domain.split("/")[0].replace("dummy://", "")


_NGINX_ACCESS_PATTERN = re.compile(
    r'(\S+) - \S+? \[([^\]]+)\] "(\S+) ([^"]+) ([^"]+)" '
    r'(\d+) (\d+) "([^"]*)"'
    r'(?: "[^"]*" "[^"]*" "upstream: ([^"]*)" '
    r'"ups_resp_time: ([^"]*)")?'
)
_STREAM_ACCESS_PATTERN = re.compile(
    r'(\S+) \[([^\]]+)\] "(\S+) ([^"]+) ([^"]+)" (\d+) (\d+) '
    r"rt=(\S+) uct=(\S+) uht=(\S+) urt=(\S+) "
    r'ua="([^"]*)" us="([^"]*)"'
)


def parse_access_log(message: str) -> dict[str, Any] | None:
    """Parse either the nginx HTTP or stream access-log format.

    The returned mapping intentionally uses the names consumed by the old
    collector so callers can migrate without changing persisted values.
    """
    match = _NGINX_ACCESS_PATTERN.match(message)
    if match:
        return {
            "access_time": match.group(2),
            "url": match.group(4),
            "status_code": int(match.group(6)),
            "bytes_sent": int(match.group(7)),
            "upstream": match.group(9),
            "upstream_response_time": match.group(10),
        }

    match = _STREAM_ACCESS_PATTERN.match(message)
    if not match:
        return None
    return {
        "access_time": match.group(2),
        "url": match.group(4),
        "status_code": int(match.group(6)),
        "bytes_sent": int(match.group(7)),
        "upstream": match.group(12),
        "upstream_response_time": match.group(11),
    }


# Descriptive aliases make the pure boundary convenient to use from tests and
# integrations without exposing the collector's historical local name.
parse_nginx_access_log = parse_access_log
parse_stream_access_log = parse_access_log


def is_stream_request(url: str) -> bool:
    """Return whether a request is a media-stream request."""
    return url.startswith("/stream") or bool(
        re.search(r"[Oo]riginal\.|[Ss]tream\.?", url)
    )


def select_request_identity(url: str, backend: str | None) -> dict[str, str] | None:
    """Extract service, token and line from a request URL.

    ``api_key`` is the legacy Emby reverse-proxy spelling and is deliberately
    treated exactly like ``token``.  ``line`` wins over the log envelope's
    backend, including for custom lines.
    """
    parsed_url = urlparse(url)
    query = parse_qs(parsed_url.query)
    service_values = query.get("service")
    token_values = query.get("token")
    if not service_values or not token_values:
        api_key = query.get("api_key")
        if not api_key:
            return None
        service_values = ["emby"]
        token_values = api_key

    line_values = query.get("line")
    line = line_values[0] if line_values else backend
    if not line:
        return None
    return {
        "service": service_values[0],
        "token": token_values[0],
        "line": line,
        "request_uri": unquote(parsed_url.path),
    }


# Names used by callers that prefer to describe this operation as token
# resolution rather than URL parsing.
resolve_request = select_request_identity
select_service_token_line = select_request_identity


def format_access_timestamp(
    access_time: str,
    fallback_timestamp: str | None = None,
    *,
    timezone: tzinfo,
) -> str:
    """Convert nginx's timestamp, falling back to the envelope timestamp."""
    try:
        parsed = datetime.strptime(access_time, "%d/%b/%Y:%H:%M:%S %z")
        return parsed.astimezone(timezone).isoformat()
    except ValueError:
        if not fallback_timestamp:
            return ""
        return (
            datetime.fromisoformat(fallback_timestamp).astimezone(timezone).isoformat()
        )


def build_event_hash(
    *,
    line: str,
    service: str,
    username: str,
    user_id: str | int | None,
    timestamp: str,
    request_uri: str,
    send_bytes: int,
    upstream: str | None = None,
    upstream_response_time: str | None = None,
) -> str:
    """Build the canonical, stable event id used for ingestion de-duplication."""
    raw = json.dumps(
        {
            "line": line,
            "service": service,
            "username": username,
            "user_id": user_id or "",
            "timestamp": timestamp,
            "request_uri": request_uri,
            "send_bytes": int(send_bytes),
            "upstream": upstream or "",
            "upstream_response_time": upstream_response_time or "",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_build_line_traffic_event_hash = build_event_hash


__all__ = [
    "_build_line_traffic_event_hash",
    "build_event_hash",
    "format_access_timestamp",
    "is_stream_request",
    "normalize_line_domain",
    "parse_access_log",
    "parse_nginx_access_log",
    "parse_stream_access_log",
    "resolve_request",
    "select_request_identity",
    "select_service_token_line",
]
