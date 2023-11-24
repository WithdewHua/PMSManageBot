#! /usr/bin/env python3

import requests
import json

from typing import Optional

from log import logger
from settings import (
    EMBY_BASE_URL,
    EMBY_API_TOKEN,
    EMBY_ADMIN_USER,
    EMBY_USER_TEMPLATE,
)


class Emby:
    def __init__(
        self, base_url: str = EMBY_BASE_URL, api_token: str = EMBY_API_TOKEN
    ) -> None:
        self.base_url = base_url
        self.api_token = api_token

    def add_user(
        self, username: str, user_template: str = EMBY_USER_TEMPLATE
    ) -> tuple[bool, str]:
        header = {"accept": "application/json", "Content-Type": "application/json"}

        data = {
            "Name": username,
            "CopyFromUserId": self.get_uid_from_username(user_template),
            "UserCopyOptions": ["UserPolicy"],
        }

        try:
            response = requests.post(
                url=self.base_url + "/Users/New" + f"?api_key={self.api_token}",
                data=json.dumps(data),
                headers=header,
            )

            if response:
                if response.status_code == 200:
                    return True, response.json()["Id"]
                else:
                    return False, response.text
            else:
                return False, "Unknown error"
        except Exception as e:
            return False, str(e)

    def get_uid_from_username(self, username: str) -> Optional[str]:
        headers = {"accept": "application/json"}

        params = {
            "IsHidden": "false",
            "IsDisabled": "false",
            "Limit": "1",
            "NameStartsWithOrGreater": username,
            "api_key": self.api_token,
        }

        response = requests.get(
            url=self.base_url + "/Users/Query", params=params, headers=headers
        )

        response_json = response.json()

        name = response_json["Items"][0]["Name"]
        # 判断用户名是否一致
        if name != username:
            return None

        return response_json["Items"][0]["Id"]

    def get_user_total_play_time(self) -> dict[str, str]:
        headers = {"accept": "application/json", "Content-Type": "application/json"}

        params = {"api_key": self.api_token}
        data = {
            "CustomQueryString": "SELECT UserId, SUM(PlayDuration) FROM PlaybackActivity GROUP BY UserId",
            "ReplaceUserId": False,
        }

        response = requests.post(
            url=self.base_url + "/user_usage_stats/submit_custom_query",
            params=params,
            headers=headers,
            data=json.dumps(data),
        )

        response_json = response.json()

        user_stats = {}

        for user in response_json.get("results", {}):
            user_id, play_duration = user
            user_stats.update({user_id: play_duration})

        return user_stats
