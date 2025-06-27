#! /usr/bin/env python3

import json
import pickle
from time import time
from typing import Any, Optional, Union

import aiohttp
import filelock
import requests
from app.cache import emby_api_key_cache
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
        user_info = {}
        with self.cache_lock:
            if self.cache.exists():
                with open(self.cache, "rb") as f:
                    cache = pickle.load(f)
            if username in cache:
                user_info = cache[username]
                # 如果缓存中的用户信息未过期，则直接返回
                if time() - user_info.get("added_time", 0) < 7 * 24 * 3600:
                    logger.debug(f"Cache hit for {username}: {user_info}")
                    return user_info

            if not from_emby:
                # 如果不从 Emby 获取，则直接返回过期信息或者空字典
                return user_info

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
            logger.info(f"Updated user info for {username}: {user_info}")

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

    def authenticate_user(
        self, username: str, password: str
    ) -> tuple[bool, Optional[str]]:
        """
        验证Emby用户的用户名和密码
        返回 (是否验证成功, 用户ID) 的元组
        """
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "X-Emby-Authorization": 'MediaBrowser Token="", UserId="", Client="PMSManageBot", Device="Linux", DeviceId="4729AEE7-110E-4B0F-9DC3-E7E461C6E5DA", Version="1.0.0.0"',
        }

        data = {"Username": username, "Pw": password}

        try:
            response = requests.post(
                url=self.base_url + "/Users/AuthenticateByName",
                headers=headers,
                json=data,
            )

            if response.status_code == 200:
                response_data = response.json()
                user_id = response_data.get("User", {}).get("Id")
                if user_id:
                    logger.info(f"Emby用户 {username} 认证成功")
                    return True, user_id
                else:
                    logger.warning(f"Emby用户 {username} 认证失败：无法获取用户ID")
                    return False, None
            else:
                logger.warning(
                    f"Emby用户 {username} 认证失败：{response.status_code} - {response.content.decode('utf-8')}"
                )
                return False, None

        except Exception as e:
            logger.error(f"Emby用户 {username} 认证时发生错误: {str(e)}")
            return False, None

    async def get_emby_username_from_api_key(self, api_key: str) -> Optional[str]:
        """
        请求 Emby API 获取用户名
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url.rstrip('/')}/Sessions?api_key={api_key}"
                ) as response:
                    response.raise_for_status()
                    if response.status == 200:
                        sessions = await response.json()
                        usernames = set()
                        for session in sessions:
                            if "UserName" in session:
                                usernames.add(session["UserName"].lower())
                        if len(usernames) == 1:
                            # 只有一个用户名才认为是有效的
                            username = str(usernames.pop()).lower()
                            logger.info(f"Got username from api_key: {username}")
                            emby_api_key_cache.put(api_key, username)
                            return username
                        else:
                            logger.info("Multi usernames found, maybe admin, skip")
                    else:
                        logger.error(
                            f"Failed to get username: {response.status}, {await response.text()}"
                        )
        except Exception as e:
            logger.error(f"Error fetching Emby username: {e}")
        return None
