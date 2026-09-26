"""Declarative scheduler registry for recurring and persisted tasks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.log import logger
from app.core.scheduler import (
    Scheduler,
    register_task,
    rewrite_job_references,
    schedule_task,
)
from app.domains.accounts.jobs import refresh_emby_user_info, update_users_last_viewed
from app.domains.accounts.service import update_plex_info
from app.domains.auction.jobs import (
    finish_expired_auctions_job,
    restore_auction_schedules,
)
from app.domains.badge_awards.jobs import (
    check_and_award_game_king_badge,
    check_and_award_supreme_contributor_badge,
)
from app.domains.blackjack.jobs.cash import (
    _settle_blackjack_hand_on_timeout,
    blackjack_weekly_cashback_job,
    notify_blackjack_freespin_grants_job,
    notify_blackjack_jackpot_wins_job,
    remind_blackjack_freespin_expiry_job,
    restore_blackjack_timeouts,
    sweep_expired_blackjack_hands_job,
)
from app.domains.blackjack.jobs.tournament import (
    auto_create_blackjack_tournament_job,
    blackjack_tournament_tick_job,
)
from app.domains.credits.jobs import rewrite_users_credits_to_redis
from app.domains.crypto_donation.jobs import check_expired_crypto_donation_orders
from app.domains.custom_lines.jobs import (
    check_custom_line_traffic,
    check_expired_custom_lines,
)
from app.domains.custom_lines.service import settle_custom_line_traffic
from app.domains.gift_pack.jobs import scan_expired_gift_packs, scan_gift_pack_start_dms
from app.domains.lines.jobs import auto_switch_user_lines, write_user_info_cache
from app.domains.prediction.jobs import check_prediction_markets_closing_soon_job
from app.domains.premium.service import (
    check_premium_expiring_soon,
    check_premium_expiry,
    get_and_send_premium_statistics,
)
from app.domains.profile.jobs import refresh_tg_user_info
from app.domains.reports.jobs import send_weekly_report
from app.domains.traffic.jobs import (
    monthly_traffic_data_migration,
    update_line_traffic_stats,
)
from app.domains.watch_rewards.jobs import clean_ghost_sessions_job, update_credits


@dataclass(frozen=True)
class RecurringJob:
    id: str
    func: Callable[..., Any]
    runner: str
    trigger: str
    trigger_args: dict[str, Any]
    log_message: str


TASKS = {
    "blackjack.hand_timeout": _settle_blackjack_hand_on_timeout,
    "treasure.open_next_issue": None,
}
LEGACY_TASK_REFS = {
    "app.webapp.routers.activities.blackjack:_settle_blackjack_hand_on_timeout": "blackjack.hand_timeout",
    "app.webapp.routers.activities.treasure:_auto_create_next_treasure_issue_from": "treasure.open_next_issue",
}
ON_STARTUP = [restore_auction_schedules, restore_blackjack_timeouts]


def _jobs(now: datetime) -> list[RecurringJob]:
    return [
        RecurringJob(
            "update_credits",
            update_credits,
            "async",
            "cron",
            {"day_of_week": "*", "hour": 0, "minute": 0},
            "添加定时任务：每天凌晨 12:00 更新积分 (Plex 和 Emby)",
        ),
        RecurringJob(
            "clean_ghost_sessions",
            clean_ghost_sessions_job,
            "async",
            "cron",
            {"hour": "3,9,15,21", "minute": 17},
            "添加定时任务：每 6 小时清理 Tautulli 幽灵会话",
        ),
        RecurringJob(
            "update_plex_info",
            update_plex_info,
            "sync",
            "cron",
            {"day_of_week": "*", "hour": 12, "minute": 0},
            "添加定时任务：每天中午 12:00 更新 Plex 用户信息",
        ),
        RecurringJob(
            "refresh_user_info",
            refresh_tg_user_info,
            "async",
            "cron",
            {"day_of_week": "*", "hour": 12, "minute": 10},
            "添加定时任务：每天中午 12:10 更新 Telegram 用户信息",
        ),
        RecurringJob(
            "refresh_emby_user_info",
            refresh_emby_user_info,
            "sync",
            "cron",
            {"day_of_week": "*", "hour": 7, "minute": 0},
            "添加定时任务：每天早上 07:00 更新 Emby 用户信息",
        ),
        RecurringJob(
            "finish_expired_auctions_fallback",
            finish_expired_auctions_job,
            "async",
            "cron",
            {"hour": 2, "minute": 0},
            "添加定时任务：每天凌晨 2 点检查过期竞拍活动（兜底机制）",
        ),
        RecurringJob(
            "sweep_expired_blackjack_hands_fallback",
            sweep_expired_blackjack_hands_job,
            "async",
            "cron",
            {"minute": "*/10"},
            "添加定时任务：每 10 分钟清理超时的 21 点手牌（兜底机制）",
        ),
        RecurringJob(
            "notify_blackjack_jackpot_wins",
            notify_blackjack_jackpot_wins_job,
            "async",
            "cron",
            {"minute": "*"},
            "添加定时任务：每分钟播报 21 点幸运奖池中奖",
        ),
        RecurringJob(
            "blackjack_tournament_tick",
            blackjack_tournament_tick_job,
            "async",
            "cron",
            {"minute": "*"},
            "添加定时任务：每分钟推进 21 点锦标赛（报名截止/完赛提醒/完赛结算）",
        ),
        RecurringJob(
            "blackjack_tournament_auto_create",
            auto_create_blackjack_tournament_job,
            "async",
            "cron",
            {"day_of_week": "mon", "hour": 9, "minute": 0},
            "添加定时任务：每周一 09:00 自动创建 21 点锦标赛（周三 18:00 报名截止，周日 23:59 完赛截止）",
        ),
        RecurringJob(
            "check_premium_expiry",
            check_premium_expiry,
            "async",
            "interval",
            {"minutes": 5, "next_run_time": now + timedelta(seconds=30)},
            "添加定时任务：每 5 分钟检查 Premium 会员过期状态",
        ),
        RecurringJob(
            "check_premium_expiring_soon",
            check_premium_expiring_soon,
            "async",
            "cron",
            {"day_of_week": "*", "hour": 9, "minute": 0},
            "添加定时任务：每天早上 09:00 检查即将过期的 Premium 用户",
        ),
        RecurringJob(
            "update_line_traffic_stats",
            update_line_traffic_stats,
            "async",
            "cron",
            {"minute": "*/1"},
            "添加定时任务：每 1 分钟更新线路流量统计信息",
        ),
        RecurringJob(
            "blackjack_weekly_cashback",
            blackjack_weekly_cashback_job,
            "async",
            "cron",
            {"day_of_week": "mon", "hour": 0, "minute": 5},
            "添加定时任务：每周一 00:05 结算 21 点周损失返还（争霸赛余额）",
        ),
        RecurringJob(
            "blackjack_freespin_grant_notify",
            notify_blackjack_freespin_grants_job,
            "async",
            "cron",
            {"minute": "*"},
            "添加定时任务：每分钟私信新发放的 21 点免费大转盘机会",
        ),
        RecurringJob(
            "blackjack_freespin_expiry_reminder",
            remind_blackjack_freespin_expiry_job,
            "async",
            "cron",
            {"hour": 10, "minute": 0},
            "添加定时任务：每天 10:00 提醒即将过期的免费大转盘机会",
        ),
        RecurringJob(
            "update_users_credits",
            rewrite_users_credits_to_redis,
            "sync",
            "cron",
            {"minute": "*/5"},
            "添加定时任务：每 5 分钟更新用户积分信息",
        ),
        RecurringJob(
            "write_user_info_cache",
            write_user_info_cache,
            "sync",
            "interval",
            {"minutes": 15, "next_run_time": now + timedelta(seconds=30)},
            "添加定时任务：每 15 分钟更新用户信息",
        ),
        RecurringJob(
            "check_prediction_markets_closing_soon_job",
            check_prediction_markets_closing_soon_job,
            "async",
            "interval",
            {"hours": 1, "next_run_time": now + timedelta(minutes=2)},
            "添加定时任务：每 1 小时检查大预言家 6 小时内截止题目并发送群组提醒",
        ),
        RecurringJob(
            "update_users_last_viewed",
            update_users_last_viewed,
            "sync",
            "interval",
            {"minutes": 30, "next_run_time": now + timedelta(minutes=1)},
            "添加定时任务：每 30 分钟更新用户最后观看时间",
        ),
        RecurringJob(
            "monthly_traffic_data_migration",
            monthly_traffic_data_migration,
            "async",
            "cron",
            {"day": 1, "hour": 1, "minute": 0},
            "添加定时任务：每月 1 号凌晨 1:00 执行月度流量数据迁移聚合",
        ),
        RecurringJob(
            "send_premium_statistics",
            get_and_send_premium_statistics,
            "async",
            "cron",
            {"day_of_week": "*", "hour": 23, "minute": 59},
            "添加定时任务：每天 23:59 发送 Premium 线路统计信息给管理员",
        ),
        RecurringJob(
            "check_expired_crypto_donation_orders",
            check_expired_crypto_donation_orders,
            "async",
            "interval",
            {"minutes": 10, "next_run_time": now + timedelta(seconds=45)},
            "添加定时任务：每 10 分钟检查过期的 crypto 捐赠订单",
        ),
        RecurringJob(
            "auto_switch_user_lines",
            auto_switch_user_lines,
            "async",
            "cron",
            {"minute": "*/1"},
            "添加定时任务：每 1 分钟自动切换用户线路调度",
        ),
        RecurringJob(
            "send_weekly_report",
            send_weekly_report,
            "async",
            "cron",
            {"day_of_week": "mon", "hour": 0, "minute": 5},
            "添加定时任务：每周一凌晨 00:05 发送每周统计报告",
        ),
        RecurringJob(
            "check_and_award_supreme_contributor_badge",
            check_and_award_supreme_contributor_badge,
            "async",
            "cron",
            {
                "day_of_week": "*",
                "hour": 9,
                "minute": 0,
                "next_run_time": now + timedelta(minutes=2),
            },
            "添加定时任务：每天上午 09:00 检查并授予至尊贡献者勋章",
        ),
        RecurringJob(
            "check_expired_custom_lines",
            check_expired_custom_lines,
            "async",
            "interval",
            {"minutes": 5, "next_run_time": now + timedelta(minutes=3)},
            "添加定时任务：每 5 分钟检查并下线过期的自定义线路",
        ),
        RecurringJob(
            "scan_expired_gift_packs",
            scan_expired_gift_packs,
            "async",
            "interval",
            {"minutes": 10, "next_run_time": now + timedelta(minutes=4)},
            "添加定时任务：每 10 分钟扫描过期礼包并发送领取汇总",
        ),
        RecurringJob(
            "scan_gift_pack_start_dms",
            scan_gift_pack_start_dms,
            "async",
            "interval",
            {"minutes": 5, "next_run_time": now + timedelta(minutes=2)},
            "添加定时任务：每 5 分钟扫描名单型礼包开始私信",
        ),
        RecurringJob(
            "check_custom_line_traffic",
            check_custom_line_traffic,
            "async",
            "interval",
            {"minutes": 3, "next_run_time": now + timedelta(minutes=1)},
            "添加定时任务：每 3 分钟检查自定义线路流量使用情况",
        ),
        RecurringJob(
            "settle_custom_line_traffic",
            settle_custom_line_traffic,
            "async",
            "cron",
            {"day": 1, "hour": 2, "minute": 0},
            "添加定时任务：每月1号凌晨 2:00 结算上月自定义线路流量积分（在流量聚合后）",
        ),
        RecurringJob(
            "check_and_award_game_king_badge",
            check_and_award_game_king_badge,
            "async",
            "cron",
            {
                "day_of_week": "*",
                "hour": 9,
                "minute": 10,
                "next_run_time": now + timedelta(minutes=3),
            },
            "添加定时任务：每天上午 09:10 检查并授予游戏王勋章",
        ),
    ]


def register_tasks() -> None:
    """Make one-shot tasks available before the API accepts any requests."""
    TASKS["blackjack.hand_timeout"] = _settle_blackjack_hand_on_timeout
    register_task("blackjack.hand_timeout", _settle_blackjack_hand_on_timeout)
    treasure_task = _load_treasure_task()
    TASKS["treasure.open_next_issue"] = treasure_task
    register_task("treasure.open_next_issue", treasure_task)


def register_all(scheduler: Scheduler | None = None) -> None:
    scheduler = scheduler or Scheduler()
    register_tasks()
    jobs = _jobs(datetime.now(settings.TZ))
    for index, job in enumerate(jobs):
        if index == 24:
            for hook in ON_STARTUP:
                hook()
        kwargs = dict(job.trigger_args)
        scheduler_method = (
            scheduler.add_async_job if job.runner == "async" else scheduler.add_sync_job
        )
        scheduler_method(
            func=job.func,
            trigger=job.trigger,
            id=job.id,
            replace_existing=True,
            max_instances=1,
            **kwargs,
        )
        logger.info(job.log_message)
    scheduler.enable_named_persistent_tasks()


def _load_treasure_task() -> Callable[..., Any]:
    from app.domains.treasure.jobs import _auto_create_next_treasure_issue_from

    return _auto_create_next_treasure_issue_from


def migrate_persisted_jobs(scheduler: Scheduler | None = None) -> int:
    scheduler = scheduler or Scheduler()
    return rewrite_job_references(scheduler.jobstores["sqlalchemy"], LEGACY_TASK_REFS)


__all__ = [
    "LEGACY_TASK_REFS",
    "ON_STARTUP",
    "TASKS",
    "_jobs",
    "migrate_persisted_jobs",
    "register_all",
    "schedule_task",
]
