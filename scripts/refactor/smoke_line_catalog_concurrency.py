"""Verify concurrent line additions on disposable PostgreSQL."""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    if not args.url.startswith("postgresql"):
        raise SystemExit("line catalog concurrency requires a PostgreSQL URL")

    os.environ["DATABASE_URL"] = args.url
    os.environ["DATABASE_TYPE"] = "postgresql"

    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    import app.core.db as db_module
    from app.domains.lines import catalog
    from app.domains.lines.models import LineCatalog
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

    catalog.invalidate_cache()

    def add_worker(index: int) -> tuple[int, bool, str | None]:
        try:
            catalog.add_line(f"conc-line-{index:02d}", premium=False)
            return (index, True, None)
        except Exception as error:
            return (index, False, str(error))

    succeeded = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(add_worker, i) for i in range(20)]
        for future in as_completed(futures):
            _, success, _ = future.result()
            if success:
                succeeded += 1
            else:
                failed += 1

    with db_module.get_session() as session:
        rows = (
            session.execute(
                select(LineCatalog)
                .where(LineCatalog.kind == "normal")
                .order_by(LineCatalog.position)
            )
            .scalars()
            .all()
        )
        positions = [r.position for r in rows]

    assert len(positions) == succeeded, (
        f"Row count {len(positions)} != succeeded {succeeded}"
    )
    assert len(positions) == len(set(positions)), (
        f"Duplicate positions found: {positions}"
    )
    print(
        {"ok": True, "succeeded": succeeded, "failed": failed, "positions": positions}
    )
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
