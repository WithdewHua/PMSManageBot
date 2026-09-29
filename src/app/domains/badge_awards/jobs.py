import asyncio
from time import time

from sqlalchemy import distinct, func, select, union

from app.core.db import get_session
from app.core.log import logger
from app.domains.badges import service as badges_service
from app.domains.badges.models import UserBadge
from app.domains.blackjack import service as blackjack_service
from app.domains.identity.models import Statistics
from app.domains.luckywheel.models import WheelStats
from app.domains.prediction.models import PredictionBet
from app.domains.treasure.models import TreasureParticipation
from app.integrations.telegram.messaging import send_message_by_url


async def check_and_award_supreme_contributor_badge(user_id: int | None = None):
    """
    检查并授予至尊贡献者勋章

    Args:
        user_id: 可选，指定用户的 Telegram ID。如果提供，只检查该用户；否则检查所有符合条件的用户。

    Returns:
        bool: 当指定 user_id 时，返回是否成功授予勋章；批量检查时返回 None
    """
    DONATION_THRESHOLD = 1688
    BADGE_TYPE = "supreme_contributor"

    if user_id:
        logger.info(f"检查用户 {user_id} 的至尊贡献者勋章资格...")
    else:
        logger.info("开始检查并授予至尊贡献者勋章...")

    try:
        # 1. 检查勋章是否存在，不存在则创建
        badge_info = badges_service.get_badge_by_type(BADGE_TYPE)
        if not badge_info:
            logger.info(f"勋章 '{BADGE_TYPE}' 不存在，正在创建...")
            badge_info = badges_service.create_badge(
                badge_type=BADGE_TYPE,
                name="至尊贡献者勋章",
                description="此勋章授予对平台有特殊贡献的用户",
                icon_url="/badges/supreme_contributor.svg",
                credits_cost=0,  # 由系统自动授予，不需要积分
                bonus_percentage=0.18,  # 18% 每日积分加成
                valid_days=36500,  # 约 100 年有效期
                is_enabled=0,  # 禁用兑换，仅由系统授予
            )
            if not badge_info:
                logger.error("创建至尊贡献者勋章失败")
                return False if user_id else None
            logger.info(f"成功创建至尊贡献者勋章，ID: {badge_info['id']}")

        badge_id = badge_info["id"]
        badge_name = badge_info.get("name", "至尊贡献者勋章")
        bonus_percentage = badge_info.get("bonus_percentage", 0.18)
        valid_days = badge_info.get("valid_days", 36500)

        # 2. 查询符合条件的用户
        with get_session() as session:
            if user_id:
                # 单用户模式：只查询指定用户
                user_donation = session.execute(
                    select(Statistics.donation).where(Statistics.tg_id == user_id)
                ).scalar_one_or_none()

                if user_donation is None or user_donation <= DONATION_THRESHOLD:
                    logger.info(
                        f"用户 {user_id} 捐赠金额 {user_donation} 未达到至尊贡献者门槛 {DONATION_THRESHOLD}"
                    )
                    return False

                eligible_users = [(user_id, user_donation)]
            else:
                # 批量模式：查询所有符合条件的用户
                stmt = select(Statistics.tg_id, Statistics.donation).where(
                    Statistics.donation > DONATION_THRESHOLD
                )
                eligible_users = session.execute(stmt).fetchall()

        if not eligible_users:
            if not user_id:
                logger.info(f"没有找到捐赠金额超过 {DONATION_THRESHOLD} 的用户")
            return False if user_id else None

        if not user_id:
            logger.info(f"找到 {len(eligible_users)} 位符合条件的用户")

        # 3. 为符合条件的用户授予勋章
        notification_tasks = []
        awarded_count = 0

        for tg_id, donation in eligible_users:
            try:
                with get_session() as session:
                    # 检查用户是否已拥有该勋章
                    existing = session.execute(
                        select(UserBadge).where(
                            UserBadge.tg_id == tg_id, UserBadge.badge_id == badge_id
                        )
                    ).scalar_one_or_none()

                    if existing:
                        if user_id:
                            logger.info(f"用户 {tg_id} 已拥有至尊贡献者勋章")
                            return False
                        continue

                    # 创建用户勋章记录
                    current_time = int(time())
                    expires_at = current_time + (valid_days * 24 * 3600)

                    user_badge_record = UserBadge(
                        tg_id=tg_id,
                        badge_id=badge_id,
                        credits_cost=0,
                        redeemed_at=current_time,
                        expires_at=expires_at,
                        is_active=1,
                    )
                    session.add(user_badge_record)

                    awarded_count += 1
                    logger.info(
                        f"已授予用户 {tg_id} (捐赠: {donation:.2f}) 至尊贡献者勋章"
                    )

                    # 添加用户通知任务
                    notification_tasks.append(
                        (
                            tg_id,
                            f"""🏆 恭喜获得勋章！
====================

勋章名称：{badge_name}
勋章权益：每日观看积分 +{bonus_percentage * 100:.0f}%
有效期限：永久

感谢您的支持与贡献！

====================""",
                        )
                    )

            except Exception as e:
                logger.error(f"授予用户 {tg_id} 勋章失败: {e}")
                if user_id:
                    return False
                continue

        if not user_id:
            if awarded_count > 0:
                logger.info(f"本次共授予 {awarded_count} 位用户至尊贡献者勋章")
            else:
                logger.info("所有符合条件的用户都已拥有至尊贡献者勋章")

        # 发送用户通知
        for tg_id, text in notification_tasks:
            try:
                await send_message_by_url(
                    chat_id=tg_id, text=text, disable_notification=False
                )
                if not user_id:
                    await asyncio.sleep(0.5)  # 批量模式下避免发送过于频繁
            except Exception as e:
                logger.warning(f"向用户 {tg_id} 发送勋章授予通知失败: {e}")

        return awarded_count > 0 if user_id else None

    except Exception as e:
        logger.error(f"检查并授予至尊贡献者勋章失败: {e}")
        return False if user_id else None


async def check_and_award_game_king_badge(
    user_id: int | None = None,
) -> bool | None:
    """
    检查并授予游戏王勋章。

    获取条件（满足任一）：
    - 幸运大转盘累计游戏次数 >= 5000 次
    - 夺宝奇兵累计参与期数 >= 500 期
    - 大预言家累计参与预测次数 >= 500 次
    - 21 点累计手数 >= 2000 手**且**决策准确率 >= 80%

    Args:
        user_id: 可选，指定用户的 Telegram ID。如果提供，只检查该用户；否则检查所有符合条件的用户。

    Returns:
        bool: 当指定 user_id 时，返回是否成功授予勋章；批量检查时返回 None。
    """
    WHEEL_SPIN_THRESHOLD = 5000
    TREASURE_ISSUE_THRESHOLD = 500
    PREDICTION_BET_THRESHOLD = 500
    # 21 点按平均注额 15 计，等价投入量约 3300 手；取 2000 手略低于等价投入量，
    # 因为单手需多次交互、耗时显著长于转盘一次点击，按投入量对等设定会形同虚设。
    #
    # 但**单以手数为条件是负期望游戏里的纯刷量激励**（2000 手 @ 注 15 的期望代价
    # 是 −720 积分）。叠加决策准确率后，这条件奖励的变成「把牌打好」而非「打得多」。
    # 80% 是刻意留出余地的阈值：严格照基本策略打是 100%，凭直觉打大约 70–85%。
    #
    # 两个阈值取自 21 点配置而非写死：spec 要求管理员可在线调整，SHALL NOT 需要
    # 重新部署。其余三个活动的阈值本就不属于 21 点，维持原样。
    _bj_config = blackjack_service.get_blackjack_config_dict()
    BLACKJACK_HAND_THRESHOLD = int(_bj_config.get("badge_min_hands", 2000))
    BLACKJACK_ACCURACY_THRESHOLD = float(_bj_config.get("badge_min_accuracy", 80))
    # 终态集合以引擎常量为单一来源，避免与 db 层的口径各自漂移
    BADGE_TYPE = "game_king"

    if user_id:
        logger.info(f"检查用户 {user_id} 的游戏王勋章资格...")
    else:
        logger.info("开始批量检查并授予游戏王勋章...")

    try:
        # 1. 检查勋章是否存在，不存在则创建
        badge_info = badges_service.get_badge_by_type(BADGE_TYPE)
        if not badge_info:
            logger.info(f"勋章 '{BADGE_TYPE}' 不存在，正在创建...")
            badge_info = badges_service.create_badge(
                badge_type=BADGE_TYPE,
                name="游戏王勋章",
                description=(
                    f"此勋章授予游戏达人：大转盘累计游戏 {WHEEL_SPIN_THRESHOLD} 次，"
                    f"或夺宝奇兵累计参与 {TREASURE_ISSUE_THRESHOLD} 期，"
                    f"或大预言家累计参与预测 {PREDICTION_BET_THRESHOLD} 次，"
                    f"或 21 点累计 {BLACKJACK_HAND_THRESHOLD} 手"
                    f"且决策准确率达 {int(BLACKJACK_ACCURACY_THRESHOLD)}%"
                ),
                icon_url="/badges/game_king.svg",
                credits_cost=0,
                bonus_percentage=0,
                valid_days=36500,  # 约 100 年，永久有效
                is_enabled=0,  # 禁用兑换，仅由系统授予
            )
            if not badge_info:
                logger.error("创建游戏王勋章失败")
                return False if user_id else None
            logger.info(f"成功创建游戏王勋章，ID: {badge_info['id']}")

        badge_id = badge_info["id"]
        badge_name = badge_info.get("name", "游戏王勋章")
        valid_days = badge_info.get("valid_days", 36500)

        # 21 点的双条件统计在**开启事务之前**取好：get_user_blackjack_stats 自带
        # 一个 get_session()，在下方的 with 块内调用会同时占用两个连接。
        blackjack_count = 0
        blackjack_accuracy = 0.0
        if user_id:
            blackjack_stats = blackjack_service.get_user_blackjack_stats(user_id)
            blackjack_count = int(blackjack_stats.get("total_hands") or 0)
            blackjack_accuracy = float(blackjack_stats.get("accuracy") or 0)

        # 2. 查询符合条件的用户
        with get_session() as session:
            if user_id:
                # 单用户模式：分别检查大转盘次数、夺宝参与期数、大预言家预测次数、21 点手数
                wheel_count = (
                    session.execute(
                        select(func.count(WheelStats.id)).where(
                            WheelStats.tg_id == user_id
                        )
                    ).scalar()
                    or 0
                )
                treasure_count = (
                    session.execute(
                        select(
                            func.count(distinct(TreasureParticipation.issue_id))
                        ).where(TreasureParticipation.tg_id == user_id)
                    ).scalar()
                    or 0
                )
                prediction_count = (
                    session.execute(
                        select(func.count(PredictionBet.id)).where(
                            PredictionBet.tg_id == user_id
                        )
                    ).scalar()
                    or 0
                )
                # 21 点为双条件：手数 + 决策准确率，两者须同时满足。
                # 统计已在事务外取好，见上方注释。
                blackjack_ok = (
                    blackjack_count >= BLACKJACK_HAND_THRESHOLD
                    and blackjack_accuracy >= BLACKJACK_ACCURACY_THRESHOLD
                )

                if (
                    wheel_count < WHEEL_SPIN_THRESHOLD
                    and treasure_count < TREASURE_ISSUE_THRESHOLD
                    and prediction_count < PREDICTION_BET_THRESHOLD
                    and not blackjack_ok
                ):
                    logger.info(
                        f"用户 {user_id} 不满足游戏王条件："
                        f"大转盘 {wheel_count}/{WHEEL_SPIN_THRESHOLD} 次，"
                        f"夺宝期数 {treasure_count}/{TREASURE_ISSUE_THRESHOLD} 期，"
                        f"大预言家预测 {prediction_count}/{PREDICTION_BET_THRESHOLD} 次，"
                        f"21 点 {blackjack_count}/{BLACKJACK_HAND_THRESHOLD} 手 "
                        f"且准确率 {blackjack_accuracy:.1f}%/{BLACKJACK_ACCURACY_THRESHOLD}%"
                    )
                    return False

                eligible_tg_ids = [user_id]
            else:
                # 批量模式：用 UNION 合并大转盘、夺宝奇兵、大预言家、21 点四个子查询
                wheel_subq = (
                    select(WheelStats.tg_id)
                    .group_by(WheelStats.tg_id)
                    .having(func.count(WheelStats.id) >= WHEEL_SPIN_THRESHOLD)
                )
                treasure_subq = (
                    select(TreasureParticipation.tg_id)
                    .group_by(TreasureParticipation.tg_id)
                    .having(
                        func.count(distinct(TreasureParticipation.issue_id))
                        >= TREASURE_ISSUE_THRESHOLD
                    )
                )
                prediction_subq = (
                    select(PredictionBet.tg_id)
                    .group_by(PredictionBet.tg_id)
                    .having(func.count(PredictionBet.id) >= PREDICTION_BET_THRESHOLD)
                )
                # 21 点资格查询由 blackjack repository 持有，避免本跨域作业
                # 直接依赖 blackjack ORM 模型；其余三个活动仍在本事务中合并。
                blackjack_tg_ids = blackjack_service.get_game_king_eligible_tg_ids_tx(
                    session,
                    BLACKJACK_HAND_THRESHOLD,
                    BLACKJACK_ACCURACY_THRESHOLD,
                )
                union_stmt = union(wheel_subq, treasure_subq, prediction_subq)
                rows = session.execute(union_stmt).fetchall()
                eligible_tg_ids = [row[0] for row in rows]
                eligible_tg_ids.extend(blackjack_tg_ids)
                eligible_tg_ids = list(dict.fromkeys(eligible_tg_ids))

        if not eligible_tg_ids:
            if not user_id:
                logger.info("没有找到符合游戏王条件的用户")
            return False if user_id else None

        if not user_id:
            logger.info(f"找到 {len(eligible_tg_ids)} 位符合游戏王条件的用户")

        # 3. 为符合条件的用户授予勋章
        notification_tasks = []
        awarded_count = 0

        for tg_id in eligible_tg_ids:
            try:
                with get_session() as session:
                    # 检查用户是否已拥有该勋章（幂等保护）
                    existing = session.execute(
                        select(UserBadge).where(
                            UserBadge.tg_id == tg_id, UserBadge.badge_id == badge_id
                        )
                    ).scalar_one_or_none()

                    if existing:
                        if user_id:
                            logger.info(f"用户 {tg_id} 已拥有游戏王勋章")
                            return False
                        continue

                    # 创建用户勋章记录
                    current_time = int(time())
                    expires_at = current_time + (valid_days * 24 * 3600)

                    user_badge_record = UserBadge(
                        tg_id=tg_id,
                        badge_id=badge_id,
                        credits_cost=0,
                        redeemed_at=current_time,
                        expires_at=expires_at,
                        is_active=1,
                    )
                    session.add(user_badge_record)

                    awarded_count += 1
                    logger.info(f"已授予用户 {tg_id} 游戏王勋章")

                    notification_tasks.append(
                        (
                            tg_id,
                            (
                                f"🎮 恭喜获得勋章！\n====================\n\n勋章名称：{badge_name}\n"
                                "有效期限：永久\n\n感谢您的热情参与！\n\n===================="
                            ),
                        )
                    )

            except Exception as e:
                logger.error(f"授予用户 {tg_id} 游戏王勋章失败: {e}")
                if user_id:
                    return False
                continue

        if not user_id:
            if awarded_count > 0:
                logger.info(f"本次共授予 {awarded_count} 位用户游戏王勋章")
            else:
                logger.info("所有符合条件的用户都已拥有游戏王勋章")

        # 4. 发送用户通知
        for tg_id, text in notification_tasks:
            try:
                await send_message_by_url(
                    chat_id=tg_id, text=text, disable_notification=False
                )
                if not user_id:
                    await asyncio.sleep(0.5)  # 批量模式下避免发送过于频繁
            except Exception as e:
                logger.warning(f"向用户 {tg_id} 发送游戏王勋章通知失败: {e}")

        return awarded_count > 0 if user_id else None

    except Exception as e:
        logger.error(f"检查并授予游戏王勋章失败: {e}")
        return False if user_id else None
