"""领域配置 JSON 文档存储的事务内读写与条件更新。

`compare_and_update_tx` 是转盘“下一次生成特权码”开关的并发保护：只有在配置行
锁内把开关从真改成假的那一次调用返回真。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import event, select

import app.core.kv as core_kv
from app.core.db import get_session
from app.core.kv import (
    SystemConfig,
    SystemConfigRepository,
    compare_and_update_tx,
    delete_tx,
    get,
    get_tx,
    insert_if_absent_tx,
    upsert_tx,
)
from tests.conftest import next_id


def _assign_row_id(mapper, connection, target) -> None:  # pragma: no cover - hook
    if target.id is None:
        target.id = next_id()


# SQLite 上 BIGINT 主键不自增
event.listen(SystemConfig, "before_insert", _assign_row_id)


def _seed(config_type: str, config_key: str, value: str) -> None:
    with get_session() as session:
        upsert_tx(session, config_type, config_key, value)


def test_get_tx_and_upsert_tx_round_trip(session_env) -> None:
    with get_session() as session:
        assert get_tx(session, "lucky_wheel", "config") is None
        upsert_tx(session, "lucky_wheel", "config", '{"a": 1}')

    with get_session() as session:
        assert get_tx(session, "lucky_wheel", "config") == '{"a": 1}'
        upsert_tx(session, "lucky_wheel", "config", '{"a": 2}')

    with get_session() as session:
        assert get_tx(session, "lucky_wheel", "config") == '{"a": 2}'
        assert len(session.execute(select(SystemConfig)).scalars().all()) == 1


def test_compare_and_update_only_writes_when_the_predicate_holds(session_env) -> None:
    _seed(
        "lucky_wheel",
        "config",
        json.dumps({"gen_privileged_code": True, "cost_credits": 10}),
    )

    with get_session() as session:
        updated = compare_and_update_tx(
            session,
            "lucky_wheel",
            "config",
            lambda document: document.get("gen_privileged_code") is True,
            gen_privileged_code=False,
        )
    assert updated is True

    with get_session() as session:
        # 只合并 changes 里的键，其余字段原样保留
        assert json.loads(get_tx(session, "lucky_wheel", "config")) == {
            "gen_privileged_code": False,
            "cost_credits": 10,
        }

    # 开关已被消费：第二个调用者读到假值后放弃，不再写库
    with get_session() as session:
        assert (
            compare_and_update_tx(
                session,
                "lucky_wheel",
                "config",
                lambda document: document.get("gen_privileged_code") is True,
                gen_privileged_code=False,
            )
            is False
        )


def test_compare_and_update_rejects_absent_and_unparseable_documents(
    session_env,
) -> None:
    with get_session() as session:
        assert (
            compare_and_update_tx(
                session, "lucky_wheel", "missing", lambda document: True, a=1
            )
            is False
        )

    _seed("lucky_wheel", "config", "not-json")
    with get_session() as session:
        assert (
            compare_and_update_tx(
                session, "lucky_wheel", "config", lambda document: True, a=1
            )
            is False
        )
        # 无法解析的原始内容保持不变
        assert get_tx(session, "lucky_wheel", "config") == "not-json"

    _seed("lucky_wheel", "list", "[1, 2]")
    with get_session() as session:
        assert (
            compare_and_update_tx(
                session, "lucky_wheel", "list", lambda document: True, a=1
            )
            is False
        )


class _BrokenSessionContext:
    def __enter__(self):
        raise RuntimeError("database unavailable")

    def __exit__(self, *_args):
        return False


def test_get_distinguishes_missing_value_from_read_error(
    session_env, monkeypatch
) -> None:
    assert get("lucky_wheel", "missing") is None

    monkeypatch.setattr(core_kv, "get_session", _BrokenSessionContext)
    with pytest.raises(RuntimeError, match="database unavailable"):
        get("lucky_wheel", "missing")
    assert SystemConfigRepository().get_system_config("lucky_wheel", "missing") is None


def test_insert_if_absent_returns_the_value_that_won_the_unique_key(
    session_env,
) -> None:
    with get_session() as session:
        assert insert_if_absent_tx(session, "domain", "field", "first") == "first"

    with get_session() as session:
        assert insert_if_absent_tx(session, "domain", "field", "second") == "first"
        assert get_tx(session, "domain", "field") == "first"


def test_delete_tx_is_idempotent_and_old_setter_uses_module_api(session_env) -> None:
    repository = SystemConfigRepository()
    assert repository.set_system_config("domain", "field", "value") is True

    with get_session() as session:
        assert delete_tx(session, "domain", "field") is True
    with get_session() as session:
        assert delete_tx(session, "domain", "field") is False
        assert get_tx(session, "domain", "field") is None
