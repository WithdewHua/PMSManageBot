"""Ensure every model-level Telegram ID field has an explicit migration owner."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table

import app.model_registry  # noqa: F401
from app.core.db import Base
from app.domains.tg_rebind.constants import (
    ENCODED_TG_ID_LOCATIONS,
    PARTICIPATING_DOMAINS,
)

if TYPE_CHECKING:
    from sqlalchemy.sql.schema import Column as ColumnType
    from sqlalchemy.sql.schema import Table as TableType


_SUSPICIOUS_SUFFIXES = (
    "tg_id",
    "_tg_id",
    "_by",
    "owner",
    "winner_id",
    "bidder_id",
    "user_id",
)

EXPECTED_TAGGED_NUMERIC_COUNT = 35


def _is_suspicious(column: ColumnType) -> bool:
    """Detect columns that could store a Telegram ID by naming convention or FK."""
    name = column.name.lower()
    if name in {"tg_id", "owner", "user_id"} or name.endswith(_SUSPICIOUS_SUFFIXES):
        return True
    for fk in column.foreign_keys:
        if fk.column.table.name == "statistics" and fk.column.name == "tg_id":
            return True
        if fk.target_fullname in {"statistics.tg_id", "public.statistics.tg_id"}:
            return True
    return False


def _domain_for_table(table: TableType) -> str:
    """Resolve domain name for a table via metadata info or ORM mapper."""
    if "domain" in table.info:
        return str(table.info["domain"])
    module = next(iter(table.columns)).table.metadata.info.get("domain")
    if module:
        return str(module)
    for mapper in Base.registry.mappers:
        if mapper.local_table is table:
            mod_name = mapper.class_.__module__
            if ".domains." in mod_name:
                return mod_name.split(".domains.", 1)[-1].split(".", 1)[0]
            return mod_name.split(".", 1)[0]
    return "unknown"


def _declared_columns() -> dict[str, set[str]]:
    declarations: dict[str, set[str]] = {}
    for domain in PARTICIPATING_DOMAINS:
        module = importlib.import_module(f"app.domains.{domain}.repository")
        declarations[domain] = set(getattr(module, "REASSIGNED_TG_ID_COLUMNS", ()))
    return declarations


def validate_tg_rebind_coverage(
    metadata: MetaData | None = None,
    declarations: dict[str, set[str]] | None = None,
) -> None:
    """Validate that all model columns and declared migration columns strictly align."""
    if metadata is None:
        metadata = Base.metadata
    if declarations is None:
        declarations = _declared_columns()

    encoded_cols = {f"{loc.table}.{loc.column}" for loc in ENCODED_TG_ID_LOCATIONS}

    # 1. Enforce exact registration: no invented or cross-domain nonexistent columns
    for domain, cols in declarations.items():
        assert domain in PARTICIPATING_DOMAINS, (
            f"Domain {domain} is not in PARTICIPATING_DOMAINS"
        )
        for col_id in cols:
            assert "." in col_id, (
                f"Invalid column declaration format '{col_id}' in {domain}"
            )
            t_name, c_name = col_id.split(".", 1)
            assert t_name in metadata.tables, (
                f"{domain} declared nonexistent table {t_name} in {col_id}"
            )
            table = metadata.tables[t_name]
            assert c_name in table.columns, (
                f"{domain} declared nonexistent column {c_name} in {col_id}"
            )
            if col_id in encoded_cols:
                assert any(
                    loc.domain == domain and f"{loc.table}.{loc.column}" == col_id
                    for loc in ENCODED_TG_ID_LOCATIONS
                ), f"{domain} declared encoded col {col_id} not owned by this domain"
            else:
                table_domain = _domain_for_table(table)
                assert table_domain == domain, (
                    f"{domain} declared column {col_id} belonging to domain {table_domain}"
                )

    # 2. Enforce model-level tags, ownership, and suspicious columns
    for table in metadata.tables.values():
        domain = _domain_for_table(table)
        for column in table.columns:
            marker = column.info.get("tg_id") if isinstance(column.info, dict) else None
            if marker is not None:
                assert marker in {"user", "admin", False}, (
                    f"Unsupported tg_id label {marker!r} on {table.name}.{column.name}"
                )
            if marker in {"user", "admin"}:
                assert domain in PARTICIPATING_DOMAINS, (
                    f"Table {table.name} belongs to domain {domain} which is not in PARTICIPATING_DOMAINS"
                )
                col_id = f"{table.name}.{column.name}"
                assert col_id in declarations.get(domain, set()), (
                    f"{col_id} is marked as {marker} but not in {domain}.REASSIGNED_TG_ID_COLUMNS"
                )
            elif _is_suspicious(column):
                assert isinstance(column.info, dict) and "tg_id" in column.info, (
                    f"Suspicious column lacks explicit tg_id metadata: {table.name}.{column.name}"
                )

    # 3. Enforce encoded location ownership and registration
    for loc in ENCODED_TG_ID_LOCATIONS:
        assert loc.domain in PARTICIPATING_DOMAINS, (
            f"Encoded location domain {loc.domain} is not in PARTICIPATING_DOMAINS"
        )
        assert loc.kind in {"prefix", "json_path"}, (
            f"Unsupported encoded kind {loc.kind}"
        )
        loc_col = f"{loc.table}.{loc.column}"
        assert loc_col in declarations[loc.domain], (
            f"Encoded location {loc_col} missing from {loc.domain}.REASSIGNED_TG_ID_COLUMNS"
        )


def test_marked_columns_are_declared_and_owned() -> None:
    """Full coverage validation against real Base.metadata and domain declarations."""
    validate_tg_rebind_coverage()


def test_tagged_numeric_column_count_and_statistics_root() -> None:
    """Verify exact count of 35 tagged numeric TG columns and statistics root ownership."""
    tagged = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.info, dict)
        and column.info.get("tg_id") in {"user", "admin"}
    ]
    assert len(tagged) == EXPECTED_TAGGED_NUMERIC_COUNT, (
        f"Expected {EXPECTED_TAGGED_NUMERIC_COUNT} tagged numeric columns, got {len(tagged)}: {sorted(tagged)}"
    )

    # Statistics root column check
    stats_col = Base.metadata.tables["statistics"].columns["tg_id"]
    assert stats_col.info.get("tg_id") == "user"
    assert "statistics.tg_id" in _declared_columns()["identity"]


def test_encoded_locations_have_unique_owner_and_migration_kind() -> None:
    assert {location.column for location in ENCODED_TG_ID_LOCATIONS} == {
        "used_by",
        "audience",
    }
    assert all(
        location.domain in PARTICIPATING_DOMAINS for location in ENCODED_TG_ID_LOCATIONS
    )
    assert all(
        location.kind in {"prefix", "json_path"} for location in ENCODED_TG_ID_LOCATIONS
    )


def test_unmarked_synthetic_tg_column_is_rejected() -> None:
    meta = MetaData()
    Table("fake_table", meta, Column("foo_tg_id", Integer), info={"domain": "identity"})
    with pytest.raises(
        AssertionError,
        match="Suspicious column lacks explicit tg_id metadata: fake_table.foo_tg_id",
    ):
        validate_tg_rebind_coverage(metadata=meta, declarations={"identity": set()})


def test_marked_but_undeclared_synthetic_column_is_rejected() -> None:
    meta = MetaData()
    Table(
        "fake_table",
        meta,
        Column("new_tg_id", Integer, info={"tg_id": "user"}),
        info={"domain": "identity"},
    )
    with pytest.raises(
        AssertionError,
        match="fake_table.new_tg_id is marked as user but not in identity.REASSIGNED_TG_ID_COLUMNS",
    ):
        validate_tg_rebind_coverage(metadata=meta, declarations={"identity": set()})


def test_unsupported_label_is_rejected() -> None:
    meta = MetaData()
    Table(
        "fake_table",
        meta,
        Column("foo_tg_id", Integer, info={"tg_id": "player"}),
        info={"domain": "identity"},
    )
    with pytest.raises(
        AssertionError, match="Unsupported tg_id label 'player' on fake_table.foo_tg_id"
    ):
        validate_tg_rebind_coverage(metadata=meta, declarations={"identity": set()})


def test_invented_nonexistent_column_is_rejected() -> None:
    decls = {
        **_declared_columns(),
        "identity": _declared_columns()["identity"] | {"nonexistent_table.some_col"},
    }
    with pytest.raises(
        AssertionError, match="identity declared nonexistent table nonexistent_table"
    ):
        validate_tg_rebind_coverage(declarations=decls)


def test_foreign_key_to_statistics_detected_as_suspicious() -> None:
    meta = MetaData()
    Table(
        "statistics",
        meta,
        Column("tg_id", Integer, primary_key=True, info={"tg_id": "user"}),
        info={"domain": "identity"},
    )
    Table(
        "user_reference",
        meta,
        Column("account_ref", Integer, ForeignKey("statistics.tg_id")),
        info={"domain": "identity"},
    )
    with pytest.raises(
        AssertionError,
        match="Suspicious column lacks explicit tg_id metadata: user_reference.account_ref",
    ):
        validate_tg_rebind_coverage(
            metadata=meta, declarations={"identity": {"statistics.tg_id"}}
        )
