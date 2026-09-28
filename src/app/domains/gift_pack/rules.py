"""礼包领域的纯计算：奖励登记表与文案、条件解析、生命周期与余量、字段校验。

这里不读数据库、不开 session、不发通知、不导入其他领域：输入是普通 dict 和模型
快照，输出是普通值（design D4）。需要取数的部分由 repository 依据
``required_metrics`` 决定取哪些指标，再把结果交给 ``evaluate``。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime

from app.core.config import settings
from app.domains.gift_pack.exceptions import gift_pack_error
from app.domains.gift_pack.models import GiftPack, GiftPackUserState

#: 需要向各领域计数器取数的条件类型（次数的具体查询由 repository 负责）。
_GIFT_PACK_METRICS = (
    "wheel_spins",
    "blackjack_hands",
    "treasure_issues",
    "prediction_bets",
    "auction_participations",
    "tournament_entries",
    "invitees",
    "watched_hours",
)


def _format_gift_pack_number(value) -> str:
    """整数去掉小数点，其余按 %g 输出，如 100.0 -> 100、12.5 -> 12.5"""
    number = float(value or 0)
    return str(int(number)) if number.is_integer() else f"{number:g}"


GIFT_PACK_REWARD_TYPES: dict[str, dict] = {
    "credits": {
        "requires_binding": False,
        "label": lambda r: f"{_format_gift_pack_number(r.get('amount'))} 积分",
        "stat_label": "积分",
        "stat_field": "amount",
        "skipped_label": None,
    },
    "premium_days": {
        "requires_binding": True,
        "label": lambda r: f"{int(r.get('days') or 0)} 天 Premium",
        "stat_label": "Premium 天数",
        "stat_field": "days",
        "skipped_label": "因永久会员跳过",
    },
    "wheel_free_spins": {
        "requires_binding": False,
        "label": lambda r: (
            f"{int(r.get('count') or 0)} 次大转盘免费机会"
            f"（{int(r.get('expiry_days') or 0)} 天有效）"
        ),
        "stat_label": "大转盘免费机会（次）",
        "stat_field": "count",
        "skipped_label": None,
    },
    "tournament_wallet": {
        "requires_binding": False,
        "label": lambda r: f"{_format_gift_pack_number(r.get('amount'))} 争霸赛余额",
        "stat_label": "争霸赛余额",
        "stat_field": "amount",
        "skipped_label": None,
    },
    "invite_codes": {
        "requires_binding": False,
        "label": lambda r: (
            f"{int(r.get('count') or 0)} 枚"
            f"{'特权' if r.get('privileged') else ''}邀请码"
        ),
        "stat_label": "邀请码（枚）",
        "stat_field": "count",
        "skipped_label": None,
    },
    "line_schedule_unlock": {
        "requires_binding": True,
        "label": lambda r: "线路调度解锁",
        "stat_label": "线路调度解锁（生效服务数）",
        "stat_field": None,
        "skipped_label": "因已解锁跳过",
    },
    "download_unlock": {
        "requires_binding": True,
        "label": lambda r: "下载权限解锁",
        "stat_label": "下载权限解锁（生效服务数）",
        "stat_field": None,
        "skipped_label": "因已解锁跳过",
    },
}


def gift_pack_rewards_require_binding(rewards: list[dict]) -> bool:
    """奖励项中是否含作用于已绑定服务的奖励（隐含「至少绑定一个媒体账号」）"""
    return any(
        GIFT_PACK_REWARD_TYPES.get(r.get("type"), {}).get("requires_binding")
        for r in rewards
    )


def _gift_pack_local_date(timestamp: int) -> str:
    """按 settings.TZ 把时间戳折算成 YYYY-MM-DD

    提醒节流的「今天」以运营时区为准，而非用户浏览器时区，
    否则跨时区用户的提醒节奏会与运营预期错位。
    """
    return datetime.fromtimestamp(int(timestamp), settings.TZ).strftime("%Y-%m-%d")


def _is_premium_active(is_premium, expiry_time) -> bool:
    """判断某个服务的 Premium 是否当前有效（永久会员视为有效）"""
    if not is_premium:
        return False
    if not expiry_time:
        # 有 is_premium 标记但无到期时间 = 永久会员
        return True
    try:
        return datetime.fromisoformat(str(expiry_time)).astimezone(
            settings.TZ
        ) > datetime.now(settings.TZ)
    except (ValueError, TypeError):
        # 到期时间无法解析时退回标记位，避免因脏数据误判为不可领取
        return bool(is_premium)


def _legacy_gift_pack_requirements(legacy: dict) -> list[dict]:
    result = []
    if legacy.get("min_credits") is not None:
        result.append({"type": "credits", "min": legacy["min_credits"]})
    if legacy.get("require_premium"):
        result.append({"type": "premium", "state": "active"})
    if legacy.get("require_binding"):
        result.append({"type": "bound", "service": legacy["require_binding"]})
    return result


def _gift_pack_conditions_with_binding(
    requirements: list[dict], rewards: list[dict]
) -> list[dict]:
    result = list(requirements or [])
    if gift_pack_rewards_require_binding(rewards) and not any(
        item["type"] == "bound" for item in result
    ):
        result.append({"type": "bound", "service": "any"})
    return result


def _resolve_gift_pack_conditions(pack: GiftPack) -> tuple[list[dict], list[dict]]:
    """Read new condition JSON, or adapt an unmigrated legacy eligibility row."""
    audience = json.loads(pack.audience) if pack.audience else []
    if pack.requirements:
        requirements = json.loads(pack.requirements)
    else:
        legacy = json.loads(pack.eligibility) if pack.eligibility else {}
        requirements = []
        if legacy.get("min_credits") is not None:
            requirements.append({"type": "credits", "min": legacy["min_credits"]})
        if legacy.get("require_premium"):
            requirements.append({"type": "premium", "state": "active"})
        if legacy.get("require_binding"):
            requirements.append({"type": "bound", "service": legacy["require_binding"]})
    return audience, requirements


def _gift_pack_condition_label(item: dict) -> str:
    """Keep all user-facing and admin condition wording in one place."""
    kind = item["type"]
    labels = {
        "wheel_spins": "付费转盘" if item.get("paid_only", True) else "转盘",
        "blackjack_hands": "21 点",
        "treasure_issues": "夺宝参与期数",
        "prediction_bets": "大预言家下注",
        "auction_participations": "竞拍参与场数",
        "tournament_entries": "锦标赛参赛",
        "invitees": "邀请人数",
        "watched_hours": "累计观看时长（小时）",
    }
    if kind in labels:
        window = item.get("window") or {"kind": "all"}
        prefix = (
            "礼包开始后"
            if window["kind"] == "pack"
            else f"最近 {window['days']} 天 "
            if window["kind"] == "days"
            else ""
        )
        suffix = ""
        if kind == "blackjack_hands" and item.get("min_bet") is not None:
            suffix = f"（每手 ≥ {_format_gift_pack_number(item['min_bet'])}）"
        return f"{prefix}{labels[kind]}{suffix}"
    if kind == "credits":
        if item.get("max") is not None:
            if item.get("min") is not None:
                return f"积分（{_format_gift_pack_number(item['min'])}–{_format_gift_pack_number(item['max'])}）"
            return f"积分（不超过 {_format_gift_pack_number(item['max'])}）"
        return "积分"
    if kind == "premium":
        return "需要 Premium 身份" if item["state"] == "active" else "无 Premium 身份"
    if kind == "bound":
        service = item.get("service", "any")
        return (
            f"绑定 {service.capitalize()} 账号"
            if service != "any"
            else "绑定 Plex 或 Emby 账号"
        )
    if kind == "badge":
        return f"持有勋章 #{item['badge_id']}"
    if kind == "claimed_pack":
        return f"已领取礼包 #{item['pack_id']}"
    if kind == "user_list":
        return "包含名单" if item["mode"] == "include" else "排除名单"
    raise gift_pack_error(f"不支持的礼包条件: {kind}")


def _gift_pack_condition_summary(items: list[dict]) -> str:
    def label(item: dict) -> str:
        if item["type"] == "any_of":
            return "（" + " 或 ".join(label(child) for child in item["items"]) + "）"
        text = _gift_pack_condition_label(item)
        target = item.get("min")
        if target is not None:
            number = _format_gift_pack_number(target)
            unit = {
                "wheel_spins": " 次",
                "blackjack_hands": " 手",
                "treasure_issues": " 期",
                "prediction_bets": " 次",
                "auction_participations": " 场",
                "tournament_entries": " 次",
                "invitees": " 人",
                "watched_hours": " 小时",
            }.get(item["type"])
            text += f" {number}{unit}" if unit else f" ≥ {number}"
        return text

    return " 且 ".join(label(item) for item in items or [])


def _gift_pack_audience_size(audience: list[dict]) -> int | None:
    include = [
        set(item["tg_ids"])
        for item in audience
        if item["type"] == "user_list" and item["mode"] == "include"
    ]
    if not include:
        return None
    members = set.intersection(*include)
    for item in audience:
        if item["type"] == "user_list" and item["mode"] == "exclude":
            members.difference_update(item["tg_ids"])
    return len(members)


def metric_key(item: dict, pack: GiftPack, ref: int) -> tuple:
    """一次取数的身份：(条件类型, 起始时间, 参考时间, 限定条件)

    同一身份在同一个礼包里只查一次，因此这里的取值必须与查询参数一一对应。
    """
    window = item.get("window") or {"kind": "all"}
    kind = window["kind"]
    if kind == "pack":
        since = int(pack.start_at)
    elif kind == "days":
        since = ref - int(window["days"]) * 86400
    else:
        since = 0
    qualifiers = tuple(
        sorted(
            (key, item[key])
            for key in ("paid_only", "min_bet", "min_accuracy")
            if key in item
        )
    )
    return (item["type"], since, ref, qualifiers)


def metric_window_open(item: dict, pack: GiftPack, ref: int) -> bool:
    """礼包自己的窗口还没开始时不用取数：直接按 0 计（不发 COUNT 查询）"""
    window = item.get("window") or {"kind": "all"}
    return not (window["kind"] == "pack" and ref < int(pack.start_at))


def required_metrics(items: list[dict] | None, pack: GiftPack, ref: int) -> list[tuple]:
    """本次求值需要向各领域计数器取数的条件（去重、顺序稳定）

    any_of 组内的每一项都要展示进度，所以这里不做短路：返回组内所有可用的窗口。
    """
    requested: list[tuple] = []
    for item in items or []:
        if item["type"] == "any_of":
            for key in required_metrics(item["items"], pack, ref):
                if key not in requested:
                    requested.append(key)
        elif item["type"] in _GIFT_PACK_METRICS and metric_window_open(item, pack, ref):
            key = metric_key(item, pack, ref)
            if key not in requested:
                requested.append(key)
    return requested


def metric_value(
    item: dict, pack: GiftPack, ref: int, metrics: dict
) -> int | float | tuple[int, float]:
    """从预取结果里取一条计数；窗口未打开时按 0 计"""
    if not metric_window_open(item, pack, ref):
        return (0, 0.0) if item.get("min_accuracy") is not None else 0
    return metrics[metric_key(item, pack, ref)]


def evaluate(
    items: list[dict] | None,
    ctx: dict,
    pack: GiftPack,
    ref: int,
    *,
    metrics: dict,
) -> tuple[bool, list[dict]]:
    """求值入口：只读预取好的计数，不碰数据库（design D4）"""
    return _evaluate_conditions(items, ctx, pack, ref, metrics=metrics)


def _evaluate_gift_pack_audience(
    audience: list[dict] | None,
    ctx: dict,
    pack: GiftPack,
    ref: int,
    state: GiftPackUserState | None = None,
    *,
    metrics: dict | None = None,
) -> bool:
    """List membership is live even when non-list criteria were locked earlier."""
    metrics = metrics or {}
    lists = [item for item in audience or [] if item["type"] == "user_list"]
    others = [item for item in audience or [] if item["type"] != "user_list"]
    listed, _ = _evaluate_conditions(lists, ctx, pack, ref, metrics=metrics)
    if not listed:
        return False
    if state is not None and state.audience_locked_at is not None:
        return True
    return _evaluate_conditions(others, ctx, pack, ref, metrics=metrics)[0]


def _evaluate_conditions(
    items: list[dict] | None,
    ctx: dict,
    pack: GiftPack,
    ref: int,
    *,
    metrics: dict,
) -> tuple[bool, list[dict]]:
    """Evaluate each condition once, returning eligibility and structured progress."""
    progress = []
    all_met = True
    for item in items or []:
        if item["type"] == "any_of":
            # A group contains leaves only; evaluate all leaves for their progress.
            children = [
                _evaluate_gift_pack_condition(leaf, ctx, pack, ref, metrics=metrics)
                for leaf in item["items"]
            ]
            met = any(child["met"] for child in children)
            progress.append(
                {
                    "type": "any_of",
                    "label": "任选其一",
                    "met": met,
                    "items": children,
                }
            )
        else:
            leaf = _evaluate_gift_pack_condition(item, ctx, pack, ref, metrics=metrics)
            met = leaf["met"]
            progress.append(leaf)
        all_met = all_met and met
    return all_met, progress


def _evaluate_gift_pack_condition(
    item: dict, ctx: dict, pack: GiftPack, ref: int, *, metrics: dict
) -> dict:
    kind = item["type"]
    result = {"type": kind, "label": _gift_pack_condition_label(item)}
    if kind == "premium":
        result["met"] = bool(ctx["premium_services"]) == (item["state"] == "active")
    elif kind == "bound":
        service = item.get("service", "any")
        result["met"] = (
            bool(ctx["bound_services"])
            if service == "any"
            else service in ctx["bound_services"]
        )
    elif kind == "credits":
        current = float(ctx["credits"])
        lower = item.get("min")
        upper = item.get("max")
        result.update(
            met=(lower is None or current >= lower)
            and (upper is None or current <= upper),
            current=current,
            target=lower if lower is not None else upper,
        )
    elif kind == "badge":
        result["met"] = item["badge_id"] in ctx["badge_ids"]
    elif kind == "claimed_pack":
        result["met"] = item["pack_id"] in ctx["claimed_pack_ids"]
    elif kind == "user_list":
        member = ctx["_tg_id"] in item["tg_ids"]
        result["met"] = member if item["mode"] == "include" else not member
    elif kind in _GIFT_PACK_METRICS:
        value = metric_value(item, pack, ref, metrics)
        accuracy = None
        if kind == "blackjack_hands" and isinstance(value, tuple):
            value, accuracy = value
        target = item["min"]
        met = value >= target
        if accuracy is not None:
            accuracy_target = float(item["min_accuracy"])
            met = met and accuracy >= accuracy_target
            result["sub"] = [
                {
                    "label": "准确率",
                    "current": round(accuracy, 2),
                    "target": accuracy_target,
                    "met": accuracy >= accuracy_target,
                }
            ]
        result.update(met=met, current=value, target=target)
        if kind not in ("invitees", "watched_hours"):
            result["window"] = item.get("window") or {"kind": "all"}
    else:
        raise gift_pack_error(f"不支持的礼包条件: {kind}")
    return result


def _gift_pack_reward_label(reward: dict) -> str:
    """把一个奖励项渲染成人类可读的短语，如「100 积分」「7 天 Premium」"""
    reward_type = reward.get("type")
    meta = GIFT_PACK_REWARD_TYPES.get(reward_type)
    if meta is None:
        return str(reward_type)
    return meta["label"](reward)


def _gift_pack_phase_ref(pack: GiftPack, now: int) -> int:
    """Freeze timestamped tasks at their deadline (or the pack's end)."""
    return min(int(now), int(pack.task_end_at or pack.end_at))


def _gift_pack_lifecycle(pack: GiftPack, now: int) -> str:
    """礼包相对当前时间的生命周期状态"""
    if now < int(pack.start_at):
        return "upcoming"
    if now > int(pack.end_at):
        return "ended"
    if pack.task_end_at is not None and int(pack.task_end_at) < now:
        return "claim_only"
    return "active"


def _gift_pack_remaining(pack: GiftPack) -> int | None:
    """剩余份数；不限量时返回 None"""
    if pack.total_quantity is None:
        return None
    return max(0, int(pack.total_quantity) - int(pack.claimed_count))


_LIFECYCLE_SORT_ORDER = {"active": 0, "claim_only": 0, "upcoming": 1, "ended": 2}


def gift_pack_status(
    *,
    claimed: bool,
    is_enabled: bool,
    lifecycle: str,
    remaining: int | None,
    requirements_met: bool,
) -> str:
    """Derive the user-facing list status without reading a model or database."""
    if claimed:
        return "claimed"
    if not is_enabled:
        return "disabled"
    if lifecycle == "upcoming":
        return "upcoming"
    if lifecycle == "ended":
        return "ended"
    if remaining is not None and remaining <= 0:
        return "sold_out"
    return "claimable" if requirements_met else "in_progress"


def gift_pack_sort_key(item: Mapping[str, object]) -> tuple[int, int]:
    """Sort list payloads by lifecycle, then by end time."""
    lifecycle = str(item.get("lifecycle") or "")
    return (
        _LIFECYCLE_SORT_ORDER.get(lifecycle, 3),
        int(item.get("end_at") or 0),
    )


def reminder_allowed(
    *, count: int, maximum: int, last_prompt_date: str | None, today: str
) -> bool:
    """Return whether one reminder class may be emitted today."""
    return int(count) < int(maximum) and last_prompt_date != today


def aggregate_reward_snapshots(
    snapshots: Iterable[str],
) -> tuple[list[dict], int]:
    """Aggregate persisted reward snapshots in registry order.

    The second return value counts malformed snapshots so the repository can keep
    its warning behavior without putting logging or I/O into this pure function.
    """
    aggregates: dict[str, dict] = {}
    invalid = 0
    for raw in snapshots:
        try:
            items = json.loads(raw)
            for item in items:
                reward_type = item.get("type")
                meta = GIFT_PACK_REWARD_TYPES.get(reward_type)
                if meta is None:
                    continue
                entry = aggregates.setdefault(
                    reward_type,
                    {
                        "type": reward_type,
                        "label": meta["stat_label"],
                        "total": 0,
                        "grants": 0,
                        "skipped": 0,
                    },
                )
                if item.get("skipped"):
                    entry["skipped"] += 1
                    continue
                field = meta["stat_field"]
                entry["total"] += float(item.get(field) or 0) if field else 1
                entry["grants"] += 1
        except (ValueError, TypeError):
            invalid += 1

    reward_totals = []
    for reward_type, meta in GIFT_PACK_REWARD_TYPES.items():
        entry = aggregates.get(reward_type)
        if entry is None:
            continue
        entry["total"] = round(entry["total"], 2)
        if meta["skipped_label"]:
            entry["skipped_label"] = meta["skipped_label"]
        if reward_type == "premium_days":
            entry["skipped_lifetime"] = entry["skipped"]
        reward_totals.append(entry)
    return reward_totals, invalid


def validate_gift_pack_fields(
    *,
    rewards: list[dict],
    start_at: int,
    end_at: int,
    task_end_at: int | None,
    total_quantity: int | None,
    audience: list[dict] | None,
    notify_audience_on_start: bool,
    claimed_count: int | None = None,
) -> None:
    """Validate merged create/update fields while preserving legacy messages."""
    if not rewards:
        raise gift_pack_error("礼包至少需要一项奖励")
    if end_at <= start_at:
        raise gift_pack_error("结束时间必须晚于开始时间")
    if task_end_at is not None and not start_at < task_end_at <= end_at:
        raise gift_pack_error("任务截止时间必须晚于开始时间且不晚于结束时间")
    if total_quantity is not None and total_quantity <= 0:
        raise gift_pack_error(
            "限量份数不能小于已领取份数且必须大于 0"
            if claimed_count is not None
            else "限量份数必须大于 0"
        )
    if (
        claimed_count is not None
        and total_quantity is not None
        and total_quantity < claimed_count
    ):
        raise gift_pack_error("限量份数不能小于已领取份数且必须大于 0")
    if notify_audience_on_start and not any(
        item["type"] == "user_list" and item["mode"] == "include"
        for item in audience or []
    ):
        raise gift_pack_error("开启开始通知要求受众顶层包含 include 指定名单")


def _validate_post_start_edit(old: dict, new: dict) -> None:
    def reject(field: str) -> None:
        raise gift_pack_error(f"礼包开始后不能修改 {field}；可停用后新建礼包")

    for field in ("start_at", "rewards"):
        if old[field] != new[field]:
            reject(field if field == "start_at" else "奖励 rewards")

    def skeleton(items, field):
        def strip(item):
            item = dict(item)
            if field == "audience" and item["type"] == "user_list":
                item.pop("tg_ids", None)
            if field == "requirements":
                if item["type"] == "any_of":
                    item["items"] = [strip(child) for child in item["items"]]
                elif item["type"] in _GIFT_PACK_METRICS or item["type"] == "credits":
                    item.pop("min", None)
            return item

        return [strip(item) for item in items]

    for field in ("audience", "requirements"):
        old_items, new_items = old[field], new[field]
        if skeleton(old_items, field) != skeleton(new_items, field):
            reject(field)
        if field == "requirements":

            def targets(items):
                for item in items:
                    if item["type"] == "any_of":
                        yield from targets(item["items"])
                    else:
                        yield item.get("min")

            for before, after in zip(targets(old_items), targets(new_items)):
                if before is not None and (after is None or after > before):
                    reject(field)
    if new["end_at"] < old["end_at"]:
        reject("end_at")
    old_deadline, new_deadline = old["task_end_at"], new["task_end_at"]
    if (old_deadline is None and new_deadline is not None) or (
        old_deadline is not None
        and new_deadline is not None
        and new_deadline < old_deadline
    ):
        reject("task_end_at")
    old_quantity, new_quantity = old["total_quantity"], new["total_quantity"]
    if (old_quantity is None and new_quantity is not None) or (
        old_quantity is not None
        and new_quantity is not None
        and new_quantity < old_quantity
    ):
        reject("total_quantity")
