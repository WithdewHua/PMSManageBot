"""领域配置 JSON 文档存储的事务内读写与条件更新。

`compare_and_update_tx` 是转盘“下一次生成特权码”开关的并发保护：只有在配置行
锁内把开关从真改成假的那一次调用返回真。
"""

from __future__ import annotations

import json

from sqlalchemy import event, select

from app.core.db import get_session
from app.core.kv import SystemConfig, compare_and_update_tx, get_tx, upsert_tx
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
