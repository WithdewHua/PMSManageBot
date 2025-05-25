#! /usr/bin/env python3

import json
import pickle
from time import time
from typing import Any, Optional, Union

import filelock
import requests
from app.config import settings
from app.log import logger


class Emby:
    cache = settings.DATA_PATH / "emby_user_info.cache"
    cache_lock = filelock.FileLock(str(cache) + ".lock")

    def __init__(
        self,
        base_url: str = settings.EMBY_BASE_URL,
        api_token: str = settings.EMBY_API_TOKEN,
    ) -> None:
        self.base_url = base_url
        self.api_token = api_token

    def add_user(
        self, username: str, user_template: str = settings.EMBY_USER_TEMPLATE
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
        return self.get_user_info_from_username(username).get("id")

    def get_user_info_from_username(self, username: str, from_emby=True):
        cache = {}
        with self.cache_lock:
            if self.cache.exists():
                with open(self.cache, "rb") as f:
                    cache = pickle.load(f)
            if username in cache:
                return cache[username]

            if not from_emby:
                # 如果不从 Emby 获取，则直接返回空字典
                return {}

            headers = {"accept": "application/json"}

            params = {
                "IsHidden": "true",
                "IsDisabled": "false",
                "Limit": "1",
                "NameStartsWithOrGreater": username,
                "api_key": self.api_token,
            }

            retry = 3
            name = None
            while retry > 0:
                try:
                    response = requests.get(
                        url=self.base_url + "/Users/Query",
                        params=params,
                        headers=headers,
                    )

                    response_json = response.json()
                    logger.debug(f"{response_json=}")

                    if response.status_code == 200 and response_json.get("Items"):
                        name = response_json["Items"][0]["Name"]
                        break
                except Exception as e:
                    logger.error(f"Error fetching user ID for {username}: {e}")
                    retry -= 1

            # 判断用户名是否一致
            if name != username:
                return {}

            user_id = response_json["Items"][0]["Id"]
            primary_image_tag = response_json["Items"][0].get("PrimaryImageTag", "")
            user_avatar = (
                self.base_url
                + "/Users/"
                + user_id
                + f"/Images/Primary?tag={primary_image_tag}&maxWidth=160&quality=90"
                if primary_image_tag
                else ""
            )
            user_info = {
                "id": user_id,
                "name": name,
                "avatar": user_avatar,
                "date_created": response_json["Items"][0]["DateCreated"],
                "added_time": time(),
            }
            cache[username] = user_info
            with open(self.cache, "wb") as f:
                pickle.dump(cache, f)

            return user_info

    def get_user_avatar_by_username(self, username: str, from_emby=True) -> str:
        """获取用户头像 URL"""
        user_info = self.get_user_info_from_username(username, from_emby)
        return user_info.get("avatar", "")

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

    def add_user_library(self, user_id, library=settings.NSFW_LIBS):
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
            # 如果已经有该资料库的权限，则跳过
            if guid in enabled_folders:
                continue
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

    def remove_user_library(self, user_id, library=settings.NSFW_LIBS):
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
            # 如果没有该资料库的权限，则跳过
            if guid not in enabled_folders:
                continue
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

    def __get_url(self, url) -> list:
        headers = {
            "accept": "application/json",
            "X-Emby-Token": self.api_token,
        }
        try:
            res = requests.get(url, headers=headers)
            res.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to get {url}: {e}")
            return []
        else:
            return res.json().get("Items", [])

    def get_users(self) -> list:
        url = f"{self.base_url}/Users/Query"
        return self.__get_url(url)

    def get_devices(self) -> list:
        url = f"{self.base_url}/Devices"
        return self.__get_url(url)

    def get_devices_per_user(self) -> list:
        users = self.get_users()
        devices = self.get_devices()
        user_data = []
        for user in users:
            per_user_devices = set()
            per_user_ip = set()
            per_user_apps = set()
            user_id = user.get("Id")
            user_name = user.get("Name")
            for device in devices:
                if device.get("LastUserId") != user_id:
                    continue
                device_name = device.get("Name")
                app_name = device.get("AppName")
                ip_addr = device.get("IpAddress")
                per_user_devices.add(device_name)
                per_user_ip.add(ip_addr)
                per_user_apps.add(app_name)
            user_data.append(
                {
                    "user_id": user_id,
                    "user_name": user_name,
                    "devices": per_user_devices,
                    "ip": per_user_ip,
                    "clients": per_user_apps,
                }
            )
        return user_data

    def update_all_users_library(self, library: Union[str, list]) -> None:
        if isinstance(library, str):
            library = [library]
        users = self.get_users()
        for user in users:
            user_id = user.get("Id")
            user_name = user.get("Name")
            if user_name.lower() in ["ggbond", "huahua"]:
                continue
            self.add_user_library(user_id, library)


def emby_is_premium_line(line: str):
    """检查是否为高级线路"""
    is_premium_line = False
    for _line in settings.EMBY_PREMIUM_STREAM_BACKEND:
        if _line in line:
            is_premium_line = True
            break
    return is_premium_line
