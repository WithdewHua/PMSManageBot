#! /usr/bin/env python3

import requests
import json

from typing import Optional, Any

from log import logger
from settings import (
    EMBY_BASE_URL,
    EMBY_API_TOKEN,
    EMBY_ADMIN_USER,
    EMBY_USER_TEMPLATE,
    NSFW_LIBS,
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

    def get_libraries(self) -> dict[str, dict[str, Any]]:
        headers = {"accept": "application/json"}
        params = {"api_key": self.api_token}

        response = requests.get(
            url=self.base_url + "/Library/SelectableMediaFolders",
            headers=headers,
            params=params,
        )

        libs = response.json()
        libraries = {}
        for lib in libs:
            name = lib.get("Name")
            guid = lib.get("Guid")
            subfolders = lib.get("SubFolders", [])
            subfolders_id = [folder.get("Id") for folder in subfolders]
            libraries.update({name: {"guid": guid, "subfolders_id": subfolders_id}})

        return libraries

    def add_user_library(self, user_id, library=NSFW_LIBS):
        headers = {"accept": "application/json", "Content-Type": "application/json"}
        params = {"api_key": self.api_token}

        # 先获取该用户的 policy
        response = requests.get(
            url=self.base_url + f"/Users/{user_id}", params=params, headers=headers
        )
        policy = response.json().get("Policy")

        libraries = self.get_libraries()

        for lib_name in library:
            lib = libraries.get(lib_name)
            guid = lib.get("guid")
            subfolders_id = lib.get("subfolders_id")
            enabled_folders = policy.get("EnabledFolders")
            excluded_subfolders = policy.get("ExcludedSubFolders")
            # 增加资料库权限
            enabled_folders.append(guid)
            for subfolder in subfolders_id:
                subfolder_id = f"{guid}_{subfolder}"
                if subfolder_id in excluded_subfolders:
                    excluded_subfolders.remove(subfolder_id)

        # 更新权限设置
        try:
            response = requests.post(
                url=self.base_url + f"/Users/{user_id}/Policy",
                data=json.dumps(policy),
                params=params,
                headers=headers,
            )
            if response:
                if response.status_code in [200, 204]:
                    return True, "ok"
                else:
                    return False, response.text
            else:
                return False, "Unknown error"
        except Exception as e:
            return False, str(e)

    def remove_user_library(self, user_id, library=NSFW_LIBS):
        headers = {"accept": "application/json", "Content-Type": "application/json"}
        params = {"api_key": self.api_token}

        # 先获取该用户的 policy
        response = requests.get(
            url=self.base_url + f"/Users/{user_id}", headers=headers, params=params
        )
        policy = response.json().get("Policy")

        libraries = self.get_libraries()

        for lib_name in library:
            lib = libraries.get(lib_name)
            guid = lib.get("guid")
            subfolders_id = lib.get("subfolders_id")
            enabled_folders = policy.get("EnabledFolders")
            excluded_subfolders = policy.get("ExcludedSubFolders")
            # 更新资料库权限
            enabled_folders.remove(guid)
            for subfolder in subfolders_id:
                subfolder_id = f"{guid}_{subfolder}"
                if subfolder_id not in excluded_subfolders:
                    excluded_subfolders.append(subfolder_id)

        # 更新权限设置
        try:
            response = requests.post(
                url=self.base_url + f"/Users/{user_id}/Policy",
                data=json.dumps(policy),
                params=params,
                headers=headers,
            )
            if response:
                if response.status_code in [200, 204]:
                    return True, "ok"
                else:
                    return False, response.text
            else:
                return False, "Unknown error"
        except Exception as e:
            return False, str(e)
