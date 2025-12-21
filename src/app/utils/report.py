#!/usr/bin/env python
# -*- coding: utf-8 -*-


import re
import time
from builtins import range
from datetime import date, datetime, timedelta
from operator import itemgetter

import pytz
from app.config import settings
from app.log import logger
from app.modules.emby import Emby
from app.modules.tautulli import Tautulli
from app.utils.utils import send_message_by_url

# Remove library element you do not want shown. Logging before exclusion.
# SHOW_STAT = 'Shows: {0}, Episodes: {2}'
# SHOW_STAT = 'Episodes: {2}'
# SHOW_STAT = ''
SHOW_STAT = "Shows: {0}, Seasons: {1}, Episodes: {2}"
ARTIST_STAT = "Artists: {0}, Albums: {1}, Songs: {2}"
PHOTO_STAT = "Folders: {0}, Subfolders: {1}, Photos: {2}"
MOVIE_STAT = "{0}"

# Library names you do not want shown. Logging before exclusion.
LIB_IGNORE = settings.NSFW_LIBS

# Customize user stats display
# User: USER1 -> 1 hr 32 min 00 sec
USER_STAT = "{2}. {0} -> {1}"

# Usernames you do not want shown. Logging before exclusion.
USER_IGNORE = [settings.PLEX_ADMIN_USER]

# User stat choices
STAT_CHOICE = ["duration", "plays"]

# Customize time display
# {0:d} hr {1:02d} min {2:02d} sec  -->  1 hr 32 min 00 sec
# {0:d} hr {1:02d} min  -->  1 hr 32 min
# {0:02d} hr {1:02d} min  -->  01 hr 32 min
TIME_DISPLAY = "{0:d} hr {1:02d} min {2:02d} sec"

# Customize BODY to your liking
BODY_TEXT = """
<strong>🔥FunMedia Dashboard🔥</strong>

<strong>🎦服务器统计</strong>
{sections_stats}

<strong>👤上周用户榜 (Plex)</strong>
{user_stats}

<strong>🎥上周电影榜 (Plex)</strong>
{watched_movie_stats}

<strong>📺上周剧集榜 (Plex)</strong>
{watched_tv_stats}
"""

EMBY_BODY_TEXT = """
<strong>👤上周用户榜 (Emby)</strong>
{emby_user_stats}

<strong>🎥上周电影榜 (Emby)</strong>
{emby_watched_movie_stats}

<strong>📺上周剧集榜 (Emby)</strong>
{emby_watched_tv_stats}
"""


def utc_now_iso():
    """Get current time in ISO format"""
    utcnow = datetime.utcnow()

    return utcnow.isoformat()


def hex_to_int(value):
    """Convert hex value to integer"""
    try:
        return int(value, 16)
    except (ValueError, TypeError):
        return 0


def sizeof_fmt(num, suffix="B"):
    # Function found https://stackoverflow.com/a/1094933
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, "Yi", suffix)


def date_split(to_split):
    split_year = int(to_split.split("-")[0])
    split_month = int(to_split.split("-")[1])
    split_day = int(to_split.split("-")[2])
    return [split_year, split_month, split_day]


def add_to_dictval(d, key, val):
    if key not in d:
        d[key] = val
    else:
        d[key] += val


def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(n)


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

    idx = 0
    for user, stat in sorted(user_stats_dict.items(), key=itemgetter(1), reverse=True):
        idx += 1
        if stats_type == "duration":
            user_total = timedelta(seconds=stat)
            USER_STATS = USER_STAT.format(user, user_total, idx)
        else:
            USER_STATS = USER_STAT.format(user, stat, idx)
        user_stats_lst += ["{}".format(USER_STATS)]

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
        idx = 0
        for media, stat in sorted(media_dict.items(), key=itemgetter(1), reverse=True):
            idx += 1
            if stats_type == "duration":
                total = timedelta(seconds=stat)
                stat_id_list_map.get(media_type).append(f"{idx}. {media}: {total}")
            else:
                stat_id_list_map.get(media_type).append(f"{idx}. {media}: {stat} plays")

    return [movie_stats_lst, tv_stats_lst]


def get_library_stats(libraries):
    section_count = ""
    # total_size = 0
    sections_stats_lst = []

    logger.info("Checking library stats.")
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

        if section["section_name"] not in LIB_IGNORE and section_count:
            sections_stats_lst += [
                "{}: {}".format(section["section_name"], section_count)
            ]

    # sections_stats_lst += ['Capacity: {}'.format(sizeof_fmt(total_size))]

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
    START_DATE = datetime.utcfromtimestamp(DAYS_AGO).strftime(
        "%Y-%m-%d"
    )  # DAYS_AGO as YYYY-MM-DD
    END_DATE = datetime.utcfromtimestamp(TODAY).strftime(
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

    end = datetime.strptime(time.ctime(float(TODAY)), "%a %b %d %H:%M:%S %Y").strftime(
        "%a %b %d %Y"
    )
    start = datetime.strptime(
        time.ctime(float(DAYS_AGO)), "%a %b %d %H:%M:%S %Y"
    ).strftime("%a %b %d %Y")

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
            logger.info("Checking user stats from {:02d} days ago.".format(days))
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

    logger.debug("Report Body Text:\n{}".format(body_text))

    return body_text


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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Use Tautulli to pull library and user statistics for date range.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--days",
        default=7,
        metavar="",
        type=int,
        help="Enter in number of days to go back. \n(default: %(default)s)",
    )
    parser.add_argument(
        "-t",
        "--top",
        default=5,
        metavar="",
        type=int,
        help="Enter in number of top users to find. \n(default: %(default)s)",
    )
    parser.add_argument(
        "--stat",
        default="duration",
        choices=STAT_CHOICE,
        help="Enter in stats type to show. \n(default: %(default)s)",
    )

    parser.add_argument(
        "--refresh", action="store_true", help="Refresh all libraries in Tautulli"
    )
    parser.add_argument("--all_stats", action="store_true", help="Retrieve all stats.")
    parser.add_argument(
        "--library_stats", action="store_true", help="Only retrieve library stats."
    )
    parser.add_argument(
        "--user_stats", action="store_true", help="Only retrieve users stats."
    )

    parser.add_argument(
        "--watched_stats",
        action="store_true",
        help="Only retrieve watched movies and tv_shows stats.",
    )
    parser.add_argument("--emby", action="store_true", help="Retrieve stats for Emby.")

    opts = parser.parse_args()
    stats_report(
        days=opts.days,
        top=opts.top,
        stat=opts.stat,
        refresh=opts.refresh,
        all_stats=opts.all_stats,
        library_stats=opts.library_stats,
        user_stats=opts.user_stats,
        watched_stats=opts.watched_stats,
        emby=opts.emby,
    )
