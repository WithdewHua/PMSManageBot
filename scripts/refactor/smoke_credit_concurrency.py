"""Run deterministic PostgreSQL concurrency checks for the credit ledger.

Usage::

    DATABASE_URL=postgresql+psycopg2://... \
      python -m scripts.refactor.smoke_credit_concurrency --url "$DATABASE_URL"

The command owns the target database for the duration of the run: it recreates
all application tables, seeds synthetic rows, verifies the invariants, and
leaves no production data behind. Never point it at a live application
Database without an isolated database or disposable container.
"""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    if not args.url.startswith("postgresql"):
        raise SystemExit("credit concurrency smoke requires a PostgreSQL URL")

    os.environ["DATABASE_URL"] = args.url
    os.environ["DATABASE_TYPE"] = "postgresql"

    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    import app.core.db as db_module
    from app.domains.credits import service
    from app.domains.credits.types import CreditAccount
    from app.domains.identity.models import EmbyUser, PlexUser, Statistics
    from app.model_registry import metadata

    # Cache behavior is covered by unit tests; keep this database-only smoke
    # independent of a Redis daemon.
    service.invalidate_cache_keys = lambda _keys: None

    engine = db_module.create_engine(
        args.url,
        pool_size=20,
        max_overflow=20,
        pool_pre_ping=True,
    )
    metadata.drop_all(engine)
    metadata.create_all(engine)
    db_module.engine = engine
    db_module.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )

    with db_module.get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=1001, donation=0, credits=200),
                Statistics(tg_id=2002, donation=0, credits=200),
                Statistics(tg_id=3001, donation=0, credits=1000),
                Statistics(tg_id=3002, donation=0, credits=1000),
                PlexUser(
                    id=1,
                    plex_id=9001,
                    tg_id=None,
                    credits=0,
                    plex_username="concurrency-plex",
                ),
                EmbyUser(
                    emby_username="concurrency-emby",
                    emby_id="concurrency-emby",
                    tg_id=None,
                    emby_credits=0,
                ),
            ]
        )

    def deduct_one(_: int) -> None:
        service.deduct(CreditAccount.tg(1001), 1)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(deduct_one, range(100)))

    def mixed_delta(index: int) -> None:
        if index % 2:
            service.add(CreditAccount.tg(1001), 0.5)
        else:
            service.deduct(CreditAccount.tg(1001), 0.25)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(mixed_delta, range(100)))

    def opposite_transfer(_: int) -> None:
        if _ % 2:
            service.transfer(3001, 3002, 10)
        else:
            service.transfer(3002, 3001, 10)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(opposite_transfer, range(20)))

    def add_unbound(_: int) -> None:
        service.add(CreditAccount.plex(9001), 0.5)
        service.add(CreditAccount.emby("concurrency-emby"), 0.25)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(add_unbound, range(40)))

    with db_module.get_session() as session:
        tg_1001 = session.execute(
            select(Statistics.credits).where(Statistics.tg_id == 1001)
        ).scalar_one()
        tg_3001 = session.execute(
            select(Statistics.credits).where(Statistics.tg_id == 3001)
        ).scalar_one()
        tg_3002 = session.execute(
            select(Statistics.credits).where(Statistics.tg_id == 3002)
        ).scalar_one()
        plex = session.execute(
            select(PlexUser.credits).where(PlexUser.plex_id == 9001)
        ).scalar_one()
        emby = session.execute(
            select(EmbyUser.emby_credits).where(EmbyUser.emby_id == "concurrency-emby")
        ).scalar_one()

    assert round(float(tg_1001), 2) == 112.5
    assert float(tg_3001) >= 0 and float(tg_3002) >= 0
    assert round(float(tg_3001) + float(tg_3002), 2) == 1990.0
    assert round(float(plex), 2) == 20.0
    assert round(float(emby), 2) == 10.0
    print(
        {
            "ok": True,
            "tg_1001": float(tg_1001),
            "transfer_total": round(float(tg_3001) + float(tg_3002), 2),
            "plex": float(plex),
            "emby": float(emby),
        }
    )
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
