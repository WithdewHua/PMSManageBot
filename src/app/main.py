# ruff: noqa: F403
from copy import copy

from app.config import settings
from app.handlers.db import *
from app.handlers.emby import *
from app.handlers.plex import *
from app.handlers.rank import *
from app.handlers.start import *
from app.handlers.status import *
from app.handlers.user import *
from app.log import logger
from telegram.ext import ApplicationBuilder

if __name__ == "__main__":
    application = ApplicationBuilder().token(settings.TG_API_TOKEN).build()

    local_vars = copy(locals())
    for var, val in local_vars.items():
        if var.endswith("_handler"):
            logger.info(f"Add handler: {var}")
            application.add_handler(val)

    application.run_polling()
