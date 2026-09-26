"""Treasure auto-reopen jobs; callable paths here are persisted by APScheduler."""

from app.core.config import settings
from app.core.log import uvicorn_logger as logger
from app.databases import db
from app.domains.treasure.notifications import notify_treasure_issue_created


async def _auto_create_next_treasure_issue_from(*, source_issue_id: int) -> None:
    """在指定期数开奖后，自动创建“同规格”的下一期。"""

    try:
        source = db.get_treasure_issue_by_id(int(source_issue_id))
        if not source:
            logger.warning(
                f"Treasure auto reopen: source issue not found: {source_issue_id}"
            )
            return
        if int(source.get("status") or 0) != 2:
            logger.info(
                f"Treasure auto reopen: source issue not settled; skip: {source_issue_id}"
            )
            return

        from datetime import datetime

        now = datetime.now(settings.TZ).strftime("%Y-%m-%d-%H:%M:%S")
        # 标题不强制与上一期相同，避免列表中难以区分；规格（积分配置）保持一致。
        title = f"夺宝奇兵 {now}"

        issue_id = db.create_treasure_issue(
            title=title,
            description=source.get("description"),
            prize_credits=int(source.get("prize_credits") or 0),
            total_credits_required=int(source.get("total_credits_required") or 0),
            credits_per_share=int(source.get("credits_per_share") or 10),
            start_number=None,  # 新一期重新随机起始号
            created_by=source.get("created_by"),
        )

        try:
            created = db.get_treasure_issue_by_id(int(issue_id))
            if created:
                await notify_treasure_issue_created(
                    issue_id=int(issue_id),
                    title=str(created.get("title")),
                    total_shares=int(created.get("total_shares")),
                    credits_per_share=int(created.get("credits_per_share")),
                    prize_credits=int(created.get("prize_credits")),
                )
        except Exception as e:
            logger.warning(f"Treasure auto reopen notify failed: {e}")

        logger.info(
            f"Treasure auto reopen: created next issue {issue_id} from {source_issue_id}"
        )
    except Exception as e:
        logger.error(f"Treasure auto reopen failed (source={source_issue_id}): {e}")


def schedule_auto_reopen_treasure_issue(*, source_issue_id: int) -> None:
    """安排在开奖后 N 分钟自动开新一期。"""

    delay_min = 10

    try:
        from datetime import datetime, timedelta

        from app.core.scheduler import Scheduler

        run_date = datetime.now(settings.TZ) + timedelta(minutes=int(delay_min))
        job_id = f"treasure_auto_reopen_{int(source_issue_id)}"
        Scheduler().add_async_job(
            # B2 keeps the B1 persisted callable path until B3 jobstore migration.
            func="app.webapp.routers.activities.treasure:_auto_create_next_treasure_issue_from",
            trigger="date",
            id=job_id,
            replace_existing=True,
            max_instances=1,
            run_date=run_date,
            kwargs={"source_issue_id": int(source_issue_id)},
            jobstore="sqlalchemy",  # 使用持久化存储，避免服务重启导致任务丢失
        )
        logger.info(
            f"Treasure auto reopen scheduled: source={source_issue_id}, delay_min={delay_min}"
        )
    except Exception as e:
        logger.error(f"Treasure auto reopen schedule failed: {e}")
