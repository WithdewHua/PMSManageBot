"""Run disposable PostgreSQL concurrency checks for prediction settlement.

Usage::

    DATABASE_URL=postgresql+psycopg2://... \
      python -m scripts.refactor.smoke_prediction_concurrency --url "$DATABASE_URL"

The target database is recreated for the run. Use only a disposable local
PostgreSQL database; this command deliberately drops all application tables.
"""

from __future__ import annotations

import argparse
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    return parser.parse_args()


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    args = _parse_args()
    os.environ["DATABASE_URL"] = args.url
    os.environ["DATABASE_TYPE"] = "postgresql"

    from sqlalchemy import func, select

    from app.core import db as db_module
    from app.core.kv import SystemConfig
    from app.domains.credits import repository as credits_repository
    from app.domains.identity.models import Statistics
    from app.domains.prediction import repository as prediction_repository
    from app.domains.prediction.exceptions import PredictionError
    from app.domains.prediction.models import PredictionBet, PredictionMarket
    from app.model_registry import metadata

    # The smoke run must not contact Redis or any external cache.
    credits_repository.invalidate_user_credits = lambda _keys: None

    metadata.drop_all(bind=db_module.engine)
    metadata.create_all(bind=db_module.engine)

    with db_module.get_session() as session:
        for tg_id in range(1, 5):
            session.add(Statistics(tg_id=tg_id, credits=1000, donation=0))
        markets = [
            PredictionMarket(
                title=f"concurrency-{index}",
                status=1,
                betting_deadline=4_100_000_000,
                real_yes_pool=0,
                real_no_pool=0,
                virtual_yes_pool=500,
                virtual_no_pool=500,
                fee_rate_bp=500,
                fee_burn_bp=300,
                fee_glory_bp=200,
                max_bet_per_user=500,
                created_by=999,
            )
            for index in (1, 2)
        ]
        session.add_all(markets)
        session.add(
            SystemConfig(
                config_type="prediction_market",
                config_key="glory_fund",
                config_value="10.5",
                created_at=1,
                updated_at=1,
            )
        )
        session.flush()
        market_ids = [int(market.id) for market in markets]

    # Give both settlements the same two winners. The resolver threads then
    # contend for the shared glory row and the same Statistics rows.
    for market_id in market_ids:
        prediction_repository.place_prediction_bet(
            market_id=market_id, tg_id=1, option=1, amount=10
        )
        prediction_repository.place_prediction_bet(
            market_id=market_id, tg_id=2, option=1, amount=10
        )

    barrier = threading.Barrier(6)

    def resolve(market_id: int) -> tuple[str, object]:
        barrier.wait()
        try:
            return "resolved", prediction_repository.resolve_prediction_market(
                market_id=market_id,
                result_option=1,
                resolved_by=999,
            )
        except Exception as error:
            return "error", error

    def bet(market_id: int, tg_id: int) -> tuple[str, object]:
        barrier.wait()
        try:
            return "bet", prediction_repository.place_prediction_bet(
                market_id=market_id,
                tg_id=tg_id,
                option=0,
                amount=1,
            )
        except PredictionError as error:
            # A bet racing a resolver is allowed to lose the market lock.
            return "rejected", error
        except Exception as error:
            return "error", error

    jobs = [
        (resolve, (market_ids[0],)),
        (resolve, (market_ids[1],)),
        (bet, (market_ids[0], 3)),
        (bet, (market_ids[0], 4)),
        (bet, (market_ids[1], 3)),
        (bet, (market_ids[1], 4)),
    ]
    results: list[tuple[str, object]] = []
    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        futures = [executor.submit(function, *args) for function, args in jobs]
        for future in as_completed(futures):
            results.append(future.result())

    errors = [value for kind, value in results if kind == "error"]
    _check(not errors, f"unexpected concurrent errors: {errors!r}")

    with db_module.get_session() as session:
        settled_count = session.execute(
            select(func.count(PredictionMarket.id)).where(PredictionMarket.status == 3)
        ).scalar_one()
        _check(int(settled_count) == 2, f"settled_count={settled_count}")

        bet_count = session.execute(select(func.count(PredictionBet.id))).scalar_one()
        _check(int(bet_count) >= 4, f"bet_count={bet_count}")

        stats = (
            session.execute(
                select(Statistics).where(Statistics.tg_id.in_([1, 2, 3, 4]))
            )
            .scalars()
            .all()
        )
        _check(all(float(row.credits) >= 0 for row in stats), "negative credits")

        glory = session.execute(
            select(SystemConfig.config_value).where(
                SystemConfig.config_type == "prediction_market",
                SystemConfig.config_key == "glory_fund",
            )
        ).scalar_one()
        _check(glory is not None, "glory fund missing")

    print(
        "prediction concurrency ok: "
        f"resolved={settled_count}, bets={bet_count}, results={len(results)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
