from sqlalchemy import and_, select

from app.domains.custom_lines.models import CustomLine


async def _get_expiring_soon_lines(
    session, current_time: int, one_day_later: int
) -> list[CustomLine]:
    """获取即将在1天内过期的线路"""
    stmt_expiring_soon = select(CustomLine).where(
        and_(
            CustomLine.status == "approved",
            CustomLine.is_permanent == 0,
            CustomLine.expires_at.isnot(None),
            CustomLine.expires_at > current_time,  # 还没过期
            CustomLine.expires_at <= one_day_later,  # 但1天内会过期
        )
    )

    result = session.execute(stmt_expiring_soon)
    return result.scalars().all()


async def _get_expired_lines(session, current_time: int) -> list[CustomLine]:
    """获取已经过期的线路"""
    stmt_expired = select(CustomLine).where(
        and_(
            CustomLine.status == "approved",
            CustomLine.is_permanent == 0,
            CustomLine.expires_at.isnot(None),
            CustomLine.expires_at <= current_time,
        )
    )

    result = session.execute(stmt_expired)
    return result.scalars().all()
