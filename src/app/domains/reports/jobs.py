from app.core.config import settings
from app.domains.reports.constants import BODY_TEXT, EMBY_BODY_TEXT
from app.domains.reports.service import stats_report
from app.integrations.telegram.messaging import send_message_by_url


async def send_weekly_report(channel_id: str = settings.TG_CHANNEL_ID):
    report = stats_report(
        days=7,
        top=10,
        stat="duration",
        refresh=False,
        all_stats=True,
        library_stats=False,
        user_stats=False,
        watched_stats=False,
        body_text=BODY_TEXT,
        emby=True,
        emby_body_text=EMBY_BODY_TEXT,
    )
    await send_message_by_url(
        chat_id=channel_id,
        text=report,
        parse_mode="HTML",
    )
