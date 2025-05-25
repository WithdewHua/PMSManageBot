#!/usr/bin/env python3

import asyncio
import pickle
from time import sleep, time

import aiohttp
import filelock
import requests
from app.config import settings
from app.db import DB
from app.log import logger
from telegram.ext import ContextTypes


async def send_message(chat_id, text: str, context: ContextTypes.DEFAULT_TYPE, **kargs):
    """send telegram message"""
    retry = 10
    while retry > 0:
        try:
            if "connect_timeout" not in kargs:
                kargs["connect_timeout"] = 3
            await context.bot.send_message(chat_id=chat_id, text=text, **kargs)
            break
        except Exception as e:
            logger.error(f"Error: {e}, retrying in 1 seconds...")
            await asyncio.sleep(1)
            retry -= 1


async def send_message_by_url(
    chat_id, text: str, token: str = settings.TG_API_TOKEN, parse_mode="markdownv2"
):
    """send telegram message by url"""
    retry = 10
    while retry > 0:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    data={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
                    timeout=3,
                ) as response:
                    if response.status == 200:
                        break
        except Exception as e:
            logger.error(f"Error: {e}, retrying in 1 seconds...")
            await asyncio.sleep(1)
            retry -= 1


def get_user_total_duration(home_stats: dict):
    """Get user's total watched duration"""
    user_total_duration: dict = {}
    for row in home_stats.get("rows", []):
        user_id = row.get("user_id")
        total_duration = float(row.get("total_duration") / 3600)
        user_total_duration.update({user_id: total_duration})
    return user_total_duration


def caculate_credits_fund(unlock_time, unlock_credits: int):
    if not unlock_time:
        return 0
    cur_time = time()
    gap = cur_time - unlock_time
    # 一天内，返还 90%
    if gap <= 3600 * 24:
        return unlock_credits * 0.9
    elif gap <= 3600 * 24 * 7:
        return unlock_credits * 0.7
    elif gap <= 3600 * 24 * 30:
        return unlock_credits * 0.5
    else:
        return 0


def get_user_info_from_tg_id(chat_id, token=settings.TG_API_TOKEN):
    """Get telegram user's info
    cache format: {tg_id: {"first_name": first_name, "username": username, "added": timestamp}}
    """
    cache_file = settings.USER_INFO_CACHE_PATH
    cache = {}
    if not cache_file.exists():
        logger.warning(f"Not found {settings.USER_INFO_CACHE_PATH}")
        return {}
    with open(cache_file, "rb") as f:
        cache = pickle.load(f)
    return cache.get(chat_id, {})


def get_user_photo_url(tg_id: int, token: str = settings.TG_API_TOKEN):
    """获取 Telegram 头像"""
    retry = 5
    while retry > 0:
        try:
            # 获取用户头像
            photos_response = requests.get(
                f"https://api.telegram.org/bot{token}/getUserProfilePhotos?user_id={tg_id}&limit=1"
            )
            photo_url = None
            if photos_response.ok:
                photos_data = photos_response.json()
                if photos_data.get("result", {}).get("total_count", 0) > 0:
                    photo_file_id = photos_data["result"]["photos"][0][0]["file_id"]

                    # 获取文件路径
                    file_response = requests.get(
                        f"https://api.telegram.org/bot{token}/getFile?file_id={photo_file_id}"
                    )
                    if file_response.ok:
                        file_data = file_response.json()
                        if file_data.get("ok"):
                            file_path = file_data["result"]["file_path"]
                            photo_url = (
                                f"https://api.telegram.org/file/bot{token}/{file_path}"
                            )

            return photo_url
        except Exception:
            logger.error(f"Error: failed to get photo for {tg_id}, retrying...")
            sleep(1)
            retry -= 1
    return None


def get_user_name_from_tg_id(chat_id, token=settings.TG_API_TOKEN):
    user_info = get_user_info_from_tg_id(chat_id, token=token)
    return user_info.get("first_name") or user_info.get("username") or chat_id


def refresh_user_info(token: str = settings.TG_API_TOKEN):
    """刷新用户信息"""
    try:
        cache_file_lock = filelock.FileLock(
            str(settings.USER_INFO_CACHE_PATH) + ".lock"
        )
        if settings.USER_INFO_CACHE_PATH.exists():
            with open(settings.USER_INFO_CACHE_PATH, "rb") as f:
                cache = pickle.load(f)
        else:
            cache = {}
        db = DB()

        # 从 statistics 表获取所有用户
        stats_users = db.cur.execute("SELECT tg_id FROM statistics").fetchall()
        stats_users = [user[0] for user in stats_users]

        for tg_id in stats_users:
            # 缓存保留 7 天
            if tg_id in cache:
                if time() - cache.get(tg_id).get("added") <= 7 * 24 * 3600:
                    continue
            retry = 10
            while retry > 0:
                try:
                    response = requests.get(
                        url=f"https://api.telegram.org/bot{token}/getChat?chat_id={tg_id}"
                    )
                except Exception as e:
                    logger.error(f"Error: {e}, retrying in 1 seconds...")
                    sleep(1)
                    retry -= 1
                    continue
                else:
                    if not response.ok:
                        logger.error(f"Error: failed to get info. for {tg_id}")
                        return {}
                    break
            result = response.json().get("result", {})
            user_info = {
                "first_name": result.get("first_name"),
                "username": result.get("username"),
                "added": time(),
            }
            # 获取用户 photo url
            photo_url = get_user_photo_url(tg_id, token=token)
            user_info["photo_url"] = photo_url
            # add cache
            cache.update({tg_id: user_info})
        with cache_file_lock:
            with open(settings.USER_INFO_CACHE_PATH, "wb") as f:
                pickle.dump(cache, f)
    except Exception as e:
        logger.error(f"Refresh user tg info failed: {e}")
    finally:
        db.close()


class SingletonMeta(type):
    """Singleton metaclass"""

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]
