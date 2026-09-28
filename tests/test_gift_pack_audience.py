"""礼包受众、用户入口、编辑约束与开始私信测试。

覆盖 add-gift-pack-audience-and-tasks 的 3.6、4.1--4.3、5.2 与 6.1。
条件计数器和 schema 的细节见 test_gift_pack_conditions.py。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from app.core.db import get_session
from app.domains.gift_pack import repository as gift_pack_repository
from app.domains.gift_pack import service as gift_pack_service
from app.domains.gift_pack.models import GiftPack, GiftPackUserState
from app.domains.identity.models import Statistics
from app.domains.luckywheel.models import WheelStats
from tests.conftest import add_user, next_id


# SQLite does not autoincrement BIGINT primary keys.  This listener is scoped to
# the test process and lets production paths insert pack/state/activity rows.
def _assign_bigint_id(mapper, connection, target) -> None:
    if target.id is None:
        target.id = next_id()


for _model in (GiftPack, GiftPackUserState, WheelStats):
    event.listen(_model, "before_insert", _assign_bigint_id)


def _pack(
    *,
    start_at: int,
    end_at: int,
    audience: list[dict] | None = None,
    requirements: list[dict] | None = None,
    task_end_at: int | None = None,
    total_quantity: int | None = None,
    max_prompt_count: int = 3,
    max_task_prompt_count: int = 2,
    notify_audience_on_start: int = 0,
    is_enabled: int = 1,
) -> GiftPack:
    now = int(time.time())
    return GiftPack(
        id=next_id(),
        title="受众测试礼包",
        description="测试描述",
        rewards=json.dumps([{"type": "credits", "amount": 10}], ensure_ascii=False),
        audience=json.dumps(audience, ensure_ascii=False)
        if audience is not None
        else None,
        requirements=(
            json.dumps(requirements, ensure_ascii=False)
            if requirements is not None
            else None
        ),
        total_quantity=total_quantity,
        claimed_count=0,
        start_at=start_at,
        end_at=end_at,
        task_end_at=task_end_at,
        max_prompt_count=max_prompt_count,
        max_task_prompt_count=max_task_prompt_count,
        notify_audience_on_start=notify_audience_on_start,
        is_enabled=is_enabled,
        expiry_notified=0,
        created_at=now,
        updated_at=now,
    )


def _add_pack(pack: GiftPack) -> int:
    with get_session() as session:
        session.add(pack)
        session.flush()
        return int(pack.id)


def _set_pack_json(pack_id: int, field: str, value: list[dict] | None) -> None:
    with get_session() as session:
        pack = session.get(GiftPack, pack_id)
        assert pack is not None
        setattr(
            pack,
            field,
            json.dumps(value, ensure_ascii=False) if value is not None else None,
        )


def _set_credits(tg_id: int, credits: float) -> None:
    with get_session() as session:
        stats = session.get(Statistics, tg_id)
        assert stats is not None
        stats.credits = credits


def _add_wheel_spin(tg_id: int, timestamp: int, source: str = "paid") -> None:
    with get_session() as session:
        session.add(
            WheelStats(
                id=next_id(),
                tg_id=tg_id,
                item_name="测试奖品",
                cost_credits=10,
                credits_change=1,
                timestamp=timestamp,
                date="1970-01-01",
                source=source,
            )
        )


def _state(pack_id: int, tg_id: int) -> GiftPackUserState | None:
    with get_session() as session:
        row = session.execute(
            select(GiftPackUserState).where(
                GiftPackUserState.pack_id == pack_id,
                GiftPackUserState.tg_id == tg_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return GiftPackUserState(
            id=row.id,
            pack_id=row.pack_id,
            tg_id=row.tg_id,
            claimed_at=row.claimed_at,
            reward_snapshot=row.reward_snapshot,
            last_prompted_at=row.last_prompted_at,
            prompt_count=row.prompt_count,
            audience_locked_at=row.audience_locked_at,
            task_prompt_count=row.task_prompt_count,
            last_task_prompted_at=row.last_task_prompted_at,
            start_dm_sent_at=row.start_dm_sent_at,
        )


def _pack_item(items: list[dict], pack_id: int) -> dict:
    return next(item for item in items if item["id"] == pack_id)


# ---------------------------------------------------------------------------
# Audience visibility and locking (OpenSpec 3.6, 4.1)


GIFT_PACK_CLOCK_MODULES = tuple(
    importlib.import_module(f"app.domains.gift_pack.repository.{topic}")
    for topic in ("conditions", "rewards", "packs", "claims", "notices")
)


def _advance_gift_pack_clock(monkeypatch, now: int) -> None:
    """只拨礼包子主题模块的时钟，不动全局 time 模块。"""
    for module in GIFT_PACK_CLOCK_MODULES:
        if hasattr(module, "time"):
            monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: now))


def test_include_and_exclude_audiences_are_live_and_claimed_packs_remain_visible(orm):
    now = int(time.time())
    add_user(orm, 1)
    add_user(orm, 2)
    add_user(orm, 3)
    include_id = _add_pack(
        _pack(
            start_at=now - 10,
            end_at=now + 3600,
            audience=[{"type": "user_list", "mode": "include", "tg_ids": [1, 2]}],
        )
    )
    exclude_id = _add_pack(
        _pack(
            start_at=now - 10,
            end_at=now + 3600,
            audience=[{"type": "user_list", "mode": "exclude", "tg_ids": [2]}],
        )
    )

    assert {item["id"] for item in gift_pack_repository.get_gift_packs_for_user(1)} == {
        include_id,
        exclude_id,
    }
    assert [item["id"] for item in gift_pack_repository.get_gift_packs_for_user(2)] == [
        include_id
    ]
    assert [item["id"] for item in gift_pack_repository.get_gift_packs_for_user(3)] == [
        exclude_id
    ]

    # A claimed item remains visible even when a live include list is edited.
    gift_pack_service.claim_gift_pack(include_id, 1)
    _set_pack_json(
        include_id,
        "audience",
        [{"type": "user_list", "mode": "include", "tg_ids": [2]}],
    )
    assert include_id in {
        item["id"] for item in gift_pack_repository.get_gift_packs_for_user(1)
    }


def test_non_list_audience_is_locked_by_prompt_and_survives_state_change(orm):
    now = int(time.time())
    add_user(orm, 1, credits=40)
    pack_id = _add_pack(
        _pack(
            start_at=now - 10,
            end_at=now + 3600,
            audience=[{"type": "credits", "max": 50}],
            requirements=[
                {"type": "wheel_spins", "min": 1, "window": {"kind": "pack"}}
            ],
        )
    )

    response = gift_pack_repository.prompt_check_gift_packs(1)
    assert response["packs"] == []
    assert [item["id"] for item in response["task_packs"]] == [pack_id]
    locked = _state(pack_id, 1)
    assert locked is not None
    assert locked.audience_locked_at is not None

    _set_credits(1, 140)
    _add_wheel_spin(1, now)
    item = _pack_item(gift_pack_repository.get_gift_packs_for_user(1), pack_id)
    assert item["status"] == "claimable"
    assert gift_pack_service.claim_gift_pack(pack_id, 1)["success"] is True


def test_list_membership_is_never_locked_even_after_non_list_audience_lock(orm):
    now = int(time.time())
    add_user(orm, 1, credits=40)
    pack_id = _add_pack(
        _pack(
            start_at=now - 10,
            end_at=now + 3600,
            audience=[
                {"type": "user_list", "mode": "include", "tg_ids": [1]},
                {"type": "credits", "max": 50},
            ],
        )
    )

    response = gift_pack_repository.prompt_check_gift_packs(1)
    assert [item["id"] for item in response["packs"]] == [pack_id]
    assert _state(pack_id, 1).audience_locked_at is not None

    _set_pack_json(
        pack_id,
        "audience",
        [
            {"type": "user_list", "mode": "include", "tg_ids": []},
            {"type": "credits", "max": 50},
        ],
    )
    assert pack_id not in {
        item["id"] for item in gift_pack_repository.get_gift_packs_for_user(1)
    }


def test_upcoming_audience_is_not_locked_and_is_rechecked_when_pack_starts(
    orm, monkeypatch
):
    now = int(time.time())
    add_user(orm, 1, credits=40)
    pack_id = _add_pack(
        _pack(
            start_at=now + 100,
            end_at=now + 1000,
            audience=[{"type": "credits", "max": 50}],
        )
    )

    item = _pack_item(gift_pack_repository.get_gift_packs_for_user(1), pack_id)
    assert item["status"] == "upcoming"
    assert _state(pack_id, 1) is None

    _set_credits(1, 100)
    _advance_gift_pack_clock(monkeypatch, now + 101)
    assert pack_id not in {
        item["id"] for item in gift_pack_repository.get_gift_packs_for_user(1)
    }
    assert _state(pack_id, 1) is None


# ---------------------------------------------------------------------------
# List progress, prompts, and claim-time rechecks (OpenSpec 4.1--4.3)


def test_list_returns_structured_progress_and_freezes_count_at_task_deadline(orm):
    now = int(time.time())
    add_user(orm, 1)
    task_end = now - 100
    pack_id = _add_pack(
        _pack(
            start_at=now - 1000,
            task_end_at=task_end,
            end_at=now + 1000,
            requirements=[
                {"type": "wheel_spins", "min": 5, "window": {"kind": "pack"}}
            ],
        )
    )
    for timestamp in (now - 900, now - 800):
        _add_wheel_spin(1, timestamp)
    for timestamp in (now - 50, now - 40, now - 30):
        _add_wheel_spin(1, timestamp)

    item = _pack_item(gift_pack_repository.get_gift_packs_for_user(1), pack_id)
    assert item["status"] == "in_progress"
    assert item["task_closed"] is True
    assert item["requirements"][0]["current"] == 2
    assert item["requirements"][0]["target"] == 5


def test_prompt_separates_task_and_claim_counts_and_throttles_each_class(orm):
    now = int(time.time())
    add_user(orm, 1, credits=20)
    pack_id = _add_pack(
        _pack(
            start_at=now - 10,
            end_at=now + 3600,
            requirements=[{"type": "credits", "min": 50}],
            max_task_prompt_count=2,
            max_prompt_count=2,
        )
    )

    first = gift_pack_repository.prompt_check_gift_packs(1)
    assert first["packs"] == []
    assert [item["id"] for item in first["task_packs"]] == [pack_id]
    assert _state(pack_id, 1).task_prompt_count == 1

    # Same-day task reminders are throttled, not duplicated.
    second = gift_pack_repository.prompt_check_gift_packs(1)
    assert second == {"packs": [], "task_packs": []}

    with get_session() as session:
        state = session.execute(
            select(GiftPackUserState).where(
                GiftPackUserState.pack_id == pack_id,
                GiftPackUserState.tg_id == 1,
            )
        ).scalar_one()
        state.last_task_prompted_at = now - 86400
    third = gift_pack_repository.prompt_check_gift_packs(1)
    assert [item["id"] for item in third["task_packs"]] == [pack_id]
    assert _state(pack_id, 1).task_prompt_count == 2

    # Reaching the task cap does not prevent a later claim reminder.
    _set_credits(1, 50)
    fourth = gift_pack_repository.prompt_check_gift_packs(1)
    assert [item["id"] for item in fourth["packs"]] == [pack_id]
    assert fourth["task_packs"] == []
    assert _state(pack_id, 1).prompt_count == 1


def test_task_prompt_limit_zero_and_claim_only_phase_suppress_task_prompt(orm):
    now = int(time.time())
    add_user(orm, 1, credits=20)
    zero_id = _add_pack(
        _pack(
            start_at=now - 10,
            end_at=now + 3600,
            requirements=[{"type": "credits", "min": 50}],
            max_task_prompt_count=0,
        )
    )
    closed_id = _add_pack(
        _pack(
            start_at=now - 1000,
            task_end_at=now - 10,
            end_at=now + 3600,
            requirements=[{"type": "credits", "min": 50}],
        )
    )

    response = gift_pack_repository.prompt_check_gift_packs(1)
    assert response["packs"] == []
    assert response["task_packs"] == []
    # Locking is independent of sending a reminder, including in claim-only.
    for pack_id in (zero_id, closed_id):
        state = _state(pack_id, 1)
        assert state is not None
        assert state.audience_locked_at is not None
        assert state.task_prompt_count == 0
        assert state.prompt_count == 0


def test_same_day_task_prompt_does_not_block_claim_prompt_after_user_qualifies(orm):
    now = int(time.time())
    add_user(orm, 1, credits=20)
    pack_id = _add_pack(
        _pack(
            start_at=now - 10,
            end_at=now + 3600,
            requirements=[{"type": "credits", "min": 50}],
        )
    )
    first = gift_pack_repository.prompt_check_gift_packs(1)
    assert [item["id"] for item in first["task_packs"]] == [pack_id]

    _set_credits(1, 50)
    second = gift_pack_repository.prompt_check_gift_packs(1)
    assert [item["id"] for item in second["packs"]] == [pack_id]
    assert _state(pack_id, 1).prompt_count == 1


def test_claim_rechecks_frozen_requirement_and_hides_pack_from_outside_audience(orm):
    now = int(time.time())
    add_user(orm, 1)
    add_user(orm, 2)
    pack_id = _add_pack(
        _pack(
            start_at=now - 1000,
            task_end_at=now - 100,
            end_at=now + 1000,
            audience=[{"type": "user_list", "mode": "include", "tg_ids": [1]}],
            requirements=[
                {"type": "wheel_spins", "min": 1, "window": {"kind": "pack"}}
            ],
        )
    )
    # The only spin happens after the frozen reference point.
    _add_wheel_spin(1, now - 50)

    with pytest.raises(ValueError, match="礼包不存在"):
        gift_pack_service.claim_gift_pack(pack_id, 2)
    with pytest.raises(ValueError):
        gift_pack_service.claim_gift_pack(pack_id, 1)

    with get_session() as session:
        pack = session.get(GiftPack, pack_id)
        assert pack is not None
        assert pack.claimed_count == 0
        assert (
            session.execute(
                select(GiftPackUserState).where(GiftPackUserState.pack_id == pack_id)
            ).scalar_one_or_none()
            is None
        )


# ---------------------------------------------------------------------------
# Post-start edit restrictions (OpenSpec 5.2)


def _started_edit_pack(orm, *, audience=None, requirements=None, task_end_at=None):
    now = int(time.time())
    add_user(orm, 1)
    return _add_pack(
        _pack(
            start_at=now - 10,
            end_at=now + 1000,
            audience=audience,
            requirements=requirements,
            task_end_at=task_end_at,
        )
    )


def test_started_pack_rejects_start_reward_and_requirement_structure_changes(orm):
    pack_id = _started_edit_pack(
        orm,
        requirements=[{"type": "wheel_spins", "min": 50}],
    )
    now = int(time.time())

    with pytest.raises(ValueError, match="start_at|开始时间"):
        gift_pack_repository.update_gift_pack(pack_id, start_at=now + 100)
    with pytest.raises(ValueError, match="奖励"):
        gift_pack_repository.update_gift_pack(
            pack_id, rewards=[{"type": "credits", "amount": 99}]
        )
    with pytest.raises(ValueError, match="requirements|领取条件"):
        gift_pack_repository.update_gift_pack(
            pack_id,
            requirements=[{"type": "blackjack_hands", "min": 50}],
        )


def test_started_pack_allows_lower_targets_but_rejects_higher_targets(orm):
    pack_id = _started_edit_pack(
        orm,
        requirements=[{"type": "wheel_spins", "min": 50}],
    )

    assert (
        gift_pack_repository.update_gift_pack(
            pack_id,
            requirements=[{"type": "wheel_spins", "min": 40}],
        )
        is True
    )
    with pytest.raises(ValueError, match="requirements|领取条件|目标"):
        gift_pack_repository.update_gift_pack(
            pack_id,
            requirements=[{"type": "wheel_spins", "min": 60}],
        )


def test_started_pack_allows_end_extension_and_list_membership_changes_only(orm):
    pack_id = _started_edit_pack(
        orm,
        audience=[
            {"type": "user_list", "mode": "include", "tg_ids": [1]},
            {"type": "credits", "max": 50},
        ],
    )

    assert (
        gift_pack_repository.update_gift_pack(pack_id, end_at=int(time.time()) + 2000)
        is True
    )
    assert (
        gift_pack_repository.update_gift_pack(
            pack_id,
            audience=[
                {"type": "user_list", "mode": "include", "tg_ids": [1, 2]},
                {"type": "credits", "max": 50},
            ],
        )
        is True
    )
    with pytest.raises(ValueError, match="audience|受众"):
        gift_pack_repository.update_gift_pack(
            pack_id,
            audience=[
                {"type": "user_list", "mode": "include", "tg_ids": [1, 2]},
                {"type": "credits", "max": 100},
            ],
        )


def test_started_pack_cannot_introduce_a_task_deadline(orm):
    pack_id = _started_edit_pack(
        orm,
        requirements=[{"type": "wheel_spins", "min": 1}],
    )

    with pytest.raises(ValueError, match="task_end_at|任务截止"):
        gift_pack_repository.update_gift_pack(
            pack_id, task_end_at=int(time.time()) + 100
        )


def test_started_pack_can_extend_or_clear_existing_task_deadline(orm):
    now = int(time.time())
    pack_id = _started_edit_pack(
        orm,
        requirements=[{"type": "wheel_spins", "min": 1}],
        task_end_at=now + 100,
    )

    assert gift_pack_repository.update_gift_pack(pack_id, task_end_at=now + 200) is True
    assert gift_pack_repository.update_gift_pack(pack_id, task_end_at=None) is True


# ---------------------------------------------------------------------------
# Start DMs (OpenSpec 6.1)


def test_start_dm_candidate_scan_marks_once_excludes_claimed_and_finds_new_members(orm):
    now = int(time.time())
    for tg_id, credits in ((1, 40), (2, 40), (3, 40), (4, 40), (5, 100)):
        add_user(orm, tg_id, credits=credits)
    pack_id = _add_pack(
        _pack(
            start_at=now - 10,
            end_at=now + 3600,
            audience=[
                {"type": "user_list", "mode": "include", "tg_ids": [1, 2, 3]},
                {"type": "credits", "max": 50},
            ],
            notify_audience_on_start=1,
        )
    )
    gift_pack_service.claim_gift_pack(pack_id, 2)

    first = gift_pack_repository.claim_gift_pack_start_dm_candidates(limit=200)
    assert {item["tg_id"] for item in first} == {1, 3}
    assert all(item["pack_id"] == pack_id for item in first)
    assert all("requirements_summary" in item for item in first)

    assert gift_pack_repository.claim_gift_pack_start_dm_candidates(limit=200) == []
    _set_pack_json(
        pack_id,
        "audience",
        [
            {"type": "user_list", "mode": "include", "tg_ids": [1, 2, 3, 4, 5]},
            {"type": "credits", "max": 50},
        ],
    )
    third = gift_pack_repository.claim_gift_pack_start_dm_candidates(limit=200)
    assert {item["tg_id"] for item in third} == {4}

    with get_session() as session:
        rows = (
            session.execute(
                select(GiftPackUserState).where(GiftPackUserState.pack_id == pack_id)
            )
            .scalars()
            .all()
        )
        sent = {row.tg_id for row in rows if row.start_dm_sent_at is not None}
        assert sent == {1, 3, 4}


def test_start_dm_router_requests_200_at_a_time_with_content_and_spacing(monkeypatch):
    router = importlib.import_module("app.domains.gift_pack.jobs")
    candidates = [
        {
            "pack_id": 1,
            "tg_id": 10,
            "title": "开始通知礼包",
            "rewards": [{"type": "credits", "amount": 10}],
            "requirements_summary": "礼包开始后付费转盘 20 次",
            "end_at": 200,
        },
        {
            "pack_id": 1,
            "tg_id": 11,
            "title": "开始通知礼包",
            "rewards": [{"type": "premium_days", "days": 7}],
            "requirements_summary": "需要 Premium 身份",
            "end_at": 200,
        },
    ]
    sent = []
    sleeps = []
    limits = []

    def claim_candidates(limit):
        limits.append(limit)
        return candidates

    monkeypatch.setattr(
        gift_pack_repository,
        "claim_gift_pack_start_dm_candidates",
        claim_candidates,
        raising=False,
    )

    async def fake_send_message(**kwargs):
        sent.append(kwargs)
        return True

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(router, "send_message_by_url", fake_send_message)
    monkeypatch.setattr(router.asyncio, "sleep", fake_sleep)

    asyncio.run(router.scan_gift_pack_start_dms())

    assert limits == [200]
    assert [message["chat_id"] for message in sent] == [10, 11]
    assert sleeps == [0.5]
    assert "开始通知礼包" in sent[0]["text"]
    assert "10 积分" in sent[0]["text"]
    assert "礼包开始后付费转盘 20 次" in sent[0]["text"]
    assert "打开小程序的礼包中心领取" in sent[0]["text"]


def test_get_list_never_writes_audience_lock_even_when_user_is_eligible(orm):
    now = int(time.time())
    add_user(orm, 1, credits=40)
    pack_id = _add_pack(
        _pack(
            start_at=now - 10,
            end_at=now + 3600,
            audience=[{"type": "credits", "max": 50}],
        )
    )

    assert (
        _pack_item(gift_pack_repository.get_gift_packs_for_user(1), pack_id)["status"]
        == "claimable"
    )
    assert _state(pack_id, 1) is None


def test_claim_rechecks_sliding_window_instead_of_trusting_previous_list(
    orm, monkeypatch
):
    now = int(time.time())
    add_user(orm, 1)
    pack_id = _add_pack(
        _pack(
            start_at=now - 8 * 86400,
            end_at=now + 3600,
            requirements=[
                {"type": "wheel_spins", "min": 1, "window": {"kind": "days", "days": 7}}
            ],
        )
    )
    _add_wheel_spin(1, now - 7 * 86400 + 3)
    assert (
        _pack_item(gift_pack_repository.get_gift_packs_for_user(1), pack_id)["status"]
        == "claimable"
    )

    # 只拨礼包子主题模块的时钟；不动全局 time 模块（SQLite、日志、pytest 都在用）
    _advance_gift_pack_clock(monkeypatch, now + 5)
    with pytest.raises(ValueError):
        gift_pack_service.claim_gift_pack(pack_id, 1)
    item = _pack_item(gift_pack_repository.get_gift_packs_for_user(1), pack_id)
    assert item["status"] == "in_progress"
    assert item["requirements"][0]["current"] == 0
    with get_session() as session:
        assert session.get(GiftPack, pack_id).claimed_count == 0


def test_started_pack_quantity_can_only_expand(orm):
    now = int(time.time())
    add_user(orm, 1)
    pack_id = _add_pack(_pack(start_at=now - 10, end_at=now + 1000, total_quantity=2))
    assert gift_pack_repository.update_gift_pack(pack_id, total_quantity=3) is True
    with pytest.raises(ValueError, match="份数|total_quantity"):
        gift_pack_repository.update_gift_pack(pack_id, total_quantity=2)
    assert gift_pack_repository.update_gift_pack(pack_id, total_quantity=None) is True
    with pytest.raises(ValueError, match="份数|total_quantity"):
        gift_pack_repository.update_gift_pack(pack_id, total_quantity=4)


def test_upcoming_pack_can_change_start_reward_and_condition_freely(orm):
    now = int(time.time())
    add_user(orm, 1)
    pack_id = _add_pack(
        _pack(
            start_at=now + 3600,
            end_at=now + 7200,
            requirements=[{"type": "wheel_spins", "min": 50}],
        )
    )

    assert (
        gift_pack_repository.update_gift_pack(
            pack_id,
            start_at=now + 1800,
            rewards=[{"type": "credits", "amount": 20}],
            requirements=[{"type": "blackjack_hands", "min": 10}],
        )
        is True
    )
    with get_session() as session:
        pack = session.get(GiftPack, pack_id)
        assert pack.start_at == now + 1800
        assert json.loads(pack.rewards)[0]["amount"] == 20
        assert json.loads(pack.requirements)[0]["type"] == "blackjack_hands"


def test_admin_references_and_deletion_guard(orm):
    """References must exist and a referenced pack cannot be deleted."""
    now = int(time.time())
    fields = {
        "title": "reference test",
        "rewards": [{"type": "credits", "amount": 1}],
        "start_at": now + 60,
        "end_at": now + 3600,
    }
    with pytest.raises(ValueError, match="勋章"):
        gift_pack_repository.create_gift_pack(
            **fields, requirements=[{"type": "badge", "badge_id": 999999}]
        )
    with pytest.raises(ValueError, match="礼包"):
        gift_pack_repository.create_gift_pack(
            **fields, requirements=[{"type": "claimed_pack", "pack_id": 999999}]
        )

    source_id = gift_pack_repository.create_gift_pack(**fields)
    with pytest.raises(ValueError, match="自身"):
        gift_pack_repository.update_gift_pack(
            source_id, requirements=[{"type": "claimed_pack", "pack_id": source_id}]
        )

    dependent_id = gift_pack_repository.create_gift_pack(
        **{**fields, "title": "dependent"},
        requirements=[
            {
                "type": "any_of",
                "items": [
                    {"type": "claimed_pack", "pack_id": source_id},
                    {"type": "premium", "state": "active"},
                ],
            }
        ],
    )
    with pytest.raises(ValueError, match=str(dependent_id)):
        gift_pack_repository.delete_gift_pack(source_id)
    assert gift_pack_repository.get_gift_pack_by_id(source_id) is not None


def test_admin_resolves_mixed_identifiers_and_rejects_ambiguous_match(orm, monkeypatch):
    from app.domains.identity.models import EmbyUser, PlexUser

    for tg_id in (1, 2, 3):
        add_user(orm, tg_id)
    with get_session() as session:
        session.add_all(
            [
                PlexUser(
                    plex_id=101,
                    tg_id=1,
                    plex_username="Alice",
                    plex_email="alice@example.com",
                ),
                PlexUser(
                    plex_id=103,
                    tg_id=3,
                    plex_username="shared",
                    plex_email="shared@example.com",
                ),
                EmbyUser(emby_username="SHARED", tg_id=2),
            ]
        )
    monkeypatch.setattr(
        "app.core.telegram.load_tg_user_info_cache",
        lambda: {2: {"username": "cached", "first_name": "Cached"}},
    )
    result = gift_pack_repository.resolve_gift_pack_users(
        "1, alice ALICE@example.com，shared\n@cached unknown 1"
    )
    by_token = {item["token"]: item for item in result["resolved"]}
    assert len([item for item in result["resolved"] if item["token"] == "1"]) == 1
    assert by_token["1"]["tg_id"] == 1
    assert by_token["alice"]["tg_id"] == 1
    assert by_token["ALICE@example.com"]["tg_id"] == 1
    assert by_token["@cached"]["tg_id"] == 2
    unresolved = {item["token"]: item["reason"] for item in result["unresolved"]}
    assert "多个" in unresolved["shared"]
    assert "未找到" in unresolved["unknown"]


def test_named_pack_stats_include_audience_rate_and_task_reminders(orm):
    for tg_id in (1, 2, 3):
        add_user(orm, tg_id)
    now = int(time.time())
    pack_id = gift_pack_repository.create_gift_pack(
        title="named stats",
        rewards=[{"type": "credits", "amount": 1}],
        start_at=now - 10,
        end_at=now + 3600,
        audience=[{"type": "user_list", "mode": "include", "tg_ids": [1, 2, 3]}],
    )
    gift_pack_service.claim_gift_pack(pack_id, 1)
    with get_session() as session:
        session.add(GiftPackUserState(pack_id=pack_id, tg_id=2, task_prompt_count=1))
    stats = gift_pack_repository.get_gift_pack_stats(pack_id)
    assert stats["claimed_users"] == 1
    assert stats["task_prompted_users"] == 1
    assert stats["audience_size"] == 3
    assert stats["claim_rate"] == 33.33
    listed = gift_pack_repository.get_gift_pack_by_id(pack_id)
    assert listed["audience_size"] == 3
    assert listed["claim_rate"] == 33.33
    assert listed["audience_summary"]


@pytest.mark.asyncio
async def test_admin_resolve_users_endpoint_requires_admin_and_returns_matches(
    orm, monkeypatch
):
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.core.schemas import TelegramUser
    from app.domains.gift_pack import router

    add_user(orm, 1)

    def check_admin(user):
        if user.id != 1:
            raise HTTPException(status_code=403, detail="仅管理员可用")

    monkeypatch.setattr(router, "check_admin_permission", check_admin)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/gift-packs/admin/resolve-users",
            "headers": [],
        }
    )
    request.state.telegram_data = {}
    result = await router.admin_resolve_gift_pack_users(
        request=request, text="1", telegram_user=TelegramUser(id=1, first_name="Admin")
    )
    assert result["resolved"][0]["tg_id"] == 1
    with pytest.raises(HTTPException) as denied:
        await router.admin_resolve_gift_pack_users(
            request=request,
            text="1",
            telegram_user=TelegramUser(id=2, first_name="Other"),
        )
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_create_accepts_all_seven_rewards_with_new_conditions(
    orm, monkeypatch
):
    from fastapi import BackgroundTasks
    from starlette.requests import Request

    from app.core.schemas import TelegramUser
    from app.domains.gift_pack import router
    from app.domains.gift_pack.schemas import GiftPackCreateRequest

    monkeypatch.setattr(router, "check_admin_permission", lambda user: None)
    now = int(time.time())
    data = GiftPackCreateRequest(
        title="全种类奖励礼包",
        start_at=now + 60,
        end_at=now + 3600,
        rewards=[
            {"type": "credits", "amount": 100},
            {"type": "premium_days", "days": 7},
            {"type": "wheel_free_spins", "count": 3, "expiry_days": 7},
            {"type": "tournament_wallet", "amount": 50},
            {"type": "invite_codes", "count": 2, "privileged": True},
            {"type": "line_schedule_unlock"},
            {"type": "download_unlock"},
        ],
        requirements=[{"type": "credits", "min": 1}],
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/gift-packs/admin",
            "headers": [],
        }
    )
    request.state.telegram_data = {}
    response = await router.admin_create_gift_pack(
        request=request,
        background_tasks=BackgroundTasks(),
        data=data,
        telegram_user=TelegramUser(id=1, first_name="Admin"),
    )
    assert len(response.rewards) == 7
    assert response.requirements is not None
    assert [item.type for item in response.requirements] == ["credits", "bound"]
    with get_session() as session:
        pack = session.get(GiftPack, response.id)
        assert pack.eligibility is None
        assert pack.max_task_prompt_count == 2
        assert json.loads(pack.requirements)[-1] == {"type": "bound", "service": "any"}


@pytest.mark.asyncio
async def test_admin_update_returns_post_start_violation_message(orm, monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.core.schemas import TelegramUser
    from app.domains.gift_pack import router
    from app.domains.gift_pack.schemas import GiftPackUpdateRequest

    now = int(time.time())
    pack_id = _add_pack(_pack(start_at=now - 10, end_at=now + 3600))
    monkeypatch.setattr(router, "check_admin_permission", lambda user: None)
    request = Request(
        {
            "type": "http",
            "method": "PUT",
            "path": f"/api/gift-packs/admin/{pack_id}",
            "headers": [],
        }
    )
    request.state.telegram_data = {}
    with pytest.raises(HTTPException) as rejected:
        await router.admin_update_gift_pack(
            request=request,
            pack_id=pack_id,
            data=GiftPackUpdateRequest(start_at=now - 5),
            telegram_user=TelegramUser(id=1, first_name="Admin"),
        )
    assert rejected.value.status_code == 400
    assert "start_at" in rejected.value.detail
    assert "可停用后新建" in rejected.value.detail


@pytest.mark.asyncio
async def test_admin_update_and_enabled_return_current_pack(orm, monkeypatch):
    from starlette.requests import Request

    from app.core.schemas import TelegramUser
    from app.domains.gift_pack import router
    from app.domains.gift_pack.schemas import (
        GiftPackSetEnabledRequest,
        GiftPackUpdateRequest,
    )

    now = int(time.time())
    pack_id = _add_pack(_pack(start_at=now + 60, end_at=now + 3600))
    monkeypatch.setattr(router, "check_admin_permission", lambda user: None)
    request = Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/api/gift-packs/admin",
            "headers": [],
        }
    )
    request.state.telegram_data = {}
    user = TelegramUser(id=1, first_name="Admin")
    updated = await router.admin_update_gift_pack(
        request=request,
        pack_id=pack_id,
        data=GiftPackUpdateRequest(title="updated"),
        telegram_user=user,
    )
    assert updated.title == "updated"
    assert updated.can_delete is True
    disabled = await router.admin_set_gift_pack_enabled(
        request=request,
        pack_id=pack_id,
        data=GiftPackSetEnabledRequest(is_enabled=False),
        telegram_user=user,
    )
    assert disabled.is_enabled is False
    assert disabled.can_delete is True


@pytest.mark.asyncio
async def test_claim_route_returns_structured_current_progress_on_recheck_failure(
    orm, monkeypatch
):
    from fastapi import BackgroundTasks, HTTPException
    from starlette.requests import Request

    from app.core.schemas import TelegramUser
    from app.domains.gift_pack import router

    add_user(orm, 1)
    now = int(time.time())
    pack_id = _add_pack(
        _pack(
            start_at=now - 60,
            end_at=now + 3600,
            requirements=[
                {"type": "wheel_spins", "min": 2, "window": {"kind": "pack"}}
            ],
        )
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/api/gift-packs/{pack_id}/claim",
            "headers": [],
        }
    )
    request.state.telegram_data = {}
    with pytest.raises(HTTPException) as rejected:
        await router.claim_gift_pack(
            request=request,
            pack_id=pack_id,
            background_tasks=BackgroundTasks(),
            telegram_user=TelegramUser(id=1, first_name="User"),
        )
    assert rejected.value.status_code == 400
    assert rejected.value.detail["message"] == "不满足领取条件"
    assert rejected.value.detail["requirements"][0]["current"] == 0
    assert rejected.value.detail["requirements"][0]["target"] == 2
    with get_session() as session:
        assert session.get(GiftPack, pack_id).claimed_count == 0


def test_prestart_reward_edit_can_explicitly_remove_auto_binding(orm):
    now = int(time.time())
    pack_id = gift_pack_repository.create_gift_pack(
        title="reward switch",
        rewards=[{"type": "premium_days", "days": 7}],
        start_at=now + 3600,
        end_at=now + 7200,
    )
    with get_session() as session:
        pack = session.get(GiftPack, pack_id)
        assert json.loads(pack.requirements) == [{"type": "bound", "service": "any"}]

    # An explicit empty list removes the binding requirement after switching to
    # a reward that does not need a media account. Other explicit bound
    # conditions must remain intact; the backend cannot infer their provenance.
    gift_pack_repository.update_gift_pack(
        pack_id,
        rewards=[{"type": "credits", "amount": 10}],
        requirements=[],
    )
    with get_session() as session:
        pack = session.get(GiftPack, pack_id)
        assert pack.requirements is None
        assert pack.eligibility is None


@pytest.mark.asyncio
async def test_prompt_endpoint_returns_task_packs_for_popup(orm, monkeypatch):
    from starlette.requests import Request

    from app.core.schemas import TelegramUser
    from app.domains.gift_pack import router

    add_user(orm, 1)
    now = int(time.time())
    pack_id = _add_pack(
        _pack(
            start_at=now - 60,
            end_at=now + 3600,
            max_task_prompt_count=2,
            requirements=[{"type": "credits", "min": 1000}],
        )
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/gift-packs/prompt-check",
            "headers": [],
        }
    )
    request.state.telegram_data = {}
    response = await router.prompt_check(
        request=request, telegram_user=TelegramUser(id=1, first_name="User")
    )
    assert response.packs == []
    assert [item.id for item in response.task_packs] == [pack_id]
    assert response.task_packs[0].requirements[0].target == 1000


def test_earlier_pack_prompt_does_not_suppress_new_task_pack(orm):
    now = int(time.time())
    add_user(orm, 1, credits=20)
    old_id = _add_pack(
        _pack(
            start_at=now - 3600,
            end_at=now + 3600,
            requirements=[{"type": "credits", "min": 50}],
            max_task_prompt_count=2,
        )
    )
    first = gift_pack_repository.prompt_check_gift_packs(1)
    assert [item["id"] for item in first["task_packs"]] == [old_id]

    new_id = _add_pack(
        _pack(
            start_at=now - 60,
            end_at=now + 3600,
            requirements=[{"type": "credits", "min": 100}],
            max_task_prompt_count=2,
        )
    )
    second = gift_pack_repository.prompt_check_gift_packs(1)
    assert second["packs"] == []
    assert [item["id"] for item in second["task_packs"]] == [new_id]
    assert _state(old_id, 1).task_prompt_count == 1
    assert _state(new_id, 1).task_prompt_count == 1


def test_prompt_returns_new_task_pack_after_an_earlier_pack_was_claimed(orm):
    now = int(time.time())
    add_user(orm, 1, credits=20)
    earlier_id = _add_pack(
        _pack(
            start_at=now - 3600,
            end_at=now + 3600,
            requirements=[{"type": "credits", "min": 10}],
            max_task_prompt_count=2,
        )
    )
    gift_pack_repository.prompt_check_gift_packs(1)
    gift_pack_service.claim_gift_pack(earlier_id, 1)

    task_id = _add_pack(
        _pack(
            start_at=now - 60,
            end_at=now + 3600,
            requirements=[{"type": "credits", "min": 100}],
            max_task_prompt_count=2,
        )
    )
    reminder = gift_pack_repository.prompt_check_gift_packs(1)
    assert reminder["packs"] == []
    assert [item["id"] for item in reminder["task_packs"]] == [task_id]


# ---------------------------------------------------------------- 管理端接口与错误分支


def _rename_pack(pack_id: int, title: str) -> None:
    with get_session() as session:
        pack = session.get(GiftPack, pack_id)
        assert pack is not None
        pack.title = title


async def _http_outcome(coro) -> tuple[int, object]:
    from fastapi import HTTPException

    try:
        await coro
    except HTTPException as exc:
        return exc.status_code, exc.detail
    raise AssertionError("expected HTTPException")


@pytest.mark.asyncio
async def test_admin_list_and_records_endpoints_report_rows_and_totals(
    orm, monkeypatch
):
    from starlette.requests import Request

    from app.core.schemas import TelegramUser
    from app.domains.gift_pack import router

    now = int(time.time())
    add_user(orm, 1)
    pack_id = _add_pack(_pack(start_at=now - 10, end_at=now + 3600))
    monkeypatch.setattr(router, "check_admin_permission", lambda user: None)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/gift-packs/admin/list",
            "headers": [],
        }
    )
    request.state.telegram_data = {}
    admin = TelegramUser(id=1, first_name="Admin")

    listing = await router.admin_list_gift_packs(
        request=request, page=1, page_size=20, telegram_user=admin
    )
    assert listing.total == 1
    assert [item.id for item in listing.packs] == [pack_id]
    assert listing.packs[0].can_delete is True

    gift_pack_service.claim_gift_pack(pack_id, 1)
    records = await router.admin_gift_pack_records(
        request=request, pack_id=pack_id, page=1, page_size=20, telegram_user=admin
    )
    assert records.total == 1
    assert records.records[0].tg_id == 1
    assert records.records[0].tg_username == "1"

    empty_page = await router.admin_gift_pack_records(
        request=request, pack_id=pack_id, page=2, page_size=20, telegram_user=admin
    )
    assert (empty_page.total, empty_page.records) == (1, [])

    missing_page = await router.admin_gift_pack_records(
        request=request, pack_id=999_999, page=1, page_size=20, telegram_user=admin
    )
    assert (missing_page.total, missing_page.records) == (0, [])


@pytest.mark.asyncio
async def test_delete_route_splits_404_and_400_despite_title_quirk(orm, monkeypatch):
    from starlette.requests import Request

    from app.core.schemas import TelegramUser
    from app.domains.gift_pack import router

    now = int(time.time())
    add_user(orm, 1)
    monkeypatch.setattr(router, "check_admin_permission", lambda user: None)
    request = Request(
        {
            "type": "http",
            "method": "DELETE",
            "path": "/api/gift-packs/admin/1",
            "headers": [],
        }
    )
    request.state.telegram_data = {}
    admin = TelegramUser(id=1, first_name="Admin")

    def delete(pack_id: int):
        return router.admin_delete_gift_pack(
            request=request, pack_id=pack_id, telegram_user=admin
        )

    # 不存在 → 404
    assert await _http_outcome(delete(999_999)) == (404, "礼包不存在")

    # 已有领取记录 → 400
    claimed = _add_pack(_pack(start_at=now - 10, end_at=now + 3600))
    gift_pack_service.claim_gift_pack(claimed, 1)
    assert await _http_outcome(delete(claimed)) == (
        400,
        "该礼包已有用户领取，只能停用不能删除",
    )

    # 被引用 → 400；引用者标题里含“不存在”也一样（design D8 记下的唯一行为差异）
    referenced = _add_pack(_pack(start_at=now - 10, end_at=now + 3600))
    referrer = _add_pack(
        _pack(
            start_at=now - 10,
            end_at=now + 3600,
            requirements=[{"type": "claimed_pack", "pack_id": referenced}],
        )
    )
    status, detail = await _http_outcome(delete(referenced))
    assert status == 400
    assert "被其他礼包的已领取条件引用" in str(detail)

    _rename_pack(referrer, "不存在的引用者")
    status, detail = await _http_outcome(delete(referenced))
    # 类型化异常按抛出点的状态码返回：被引用始终是 400，不再被标题里的
    # “不存在”带偏成 404（promote-gift-pack-domain design D8 的唯一差异）
    assert status == 400
    assert "引用" in str(detail)

    # 无引用 → 删除成功
    free_pack = _add_pack(_pack(start_at=now - 10, end_at=now + 3600))
    assert await delete(free_pack) == {"success": True, "message": "礼包已删除"}


@pytest.mark.asyncio
async def test_admin_error_branches_return_fixed_details(orm, monkeypatch):
    from fastapi import BackgroundTasks
    from starlette.requests import Request

    from app.core.schemas import TelegramUser
    from app.domains.gift_pack import router
    from app.domains.gift_pack.schemas import (
        GiftPackCreateRequest,
        GiftPackUpdateRequest,
    )

    now = int(time.time())
    add_user(orm, 1)
    pack_id = _add_pack(_pack(start_at=now - 10, end_at=now + 3600))
    monkeypatch.setattr(router, "check_admin_permission", lambda user: None)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/gift-packs/admin",
            "headers": [],
        }
    )
    request.state.telegram_data = {}
    admin = TelegramUser(id=1, first_name="Admin")
    background_tasks = BackgroundTasks()

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    cases = [
        (
            "获取礼包列表失败",
            "get_gift_packs_admin",
            lambda: router.admin_list_gift_packs(request=request, telegram_user=admin),
        ),
        (
            "获取领取记录失败",
            "get_gift_pack_claim_records",
            lambda: router.admin_gift_pack_records(
                request=request, pack_id=pack_id, telegram_user=admin
            ),
        ),
        (
            "解析名单失败",
            "resolve_gift_pack_users",
            lambda: router.admin_resolve_gift_pack_users(
                request=request, text="1", telegram_user=admin
            ),
        ),
        (
            "创建礼包失败",
            "create_gift_pack",
            lambda: router.admin_create_gift_pack(
                request=request,
                background_tasks=background_tasks,
                data=GiftPackCreateRequest(
                    title="x",
                    rewards=[{"type": "credits", "amount": 1}],
                    start_at=now - 10,
                    end_at=now + 3600,
                ),
                telegram_user=admin,
            ),
        ),
        (
            "编辑礼包失败",
            "update_gift_pack",
            lambda: router.admin_update_gift_pack(
                request=request,
                pack_id=pack_id,
                data=GiftPackUpdateRequest(description="x"),
                telegram_user=admin,
            ),
        ),
        (
            "删除礼包失败",
            "delete_gift_pack",
            lambda: router.admin_delete_gift_pack(
                request=request, pack_id=pack_id, telegram_user=admin
            ),
        ),
    ]
    for detail, method, call in cases:
        with monkeypatch.context() as patcher:
            patcher.setattr(gift_pack_repository, method, _boom)
            assert await _http_outcome(call()) == (500, detail)

    # 开屏提醒是锦上添花：失败时静默返回空列表，不抛 500
    with monkeypatch.context() as patcher:
        patcher.setattr(gift_pack_repository, "prompt_check_gift_packs", _boom)
        response = await router.prompt_check(request=request, telegram_user=admin)
    assert response.packs == []
    assert response.task_packs == []
