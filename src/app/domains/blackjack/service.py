from app.core.log import logger
from app.domains.badges import service as badges_service
from app.domains.blackjack import repository as blackjack_repository
from app.domains.blackjack.repository import analytics as blackjack_analytics


async def award_blackjack_champion_badge(tg_id: int) -> dict | None:
    """给锦标赛冠军授予/续期「21 点冠军」勋章。

    照 `game_king` 的形状：勋章不存在时**自动创建**，故本变更不需要预置数据或
    数据迁移。`credits_cost=0` 且 `is_enabled=0` —— 仅由系统授予，不可用积分兑换。

    与 `game_king` 的关键区别是**再次夺冠要续期而非跳过**：`game_king` 是一次性
    成就，而冠军是可以反复拿的，若沿用「有则跳过」，连庄的人第二次夺冠什么都得
    不到。续期语义见 `db.award_or_renew_badge`。

    加成 5% 每日观看积分、30 天有效期，上限由配置的 `tournament_badge_cap_days`
    给出。**这是一条增发路径**（约 0.4 积分/天/人），量级相对大转盘的回收可忽略，
    但仍在此显式记账。

    Returns: 授予结果 dict，失败返回 None。
    """
    from app.domains.blackjack.config import (
        CHAMPION_BADGE_BONUS,
        CHAMPION_BADGE_TYPE,
        CHAMPION_BADGE_VALID_DAYS,
    )

    try:
        badge_info = badges_service.get_badge_by_type(CHAMPION_BADGE_TYPE)
        if not badge_info:
            logger.info(f"勋章 '{CHAMPION_BADGE_TYPE}' 不存在，正在创建...")
            badge_info = badges_service.create_badge(
                badge_type=CHAMPION_BADGE_TYPE,
                name="21 点冠军勋章",
                description=(
                    "此勋章授予 21 点锦标赛的冠军："
                    f"持有永久，每日观看积分 +{int(CHAMPION_BADGE_BONUS * 100)}%，"
                    f"加成有效期 {CHAMPION_BADGE_VALID_DAYS} 天，再次夺冠可续期"
                ),
                icon_url="/badges/blackjack_champion.svg",
                credits_cost=0,
                bonus_percentage=CHAMPION_BADGE_BONUS,
                valid_days=CHAMPION_BADGE_VALID_DAYS,
                is_enabled=0,  # 禁用兑换，仅由系统授予
            )
            if not badge_info:
                logger.error("创建 21 点冠军勋章失败")
                return None

        config = blackjack_repository.get_blackjack_config_dict()
        cap_days = int(config.get("tournament_badge_cap_days", 90))
        valid_days = int(badge_info.get("valid_days", CHAMPION_BADGE_VALID_DAYS))

        result = badges_service.award_or_renew_badge(
            tg_id=int(tg_id),
            badge_id=int(badge_info["id"]),
            valid_days=valid_days,
            cap_days=cap_days,
        )
        if result.get("awarded"):
            logger.info(f"已向用户 {tg_id} 授予 21 点冠军勋章")
        elif result.get("renewed"):
            logger.info(
                f"用户 {tg_id} 的 21 点冠军勋章加成已续期至 {result['expires_at']}"
            )
        return result
    except Exception as e:
        logger.error(f"授予 21 点冠军勋章失败 (tg_id={tg_id}): {e}")
        return None


def get_blackjack_config_dict() -> dict:
    return blackjack_repository.get_blackjack_config_dict()


def get_blackjack_skill_ranks(min_hands: int | None = None) -> dict:
    return blackjack_analytics.get_blackjack_skill_ranks(min_hands)


def get_blackjack_max_win_rank() -> list:
    return blackjack_analytics.get_blackjack_max_win_rank()


def get_user_blackjack_stats(tg_id: int) -> dict:
    return blackjack_repository.get_user_blackjack_stats(tg_id)


def count_eligible_cash_hands_tx(
    session,
    tg_id: int,
    since: int,
    until: int,
    *,
    min_bet: float | None = None,
    min_accuracy: float | None = None,
) -> int | tuple[int, float]:
    return blackjack_analytics.count_eligible_cash_hands_tx(
        session,
        tg_id,
        since,
        until,
        min_bet=min_bet,
        min_accuracy=min_accuracy,
    )


def count_tournament_entries_tx(session, tg_id: int, since: int, until: int) -> int:
    return blackjack_analytics.count_tournament_entries_tx(session, tg_id, since, until)


def get_game_king_eligible_tg_ids_tx(
    session, min_hands: int, min_accuracy: float
) -> list[int]:
    return blackjack_analytics.get_game_king_eligible_tg_ids_tx(
        session, min_hands, min_accuracy
    )
