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
                    total_shares=int(created.get("total_shares") or 0),
                    credits_per_share=int(created.get("credits_per_share") or 0),
                    prize_credits=int(created.get("prize_credits") or 0),
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

        from app.core.scheduler import schedule_task

        run_date = datetime.now(settings.TZ) + timedelta(minutes=int(delay_min))
        job_id = f"treasure_auto_reopen_{int(source_issue_id)}"
        schedule_task(
            "treasure.open_next_issue",
            run_date=run_date,
            job_id=job_id,
            kwargs={"source_issue_id": int(source_issue_id)},
            misfire_grace_time=60,
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            f"Treasure auto reopen scheduled: source={source_issue_id}, delay_min={delay_min}"
        )
    except Exception as e:
        logger.error(f"Treasure auto reopen schedule failed: {e}")
