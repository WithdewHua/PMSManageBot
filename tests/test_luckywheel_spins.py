"""转盘的现行行为：付费单抽、免费次数单抽、十连、各类奖品与状态查询。

这些用例在提升之前固定当前实现的结果，提升后用同一批断言比对
（`promote-activity-domains` 任务 1.2）。外部副作用（管理员/群通知、媒体
权限同步）替换成 no-op；邀请码生成与配置保存用替身记录调用。
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import event, select
from starlette.requests import Request

from app.core.db import get_session
from app.core.schemas import TelegramUser
from app.domains.blackjack import repository as blackjack_repository
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.invitation import repository as invitation_repository
from app.domains.luckywheel import exceptions as luckywheel_exceptions
from app.domains.luckywheel import notifications as luckywheel_notifications
from app.domains.luckywheel import router as lw
from app.domains.luckywheel import rules as luckywheel_rules
from app.domains.luckywheel import service as luckywheel_service
from app.domains.luckywheel.models import LuckywheelFreeSpin, WheelStats
from app.domains.luckywheel.schemas import (
    LuckyWheelConfig,
    LuckyWheelConfigUpdateRequest,
    LuckyWheelItem,
)
from app.domains.premium import service as premium_service
from tests.conftest import add_user, next_id


def _assign_row_id(mapper, connection, target) -> None:  # pragma: no cover - hook
    if target.id is None:
        target.id = next_id()


# SQLite 上 BIGINT 主键不自增，抽奖统计由 router 隐式插入
event.listen(WheelStats, "before_insert", _assign_row_id)


DOMAINS_ITEMS = [
    LuckyWheelItem(name="谢谢参与", probability=15.0),
    LuckyWheelItem(name="积分 +10", probability=25.0),
    LuckyWheelItem(name="积分 -10", probability=20.0),
    LuckyWheelItem(name="积分 +30", probability=15.0),
    LuckyWheelItem(name="积分 -30", probability=10.0),
    LuckyWheelItem(name="邀请码 1 枚", probability=0.3),
    LuckyWheelItem(name="积分 +50", probability=7.0),
    LuckyWheelItem(name="积分 -50", probability=6.0),
    LuckyWheelItem(name="积分翻倍", probability=1.0),
    LuckyWheelItem(name="积分减半", probability=0.7),
]


def _user(tg_id: int) -> TelegramUser:
    return TelegramUser(id=tg_id, first_name=f"u{tg_id}", username=f"u{tg_id}")


def _request() -> Request:
    """需要认证装饰器的接口需要一个带 telegram_data 的真实请求。"""
    request = Request({"type": "http", "method": "POST", "path": "/api", "headers": []})
    request.state.telegram_data = {}
    return request


def _config(**overrides) -> LuckyWheelConfig:
    base = {
        "items": list(DOMAINS_ITEMS),
        "cost_credits": 10,
        "min_credits_required": 30,
        "gen_privileged_code": False,
    }
    base.update(overrides)
    return LuckyWheelConfig(**base)


@pytest.fixture
def wheel_env(orm, monkeypatch):
    """统一的替身：外部通知、媒体同步、配置读写、邀请码生成。"""

    async def _noop(*args, **kwargs):
        return None

    state: dict[str, object] = {
        "config": _config(),
        "saved": [],
        "codes": [],
    }

    monkeypatch.setattr(luckywheel_notifications, "send_message_by_url", _noop)
    monkeypatch.setattr(
        luckywheel_notifications, "get_user_name_from_tg_id", lambda chat_id: "user"
    )
    monkeypatch.setattr(
        premium_service, "sync_premium_media_access", lambda *a, **k: None
    )
    monkeypatch.setattr(lw, "get_wheel_config", lambda: state["config"])
    monkeypatch.setattr(luckywheel_service, "get_wheel_config", lambda: state["config"])
    monkeypatch.setattr(
        lw, "save_wheel_config", lambda config: state["saved"].append(config)
    )

    def _issue_codes(session, tg_id, count, *, privileged=False):
        state["codes"].append(
            {"tg_id": tg_id, "num": count, "is_privileged": privileged}
        )
        return [f"test-code-{len(state['codes'])}"]

    monkeypatch.setattr(invitation_repository, "issue_codes_tx", _issue_codes)
    monkeypatch.setattr(
        invitation_repository, "persist_privileged_codes_tx", lambda codes: None
    )
    return state


def _force_prize(monkeypatch, name: str) -> None:
    item = LuckyWheelItem(name=name, probability=100.0)
    monkeypatch.setattr(
        luckywheel_rules,
        "pick_prize",
        lambda items, user_id=None, randomness=None: item,
    )


def _credits(tg_id: int) -> float:
    with get_session() as session:
        row = session.get(Statistics, int(tg_id))
        assert row is not None
        return float(row.credits)


def _wheel_records() -> list[dict]:
    with get_session() as session:
        rows = (
            session.execute(select(WheelStats).order_by(WheelStats.id)).scalars().all()
        )
        return [
            {
                "tg_id": int(row.tg_id),
                "item_name": row.item_name,
                "cost_credits": float(row.cost_credits),
                "credits_change": float(row.credits_change),
                "source": row.source,
            }
            for row in rows
        ]


def _grant_free_spin(tg_id: int, *, spin_id: int = 1) -> None:
    now_ms = int(time.time() * 1000)
    with get_session() as session:
        session.add(
            LuckywheelFreeSpin(
                id=spin_id,
                tg_id=int(tg_id),
                source="blackjack",
                cost_credits_snapshot=0,
                wheel_stats_source="blackjack_free",
                granted_at_ms=now_ms - 1000,
                expires_at_ms=now_ms + 100_000,
                used_at_ms=None,
            )
        )


def _free_spin_row(spin_id: int = 1) -> dict | None:
    """返回普通字典：会话关闭后 ORM 实例会脱离，惰性刷新会抛错。"""
    with get_session() as session:
        row = session.get(LuckywheelFreeSpin, int(spin_id))
        if row is None:
            return None
        return {
            "id": int(row.id),
            "used_at_ms": row.used_at_ms,
            "wheel_stats_source": row.wheel_stats_source,
            "cost_credits_snapshot": float(row.cost_credits_snapshot),
        }


async def _spin(tg_id: int):
    return await lw.spin_wheel(
        request=_request(),
        background_tasks=BackgroundTasks(),
        current_user=_user(tg_id),
    )


# --------------------------------------------------------------------------- #
# 付费单抽
# --------------------------------------------------------------------------- #


async def test_paid_single_spin_charges_cost_and_applies_prize(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=100.0)
    _force_prize(monkeypatch, "积分 +30")

    result = await _spin(1)

    assert result.item.name == "积分 +30"
    assert result.credits_change == 30.0
    assert result.current_credits == 120.0
    assert result.used_free_spin is False
    assert result.free_spin_source is None
    assert _credits(1) == 120.0
    assert _wheel_records() == [
        {
            "tg_id": 1,
            "item_name": "积分 +30",
            "cost_credits": 10.0,
            "credits_change": 30.0,
            "source": "paid",
        }
    ]


async def test_paid_single_spin_truncates_negative_balance_at_zero(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=35.0)
    _force_prize(monkeypatch, "积分 -50")

    result = await _spin(1)

    # 35 - 10 = 25，再减 50 触底为 0；实际生效的变化是被截断后的 -25
    assert result.credits_change == -25.0
    assert result.current_credits == 0.0
    assert _credits(1) == 0.0
    assert _wheel_records()[0]["credits_change"] == -25.0


async def test_single_spin_rejects_below_minimum_credits(orm, wheel_env) -> None:
    add_user(orm, 2, credits=5.0)

    with pytest.raises(HTTPException) as excinfo:
        await _spin(2)

    assert excinfo.value.status_code == 400
    assert "需要至少 30 积分" in str(excinfo.value.detail)


# --------------------------------------------------------------------------- #
# 免费次数单抽
# --------------------------------------------------------------------------- #


async def test_free_spin_single_spin_skips_cost_and_marks_ledger(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=5.0)
    _grant_free_spin(1)
    _force_prize(monkeypatch, "积分 +10")

    result = await _spin(1)

    assert result.used_free_spin is True
    assert result.free_spin_source == "blackjack"
    assert result.credits_change == 10.0
    assert result.current_credits == 15.0
    assert _credits(1) == 15.0  # 未扣参与费
    row = _free_spin_row(1)
    assert row is not None and row["used_at_ms"] is not None
    assert _wheel_records()[0]["source"] == "blackjack_free"
    assert _wheel_records()[0]["cost_credits"] == 0.0


async def test_free_spin_is_released_when_the_spin_fails(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=5.0)
    _grant_free_spin(1)

    async def _boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(luckywheel_service, "spin", _boom)

    with pytest.raises(HTTPException) as excinfo:
        await _spin(1)

    assert excinfo.value.status_code == 500
    row = _free_spin_row(1)
    assert row is not None and row["used_at_ms"] is None  # 补偿释放
    assert _credits(1) == 5.0


# --------------------------------------------------------------------------- #
# 十连
# --------------------------------------------------------------------------- #


async def test_ten_spin_charges_ten_participation_fees(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=1000.0)
    _force_prize(monkeypatch, "积分 +10")

    result = await lw.spin_wheel_ten_times(
        request=_request(), background_tasks=BackgroundTasks(), current_user=_user(1)
    )

    assert len(result.results) == 10
    assert result.total_credits_change == 100.0
    assert result.current_credits == 1000.0
    records = _wheel_records()
    assert len(records) == 10
    assert {record["cost_credits"] for record in records} == {10.0}
    assert {record["source"] for record in records} == {"paid"}


async def test_ten_spin_does_not_consume_free_spins(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=1000.0)
    _grant_free_spin(1)
    _force_prize(monkeypatch, "积分 +10")

    await lw.spin_wheel_ten_times(
        request=_request(), background_tasks=BackgroundTasks(), current_user=_user(1)
    )

    row = _free_spin_row(1)
    assert row is not None and row["used_at_ms"] is None


async def test_ten_spin_requires_ten_times_the_threshold(orm, wheel_env) -> None:
    add_user(orm, 2, credits=100.0)
    with pytest.raises(HTTPException) as excinfo:
        await lw.spin_wheel_ten_times(
            request=_request(),
            background_tasks=BackgroundTasks(),
            current_user=_user(2),
        )

    assert excinfo.value.status_code == 400
    assert "十连抽需要至少 400 积分" in str(excinfo.value.detail)


# --------------------------------------------------------------------------- #
# 各类奖品
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("prize", "expected_change"),
    [
        ("积分 +10", 10.0),
        ("积分 -10", -10.0),
        ("积分翻倍", 90.0),
        ("积分减半", -45.0),
        ("谢谢参与", 0.0),
    ],
)
async def test_credit_prizes_apply_expected_change(
    orm, wheel_env, monkeypatch, prize: str, expected_change: float
) -> None:
    add_user(orm, 1, credits=100.0)
    _force_prize(monkeypatch, prize)

    result = await _spin(1)

    assert result.credits_change == expected_change
    # 100 - 10 = 90 是进入奖品计算时的余额
    assert result.current_credits == 90.0 + expected_change


async def test_invite_code_prize_issues_a_normal_code(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=100.0)
    _force_prize(monkeypatch, "邀请码 1 枚")

    result = await _spin(1)

    assert result.credits_change == 0.0
    assert wheel_env["codes"] == [{"tg_id": 1, "num": 1, "is_privileged": False}]


async def test_privileged_toggle_is_consumed_by_exactly_one_code(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=100.0)
    wheel_env["config"] = _config(gen_privileged_code=True)
    _force_prize(monkeypatch, "邀请码 1 枚")

    await _spin(1)
    await _spin(1)

    assert [call["is_privileged"] for call in wheel_env["codes"]] == [True, False]
    # 第一次抽中后，事务内条件更新与本次请求配置副本都关闭开关
    assert wheel_env["config"].gen_privileged_code is False


async def test_premium_prize_is_skipped_for_unbound_accounts(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=100.0)
    _force_prize(monkeypatch, "Premium 7 天")

    result = await _spin(1)

    assert result.credits_change == 0.0
    with get_session() as session:
        assert session.execute(select(PlexUser)).scalars().all() == []
        assert session.execute(select(EmbyUser)).scalars().all() == []


async def test_premium_prize_extends_bound_accounts(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=100.0)
    with get_session() as session:
        session.add(
            PlexUser(
                plex_id=11,
                tg_id=1,
                plex_email="1@example.com",
                plex_username="plex1",
            )
        )
        session.add(EmbyUser(emby_username="emby1", emby_id="e1", tg_id=1))
    _force_prize(monkeypatch, "Premium 7 天")

    await _spin(1)

    with get_session() as session:
        plex = session.execute(select(PlexUser)).scalars().one()
        emby = session.execute(select(EmbyUser)).scalars().one()
        assert plex.is_premium == 1 and plex.premium_expiry_time
        assert emby.is_premium == 1 and emby.premium_expiry_time


# --------------------------------------------------------------------------- #
# 随机性统计与用户状态
# --------------------------------------------------------------------------- #


def test_randomness_stats_reports_rates_for_every_positive_item() -> None:
    items = [
        LuckyWheelItem(name="a", probability=70.0),
        LuckyWheelItem(name="b", probability=30.0),
    ]

    stats = lw.get_randomness_stats(items, iterations=40)

    assert set(stats) == {"a", "b"}
    assert stats["a"]["expected_rate"] == 70.0
    assert stats["b"]["expected_rate"] == 30.0
    total_wins = stats["a"]["win_count"] + stats["b"]["win_count"]
    assert total_wins == 40
    assert all(isinstance(stats[name]["is_fair"], bool) for name in stats)
    # 0 概率的奖品不参与统计
    assert (
        lw.get_randomness_stats(
            [LuckyWheelItem(name="c", probability=0.0)], iterations=5
        )
        == {}
    )


async def test_user_status_reports_participation_threshold(orm, wheel_env) -> None:
    add_user(orm, 1, credits=100.0)
    add_user(orm, 2, credits=10.0)

    rich = await lw.get_user_status(request=_request(), current_user=_user(1))
    poor = await lw.get_user_status(request=_request(), current_user=_user(2))

    assert rich == {
        "can_participate": True,
        "current_credits": 100.0,
        "min_credits_required": 30,
        "cost_credits": 10,
    }
    assert poor["can_participate"] is False


async def test_free_spins_summary_reports_progress(orm, wheel_env) -> None:
    add_user(orm, 1, credits=0.0)
    _grant_free_spin(1)
    with get_session() as session:
        session.get(Statistics, 1).blackjack_hands_since_freespin = 7

    summary = await lw.get_free_spins(request=_request(), current_user=_user(1))

    assert summary.enabled is True
    assert summary.available == 1
    assert summary.hands_since_freespin == 7
    assert summary.hand_threshold == 20
    assert summary.expires_at_ms_list


def test_service_validation_raises_typed_luckywheel_error() -> None:
    with pytest.raises(
        luckywheel_exceptions.LuckywheelError,
        match="奖品概率总和必须为 100%",
    ):
        luckywheel_service.update_wheel_config(
            LuckyWheelConfigUpdateRequest(
                items=[LuckyWheelItem(name="x", probability=50.0)]
            )
        )


async def test_free_spin_summary_reads_live_blackjack_threshold(orm, wheel_env) -> None:
    add_user(orm, 1, credits=0.0)
    config = blackjack_repository.get_blackjack_config_dict()
    config["freespins_hand_threshold"] = 7
    assert blackjack_repository.set_blackjack_config("config", json.dumps(config))

    summary = await lw.get_free_spins(request=_request(), current_user=_user(1))

    assert summary.enabled is True
    assert summary.hand_threshold == 7


async def test_spin_transaction_rolls_back_all_writes_when_statistics_fails(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=100.0)
    _force_prize(monkeypatch, "积分 +30")
    monkeypatch.setattr(
        luckywheel_service.repository,
        "add_wheel_spin_record_tx",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("stats failed")),
    )

    with pytest.raises(RuntimeError, match="stats failed"):
        await luckywheel_service.spin(1, config=wheel_env["config"])

    assert _credits(1) == 100.0
    assert _wheel_records() == []


async def test_free_spin_is_restored_by_transaction_rollback(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=5.0)
    _grant_free_spin(1)
    _force_prize(monkeypatch, "积分 +10")
    monkeypatch.setattr(
        luckywheel_service.repository,
        "add_wheel_spin_record_tx",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("stats failed")),
    )

    with pytest.raises(RuntimeError, match="stats failed"):
        await luckywheel_service.spin(1, config=wheel_env["config"])

    assert _credits(1) == 5.0
    row = _free_spin_row(1)
    assert row is not None and row["used_at_ms"] is None
    assert _wheel_records() == []


async def test_invitation_failure_rolls_back_fee_and_ledger(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=100.0)
    _force_prize(monkeypatch, "邀请码 1 枚")
    monkeypatch.setattr(
        invitation_repository,
        "issue_codes_tx",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("invite failed")),
    )

    with pytest.raises(RuntimeError, match="invite failed"):
        await luckywheel_service.spin(1, config=wheel_env["config"])

    assert _credits(1) == 100.0
    assert _wheel_records() == []


async def test_premium_failure_rolls_back_fee_and_ledger(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=100.0)
    _force_prize(monkeypatch, "Premium 7 天")
    monkeypatch.setattr(
        luckywheel_service.repository.premium_repository,
        "grant_premium_days_tx",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("premium failed")),
    )

    with pytest.raises(RuntimeError, match="premium failed"):
        await luckywheel_service.spin(1, config=wheel_env["config"])

    assert _credits(1) == 100.0
    assert _wheel_records() == []


async def test_notification_failure_does_not_undo_committed_spin(
    orm, wheel_env, monkeypatch
) -> None:
    add_user(orm, 1, credits=100.0)
    _force_prize(monkeypatch, "邀请码 1 枚")

    async def _notification_failure(*args, **kwargs):
        raise RuntimeError("notification failed")

    monkeypatch.setattr(
        luckywheel_notifications,
        "notify_invite_code_awarded",
        _notification_failure,
    )

    result = await luckywheel_service.spin(1, config=wheel_env["config"])

    assert result.item.name == "邀请码 1 枚"
    assert _credits(1) == 90.0
    assert len(_wheel_records()) == 1
