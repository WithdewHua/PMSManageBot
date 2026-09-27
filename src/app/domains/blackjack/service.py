from app.core.log import logger
from app.domains.badges import service as badges_service
from app.domains.blackjack import repository as blackjack_repository
from app.domains.blackjack.repository import analytics as blackjack_analytics
from app.domains.luckywheel import service as luckywheel_service


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


def get_blackjack_jackpot() -> float:
    return blackjack_repository.get_blackjack_jackpot()


def seed_blackjack_jackpot(amount: float) -> float:
    return blackjack_repository.seed_blackjack_jackpot(amount)


def get_blackjack_free_hands_remaining(tg_id: int) -> int:
    return blackjack_repository.get_blackjack_free_hands_remaining(tg_id)


def get_current_blackjack_hand(tg_id: int) -> dict | None:
    return blackjack_repository.get_current_blackjack_hand(tg_id)


def list_active_blackjack_hands() -> list[dict]:
    return blackjack_repository.list_active_blackjack_hands()


def get_blackjack_admin_stats() -> dict:
    return blackjack_repository.get_blackjack_admin_stats()


def set_blackjack_config(config_key: str, config_json: str) -> bool:
    return blackjack_repository.set_blackjack_config(config_key, config_json)


def create_blackjack_hand(tg_id: int, bet_credits: int) -> dict:
    return blackjack_repository.create_blackjack_hand(tg_id, bet_credits)


def blackjack_hit(tg_id: int, hand_id: int) -> dict:
    return blackjack_repository.blackjack_hit(tg_id, hand_id)


def blackjack_stand(tg_id: int, hand_id: int) -> dict:
    return blackjack_repository.blackjack_stand(tg_id, hand_id)


def blackjack_double(tg_id: int, hand_id: int) -> dict:
    return blackjack_repository.blackjack_double(tg_id, hand_id)


def blackjack_surrender(tg_id: int, hand_id: int) -> dict:
    return blackjack_repository.blackjack_surrender(tg_id, hand_id)


def settle_blackjack_hand_by_timeout(hand_id: int) -> dict:
    return blackjack_repository.settle_blackjack_hand_by_timeout(hand_id)


def sweep_timed_out_blackjack_hands(tg_id: int | None = None) -> int:
    return blackjack_repository.sweep_timed_out_blackjack_hands(tg_id)


def settle_blackjack_weekly_cashback() -> dict:
    return blackjack_repository.settle_blackjack_weekly_cashback()


def claim_unannounced_jackpot_wins() -> list[dict]:
    return blackjack_repository.claim_unannounced_jackpot_wins()


def claim_unnotified_blackjack_freespins() -> list:
    return luckywheel_service.claim_unnotified_blackjack_freespins()


def list_expiring_blackjack_freespins(*, within_ms: int = 86400 * 1000) -> list[dict]:
    return luckywheel_service.list_expiring_blackjack_freespins(within_ms=within_ms)


def get_blackjack_freespin_summary(tg_id: int) -> dict:
    return luckywheel_service.get_blackjack_freespin_summary(tg_id)


def consume_blackjack_freespin(tg_id: int) -> dict | None:
    return luckywheel_service.consume_blackjack_freespin(tg_id)


def release_blackjack_freespin(spin_id: int, *, claimed_at_ms: int) -> bool:
    return luckywheel_service.release_blackjack_freespin(
        spin_id, claimed_at_ms=claimed_at_ms
    )


def get_blackjack_tournament_wallet(tg_id: int) -> float:
    return blackjack_repository.get_blackjack_tournament_wallet(tg_id)


def get_blackjack_tournament(
    tournament_id: int, tg_id: int | None = None
) -> dict | None:
    return blackjack_repository.get_blackjack_tournament(tournament_id, tg_id)


def list_blackjack_tournaments(
    tg_id: int | None = None,
    statuses: tuple | None = None,
    limit: int = 20,
) -> list[dict]:
    return blackjack_repository.list_blackjack_tournaments(tg_id, statuses, limit)


def list_blackjack_tournaments_with_playing_entries(
    tournament_ids: list[int],
) -> list[dict] | set[int] | None:
    return blackjack_repository.list_blackjack_tournaments_with_playing_entries(
        tournament_ids
    )


def count_registering_blackjack_tournaments(now_ms: int) -> int | None:
    return blackjack_repository.count_registering_blackjack_tournaments(now_ms)


def get_blackjack_tournament_standings(tournament_id: int) -> list[dict]:
    return blackjack_repository.get_blackjack_tournament_standings(tournament_id)


def get_user_blackjack_tournament_entry(tg_id: int, tournament_id: int) -> dict | None:
    return blackjack_repository.get_user_blackjack_tournament_entry(
        tg_id, tournament_id
    )


def create_blackjack_tournament(params: dict, created_by: int | None = None) -> dict:
    return blackjack_repository.create_blackjack_tournament(params, created_by)


def update_blackjack_tournament(tournament_id: int, params: dict) -> dict:
    return blackjack_repository.update_blackjack_tournament(tournament_id, params)


def register_blackjack_tournament(tg_id: int, tournament_id: int) -> dict:
    return blackjack_repository.register_blackjack_tournament(tg_id, tournament_id)


def start_blackjack_tournament(tournament_id: int) -> dict:
    return blackjack_repository.start_blackjack_tournament(tournament_id)


def cancel_blackjack_tournament(
    tournament_id: int, reason: str = "insufficient_entrants"
) -> dict:
    return blackjack_repository.cancel_blackjack_tournament(tournament_id, reason)


def claim_tournament_reminder(tournament_id: int) -> dict:
    return blackjack_repository.claim_tournament_reminder(tournament_id)


def create_blackjack_tournament_hand(
    tg_id: int, tournament_id: int, bet_chips: int
) -> dict:
    return blackjack_repository.create_blackjack_tournament_hand(
        tg_id, tournament_id, bet_chips
    )


def blackjack_tournament_hit(tg_id: int, hand_id: int) -> dict:
    return blackjack_repository.blackjack_tournament_hit(tg_id, hand_id)


def blackjack_tournament_stand(tg_id: int, hand_id: int) -> dict:
    return blackjack_repository.blackjack_tournament_stand(tg_id, hand_id)


def blackjack_tournament_double(tg_id: int, hand_id: int) -> dict:
    return blackjack_repository.blackjack_tournament_double(tg_id, hand_id)


def blackjack_tournament_surrender(tg_id: int, hand_id: int) -> dict:
    return blackjack_repository.blackjack_tournament_surrender(tg_id, hand_id)


def force_settle_tournament_hands(tournament_id: int) -> dict:
    return blackjack_repository.force_settle_tournament_hands(tournament_id)


def settle_blackjack_tournament(tournament_id: int) -> dict:
    return blackjack_repository.settle_blackjack_tournament(tournament_id)


def check_blackjack_tournament_consistency(tournament_id: int) -> dict | None:
    return blackjack_repository.check_blackjack_tournament_consistency(tournament_id)
