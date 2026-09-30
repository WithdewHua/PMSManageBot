"""Frozen badge payloads and business behavior on disposable databases only."""

import time

import pytest
from sqlalchemy import event

from app.core.db import get_session
from app.domains.badges import repository
from app.domains.badges.models import Badge, UserBadge
from app.domains.identity.models import Statistics


@pytest.fixture
def badge_api(session_env, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1700000000)
    # Older test modules install process-wide BIGINT ID listeners at collection.
    # Override their assigned IDs only within this isolated SQLite fixture so
    # frozen payloads do not depend on test collection/execution order.
    counters = {Badge: iter(range(1, 1000)), UserBadge: iter(range(1, 1000))}

    def assign_id(_mapper, connection, row):
        if connection.dialect.name == "sqlite":
            row.id = next(counters[type(row)])

    for model in counters:
        event.listen(model, "before_insert", assign_id)
    try:
        with get_session() as session:
            session.add(Statistics(tg_id=42, credits=100, donation=0))
        yield repository
    finally:
        for model in counters:
            event.remove(model, "before_insert", assign_id)


def make_badge(api, badge_type="test", **overrides):
    values = {
        "badge_type": badge_type,
        "name": "测试",
        "description": "说明",
        "icon_url": "/badge.svg",
        "credits_cost": 30.0,
        "bonus_percentage": 0.18,
        "valid_days": 365,
        "is_enabled": 1,
    }
    values.update(overrides)
    return api.create_badge(**values)


def test_badge_definition_crud(badge_api):
    badge = make_badge(badge_api)
    assert badge == {
        "id": 1,
        "badge_type": "test",
        "name": "测试",
        "description": "说明",
        "icon_url": "/badge.svg",
        "credits_cost": 30.0,
        "bonus_percentage": 0.18,
        "valid_days": 365,
        "is_enabled": 1,
        "created_at": 1700000000,
        "updated_at": 1700000000,
    }
    assert badge_api.get_badge_by_id(1) == badge
    assert badge_api.get_badge_by_type("test") == badge
    assert badge_api.get_all_badges() == [badge]
    assert badge_api.update_badge(1, name="改名", is_enabled=0)
    assert badge_api.get_all_badges(only_enabled=True) == []
    assert badge_api.get_badge_by_id(1)["name"] == "改名"
    assert badge_api.delete_badge(1)
    assert not badge_api.delete_badge(1)
    assert badge_api.get_badge_by_id(1) is None
    assert not badge_api.update_badge(1, name="missing")


def test_redemption_payload_and_rank(badge_api):
    badge = make_badge(badge_api)
    success, message, owned = badge_api.redeem_badge(42, badge["id"])
    expected = {
        "id": 1,
        "tg_id": 42,
        "badge_id": 1,
        "credits_cost": 30.0,
        "redeemed_at": 1700000000,
        "expires_at": 1731536000,
        "is_active": 1,
        "bonus_active": True,
        "badge": badge,
    }
    assert (success, message, owned) == (True, "兑换成功", expected)
    with get_session() as session:
        assert session.get(Statistics, 42).credits == 70
    assert badge_api.get_user_badges(42) == [expected]
    from app.databases.db import DatabaseORM

    assert DatabaseORM().get_badge_rank() == [
        {"tg_id": 42, "badge_count": 1, "badges": [expected]}
    ]
    assert badge_api.redeem_badge(42, 1) == (False, "您已经拥有该勋章", None)


def test_redemption_rejections(badge_api):
    assert badge_api.redeem_badge(42, 99) == (False, "勋章不存在", None)
    badge = make_badge(badge_api, credits_cost=101.0)
    assert badge_api.redeem_badge(42, badge["id"]) == (
        False,
        "积分不足，需要 101.0 积分",
        None,
    )
    assert badge_api.redeem_badge(999, badge["id"]) == (False, "用户不存在", None)
    badge_api.update_badge(badge["id"], is_enabled=0)
    assert badge_api.redeem_badge(42, badge["id"]) == (False, "该勋章暂不可兑换", None)


def test_bonus_filters_expiry_and_removed_but_not_disabled(badge_api):
    badge = make_badge(badge_api, is_enabled=0)
    with get_session() as session:
        session.add(
            UserBadge(
                tg_id=42,
                badge_id=badge["id"],
                credits_cost=0,
                redeemed_at=1699990000,
                expires_at=1700000001,
                is_active=1,
            )
        )
    assert badge_api.get_user_active_badges_with_bonus(42) == [
        {"badge": badge, "bonus_percentage": 0.18, "expires_at": 1700000001}
    ]
    with get_session() as session:
        session.get(UserBadge, 1).expires_at = 1700000000
    assert badge_api.get_user_active_badges_with_bonus(42) == []
    assert badge_api.get_user_badges(42)[0]["bonus_active"] is False
    with get_session() as session:
        row = session.get(UserBadge, 1)
        row.expires_at = 1700000001
        row.is_active = 0
    assert badge_api.get_user_active_badges_with_bonus(42) == []
    assert badge_api.get_user_badges(42) == []
    assert len(badge_api.get_user_badges(42, only_active=False)) == 1


def test_renewal_preserves_cap_and_ownership(badge_api):
    badge = make_badge(badge_api)
    assert repository.award_or_renew_badge(42, badge["id"], 7) == {
        "awarded": True,
        "renewed": False,
        "expires_at": 1700604800,
        "previous_expires_at": None,
    }
    assert repository.award_or_renew_badge(42, badge["id"], 7, cap_days=10) == {
        "awarded": False,
        "renewed": True,
        "expires_at": 1700864000,
        "previous_expires_at": 1700604800,
    }


@pytest.mark.parametrize(
    "badge_id, expected", [(99, "badge_not_found"), (1, "badge_insufficient_credits")]
)
def test_service_typed_rejections(badge_api, badge_id, expected):
    from app.core.errors import DomainError
    from app.domains.badges import exceptions, service

    make_badge(badge_api, credits_cost=101.0)
    with pytest.raises(exceptions.BadgeError) as error:
        service.redeem_badge(42, badge_id)
    assert isinstance(error.value, (DomainError, ValueError))
    assert error.value.code == expected


def test_failed_insert_rolls_back_debit_and_cache_callbacks(badge_api, monkeypatch):
    from app.domains.badges import service
    from app.domains.credits import repository as credit_repository

    make_badge(badge_api)
    invalidations = []
    monkeypatch.setattr(
        credit_repository,
        "invalidate_user_credits",
        lambda keys: invalidations.append(keys),
    )

    def fail_insert(*args):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(repository, "_new_ownership", fail_insert)
    with pytest.raises(RuntimeError, match="insert failed"):
        service.redeem_badge(42, 1)
    with get_session() as session:
        assert session.get(Statistics, 42).credits == 100
        assert session.query(UserBadge).count() == 0
    assert invalidations == []


def test_award_idempotency_and_bonus_sum(badge_api):
    from app.domains.badges import service

    make_badge(badge_api, "one", is_enabled=0, bonus_percentage=0.18)
    make_badge(badge_api, "two", bonus_percentage=0.3)
    assert service.award_badge(42, "one") is True
    assert service.award_badge(42, "one") is False
    assert service.award_badge(42, "two") is True
    assert service.active_bonus_percentage(42) == pytest.approx(0.48)
    with get_session() as session:
        row = session.get(UserBadge, 1)
        row.is_active = 0
    # Inactive/expired ownership still blocks duplicate awards; no renewal.
    assert service.award_badge(42, "one") is False
    assert service.active_bonus_percentage(42) == pytest.approx(0.3)


def test_award_storage_failure_propagates(badge_api, monkeypatch):
    from app.domains.badges import service
    from app.domains.identity import repository as identity_repository

    make_badge(badge_api)

    def fail(*args, **kwargs):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(identity_repository, "get_statistics_tx", fail)
    with pytest.raises(RuntimeError, match="storage unavailable"):
        service.award_badge(42, "test")


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_concurrent_awards_and_redemptions(tmp_path, monkeypatch, dialect):
    import os
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker

    from app.core import db as session_module
    from app.domains.badges import exceptions, service
    from app.model_registry import metadata

    if dialect == "postgresql":
        url = os.environ.get("BADGES_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("set BADGES_TEST_POSTGRES_URL to a disposable local PostgreSQL")
        assert "localhost" in url or "127.0.0.1" in url
    else:
        url = f"sqlite:///{tmp_path / 'badges.sqlite'}"
    engine = create_engine(url)
    metadata.create_all(engine)
    monkeypatch.setattr(
        session_module, "SessionLocal", sessionmaker(bind=engine, autoflush=False)
    )
    with get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=42, credits=100, donation=0),
                Statistics(tg_id=43, credits=100, donation=0),
            ]
        )
    badge = make_badge(repository)
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            awards = list(
                executor.map(lambda _: service.award_badge(42, "test"), range(16))
            )
        assert awards.count(True) == 1
        assert awards.count(False) == 15

        def redeem(_):
            try:
                service.redeem_badge(43, badge["id"])
                return True
            except exceptions.BadgeAlreadyOwned:
                return False

        with ThreadPoolExecutor(max_workers=8) as executor:
            redemptions = list(executor.map(redeem, range(16)))
        assert redemptions.count(True) == 1
        with get_session() as session:
            assert session.scalar(select(func.count()).select_from(UserBadge)) == 2
            assert session.get(Statistics, 43).credits == 70
    finally:
        metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.parametrize(
    "cost, success, message",
    [(30.0, True, "兑换成功"), (101.0, False, "积分不足，需要 101.0 积分")],
)
def test_router_redemption_response(badge_api, monkeypatch, cost, success, message):
    import asyncio

    from starlette.requests import Request

    from app.domains.badges import router, service
    from app.domains.badges.schemas import BadgeRedeemRequest
    from app.domains.identity import service as identity_service
    from app.transport.http.schemas import TelegramUser

    badge = make_badge(badge_api, credits_cost=cost)
    service.set_badge_center_config(True)
    monkeypatch.setattr(identity_service, "get_stats_by_tg_id", lambda _: (42,))
    request = Request({"type": "http"})
    request.state.telegram_data = {"id": 42}
    response = asyncio.run(
        router.redeem_badge(
            request=request,
            data=BadgeRedeemRequest(badge_id=badge["id"]),
            telegram_user=TelegramUser(id=42, first_name="测试"),
        )
    )
    assert response.success is success
    assert response.message == message
    if success:
        assert response.remaining_credits == 70.0
        assert response.credits_deducted == 30.0
        assert response.user_badge.model_dump() == repository.get_user_badges(42)[0]
    else:
        assert response.model_dump() == {
            "success": False,
            "message": message,
            "user_badge": None,
            "credits_deducted": None,
            "remaining_credits": None,
        }
