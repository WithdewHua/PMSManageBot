from plexapi.server import CONFIG


# log
LOG_LEVEL = "DEBUG"

# plex
PLEX_BASE_URL = ""
PLEX_API_TOKEN = ""
PLEX_ADMIN_USER = ""
PLEX_ADMIN_EMAIL = ""

# library
NSFW_LIBS = ["NSFW", "NC17 Movies"]

# credits
UNLOCK_CREDITS = 100
INVITATION_CREDITS = 218

# TG
TG_API_TOKEN = ""
ADMIN_CHAT_ID = []

# tautulli
TAUTULLI_URL = ''
TAUTULLI_APIKEY = ''
TAUTULLI_PUBLIC_URL = '/'

if not TAUTULLI_URL:
    TAUTULLI_URL = CONFIG.data['auth'].get('tautulli_baseurl')
if not TAUTULLI_APIKEY:
    TAUTULLI_APIKEY = CONFIG.data['auth'].get('tautulli_apikey')
if not TAUTULLI_PUBLIC_URL:
    TAUTULLI_PUBLIC_URL = CONFIG.data['auth'].get('tautulli_public_url')

VERIFY_SSL = False

# emby
EMBY_BASE_URL = ""
EMBY_API_TOKEN = ""
EMBY_ADMIN_USER = ""
EMBY_USER_TEMPLATE = "UserTemplate"
