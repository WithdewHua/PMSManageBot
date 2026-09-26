from datetime import datetime, timedelta

from app.core.config import settings
from app.core.formatting import format_traffic_size
from app.core.telegram import get_user_name_from_tg_id


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
                f"扣除积分: {record['deducted_credits']:.2f} | "
                f"扣费流量: {format_traffic_size(record['chargeable_bytes'])}"
            )

    message_parts.extend(
        [
            "",
            "📋 总计:",
            f"扣分用户: {len(deduction_records)} 人",
            f"扣除积分: {total_credits:.2f}",
            f"扣费流量: {format_traffic_size(total_chargeable_bytes)}",
        ]
    )
    return "\n".join(message_parts)


def _format_ghost_session_summary(summary: dict) -> str:
    """把清理结果拼成管理员通知文本"""
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

        def _detail(item):
            return (
                f"· {item['friendly_name']}《{item['title']}》\n"
                f"  {item['play_date']} 原始 {item['raw_seconds'] / 3600:.2f}h → "
                f"补偿 {item['compensated_seconds'] / 3600:.2f}h "
                f"(媒体 {(item['media_seconds'] or 0) / 3600:.2f}h, "
                f"进度 {item['percent_complete']}%)"
            )

        if compensated:
            lines.append("")
            lines.append("--- 已删除并补偿时长 ---")
            lines.extend(_detail(item) for item in compensated)

        if settled:
            lines.append("")
            lines.append("--- 已删除，不补偿（该日积分已结算，补偿会二次计入）---")
            lines.extend(
                f"· {item['friendly_name']}《{item['title']}》 {item['play_date']} "
                f"原始 {item['raw_seconds'] / 3600:.2f}h"
                for item in settled
            )

    if summary["undetermined"]:
        lines.append("")
        lines.append("--- 无法判定，需人工确认 ---")
        for item in summary["undetermined"]:
            lines.append(
                f"· {item['friendly_name']}《{item['title']}》 "
                f"{item['raw_seconds'] / 3600:.2f}h (媒体元数据缺失)"
            )

    if summary["failed"]:
        lines.append("")
        lines.append(f"--- 处理失败 {len(summary['failed'])} 条 ---")
        lines.append(f"row_ids: {summary['failed']}")

    lines.append("")
    lines.append("====================")
    return "\n".join(lines)
