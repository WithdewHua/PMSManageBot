"""礼包 repository 包：按子主题组合五个 mixin。

纯计算（奖励登记表与文案、条件解析、生命周期与校验）在
``app.domains.gift_pack.rules``，这里只保留需要数据库的部分。
"""

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
