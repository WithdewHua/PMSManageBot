from app.domains.lines import service as lines_service
from app.domains.lines.cache import plex_user_defined_line_cache
from app.domains.lines.rules import is_binded_premium_line, normalize_line_domain


def test_line_domain_normalization_and_premium_catalog_matching() -> None:
    assert normalize_line_domain("https://example.com:8096/path") == "example.com:8096"
    assert normalize_line_domain("example.com/path") == "example.com"
    assert is_binded_premium_line(
        "https://premium.example.com/path", ["premium.example.com"]
    )
    assert not is_binded_premium_line(None, ["premium.example.com"])
    assert not is_binded_premium_line("normal.example.com", ["premium.example.com"])


def test_gateway_line_cache_preserves_key_and_value(
    fake_gateway_redis, monkeypatch
) -> None:
    monkeypatch.setattr(
        plex_user_defined_line_cache, "redis_client", fake_gateway_redis
    )
    lines_service.put_cached_line("plex", "User@Example.com", "line-a")
    assert fake_gateway_redis.get("plex_user_defined_line:user@example.com") == "line-a"
    assert lines_service.get_cached_line("plex", "USER@example.com") == "line-a"
    lines_service.delete_cached_line("plex", "user@example.com")
    assert fake_gateway_redis.get("plex_user_defined_line:user@example.com") is None
