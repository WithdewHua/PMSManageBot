#!/usr/bin/env python3
#

import logging
from datetime import datetime

from app.config import settings


class TimezoneFormatter(logging.Formatter):
    """自定义格式化器，支持时区"""

    def __init__(self, fmt=None, datefmt=None, timezone=None):
        super().__init__(fmt, datefmt)
        self.timezone = timezone or settings.TZ

    def formatTime(self, record, datefmt=None):
        """格式化时间，应用时区"""
        ct = datetime.fromtimestamp(record.created, tz=self.timezone)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime("%Y-%m-%d %H:%M:%S")
        return s


# 日志格式
logging_datefmt = "%m/%d/%Y %H:%M:%S"
logging_format = "[%(asctime)s][%(levelname)s]<%(funcName)s>: %(message)s"


# 日志相关
logFormatter = TimezoneFormatter(
    fmt=logging_format, datefmt=logging_datefmt, timezone=settings.TZ
)

logger = logging.getLogger()
logger.setLevel(getattr(logging, settings.LOG_LEVEL))
while logger.handlers:  # Remove un-format logging in Stream, or all of messages are appearing more than once.
    logger.handlers.pop()

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
logger.addHandler(consoleHandler)

# uvicorn 日志
uvicorn_logger = logging.getLogger("uvicorn")
