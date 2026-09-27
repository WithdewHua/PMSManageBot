"""``gift_pack.rules`` 的纯函数单元测试（OpenSpec 4.1）。

rules 只接受普通 dict 与模型快照，不做任何 I/O：这里逐条钉住旧格式条件的
解析、全部条件类型的求值、any_of 的进度、取数计划（含“礼包未开始不取数”），
以及生命周期、余量、受众规模、文案与开始后编辑校验。
"""

from __future__ import annotations

import pytest

from app.domains.gift_pack import rules
from app.domains.gift_pack.exceptions import GiftPackError
from app.domains.gift_pack.models import GiftPack, GiftPackUserState


def _pack(**overrides) -> GiftPack:
    values = {
        "id": 1,
        "title": "纯计算礼包",
        "rewards": "[]",
        "start_at": 100,
        "end_at": 1000,
        "task_end_at": 200,
        "total_quantity": 10,
        "claimed_count": 3,
        "is_enabled": 1,
    }
    values.update(overrides)
    return GiftPack(**values)


def _context(**overrides) -> dict:
    context = {
        "has_stats": True,
        "credits": 42.0,
        "bound_services": ["plex"],
        "premium_services": ["plex"],
        "badge_ids": {7},
        "claimed_pack_ids": {88},
        "_tg_id": 1,
    }
    context.update(overrides)
    return context


# ---------------------------------------------------------------------------
# 奖励登记表、文案与摘要


def test_reward_registry_labels_every_type() -> None:
    for reward_type in (
        "credits",
        "premium_days",
        "wheel_free_spins",
        "tournament_wallet",
        "invite_codes",
        "line_schedule_unlock",
        "download_unlock",
    ):
        assert reward_type in rules.GIFT_PACK_REWARD_TYPES

    assert (
        rules._gift_pack_reward_label({"type": "credits", "amount": 100}) == "100 积分"
    )
    assert (
        rules._gift_pack_reward_label({"type": "credits", "amount": 12.5})
        == "12.5 积分"
    )
    assert (
        rules._gift_pack_reward_label({"type": "premium_days", "days": 7})
        == "7 天 Premium"
    )
    assert (
        rules._gift_pack_reward_label(
            {"type": "invite_codes", "count": 2, "privileged": True}
        )
        == "2 枚特权邀请码"
    )
    assert rules._gift_pack_reward_label({"type": "unknown"}) == "unknown"


def test_binding_requirement_comes_from_the_registry() -> None:
    assert rules.gift_pack_rewards_require_binding([{"type": "credits"}]) is False
    assert (
        rules.gift_pack_rewards_require_binding([{"type": "download_unlock"}]) is True
    )
    assert rules._gift_pack_conditions_with_binding(
        [], [{"type": "credits"}, {"type": "download_unlock"}]
    ) == [{"type": "bound", "service": "any"}]
    # 已显式写了绑定条件时不重复追加
    explicit = [{"type": "bound", "service": "plex"}]
    assert (
        rules._gift_pack_conditions_with_binding(
            explicit, [{"type": "download_unlock"}]
        )
        == explicit
    )


def test_condition_summary_renders_every_family() -> None:
    summary = rules._gift_pack_condition_summary(
        [
            {"type": "credits", "min": 100},
            {"type": "premium", "state": "active"},
            {"type": "bound", "service": "plex"},
            {"type": "badge", "badge_id": 7},
            {"type": "claimed_pack", "pack_id": 88},
            {"type": "user_list", "mode": "include", "tg_ids": [1]},
            {"type": "wheel_spins", "min": 3, "window": {"kind": "all"}},
            {"type": "watched_hours", "min": 5, "window": {"kind": "all"}},
            {
                "type": "any_of",
                "items": [{"type": "credits", "min": 1}, {"type": "bound"}],
            },
        ]
    )
    assert "积分 ≥ 100" in summary
    assert "需要 Premium 身份" in summary
    assert "绑定 Plex 账号" in summary
    assert "持有勋章 #7" in summary
    assert "已领取礼包 #88" in summary
    assert "包含名单" in summary
    assert "付费转盘 3 次" in summary
    assert "累计观看时长（小时） 5 小时" in summary
    assert "或" in summary
    assert rules._gift_pack_condition_summary([]) == ""


def test_condition_labels_cover_every_type() -> None:
    for item in (
        {"type": "user_list", "mode": "exclude"},
        {"type": "credits", "min": 1},
        {"type": "premium", "state": "active"},
        {"type": "premium", "state": "inactive"},
        {"type": "bound", "service": "any"},
        {"type": "badge", "badge_id": 1},
        {"type": "claimed_pack", "pack_id": 1},
        {"type": "wheel_spins", "paid_only": False, "window": {"kind": "all"}},
        {"type": "blackjack_hands", "window": {"kind": "all"}},
        {"type": "treasure_issues", "window": {"kind": "days", "days": 3}},
        {"type": "prediction_bets", "window": {"kind": "pack"}},
        {"type": "auction_participations", "window": {"kind": "all"}},
        {"type": "tournament_entries", "window": {"kind": "all"}},
        {"type": "invitees", "window": {"kind": "all"}},
        {"type": "watched_hours", "window": {"kind": "all"}},
    ):
        assert isinstance(rules._gift_pack_condition_label(item), str)

    with pytest.raises(GiftPackError) as rejected:
        rules._gift_pack_condition_label({"type": "magic"})
    assert rejected.value.code == "gift_pack_invalid"


# ---------------------------------------------------------------------------
# 旧格式条件与生命周期


def test_legacy_eligibility_becomes_leaves() -> None:
    legacy = {
        "min_credits": 100,
        "require_premium": True,
        "require_binding": "any",
    }
    assert rules._legacy_gift_pack_requirements(legacy) == [
        {"type": "credits", "min": 100},
        {"type": "premium", "state": "active"},
        {"type": "bound", "service": "any"},
    ]
    assert rules._legacy_gift_pack_requirements({}) == []

    assert rules._resolve_gift_pack_conditions(
        _pack(eligibility='{"min_credits": 50}', requirements=None, audience=None)
    ) == ([], [{"type": "credits", "min": 50}])
    # 新列优先
    assert rules._resolve_gift_pack_conditions(
        _pack(
            eligibility='{"min_credits": 50}',
            requirements='[{"type": "credits", "min": 5}]',
            audience='[{"type": "user_list", "mode": "include", "tg_ids": [1]}]',
        )
    ) == (
        [{"type": "user_list", "mode": "include", "tg_ids": [1]}],
        [{"type": "credits", "min": 5}],
    )


def test_lifecycle_phase_ref_and_remaining() -> None:
    pack = _pack(start_at=100, end_at=300, task_end_at=200, total_quantity=10)
    assert rules._gift_pack_lifecycle(pack, 99) == "upcoming"
    assert rules._gift_pack_lifecycle(pack, 100) == "active"
    assert rules._gift_pack_lifecycle(pack, 201) == "claim_only"
    assert rules._gift_pack_lifecycle(pack, 301) == "ended"
    # 冻结在任务截止时间（没有截止时间则用礼包结束时间）
    assert rules._gift_pack_phase_ref(pack, 250) == 200
    assert rules._gift_pack_phase_ref(pack, 150) == 150
    assert rules._gift_pack_phase_ref(_pack(task_end_at=None), 250) == 250

    assert rules._gift_pack_remaining(_pack(total_quantity=10, claimed_count=3)) == 7
    assert rules._gift_pack_remaining(_pack(total_quantity=10, claimed_count=10)) == 0
    assert rules._gift_pack_remaining(_pack(total_quantity=10, claimed_count=12)) == 0
    assert rules._gift_pack_remaining(_pack(total_quantity=None)) is None


def test_audience_size_and_local_date() -> None:
    assert rules._gift_pack_audience_size([]) is None
    assert (
        rules._gift_pack_audience_size(
            [
                {"type": "user_list", "mode": "include", "tg_ids": [1, 2]},
                {"type": "premium", "state": "active"},
            ]
        )
        == 2
    )
    assert (
        rules._gift_pack_audience_size([{"type": "user_list", "mode": "exclude"}])
        is None
    )
    assert rules._gift_pack_local_date(0) == "1970-01-01"


# ---------------------------------------------------------------------------
# 求值：13 种条件、any_of、进度


def test_evaluate_covers_every_condition_type() -> None:
    pack = _pack()
    context = _context()
    items = [
        {"type": "credits", "min": 40, "max": 50},
        {"type": "premium", "state": "active"},
        {"type": "bound", "service": "plex"},
        {"type": "bound", "service": "any"},
        {"type": "badge", "badge_id": 7},
        {"type": "claimed_pack", "pack_id": 88},
        {"type": "user_list", "mode": "include", "tg_ids": [1]},
        {"type": "user_list", "mode": "exclude", "tg_ids": [2]},
        {
            "type": "wheel_spins",
            "min": 3,
            "window": {"kind": "pack"},
            "paid_only": True,
        },
        {
            "type": "blackjack_hands",
            "min": 2,
            "min_accuracy": 0.5,
            "window": {"kind": "days", "days": 7},
        },
        {"type": "treasure_issues", "min": 1, "window": {"kind": "all"}},
        {"type": "prediction_bets", "min": 1, "window": {"kind": "all"}},
        {"type": "auction_participations", "min": 1, "window": {"kind": "all"}},
        {"type": "tournament_entries", "min": 1, "window": {"kind": "all"}},
        {"type": "invitees", "min": 1, "window": {"kind": "all"}},
        {"type": "watched_hours", "min": 1, "window": {"kind": "all"}},
    ]
    metrics = {
        rules.metric_key(item, pack, 300): 5
        for item in items
        if item["type"] in rules._GIFT_PACK_METRICS
    }
    # 黑杰克带准确率时取回的是 (次数, 准确率)
    metrics[rules.metric_key(items[9], pack, 300)] = (5, 0.8)

    ok, progress = rules.evaluate(items, context, pack, 300, metrics=metrics)

    assert ok is True
    assert [item["met"] for item in progress] == [True] * len(items)
    assert progress[0]["current"] == 42.0
    assert progress[0]["target"] == 40
    assert progress[9]["sub"][0] == {
        "label": "准确率",
        "current": 0.8,
        "target": 0.5,
        "met": True,
    }
    assert progress[10]["window"] == {"kind": "all"}
    # invitees / watched_hours 不带窗口
    assert "window" not in progress[14]
    assert "window" not in progress[15]

    failing = [{"type": "credits", "min": 1000}]
    ok, progress = rules.evaluate(failing, context, pack, 300, metrics={})
    assert ok is False
    assert progress[0]["met"] is False


def test_any_of_reports_every_child_and_short_circuits_nothing() -> None:
    pack = _pack()
    items = [
        {
            "type": "any_of",
            "items": [
                {"type": "wheel_spins", "min": 10, "window": {"kind": "pack"}},
                {"type": "wheel_spins", "min": 20, "window": {"kind": "pack"}},
            ],
        }
    ]
    metrics = {rules.metric_key(items[0]["items"][0], pack, 300): 12}

    ok, progress = rules.evaluate(items, _context(), pack, 300, metrics=metrics)

    assert ok is True
    assert progress[0]["type"] == "any_of"
    assert progress[0]["label"] == "任选其一"
    assert [child["met"] for child in progress[0]["items"]] == [True, False]


def test_unsupported_condition_is_a_typed_rejection() -> None:
    with pytest.raises(GiftPackError) as rejected:
        rules.evaluate([{"type": "magic"}], _context(), _pack(), 300, metrics={})
    assert rejected.value.code == "gift_pack_invalid"


# ---------------------------------------------------------------------------
# 取数计划：礼包未开始时不取数


def test_required_metrics_plans_windows_and_skips_closed_ones() -> None:
    pack = _pack(start_at=500, end_at=1000)
    items = [
        {"type": "credits", "min": 1},
        {"type": "wheel_spins", "min": 1, "window": {"kind": "all"}},
        {"type": "wheel_spins", "min": 1, "window": {"kind": "pack"}},
        {"type": "blackjack_hands", "min": 1, "window": {"kind": "days", "days": 3}},
        {
            "type": "any_of",
            "items": [
                {"type": "tournament_entries", "min": 1, "window": {"kind": "all"}}
            ],
        },
    ]

    # 礼包窗口未开始（ref < start_at）：pack 窗口不取数
    planned = rules.required_metrics(items, pack, 499)
    assert ("wheel_spins", 0, 499, ()) in planned
    assert not any(key[0] == "wheel_spins" and key[1] == 500 for key in planned)
    assert ("tournament_entries", 0, 499, ()) in planned
    assert len(planned) == 3

    # 窗口打开后：pack 窗口按 start_at 取数，且重复窗口只登记一次
    opened = rules.required_metrics(items, pack, 600)
    assert ("wheel_spins", 500, 600, ()) in opened
    assert len(opened) == 4

    # 未开始的窗口在求值时按 0 计，仍然展示进度
    top = {"type": "wheel_spins", "min": 1, "window": {"kind": "pack"}}
    assert rules.metric_value(top, pack, 499, {}) == 0
    accuracy_item = {
        "type": "blackjack_hands",
        "min": 1,
        "min_accuracy": 0.5,
        "window": {"kind": "pack"},
    }
    assert rules.metric_value(accuracy_item, pack, 499, {}) == (0, 0.0)


def test_metric_key_includes_qualifiers_and_reference() -> None:
    pack = _pack()
    base = {"type": "wheel_spins", "min": 1, "window": {"kind": "pack"}}
    paid = {**base, "paid_only": True}
    free = {**base, "paid_only": False}

    assert rules.metric_key(base, pack, 300) == ("wheel_spins", 100, 300, ())
    assert rules.metric_key(paid, pack, 300) != rules.metric_key(free, pack, 300)
    assert rules.metric_key(paid, pack, 300) == (
        "wheel_spins",
        100,
        300,
        (("paid_only", True),),
    )


# ---------------------------------------------------------------------------
# 受众求值与开始后编辑校验


def test_audience_requires_list_then_non_list_conditions() -> None:
    pack = _pack()
    audience = [
        {"type": "user_list", "mode": "include", "tg_ids": [1]},
        {"type": "premium", "state": "active"},
    ]
    assert rules._evaluate_gift_pack_audience(audience, _context(), pack, 300) is True
    assert (
        rules._evaluate_gift_pack_audience(
            audience, _context(premium_services=[]), pack, 300
        )
        is False
    )
    assert (
        rules._evaluate_gift_pack_audience(audience, _context(_tg_id=99), pack, 300)
        is False
    )
    # 非名单条件在锁定后不再重算
    locked = GiftPackUserState(audience_locked_at=250)
    assert (
        rules._evaluate_gift_pack_audience(
            audience, _context(premium_services=[]), pack, 300, locked
        )
        is True
    )


def test_post_start_edit_validation() -> None:
    old = {
        "start_at": 100,
        "end_at": 1000,
        "task_end_at": 200,
        "total_quantity": 10,
        "rewards": [{"type": "credits", "amount": 10}],
        "audience": [],
        "requirements": [{"type": "credits", "min": 100}],
    }
    new = {**old, "rewards": [{"type": "credits", "amount": 99}]}
    with pytest.raises(GiftPackError) as rejected:
        rules._validate_post_start_edit(old, new)
    assert rejected.value.code == "gift_pack_invalid"
    assert "礼包开始后不能修改" in str(rejected.value)

    # 开始后门槛不能提高（降低门槛是允许的，方便运营放宽）
    looser = {**old, "requirements": [{"type": "credits", "min": 50}]}
    rules._validate_post_start_edit(old, looser)
    tighter = {**old, "requirements": [{"type": "credits", "min": 200}]}
    with pytest.raises(GiftPackError):
        rules._validate_post_start_edit(old, tighter)

    # 截止时间与总量只能增加
    rules._validate_post_start_edit(old, {**old, "end_at": 2000})
    with pytest.raises(GiftPackError):
        rules._validate_post_start_edit(old, {**old, "end_at": 900})
    rules._validate_post_start_edit(old, {**old, "total_quantity": 99})
    with pytest.raises(GiftPackError):
        rules._validate_post_start_edit(old, {**old, "total_quantity": 5})
    # 名单只比较骨架：具体 tg_ids 可以改，条件本身不能变
    old_listed = {
        **old,
        "audience": [{"type": "user_list", "mode": "include", "tg_ids": [1]}],
    }
    rules._validate_post_start_edit(
        old_listed,
        {
            **old_listed,
            "audience": [{"type": "user_list", "mode": "include", "tg_ids": [1, 2]}],
        },
    )
    with pytest.raises(GiftPackError):
        rules._validate_post_start_edit(
            old_listed,
            {
                **old_listed,
                "audience": [{"type": "user_list", "mode": "exclude", "tg_ids": [1]}],
            },
        )
