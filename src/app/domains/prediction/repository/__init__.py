from .analytics import _PredictionRepositoryAnalytics
from .bets import _PredictionRepositoryBets
from .markets import (
    _PredictionRepositoryMarkets,
)
from .markets import (
    list_prediction_markets_closing_soon as _list_prediction_markets_closing_soon,
)
from .settlement import (
    _PredictionRepositorySettlement,
)
from .settlement import (
    reward_prediction_submission as _reward_prediction_submission,
)


class PredictionRepository(
    _PredictionRepositoryMarkets,
    _PredictionRepositoryBets,
    _PredictionRepositorySettlement,
    _PredictionRepositoryAnalytics,
):
    """Private compatibility implementation."""


_repository = PredictionRepository()


def list_prediction_markets(limit: int = 50, include_closed: bool = True) -> list[dict]:
    return _repository.list_prediction_markets(limit, include_closed)


def get_prediction_market_by_id(
    market_id: int, tg_id: int | None = None
) -> dict | None:
    return _repository.get_prediction_market_by_id(market_id, tg_id)


def list_prediction_bets(market_id: int, limit: int = 100) -> list[dict]:
    return _repository.list_prediction_bets(market_id, limit)


def list_prediction_user_positions(market_id: int) -> list[dict]:
    return _repository.list_prediction_user_positions(market_id)


def place_prediction_bet(market_id: int, tg_id: int, option: int, amount: int) -> dict:
    return _repository.place_prediction_bet(market_id, tg_id, option, amount)


def create_prediction_market(
    title: str,
    description: str | None = None,
    betting_deadline: int | None = None,
    created_by: int | None = None,
    virtual_yes_pool: int = 500,
    virtual_no_pool: int = 500,
    fee_rate_bp: int = 500,
    fee_burn_bp: int = 300,
    fee_glory_bp: int = 200,
    max_bet_per_user: int = 500,
) -> int:
    return _repository.create_prediction_market(
        title=title,
        description=description,
        betting_deadline=betting_deadline,
        created_by=created_by,
        virtual_yes_pool=virtual_yes_pool,
        virtual_no_pool=virtual_no_pool,
        fee_rate_bp=fee_rate_bp,
        fee_burn_bp=fee_burn_bp,
        fee_glory_bp=fee_glory_bp,
        max_bet_per_user=max_bet_per_user,
    )


def submit_prediction_market(
    title: str,
    betting_deadline: int,
    submitter_tg_id: int,
    description: str | None = None,
) -> int:
    return _repository.submit_prediction_market(
        title=title,
        betting_deadline=betting_deadline,
        submitter_tg_id=submitter_tg_id,
        description=description,
    )


def list_prediction_submissions(
    status: int | None = None,
    limit: int = 50,
    submitter_tg_id: int | None = None,
) -> list[dict]:
    return _repository.list_prediction_submissions(
        status=status,
        limit=limit,
        submitter_tg_id=submitter_tg_id,
    )


def review_prediction_submission(
    submission_id: int,
    admin_tg_id: int,
    approved: bool,
    review_note: str | None = None,
    title: str | None = None,
    description: str | None = None,
    betting_deadline: int | None = None,
) -> dict:
    return _repository.review_prediction_submission(
        submission_id=submission_id,
        admin_tg_id=admin_tg_id,
        approved=approved,
        review_note=review_note,
        title=title,
        description=description,
        betting_deadline=betting_deadline,
    )


def close_prediction_market_betting(market_id: int) -> dict:
    return _repository.close_prediction_market_betting(market_id)


def resolve_prediction_market(
    market_id: int,
    result_option: int,
    resolved_by: int,
    resolution_note: str | None = None,
) -> dict:
    return _repository.resolve_prediction_market(
        market_id=market_id,
        result_option=result_option,
        resolved_by=resolved_by,
        resolution_note=resolution_note,
    )


def resolve_prediction_market_with_payouts(
    market_id: int,
    result_option: int,
    resolved_by: int,
    resolution_note: str | None = None,
) -> dict:
    return _repository.resolve_prediction_market(
        market_id=market_id,
        result_option=result_option,
        resolved_by=resolved_by,
        resolution_note=resolution_note,
        _include_payouts=True,
    )


def get_prediction_user_stats(tg_id: int) -> dict:
    return _repository.get_prediction_user_stats(tg_id)


def list_prediction_markets_closing_soon(
    now_ts: int, deadline_upper_ts: int
) -> list[dict]:
    return _list_prediction_markets_closing_soon(now_ts, deadline_upper_ts)


def reward_prediction_submission(submitter_tg_id: int) -> int:
    return _reward_prediction_submission(submitter_tg_id)


from .analytics import count_bets_tx as count_bets_tx

__all__ = [
    "PredictionRepository",
    "close_prediction_market_betting",
    "count_bets_tx",
    "create_prediction_market",
    "get_prediction_market_by_id",
    "get_prediction_user_stats",
    "list_prediction_bets",
    "list_prediction_markets",
    "list_prediction_markets_closing_soon",
    "list_prediction_submissions",
    "list_prediction_user_positions",
    "place_prediction_bet",
    "resolve_prediction_market",
    "resolve_prediction_market_with_payouts",
    "review_prediction_submission",
    "reward_prediction_submission",
    "submit_prediction_market",
]
