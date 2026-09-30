from __future__ import annotations

import re
import time
from datetime import UTC, date, datetime, timedelta
from operator import itemgetter
from typing import Any

import pytz

from app.core.config import settings
from app.core.log import logger
from app.domains.accounts import service as accounts_service
from app.domains.credits import service as credits_service
from app.domains.crypto_donation import service as crypto_donation_service
from app.domains.custom_lines import service as custom_lines_service
from app.domains.donation import service as donation_service
from app.domains.invitation import service as invitation_service
from app.domains.lines import service as lines_service
from app.domains.media_access import service as media_access_service
from app.domains.premium import service as premium_service
from app.domains.reports import repository
from app.domains.reports.constants import (
    ARTIST_STAT,
    BODY_TEXT,
    EMBY_BODY_TEXT,
    MOVIE_STAT,
    PHOTO_STAT,
    SHOW_STAT,
    USER_IGNORE,
    USER_STAT,
)
from app.domains.reports.rules import add_to_dictval, date_split, daterange
from app.domains.traffic import service as traffic_service
from app.domains.vaultwarden import service as vaultwarden_service
from app.integrations.emby import Emby
from app.integrations.tautulli import Tautulli
from app.integrations.telegram.messaging import send_message_by_url


def get_business_config_overview() -> dict[str, Any]:
    """Read the current business configuration for status/report endpoints."""
    accounts = accounts_service.get_registration_config()
    return {
        "plex_register": accounts.plex_register,
        "emby_register": accounts.emby_register,
        "premium_free": lines_service.is_premium_free_enabled(),
        "premium_unlock_enabled": premium_service.is_premium_unlock_enabled(),
        "premium_daily_credits": premium_service.get_premium_daily_credits(),
        "credits_transfer_enabled": credits_service.is_transfer_enabled(),
        "invitation_credits": invitation_service.get_invitation_credits(),
        "unlock_credits": media_access_service.get_unlock_credits(),
        "download_unlock_credits": media_access_service.get_download_unlock_credits(),
        "line_schedule_unlock_credits": lines_service.get_line_schedule_unlock_credits(),
        "user_traffic_limit": traffic_service.get_user_traffic_limit(),
        "premium_user_traffic_limit": traffic_service.get_premium_user_traffic_limit(),
        "credits_cost_per_10gb": premium_service.get_credits_cost_per_10gb(),
        "nsfw_libs": media_access_service.get_nsfw_libs(),
        "donation_multiplier": donation_service.get_donation_multiplier(),
        "upay_crypto_types": crypto_donation_service.get_supported_crypto_types(),
        "vaultwarden_enabled": vaultwarden_service.is_enabled(),
        "vaultwarden_redeem_credits": vaultwarden_service.get_redeem_credits(),
    }


def get_system_stats() -> dict[str, int]:
    """Assemble overall system statistics across media users and capabilities."""
    return {
        "plex_users": repository.get_plex_users_num(),
        "emby_users": repository.get_emby_users_num(),
        "total_users": repository.get_total_users_num(),
        "nsfw_unlocked_users": repository.get_nsfw_unlocked_users_num(),
        "line_schedule_unlocked_users": repository.get_line_schedule_unlocked_users_num(),
        "vaultwarden_redeemed_count": vaultwarden_service.count_redemptions(),
        "download_unlocked_users": repository.get_download_unlocked_users_num(),
    }


def get_system_status() -> dict[str, Any]:
    """Assemble public system status overview."""
    business_config = get_business_config_overview()
    return {
        "site_name": settings.SITE_NAME,
        "emby_entry_url": settings.EMBY_ENTRY_URL or settings.EMBY_BASE_URL,
        "plex_register": business_config["plex_register"],
        "emby_register": business_config["emby_register"],
        "premium_unlock_enabled": business_config["premium_unlock_enabled"],
        "premium_free": business_config["premium_free"],
        "premium_daily_credits": business_config["premium_daily_credits"],
        "credits_transfer_enabled": business_config["credits_transfer_enabled"],
        "community_links": {
            "group": getattr(settings, "TG_GROUP", ""),
            "channel": getattr(
                settings, "TG_CHANNEL", getattr(settings, "TG_GROUP", "")
            ),
        },
    }


def get_admin_settings_overview() -> dict[str, Any]:
    """Assemble complete settings overview for admin view."""
    business_config = get_business_config_overview()
    return {
        "plex_register": business_config["plex_register"],
        "emby_register": business_config["emby_register"],
        "premium_free": business_config["premium_free"],
        "premium_unlock_enabled": business_config["premium_unlock_enabled"],
        "lines": lines_service.get_normal_lines(),
        "premium_lines": lines_service.get_premium_lines(),
        "free_premium_lines": lines_service.get_free_premium_lines(),
        "invitation_credits": business_config["invitation_credits"],
        "unlock_credits": business_config["unlock_credits"],
        "premium_daily_credits": business_config["premium_daily_credits"],
        "user_traffic_limit": business_config["user_traffic_limit"],
        "premium_user_traffic_limit": business_config["premium_user_traffic_limit"],
        "credits_transfer_enabled": business_config["credits_transfer_enabled"],
        "line_schedule_unlock_credits": business_config["line_schedule_unlock_credits"],
        "download_unlock_credits": business_config["download_unlock_credits"],
        "credits_cost_per_10gb": business_config["credits_cost_per_10gb"],
        "nsfw_libs": business_config["nsfw_libs"],
        "donation_multiplier": business_config["donation_multiplier"],
        "upay_crypto_types": business_config["upay_crypto_types"],
        "vaultwarden_enabled": business_config["vaultwarden_enabled"],
        "vaultwarden_redeem_credits": business_config["vaultwarden_redeem_credits"],
    }


def get_traffic_statistics() -> dict[str, Any]:
    """Get comprehensive traffic statistics today/week/month grouped by service and line."""
    try:
        now = datetime.now(settings.TZ)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=now.weekday())
        month_start = today_start.replace(day=1)

        periods = [
            ("today", today_start.isoformat()),
            ("week", week_start.isoformat()),
            ("month", month_start.isoformat()),
        ]

        raw_stats = repository.get_raw_traffic_stats(periods)
        approved_custom_lines = set(custom_lines_service.list_approved_domains())

        result: dict[str, Any] = {}
        for period_name, _ in periods:
            total_traffic, service_results, line_results = raw_stats[period_name]
            period_data: dict[str, Any] = {
                "total": total_traffic,
                "emby": 0,
                "plex": 0,
                "lines": [],
                "custom_lines": [],
            }

            for service, traffic in service_results:
                service_lower = service.lower()
                if service_lower == "emby":
                    period_data["emby"] = traffic
                elif service_lower == "plex":
                    period_data["plex"] = traffic

            for line, traffic in line_results:
                is_known_line = lines_service.is_known_catalog_line(line)
                if is_known_line:
                    period_data["lines"].append({"line": line, "traffic": traffic})

                # If not a catalog line, check if approved custom line
                if not is_known_line and line in approved_custom_lines:
                    period_data["custom_lines"].append(
                        {"line": line, "traffic": traffic, "is_custom": True}
                    )

            result[period_name] = period_data

        return result

    except Exception as e:
        logger.error(f"Error getting comprehensive traffic statistics: {e}")
        return {
            "today": {
                "total": 0,
                "emby": 0,
                "plex": 0,
                "lines": [],
                "custom_lines": [],
            },
            "week": {
                "total": 0,
                "emby": 0,
                "plex": 0,
                "lines": [],
                "custom_lines": [],
            },
            "month": {
                "total": 0,
                "emby": 0,
                "plex": 0,
                "lines": [],
                "custom_lines": [],
            },
        }


def get_current_playing_users() -> tuple[int, int]:
    """Get currently playing user counts from Tautulli (Plex) and Emby."""
    current_plex_user_num = Tautulli().get_plex_current_playing_user_num()
    current_emby_user_num = Emby().get_emby_current_playing_user_num()
    return current_plex_user_num, current_emby_user_num


async def send_weekly_report(channel_id: str = settings.TG_CHANNEL_ID) -> str:
    """Generate and dispatch the weekly Tautulli/Emby statistics report to Telegram."""
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
    return report


def utc_now_iso():
    """Get current UTC time in the legacy ISO format without an offset."""
    return datetime.now(UTC).isoformat().removesuffix("+00:00")


def get_user_stats(home_stats, stats_type):
    user_stats_lst = []
    user_stats_dict = {}
    logger.info("Checking users stats.")
    for stats in home_stats:
        if stats["stat_id"] == "top_users":
            for row in stats["rows"]:
                if row["friendly_name"] in USER_IGNORE:
                    continue
                if stats_type == "duration":
                    add_to_dictval(
                        user_stats_dict, row["friendly_name"], row["total_duration"]
                    )
                else:
                    add_to_dictval(
                        user_stats_dict, row["friendly_name"], row["total_plays"]
                    )

    for idx, (user, stat) in enumerate(
        sorted(user_stats_dict.items(), key=itemgetter(1), reverse=True), start=1
    ):
        if stats_type == "duration":
            user_total = timedelta(seconds=stat)
            USER_STATS = USER_STAT.format(user, user_total, idx)
        else:
            USER_STATS = USER_STAT.format(user, stat, idx)
        user_stats_lst += [f"{USER_STATS}"]

    return user_stats_lst


def get_most_watched_stats(home_stats, stats_type):
    movie_stats_lst, tv_stats_lst = [], []
    movie_stats_dict, tv_stats_dict = {}, {}
    stat_id_dict_map = {"top_movies": movie_stats_dict, "top_tv": tv_stats_dict}
    stat_id_list_map = {"top_movies": movie_stats_lst, "top_tv": tv_stats_lst}
    logger.info("Checking most watched movies and tvs stats.")
    for stats in home_stats:
        if stats["stat_id"] in ["top_movies", "top_tv"]:
            for row in stats["rows"]:
                # ignore nsfw
                if re.search(r"\w{3,4}-\d{2,5}", row["title"]):
                    continue
                if stats_type == "duration":
                    add_to_dictval(
                        stat_id_dict_map.get(stats["stat_id"]),
                        f"{row['title']} ({row['year']})",
                        row["total_duration"],
                    )
                else:
                    add_to_dictval(
                        stat_id_dict_map.get(stats["stat_id"]),
                        f"{row['title']} ({row['year']})",
                        row["total_plays"],
                    )

    for media_type, media_dict in stat_id_dict_map.items():
        for idx, (media, stat) in enumerate(
            sorted(media_dict.items(), key=itemgetter(1), reverse=True), start=1
        ):
            if stats_type == "duration":
                total = timedelta(seconds=stat)
                stat_id_list_map.get(media_type).append(f"{idx}. {media}: {total}")
            else:
                stat_id_list_map.get(media_type).append(f"{idx}. {media}: {stat} plays")

    return [movie_stats_lst, tv_stats_lst]


def get_lib_ignore() -> list[str]:
    return media_access_service.get_nsfw_libs()


def get_library_stats(libraries):
    section_count = ""
    sections_stats_lst = []

    logger.info("Checking library stats.")
    lib_ignore = get_lib_ignore()
    for section in libraries:
        if section["section_type"] == "artist":
            section_count = ARTIST_STAT.format(
                section["count"], section["parent_count"], section["child_count"]
            )

        elif section["section_type"] == "show":
            section_count = SHOW_STAT.format(
                section["count"], section["parent_count"], section["child_count"]
            )

        elif section["section_type"] == "photo":
            section_count = PHOTO_STAT.format(
                section["count"], section["parent_count"], section["child_count"]
            )

        elif section["section_type"] == "movie":
            section_count = MOVIE_STAT.format(section["count"])

        if section["section_name"] not in lib_ignore and section_count:
            sections_stats_lst += [
                "{}: {}".format(section["section_name"], section_count)
            ]

    return sections_stats_lst


def stats_report(
    days=7,
    top=5,
    stat="duration",
    refresh=False,
    all_stats=False,
    library_stats=False,
    user_stats=False,
    watched_stats=False,
    body_text=BODY_TEXT,
    emby=True,
    emby_body_text=EMBY_BODY_TEXT,
):
    tautulli_server = Tautulli(
        settings.TAUTULLI_URL.rstrip("/"),
        settings.TAUTULLI_APIKEY,
        settings.TAUTULLI_VERIFY_SSL,
    )

    if refresh:
        tautulli_server.get_library_media_info(refresh=True)

    TODAY = int(time.time())
    DAYS = days
    DAYS_AGO = int(TODAY - DAYS * 24 * 60 * 60)
    START_DATE = datetime.fromtimestamp(DAYS_AGO, tz=UTC).strftime(
        "%Y-%m-%d"
    )  # DAYS_AGO as YYYY-MM-DD
    END_DATE = datetime.fromtimestamp(TODAY, tz=UTC).strftime(
        "%Y-%m-%d"
    )  # TODAY as YYYY-MM-DD

    start_date = date(
        date_split(START_DATE)[0], date_split(START_DATE)[1], date_split(START_DATE)[2]
    )
    end_date = date(
        date_split(END_DATE)[0], date_split(END_DATE)[1], date_split(END_DATE)[2]
    )

    dates_range_lst = []
    for single_date in daterange(start_date, end_date):
        dates_range_lst += [single_date.strftime("%Y-%m-%d")]

    end = time.strftime("%a %b %d %Y", time.localtime(float(TODAY)))
    start = time.strftime("%a %b %d %Y", time.localtime(float(DAYS_AGO)))

    sections_stats = ""
    if all_stats or library_stats:
        libraries = tautulli_server.get_libraries()
        lib_stats = get_library_stats(libraries)
        sections_stats = "\n".join(lib_stats)

    user_stats_str = ""
    watched_movie_stats, watched_tv_stats = "", ""
    if all_stats or user_stats or watched_stats:
        home_stats = tautulli_server.get_home_stats(days, stat, top)
        if all_stats or user_stats:
            logger.info(f"Checking user stats from {days:02d} days ago.")
            user_stats_lst = get_user_stats(home_stats, stat)
            user_stats_str = "\n".join(user_stats_lst)
        if all_stats or watched_stats:
            movie_stats_lst, tv_stats_lst = get_most_watched_stats(home_stats, stat)
            watched_movie_stats = "\n".join(movie_stats_lst)
            watched_tv_stats = "\n".join(tv_stats_lst)

    body_text = body_text.format(
        end=end,
        start=start,
        sections_stats=sections_stats,
        user_stats=user_stats_str,
        watched_movie_stats=watched_movie_stats,
        watched_tv_stats=watched_tv_stats,
    )

    if emby:
        _emby = Emby()
        _end_date = datetime.fromtimestamp(TODAY, tz=pytz.timezone("Asia/Shanghai"))
        movie_flag, movie_msg = _emby.get_report(
            types="movie", days=days, limit=top, end_date=_end_date
        )
        tv_flag, tv_msg = _emby.get_report(
            types="episode", days=days, limit=top, end_date=_end_date
        )
        user_flag, user_msg = _emby.get_report(
            types="user", days=days, limit=top, end_date=_end_date
        )
        if movie_flag:
            movie_msg = "\n".join(movie_msg)
        if tv_flag:
            tv_msg = "\n".join(tv_msg)
        if user_flag:
            user_msg = "\n".join(user_msg)
        emby_body_text = emby_body_text.format(
            emby_user_stats=user_msg,
            emby_watched_movie_stats=movie_msg,
            emby_watched_tv_stats=tv_msg,
        )
        body_text += emby_body_text

    logger.debug(f"Report Body Text:\n{body_text}")

    return body_text


__all__ = [
    "get_admin_settings_overview",
    "get_business_config_overview",
    "get_current_playing_users",
    "get_library_stats",
    "get_most_watched_stats",
    "get_system_stats",
    "get_system_status",
    "get_traffic_statistics",
    "get_user_stats",
    "send_weekly_report",
    "stats_report",
    "utc_now_iso",
]
