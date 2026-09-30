"""Export line catalog back to .env lines and SystemConfig SQL / kv rows for rollback."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import delete as sql_delete
from sqlalchemy import select

from app.core.db import get_session
from app.core.kv import SystemConfig, upsert_tx
from app.domains.lines.models import LineCatalog


def get_export_data() -> dict:
    """Retrieve catalog data structured for rollback export."""
    with get_session() as session:
        rows = (
            session.execute(select(LineCatalog).order_by(LineCatalog.position))
            .scalars()
            .all()
        )
        normal_lines = [r.name for r in rows if r.kind == "normal"]
        premium_lines = [r.name for r in rows if r.kind == "premium"]

        tags_map = {}
        for r in rows:
            try:
                tags = json.loads(r.tags)
                if isinstance(tags, list) and tags:
                    tags_map[r.name] = ",".join(tags)
            except json.JSONDecodeError:
                continue

        free_premium_lines = [
            r.name for r in rows if r.kind == "premium" and r.free_open == 1
        ]

    return {
        "normal_lines": normal_lines,
        "premium_lines": premium_lines,
        "tags_map": tags_map,
        "free_premium_lines": free_premium_lines,
    }


def generate_export_content() -> tuple[list[str], list[str]]:
    """Generate .env lines and SQL statements."""
    data = get_export_data()
    now = int(time.time())

    env_lines = [
        f"STREAM_BACKEND={','.join(data['normal_lines'])}",
        f"PREMIUM_STREAM_BACKEND={','.join(data['premium_lines'])}",
    ]

    sql_statements = [
        "DELETE FROM system_config WHERE config_type IN ('line_tag', 'free_premium_line');",
        "DELETE FROM system_config WHERE config_type = 'lines' AND config_key = 'catalog_imported';",
    ]

    for name, tags_str in data["tags_map"].items():
        escaped_name = name.replace("'", "''")
        escaped_val = tags_str.replace("'", "''")
        sql_statements.append(
            f"INSERT INTO system_config (config_type, config_key, config_value, created_at, updated_at) "
            f"VALUES ('line_tag', '{escaped_name}', '{escaped_val}', {now}, {now});"
        )

    for name in data["free_premium_lines"]:
        escaped_name = name.replace("'", "''")
        sql_statements.append(
            f"INSERT INTO system_config (config_type, config_key, config_value, created_at, updated_at) "
            f"VALUES ('free_premium_line', '{escaped_name}', '1', {now}, {now});"
        )

    return env_lines, sql_statements


def apply_kv_restore() -> dict[str, int]:
    """Write tags and free premium line markers directly back into system_config."""
    data = get_export_data()

    with get_session() as session:
        # Delete existing line_tag and free_premium_line
        session.execute(
            sql_delete(SystemConfig).where(
                SystemConfig.config_type.in_(["line_tag", "free_premium_line"])
            )
        )
        # Remove import marker
        session.execute(
            sql_delete(SystemConfig).where(
                SystemConfig.config_type == "lines",
                SystemConfig.config_key == "catalog_imported",
            )
        )

        for name, tags_str in data["tags_map"].items():
            upsert_tx(session, "line_tag", name, tags_str)

        for name in data["free_premium_lines"]:
            upsert_tx(session, "free_premium_line", name, "1")

    return {
        "tags_restored": len(data["tags_map"]),
        "free_premium_restored": len(data["free_premium_lines"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export line catalog to .env lines and system_config SQL for rollback."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Directly restore line_tag and free_premium_line rows into system_config.",
    )
    args = parser.parse_args()

    env_lines, sql_statements = generate_export_content()

    print("# --- .env lines ---")
    for line in env_lines:
        print(line)

    print("\n# --- SQL statements ---")
    for sql in sql_statements:
        print(sql)

    if args.apply:
        result = apply_kv_restore()
        print(
            f"\n[APPLIED] Successfully restored {result['tags_restored']} tag rows and {result['free_premium_restored']} free premium line rows."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
