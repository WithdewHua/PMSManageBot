import threading

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


from .claims import _GiftPackRepositoryClaims
from .conditions import _GiftPackRepositoryConditions
from .notices import _GiftPackRepositoryNotices
from .packs import _GiftPackRepositoryPacks
from .rewards import _GiftPackRepositoryRewards


class GiftPackRepository(
    _GiftPackRepositoryConditions,
    _GiftPackRepositoryRewards,
    _GiftPackRepositoryPacks,
    _GiftPackRepositoryClaims,
    _GiftPackRepositoryNotices,
):
    """礼包数据访问门面，按子主题组合五个 mixin。"""
