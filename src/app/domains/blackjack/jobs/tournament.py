"""21 点锦标赛调度适配层。

按项目分层，`jobs` 只负责「解析任务参数 → 调 service」：赛事推进与每周自动开赛
的业务流程、事务和通知都在 `blackjack_service` 里（本模块保留同名任务入口，供
`app.schedule` 注册）。

**赛事推进用每分钟一次的 tick 任务，不用 per-赛事的持久化 date 任务**（design 决策
8）：那套机制的代价是 `misfire_grace_time=None` 的陷阱外加一个重启恢复函数。手牌
超时值得付这个代价（15 分钟时限要求及时性），而赛事是跨天事件，一分钟的推进延迟
无人可感，周期 tick 天然免疫任务丢失与重启，**不需要恢复函数**。

赛内手牌超时仍复用现金局那套持久化 date 任务（`_schedule_tournament_hand_timeout`），
结算时走哪个适配层由 `_settle_blackjack_hand_dispatch` 按 `tournament_id` 分派。
"""

from app.core.log import uvicorn_logger as logger
from app.domains.blackjack import service as blackjack_service


async def blackjack_tournament_tick_job() -> None:
    """赛事推进任务入口：每分钟依次处理报名截止、完赛提醒、完赛结算。"""

    await blackjack_service.tick_tournaments()


async def auto_create_blackjack_tournament_job() -> None:
    """每周一 09:00 自动创建周赛（cron 注册在 schedule.py）。"""

    await blackjack_service.create_weekly_tournament()


def _schedule_tournament_hand_timeout(result: dict) -> None:
    """为新发出的赛内手牌安排超时任务。

    复用现金局那套持久化 date 任务（三层保障：date 任务 / 重启恢复 / 定时全量
    兜底），结算时走哪个适配层由 `_settle_blackjack_hand_dispatch` 按
    `tournament_id` 分派，故此处无需区分。

    时限从手牌自己的快照读（发牌时已从赛事固化到手牌行上），不回查赛事。
    """
    if result.get("settled"):
        return
    try:
        from app.domains.blackjack.jobs.cash import (
            _schedule_blackjack_timeout,
        )

        _schedule_blackjack_timeout(
            hand_id=int(result["hand"]["id"]),
            timeout_minutes=float(result["hand"]["hand_timeout_minutes"]),
        )
    except Exception as e:
        logger.error(f"安排赛内手牌超时任务失败: {e}")
