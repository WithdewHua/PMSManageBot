"""Run a PostgreSQL concurrency check for the JSON config compare-and-update.

Usage::

    DATABASE_URL=postgresql+psycopg2://... \
      python -m scripts.refactor.smoke_kv_concurrency --url "$DATABASE_URL"

The command owns the target database for the duration of the run: it recreates
all application tables, seeds one config document, and leaves no production data
behind. Never point it at a live application database without an isolated
database or disposable container.
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    if not args.url.startswith("postgresql"):
        raise SystemExit("config concurrency smoke requires a PostgreSQL URL")

    os.environ["DATABASE_URL"] = args.url
    os.environ["DATABASE_TYPE"] = "postgresql"

    from sqlalchemy.orm import sessionmaker

    import app.core.db as db_module
    from app.core.kv import compare_and_update_tx, get_tx, upsert_tx
    from app.model_registry import metadata

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
        upsert_tx(session, "lucky_wheel", "config", '{"gen_privileged_code": true}')

    def attempt(_: int) -> bool:
        with db_module.get_session() as session:
            return compare_and_update_tx(
                session,
                "lucky_wheel",
                "config",
                lambda document: document.get("gen_privileged_code") is True,
                gen_privileged_code=False,
            )

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(attempt, range(20)))

    with db_module.get_session() as session:
        stored = get_tx(session, "lucky_wheel", "config")

    successes = sum(1 for result in results if result)
    assert successes == 1, results
    assert json.loads(stored) == {"gen_privileged_code": False}
    print(
        {"ok": True, "successes": successes, "attempts": len(results), "stored": stored}
    )
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
