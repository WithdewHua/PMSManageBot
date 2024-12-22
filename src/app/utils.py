#!/usr/bin/env python3

import logging
import pickle
from time import time

import requests
from app.config import settings


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


def get_user_name_from_tg_id(chat_id, token=settings.TG_API_TOKEN):
    """Get telegram user's info
    cache format: {tg_id: {"first_name": first_name, "username": username, "added": timestamp}}
    """
    cache_file = settings.DATA_PATH / "tg_user_info.cache"
    cache = {}
    if cache_file.exists():
        with open(cache_file, "rb") as f:
            cache = pickle.load(f)
    # get from cache if exists
    current_time = time()
    if cache and chat_id in cache:
        user_info = cache.get(chat_id)
        # if not expire (7d)
        if current_time - user_info.get("added") < 7 * 24 * 3600:
            return user_info.get("first_name") or user_info.get("username") or chat_id
    response = requests.get(
        url=f"https://api.telegram.org/bot{token}/getChat?chat_id={chat_id}"
    )
    if not response.ok:
        logging.error(f"Error: failed to get info. for {chat_id}")
        return chat_id
    result = response.json().get("result", {})
    # add cache
    cache.update(
        {
            chat_id: {
                "first_name": result.get("first_name"),
                "username": result.get("username"),
                "added": current_time,
            }
        }
    )
    with open(cache_file, "wb") as f:
        pickle.dump(cache, f)
    return result.get("first_name") or result.get("username") or chat_id
