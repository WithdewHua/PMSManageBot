"""Cross-domain badge checks; synchronous domain APIs run off the event loop."""

import asyncio
from collections.abc import Callable
from typing import Protocol

from app.core.log import logger
from app.domains.badges import service as badges_service
from app.domains.blackjack import service as blackjack_service
from app.domains.donation import service as donation_service
from app.domains.luckywheel import service as luckywheel_service
from app.domains.prediction import service as prediction_service
from app.domains.treasure import service as treasure_service
from app.integrations.telegram import messaging


class _UserEvent(Protocol):
    @property
    def tg_id(self) -> int: ...


def _check_supreme_contributor(user_id: int | None) -> list[tuple[int, str]]:
    badge_type = "supreme_contributor"
    badge = badges_service.get_badge_by_type(badge_type)
    if not badge:
        badge = badges_service.create_badge(
            badge_type=badge_type,
            name="至尊贡献者勋章",
            description="此勋章授予对平台有特殊贡献的用户",
            icon_url="/badges/supreme_contributor.svg",
            credits_cost=0,
            bonus_percentage=0.18,
            valid_days=36500,
            is_enabled=0,
        )
    if not badge:
        return []
    notifications = []
    for tg_id, donation in donation_service.list_badge_eligible_donors(1688, user_id):
        try:
            if not badges_service.award_badge(tg_id, badge_type):
                continue
            logger.info(f"已授予用户 {tg_id} (捐赠: {donation:.2f}) 至尊贡献者勋章")
            notifications.append(
                (
                    tg_id,
                    f"""🏆 恭喜获得勋章！
====================

勋章名称：{badge.get("name", "至尊贡献者勋章")}
勋章权益：每日观看积分 +{badge.get("bonus_percentage", 0.18) * 100:.0f}%
有效期限：永久

感谢您的支持与贡献！

====================""",
                )
            )
        except Exception as error:
            logger.error(f"授予用户 {tg_id} 勋章失败: {error}")
    return notifications


def _check_game_king(user_id: int | None) -> list[tuple[int, str]]:
    config = blackjack_service.get_blackjack_config_dict()
    min_hands = int(config.get("badge_min_hands", 2000))
    min_accuracy = float(config.get("badge_min_accuracy", 80))
    badge_type = "game_king"
    badge = badges_service.get_badge_by_type(badge_type)
    if not badge:
        badge = badges_service.create_badge(
            badge_type=badge_type,
            name="游戏王勋章",
            description=(
                "此勋章授予游戏达人：大转盘累计游戏 5000 次，"
                "或夺宝奇兵累计参与 500 期，"
                "或大预言家累计参与预测 500 次，"
                f"或 21 点累计 {min_hands} 手且决策准确率达 {int(min_accuracy)}%"
            ),
            icon_url="/badges/game_king.svg",
            credits_cost=0,
            bonus_percentage=0,
            valid_days=36500,
            is_enabled=0,
        )
    if not badge:
        return []
    if user_id:
        # The single-user API intentionally uses rounded accuracy; batch eligibility
        # uses the repository's unrounded ratio, preserving the historical difference.
        stats = blackjack_service.get_user_blackjack_stats(user_id)
        blackjack_ok = (
            int(stats.get("total_hands") or 0) >= min_hands
            and float(stats.get("accuracy") or 0) >= min_accuracy
        )
        wheel_count = luckywheel_service.count_badge_spins(user_id)
        treasure_count = treasure_service.count_badge_issues(user_id)
        prediction_count = prediction_service.count_badge_bets(user_id)
        if not (
            blackjack_ok
            or wheel_count >= 5000
            or treasure_count >= 500
            or prediction_count >= 500
        ):
            return []
        candidates = [user_id]
    else:
        candidates = list(
            dict.fromkeys(
                [
                    *luckywheel_service.list_badge_eligible_tg_ids(5000),
                    *treasure_service.list_badge_eligible_tg_ids(500),
                    *prediction_service.list_badge_eligible_tg_ids(500),
                    *blackjack_service.get_game_king_eligible_tg_ids(
                        min_hands, min_accuracy
                    ),
                ]
            )
        )
    notifications = []
    for tg_id in candidates:
        try:
            if not badges_service.award_badge(tg_id, badge_type):
                continue
            logger.info(f"已授予用户 {tg_id} 游戏王勋章")
            notifications.append(
                (
                    tg_id,
                    (
                        f"🎮 恭喜获得勋章！\n====================\n\n勋章名称：{badge.get('name', '游戏王勋章')}\n"
                        "有效期限：永久\n\n感谢您的热情参与！\n\n===================="
                    ),
                )
            )
        except Exception as error:
            logger.error(f"授予用户 {tg_id} 游戏王勋章失败: {error}")
    return notifications


async def _check_and_notify(
    check: Callable[[int | None], list[tuple[int, str]]],
    user_id: int | None,
    label: str,
) -> bool | None:
    try:
        notifications = await asyncio.to_thread(check, user_id)
        for tg_id, text in notifications:
            try:
                await messaging.send_message_by_url(
                    chat_id=tg_id, text=text, disable_notification=False
                )
                if not user_id:
                    await asyncio.sleep(0.5)
            except Exception as error:
                logger.warning(f"向用户 {tg_id} 发送{label}勋章通知失败: {error}")
        return bool(notifications) if user_id else None
    except Exception as error:
        logger.error(f"检查并授予{label}勋章失败: {error}")
        return False if user_id else None


async def check_and_award_supreme_contributor_badge(
    user_id: int | None = None,
) -> bool | None:
    return await _check_and_notify(_check_supreme_contributor, user_id, "至尊贡献者")


async def check_and_award_game_king_badge(user_id: int | None = None) -> bool | None:
    return await _check_and_notify(_check_game_king, user_id, "游戏王")


async def on_game_activity(event: _UserEvent) -> None:
    await check_and_award_game_king_badge(event.tg_id)


async def on_donation(event: _UserEvent) -> None:
    await check_and_award_supreme_contributor_badge(event.tg_id)
