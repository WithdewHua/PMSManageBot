"""Run deterministic PostgreSQL concurrency checks for blackjack.

Usage::

    DATABASE_URL=postgresql+psycopg2://... \
      python -m scripts.refactor.smoke_blackjack_concurrency --url "$DATABASE_URL"

The command owns the target database for the duration of the run: it recreates
all application tables, seeds synthetic rows, verifies the invariants, and
leaves no production data behind. Never point it at a live application database
without an isolated database or a disposable container.

Covered invariants:

1. 同一手牌上的要牌/停牌/超时结算竞争：只结算一次，赔付只入账一次。
2. 并发报名：名额不超卖，每个人恰好扣一次报名费，钱包/积分拆分自洽。
3. 并发结算：只派奖一次，奖金总额与积分增加额一致，名次唯一。
4. 并发结算下的免费次数发放：每手恰好发放一次，不重复、不为负。
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor

BET = 15
BUY_IN = 30
NOW_MS = 1_800_000_000_000  # 固定时间基准，避免跨周/跨日漂移
BASE_CONFIG = {
    "enabled": True,
    "bet_options": [BET],
    "min_credits": 0,
    "min_deal_interval_seconds": 0,
    "rake_bp_on_profit": 0,
    "rake_burn_bp": 0,
    "rake_jackpot_bp": 0,
    "jackpot_enabled": False,
    "relief_enabled": False,
    "cashback_enabled": False,
    "freespins_enabled": False,
    "free_hands_per_day": 0,
    "surrender_enabled": True,
    "hand_timeout_minutes": 15,
    "tournament_notify_enabled": False,
    "tournament_defaults": {
        "buy_in_credits": BUY_IN,
        "starting_chips": 1000,
        "total_hands": 30,
        "min_bet_chips": 10,
        "max_bet_chips": 500,
        "bet_step_chips": 10,
        "min_entrants": 2,
        "max_entrants": 5,
        "rake_bp": 0,
        "payout_structure": [50, 30, 20],
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if not args.url.startswith("postgresql"):
        raise SystemExit("blackjack concurrency smoke requires a PostgreSQL URL")

    os.environ["DATABASE_URL"] = args.url
    os.environ["DATABASE_TYPE"] = "postgresql"

    from sqlalchemy import func, select, update
    from sqlalchemy.orm import sessionmaker

    import app.core.db as db_module
    from app.domains.blackjack import repository as blackjack_repository
    from app.domains.blackjack import service as blackjack_service
    from app.domains.blackjack.config import (
        ENTRY_FINISHED,
        TOURNAMENT_SETTLED,
    )
    from app.domains.blackjack.models import (
        BlackjackHand,
        BlackjackTournament,
        BlackjackTournamentEntry,
    )
    from app.domains.blackjack.rules import TERMINAL_STATUSES
    from app.domains.credits import service as credits_service
    from app.domains.identity.models import Statistics
    from app.domains.luckywheel.models import LuckywheelFreeSpin
    from app.model_registry import metadata

    credits_service.invalidate_cache_keys = lambda _keys: None

    engine = db_module.create_engine(
        args.url,
        pool_size=args.workers * 2,
        max_overflow=args.workers * 2,
        pool_pre_ping=True,
    )
    metadata.drop_all(engine)
    metadata.create_all(engine)
    db_module.engine = engine
    db_module.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )

    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{label}: {detail}")
            print(f"FAIL {label} {detail}")

    def run(workers: int, fn) -> list[Exception]:
        errors: list[Exception] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fn, index) for index in range(workers)]
            for future in futures:
                try:
                    future.result()
                except Exception as exc:
                    errors.append(exc)
        return errors

    def is_deadlock(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        return "deadlock" in text or "could not serialize" in text

    def apply_config(**overrides) -> None:
        config = {**BASE_CONFIG, **overrides}
        blackjack_repository.set_blackjack_config(
            "config", json.dumps(config, ensure_ascii=False)
        )

    def seed_user(tg_id: int, credits: float = 1000.0) -> None:
        with db_module.get_session() as session:
            session.add(
                Statistics(tg_id=int(tg_id), donation=0, credits=float(credits))
            )

    def credits_of(tg_id: int) -> float:
        with db_module.get_session() as session:
            row = session.execute(
                select(Statistics.credits).where(Statistics.tg_id == int(tg_id))
            ).scalar_one_or_none()
            return round(float(row or 0), 2)

    def hand_row(hand_id: int) -> dict:
        with db_module.get_session() as session:
            hand = session.get(BlackjackHand, int(hand_id))
            return {
                "status": int(hand.status),
                "payout_credits": float(hand.payout_credits or 0),
                "bet_credits": float(hand.bet_credits),
            }

    def freespin_count(tg_id: int) -> int:
        with db_module.get_session() as session:
            return int(
                session.execute(
                    select(func.count())
                    .select_from(LuckywheelFreeSpin)
                    .where(LuckywheelFreeSpin.tg_id == int(tg_id))
                ).scalar_one()
            )

    def tournament_row(tournament_id: int) -> dict:
        with db_module.get_session() as session:
            row = session.get(BlackjackTournament, int(tournament_id))
            return {"status": int(row.status), "entrant_count": int(row.entrant_count)}

    def entries_of(tournament_id: int) -> list[dict]:
        with db_module.get_session() as session:
            rows = (
                session.execute(
                    select(BlackjackTournamentEntry).where(
                        BlackjackTournamentEntry.tournament_id == int(tournament_id)
                    )
                )
                .scalars()
                .all()
            )
            return [
                {
                    "tg_id": int(row.tg_id),
                    "status": int(row.status),
                    "chips": int(row.chips),
                    "final_rank": row.final_rank,
                    "prize_credits": float(row.prize_credits or 0),
                    "wallet_paid": float(row.wallet_paid_credits or 0),
                    "credits_paid": float(row.credits_paid_credits or 0),
                }
                for row in rows
            ]

    # ---------------------------------------------------------------- S1
    apply_config()
    settled_hands = 0
    for index in range(12):
        tg_id = 5000 + index
        seed_user(tg_id, 1000.0)
        created = blackjack_service.create_blackjack_hand(tg_id, BET)
        if created.get("settled"):
            continue  # 天胡：发牌即结算，不参与竞争
        hand_id = int(created["hand"]["id"])
        before = credits_of(tg_id)

        def act(slot: int, hand_id: int = hand_id, tg_id: int = tg_id) -> None:
            if slot % 2:
                blackjack_service.blackjack_stand(tg_id, hand_id)
            else:
                blackjack_service.settle_blackjack_hand_by_timeout(hand_id)

        errors = run(args.workers, act)
        check(
            f"S1 hand {hand_id} no deadlock",
            not any(is_deadlock(exc) for exc in errors),
            repr([type(exc).__name__ for exc in errors]),
        )
        row = hand_row(hand_id)
        after = credits_of(tg_id)
        check(
            f"S1 hand {hand_id} settled exactly once",
            row["status"] in TERMINAL_STATUSES
            and after == round(before + row["payout_credits"], 2)
            and after >= 0,
            f"status={row['status']} before={before} after={after} payout={row['payout_credits']}",
        )
        settled_hands += 1
    check("S1 produced cash hands", settled_hands > 0, str(settled_hands))

    # ---------------------------------------------------------------- S2
    contenders = 12
    max_entrants = 5
    params = {
        **BASE_CONFIG["tournament_defaults"],
        "min_entrants": max_entrants,
        "max_entrants": max_entrants,
        "title": "concurrency smoke",
        "register_deadline_ms": NOW_MS + 2 * 3600 * 1000,
        "play_deadline_ms": NOW_MS + 6 * 3600 * 1000,
    }
    tournament = blackjack_service.create_blackjack_tournament(params, created_by=1)
    tournament_id = int(tournament["id"])
    for index in range(contenders):
        seed_user(7000 + index, 100.0)

    def register(slot: int) -> None:
        blackjack_service.register_blackjack_tournament(7000 + slot, tournament_id)

    errors = run(contenders, register)
    check(
        "S2 registration no deadlock",
        not any(is_deadlock(exc) for exc in errors),
        repr([type(exc).__name__ for exc in errors]),
    )
    entries = entries_of(tournament_id)
    state = tournament_row(tournament_id)
    check(
        "S2 seats are not oversold",
        len(entries) == max_entrants and state["entrant_count"] == max_entrants,
        f"entries={len(entries)} entrant_count={state['entrant_count']}",
    )
    check(
        "S2 every entry paid the buy-in exactly once",
        all(
            round(entry["wallet_paid"] + entry["credits_paid"], 2) == float(BUY_IN)
            for entry in entries
        ),
        repr(entries),
    )
    registrants = {entry["tg_id"] for entry in entries}
    check(
        "S2 credits deducted once per entry",
        all(
            credits_of(tg_id) == (100.0 - BUY_IN if tg_id in registrants else 100.0)
            for tg_id in (7000 + index for index in range(contenders))
        ),
        repr({tg_id: credits_of(tg_id) for tg_id in sorted(registrants)}),
    )

    # ---------------------------------------------------------------- S3
    with db_module.get_session() as session:
        session.execute(
            update(BlackjackTournamentEntry)
            .where(BlackjackTournamentEntry.tournament_id == tournament_id)
            .values(status=ENTRY_FINISHED, chips=1000 + BlackjackTournamentEntry.id)
        )
    ranked_ids = [entry["tg_id"] for entry in entries_of(tournament_id)]
    before_total = round(sum(credits_of(tg_id) for tg_id in ranked_ids), 2)

    def settle(slot: int) -> None:
        if slot % 2:
            blackjack_service.force_settle_tournament_hands(tournament_id)
        blackjack_service.settle_blackjack_tournament(tournament_id)

    errors = run(args.workers, settle)
    check(
        "S3 settlement no deadlock",
        not any(is_deadlock(exc) for exc in errors),
        repr([type(exc).__name__ for exc in errors]),
    )
    entries = entries_of(tournament_id)
    state = tournament_row(tournament_id)
    after_total = round(sum(credits_of(tg_id) for tg_id in ranked_ids), 2)
    prizes = round(sum(entry["prize_credits"] for entry in entries), 2)
    pool = round(BUY_IN * len(entries), 2)
    check(
        "S3 tournament settled once",
        state["status"] == TOURNAMENT_SETTLED,
        str(state),
    )
    check(
        "S3 prizes equal the pool and the credited delta",
        prizes == pool and round(after_total - before_total, 2) == prizes,
        f"prizes={prizes} pool={pool} delta={round(after_total - before_total, 2)}",
    )
    ranks = [entry["final_rank"] for entry in entries if entry["final_rank"]]
    check(
        "S3 ranks are unique",
        len(ranks) == len(set(ranks)) and len(ranks) == len(entries),
        repr(sorted(ranks)),
    )

    # ---------------------------------------------------------------- S4
    apply_config(
        freespins_enabled=True,
        freespins_hand_threshold=1,
        freespins_weekly_cap=100,
    )
    granted = 0
    for index in range(6):
        tg_id = 9000 + index
        seed_user(tg_id, 1000.0)
        created = blackjack_service.create_blackjack_hand(tg_id, BET)
        if created.get("settled"):
            continue
        hand_id = int(created["hand"]["id"])
        before_spins = freespin_count(tg_id)

        def act(slot: int, hand_id: int = hand_id, tg_id: int = tg_id) -> None:
            if slot % 2:
                blackjack_service.blackjack_stand(tg_id, hand_id)
            else:
                blackjack_service.settle_blackjack_hand_by_timeout(hand_id)

        errors = run(args.workers, act)
        check(
            f"S4 hand {hand_id} no deadlock",
            not any(is_deadlock(exc) for exc in errors),
            repr([type(exc).__name__ for exc in errors]),
        )
        after_spins = freespin_count(tg_id)
        check(
            f"S4 hand {hand_id} granted exactly one free spin",
            after_spins - before_spins == 1,
            f"before={before_spins} after={after_spins}",
        )
        check(f"S4 hand {hand_id} non-negative balance", credits_of(tg_id) >= 0)
        granted += 1
    check("S4 produced settled hands", granted > 0, str(granted))

    print(
        json.dumps(
            {
                "failures": failures,
                "settled_cash_hands": settled_hands,
                "free_spin_hands": granted,
                "ok": not failures,
            },
            ensure_ascii=False,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
