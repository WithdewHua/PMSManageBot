"""Real PostgreSQL contention checks, strictly restricted to disposable local DBs."""

import asyncio
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core import db, events
from app.domains.credits import repository as credits_repository
from app.domains.crypto_donation import repository as crypto_repository
from app.domains.crypto_donation.models import CryptoDonationOrders
from app.domains.donation import exceptions as donation_errors
from app.domains.donation import repository as donation_repository
from app.domains.identity.models import Statistics
from app.model_registry import metadata


@pytest.fixture
def postgres(monkeypatch):
    url = os.environ.get("REMAINING_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("REMAINING_TEST_POSTGRES_URL must name a disposable local database")
    parsed = make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost"}
    assert parsed.database.startswith("pms_test_remaining_")
    engine = create_engine(url)
    schema = f"remaining_{uuid.uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    isolated = engine.execution_options(schema_translate_map={None: schema})
    metadata.create_all(isolated)
    monkeypatch.setattr(
        db,
        "SessionLocal",
        sessionmaker(bind=isolated, autoflush=False, expire_on_commit=False),
    )
    monkeypatch.setattr(credits_repository, "invalidate_user_credits", lambda _: None)
    dispatched = []
    monkeypatch.setattr(events, "_dispatch", lambda batch: dispatched.extend(batch))
    try:
        with db.get_session() as session:
            session.add_all(
                [
                    Statistics(tg_id=42, credits=100, donation=0),
                    Statistics(tg_id=1, credits=0, donation=0),
                ]
            )
        yield dispatched
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def concurrently(function):
    barrier = threading.Barrier(8)

    def run(_):
        barrier.wait(timeout=15)
        return function()

    with ThreadPoolExecutor(max_workers=8) as executor:
        return list(executor.map(run, range(8)))


def test_concurrent_donation_confirmation_posts_once(postgres, monkeypatch):
    from unittest.mock import AsyncMock

    from app.domains.donation import service as donation_service

    monkeypatch.setattr(donation_service, "get_donation_multiplier", lambda: 2)
    monkeypatch.setattr(
        donation_service.telegram_profiles, "get_user_name_from_tg_id", str
    )
    monkeypatch.setattr(
        donation_service.notifications, "send_confirmation_notifications", AsyncMock()
    )
    registration_id = donation_repository.create_donation_registration(42, "other", 10)
    assert registration_id is not None

    def confirm():
        try:
            asyncio.run(
                donation_service.confirm_donation_registration(registration_id, 1, True)
            )
            return True
        except donation_errors.DonationRegistrationNotPending:
            return False

    assert concurrently(confirm).count(True) == 1
    with db.get_session() as session:
        statistics = session.get(Statistics, 42)
        assert statistics.donation == 10
        assert statistics.credits == 120
    assert len(postgres) == 1


def test_concurrent_crypto_callback_posts_once(postgres):
    with db.get_session() as session:
        session.add(
            CryptoDonationOrders(
                user_id=42,
                order_id="order",
                trade_id="trade",
                crypto_type="USDT",
                amount=10,
                status=1,
                created_at="2030-01-01",
            )
        )

    def complete():
        return crypto_repository.settle_payment(
            trade_id="trade",
            callback_amount=10,
            actual_amount=9.5,
            block_transaction_id="chain",
            multiplier=2,
        )

    results = concurrently(complete)
    assert sum(item is not None for item in results) == 1
    with db.get_session() as session:
        statistics = session.get(Statistics, 42)
        assert statistics.donation == 10
        assert statistics.credits == 120
    assert len(postgres) == 1
