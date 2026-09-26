from sqlalchemy import select

from app.core.db import get_session
from app.core.log import logger
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import Statistics


def update_donation_credits(old_multiplier, new_multiplier):
    """
    更新捐赠积分

    Args:
        old_multiplier: 旧的积分倍数
        new_multiplier: 新的积分倍数
    """
    try:
        # 获取所有捐赠记录
        with get_session() as session:
            stmt = select(
                Statistics.tg_id, Statistics.donation, Statistics.credits
            ).where(Statistics.donation > 0)
            donations = session.execute(stmt).fetchall()

        for tg_id, donation, credits in donations:
            delta = round(donation * (new_multiplier - old_multiplier), 2)
            if delta > 0:
                credits_service.add(CreditAccount.tg(int(tg_id)), delta)
            elif delta < 0:
                credits_service.deduct(CreditAccount.tg(int(tg_id)), -delta)
            new_credits = round(credits + delta, 2)
            logger.info(
                f"用户 {tg_id} 捐赠：{donation}, 更新积分: {credits} -> {new_credits}"
            )

    except Exception as e:
        logger.error(str(e))
