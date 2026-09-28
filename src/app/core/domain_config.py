"""Typed, database-backed business configuration.

A :class:`DomainConfig` owns the cache and validation policy for one domain's
configuration model.  The storage strategies deliberately depend only on the
small transactional API in :mod:`app.core.kv`; callers never need to know
whether a configuration is represented by one JSON document or by independent
field rows.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.core import kv
from app.core.db import get_session, register_post_commit
from app.core.log import logger

M = TypeVar("M", bound=BaseModel)
_MISSING = object()


@dataclass(frozen=True)
class SeedReport:
    """Result of inserting only the missing rows for one configuration."""

    name: str
    inserted: int
    existing: int


@dataclass(frozen=True)
class LegacySource:
    """Describe one legacy value used while seeding a configuration.

    ``reader`` is intentionally small: task 3 supplies the environment source
    and keeps its parsing rules outside this core module.
    """

    key: str
    reader: Callable[[str], Any]

    def read(self) -> Any:
        return self.reader(self.key)


@dataclass(frozen=True)
class FieldSpec:
    """Storage key and codec for one ``FieldRows`` field."""

    key: str | None = None
    encode: Callable[[Any], str] = lambda value: json.dumps(
        value, ensure_ascii=False, separators=(",", ":")
    )
    decode: Callable[[str], Any] = json.loads


class ConfigStorage(Protocol[M]):
    """Storage strategy used by :class:`DomainConfig`."""

    def read_tx(self, session, model: type[M], default: M) -> M | None: ...

    def ensure_tx(self, session, model: type[M], default: M) -> tuple[M, int]: ...

    def update_tx(
        self, session, model: type[M], default: M, changes: Mapping[str, Any]
    ) -> M: ...

    def seed_tx(self, session, model: type[M], default: M) -> int: ...


class JsonDocument(Generic[M]):
    """Store a model as one JSON document in one ``SystemConfig`` row."""

    def __init__(
        self,
        config_type: str,
        config_key: str,
        *,
        merge: Callable[[dict[str, Any], Mapping[str, Any]], dict[str, Any]]
        | None = None,
    ) -> None:
        self.config_type = config_type
        self.config_key = config_key
        self.merge = merge or self._shallow_merge

    @staticmethod
    def _shallow_merge(
        document: dict[str, Any], changes: Mapping[str, Any]
    ) -> dict[str, Any]:
        merged = dict(document)
        merged.update(changes)
        return merged

    @staticmethod
    def _dump(model: BaseModel) -> str:
        return json.dumps(
            model.model_dump(mode="python"),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _decode(self, raw: str, model: type[M], default: M) -> M:
        try:
            document = json.loads(raw)
            if not isinstance(document, dict):
                raise TypeError("configuration document must be a JSON object")
            return model.model_validate(document)
        except (TypeError, ValueError, ValidationError) as error:
            logger.error(
                "配置文档无法解析 (type=%s, key=%s): %s",
                self.config_type,
                self.config_key,
                error,
            )
            return default.model_copy(deep=True)

    def read_tx(self, session, model: type[M], default: M) -> M | None:
        raw = kv.get_tx(session, self.config_type, self.config_key)
        if raw is None:
            return None
        return self._decode(raw, model, default)

    def ensure_tx(self, session, model: type[M], default: M) -> tuple[M, int]:
        raw = kv.get_tx(session, self.config_type, self.config_key)
        if raw is not None:
            return self._decode(raw, model, default), 0
        stored = kv.insert_if_absent_tx(
            session, self.config_type, self.config_key, self._dump(default)
        )
        return self._decode(stored, model, default), 1

    def update_tx(
        self, session, model: type[M], default: M, changes: Mapping[str, Any]
    ) -> M:
        raw = kv.get_tx(session, self.config_type, self.config_key, for_update=True)
        if raw is None:
            current = default.model_dump(mode="python")
        else:
            current_model = self._decode(raw, model, default)
            current = current_model.model_dump(mode="python")
        updated = model.model_validate(self.merge(current, changes))
        kv.upsert_tx(session, self.config_type, self.config_key, self._dump(updated))
        return updated

    def seed_tx(self, session, model: type[M], default: M) -> int:
        _, inserted = self.ensure_tx(session, model, default)
        return inserted


class FieldRows(Generic[M]):
    """Store each model field in an independently upserted configuration row."""

    def __init__(
        self,
        config_type: str,
        fields: Mapping[str, FieldSpec] | None = None,
    ) -> None:
        self.config_type = config_type
        self.fields = dict(fields or {})

    def _spec(self, field: str) -> FieldSpec:
        return self.fields.get(field, FieldSpec())

    def _key(self, field: str) -> str:
        return self._spec(field).key or field

    def _decode_field(self, field: str, raw: str, default: Any) -> Any:
        try:
            return self._spec(field).decode(raw)
        except (TypeError, ValueError, ValidationError) as error:
            logger.error(
                "配置字段无法解析 (type=%s, key=%s): %s",
                self.config_type,
                self._key(field),
                error,
            )
            return default

    def _read_values(self, session, model: type[M], default: M) -> tuple[dict, int]:
        values = default.model_dump(mode="python")
        present = 0
        for field in model.model_fields:
            raw = kv.get_tx(session, self.config_type, self._key(field))
            if raw is None:
                continue
            present += 1
            values[field] = self._decode_field(field, raw, values[field])
        return values, present

    def read_tx(self, session, model: type[M], default: M) -> M | None:
        values, present = self._read_values(session, model, default)
        if not present:
            return None
        try:
            return model.model_validate(values)
        except ValidationError as error:
            logger.error("配置字段校验失败 (type=%s): %s", self.config_type, error)
            return default.model_copy(deep=True)

    def ensure_tx(self, session, model: type[M], default: M) -> tuple[M, int]:
        values, present = self._read_values(session, model, default)
        inserted = 0
        for field in model.model_fields:
            if kv.get_tx(session, self.config_type, self._key(field)) is not None:
                continue
            stored = kv.insert_if_absent_tx(
                session,
                self.config_type,
                self._key(field),
                self._spec(field).encode(values[field]),
            )
            values[field] = self._decode_field(field, stored, values[field])
            inserted += 1
        if not present and inserted == 0:
            return default.model_copy(deep=True), 0
        try:
            return model.model_validate(values), inserted
        except ValidationError as error:
            logger.error("配置字段校验失败 (type=%s): %s", self.config_type, error)
            return default.model_copy(deep=True), inserted

    def update_tx(
        self, session, model: type[M], default: M, changes: Mapping[str, Any]
    ) -> M:
        current = self.read_tx(session, model, default) or default
        values = current.model_dump(mode="python")
        values.update(changes)
        updated = model.model_validate(values)
        for field in changes:
            spec = self._spec(field)
            kv.upsert_tx(
                session,
                self.config_type,
                self._key(field),
                spec.encode(getattr(updated, field)),
            )
        return updated

    def seed_tx(self, session, model: type[M], default: M) -> int:
        _, inserted = self.ensure_tx(session, model, default)
        return inserted


class DomainConfig(Generic[M]):
    """Typed configuration declaration with transactional storage and TTL cache."""

    def __init__(
        self,
        name: str,
        model: type[M],
        storage: ConfigStorage[M],
        legacy: Mapping[str, LegacySource | Callable[[], Any]] | None = None,
        ttl_seconds: float = 30,
        default: M | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.storage = storage
        self.legacy = dict(legacy or {})
        self.ttl_seconds = float(ttl_seconds)
        self.default = default.model_copy(deep=True) if default is not None else None
        self._cache: tuple[float, M] | None = None
        self._cache_lock = RLock()

    def _legacy_value(self, field: str) -> Any:
        source = self.legacy.get(field)
        if source is None:
            return _MISSING
        if isinstance(source, LegacySource):
            return source.read()
        if callable(source):
            return source()
        reader = getattr(source, "read", None)
        if callable(reader):
            return reader()
        getter = getattr(source, "get", None)
        if callable(getter):
            return getter(field)
        return _MISSING

    def _default(self) -> M:
        base = (
            self.default.model_copy(deep=True)
            if self.default is not None
            else self.model()
        )
        values = base.model_dump(mode="python")
        for field in self.model.model_fields:
            value = self._legacy_value(field)
            if value is not _MISSING:
                values[field] = value
        return self.model.model_validate(values)

    def _cached(self) -> M | None:
        with self._cache_lock:
            if self._cache is None:
                return None
            timestamp, value = self._cache
            if time.monotonic() - timestamp > self.ttl_seconds:
                self._cache = None
                return None
            return value.model_copy(deep=True)

    def _cache_value(self, value: M) -> None:
        with self._cache_lock:
            self._cache = (time.monotonic(), value.model_copy(deep=True))

    def invalidate(self) -> None:
        with self._cache_lock:
            self._cache = None

    def _cache_after_commit(self, session, value: M) -> None:
        register_post_commit(
            session,
            f"domain-config:{self.name}",
            lambda: self._cache_value(value),
        )

    def invalidate_after_commit(self, session) -> None:
        """Invalidate this declaration after a caller-owned transaction commits."""
        register_post_commit(
            session,
            f"domain-config:{self.name}",
            self.invalidate,
        )

    def get_tx(self, session) -> M:
        cached = self._cached()
        if cached is not None:
            return cached
        default = self._default()
        value, inserted = self.storage.ensure_tx(session, self.model, default)
        if inserted:
            self._cache_after_commit(session, value)
        else:
            self._cache_value(value)
        return value.model_copy(deep=True)

    def get(self) -> M:
        with get_session() as session:
            return self.get_tx(session)

    def update(self, **changes: Any) -> M:
        unknown = set(changes) - set(self.model.model_fields)
        if unknown:
            raise ValueError(f"未知配置字段: {', '.join(sorted(unknown))}")
        default = self._default()
        with get_session() as session:
            value = self.storage.update_tx(session, self.model, default, changes)
        self.invalidate()
        return value.model_copy(deep=True)

    def seed(self) -> SeedReport:
        default = self._default()
        with get_session() as session:
            inserted = self.storage.seed_tx(session, self.model, default)
        if inserted:
            self.invalidate()
        return SeedReport(
            name=self.name,
            inserted=inserted,
            existing=len(self.model.model_fields) - inserted,
        )


__all__ = [
    "ConfigStorage",
    "DomainConfig",
    "FieldRows",
    "FieldSpec",
    "JsonDocument",
    "LegacySource",
    "SeedReport",
]
