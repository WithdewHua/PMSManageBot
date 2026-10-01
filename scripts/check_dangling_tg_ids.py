"""Read-only audit of Telegram IDs that no longer have a statistics row."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import create_engine, select, text

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


def _extract_json_path_ids(value: Any, json_path: str | None) -> set[int]:
    """Extract valid positive Telegram IDs from JSON data at json_path.

    Supports:
    - Numeric integers and legitimate numeric strings (e.g. 12345, '12345').
    - Reports and handles nested invalid data safely instead of failing silently.
    - Ignores null and nonpositive sentinels (<= 0).
    """
    from app.core.log import logger

    if not value:
        return set()

    data: Any
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except (ValueError, TypeError) as err:
            logger.warning(
                "Malformed JSON in encoded location: %s (value: %r)", err, value
            )
            return set()
    else:
        data = value

    result: set[int] = set()

    if json_path == "user_list.tg_ids":
        items: list[Any]
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = [data]
        else:
            logger.warning("Unexpected audience root structure: %r", type(data))
            return set()

        for item in items:
            if not isinstance(item, dict):
                logger.warning("Audience item is not a dict: %r", item)
                continue
            if item.get("type") != "user_list":
                continue
            raw_ids = item.get("tg_ids")
            if not isinstance(raw_ids, list):
                logger.warning(
                    "Audience item user_list.tg_ids is not a list: %r",
                    type(raw_ids),
                )
                continue
            for raw_id in raw_ids:
                if raw_id is None:
                    # null sentinel ignored
                    continue
                try:
                    val = int(raw_id)
                except (ValueError, TypeError):
                    logger.warning("Non-integer value in audience tg_ids: %r", raw_id)
                    continue
                if val <= 0:
                    # nonpositive sentinel ignored
                    continue
                result.add(val)
    else:
        logger.warning("Unknown json_path in encoded location: %s", json_path)

    return result


def collect_dangling_tg_ids(
    database_url: str | None = None,
    *,
    engine: Engine | None = None,
) -> dict[str, list[int]]:
    """Return sorted dangling IDs without issuing INSERT/UPDATE/DELETE statements."""
    import app.model_registry  # noqa: F401
    from app.core.db import Base
    from app.core.log import logger
    from app.domains.identity.models import Statistics
    from app.domains.tg_rebind.constants import ENCODED_TG_ID_LOCATIONS

    owns_engine = engine is None
    if engine is None:
        if not database_url:
            raise ValueError("Either database_url or engine must be provided")
        engine = create_engine(database_url)

    result: dict[str, set[int]] = defaultdict(set)
    try:
        with engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(text("SET TRANSACTION READ ONLY"))
            elif connection.dialect.name == "sqlite":
                connection.execute(text("PRAGMA query_only = ON"))

            existing: set[int] = {
                int(row[0])
                for row in connection.execute(
                    select(Statistics.tg_id).where(Statistics.tg_id > 0)
                ).all()
                if row[0] is not None
            }

            # 1. Audit numeric columns marked in model info
            for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
                for column in table.columns:
                    marker = (
                        column.info.get("tg_id")
                        if isinstance(column.info, dict)
                        else None
                    )
                    if marker not in {"user", "admin"}:
                        continue
                    # statistics.tg_id is the identity source of truth
                    if table.name == "statistics" and column.name == "tg_id":
                        continue

                    stmt = select(column).where(column.is_not(None))
                    for (value,) in connection.execute(stmt).all():
                        if value is None:
                            continue
                        try:
                            tg_id = int(value)
                        except (ValueError, TypeError):
                            logger.warning(
                                "Non-integer value in numeric column %s.%s: %r",
                                table.name,
                                column.name,
                                value,
                            )
                            continue
                        if tg_id <= 0:
                            # null/nonpositive sentinels ignored
                            continue
                        if tg_id not in existing:
                            result[f"{table.name}.{column.name}"].add(tg_id)

            # 2. Audit registry-driven encoded locations
            for location in ENCODED_TG_ID_LOCATIONS:
                table = Base.metadata.tables.get(location.table)
                if table is None:
                    logger.warning(
                        "Encoded location table not found in metadata: %s",
                        location.table,
                    )
                    continue
                col = table.c.get(location.column)
                if col is None:
                    logger.warning(
                        "Encoded location column not found in table %s: %s",
                        location.table,
                        location.column,
                    )
                    continue

                prefix = location.prefix or ""
                key = (
                    f"{location.table}.{location.column}:{prefix}"
                    if prefix
                    else f"{location.table}.{location.column}"
                )

                if location.kind == "prefix":
                    stmt = select(col).where(col.is_not(None))
                    for (value,) in connection.execute(stmt).all():
                        if not isinstance(value, str) or not value.startswith(prefix):
                            continue
                        raw_id = value.removeprefix(prefix)
                        try:
                            tg_id = int(raw_id)
                        except (ValueError, TypeError):
                            logger.warning(
                                "Invalid integer in prefix location %s: %r",
                                key,
                                value,
                            )
                            continue
                        if tg_id <= 0:
                            continue
                        if tg_id not in existing:
                            result[key].add(tg_id)

                elif location.kind == "json_path":
                    stmt = select(col).where(col.is_not(None))
                    for (value,) in connection.execute(stmt).all():
                        extracted_ids = _extract_json_path_ids(value, location.prefix)
                        for tg_id in extracted_ids:
                            if tg_id > 0 and tg_id not in existing:
                                result[key].add(tg_id)
                else:
                    logger.warning(
                        "Unsupported encoded location kind: %s", location.kind
                    )

    finally:
        if owns_engine:
            engine.dispose()

    return {key: sorted(values) for key, values in sorted(result.items()) if values}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        required=not bool(os.environ.get("DATABASE_URL")),
        help="Database URL (defaults to DATABASE_URL environment variable)",
    )
    parser.add_argument("--output", type=Path, help="Path to write JSON report")
    options = parser.parse_args(argv)
    report = collect_dangling_tg_ids(options.database_url)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if options.output:
        options.output.write_text(encoded)
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
