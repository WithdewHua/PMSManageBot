"""HTTP-level regressions for the public/admin wheel data boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.domains.luckywheel import router as wheel_router
from app.domains.luckywheel import service as wheel_service
from app.integrations.telegram import init_data
from app.transport.http.middleware import TelegramAuthMiddleware

NOW = 1_800_000_000
TOKEN = "wheel-api-isolated-test-token"
ADMIN = 123456789
USER = 987654321
PRIVATE_KEYS = {
    "probability",
    "gen_privileged_code",
    "global_weekly_limit",
    "personal_weekly_limit",
    "global_used",
    "personal_used",
    "global_blocked",
    "personal_blocked",
    "candidate_name",
    "randomness_config",
    "invite_quotas",
}


def _headers(tg_id: int) -> dict[str, str]:
    payload = {
        "auth_date": str(NOW),
        "user": json.dumps({"id": tg_id, "first_name": "Test"}),
    }
    check_string = "\n".join(f"{key}={payload[key]}" for key in sorted(payload))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(
        secret, check_string.encode(), hashlib.sha256
    ).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(payload)}


def _assert_public(value: object) -> None:
    if isinstance(value, dict):
        assert not PRIVATE_KEYS.intersection(value)
        for item in value.values():
            _assert_public(item)
    elif isinstance(value, list):
        for item in value:
            _assert_public(item)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(settings, "TG_API_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "WEBAPP_INIT_DATA_MAX_AGE", 86400)
    monkeypatch.setattr(settings, "WEBAPP_DEV_MOCK_AUTH", False)
    monkeypatch.setattr(init_data, "current_time", lambda: NOW)

    config = {
        "items": [
            {"name": "积分 +10", "probability": 99.92},
            {"name": "邀请码 1 枚", "probability": 0.08},
        ],
        "cost_credits": 10,
        "min_credits_required": 30,
        "gen_privileged_code": True,
        "invite_quotas": {"global_weekly_limit": 30, "personal_weekly_limit": 5},
        "randomness_config": {"protection_factor": 1.2},
    }
    state = {
        "quota": {"global_weekly_limit": 30, "personal_weekly_limit": 5},
        "calls": [],
    }
    monkeypatch.setattr(wheel_service, "get_wheel_config", lambda: config)

    def get_quotas():
        state["calls"].append("get_quotas")
        return dict(state["quota"])

    def update_quotas(changes):
        state["calls"].append("update_quotas")
        state["quota"].update(changes)
        return dict(state["quota"])

    def get_stats(*, week_start_ms=None):
        state["calls"].append("get_stats")
        return {
            "initialized": True,
            "week_start_ms": week_start_ms or 1_799_596_800_000,
            "week_end_ms": (week_start_ms or 1_799_596_800_000) + 604_800_000,
            "global_used": 24,
            "global_limit": 30,
            "personal_limit": 5,
            "historical_issued": 20,
            "new_issued": 4,
            "global_blocked_count": 0,
            "personal_blocked_count": 2,
            "both_blocked_count": 0,
            "first_exhausted_at_ms": None,
            "users": [{"tg_id": USER, "issued": 4}],
            "sources": [
                {"source": None, "issued": 20},
                {"source": "paid", "issued": 4},
            ],
        }

    # Service methods are mocked at the transport boundary, not database guards.
    monkeypatch.setattr(
        wheel_service, "get_invite_quota_config", get_quotas, raising=False
    )
    monkeypatch.setattr(
        wheel_service, "update_invite_quota_config", update_quotas, raising=False
    )
    monkeypatch.setattr(
        wheel_service, "get_invite_quota_stats", get_stats, raising=False
    )

    def result():
        return SimpleNamespace(
            item=SimpleNamespace(name="积分 +10", probability=99.92),
            credits_change=10.0,
            current_credits=100.0,
            used_free_spin=True,
            free_spin_source="gift_pack",
            candidate_name="邀请码 1 枚",
            global_blocked=True,
            personal_blocked=False,
            global_used=30,
        )

    async def spin(tg_id, **kwargs):
        state["calls"].append("spin")
        return result()

    async def spin_ten(tg_id, **kwargs):
        state["calls"].append("spin_ten")
        return SimpleNamespace(
            results=[result() for _ in range(10)],
            total_credits_change=100.0,
            current_credits=100.0,
            global_used=30,
        )

    def unavailable_profile(_tg_id):
        raise RuntimeError("No Telegram network calls allowed in result logging")

    monkeypatch.setattr(wheel_service, "spin", spin)
    monkeypatch.setattr(wheel_service, "spin_ten_times", spin_ten)
    monkeypatch.setattr(wheel_router, "get_user_name_from_tg_id", unavailable_profile)
    app = FastAPI()
    app.add_middleware(TelegramAuthMiddleware)
    app.include_router(wheel_router.router, prefix="/api")
    with TestClient(app) as client:
        yield client, state


@pytest.mark.parametrize("tg_id", [None, USER, ADMIN])
def test_public_config_is_allowlisted_for_every_caller(api, tg_id):
    client, _ = api
    response = client.get(
        "/api/luckywheel/config?admin=true&include_probability=true",
        headers=_headers(tg_id) if tg_id else {},
    )
    assert response.status_code == 200
    assert response.json() == {
        "items": [{"name": "积分 +10"}, {"name": "邀请码 1 枚"}],
        "cost_credits": 10,
        "min_credits_required": 30,
    }
    _assert_public(response.json())


@pytest.mark.parametrize("path", ["spin", "spin-ten"])
def test_spin_serialization_strips_all_private_metadata(api, path):
    client, _ = api
    response = client.post(f"/api/luckywheel/{path}", headers=_headers(USER), json={})
    assert response.status_code == 200
    body = response.json()
    _assert_public(body)
    results = body["results"] if path == "spin-ten" else [body]
    assert len(results) == (10 if path == "spin-ten" else 1)
    for item in results:
        assert item["item"] == {"name": "积分 +10"}
        assert item["credits_change"] == 10.0
        assert item["current_credits"] == 100.0
        assert item["used_free_spin"] is True
        assert item["free_spin_source"] == "gift_pack"


@pytest.mark.parametrize(
    "path",
    [
        "admin/config",
        "admin/invite-quotas",
        "admin/invite-quota-stats",
        "randomness-config",
        "randomness-stats",
        "stats",
    ],
)
@pytest.mark.parametrize("tg_id,expected", [(None, 401), (USER, 403)])
def test_management_reads_require_authenticated_admin(api, path, tg_id, expected):
    client, state = api
    response = client.get(
        f"/api/luckywheel/{path}", headers=_headers(tg_id) if tg_id else {}
    )
    assert response.status_code == expected
    _assert_public(response.json())
    assert not state["calls"]


@pytest.mark.parametrize("tg_id,expected", [(None, 401), (USER, 403)])
def test_quota_write_rejects_non_admin_before_service(api, tg_id, expected):
    client, state = api
    response = client.put(
        "/api/luckywheel/admin/invite-quotas",
        headers=_headers(tg_id) if tg_id else {},
        json={"global_weekly_limit": 1, "personal_weekly_limit": 1},
    )
    assert response.status_code == expected
    assert not state["calls"]


def test_admin_keeps_full_config_and_reads_accounting(api):
    client, _ = api
    config = client.get("/api/luckywheel/admin/config", headers=_headers(ADMIN))
    assert config.status_code == 200
    assert config.json()["items"][1]["probability"] == 0.08
    assert config.json()["gen_privileged_code"] is True
    stats = client.get(
        "/api/luckywheel/admin/invite-quota-stats", headers=_headers(ADMIN)
    )
    assert stats.status_code == 200
    assert stats.json()["global_used"] == 24
    assert stats.json()["first_exhausted_at_ms"] is None
    assert stats.json()["sources"][0]["source"] is None


def test_admin_can_set_zero_and_read_it_back(api):
    client, state = api
    response = client.put(
        "/api/luckywheel/admin/invite-quotas",
        headers=_headers(ADMIN),
        json={"global_weekly_limit": 0, "personal_weekly_limit": 5},
    )
    assert response.status_code == 200
    assert response.json()["global_weekly_limit"] == 0
    again = client.get("/api/luckywheel/admin/invite-quotas", headers=_headers(ADMIN))
    assert again.json() == state["quota"]


@pytest.mark.parametrize("value", [-1, 1.5, True, "30", None, 2**31])
def test_quota_inputs_are_strict_nonnegative_integers(api, value):
    client, state = api
    response = client.put(
        "/api/luckywheel/admin/invite-quotas",
        headers=_headers(ADMIN),
        json={"global_weekly_limit": value, "personal_weekly_limit": 5},
    )
    assert response.status_code == 422
    assert not state["calls"]


def test_internal_failure_does_not_leak_config(api, monkeypatch):
    client, _ = api

    def fail():
        raise RuntimeError("global_weekly_limit=30 probability=0.08 SECRET")

    monkeypatch.setattr(wheel_service, "get_wheel_config", fail)
    response = client.get("/api/luckywheel/config")
    assert response.status_code == 500
    assert response.json() == {"detail": "获取配置失败"}
    assert "SECRET" not in response.text


def test_invalid_statistics_period_does_not_call_service(api):
    client, state = api
    response = client.get(
        "/api/luckywheel/admin/invite-quota-stats?week_start_ms=-1",
        headers=_headers(ADMIN),
    )
    assert response.status_code == 422
    assert not state["calls"]


def test_admin_save_keeps_complete_weights_and_existing_route(api, monkeypatch):
    client, _ = api
    saved = []
    monkeypatch.setattr(
        wheel_service, "update_wheel_config", lambda request: saved.append(request)
    )
    response = client.put(
        "/api/luckywheel/config",
        headers=_headers(ADMIN),
        json={
            "items": [
                {"name": "积分 +10", "probability": 90},
                {"name": "邀请码 1 枚", "probability": 10},
            ],
            "cost_credits": 10,
            "min_credits_required": 30,
            "gen_privileged_code": True,
        },
    )
    assert response.status_code == 200
    assert len(saved) == 1
    assert [item.probability for item in saved[0].items] == [90, 10]
    assert saved[0].gen_privileged_code is True


def test_admin_save_rejects_missing_noninvite_fallback(api):
    client, _ = api
    response = client.put(
        "/api/luckywheel/config",
        headers=_headers(ADMIN),
        json={
            "items": [{"name": "邀请码 1 枚", "probability": 100}],
            "cost_credits": 10,
            "min_credits_required": 30,
        },
    )
    assert response.status_code == 400


def test_public_user_cannot_save_complete_wheel_config(api, monkeypatch):
    client, _ = api
    saved = []
    monkeypatch.setattr(
        wheel_service, "update_wheel_config", lambda request: saved.append(request)
    )
    response = client.put(
        "/api/luckywheel/config",
        headers=_headers(USER),
        json={"items": [{"name": "积分 +10", "probability": 100}]},
    )
    assert response.status_code == 403
    assert not saved
