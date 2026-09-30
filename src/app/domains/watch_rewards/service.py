"""Watch reward orchestration; persistence lives in :mod:`repository`."""

from __future__ import annotations

import traceback
from datetime import datetime, timedelta

from app.core import kv as core_kv
from app.core.config import settings
from app.core.log import logger
from app.domains.accounts import service as accounts_service
from app.domains.badges import service as badges_service
from app.domains.credits.types import CreditAccount
from app.domains.invitation import service as invitation_service
from app.domains.premium import service as premium_service
from app.domains.traffic import service as traffic_service
from app.domains.watch_rewards import notifications, repository, rules
from app.domains.watch_rewards.constants import GHOST_SCAN_DAYS
from app.integrations.emby import Emby
from app.integrations.plex import Plex
from app.integrations.tautulli import Tautulli, get_user_total_duration
from app.integrations.tautulli_history import (
    STATUS_GHOST,
    STATUS_UNDETERMINED,
    scan_history,
)

# Kept as a source-compatible alias for manual/test callers during the promotion.
_watch_daily_award = rules.watch_daily_award


def update_plex_info(**kwargs) -> None:
    """Retain the existing test/manual seam without a cross-layer function import."""
    accounts_service.update_plex_info(**kwargs)


def _resolve_premium_status_for_settlement(**kwargs) -> bool:
    return premium_service.resolve_premium_status_for_settlement(**kwargs)


def _settle_premium_traffic_usage(**kwargs) -> dict:
    return premium_service.settle_premium_traffic_usage(**kwargs)


def _get_settled_through_date() -> str:
    stored = core_kv.get("ghost_session", "settled_through_date")
    if stored:
        return stored
    return (datetime.now(settings.TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


def _set_settled_through_date(date_str: str) -> None:
    core_kv.upsert("ghost_session", "settled_through_date", date_str)


def _daily_traffic(**kwargs) -> int:
    return traffic_service.get_user_daily_traffic(**kwargs)


def _active_badge_bonus(tg_id: int) -> float:
    return float(badges_service.active_bonus_percentage(tg_id))


def clean_tautulli_ghost_sessions(scan_days: int = GHOST_SCAN_DAYS) -> dict:
    logger.info(f"开始清理 Tautulli 幽灵会话（扫描最近 {scan_days} 天）")
    summary = {
        "scanned": 0,
        "ghosts": [],
        "undetermined": [],
        "deleted": 0,
        "failed": [],
        "retried": 0,
    }
    try:
        tautulli = Tautulli()
        stale_row_ids = repository.get_undeleted_ghost_row_ids()
        if stale_row_ids:
            logger.warning(f"发现 {len(stale_row_ids)} 条未确认删除的幽灵会话，重试")
            if tautulli.delete_history(stale_row_ids):
                repository.mark_ghost_sessions_deleted(stale_row_ids)
                summary["retried"] = len(stale_row_ids)
            else:
                logger.error(f"重试删除幽灵会话失败: {stale_row_ids}")
        after = (datetime.now(settings.TZ) - timedelta(days=scan_days)).strftime(
            "%Y-%m-%d"
        )
        scanned, verdicts = scan_history(tautulli, after=after)
        summary["scanned"] = scanned
        ghosts = [v for v in verdicts if v.status == STATUS_GHOST and v.row_id]
        summary["undetermined"] = [
            {
                "row_id": v.row_id,
                "friendly_name": v.friendly_name,
                "title": v.title,
                "raw_seconds": v.raw_seconds,
            }
            for v in verdicts
            if v.status == STATUS_UNDETERMINED
        ]
        if not ghosts:
            return summary
        logged = repository.get_logged_ghost_row_ids([v.row_id for v in ghosts])
        ghosts = [v for v in ghosts if v.row_id not in logged]
        staged_row_ids = []
        settled_through = _get_settled_through_date()
        for verdict in ghosts:
            play_date = (
                datetime.fromtimestamp(verdict.started, settings.TZ).strftime(
                    "%Y-%m-%d"
                )
                if verdict.started
                else datetime.now(settings.TZ).strftime("%Y-%m-%d")
            )
            already_settled = bool(settled_through) and play_date <= settled_through
            record = {
                "row_id": verdict.row_id,
                "user_id": verdict.user_id,
                "friendly_name": verdict.friendly_name,
                "title": verdict.title,
                "rating_key": verdict.rating_key,
                "started": verdict.started,
                "stopped": verdict.stopped,
                "play_date": play_date,
                "raw_seconds": verdict.raw_seconds,
                "media_seconds": verdict.media_seconds,
                "percent_complete": verdict.percent_complete,
                "compensated_seconds": verdict.compensated_seconds,
                "compensated": int(already_settled),
            }
            if repository.add_ghost_session_log(record):
                staged_row_ids.append(verdict.row_id)
                summary["ghosts"].append({**record, "already_settled": already_settled})
            else:
                summary["failed"].append(verdict.row_id)
        if staged_row_ids:
            if tautulli.delete_history(staged_row_ids):
                if repository.mark_ghost_sessions_deleted(staged_row_ids):
                    summary["deleted"] = len(staged_row_ids)
                else:
                    logger.error(
                        f"幽灵会话已删除但标记失败，需人工核查: {staged_row_ids}"
                    )
            else:
                summary["failed"].extend(staged_row_ids)
        return summary
    except Exception as error:
        logger.error(f"清理 Tautulli 幽灵会话失败: {error}")
        traceback.print_exc()
        return summary


def _settle_service_accounts(
    service: str,
    accounts: list[dict],
    durations: dict,
    *,
    traffic_config,
    premium_config,
    ghost_rows: dict,
) -> tuple[list[tuple[int, str]], list[dict]]:
    notifications_out: list[tuple[int, str]] = []
    deductions: list[dict] = []
    inviter_rewards: dict[int, dict] = {}
    failures: list[str] = []
    settlement_date = datetime.now(settings.TZ) - timedelta(days=1)
    settlement_key = settlement_date.strftime("%Y-%m-%d")
    for row in accounts:
        account_key = str(row["plex_id"] if service == "plex" else row["emby_id"])
        username = row["username"]
        tg_id = row["tg_id"]
        try:
            if service == "plex":
                play_duration = round(
                    min(
                        float(durations.get(row["plex_id"], 0))
                        + ghost_rows.get(account_key, {"hours": 0.0})["hours"],
                        24,
                    ),
                    2,
                )
                current_watched = float(row["watched_time"] or 0)
                user_id_kwargs = {"user_id": account_key}
            else:
                play_duration = round(float(durations.get(row["emby_id"], 0)) / 3600, 2)
                current_watched = float(row["watched_time"] or 0)
                play_duration = play_duration - current_watched
                user_id_kwargs = {"username": username}
            base_credits = min(play_duration, 8)
            settlement_status = _resolve_premium_status_for_settlement(
                current_is_premium=bool(row["is_premium"]),
                premium_status_updated_at=row["premium_status_updated_at"],
                settlement_date=settlement_date,
            )
            traffic_usage_premium = _daily_traffic(
                **user_id_kwargs,
                service=service,
                date=settlement_date,
                premium_only=True,
            )
            traffic_usage_total = _daily_traffic(
                **user_id_kwargs,
                service=service,
                date=settlement_date,
                premium_only=False,
            )
            premium_result = _settle_premium_traffic_usage(
                traffic_usage_premium=traffic_usage_premium,
                is_premium=settlement_status,
                debt_bytes=int(row["premium_traffic_debt_bytes"] or 0),
                debt_updated_date=row["premium_traffic_debt_updated_date"],
                settlement_date=settlement_date,
                user_traffic_limit=traffic_config.user_traffic_limit,
                premium_user_traffic_limit=traffic_config.premium_user_traffic_limit,
                credits_cost_per_10gb=premium_config.credits_cost_per_10gb,
            )
            traffic_cost = float(premium_result["traffic_cost_credits"])
            ghost_info = ghost_rows.get(account_key, {"hours": 0.0, "row_ids": []})
            if (
                play_duration <= 0
                and traffic_usage_total == 0
                and premium_result["debt_before_today"] == 0
                and premium_result["next_debt_bytes"] == 0
                and traffic_cost == 0
                and not ghost_info["row_ids"]
                and not row["premium_traffic_debt_bytes"]
                and not row["premium_traffic_debt_updated_date"]
            ):
                continue
            daily_award, time_penalty, data_penalty = rules.watch_daily_award(
                base_credits, play_duration, traffic_usage_total
            )
            bonus_percentage = _active_badge_bonus(int(tg_id)) if tg_id else 0.0
            badge_bonus = daily_award * bonus_percentage
            inviter_tg_id = (
                invitation_service.get_inviter_tg_id_by_plex_id(int(account_key))
                if service == "plex"
                else invitation_service.get_inviter_tg_id_by_emby_id(account_key)
            )
            bonus = rules.inviter_bonus(daily_award, inviter_tg_id, tg_id)
            account = (
                CreditAccount.tg(int(tg_id))
                if tg_id
                else (
                    CreditAccount.plex(int(account_key))
                    if service == "plex"
                    else CreditAccount.emby(account_key)
                )
            )
            result = repository.settle_user(
                service=service,
                account_key=account_key,
                settlement_date=settlement_key,
                account=account,
                tg_id=int(tg_id) if tg_id else None,
                inviter_tg_id=int(inviter_tg_id) if inviter_tg_id and bonus else None,
                inviter_bonus=bonus,
                credits_delta=round(daily_award + badge_bonus, 2),
                premium_charge=traffic_cost,
                watched_value=(current_watched + play_duration)
                if service == "plex"
                else max(current_watched + play_duration, current_watched),
                debt_bytes=premium_result["next_debt_bytes"],
                debt_updated_date=premium_result["next_debt_updated_date"],
                ghost_row_ids=ghost_info["row_ids"],
                transfer_unbound_balance=bool(tg_id) and service == "emby",
            )
            if result is None:
                continue
            if traffic_cost > 0:
                deductions.append(
                    {
                        "service": service.title(),
                        "username": username,
                        "tg_id": tg_id,
                        "deducted_credits": traffic_cost,
                        "chargeable_bytes": premium_result["chargeable_bytes"],
                    }
                )
            if result["inviter_tg_id"] and bonus:
                reward = inviter_rewards.setdefault(
                    result["inviter_tg_id"],
                    {"total_bonus": 0.0, "details": [], "balance": 0.0},
                )
                reward["total_bonus"] = round(reward["total_bonus"] + bonus, 2)
                reward["details"].append(
                    {
                        "username": username,
                        "base_credits": round(daily_award, 2),
                        "bonus": bonus,
                    }
                )
                reward["balance"] = result["inviter_balance"]
            if tg_id and play_duration > 0:
                notifications_out.append(
                    (
                        int(tg_id),
                        notifications.user_settlement_notification(
                            service.title(),
                            play_duration=play_duration,
                            base_credits=base_credits,
                            penalty=time_penalty + data_penalty,
                            traffic_cost=traffic_cost,
                            credits_change=daily_award + badge_bonus - traffic_cost,
                            balance=result["balance"],
                            watched_time=(current_watched + play_duration)
                            if service == "plex"
                            else max(current_watched + play_duration, current_watched),
                        ),
                    )
                )
        except Exception as error:
            logger.exception("结算 %s 用户 %s 失败", service, account_key)
            failures.append(f"{service.title()} {username} ({account_key}): {error}")
    notifications_out.extend(
        notifications.inviter_notification(
            service.title(), settlement_key, inviter_rewards
        )
    )
    notifications_out.extend(
        notifications.settlement_failures(failures, service.title())
    )
    return notifications_out, deductions


def update_plex_credits():
    logger.info("开始更新 Plex 用户积分及观看时长")
    try:
        premium_config = premium_service.get_premium_config()
        traffic_config = traffic_service.get_traffic_config()
        update_plex_info(plex_name=True, plex_id=False, plex_avatar=False)
        duration = get_user_total_duration(
            Tautulli().get_home_stats(
                1, "duration", len(Plex().users_by_id), "top_users"
            )
        )
        ghost_rows = repository.get_pending_ghost_compensation_rows()
        result = _settle_service_accounts(
            "plex",
            repository.list_plex_accounts(),
            duration,
            traffic_config=traffic_config,
            premium_config=premium_config,
            ghost_rows=ghost_rows,
        )
        _set_settled_through_date(
            (datetime.now(settings.TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        )
        return result
    except Exception as error:
        logger.exception("准备 Plex 观看积分结算失败")
        return [
            (chat_id, f"更新 Plex 用户积分及观看时长失败: {error}")
            for chat_id in settings.TG_ADMIN_CHAT_ID
        ], []


def update_emby_credits():
    logger.info("开始更新 Emby 用户积分及观看时长")
    try:
        premium_config = premium_service.get_premium_config()
        traffic_config = traffic_service.get_traffic_config()
        result = _settle_service_accounts(
            "emby",
            repository.list_emby_accounts(),
            Emby().get_user_total_play_time(),
            traffic_config=traffic_config,
            premium_config=premium_config,
            ghost_rows={},
        )
        return result
    except Exception as error:
        logger.exception("准备 Emby 观看积分结算失败")
        return [
            (chat_id, f"更新 Emby 用户积分及观看时长失败: {error}")
            for chat_id in settings.TG_ADMIN_CHAT_ID
        ], []


def _append_inviter_notifications(notifications_out, rewards, service, settlement_date):
    notifications_out.extend(
        notifications.inviter_notification(service, settlement_date, rewards)
    )


def _append_settlement_failures(notifications_out, failures, service):
    notifications_out.extend(notifications.settlement_failures(failures, service))
