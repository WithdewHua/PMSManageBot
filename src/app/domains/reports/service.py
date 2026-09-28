import re
import time
from datetime import UTC, date, datetime, timedelta
from operator import itemgetter

import pytz

from app.core.config import settings
from app.core.log import logger
from app.domains.accounts import service as accounts_service
from app.domains.credits import service as credits_service
from app.domains.crypto_donation import service as crypto_donation_service
from app.domains.donation import service as donation_service
from app.domains.invitation import service as invitation_service
from app.domains.lines import service as lines_service
from app.domains.media_access import service as media_access_service
from app.domains.premium import service as premium_service
from app.domains.traffic import service as traffic_service
from app.domains.vaultwarden import service as vaultwarden_service
from app.integrations.emby import Emby
from app.integrations.tautulli import Tautulli


def get_business_config_overview() -> dict:
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


def utc_now_iso():
    """Get current UTC time in the legacy ISO format without an offset."""
    return datetime.now(UTC).isoformat().removesuffix("+00:00")


from app.domains.reports.constants import USER_IGNORE, USER_STAT
from app.domains.reports.rules import add_to_dictval


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


from app.domains.reports.constants import (
    ARTIST_STAT,
    MOVIE_STAT,
    PHOTO_STAT,
    SHOW_STAT,
)


def get_lib_ignore() -> list[str]:
    return media_access_service.get_nsfw_libs()


def get_library_stats(libraries):
    section_count = ""
    # total_size = 0
    sections_stats_lst = []

    logger.info("Checking library stats.")
    lib_ignore = get_lib_ignore()
    for section in libraries:
        # library = tautulli.get_library_media_info(section['section_id'])
        # total_size += library['total_file_size']

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

    # sections_stats_lst += ['Capacity: {}'.format(sizeof_fmt(total_size))]

    return sections_stats_lst


from app.domains.reports.constants import BODY_TEXT, EMBY_BODY_TEXT
from app.domains.reports.rules import date_split, daterange


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
