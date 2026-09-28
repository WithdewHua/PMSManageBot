"""Gift-pack PostgreSQL concurrency checks.

Usage::

    DATABASE_URL=postgresql+psycopg2://... \
      python -m scripts.refactor.smoke_gift_pack_concurrency --url "$DATABASE_URL"

The command owns the target database for the duration of the run: it recreates
all application tables, seeds synthetic rows and leaves no production data
behind. Never point it at a live application database.

Covered invariants:

1. 最后一份的争抢：限量 1 份时并发领取只成功一次，余量不超卖。
2. 同一用户并发领取：只记录一次领取、只发放一次奖励。
3. 礼包领取与线路调度解锁交叉进行（奖励顺序相反）：不死锁则两边状态自洽；
   当前代码存在 ABBA 加锁顺序，复现死锁时以 `s3.deadlock` 上报（5.1 修复）。
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

REWARD = 50.0
UNLOCK_COST = 10.0
ROUNDS = 30
WORKERS = 8


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    args = parser.parse_args()
    if not args.url.startswith("postgresql"):
        raise SystemExit("gift pack concurrency smoke requires a PostgreSQL URL")

    os.environ["DATABASE_URL"] = args.url
    os.environ["DATABASE_TYPE"] = "postgresql"

    from sqlalchemy import delete, func, select, update
    from sqlalchemy.orm import sessionmaker

    import app.core.db as db_module
    from app.domains.credits import service as credits_service
    from app.domains.gift_pack import service as gift_pack_service
    from app.domains.gift_pack.models import GiftPack, GiftPackUserState
    from app.domains.identity.models import PlexUser, Statistics
    from app.domains.lines import service as lines_service
    from app.model_registry import metadata

    credits_service.invalidate_cache_keys = lambda _keys: None

    engine = db_module.create_engine(
        args.url,
        pool_size=WORKERS * 2,
        max_overflow=WORKERS * 2,
        pool_pre_ping=True,
    )
    metadata.drop_all(engine)
    metadata.create_all(engine)
    db_module.engine = engine
    db_module.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )

    failures: list[str] = []
    report: dict[str, object] = {}

    def check(label: str, ok: bool, detail: str = "") -> None:
        if not ok:
            failures.append(f"{label}: {detail}")
            print(f"FAIL {label} {detail}")

    def is_deadlock(exc: BaseException) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        return "deadlock" in text or "could not serialize" in text

    def seed_user(
        tg_id: int, credits: float = 1000.0, *, bind_plex: bool = False
    ) -> None:
        with db_module.get_session() as session:
            session.add(
                Statistics(tg_id=int(tg_id), donation=0, credits=float(credits))
            )
            if bind_plex:
                session.add(
                    PlexUser(
                        plex_id=int(tg_id) * 10,
                        tg_id=int(tg_id),
                        plex_email=f"u{tg_id}@example.com",
                        plex_username=f"u{tg_id}",
                    )
                )

    def credits_of(tg_id: int) -> float:
        with db_module.get_session() as session:
            row = session.execute(
                select(Statistics.credits).where(Statistics.tg_id == int(tg_id))
            ).scalar_one_or_none()
        return round(float(row or 0), 2)

    def pack_row(pack_id: int) -> dict:
        with db_module.get_session() as session:
            pack = session.get(GiftPack, int(pack_id))
            claimed_count = int(pack.claimed_count)
            claimed_states = int(
                session.execute(
                    select(func.count())
                    .select_from(GiftPackUserState)
                    .where(
                        GiftPackUserState.pack_id == int(pack_id),
                        GiftPackUserState.claimed_at.is_not(None),
                    )
                ).scalar_one()
            )
        return {"claimed_count": claimed_count, "claimed_states": claimed_states}

    def plex_unlocked(tg_id: int) -> int:
        with db_module.get_session() as session:
            return int(
                session.execute(
                    select(PlexUser.line_schedule_unlocked).where(
                        PlexUser.tg_id == int(tg_id)
                    )
                ).scalar_one()
            )

    def make_pack(now: int, rewards: list[dict], **kwargs) -> int:
        from app.domains.gift_pack import repository as gift_pack_repository

        return int(
            gift_pack_repository.create_gift_pack(
                "并发礼包", rewards, now - 3600, now + 3600, **kwargs
            )
        )

    now = int(time.time())

    # ------------------------------------------------------------------ S1
    pack_s1 = make_pack(now, [{"type": "credits", "amount": REWARD}], total_quantity=1)
    for index in range(WORKERS):
        seed_user(1000 + index, credits=100.0)

    successes: list[int] = []
    rejections: list[str] = []

    def claim_s1(index: int) -> None:
        try:
            gift_pack_service.claim_gift_pack(pack_s1, 1000 + index)
            successes.append(index)
        except ValueError as exc:
            rejections.append(str(exc))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(claim_s1, range(WORKERS)))

    row = pack_row(pack_s1)
    check("S1 exactly one winner", len(successes) == 1, f"winners={successes}")
    check("S1 no oversell", row["claimed_count"] == 1, str(row))
    check("S1 one claim state", row["claimed_states"] == 1, str(row))
    check(
        "S1 losers see sold out",
        len(rejections) == WORKERS - 1 and all("领完" in text for text in rejections),
        str(rejections),
    )
    granted = sum(credits_of(1000 + index) - 100.0 for index in range(WORKERS))
    check("S1 reward granted once", granted == REWARD, f"granted={granted}")
    report["s1"] = {
        "winners": len(successes),
        "claimed_count": row["claimed_count"],
        "granted": granted,
    }

    # ------------------------------------------------------------------ S2
    pack_s2 = make_pack(now, [{"type": "credits", "amount": REWARD}])
    seed_user(2000, credits=100.0)

    outcomes: list[str] = []
    lock = threading.Lock()

    def claim_s2(index: int) -> None:
        try:
            gift_pack_service.claim_gift_pack(pack_s2, 2000)
            with lock:
                outcomes.append("ok")
        except ValueError as exc:
            with lock:
                outcomes.append(str(exc))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(claim_s2, range(WORKERS)))

    row = pack_row(pack_s2)
    winner_count = outcomes.count("ok")
    check("S2 exactly one success", winner_count == 1, str(outcomes))
    check("S2 one claim state", row["claimed_states"] == 1, str(row))
    check(
        "S2 losers see already claimed",
        all("已领取过" in text for text in outcomes if text != "ok"),
        str(outcomes),
    )
    check(
        "S2 reward granted once",
        credits_of(2000) == 100.0 + REWARD,
        f"credits={credits_of(2000)}",
    )
    report["s2"] = {"successes": winner_count, "credits": credits_of(2000)}

    # ------------------------------------------------------------------ S3
    # 奖励顺序：先解锁线路调度（锁 plex_user），再发积分（锁 statistics）；
    # 线路解锁购买路径的顺序相反（先扣积分，再写 plex_user）。
    pack_s3 = make_pack(
        now,
        [
            {"type": "line_schedule_unlock"},
            # 邀请码夹在中间：让领取方在持有 plex_user 行锁后、取 statistics 行锁前
            # 多走几条语句，与线路解锁购买路径形成真实的 ABBA 竞争窗口
            {"type": "invite_codes", "count": 3},
            {"type": "credits", "amount": 1},
        ],
    )
    seed_user(3000, credits=100.0, bind_plex=True)

    deadlocks: list[str] = []
    other_errors: list[str] = []
    both_succeeded = 0

    # ABBA 竞争要求两条路径在各自第一次加锁后交错；生产语句之间只隔几条 Python
    # 语句，所以用一个计时放大器（拿住行锁后休眠）把窗口拉开，使反转可稳定复现。
    from sqlalchemy import event as sa_event

    def _amplify(conn, cursor, statement, parameters, context, executemany):
        lowered = statement.lower()
        if "plex_user" in lowered or (
            "statistics" in lowered and "for update" in lowered
        ):
            time.sleep(0.2)

    sa_event.listen(engine, "after_cursor_execute", _amplify)

    def reset_side_state() -> None:
        with db_module.get_session() as session:
            session.execute(
                update(Statistics).where(Statistics.tg_id == 3000).values(credits=100.0)
            )
            session.execute(
                update(PlexUser)
                .where(PlexUser.tg_id == 3000)
                .values(line_schedule_unlocked=0)
            )
            # 每轮从同一起点开始，才能重复观察 ABBA 加锁顺序
            session.execute(
                delete(GiftPackUserState).where(GiftPackUserState.pack_id == pack_s3)
            )
            session.execute(
                update(GiftPack).where(GiftPack.id == pack_s3).values(claimed_count=0)
            )

    for _ in range(args.rounds):
        reset_side_state()
        barrier = threading.Barrier(2)
        round_outcomes: list[str] = []

        def claim_side(
            barrier: threading.Barrier = barrier,
            round_outcomes: list[str] = round_outcomes,
        ) -> None:
            barrier.wait()
            try:
                gift_pack_service.claim_gift_pack(pack_s3, 3000)
                round_outcomes.append("claim-ok")
            except Exception as exc:
                if is_deadlock(exc):
                    deadlocks.append(str(exc))
                else:
                    other_errors.append(f"claim: {type(exc).__name__}: {exc}")

        def unlock_side(
            barrier: threading.Barrier = barrier,
            round_outcomes: list[str] = round_outcomes,
        ) -> None:
            barrier.wait()
            try:
                lines_service.unlock_line_schedule_with_credit(
                    3000, "plex", UNLOCK_COST
                )
                round_outcomes.append("unlock-ok")
            except Exception as exc:
                if is_deadlock(exc):
                    deadlocks.append(str(exc))
                else:
                    other_errors.append(f"unlock: {type(exc).__name__}: {exc}")

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim_side), pool.submit(unlock_side)]
            for future in as_completed(futures):
                future.result()
        if sorted(round_outcomes) == ["claim-ok", "unlock-ok"]:
            both_succeeded += 1

    sa_event.remove(engine, "after_cursor_execute", _amplify)

    check("S3 no non-deadlock errors", not other_errors, str(other_errors[:3]))
    expected_credits = 100.0 + 1.0 - UNLOCK_COST
    if not deadlocks:
        check(
            "S3 credits match reward minus unlock cost",
            credits_of(3000) == expected_credits,
            f"credits={credits_of(3000)} expected={expected_credits}",
        )
        check(
            "S3 line schedule unlocked",
            plex_unlocked(3000) == 1,
            str(plex_unlocked(3000)),
        )
    check(
        "S3 both sides complete in most rounds",
        both_succeeded >= args.rounds - 1 or bool(deadlocks),
        f"both={both_succeeded}/{args.rounds}",
    )
    report["s3"] = {
        "deadlock": bool(deadlocks),
        "deadlocks": len(deadlocks),
        "rounds": args.rounds,
        "both_succeeded": both_succeeded,
        "credits": credits_of(3000),
        "unlocked": plex_unlocked(3000),
        "errors": other_errors[:3],
    }

    print(
        json.dumps(
            {"ok": not failures, "failures": failures, **report},
            ensure_ascii=False,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
