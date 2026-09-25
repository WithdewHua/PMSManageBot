import json
import threading

from sqlalchemy import select

from app.domains.gift_pack.models import GiftPack

_GIFT_PACK_PRIVILEGED_CODES_LOCK = threading.Lock()


def _format_gift_pack_number(value) -> str:
    """整数去掉小数点，其余按 %g 输出，如 100.0 -> 100、12.5 -> 12.5"""
    number = float(value or 0)
    return str(int(number)) if number.is_integer() else f"{number:g}"


# 礼包奖励类型登记表。标签渲染、自动补绑定要求、统计汇总、过期汇总通知都从这里读，
# 不再各自写 `if type == ...`。新增奖励类型时只需在此登记并实现发放分支。
#
# - requires_binding：该奖励作用于已绑定的媒体服务，礼包隐含「至少绑定一个媒体账号」
# - label：把奖励项配置渲染成人类可读的短语
# - stat_label：统计中该类型的名称
# - stat_field：统计时累加快照条目的哪个字段；None 表示按生效条目数计（每个服务一条）
# - skipped_label：快照条目带 skipped 时，统计里说明跳过原因的文案
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


from .part_1 import _GiftPackRepositoryPart1
from .part_2 import _GiftPackRepositoryPart2
from .part_3 import _GiftPackRepositoryPart3


class GiftPackRepository(
    _GiftPackRepositoryPart1, _GiftPackRepositoryPart2, _GiftPackRepositoryPart3
):
    @staticmethod
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
                requirements.append(
                    {"type": "bound", "service": legacy["require_binding"]}
                )
        return audience, requirements

    @staticmethod
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
            return (
                "需要 Premium 身份" if item["state"] == "active" else "无 Premium 身份"
            )
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
        raise ValueError(f"不支持的礼包条件: {kind}")

    @staticmethod
    def _gift_pack_condition_summary(items: list[dict]) -> str:
        def label(item: dict) -> str:
            if item["type"] == "any_of":
                return (
                    "（" + " 或 ".join(label(child) for child in item["items"]) + "）"
                )
            text = GiftPackRepository._gift_pack_condition_label(item)
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

    @staticmethod
    def _validate_post_start_edit(old: dict, new: dict) -> None:
        def reject(field: str) -> None:
            raise ValueError(f"礼包开始后不能修改 {field}；可停用后新建礼包")

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
                    elif (
                        item["type"] in GiftPackRepository._GIFT_PACK_COUNT_METHODS
                        or item["type"] == "credits"
                    ):
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

    @staticmethod
    def _gift_pack_referencing_packs(session, pack_id: int) -> list[tuple[int, str]]:
        """Check references semantically, including any_of, not via JSON substring."""
        references = []
        for pack in session.execute(
            select(GiftPack).where(GiftPack.id != pack_id)
        ).scalars():
            audience, requirements = GiftPackRepository._resolve_gift_pack_conditions(
                pack
            )

            def refers(items):
                return any(
                    any(
                        child["type"] == "claimed_pack" and child["pack_id"] == pack_id
                        for child in item["items"]
                    )
                    if item["type"] == "any_of"
                    else item["type"] == "claimed_pack" and item["pack_id"] == pack_id
                    for item in items
                )

            if refers(audience) or refers(requirements):
                references.append((int(pack.id), pack.title))
        return references
