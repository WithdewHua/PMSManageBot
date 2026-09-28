"""Verify concurrent updates to one JSON business-config document on PostgreSQL."""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    if not args.url.startswith("postgresql"):
        raise SystemExit("business config concurrency requires a PostgreSQL URL")

    os.environ["DATABASE_URL"] = args.url
    os.environ["DATABASE_TYPE"] = "postgresql"

    from sqlalchemy.orm import sessionmaker

    import app.core.db as db_module
    from app.core.kv import get_tx
    from app.domains.blackjack.config import BLACKJACK_CONFIG
    from app.model_registry import metadata

    engine = db_module.create_engine(
        args.url, pool_size=20, max_overflow=20, pool_pre_ping=True
    )
    metadata.drop_all(engine)
    metadata.create_all(engine)
    db_module.engine = engine
    db_module.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )

    BLACKJACK_CONFIG.seed()

    def update(index: int):
        if index % 2:
            return BLACKJACK_CONFIG.update(min_credits=101 + index)
        return BLACKJACK_CONFIG.update(hand_timeout_minutes=200 + index)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(update, range(20)))

    with db_module.get_session() as session:
        import json

        document = json.loads(get_tx(session, "blackjack", "config"))

    assert document["min_credits"] in range(102, 121, 2)
    assert document["hand_timeout_minutes"] in range(200, 220, 2)
    print(
        {
            "ok": True,
            "min_credits": document["min_credits"],
            "hand_timeout_minutes": document["hand_timeout_minutes"],
        }
    )
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
