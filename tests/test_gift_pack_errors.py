"""Typed gift-pack rejections keep the legacy transport detail (design D8).

Every rejection family the gift-pack repository raised as a bare ``ValueError``
now carries a stable code and an explicit status code, while the JSON that the
frozen HTTP contract fixture recorded stays byte-identical. ``GiftPackError`` also
derives from ``ValueError`` so the remaining transitional callers keep working.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.db import get_session
from app.core.errors import DomainError
from app.domains.gift_pack.exceptions import (
    ConditionsNotMet,
    GiftPackError,
    gift_pack_error,
    gift_pack_not_found,
    wrap_reward_rejection,
)

ROOT = Path(__file__).parents[1]
REPOSITORY = ROOT / "src/app/domains/gift_pack/repository"

#: 旧文案 -> (code, HTTP 状态码)。状态码在抛出点按接口语义确定。
EXPECTED = {
    "礼包不存在": ("gift_pack_not_found", 400),
    "礼包已停用": ("gift_pack_disabled", 400),
    "礼包尚未开始": ("gift_pack_not_started", 400),
    "礼包已结束": ("gift_pack_ended", 400),
    "礼包已被领完": ("gift_pack_sold_out", 400),
    "你已领取过该礼包": ("gift_pack_already_claimed", 400),
    "用户积分信息不存在": ("gift_pack_user_missing", 400),
    "请先绑定媒体账号后再领取": ("gift_pack_reward_rejected", 400),
    "不支持的奖励类型: mystery": ("gift_pack_reward_rejected", 400),
    "不支持的解锁类型: unknown/plex": ("gift_pack_reward_rejected", 400),
    "邀请码数量必须为正": ("gift_pack_reward_rejected", 400),
    "争霸赛余额数量必须为正": ("gift_pack_reward_rejected", 400),
    "免费机会的次数与有效天数必须为正": ("gift_pack_reward_rejected", 400),
    "引用的勋章不存在: 999": ("gift_pack_referenced", 400),
    "礼包不能引用自身作为已领取条件": ("gift_pack_referenced", 400),
    "该礼包被其他礼包的已领取条件引用：#1 不存在的引用者；请先移除引用": (
        "gift_pack_referenced",
        400,
    ),
    "礼包至少需要一项奖励": ("gift_pack_invalid", 400),
    "结束时间必须晚于开始时间": ("gift_pack_invalid", 400),
    "任务截止时间必须晚于开始时间且不晚于结束时间": ("gift_pack_invalid", 400),
    "限量份数必须大于 0": ("gift_pack_invalid", 400),
    "开启开始通知要求受众顶层包含 include 指定名单": ("gift_pack_invalid", 400),
    "礼包开始后不能修改 奖励 rewards；可停用后新建礼包": ("gift_pack_invalid", 400),
    "不支持的礼包条件: magic": ("gift_pack_invalid", 400),
}


@pytest.mark.parametrize(("message", "expected"), sorted(EXPECTED.items()))
def test_legacy_messages_map_to_codes_and_details(message, expected) -> None:
    error = gift_pack_error(message)
    code, status_code = expected
    assert error.code == code
    assert error.status_code == status_code
    assert error.as_response()["detail"] == message
    assert str(error) == message


def test_not_found_helper_defaults_to_400_and_allows_404() -> None:
    assert gift_pack_not_found().status_code == 400
    assert gift_pack_not_found(status_code=404).status_code == 404
    assert gift_pack_not_found().code == "gift_pack_not_found"


def test_errors_stay_compatible_with_value_error() -> None:
    assert isinstance(gift_pack_error("礼包不存在"), ValueError)
    assert isinstance(gift_pack_error("礼包不存在"), DomainError)
    assert isinstance(ConditionsNotMet([]), ValueError)


def test_conditions_not_met_carries_structured_progress() -> None:
    progress = [
        {"type": "credits", "label": "积分", "met": False, "current": 1, "target": 5}
    ]
    error = ConditionsNotMet(progress)

    assert error.code == "gift_pack_conditions_not_met"
    assert error.status_code == 400
    assert error.requirements == progress
    payload = error.as_response()
    assert payload["requirements"] == progress
    # 前端要展示逐项进度：detail 是对象，且与 1.2 冻结的夹具一致
    assert payload["detail"] == {"message": "不满足领取条件", "requirements": progress}


def test_conditions_not_met_without_progress_uses_plain_detail() -> None:
    error = ConditionsNotMet([])
    assert error.as_response()["detail"] == "不满足领取条件"


def test_foreign_value_error_is_wrapped_and_keeps_its_text() -> None:
    original = ValueError("发放阶段拒绝：奖励目标不可用")
    error = wrap_reward_rejection(original)

    assert error.code == "gift_pack_reward_rejected"
    assert error.status_code == 400
    assert error.as_response()["detail"] == str(original)
    assert error.__cause__ is original


def test_wrapping_a_gift_pack_error_returns_it_unchanged() -> None:
    error = gift_pack_error("礼包已被领完")
    assert wrap_reward_rejection(error) is error


def test_repository_raises_only_typed_errors() -> None:
    """repository 里不再有裸 ValueError（不含 *参数* 这类外域语义）。"""
    offenders: list[str] = []
    for path in sorted(REPOSITORY.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id == "ValueError"
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_router_uses_typed_status_codes_instead_of_substrings() -> None:
    """router 只读类型化异常的状态码与 payload，不做字符串匹配。"""
    source = (ROOT / "src/app/domains/gift_pack/router.py").read_text(encoding="utf-8")
    assert "except GiftPackError as e:" in source
    assert source.count("e.status_code") >= 2
    assert "不满足领取条件；当前进度：" not in source
    assert '"不存在" in message' not in source


def _started_pack(orm) -> int:
    """一个已经开始、可以领取的礼包，用于编辑/删除路径的状态码断言。"""
    import json
    import time

    from app.domains.gift_pack.models import GiftPack

    with get_session() as session:
        pack = GiftPack(
            id=900001,
            title="状态码礼包",
            description=None,
            rewards=json.dumps([{"type": "credits", "amount": 10}]),
            start_at=int(time.time()) - 10,
            end_at=int(time.time()) + 3600,
            is_enabled=1,
            claimed_count=0,
            max_prompt_count=3,
            max_task_prompt_count=2,
            notify_audience_on_start=0,
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        session.add(pack)
    return 900001


def test_delete_missing_pack_is_a_404_typed_error(orm) -> None:
    with pytest.raises(GiftPackError) as rejected:
        orm.delete_gift_pack(999999)

    assert rejected.value.code == "gift_pack_not_found"
    assert rejected.value.status_code == 404
    assert rejected.value.as_response()["detail"] == "礼包不存在"


def test_update_missing_pack_is_a_400_typed_error(orm) -> None:
    with pytest.raises(GiftPackError) as rejected:
        orm.update_gift_pack(999999, title="新标题")

    assert rejected.value.code == "gift_pack_not_found"
    assert rejected.value.status_code == 400


def test_post_start_edit_rejection_is_typed(orm) -> None:
    pack_id = _started_pack(orm)

    with pytest.raises(GiftPackError) as rejected:
        orm.update_gift_pack(pack_id, rewards=[{"type": "credits", "amount": 99}])

    assert rejected.value.code == "gift_pack_invalid"
    assert rejected.value.status_code == 400
    assert rejected.value.as_response()["detail"].startswith("礼包开始后不能修改")
    assert "rewards" in rejected.value.as_response()["detail"]
