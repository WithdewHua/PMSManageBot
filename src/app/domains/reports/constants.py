from app.core.config import settings

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
