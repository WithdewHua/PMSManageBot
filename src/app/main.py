# ruff: noqa: F403
from app.config import settings
from app.handlers.db import *
from app.handlers.emby import *
from app.handlers.plex import *
from app.handlers.rank import *
from app.handlers.start import *
from app.handlers.status import *
from app.handlers.user import *
from telegram.ext import ApplicationBuilder

if __name__ == "__main__":
    application = ApplicationBuilder().token(settings.TG_API_TOKEN).build()

    for var, val in locals().items():
        if var.endswith("_handler"):
            application.add_handler(val)

    application.run_polling()
