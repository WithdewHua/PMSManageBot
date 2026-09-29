"""Scheduler entry points for line cache refresh and automatic switching."""

from app.domains.lines import service as lines_service


def write_user_line_cache() -> None:
    return lines_service.write_user_line_cache()


async def auto_switch_user_lines(
    tg_id: int | None = None, service: str | None = None
) -> None:
    await lines_service.auto_switch_user_lines(tg_id=tg_id, service=service)
