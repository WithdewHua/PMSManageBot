import time
import traceback
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core import kv as core_kv
from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.databases.db import db
from app.domains.credits import repository as credits_repository
from app.domains.credits.exceptions import CreditAccountNotFound
from app.domains.credits.types import CreditAccount
from app.domains.identity import repository as identity_repository
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
from app.domains.invitation import service as invitation_service
from app.domains.premium import repository as premium_repository
from app.domains.watch_rewards import repository as watch_rewards_repository
from app.domains.watch_rewards.constants import (
    GHOST_SETTLEMENT_CONFIG_KEY,
    GHOST_SETTLEMENT_CONFIG_TYPE,
)
from app.integrations.emby import Emby
from app.integrations.plex import Plex
from app.integrations.tautulli import Tautulli, get_user_total_duration
from app.integrations.tautulli_history import (
    STATUS_GHOST,
    STATUS_UNDETERMINED,
    scan_history,
)


def _get_settled_through_date() -> str:
    """取已完成结算的最后一个日期

    未初始化时保守地视为「昨天及以前都已结算」：首次部署时库里可能残留早已
    按被夸大的时长结算过的幽灵记录，此时宁可少补也不能重复补——重复补偿会把
    时长二次计入，比不补更糟。水位线随首次结算完成后即进入正常推进。
    """
    stored = core_kv.get(GHOST_SETTLEMENT_CONFIG_TYPE, GHOST_SETTLEMENT_CONFIG_KEY)
    if stored:
        return stored
    return (datetime.now(settings.TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


def _set_settled_through_date(date_str: str) -> None:
    """结算完成后推进水位线"""
    core_kv.upsert(GHOST_SETTLEMENT_CONFIG_TYPE, GHOST_SETTLEMENT_CONFIG_KEY, date_str)


from app.domains.watch_rewards.constants import GHOST_SCAN_DAYS


def clean_tautulli_ghost_sessions(scan_days: int = GHOST_SCAN_DAYS) -> dict:
    """清理 Tautulli 中的幽灵会话记录

    Plex 在部分版本下不发送 WebSocket stop 事件，Tautulli 会保持会话开启直到
    超时或重启才写入 history，产生一条时长被严重夸大的记录，污染观看时长与积分。
    Tautulli 官方对此的处置方式即为删除错误记录。

    处理顺序是「先留档、再删除、后标记」：
      - 留档失败则不删除，下轮重试；
      - 删除失败则停在 deleted=0，不会被补偿，下轮由自愈逻辑重试；
      - 记录一旦从 Tautulli 删除便无法回溯，补偿时长只能依赖留档表。

    必须在积分结算之前执行，否则 get_home_stats 取到的仍是脏数据。

    Returns
    -------
    dict
        本次清理的汇总，供管理员通知使用。
    """
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

        # 自愈：上一轮留档成功但未确认删除的记录，先重试一次
        stale_row_ids = db.get_undeleted_ghost_row_ids()
        if stale_row_ids:
            logger.warning(f"发现 {len(stale_row_ids)} 条未确认删除的幽灵会话，重试")
            if tautulli.delete_history(stale_row_ids):
                db.mark_ghost_sessions_deleted(stale_row_ids)
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
            logger.info(f"未发现幽灵会话（共扫描 {scanned} 条记录）")
            return summary

        # 跳过已经处理过的，避免重复删除与重复补偿
        logged = db.get_logged_ghost_row_ids([v.row_id for v in ghosts])
        ghosts = [v for v in ghosts if v.row_id not in logged]
        if not ghosts:
            logger.info("检出的幽灵会话均已留档处理过，跳过")
            return summary

        staged_row_ids = []
        # 结算水位线之前（含当天）的记录已经按被夸大的时长结算过了，
        # 此时再补偿等于把时长二次计入，因此这类记录只删除、不补偿。
        # 水位线为空表示还没跑过任何结算，此时全部记录都可补偿。
        settled_through = _get_settled_through_date()
        for v in ghosts:
            play_date = (
                datetime.fromtimestamp(v.started, settings.TZ).strftime("%Y-%m-%d")
                if v.started
                else datetime.now(settings.TZ).strftime("%Y-%m-%d")
            )
            already_settled = bool(settled_through) and play_date <= settled_through
            record = {
                "row_id": v.row_id,
                "user_id": v.user_id,
                "friendly_name": v.friendly_name,
                "title": v.title,
                "rating_key": v.rating_key,
                "started": v.started,
                "stopped": v.stopped,
                "play_date": play_date,
                "raw_seconds": v.raw_seconds,
                "media_seconds": v.media_seconds,
                "percent_complete": v.percent_complete,
                "compensated_seconds": v.compensated_seconds,
                "compensated": 1 if already_settled else 0,
            }
            # 留档必须先于删除：删掉之后这条记录就再也拿不回来了
            if db.add_ghost_session_log(record):
                staged_row_ids.append(v.row_id)
                summary["ghosts"].append(
                    {
                        "row_id": v.row_id,
                        "user_id": v.user_id,
                        "friendly_name": v.friendly_name,
                        "title": v.title,
                        "raw_seconds": v.raw_seconds,
                        "media_seconds": v.media_seconds,
                        "percent_complete": v.percent_complete,
                        "compensated_seconds": v.compensated_seconds,
                        "play_date": play_date,
                        "already_settled": already_settled,
                    }
                )
            else:
                summary["failed"].append(v.row_id)
                logger.error(f"幽灵会话 row_id={v.row_id} 留档失败，跳过删除")

        if staged_row_ids:
            if tautulli.delete_history(staged_row_ids):
                if db.mark_ghost_sessions_deleted(staged_row_ids):
                    summary["deleted"] = len(staged_row_ids)
                else:
                    # 已从 Tautulli 删除但标记失败，补偿会被推迟到下轮自愈
                    logger.error(
                        f"幽灵会话已删除但标记失败，需人工核查: {staged_row_ids}"
                    )
            else:
                summary["failed"].extend(staged_row_ids)
                logger.error(f"删除幽灵会话失败: {staged_row_ids}")

        for item in summary["ghosts"]:
            logger.info(
                f"清理幽灵会话 row_id={item['row_id']} 用户={item['friendly_name']} "
                f"《{item['title']}》 原始 {item['raw_seconds'] / 3600:.2f}h -> "
                f"补偿 {item['compensated_seconds'] / 3600:.2f}h"
            )
        logger.info(
            f"幽灵会话清理完成：扫描 {scanned} 条，删除 {summary['deleted']} 条，"
            f"失败 {len(summary['failed'])} 条"
        )

    except Exception as e:
        logger.error(f"清理 Tautulli 幽灵会话失败: {e}")
        traceback.print_exc()

    return summary


from app.domains.accounts.service import update_plex_info
from app.domains.premium import service as premium_service
from app.domains.premium.rules import (
    _resolve_premium_status_for_settlement,
    _settle_premium_traffic_usage,
)
from app.domains.traffic import service as traffic_service


def update_plex_credits():
    """Settle Plex watch rewards once per user and configured local date."""
    logger.info("开始更新 Plex 用户积分及观看时长")
    notification_tasks: list[tuple[int, str]] = []
    deduction_records: list[dict] = []
    inviter_rewards: dict[int, dict] = {}
    failures: list[str] = []
    try:
        premium_config = premium_service.get_premium_config()
        traffic_config = traffic_service.get_traffic_config()
        update_plex_info(plex_name=True, plex_id=False, plex_avatar=False)
        duration = get_user_total_duration(
            Tautulli().get_home_stats(
                1, "duration", len(Plex().users_by_id), "top_users"
            )
        )
        ghost_rows = watch_rewards_repository.get_pending_ghost_compensation_rows()
        for ghost_user_id, info in ghost_rows.items():
            key = int(ghost_user_id) if str(ghost_user_id).isdigit() else ghost_user_id
            duration[key] = duration.get(key, 0) + info["hours"]

        with get_session() as session:
            users = session.execute(
                select(
                    PlexUser.plex_id,
                    PlexUser.credits,
                    PlexUser.watched_time,
                    PlexUser.tg_id,
                    PlexUser.plex_username,
                    PlexUser.is_premium,
                    PlexUser.premium_status_updated_at,
                    PlexUser.premium_traffic_debt_bytes,
                    PlexUser.premium_traffic_debt_updated_date,
                ).where(PlexUser.plex_id.isnot(None))
            ).all()
    except Exception as error:
        logger.exception("准备 Plex 观看积分结算失败")
        return [
            (chat_id, f"更新 Plex 用户积分及观看时长失败: {error}")
            for chat_id in settings.TG_ADMIN_CHAT_ID
        ], deduction_records

    settlement_date = datetime.now(settings.TZ) - timedelta(days=1)
    settlement_key = settlement_date.strftime("%Y-%m-%d")
    for row in users:
        plex_id, _old_credits, watched_time, tg_id, username = row[:5]
        try:
            play_duration = round(min(float(duration.get(plex_id, 0)), 24), 2)
            base_credits = min(play_duration, 8)
            debt_bytes = int(row[7] or 0)
            debt_updated_date = row[8]
            is_premium = _resolve_premium_status_for_settlement(
                current_is_premium=bool(row[5]),
                premium_status_updated_at=row[6],
                settlement_date=settlement_date,
            )
            traffic_usage_premium = db.get_user_daily_traffic(
                user_id=str(plex_id),
                service="plex",
                date=settlement_date,
                premium_only=True,
            )
            traffic_usage_total = db.get_user_daily_traffic(
                user_id=str(plex_id),
                service="plex",
                date=settlement_date,
                premium_only=False,
            )
            premium_result = _settle_premium_traffic_usage(
                traffic_usage_premium=traffic_usage_premium,
                is_premium=is_premium,
                debt_bytes=debt_bytes,
                debt_updated_date=debt_updated_date,
                settlement_date=settlement_date,
                user_traffic_limit=traffic_config.user_traffic_limit,
                premium_user_traffic_limit=traffic_config.premium_user_traffic_limit,
                credits_cost_per_10gb=premium_config.credits_cost_per_10gb,
            )
            traffic_cost = float(premium_result["traffic_cost_credits"])
            ghost_info = ghost_rows.get(str(plex_id), {"hours": 0.0, "row_ids": []})
            if (
                play_duration == 0
                and traffic_usage_total == 0
                and premium_result["debt_before_today"] == 0
                and premium_result["next_debt_bytes"] == 0
                and traffic_cost == 0
                and not ghost_info["row_ids"]
                and not debt_bytes
                and not debt_updated_date
            ):
                continue

            daily_award, time_penalty, data_penalty = _watch_daily_award(
                base_credits, play_duration, traffic_usage_total
            )
            badge_bonus = 0.0
            if tg_id:
                for badge in db.get_user_active_badges_with_bonus(tg_id):
                    badge_bonus += daily_award * float(badge["bonus_percentage"])
            inviter_tg_id = invitation_service.get_inviter_tg_id_by_plex_id(plex_id)
            inviter_bonus = (
                round(daily_award * 0.1, 2)
                if inviter_tg_id and inviter_tg_id != tg_id and daily_award > 0
                else 0.0
            )
            account = (
                CreditAccount.tg(int(tg_id))
                if tg_id
                else CreditAccount.plex(int(plex_id))
            )
            result = _commit_watch_settlement(
                service="plex",
                account_key=str(plex_id),
                settlement_date=settlement_key,
                account=account,
                tg_id=int(tg_id) if tg_id else None,
                inviter_tg_id=int(inviter_tg_id)
                if inviter_tg_id and inviter_bonus > 0
                else None,
                inviter_bonus=inviter_bonus,
                credits_delta=round(daily_award + badge_bonus, 2),
                premium_charge=traffic_cost,
                media_model=PlexUser,
                media_key=PlexUser.plex_id,
                media_id=int(plex_id),
                watched_column=PlexUser.watched_time,
                watched_value=float(watched_time or 0) + play_duration,
                debt_bytes=premium_result["next_debt_bytes"],
                debt_updated_date=premium_result["next_debt_updated_date"],
                ghost_row_ids=ghost_info["row_ids"],
            )
            if result is None:
                continue
            if traffic_cost > 0:
                deduction_records.append(
                    {
                        "service": "Plex",
                        "username": username,
                        "tg_id": tg_id,
                        "deducted_credits": traffic_cost,
                        "chargeable_bytes": premium_result["chargeable_bytes"],
                    }
                )
            if result["inviter_tg_id"] and inviter_bonus > 0:
                reward = inviter_rewards.setdefault(
                    result["inviter_tg_id"],
                    {"total_bonus": 0.0, "details": [], "balance": 0.0},
                )
                reward["total_bonus"] = round(reward["total_bonus"] + inviter_bonus, 2)
                reward["details"].append(
                    {
                        "username": username,
                        "base_credits": round(daily_award, 2),
                        "bonus": inviter_bonus,
                    }
                )
                reward["balance"] = result["inviter_balance"]
            if tg_id and play_duration > 0:
                notification_tasks.append(
                    (
                        int(tg_id),
                        f"Plex 观看积分更新通知\n====================\n\n新增观看时长: {play_duration:.2f} 小时\n基础观看积分: {base_credits:.2f}\n观看惩罚: -{time_penalty + data_penalty:.2f}\nPremium 流量消耗积分: {traffic_cost:.2f}\n积分变化: {daily_award + badge_bonus - traffic_cost:+.2f}\n\n当前总积分: {result['balance']:.2f}\n当前总观看时长: {float(watched_time or 0) + play_duration:.2f} 小时\n====================",
                    )
                )
        except Exception as error:
            logger.exception("结算 Plex 用户 %s 失败", plex_id)
            failures.append(f"Plex {username} ({plex_id}): {error}")

    _append_inviter_notifications(
        notification_tasks, inviter_rewards, "Plex", settlement_key
    )
    _append_settlement_failures(notification_tasks, failures, "Plex")
    _set_settled_through_date(settlement_key)
    logger.info("Plex 用户积分及观看时长更新完成")
    return notification_tasks, deduction_records


def update_emby_credits():
    """Settle Emby watch rewards once per user and configured local date."""
    logger.info("开始更新 Emby 用户积分及观看时长")
    notification_tasks: list[tuple[int, str]] = []
    deduction_records: list[dict] = []
    inviter_rewards: dict[int, dict] = {}
    failures: list[str] = []
    try:
        premium_config = premium_service.get_premium_config()
        traffic_config = traffic_service.get_traffic_config()
        duration = Emby().get_user_total_play_time()
        with get_session() as session:
            users = session.execute(
                select(
                    EmbyUser.emby_id,
                    EmbyUser.tg_id,
                    EmbyUser.emby_watched_time,
                    EmbyUser.emby_credits,
                    EmbyUser.emby_username,
                    EmbyUser.is_premium,
                    EmbyUser.premium_status_updated_at,
                    EmbyUser.premium_traffic_debt_bytes,
                    EmbyUser.premium_traffic_debt_updated_date,
                )
            ).all()
    except Exception as error:
        logger.exception("准备 Emby 观看积分结算失败")
        return [
            (chat_id, f"更新 Emby 用户积分及观看时长失败: {error}")
            for chat_id in settings.TG_ADMIN_CHAT_ID
        ], deduction_records

    settlement_date = datetime.now(settings.TZ) - timedelta(days=1)
    settlement_key = settlement_date.strftime("%Y-%m-%d")
    for row in users:
        emby_id, tg_id, watched_time, _old_credits, username = row[:5]
        try:
            play_duration = round(float(duration.get(emby_id, 0)) / 3600, 2)
            daily_duration = play_duration - float(watched_time or 0)
            base_credits = min(daily_duration, 8)
            debt_bytes = int(row[7] or 0)
            debt_updated_date = row[8]
            is_premium = _resolve_premium_status_for_settlement(
                current_is_premium=bool(row[5]),
                premium_status_updated_at=row[6],
                settlement_date=settlement_date,
            )
            traffic_usage_premium = db.get_user_daily_traffic(
                username=username,
                service="emby",
                date=settlement_date,
                premium_only=True,
            )
            traffic_usage_total = db.get_user_daily_traffic(
                username=username,
                service="emby",
                date=settlement_date,
                premium_only=False,
            )
            premium_result = _settle_premium_traffic_usage(
                traffic_usage_premium=traffic_usage_premium,
                is_premium=is_premium,
                debt_bytes=debt_bytes,
                debt_updated_date=debt_updated_date,
                settlement_date=settlement_date,
                user_traffic_limit=traffic_config.user_traffic_limit,
                premium_user_traffic_limit=traffic_config.premium_user_traffic_limit,
                credits_cost_per_10gb=premium_config.credits_cost_per_10gb,
            )
            traffic_cost = float(premium_result["traffic_cost_credits"])
            if (
                daily_duration <= 0
                and traffic_usage_total == 0
                and premium_result["debt_before_today"] == 0
                and premium_result["next_debt_bytes"] == 0
                and traffic_cost == 0
                and not debt_bytes
                and not debt_updated_date
            ):
                continue

            daily_award, time_penalty, data_penalty = _watch_daily_award(
                base_credits, daily_duration, traffic_usage_total
            )
            badge_bonus = 0.0
            if tg_id:
                for badge in db.get_user_active_badges_with_bonus(tg_id):
                    badge_bonus += daily_award * float(badge["bonus_percentage"])
            inviter_tg_id = invitation_service.get_inviter_tg_id_by_emby_id(emby_id)
            inviter_bonus = (
                round(daily_award * 0.1, 2)
                if inviter_tg_id and inviter_tg_id != tg_id and daily_award > 0
                else 0.0
            )
            account = (
                CreditAccount.tg(int(tg_id))
                if tg_id
                else CreditAccount.emby(str(emby_id))
            )
            result = _commit_watch_settlement(
                service="emby",
                account_key=str(emby_id),
                settlement_date=settlement_key,
                account=account,
                tg_id=int(tg_id) if tg_id else None,
                inviter_tg_id=int(inviter_tg_id)
                if inviter_tg_id and inviter_bonus > 0
                else None,
                inviter_bonus=inviter_bonus,
                credits_delta=round(daily_award + badge_bonus, 2),
                premium_charge=traffic_cost,
                media_model=EmbyUser,
                media_key=EmbyUser.emby_id,
                media_id=str(emby_id),
                watched_column=EmbyUser.emby_watched_time,
                watched_value=max(play_duration, float(watched_time or 0)),
                debt_bytes=premium_result["next_debt_bytes"],
                debt_updated_date=premium_result["next_debt_updated_date"],
                ghost_row_ids=[],
                transfer_unbound_balance=bool(tg_id),
            )
            if result is None:
                continue
            if traffic_cost > 0:
                deduction_records.append(
                    {
                        "service": "Emby",
                        "username": username,
                        "tg_id": tg_id,
                        "deducted_credits": traffic_cost,
                        "chargeable_bytes": premium_result["chargeable_bytes"],
                    }
                )
            if result["inviter_tg_id"] and inviter_bonus > 0:
                reward = inviter_rewards.setdefault(
                    result["inviter_tg_id"],
                    {"total_bonus": 0.0, "details": [], "balance": 0.0},
                )
                reward["total_bonus"] = round(reward["total_bonus"] + inviter_bonus, 2)
                reward["details"].append(
                    {
                        "username": username,
                        "base_credits": round(daily_award, 2),
                        "bonus": inviter_bonus,
                    }
                )
                reward["balance"] = result["inviter_balance"]
            if tg_id and daily_duration > 0:
                notification_tasks.append(
                    (
                        int(tg_id),
                        f"Emby 观看积分更新通知\n====================\n\n新增观看时长: {daily_duration:.2f} 小时\n基础观看积分: {base_credits:.2f}\n观看惩罚: -{time_penalty + data_penalty:.2f}\nPremium 流量消耗积分: {traffic_cost:.2f}\n积分变化: {daily_award + badge_bonus - traffic_cost:+.2f}\n\n当前总积分: {result['balance']:.2f}\n当前总观看时长: {max(play_duration, float(watched_time or 0)):.2f} 小时\n====================",
                    )
                )
        except Exception as error:
            logger.exception("结算 Emby 用户 %s 失败", emby_id)
            failures.append(f"Emby {username} ({emby_id}): {error}")

    _append_inviter_notifications(
        notification_tasks, inviter_rewards, "Emby", settlement_key
    )
    _append_settlement_failures(notification_tasks, failures, "Emby")
    logger.info("Emby 用户积分及观看时长更新完成")
    return notification_tasks, deduction_records


def _watch_daily_award(
    base_credits: float, play_duration: float, traffic_usage_total: float
) -> tuple[float, float, float]:
    """Calculate the legacy daily watch reward and its two penalties."""
    time_penalty = (play_duration - 8 * 1.2) * 0.5 if play_duration > 8 * 1.2 else 0.0
    expected_data = play_duration * 10 * 1024**3
    data_penalty = 0.0
    if traffic_usage_total > 0 and expected_data > 0:
        ratio = float(traffic_usage_total) / float(expected_data)
        if ratio > 1.2:
            data_penalty = float(base_credits) * (ratio - 1.2) * 0.5
    award = max(0.0, min(float(base_credits) - time_penalty - data_penalty, 8.0))
    return award, time_penalty, data_penalty


def _commit_watch_settlement(
    *,
    service: str,
    account_key: str,
    settlement_date: str,
    account: CreditAccount,
    tg_id: int | None,
    inviter_tg_id: int | None,
    inviter_bonus: float,
    credits_delta: float,
    premium_charge: float,
    media_model,
    media_key,
    media_id: int | str,
    watched_column,
    watched_value: float,
    debt_bytes: int,
    debt_updated_date,
    ghost_row_ids: list[int],
    transfer_unbound_balance: bool = False,
) -> dict | None:
    """Commit ledger, user rewards, inviter reward and compensation atomically.

    Returns ``None`` when another run already settled this account/date.
    """
    with get_session() as session:
        media_row = session.execute(
            select(media_model).where(media_key == media_id).with_for_update()
        ).scalar_one_or_none()
        if media_row is None:
            raise RuntimeError(f"{service} account {account_key} disappeared")

        user_stats_exists = False
        if tg_id is not None:
            user_stats_exists = (
                session.execute(
                    select(Statistics.tg_id).where(Statistics.tg_id == int(tg_id))
                ).scalar_one_or_none()
                is not None
            )
            if not user_stats_exists and not transfer_unbound_balance:
                raise CreditAccountNotFound(CreditAccount.tg(int(tg_id)).label)

        effective_inviter = inviter_tg_id if inviter_bonus > 0 else None
        inviter_exists = False
        if effective_inviter is not None:
            inviter_exists = (
                session.execute(
                    select(Statistics.tg_id).where(
                        Statistics.tg_id == int(effective_inviter)
                    )
                ).scalar_one_or_none()
                is not None
            )
            if not inviter_exists:
                effective_inviter = None
                inviter_bonus = 0.0

        # Lock every existing Statistics row in ascending tg_id order.
        stats_ids = sorted(
            {int(value) for value in (tg_id, effective_inviter) if value is not None}
        )
        for stats_id in stats_ids:
            session.execute(
                select(Statistics.tg_id)
                .where(Statistics.tg_id == stats_id)
                .with_for_update()
            ).scalar_one()

        inserted = watch_rewards_repository.insert_watch_reward_settlement_tx(
            session,
            service=service,
            account_key=str(account_key),
            settlement_date=settlement_date,
            tg_id=tg_id,
            credits_delta=credits_delta,
            premium_charge=premium_charge,
            inviter_tg_id=effective_inviter,
            inviter_bonus=inviter_bonus,
            created_at=int(time.time()),
        )
        if not inserted:
            return None

        if tg_id is not None and not user_stats_exists:
            identity_repository.ensure_statistics_tx(session, int(tg_id))
            if transfer_unbound_balance:
                credits_repository.move_tx(
                    session,
                    CreditAccount.emby(str(account_key)),
                    CreditAccount.tg(int(tg_id)),
                )

        # Keep earned rewards and premium traffic charges separate: only this
        # explicit traffic operation is allowed to take a balance below zero.
        credits_repository.add_tx(session, account, credits_delta)
        balance_mutation = credits_repository.charge_premium_traffic_tx(
            session, account, premium_charge
        )

        inviter_balance = None
        if effective_inviter is not None and inviter_bonus > 0:
            inviter_mutation = credits_repository.add_tx(
                session, CreditAccount.tg(int(effective_inviter)), inviter_bonus
            )
            inviter_balance = inviter_mutation.after

        setattr(media_row, watched_column.key, watched_value)
        debt_account = (
            CreditAccount.plex(int(media_id))
            if service == "plex"
            else CreditAccount.emby(str(media_id))
        )
        premium_repository.update_traffic_debt_tx(
            session,
            debt_account,
            debt_bytes=int(debt_bytes),
            updated_date=debt_updated_date,
        )
        session.flush()
        watch_rewards_repository.mark_ghost_compensation_rows_tx(session, ghost_row_ids)
        return {
            "balance": balance_mutation.after,
            "inviter_tg_id": effective_inviter,
            "inviter_balance": inviter_balance,
        }


def _append_inviter_notifications(
    notifications: list[tuple[int, str]],
    rewards: dict[int, dict],
    service: str,
    settlement_date: str,
) -> None:
    for inviter_tg_id, reward in rewards.items():
        detail_lines = "\n".join(
            f"  · {item['username']}: 基础积分 {item['base_credits']} → 奖励 +{item['bonus']}"
            for item in reward["details"]
        )
        notifications.append(
            (
                inviter_tg_id,
                (
                    f"{service} 邀请奖励通知\n====================\n\n"
                    f"{settlement_date} 共 {len(reward['details'])} 位被邀请用户有新增观看记录:\n"
                    f"{detail_lines}\n\n本次邀请奖励积分: +{reward['total_bonus']}\n\n"
                    f"--------------------\n\n当前总积分: {float(reward['balance']):.2f}\n\n===================="
                ),
            )
        )


def _append_settlement_failures(
    notifications: list[tuple[int, str]], failures: list[str], service: str
) -> None:
    if not failures:
        return
    text = (
        f"{service} 观看结算部分用户失败（这些用户未提交，可在下次重试）:\n"
        + "\n".join(f"- {failure}" for failure in failures)
    )
    notifications.extend((chat_id, text) for chat_id in settings.TG_ADMIN_CHAT_ID)
