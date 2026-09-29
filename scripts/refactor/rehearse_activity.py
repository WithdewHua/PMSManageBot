"""活动领域提升的生产形态本地彩排。

用法::

    python -m scripts.refactor.rehearse_activity \
        --url postgresql+psycopg2://localuser:localpw@127.0.0.1:55444/rehearsal

只允许对一次性本地容器里的脱敏生产库副本运行。脚本不会连接生产主机；通知、
Telegram、ETH RPC、媒体同步等外部副作用全部替换为 no-op 或固定值。

彩排覆盖：

* 付费单抽、免费次数单抽、十连；
* 夺宝满员开奖；
* 预言下注与开奖；
* 竞拍创建、出价、结束以及具名内存调度任务。

每次运行使用固定的高位 Telegram ID，并在开始时清理上一轮同一批彩排数据，
因此可以在同一份本地副本上重复执行。真实业务数据不会被删除或修改，只有
这些固定彩排标记行会被重置。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import delete, select

MARKER_BASE = 9_700_000_000
USERS = {
    "wheel": MARKER_BASE + 1,
    "treasure_winner": MARKER_BASE + 2,
    "treasure_loser": MARKER_BASE + 3,
    "prediction_yes": MARKER_BASE + 4,
    "prediction_no": MARKER_BASE + 5,
    "auction_creator": MARKER_BASE + 6,
    "auction_bidder": MARKER_BASE + 7,
}
MARKER_USERS = tuple(USERS.values())
MARKER_TITLE_PREFIX = "[REHEARSAL activity]"


async def _noop_async(*_args: Any, **_kwargs: Any) -> None:
    return None


def _float_config_value(raw: str | None) -> float:
    if raw is None or not raw.strip():
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return float(json.loads(raw))


def _read_credits(session, statistics_model, tg_id: int) -> float:
    value = session.execute(
        select(statistics_model.credits).where(statistics_model.tg_id == int(tg_id))
    ).scalar_one()
    return float(value)


def _job_exists(scheduler, job_id: str, *, jobstore: str) -> bool:
    return any(job.id == job_id for job in scheduler.get_jobs(jobstore=jobstore))


def _remove_job(scheduler, job_id: str, *, jobstore: str) -> None:
    try:
        scheduler.remove_job(job_id, jobstore=jobstore)
    except Exception:
        return


def _install_notification_noops(modules: list[object], calls: list[str]) -> None:
    def _record(name: str) -> Callable[..., Awaitable[None]]:
        async def _notify(*_args: Any, **_kwargs: Any) -> None:
            calls.append(name)

        return _notify

    for module in modules:
        for name in dir(module):
            if name.startswith(("notify_", "send_")) and callable(
                getattr(module, name, None)
            ):
                setattr(module, name, _record(name))


def _prepare_marker_data(db_module, models: dict[str, object], scheduler) -> None:
    """Reset only rows belonging to the fixed rehearsal marker users."""
    statistics = models["Statistics"]
    auction = models["Auctions"]
    auction_bids = models["AuctionBids"]
    treasure_issue = models["TreasureIssue"]
    treasure_participation = models["TreasureParticipation"]
    prediction_market = models["PredictionMarket"]
    prediction_bet = models["PredictionBet"]
    prediction_submission = models["PredictionMarketSubmission"]
    wheel_stats = models["WheelStats"]
    free_spin = models["LuckywheelFreeSpin"]

    with db_module.get_session() as session:
        auction_ids = list(
            session.execute(
                select(auction.id).where(auction.created_by.in_(MARKER_USERS))
            ).scalars()
        )
        for auction_id in auction_ids:
            _remove_job(
                scheduler, f"finish_auction_{int(auction_id)}", jobstore="default"
            )
        if auction_ids:
            session.execute(
                delete(auction_bids).where(auction_bids.auction_id.in_(auction_ids))
            )
            session.execute(delete(auction).where(auction.id.in_(auction_ids)))

        market_ids = list(
            session.execute(
                select(prediction_market.id).where(
                    prediction_market.created_by.in_(MARKER_USERS)
                )
            ).scalars()
        )
        if market_ids:
            session.execute(
                delete(prediction_submission).where(
                    prediction_submission.market_id.in_(market_ids)
                )
            )
            session.execute(
                delete(prediction_bet).where(prediction_bet.market_id.in_(market_ids))
            )
            session.execute(
                delete(prediction_market).where(prediction_market.id.in_(market_ids))
            )

        issue_ids = list(
            session.execute(
                select(treasure_issue.id).where(
                    treasure_issue.created_by.in_(MARKER_USERS)
                )
            ).scalars()
        )
        for issue_id in issue_ids:
            _remove_job(
                scheduler,
                f"treasure_auto_reopen_{int(issue_id)}",
                jobstore="sqlalchemy",
            )
        if issue_ids:
            session.execute(
                delete(treasure_participation).where(
                    treasure_participation.issue_id.in_(issue_ids)
                )
            )
            session.execute(
                delete(treasure_issue).where(treasure_issue.id.in_(issue_ids))
            )

        session.execute(delete(wheel_stats).where(wheel_stats.tg_id.in_(MARKER_USERS)))
        session.execute(delete(free_spin).where(free_spin.tg_id.in_(MARKER_USERS)))

        for tg_id in MARKER_USERS:
            row = session.get(statistics, int(tg_id))
            if row is None:
                row = statistics(tg_id=int(tg_id), credits=500.0)
                session.add(row)
            else:
                row.credits = 500.0


def _install_external_noops(
    telegram_module,
    luckywheel_service,
    luckywheel_notifications,
    treasure_service,
    treasure_notifications,
    prediction_service,
    auction_service,
    auction_notifications,
    calls: list[str],
) -> None:
    telegram_module.send_message_by_url = _noop_async
    luckywheel_service.premium_service.sync_premium_media_access = lambda *_args: None
    _install_notification_noops(
        [
            luckywheel_notifications,
            treasure_notifications,
            prediction_service.prediction_notifications,
            auction_notifications,
        ],
        calls,
    )
    auction_service.get_user_name_from_tg_id = lambda tg_id: f"rehearsal-{tg_id}"


async def _run_flows(
    *,
    db_module,
    models: dict[str, object],
    services: dict[str, object],
    repositories: dict[str, object],
    scheduler,
    report: dict[str, Any],
    check: Callable[[str, bool, object], None],
) -> None:
    from app.core.kv import SystemConfigRepository
    from app.domains.luckywheel.schemas import LuckyWheelConfig, LuckyWheelItem

    statistics = models["Statistics"]
    wheel_stats = models["WheelStats"]
    free_spin = models["LuckywheelFreeSpin"]
    treasure_participation = models["TreasureParticipation"]
    treasure_issue = models["TreasureIssue"]
    prediction_market = models["PredictionMarket"]
    auctions = models["Auctions"]

    luckywheel_service = services["luckywheel"]
    treasure_service = services["treasure"]
    prediction_service = services["prediction"]
    auction_service = services["auction"]
    luckywheel_repository = repositories["luckywheel"]

    # 单一 100% 奖项使彩排结果与随机种子无关；仍然经过真实 service/repository
    # 路径，且付费/免费账本来源由生产代码写入。
    wheel_config = LuckyWheelConfig(
        items=[LuckyWheelItem(name="谢谢参与", probability=100)],
        cost_credits=10,
        min_credits_required=30,
        gen_privileged_code=False,
    )
    wheel_id = USERS["wheel"]
    with db_module.get_session() as session:
        wheel_before = _read_credits(session, statistics, wheel_id)
    paid = await luckywheel_service.spin(
        wheel_id, use_free_spin=False, config=wheel_config
    )
    with db_module.get_session() as session:
        after_paid = _read_credits(session, statistics, wheel_id)
    check(
        "luckywheel_paid_credit_delta",
        after_paid == round(wheel_before - 10, 2),
        {"before": wheel_before, "after": after_paid},
    )

    now_ms = int(time.time() * 1000)
    luckywheel_repository.grant_free_spins(
        wheel_id,
        1,
        source="gift_pack",
        granted_at_ms=now_ms,
        expires_at_ms=now_ms + 86_400_000,
    )
    free_before = after_paid
    free = await luckywheel_service.spin(
        wheel_id, use_free_spin=True, config=wheel_config
    )
    with db_module.get_session() as session:
        after_free = _read_credits(session, statistics, wheel_id)
        consumed = session.execute(
            select(free_spin.used_at_ms).where(
                free_spin.tg_id == wheel_id,
                free_spin.source == "gift_pack",
            )
        ).scalar_one_or_none()
    check(
        "luckywheel_free_spin_preserves_credits",
        after_free == free_before and consumed is not None,
        {"before": free_before, "after": after_free, "used_at_ms": consumed},
    )

    ten_before = after_free
    ten = await luckywheel_service.spin_ten_times(wheel_id, config=wheel_config)
    with db_module.get_session() as session:
        after_ten = _read_credits(session, statistics, wheel_id)
        wheel_sources = list(
            session.execute(
                select(wheel_stats.source)
                .where(wheel_stats.tg_id == wheel_id)
                .order_by(wheel_stats.id)
            ).scalars()
        )
    check(
        "luckywheel_ten_spin_credit_delta",
        after_ten == round(ten_before - 100, 2) and len(ten.results) == 10,
        {"before": ten_before, "after": after_ten, "result_count": len(ten.results)},
    )
    check(
        "luckywheel_ledger_sources",
        wheel_sources == ["paid", "gift_pack_free", *(["paid"] * 10)],
        wheel_sources,
    )
    report["flows"]["luckywheel"] = {
        "paid": paid.model_dump(),
        "free": free.model_dump(),
        "ten_count": len(ten.results),
        "credits": {"before": wheel_before, "after": after_ten},
        "sources": wheel_sources,
    }

    # 夺宝：固定时间让两个号码的 A 值可复算；B 动态选择为第一位参与者，
    # 从而验证满员开奖、赢家派奖、输家扣费和自动开期任务。
    winner_id = USERS["treasure_winner"]
    loser_id = USERS["treasure_loser"]
    with db_module.get_session() as session:
        treasure_before = {
            winner_id: _read_credits(session, statistics, winner_id),
            loser_id: _read_credits(session, statistics, loser_id),
        }
    treasure_id = await treasure_service.create_treasure_issue(
        title=f"{MARKER_TITLE_PREFIX} treasure",
        description="production-shaped rehearsal",
        prize_credits=20,
        total_credits_required=20,
        credits_per_share=10,
        start_number=29_000_001,
        created_by=winner_id,
    )
    treasure_time = 1_700_000_000.123
    original_time = treasure_service.time.time
    original_eth = treasure_service.eth_rpc.latest_block_hash_int

    async def _eth_zero() -> int:
        return 0

    treasure_service.time.time = lambda: treasure_time
    treasure_service.eth_rpc.latest_block_hash_int = _eth_zero
    try:
        await treasure_service.join_treasure_issue(
            issue_id=treasure_id, tg_id=winner_id, quantity=1
        )
        with db_module.get_session() as session:
            first = session.execute(
                select(
                    treasure_participation.created_at_ms,
                    treasure_participation.lucky_number,
                ).where(treasure_participation.issue_id == int(treasure_id))
            ).one()
            start_number = int(
                session.execute(
                    select(treasure_issue.start_number).where(
                        treasure_issue.id == int(treasure_id)
                    )
                ).scalar_one()
            )
        first_timestamp = int(first.created_at_ms)
        first_number = int(first.lucky_number)
        # 结算查询刻意保留生产路径的行为：同一事务中填满的参与行在
        # winner 查询前尚未 flush，因此 A 只来自已提交的第一行。
        external_b = (first_number - start_number - first_timestamp) % 2

        async def _eth_for_winner() -> int:
            return int(external_b)

        treasure_service.eth_rpc.latest_block_hash_int = _eth_for_winner
        settled_treasure = await treasure_service.join_treasure_issue(
            issue_id=treasure_id, tg_id=loser_id, quantity=1
        )
    finally:
        treasure_service.time.time = original_time
        treasure_service.eth_rpc.latest_block_hash_int = original_eth

    with db_module.get_session() as session:
        treasure_after = {
            winner_id: _read_credits(session, statistics, winner_id),
            loser_id: _read_credits(session, statistics, loser_id),
        }
        issue_row = session.get(treasure_issue, int(treasure_id))
        issue_state = (
            {
                "status": int(issue_row.status),
                "winner_tg_id": (
                    int(issue_row.winner_tg_id)
                    if issue_row.winner_tg_id is not None
                    else None
                ),
                "winner_number": (
                    int(issue_row.winner_number)
                    if issue_row.winner_number is not None
                    else None
                ),
            }
            if issue_row is not None
            else None
        )
    treasure_job_id = f"treasure_auto_reopen_{int(treasure_id)}"
    check(
        "treasure_full_settlement",
        bool(settled_treasure.get("settled"))
        and issue_state is not None
        and issue_state["status"] == 2
        and issue_state["winner_tg_id"] == winner_id
        and treasure_after[winner_id] == treasure_before[winner_id] + 10
        and treasure_after[loser_id] == treasure_before[loser_id] - 10,
        {
            "issue_id": treasure_id,
            "winner_tg_id": issue_state["winner_tg_id"] if issue_state else None,
            "credits_before": treasure_before,
            "credits_after": treasure_after,
        },
    )
    check(
        "treasure_reopen_task_persisted",
        _job_exists(scheduler, treasure_job_id, jobstore="sqlalchemy"),
        treasure_job_id,
    )
    report["flows"]["treasure"] = {
        "issue_id": treasure_id,
        "winner_tg_id": issue_state["winner_tg_id"] if issue_state else None,
        "winner_number": issue_state["winner_number"] if issue_state else None,
        "credits_before": treasure_before,
        "credits_after": treasure_after,
        "reopen_job_id": treasure_job_id,
    }
    _remove_job(scheduler, treasure_job_id, jobstore="sqlalchemy")

    # 预言：一方押 YES、一方押 NO，开奖 YES。默认 5% 手续费中 2% 注入荣耀池，
    # 结算后真实池 200、可派奖 190、荣耀池增加 4。
    yes_id = USERS["prediction_yes"]
    no_id = USERS["prediction_no"]
    with db_module.get_session() as session:
        prediction_before = {
            yes_id: _read_credits(session, statistics, yes_id),
            no_id: _read_credits(session, statistics, no_id),
        }
    glory_repo = SystemConfigRepository()
    glory_before = _float_config_value(
        glory_repo.get_system_config("prediction_market", "glory_fund")
    )
    prediction_id = await prediction_service.create_prediction_market(
        title=f"{MARKER_TITLE_PREFIX} prediction",
        description="production-shaped rehearsal",
        betting_deadline=int(time.time()) + 3600,
        created_by=yes_id,
        max_bet_per_user=500,
    )
    await prediction_service.place_prediction_bet(
        market_id=prediction_id, tg_id=yes_id, option=1, amount=100
    )
    await prediction_service.place_prediction_bet(
        market_id=prediction_id, tg_id=no_id, option=0, amount=100
    )
    prediction_result = await prediction_service.resolve_prediction_market(
        market_id=prediction_id,
        result_option=1,
        resolved_by=yes_id,
        resolution_note="production-shaped rehearsal",
    )
    with db_module.get_session() as session:
        prediction_after = {
            yes_id: _read_credits(session, statistics, yes_id),
            no_id: _read_credits(session, statistics, no_id),
        }
        market_row = session.get(prediction_market, int(prediction_id))
        market_state = (
            {"status": int(market_row.status)} if market_row is not None else None
        )
    glory_after = _float_config_value(
        glory_repo.get_system_config("prediction_market", "glory_fund")
    )
    check(
        "prediction_settlement",
        int(prediction_result.get("total_real_pool") or 0) == 200
        and int(prediction_result.get("payout_pool") or 0) == 190
        and market_state is not None
        and market_state["status"] == 3
        and prediction_after[yes_id] == prediction_before[yes_id] + 90
        and prediction_after[no_id] == prediction_before[no_id] - 100,
        {
            "market_id": prediction_id,
            "result": prediction_result,
            "credits_before": prediction_before,
            "credits_after": prediction_after,
        },
    )
    check(
        "prediction_glory_fund_delta",
        glory_after == round(glory_before + 4, 2),
        {"before": glory_before, "after": glory_after},
    )
    report["flows"]["prediction"] = {
        "market_id": prediction_id,
        "result": prediction_result,
        "credits_before": prediction_before,
        "credits_after": prediction_after,
        "glory_before": glory_before,
        "glory_after": glory_after,
    }

    # 竞拍：创建时写入 default 内存 jobstore，出价后结束时扣除赢家最终价，
    # 并由 finish_auction 显式移除同一 jobstore 的任务。
    creator_id = USERS["auction_creator"]
    bidder_id = USERS["auction_bidder"]
    with db_module.get_session() as session:
        bidder_before = _read_credits(session, statistics, bidder_id)
    auction_created = await auction_service.create_auction(
        title=f"{MARKER_TITLE_PREFIX} auction",
        description="production-shaped rehearsal",
        starting_price=10,
        duration_hours=1,
        created_by=creator_id,
    )
    auction_id = int(auction_created["auction_id"])
    auction_job_id = f"finish_auction_{auction_id}"
    job_before_finish = _job_exists(scheduler, auction_job_id, jobstore="default")
    auction_service.place_bid(auction_id=auction_id, bidder_id=bidder_id, bid_amount=25)
    finished, winner = await auction_service.finish_auction(
        auction_id=auction_id, remove_task=True, notify_winner=True
    )
    with db_module.get_session() as session:
        bidder_after = _read_credits(session, statistics, bidder_id)
        auction_row = session.get(auctions, auction_id)
        auction_state = (
            {"is_active": int(auction_row.is_active)}
            if auction_row is not None
            else None
        )
    check(
        "auction_finish_reconciles_bidder",
        finished
        and job_before_finish
        and not _job_exists(scheduler, auction_job_id, jobstore="default")
        and bidder_after == bidder_before - 25
        and auction_state is not None
        and auction_state["is_active"] == 0
        and isinstance(winner, dict)
        and int(winner.get("winner_id")) == bidder_id,
        {
            "auction_id": auction_id,
            "job_before_finish": job_before_finish,
            "winner": winner,
            "credits_before": bidder_before,
            "credits_after": bidder_after,
        },
    )
    report["flows"]["auction"] = {
        "auction_id": auction_id,
        "job_id": auction_job_id,
        "job_present_before_finish": job_before_finish,
        "winner": winner,
        "credits_before": bidder_before,
        "credits_after": bidder_after,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    if not args.url.startswith("postgresql"):
        raise SystemExit("activity rehearsal requires the PostgreSQL rehearsal copy")

    os.environ["DATABASE_URL"] = args.url
    os.environ["DATABASE_TYPE"] = "postgresql"

    # 所有会加载 settings / 数据库 singleton 的 import 都必须在环境变量设置后执行。
    import app.core.db as db_module
    import app.integrations.telegram.messaging as telegram_module
    from app.core.scheduler import TASK_REGISTRY, Scheduler
    from app.domains.auction import notifications as auction_notifications
    from app.domains.auction import repository as auction_repository
    from app.domains.auction import service as auction_service
    from app.domains.auction.models import AuctionBids, Auctions
    from app.domains.identity.models import Statistics
    from app.domains.luckywheel import notifications as luckywheel_notifications
    from app.domains.luckywheel import repository as luckywheel_repository
    from app.domains.luckywheel import service as luckywheel_service
    from app.domains.luckywheel.models import LuckywheelFreeSpin, WheelStats
    from app.domains.prediction import repository as prediction_repository
    from app.domains.prediction import service as prediction_service
    from app.domains.prediction.models import (
        PredictionBet,
        PredictionMarket,
        PredictionMarketSubmission,
    )
    from app.domains.treasure import notifications as treasure_notifications
    from app.domains.treasure import repository as treasure_repository
    from app.domains.treasure import service as treasure_service
    from app.domains.treasure.models import TreasureIssue, TreasureParticipation
    from app.model_registry import metadata
    from app.schedule import register_tasks

    del metadata
    scheduler = Scheduler()
    register_tasks()

    models = {
        "Statistics": Statistics,
        "Auctions": Auctions,
        "AuctionBids": AuctionBids,
        "TreasureIssue": TreasureIssue,
        "TreasureParticipation": TreasureParticipation,
        "PredictionMarket": PredictionMarket,
        "PredictionBet": PredictionBet,
        "PredictionMarketSubmission": PredictionMarketSubmission,
        "WheelStats": WheelStats,
        "LuckywheelFreeSpin": LuckywheelFreeSpin,
    }
    calls: list[str] = []
    _install_external_noops(
        telegram_module,
        luckywheel_service,
        luckywheel_notifications,
        treasure_service,
        treasure_notifications,
        prediction_service,
        auction_service,
        auction_notifications,
        calls,
    )
    _prepare_marker_data(db_module, models, scheduler)

    report: dict[str, Any] = {
        "ok": True,
        "database_type": "postgresql",
        "marker_users": USERS,
        "checks": {},
        "flows": {},
        "notification_calls": calls,
    }
    failures: list[str] = []

    def check(name: str, ok: bool, detail: object = "") -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            failures.append(f"{name}: {detail}")

    report["scheduler"] = {"named_tasks": sorted(TASK_REGISTRY)}
    check(
        "named_tasks_registered",
        {"auction.finish", "treasure.open_next_issue"} <= set(TASK_REGISTRY),
        sorted(TASK_REGISTRY),
    )

    try:
        asyncio.run(
            _run_flows(
                db_module=db_module,
                models=models,
                services={
                    "luckywheel": luckywheel_service,
                    "treasure": treasure_service,
                    "prediction": prediction_service,
                    "auction": auction_service,
                },
                repositories={
                    "luckywheel": luckywheel_repository,
                    "treasure": treasure_repository,
                    "prediction": prediction_repository,
                    "auction": auction_repository,
                },
                scheduler=scheduler,
                report=report,
                check=check,
            )
        )
    except Exception as error:
        report["exception"] = repr(error)
        failures.append(f"unhandled: {error!r}")

    report["notification_calls"] = calls
    report["ok"] = not failures
    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
