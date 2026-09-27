"""Sanitized production-shaped rehearsal for the blackjack domain promotion.

Usage::

    python -m scripts.refactor.rehearse_blackjack \
        --url postgresql+psycopg2://localuser:localpw@127.0.0.1:55442/rehearsal

Run it only against a *copy* of production data in a disposable local database
(project rule: isolated container, dummy credentials, notification handlers
mocked to no-op). The rehearsal never writes to the production host.

Checks performed:

1. API assembly: ``/health`` and ``/openapi.json`` respond, protected routes
   reject unauthenticated calls with 401.
2. Scheduler startup: periodic jobs register, named persistent tasks exist,
   legacy jobstore references migrate, the scheduler starts and stops.
3. A representative blackjack settlement on production-shaped data with the
   credit ledger reconciling exactly once.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os

from sqlalchemy import select, text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--bet", type=int, default=0, help="0 表示取配置里最小的押注")
    args = parser.parse_args()
    if not args.url.startswith("postgresql"):
        raise SystemExit("rehearsal requires the PostgreSQL rehearsal copy")

    os.environ["DATABASE_URL"] = args.url
    os.environ["DATABASE_TYPE"] = "postgresql"

    import app.core.db as db_module
    from app.core import telegram as telegram_module
    from app.core.config import settings
    from app.domains.blackjack import repository as blackjack_repository
    from app.domains.blackjack import service as blackjack_service
    from app.domains.blackjack.rules import TERMINAL_STATUSES
    from app.domains.credits import service as credits_service
    from app.domains.identity.models import Statistics
    from app.model_registry import metadata  # noqa: F401 - 确保模型注册完成

    report: dict = {"ok": True, "checks": {}}
    failures: list[str] = []

    def check(name: str, ok: bool, detail: object = "") -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            failures.append(f"{name}: {detail}")

    # ---- 外部副作用全部置为 no-op（通知、缓存失效、网络同步） ----
    credits_service.invalidate_cache_keys = lambda _keys: None

    async def _noop_async(*_args, **_kwargs):
        return None

    telegram_module.send_message_by_url = _noop_async

    # ---- 1. API 装配 ----
    from fastapi.testclient import TestClient

    from app.api.app import app

    client = TestClient(app)
    health = client.get("/health")
    check("api_health", health.status_code == 200, health.status_code)
    openapi = client.get("/openapi.json")
    paths = openapi.json().get("paths", {}) if openapi.status_code == 200 else {}
    check("api_openapi", openapi.status_code == 200 and len(paths) > 100, len(paths))
    unauth = client.get("/api/rankings/credits")
    check("api_protected_requires_auth", unauth.status_code == 401, unauth.status_code)
    report["openapi_paths"] = len(paths)

    # ---- 2. 调度器启动（含 ON_STARTUP 恢复钩子与 jobstore 迁移） ----
    from app.core.scheduler import TASK_REGISTRY, Scheduler
    from app.schedule import _jobs, migrate_persisted_jobs, register_all

    scheduler = Scheduler()
    register_all(scheduler)
    report["periodic_jobs"] = len(_jobs(datetime.datetime.now(settings.TZ)))
    report["named_tasks"] = sorted(TASK_REGISTRY)
    check(
        "named_tasks_registered",
        {"blackjack.hand_timeout", "treasure.open_next_issue"} <= set(TASK_REGISTRY),
        sorted(TASK_REGISTRY),
    )
    report["rewritten_jobstore_references"] = migrate_persisted_jobs(scheduler)

    async def _start_and_stop(target: Scheduler) -> int:
        target.start()
        count = len(target.get_jobs())
        target.shutdown()
        return count

    # AsyncIOScheduler 需要事件循环；生产里由 Telegram bot 的事件循环提供
    report["scheduler_jobs"] = asyncio.run(_start_and_stop(scheduler))
    check("scheduler_started", report["scheduler_jobs"] > 0, report["scheduler_jobs"])

    # ---- 3. 代表性结算：真实数据形状下的一次 21 点结算 ----
    config = blackjack_repository.get_blackjack_config_dict()
    # 演练副本内的一次性调整，仅用于跑通代表性路径并让积分账目可精确对账：
    # 生产库不受影响。救济/返水/奖池会在结算路径上额外改变余额，故在副本里关掉。
    replica_adjustments = {}
    if not config.get("enabled"):
        config["enabled"] = True
        replica_adjustments["enabled"] = True
    for key in ("relief_enabled", "cashback_enabled", "jackpot_enabled"):
        if config.get(key):
            config[key] = False
            replica_adjustments[key] = False
    if replica_adjustments:
        blackjack_repository.set_blackjack_config(
            "config", json.dumps(config, ensure_ascii=False)
        )
        report["replica_only_config_adjustments"] = replica_adjustments

    bet_options = sorted(int(value) for value in config.get("bet_options") or [5])
    bet = args.bet or bet_options[0]
    min_credits = float(config.get("min_credits", 30))

    with db_module.get_session() as session:
        candidates = list(
            session.execute(
                select(Statistics.tg_id, Statistics.credits)
                .where(Statistics.credits >= max(min_credits, bet))
                .order_by(Statistics.credits.desc())
                .limit(20)
            ).all()
        )
    check("rehearsal_candidates", bool(candidates), len(candidates))

    settled = None
    for tg_id, credits_before in candidates:
        tg_id = int(tg_id)
        try:
            created = blackjack_service.create_blackjack_hand(tg_id, bet)
        except Exception as exc:
            report.setdefault("deal_errors", []).append(f"{tg_id}: {exc}")
            continue
        hand_id = int(created["hand"]["id"])
        if not created.get("settled"):
            blackjack_service.blackjack_stand(tg_id, hand_id)
        settled = (tg_id, hand_id, float(credits_before))
        break

    check("representative_hand_dealt", settled is not None, report.get("deal_errors"))
    if settled:
        tg_id, hand_id, credits_before = settled
        with db_module.get_session() as session:
            row = session.execute(
                text(
                    "SELECT status, bet_credits, payout_credits FROM blackjack_hand"
                    " WHERE id = :hand_id"
                ),
                {"hand_id": hand_id},
            ).one()
            credits_after = float(
                session.execute(
                    select(Statistics.credits).where(Statistics.tg_id == tg_id)
                ).scalar_one()
            )
        status, bet_credits, payout = int(row[0]), float(row[1]), float(row[2] or 0)
        report["hand"] = {
            "tg_id": tg_id,
            "hand_id": hand_id,
            "status": status,
            "bet_credits": bet_credits,
            "payout_credits": payout,
            "credits_before_deal": credits_before,
            "credits_after_settlement": credits_after,
        }
        check("hand_settled", status in TERMINAL_STATUSES, status)
        check(
            "credits_reconcile_once",
            credits_after == round(credits_before - bet_credits + payout, 2),
            f"{credits_before} - {bet_credits} + {payout} != {credits_after}",
        )

    report["ok"] = not failures
    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
