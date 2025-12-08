#! /usr/bin/env python3

import json
import pickle
from datetime import datetime, timedelta
from time import time
from typing import Any, Optional, Union

import aiohttp
import filelock
import requests
from app.config import settings
from app.databases.cache import emby_api_key_cache
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
        self,
        username: str,
        password: str,
        user_template: str = settings.EMBY_USER_TEMPLATE,
    ) -> tuple[bool, str]:
        header = {"accept": "application/json", "Content-Type": "application/json"}

        data = {
            "Name": username,
            "CopyFromUserId": self.get_uid_from_username(user_template),
            "UserCopyOptions": ["UserPolicy"],
        }
        logger.info(
            f"Adding Emby user {username} with data: {data}, coping from {user_template}"
        )

        try:
            response = requests.post(
                url=self.base_url + "/Users/New" + f"?api_key={self.api_token}",
                data=json.dumps(data),
                headers=header,
            )

            if response:
                if response.status_code == 200:
                    emby_id = response.json()["Id"]
                    # 修改密码
                    if self.change_user_password(emby_id, new_password=password):
                        return True, response.json()["Id"]
                    else:
                        return False, "Failed to change user password"
                else:
                    return False, response.text
            else:
                return False, "Unknown error"
        except Exception as e:
            return False, str(e)

    def change_user_password(self, emby_id, new_password: str):
        """修改用户密码"""
        header = {"accept": "application/json", "Content-Type": "application/json"}

        data = {"Id": emby_id, "NewPw": new_password.strip(), "ResetPassword": False}
        try:
            response = requests.post(
                url=self.base_url
                + f"/Users/{emby_id}/Password"
                + f"?api_key={self.api_token}",
                data=json.dumps(data),
                headers=header,
            )
            if response.status_code in [200, 204]:
                return True
            else:
                logger.error(
                    f"Error changing password for {emby_id}: {response.status_code}/{response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"Error changing password for {emby_id}: {e}")
            return False

    def get_uid_from_username(self, username: str) -> Optional[str]:
        return self.get_user_info_from_username(username).get("id")

    def get_username_from_uid(self, user_id: str) -> Optional[str]:
        return self.get_user_info_from_uid(user_id).get("name")

    def get_user_info_from_uid(self, user_id: str, from_emby=True) -> dict:
        cache = {}
        user_info = {}
        with self.cache_lock:
            if self.cache.exists():
                with open(self.cache, "rb") as f:
                    cache = pickle.load(f)
            for _, info in cache.items():
                if info.get("id") == user_id:
                    user_info = info
                    # 如果缓存中的用户信息未过期，则直接返回
                    if time() - user_info.get("added_time", 0) < 7 * 24 * 3600:
                        logger.debug(f"Cache hit for {user_id}: {user_info}")
                        return user_info
            if not from_emby:
                # 如果不从 Emby 获取，则直接返回过期信息或者空字典
                return user_info
            headers = {"accept": "application/json"}

            retry = 3
            name = None
            while retry > 0:
                try:
                    reponse = requests.get(
                        url=self.base_url
                        + f"/Users/{user_id}?api_key={self.api_token}",
                        headers=headers,
                    )
                    reponse.raise_for_status()
                    response_json = reponse.json()
                    logger.debug(f"{response_json=}")
                except Exception as e:
                    logger.error(f"Error fetching user info for {user_id}: {e}")
                    retry -= 1
                else:
                    name = response_json["Name"]
                    primary_image_tag = response_json.get("PrimaryImageTag", "")
                    date_created = response_json.get("DateCreated", "")

            if name is None:
                return {}
            user_avatar = self.__user_avatar(user_id, primary_image_tag)
            user_info = {
                "id": user_id,
                "name": name,
                "avatar": user_avatar,
                "date_created": date_created,
                "added_time": time(),
            }
            cache[name] = user_info
            with open(self.cache, "wb") as f:
                pickle.dump(cache, f)
            logger.info(f"Updated user info for {user_id}: {user_info}")
            return user_info

    def get_user_info_from_username(
        self, username: str, from_emby=True, is_hidden=settings.EMBY_USER_IS_HIDDEN
    ):
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
                "IsHidden": str(is_hidden).lower(),
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

                    if response.status_code == 200:
                        if (
                            response_json.get("Items") is None
                            or len(response_json["Items"]) == 0
                        ):
                            # 用户不存在
                            return {}
                        name = response_json["Items"][0]["Name"]
                        break
                    response.raise_for_status()
                except Exception as e:
                    logger.error(f"Error fetching user ID for {username}: {e}")
                    retry -= 1

            # 判断用户名是否一致
            if name != username:
                return {}

            user_id = response_json["Items"][0]["Id"]
            primary_image_tag = response_json["Items"][0].get("PrimaryImageTag", "")
            user_avatar = self.__user_avatar(user_id, primary_image_tag)
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

    def __user_avatar(self, uid: str, primary_image_tag: str) -> str:
        if not primary_image_tag:
            return ""
        return (
            settings.EMBY_ENTRY_URL
            + "/Users/"
            + uid
            + f"/Images/Primary?tag={primary_image_tag}&maxWidth=160&quality=90"
        )

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

    def add_user_library(
        self, user_id, library: Union[str, list[str]] = settings.NSFW_LIBS
    ):
        if isinstance(library, str):
            library = [library]

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
            if not lib:
                return False, f"Library {lib_name} not found"
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

    def get_emby_current_playing_user_num(self):
        url = self.base_url + f"/Sessions?IsPlaying=True&api_key={self.api_token}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            rslts = response.json()
        except Exception as e:
            logger.error(f"Error fetching Emby current playing user num: {e}")
            return 0
        num = 0
        for rslt in rslts:
            if not rslt["PlayState"]["IsPaused"]:
                num += 1

        return num

    def get_report(
        self,
        types=None,
        user_id=None,
        days=7,
        end_date=datetime.now(settings.TZ),
        limit=10,
    ):
        item_type = {
            "movie": "ItemName",
            "episode": "substr(ItemName,0, instr(ItemName, ' - '))",
        }
        if not types:
            types = "Movie"
        sub_date = end_date - timedelta(days=days)
        start_time = sub_date.strftime("%Y-%m-%d %H:%M:%S")
        end_time = end_date.strftime("%Y-%m-%d %H:%M:%S")
        if types.lower() != "user" and item_type.get(types.lower()):
            sql = "SELECT UserId, ItemId, ItemType, "
            sql += item_type.get(types.lower()) + " AS name, "
            sql += "COUNT(1) AS play_count, "
            sql += "SUM(PlayDuration - PauseDuration) AS total_duration "
            sql += "FROM PlaybackActivity "
            sql += f"WHERE ItemType = '{types.capitalize()}' "
            sql += f"AND DateCreated >= '{start_time}' AND DateCreated <= '{end_time}' "
            sql += "AND UserId not IN (select UserId from UserList) "
            if user_id:
                sql += f"AND UserId = '{user_id}' "
            sql += "GROUP BY name "
            sql += "ORDER BY total_duration DESC "
            sql += "LIMIT " + str(limit)
        elif types.lower() == "user":
            sql = "SELECT UserId, "
            sql += "SUM(PlayDuration - PauseDuration) AS total_duration "
            sql += "FROM PlaybackActivity "
            sql += (
                f"WHERE DateCreated >= '{start_time}' AND DateCreated <= '{end_time}' "
            )
            sql += "AND UserId not IN (select UserId from UserList) "
            if user_id:
                sql += f"AND UserId = '{user_id}' "
            sql += "GROUP BY UserId "
            sql += "ORDER BY total_duration DESC "
            sql += "LIMIT " + str(limit)
        else:
            return False, "Incorrect types"

        url = (
            self.base_url
            + f"/user_usage_stats/submit_custom_query?api_key={self.api_token}"
        )
        data = {"CustomQueryString": sql, "ReplaceUserId": False}
        try:
            resp = requests.post(url, data=data)
            resp.raise_for_status()
            resp = resp.json()
        except Exception as e:
            logger.error(f"Error fetching Emby report: {e}")
            return False, "请求失败"
        if not resp:
            return False, "请求失败"
        if not resp["results"]:
            return False, resp["message"]
        ranks = []
        if types.lower() != "user":
            for idx, stats in enumerate(resp["results"], start=1):
                ranks.append(f"{idx}. {stats[-3]}: {timedelta(seconds=int(stats[-1]))}")
        else:
            for idx, stats in enumerate(resp["results"], start=1):
                user_name = self.get_username_from_uid(stats[0])
                if not user_name:
                    user_name = stats[0]
                ranks.append(f"{idx}. {user_name}: {timedelta(seconds=int(stats[1]))}")
        return True, ranks

    def get_user_last_activity(self, user_id: str) -> Optional[int]:
        """
        获取用户最后活动时间（最后观看时间）
        从 PlaybackActivity 表中获取用户最后一次播放记录的时间

        Args:
            user_id: Emby用户ID

        Returns:
            Unix时间戳(秒)，如果没有记录则返回None
        """
        headers = {"accept": "application/json", "Content-Type": "application/json"}
        params = {"api_key": self.api_token}

        # 查询用户最后一次播放活动的时间
        sql = f"""
        SELECT MAX(DateCreated) as LastActivity
        FROM PlaybackActivity
        WHERE UserId = '{user_id}'
        """

        data = {
            "CustomQueryString": sql,
            "ReplaceUserId": False,
        }

        try:
            response = requests.post(
                url=self.base_url + "/user_usage_stats/submit_custom_query",
                params=params,
                headers=headers,
                data=json.dumps(data),
            )
            response.raise_for_status()
            response_json = response.json()

            if response_json.get("results") and len(response_json["results"]) > 0:
                last_activity_str = response_json["results"][0][0]
                if last_activity_str:
                    # 将ISO格式的时间转换为Unix时间戳
                    # Emby返回的时间格式可能是: "2024-12-08 10:30:00" 或 "2024-12-08 10:30:00.123456"
                    try:
                        # 先尝试移除小数部分(如果存在)
                        if "." in last_activity_str:
                            last_activity_str = last_activity_str.split(".")[0]
                        dt = datetime.strptime(last_activity_str, "%Y-%m-%d %H:%M:%S")
                        # 转换为UTC时间戳
                        timestamp = int(dt.timestamp())
                        logger.debug(
                            f"User {user_id} last activity: {last_activity_str} ({timestamp})"
                        )
                        return timestamp
                    except Exception as e:
                        logger.error(
                            f"Error parsing timestamp for user {user_id}: {last_activity_str}, {e}"
                        )
                        return None

            logger.debug(f"No activity found for user {user_id}")
            return None

        except Exception as e:
            logger.error(f"Error fetching last activity for user {user_id}: {e}")
            return None

    def get_all_users_last_activity(self) -> dict[str, Optional[int]]:
        """
        获取所有用户的最后活动时间

        Returns:
            字典 {user_id: timestamp}，timestamp为Unix时间戳(秒)，无记录则为None
        """
        headers = {"accept": "application/json", "Content-Type": "application/json"}
        params = {"api_key": self.api_token}

        # 查询所有用户的最后一次播放活动时间
        sql = """
        SELECT UserId, MAX(DateCreated) as LastActivity
        FROM PlaybackActivity
        GROUP BY UserId
        """

        data = {
            "CustomQueryString": sql,
            "ReplaceUserId": False,
        }

        try:
            response = requests.post(
                url=self.base_url + "/user_usage_stats/submit_custom_query",
                params=params,
                headers=headers,
                data=json.dumps(data),
            )
            response.raise_for_status()
            response_json = response.json()

            user_activities = {}

            if response_json.get("results"):
                for result in response_json["results"]:
                    user_id, last_activity_str = result
                    if last_activity_str:
                        try:
                            # 将ISO格式的时间转换为Unix时间戳
                            # 先尝试移除小数部分(如果存在)
                            if "." in last_activity_str:
                                last_activity_str = last_activity_str.split(".")[0]
                            dt = datetime.strptime(
                                last_activity_str, "%Y-%m-%d %H:%M:%S"
                            )
                            timestamp = int(dt.timestamp())
                            user_activities[user_id] = timestamp
                        except Exception:
                            logger.error(
                                f"Error parsing timestamp for user {user_id}: {last_activity_str}"
                            )
                            user_activities[user_id] = None
                    else:
                        user_activities[user_id] = None

            logger.info(f"Fetched last activity for {len(user_activities)} users")
            return user_activities

        except Exception as e:
            logger.error(f"Error fetching all users last activity: {e}")
            return {}
