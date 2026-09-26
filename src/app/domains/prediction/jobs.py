from time import time

from sqlalchemy import select

from app.core.db import get_session
from app.core.log import logger
from app.domains.prediction.models import PredictionMarket


async def check_prediction_markets_closing_soon_job() -> list[dict]:
    """定时任务：每小时检查押注中且 6 小时内截止的大预言家题目，并发送群组汇总通知。"""
    try:
        now_ts = int(time())
        deadline_upper_ts = int(now_ts + 6 * 3600)

        with get_session() as session:
            rows = (
                session.execute(
                    select(PredictionMarket)
                    .where(
                        PredictionMarket.status == 1,
                        PredictionMarket.betting_deadline.is_not(None),
                        PredictionMarket.betting_deadline > int(now_ts),
                        PredictionMarket.betting_deadline <= int(deadline_upper_ts),
                    )
                    .order_by(PredictionMarket.betting_deadline.asc())
                )
                .scalars()
                .all()
            )

            markets = [
                {
                    "id": int(m.id),
                    "title": str(m.title or ""),
                    "betting_deadline": int(m.betting_deadline),
                }
                for m in rows
                if m.betting_deadline is not None
            ]

            if not markets:
                logger.info("大预言家截止提醒检查完成：未来 6 小时内无押注截止题目")
                return []

        from app.domains.prediction.notifications import (
            notify_prediction_markets_closing_soon,
        )

        await notify_prediction_markets_closing_soon(
            markets=markets,
            threshold_hours=6,
        )
        logger.info(
            f"大预言家截止提醒已发送：count={len(markets)}, window=(now, now+6h]"
        )
        return markets
    except Exception as e:
        logger.error(f"检查大预言家题目截止提醒失败: {e}")
        return []
