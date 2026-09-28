"""Prediction workflows and post-commit side effects.

Repository functions own SQLAlchemy sessions and transaction boundaries. This
module coordinates those committed results with notifications; it never opens a
session or performs ORM queries itself.
"""

from __future__ import annotations

import time

from app.core.log import logger
from app.domains.prediction import notifications as prediction_notifications
from app.domains.prediction import repository as prediction_repository


def list_prediction_markets(
    *, limit: int = 50, include_closed: bool = True
) -> list[dict]:
    return prediction_repository.list_prediction_markets(
        limit=limit, include_closed=include_closed
    )


def get_prediction_market_by_id(
    market_id: int, *, tg_id: int | None = None
) -> dict | None:
    return prediction_repository.get_prediction_market_by_id(market_id, tg_id)


def list_prediction_bets(market_id: int, *, limit: int = 100) -> list[dict]:
    return prediction_repository.list_prediction_bets(market_id, limit)


def list_prediction_submissions(
    *, status: int | None = None, limit: int = 50, submitter_tg_id: int | None = None
) -> list[dict]:
    return prediction_repository.list_prediction_submissions(
        status=status,
        limit=limit,
        submitter_tg_id=submitter_tg_id,
    )


def list_prediction_user_positions(market_id: int) -> list[dict]:
    return prediction_repository.list_prediction_user_positions(market_id)


async def place_prediction_bet(
    *, market_id: int, tg_id: int, option: int, amount: int
) -> dict:
    result = prediction_repository.place_prediction_bet(
        market_id=market_id,
        tg_id=tg_id,
        option=option,
        amount=amount,
    )
    try:
        market = result.get("market") or {}
        await prediction_notifications.notify_prediction_bet_placed(
            market_id=int(market.get("id") or market_id),
            title=str(market.get("title") or ""),
            bettor_tg_id=int(tg_id),
            option=int(option),
            amount=int(amount),
            real_yes_pool=int(market.get("real_yes_pool") or 0),
            real_no_pool=int(market.get("real_no_pool") or 0),
        )
    except Exception as error:
        logger.warning(f"Prediction bet notify failed: {error}")
    return result


async def create_prediction_market(
    *,
    title: str,
    description: str | None = None,
    betting_deadline: int | None = None,
    created_by: int | None = None,
    virtual_yes_pool: int = 500,
    virtual_no_pool: int = 500,
    max_bet_per_user: int = 500,
) -> int:
    market_id = prediction_repository.create_prediction_market(
        title=title,
        description=description,
        betting_deadline=betting_deadline,
        created_by=created_by,
        virtual_yes_pool=virtual_yes_pool,
        virtual_no_pool=virtual_no_pool,
        max_bet_per_user=max_bet_per_user,
    )
    try:
        market = prediction_repository.get_prediction_market_by_id(market_id)
        if market:
            await prediction_notifications.notify_prediction_market_created(
                market_id=int(market_id),
                title=str(market.get("title") or ""),
                betting_deadline=market.get("betting_deadline"),
            )
    except Exception as error:
        logger.warning(f"Prediction create notify failed: {error}")
    return int(market_id)


async def submit_prediction_market(
    *,
    title: str,
    betting_deadline: int,
    submitter_tg_id: int,
    description: str | None = None,
) -> int:
    submission_id = prediction_repository.submit_prediction_market(
        title=title,
        betting_deadline=betting_deadline,
        submitter_tg_id=submitter_tg_id,
        description=description,
    )
    try:
        await prediction_notifications.notify_prediction_submission_created(
            submission_id=int(submission_id),
            title=str(title),
            betting_deadline=int(betting_deadline),
            submitter_tg_id=int(submitter_tg_id),
        )
    except Exception as error:
        logger.warning(f"Prediction submission notify failed: {error}")
    return int(submission_id)


async def review_prediction_submission(
    *,
    submission_id: int,
    admin_tg_id: int,
    approved: bool,
    review_note: str | None = None,
    title: str | None = None,
    description: str | None = None,
    betting_deadline: int | None = None,
) -> dict:
    result = prediction_repository.review_prediction_submission(
        submission_id=submission_id,
        admin_tg_id=admin_tg_id,
        approved=approved,
        review_note=review_note,
        title=title,
        description=description,
        betting_deadline=betting_deadline,
    )

    reward_credits = 0
    if bool(approved):
        try:
            submitter_tg_id = int(result.get("submitter_tg_id") or 0)
            if submitter_tg_id > 0:
                reward_credits = prediction_repository.reward_prediction_submission(
                    submitter_tg_id
                )
        except Exception as error:
            logger.warning(f"Prediction submission reward credits failed: {error}")

    try:
        if bool(approved) and result.get("market_id"):
            market = prediction_repository.get_prediction_market_by_id(
                int(result["market_id"])
            )
            if market:
                await prediction_notifications.notify_prediction_market_created(
                    market_id=int(market.get("id") or result["market_id"]),
                    title=str(market.get("title") or ""),
                    betting_deadline=market.get("betting_deadline"),
                )
    except Exception as error:
        logger.warning(f"Prediction publish notify failed: {error}")

    try:
        await prediction_notifications.notify_prediction_submission_reviewed(
            submitter_tg_id=int(result.get("submitter_tg_id") or 0),
            submission_id=int(submission_id),
            approved=bool(approved),
            title=str(result.get("title") or title or ""),
            review_note=review_note,
            reward_credits=int(reward_credits),
            market_id=int(result["market_id"]) if result.get("market_id") else None,
        )
    except Exception as error:
        logger.warning(f"Prediction submission review notify failed: {error}")
    return result


def close_prediction_market_betting(market_id: int) -> dict:
    return prediction_repository.close_prediction_market_betting(market_id)


async def resolve_prediction_market(
    *,
    market_id: int,
    result_option: int,
    resolved_by: int,
    resolution_note: str | None = None,
) -> dict:
    detailed = prediction_repository.resolve_prediction_market_with_payouts(
        market_id=market_id,
        result_option=result_option,
        resolved_by=resolved_by,
        resolution_note=resolution_note,
    )
    payouts = {
        int(tg_id): float(amount)
        for tg_id, amount in (detailed.pop("payouts", {}) or {}).items()
    }

    try:
        market = prediction_repository.get_prediction_market_by_id(market_id)
        if market:
            await prediction_notifications.notify_prediction_market_resolved(
                market_id=int(market_id),
                title=str(market.get("title") or ""),
                result_option=int(detailed.get("result_option") or result_option),
                total_real_pool=int(detailed.get("total_real_pool") or 0),
                payout_pool=int(detailed.get("payout_pool") or 0),
                total_fee=int(detailed.get("total_fee") or 0),
                fee_burned=int(detailed.get("fee_burned") or 0),
                fee_to_glory=int(detailed.get("fee_to_glory") or 0),
                winner_count=int(detailed.get("winner_count") or 0),
                resolution_note=market.get("resolution_note"),
            )

            positions = prediction_repository.list_prediction_user_positions(market_id)
            for position in positions:
                tg_id = int(position.get("tg_id") or 0)
                await prediction_notifications.notify_prediction_user_settlement(
                    tg_id=tg_id,
                    market_id=int(market_id),
                    title=str(market.get("title") or ""),
                    result_option=int(detailed.get("result_option") or result_option),
                    yes_amount=int(position.get("yes_amount") or 0),
                    no_amount=int(position.get("no_amount") or 0),
                    payout_amount=float(payouts.get(tg_id, 0.0)),
                )
            logger.info(
                "Prediction resolve personal notifications queued: "
                f"market_id={int(market_id)}, users={len(positions)}, "
                f"payouts={len(payouts)}"
            )
    except Exception as error:
        logger.warning(f"Prediction resolve notify failed: {error}")
    return detailed


async def check_prediction_markets_closing_soon() -> list[dict]:
    """查询并发送截止提醒；jobs 只负责调用这个 service。"""
    now_ts = int(time.time())
    deadline_upper_ts = int(now_ts + 6 * 3600)
    markets = prediction_repository.list_prediction_markets_closing_soon(
        now_ts, deadline_upper_ts
    )
    if not markets:
        logger.info("大预言家截止提醒检查完成：未来 6 小时内无押注截止题目")
        return []

    await prediction_notifications.notify_prediction_markets_closing_soon(
        markets=markets,
        threshold_hours=6,
    )
    logger.info(f"大预言家截止提醒已发送：count={len(markets)}, window=(now, now+6h]")
    return markets


def get_prediction_user_stats(tg_id: int) -> dict:
    return prediction_repository.get_prediction_user_stats(tg_id)


def get_prediction_net_profit_rank() -> list[dict]:
    """Expose the prediction-owned net-profit ranking to read-model services."""
    return prediction_repository.get_prediction_net_profit_rank()


def get_prediction_win_rate_rank() -> list[dict]:
    """Expose the prediction-owned win-rate ranking to read-model services."""
    return prediction_repository.get_prediction_win_rate_rank()


__all__ = [
    "check_prediction_markets_closing_soon",
    "close_prediction_market_betting",
    "create_prediction_market",
    "get_prediction_market_by_id",
    "get_prediction_net_profit_rank",
    "get_prediction_user_stats",
    "get_prediction_win_rate_rank",
    "list_prediction_bets",
    "list_prediction_markets",
    "list_prediction_submissions",
    "list_prediction_user_positions",
    "place_prediction_bet",
    "resolve_prediction_market",
    "review_prediction_submission",
    "submit_prediction_market",
]
