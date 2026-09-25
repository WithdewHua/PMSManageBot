"""The B1 registry assembles every split model before table creation."""

from sqlalchemy.orm import configure_mappers

from app.core.db import Base, engine
from app.model_registry import MODEL_MODULES, init_db, metadata


def test_registry_imports_every_domain_model() -> None:
    assert metadata is Base.metadata
    assert len(metadata.tables) == 31
    assert len(MODEL_MODULES) == 17
    configure_mappers()


def test_registry_init_db_uses_registered_metadata(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(metadata, "create_all", lambda *, bind: calls.append(bind))
    init_db()
    assert calls == [engine]


def test_cross_domain_read_models_live_in_rankings_repository() -> None:
    from app.databases import db
    from app.domains.rankings.repository import RankingsRepository

    for method in ("get_credits_rank", "get_donation_rank", "get_badge_rank"):
        assert getattr(db, method).__func__ is getattr(RankingsRepository, method)
