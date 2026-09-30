from __future__ import annotations

from datetime import datetime, timedelta

from app.core.byte_size import format_bytes
from app.core.config import settings
from app.integrations.telegram.profiles import get_user_name_from_tg_id


def user_settlement_notification(
    service: str,
    *,
    play_duration: float,
    base_credits: float,
    penalty: float,
    traffic_cost: float,
    credits_change: float,
    balance: float,
    watched_time: float,
) -> str:
    return (
        f"{service} 观看积分更新通知\n====================\n\n"
        f"新增观看时长: {play_duration:.2f} 小时\n基础观看积分: {base_credits:.2f}\n"
        f"观看惩罚: -{penalty:.2f}\nPremium 流量消耗积分: {traffic_cost:.2f}\n"
        f"积分变化: {credits_change:+.2f}\n\n当前总积分: {balance:.2f}\n"
        f"当前总观看时长: {watched_time:.2f} 小时\n===================="
    )


def inviter_notification(
    service: str, settlement_date: str, rewards: dict[int, dict]
) -> list[tuple[int, str]]:
    notifications = []
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
    return notifications


def settlement_failures(failures: list[str], service: str) -> list[tuple[int, str]]:
    if not failures:
        return []
    text = (
        f"{service} 观看结算部分用户失败（这些用户未提交，可在下次重试）:\n"
        + "\n".join(f"- {failure}" for failure in failures)
    )
    return [(chat_id, text) for chat_id in settings.TG_ADMIN_CHAT_ID]


def _format_premium_traffic_deduction_summary(deduction_records: list[dict]) -> str:
    settlement_date = (datetime.now(settings.TZ) - timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )
    total_credits = sum(record["deducted_credits"] for record in deduction_records)
    total_chargeable_bytes = sum(
        record["chargeable_bytes"] for record in deduction_records
    )
    message_parts = [
        "💳 Premium 流量扣分汇总",
        f"⏰ 结算日期: {settlement_date}",
        "─" * 40,
    ]
    for service, title in (
        ("Plex", "🎬 Plex 扣分用户:"),
        ("Emby", "📺 Emby 扣分用户:"),
    ):
        service_records = [
            record for record in deduction_records if record["service"] == service
        ]
        if not service_records:
            continue
        message_parts.extend(["", title])
        for record in service_records:
            tg_id = record.get("tg_id")
            message_parts.append(
                f"  • {record['username']} | TG: {get_user_name_from_tg_id(tg_id) if tg_id else '未绑定 TG'} | "
                f"扣除积分: {record['deducted_credits']:.2f} | 扣费流量: {format_bytes(record['chargeable_bytes'])}"
            )
    message_parts.extend(
        [
            "",
            "📋 总计:",
            f"扣分用户: {len(deduction_records)} 人",
            f"扣除积分: {total_credits:.2f}",
            f"扣费流量: {format_bytes(total_chargeable_bytes)}",
        ]
    )
    return "\n".join(message_parts)


def _format_ghost_session_summary(summary: dict) -> str:
    lines = [
        "Tautulli 幽灵会话清理报告",
        "====================",
        "",
        f"扫描记录: {summary['scanned']} 条",
        f"清理删除: {summary['deleted']} 条",
    ]
    if summary.get("retried"):
        lines.append(f"补删遗留: {summary['retried']} 条")
    if summary["ghosts"]:
        compensated = [g for g in summary["ghosts"] if not g.get("already_settled")]
        settled = [g for g in summary["ghosts"] if g.get("already_settled")]

        def detail(item):
            return (
                f"· {item['friendly_name']}《{item['title']}》\n"
                f"  {item['play_date']} 原始 {item['raw_seconds'] / 3600:.2f}h → "
                f"补偿 {item['compensated_seconds'] / 3600:.2f}h "
                f"(媒体 {(item['media_seconds'] or 0) / 3600:.2f}h, 进度 {item['percent_complete']}%)"
            )

        if compensated:
            lines.extend(
                [
                    "",
                    "--- 已删除并补偿时长 ---",
                    *(detail(item) for item in compensated),
                ]
            )
        if settled:
            lines.extend(
                [
                    "",
                    "--- 已删除，不补偿（该日积分已结算，补偿会二次计入）---",
                    *(
                        f"· {item['friendly_name']}《{item['title']}》 {item['play_date']} 原始 {item['raw_seconds'] / 3600:.2f}h"
                        for item in settled
                    ),
                ]
            )
    if summary["undetermined"]:
        lines.extend(
            [
                "",
                "--- 无法判定，需人工确认 ---",
                *(
                    f"· {item['friendly_name']}《{item['title']}》 {item['raw_seconds'] / 3600:.2f}h (媒体元数据缺失)"
                    for item in summary["undetermined"]
                ),
            ]
        )
    if summary["failed"]:
        lines.extend(
            [
                "",
                f"--- 处理失败 {len(summary['failed'])} 条 ---",
                f"row_ids: {summary['failed']}",
            ]
        )
    lines.extend(["", "===================="])
    return "\n".join(lines)
