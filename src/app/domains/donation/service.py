from sqlalchemy import select
from sqlalchemy import update as sql_update

from app.core.db import get_session
from app.core.log import logger
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
            # 计算新的积分
            new_credits = round(
                credits + donation * (new_multiplier - old_multiplier), 2
            )
            # 更新数据库
            with get_session() as session:
                stmt = (
                    sql_update(Statistics)
                    .where(Statistics.tg_id == tg_id)
                    .values(credits=new_credits)
                )
                session.execute(stmt)
            logger.info(
                f"用户 {tg_id} 捐赠：{donation}, 更新积分: {credits} -> {new_credits}"
            )

    except Exception as e:
        logger.error(str(e))
