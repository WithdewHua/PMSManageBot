import traceback
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy import update as sql_update

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.databases.db import db
from app.domains.identity.models import EmbyUser, PlexUser, Statistics
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
    stored = db.get_system_config(
        GHOST_SETTLEMENT_CONFIG_TYPE, GHOST_SETTLEMENT_CONFIG_KEY
    )
    if stored:
        return stored
    return (datetime.now(settings.TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


def _set_settled_through_date(date_str: str) -> None:
    """结算完成后推进水位线"""
    db.set_system_config(
        GHOST_SETTLEMENT_CONFIG_TYPE, GHOST_SETTLEMENT_CONFIG_KEY, date_str
    )


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
from app.domains.premium.rules import (
    _resolve_premium_status_for_settlement,
    _settle_premium_traffic_usage,
)


def update_plex_credits():
    """更新积分及观看时长"""
    logger.info("开始更新 Plex 用户积分及观看时长")
    notification_tasks = []
    deduction_records = []
    ghost_compensation: dict = {}
    # 邀请人奖励累积字典: {inviter_tg_id: {"total_bonus": float, "details": [{"username": str, "base_credits": float, "bonus": float}]}}
    inviter_rewards: dict = {}
    try:
        # 先更新用户信息
        update_plex_info(plex_name=True, plex_id=False, plex_avatar=False)

        # 获取一天内的观看时长
        duration = get_user_total_duration(
            Tautulli().get_home_stats(
                1, "duration", len(Plex().users_by_id), "top_users"
            )
        )
        # 加回被清理掉的幽灵会话时长：这些记录已从 Tautulli 删除，
        # get_home_stats 不再包含它们，只能从留档表按真实播放进度补回，
        # 否则用户这部分观看时长就白丢了
        ghost_compensation = db.get_pending_ghost_compensation()
        for ghost_user_id, ghost_hours in ghost_compensation.items():
            # duration 的 key 直接来自 Tautulli，为 int 型 user_id
            key = (
                int(ghost_user_id)
                if str(ghost_user_id).lstrip("-").isdigit()
                else ghost_user_id
            )
            duration[key] = duration.get(key, 0) + ghost_hours
            logger.info(
                f"用户 {ghost_user_id} 补回幽灵会话观看时长 {round(ghost_hours, 2)} 小时"
            )
        # update credits and watched_time
        with get_session() as session:
            stmt = select(PlexUser.plex_id).where(PlexUser.plex_id.isnot(None))
            plex_ids = session.execute(stmt).scalars().all()

        for plex_id in plex_ids:
            play_duration = round(min(float(duration.get(plex_id, 0)), 24), 2)
            # 最大记 8h
            credits_inc = min(play_duration, 8)

            with get_session() as session:
                stmt = select(
                    PlexUser.credits,
                    PlexUser.watched_time,
                    PlexUser.tg_id,
                    PlexUser.plex_username,
                    PlexUser.is_premium,
                    PlexUser.premium_status_updated_at,
                    PlexUser.premium_traffic_debt_bytes,
                    PlexUser.premium_traffic_debt_updated_date,
                ).where(PlexUser.plex_id == plex_id)
                res = session.execute(stmt).fetchone()
            if not res:
                continue
            watched_time_init = res[1]
            tg_id = res[2]
            plex_username = res[3]
            is_premium = res[4]
            premium_status_updated_at = res[5]
            debt_bytes = int(res[6] or 0)
            debt_updated_date = res[7]
            settlement_date = datetime.now(settings.TZ) - timedelta(days=1)
            is_premium_for_settlement = _resolve_premium_status_for_settlement(
                current_is_premium=bool(is_premium),
                premium_status_updated_at=premium_status_updated_at,
                settlement_date=settlement_date,
            )
            # 获取用户昨日的 premium 流量使用情况（用于流量费用计算）
            traffic_usage_premium = db.get_user_daily_traffic(
                user_id=str(plex_id),
                service="plex",
                date=settlement_date,
                premium_only=True,
            )
            # 获取用户昨日的总流量（用于流量惩罚计算）
            traffic_usage_total = db.get_user_daily_traffic(
                user_id=str(plex_id),
                service="plex",
                date=settlement_date,
                premium_only=False,
            )

            premium_traffic_result = _settle_premium_traffic_usage(
                traffic_usage_premium=traffic_usage_premium,
                is_premium=is_premium_for_settlement,
                debt_bytes=debt_bytes,
                debt_updated_date=debt_updated_date,
                settlement_date=settlement_date,
            )
            traffic_usage_exceed = premium_traffic_result["exceed_bytes"]
            traffic_cost_credits = premium_traffic_result["traffic_cost_credits"]
            if traffic_cost_credits > 0:
                deduction_records.append(
                    {
                        "service": "Plex",
                        "username": plex_username,
                        "tg_id": tg_id,
                        "deducted_credits": traffic_cost_credits,
                        "chargeable_bytes": premium_traffic_result["chargeable_bytes"],
                    }
                )

            if (
                play_duration == 0
                and traffic_usage_total == 0
                and premium_traffic_result["debt_before_today"] == 0
                and premium_traffic_result["next_debt_bytes"] == 0
            ):
                if debt_bytes > 0 or debt_updated_date:
                    with get_session() as session:
                        stmt = (
                            sql_update(PlexUser)
                            .where(PlexUser.plex_id == plex_id)
                            .values(
                                premium_traffic_debt_bytes=premium_traffic_result[
                                    "next_debt_bytes"
                                ],
                                premium_traffic_debt_updated_date=premium_traffic_result[
                                    "next_debt_updated_date"
                                ],
                            )
                        )
                        session.execute(stmt)
                continue

            # 计算超长观看惩罚 (TimePenalty)
            time_penalty = 0
            if play_duration > 8 * 1.2:
                time_penalty = (play_duration - 8 * 1.2) * 0.5

            # 计算超额流量惩罚 (DataPenalty)
            data_penalty = 0
            data_ratio = 0
            expected_data = play_duration * 10 * 1024 * 1024 * 1024  # 10 GB/小时
            if traffic_usage_total > 0 and expected_data > 0:
                data_ratio = float(traffic_usage_total) / float(expected_data)
                if data_ratio > 1.2:
                    data_penalty = float(credits_inc) * (data_ratio - 1.2) * 0.5

            # 应用惩罚到基础积分
            final_daily_score = max(
                0, min(credits_inc - time_penalty - data_penalty, 8)
            )
            # 保存原始 credits_inc 用于显示
            original_credits_inc = credits_inc
            credits_inc = final_daily_score
            # 计算勋章加成
            badge_bonus = 0
            badge_bonus_details = []
            if tg_id:
                active_badges = db.get_user_active_badges_with_bonus(tg_id)
                for badge_info in active_badges:
                    bonus_percentage = float(badge_info["bonus_percentage"])
                    bonus_credits = float(credits_inc) * bonus_percentage
                    badge_bonus += bonus_credits
                    badge_bonus_details.append(
                        {
                            "name": badge_info["badge"]["name"],
                            "percentage": bonus_percentage * 100,
                            "credits": round(bonus_credits, 2),
                        }
                    )

            if not tg_id:
                credits_init = res[0]
                credits = credits_init + credits_inc - traffic_cost_credits
                watched_time = watched_time_init + play_duration
                with get_session() as session:
                    stmt = (
                        sql_update(PlexUser)
                        .where(PlexUser.plex_id == plex_id)
                        .values(
                            credits=credits,
                            watched_time=watched_time,
                            premium_traffic_debt_bytes=premium_traffic_result[
                                "next_debt_bytes"
                            ],
                            premium_traffic_debt_updated_date=premium_traffic_result[
                                "next_debt_updated_date"
                            ],
                        )
                    )
                    session.execute(stmt)
            else:
                with get_session() as session:
                    stmt = select(Statistics.credits).where(Statistics.tg_id == tg_id)
                    credits_init = session.execute(stmt).scalar()
                # 加上勋章加成
                credits = (
                    credits_init + credits_inc + badge_bonus - traffic_cost_credits
                )
                watched_time = watched_time_init + play_duration
                with get_session() as session:
                    stmt1 = (
                        sql_update(PlexUser)
                        .where(PlexUser.plex_id == plex_id)
                        .values(
                            watched_time=watched_time,
                            premium_traffic_debt_bytes=premium_traffic_result[
                                "next_debt_bytes"
                            ],
                            premium_traffic_debt_updated_date=premium_traffic_result[
                                "next_debt_updated_date"
                            ],
                        )
                    )
                    stmt2 = (
                        sql_update(Statistics)
                        .where(Statistics.tg_id == tg_id)
                        .values(credits=credits)
                    )
                    session.execute(stmt1)
                    session.execute(stmt2)

            # 邀请人奖励：被邀请人基础积分的 10%，与被邀请人是否绑定 tg 无关
            # 累积到字典，循环结束后统一发通知
            inviter_tg_id = db.get_inviter_tg_id_by_plex_id(plex_id)
            inviter_bonus = 0.0
            # 排除邀请人是自己的情况
            if inviter_tg_id and inviter_tg_id != tg_id and credits_inc > 0:
                inviter_bonus = round(credits_inc * 0.1, 2)
                if inviter_tg_id not in inviter_rewards:
                    inviter_rewards[inviter_tg_id] = {"total_bonus": 0.0, "details": []}
                inviter_rewards[inviter_tg_id]["total_bonus"] = round(
                    inviter_rewards[inviter_tg_id]["total_bonus"] + inviter_bonus, 2
                )
                inviter_rewards[inviter_tg_id]["details"].append(
                    {
                        "username": plex_username,
                        "base_credits": round(credits_inc, 2),
                        "bonus": inviter_bonus,
                    }
                )
                logger.info(
                    f"累积邀请人 {inviter_tg_id} 的奖励积分: +{inviter_bonus} (来自用户 {plex_username} ({plex_id}))"
                )

            if tg_id and play_duration > 0:
                # 构建勋章加成信息 - 只显示总加成积分
                badge_bonus_text = ""
                if badge_bonus > 0:
                    badge_bonus_text = f"\n勋章加成积分: +{round(badge_bonus, 2)}"

                # 构建惩罚信息 - 只显示总惩罚分数
                total_penalty = time_penalty + data_penalty
                penalty_text = ""
                if total_penalty > 0:
                    penalty_text = f"\n观看消耗积分: -{round(total_penalty, 2)}"

                # 构建邀请人奖励信息
                inviter_bonus_text = ""
                if inviter_bonus > 0:
                    inviter_bonus_text = (
                        f"\n邀请人额外奖励: +{inviter_bonus} (已发放给邀请人)"
                    )

                # 需要发送通知
                notification_tasks.append(
                    (
                        tg_id,
                        f"""
Plex 观看积分更新通知
====================

新增观看时长: {round(play_duration, 2)} 小时
基础观看积分: {round(original_credits_inc, 2)}{penalty_text}{badge_bonus_text}{inviter_bonus_text}
Premium 流量使用情况: {round(traffic_usage_premium / (1024 * 1024 * 1024), 2)} GB
Premium 当日可用免费额度: {round(premium_traffic_result["effective_limit"] / (1024 * 1024 * 1024), 2)} GB
Premium 当日前待偿还额度: {round(premium_traffic_result["debt_before_today"] / (1024 * 1024 * 1024), 2)} GB
Premium 自动偿还额度: {round(premium_traffic_result["recovered_before_today"] / (1024 * 1024 * 1024), 2)} GB
Premium 当日超额流量: {max(round(traffic_usage_exceed / (1024 * 1024 * 1024), 2), 0)} GB
Premium 结转待偿还额度: {round(premium_traffic_result["next_debt_bytes"] / (1024 * 1024 * 1024), 2)} GB
Premium 实际扣费流量: {round(premium_traffic_result["chargeable_bytes"] / (1024 * 1024 * 1024), 2)} GB
Premium 流量消耗积分: {round(traffic_cost_credits, 2)}

积分变化: {round(credits_inc + badge_bonus - traffic_cost_credits, 2):+.2f}

--------------------

当前总积分: {round(credits, 2)}
当前总观看时长: {round(watched_time, 2)} 小时

====================""",
                    )
                )

            logger.info(
                f"更新 Plex 用户 {plex_username} ({plex_id}) 的积分和观看时长: "
                f"新增观看时长 {round(play_duration, 2)} 小时，新增观看积分 {round(credits_inc, 2)} (原始: {round(original_credits_inc, 2)}, 时长惩罚: {round(time_penalty, 2)}, 流量惩罚: {round(data_penalty, 2)}), 流量消耗积分 {round(traffic_cost_credits, 2)}"
            )

        # 循环结束后，统一更新邀请人积分并发送汇总通知
        for inviter_tg_id, reward_info in inviter_rewards.items():
            total_bonus = reward_info["total_bonus"]
            details = reward_info["details"]
            inviter_credits_now = db.get_user_credits(inviter_tg_id)
            if inviter_credits_now is None:
                logger.warning(
                    f"邀请人 {inviter_tg_id} 在 statistics 表中无记录，跳过奖励"
                )
                continue
            db.update_user_credits(
                inviter_credits_now + total_bonus, tg_id=inviter_tg_id
            )
            logger.info(
                f"邀请人 {inviter_tg_id} 共获得 Plex 邀请奖励积分: +{total_bonus}"
            )
            # 构建明细行
            detail_lines = "\n".join(
                f"  · {d['username']}: 基础积分 {d['base_credits']} → 奖励 +{d['bonus']}"
                for d in details
            )
            stat_date = (datetime.now(settings.TZ) - timedelta(days=1)).strftime(
                "%Y-%m-%d"
            )
            notification_tasks.append(
                (
                    inviter_tg_id,
                    f"""
Plex 邀请奖励通知
====================

{stat_date} 共 {len(details)} 位被邀请用户有新增观看记录:
{detail_lines}

本次邀请奖励积分: +{total_bonus}

--------------------

当前总积分: {round(inviter_credits_now + total_bonus, 2)}

====================""",
                )
            )

    except Exception as e:
        logger.error(f"更新 Plex 用户积分及观看时长失败: {e}")
        for chat_id in settings.TG_ADMIN_CHAT_ID:
            notification_tasks.append(
                (
                    chat_id,
                    f"更新 Plex 用户积分及观看时长失败: {e}",
                )
            )
        return notification_tasks, deduction_records
    else:
        # 补偿时长已确实写入积分与观看时长，此时才允许标记结算，
        # 中途失败则保持未结算状态，留到下一轮补上
        if ghost_compensation:
            db.mark_ghost_compensation_settled()
            logger.info(f"已结算 {len(ghost_compensation)} 个用户的幽灵会话补偿时长")
        # 推进结算水位线：本次处理的是前一天的数据。之后再检出该日期及更早的
        # 幽灵会话时，清理任务据此判定为「已结算」，只删除不补偿。
        _set_settled_through_date(
            (datetime.now(settings.TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        )
        logger.info("Plex 用户积分及观看时长更新完成")
        return notification_tasks, deduction_records


def update_emby_credits():
    """更新 emby 积分及观看时长"""
    logger.info("开始更新 Emby 用户积分及观看时长")
    # 获取所有用户的观看时长
    emby = Emby()
    notification_tasks = []
    deduction_records = []
    # 邀请人奖励累积字典: {inviter_tg_id: {"total_bonus": float, "details": [{"username": str, "base_credits": float, "bonus": float}]}}
    inviter_rewards: dict = {}
    try:
        duration = emby.get_user_total_play_time()
        # 获取数据库中的观看时长信息
        with get_session() as session:
            stmt = select(
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
            users = session.execute(stmt).fetchall()
        for user in users:
            playduration = round(float(duration.get(user[0], 0)) / 3600, 2)
            # 最大记 8
            daily_play_duration = playduration - user[2]
            credits_inc = min(daily_play_duration, 8)
            next_watched_time = max(playduration, user[2])
            emby_username, is_premium = user[4], user[5]
            premium_status_updated_at = user[6]
            debt_bytes = int(user[7] or 0)
            debt_updated_date = user[8]
            settlement_date = datetime.now(settings.TZ) - timedelta(days=1)
            is_premium_for_settlement = _resolve_premium_status_for_settlement(
                current_is_premium=bool(is_premium),
                premium_status_updated_at=premium_status_updated_at,
                settlement_date=settlement_date,
            )
            # 获取用户昨日的 premium 流量使用情况（用于流量费用计算）
            traffic_usage_premium = db.get_user_daily_traffic(
                username=emby_username,
                service="emby",
                date=settlement_date,
                premium_only=True,
            )
            # 获取用户昨日的总流量（用于流量惩罚计算）
            traffic_usage_total = db.get_user_daily_traffic(
                username=emby_username,
                service="emby",
                date=settlement_date,
                premium_only=False,
            )

            premium_traffic_result = _settle_premium_traffic_usage(
                traffic_usage_premium=traffic_usage_premium,
                is_premium=is_premium_for_settlement,
                debt_bytes=debt_bytes,
                debt_updated_date=debt_updated_date,
                settlement_date=settlement_date,
            )
            traffic_usage_exceed = premium_traffic_result["exceed_bytes"]
            traffic_cost_credits = premium_traffic_result["traffic_cost_credits"]
            if traffic_cost_credits > 0:
                deduction_records.append(
                    {
                        "service": "Emby",
                        "username": emby_username,
                        "tg_id": user[1],
                        "deducted_credits": traffic_cost_credits,
                        "chargeable_bytes": premium_traffic_result["chargeable_bytes"],
                    }
                )

            if (
                daily_play_duration <= 0
                and traffic_usage_total == 0
                and premium_traffic_result["debt_before_today"] == 0
                and premium_traffic_result["next_debt_bytes"] == 0
            ):
                if debt_bytes > 0 or debt_updated_date:
                    with get_session() as session:
                        stmt = (
                            sql_update(EmbyUser)
                            .where(EmbyUser.emby_id == user[0])
                            .values(
                                premium_traffic_debt_bytes=premium_traffic_result[
                                    "next_debt_bytes"
                                ],
                                premium_traffic_debt_updated_date=premium_traffic_result[
                                    "next_debt_updated_date"
                                ],
                            )
                        )
                        session.execute(stmt)
                continue

            # 计算超长观看惩罚 (TimePenalty)
            time_penalty = 0
            if daily_play_duration > 8 * 1.2:
                time_penalty = (daily_play_duration - 8 * 1.2) * 0.5

            # 计算超额流量惩罚 (DataPenalty) - 使用非premium流量
            data_penalty = 0
            data_ratio = 0
            expected_data = daily_play_duration * 10 * 1024 * 1024 * 1024  # 10 GB/小时
            if traffic_usage_total > 0 and expected_data > 0:
                data_ratio = float(traffic_usage_total) / float(expected_data)
                if data_ratio > 1.2:
                    data_penalty = float(credits_inc) * (data_ratio - 1.2) * 0.5

            # 应用惩罚到基础积分
            final_daily_score = max(
                0, min(credits_inc - time_penalty - data_penalty, 8)
            )
            # 保存原始 credits_inc 用于显示
            original_credits_inc = credits_inc
            credits_inc = final_daily_score

            # 计算勋章加成
            badge_bonus = 0
            badge_bonus_details = []
            if user[1]:
                active_badges = db.get_user_active_badges_with_bonus(user[1])
                for badge_info in active_badges:
                    bonus_percentage = float(badge_info["bonus_percentage"])
                    bonus_credits = float(credits_inc) * bonus_percentage
                    badge_bonus += bonus_credits
                    badge_bonus_details.append(
                        {
                            "name": badge_info["badge"]["name"],
                            "percentage": bonus_percentage * 100,
                            "credits": round(bonus_credits, 2),
                        }
                    )

            if not user[1]:
                _credits = user[3] + credits_inc - traffic_cost_credits
                with get_session() as session:
                    stmt = (
                        sql_update(EmbyUser)
                        .where(EmbyUser.emby_id == user[0])
                        .values(
                            emby_watched_time=next_watched_time,
                            emby_credits=_credits,
                            premium_traffic_debt_bytes=premium_traffic_result[
                                "next_debt_bytes"
                            ],
                            premium_traffic_debt_updated_date=premium_traffic_result[
                                "next_debt_updated_date"
                            ],
                        )
                    )
                    session.execute(stmt)
            else:
                stats_info = db.get_stats_by_tg_id(user[1])
                # statistics 表中有数据
                if stats_info:
                    credits_init = stats_info[2]
                    # 加上勋章加成
                    _credits = (
                        credits_init + credits_inc + badge_bonus - traffic_cost_credits
                    )
                    db.update_user_credits(_credits, tg_id=user[1])
                else:
                    # 清空 emby_user 表中积分信息
                    db.update_user_credits(0, emby_id=user[0])
                    # 在 statistic 表中增加用户数据
                    _credits = (
                        user[3] + credits_inc + badge_bonus - traffic_cost_credits
                    )
                    db.add_user_data(user[1], credits=_credits)
                # 更新 emby_user 表中观看时间
                with get_session() as session:
                    stmt = (
                        sql_update(EmbyUser)
                        .where(EmbyUser.emby_id == user[0])
                        .values(
                            emby_watched_time=next_watched_time,
                            premium_traffic_debt_bytes=premium_traffic_result[
                                "next_debt_bytes"
                            ],
                            premium_traffic_debt_updated_date=premium_traffic_result[
                                "next_debt_updated_date"
                            ],
                        )
                    )
                    session.execute(stmt)

            # 邀请人奖励：被邀请人基础积分的 10%，与被邀请人是否绑定 tg 无关
            # 累积到字典，循环结束后统一发通知
            inviter_tg_id = db.get_inviter_tg_id_by_emby_id(user[0])
            inviter_bonus = 0.0
            # 排除邀请人是自己的情况
            if inviter_tg_id and inviter_tg_id != user[1] and credits_inc > 0:
                inviter_bonus = round(credits_inc * 0.1, 2)
                if inviter_tg_id not in inviter_rewards:
                    inviter_rewards[inviter_tg_id] = {"total_bonus": 0.0, "details": []}
                inviter_rewards[inviter_tg_id]["total_bonus"] = round(
                    inviter_rewards[inviter_tg_id]["total_bonus"] + inviter_bonus, 2
                )
                inviter_rewards[inviter_tg_id]["details"].append(
                    {
                        "username": emby_username,
                        "base_credits": round(credits_inc, 2),
                        "bonus": inviter_bonus,
                    }
                )
                logger.info(
                    f"累积邀请人 {inviter_tg_id} 的奖励积分: +{inviter_bonus} (来自用户 {emby_username} ({user[0]}))"
                )

            if user[1] and (playduration - user[2]) > 0:
                # 构建勋章加成信息 - 只显示总加成积分
                badge_bonus_text = ""
                if badge_bonus > 0:
                    badge_bonus_text = f"\n勋章加成积分: +{round(badge_bonus, 2)}"

                # 构建惩罚信息 - 只显示总惩罚分数
                total_penalty = time_penalty + data_penalty
                penalty_text = ""
                if total_penalty > 0:
                    penalty_text = f"\n观看消耗积分: -{round(total_penalty, 2)}"

                # 构建邀请人奖励信息
                inviter_bonus_text = ""
                if inviter_bonus > 0:
                    inviter_bonus_text = (
                        f"\n邀请人额外奖励: +{inviter_bonus} (已发放给邀请人)"
                    )

                # 需要发送消息通知
                notification_tasks.append(
                    (
                        user[1],
                        f"""
Emby 观看积分更新通知
====================

新增观看时长: {round(playduration - user[2], 2)} 小时
基础观看积分: {round(original_credits_inc, 2)}{penalty_text}{badge_bonus_text}{inviter_bonus_text}
Premium 流量使用情况: {round(traffic_usage_premium / (1024 * 1024 * 1024), 2)} GB
Premium 当日可用免费额度: {round(premium_traffic_result["effective_limit"] / (1024 * 1024 * 1024), 2)} GB
Premium 当日前待偿还额度: {round(premium_traffic_result["debt_before_today"] / (1024 * 1024 * 1024), 2)} GB
Premium 自动偿还额度: {round(premium_traffic_result["recovered_before_today"] / (1024 * 1024 * 1024), 2)} GB
Premium 当日超额流量: {max(round(traffic_usage_exceed / (1024 * 1024 * 1024), 2), 0)} GB
Premium 结转待偿还额度: {round(premium_traffic_result["next_debt_bytes"] / (1024 * 1024 * 1024), 2)} GB
Premium 实际扣费流量: {round(premium_traffic_result["chargeable_bytes"] / (1024 * 1024 * 1024), 2)} GB
Premium 流量消耗积分: {round(traffic_cost_credits, 2)}

积分变化: {round(credits_inc + badge_bonus - traffic_cost_credits, 2):+.2f}

--------------------

当前总积分: {round(_credits, 2)}
当前总观看时长: {round(playduration, 2)} 小时

====================""",
                    )
                )

            logger.info(
                f"更新 Emby 用户 {emby_username} ({user[0]}) 的积分和观看时长: "
                f"新增观看时长 {round(playduration - user[2], 2)} 小时，新增观看积分 {round(credits_inc, 2)} (原始: {round(original_credits_inc, 2)}, 时长惩罚: {round(time_penalty, 2)}, 流量惩罚: {round(data_penalty, 2)}), 流量消耗积分 {round(traffic_cost_credits, 2)}"
            )

        # 循环结束后，统一更新邀请人积分并发送汇总通知
        for inviter_tg_id, reward_info in inviter_rewards.items():
            total_bonus = reward_info["total_bonus"]
            details = reward_info["details"]
            inviter_credits_now = db.get_user_credits(inviter_tg_id)
            if inviter_credits_now is None:
                logger.warning(
                    f"邀请人 {inviter_tg_id} 在 statistics 表中无记录，跳过奖励"
                )
                continue
            db.update_user_credits(
                inviter_credits_now + total_bonus, tg_id=inviter_tg_id
            )
            logger.info(
                f"邀请人 {inviter_tg_id} 共获得 Emby 邀请奖励积分: +{total_bonus}"
            )
            # 构建明细行
            detail_lines = "\n".join(
                f"  · {d['username']}: 基础积分 {d['base_credits']} → 奖励 +{d['bonus']}"
                for d in details
            )
            stat_date = (datetime.now(settings.TZ) - timedelta(days=1)).strftime(
                "%Y-%m-%d"
            )
            notification_tasks.append(
                (
                    inviter_tg_id,
                    f"""
Emby 邀请奖励通知
====================

{stat_date} 共 {len(details)} 位被邀请用户有新增观看记录:
{detail_lines}

本次邀请奖励积分: +{total_bonus}

--------------------

当前总积分: {round(inviter_credits_now + total_bonus, 2)}

====================""",
                )
            )

    except Exception as e:
        logger.error(f"更新 Emby 用户积分及观看时长失败: {e}")
        for chat_id in settings.TG_ADMIN_CHAT_ID:
            notification_tasks.append(
                (
                    chat_id,
                    f"更新 Emby 用户积分及观看时长失败: {e}",
                )
            )
        return notification_tasks, deduction_records
    else:
        logger.info("Emby 用户积分及观看时长更新完成")
        return notification_tasks, deduction_records
