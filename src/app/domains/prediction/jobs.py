from app.core.log import logger
from app.domains.prediction import service as prediction_service


async def check_prediction_markets_closing_soon_job() -> list[dict]:
    """定时任务：由 prediction service 查询并发送截止提醒。"""
    try:
        return await prediction_service.check_prediction_markets_closing_soon()
    except Exception as error:
        logger.error(f"检查大预言家题目截止提醒失败: {error}")
        return []
