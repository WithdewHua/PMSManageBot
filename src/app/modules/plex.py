#!/usr/bin/env python3

import logging
import pickle
from typing import Optional, Union

import filelock
import requests
from app.config import settings
from app.log import logger
from plexapi.myplex import Section
from plexapi.server import PlexServer


class Plex:
    """class Plex"""

    cache = settings.DATA_PATH / "plex_user_info.cache"
    cache_lock = filelock.FileLock(str(cache) + ".lock")

    def __init__(
        self,
        base_url: str = settings.PLEX_BASE_URL,
        token: str = settings.PLEX_API_TOKEN,
    ):
        self.plex_server = PlexServer(baseurl=base_url, token=token)
        self.my_plex_account = self.plex_server.myPlexAccount()
        self.plex_server_name = self.plex_server.friendlyName
        self.users = []

    def get_libraries(self) -> list:
        return [section.title for section in self.plex_server.library.sections()]

    def get_users(self):
        if self.users:
            return self.users

        # 获取所有用户并过滤掉没有媒体库权限的用户
        all_users = [user for user in self.my_plex_account.users()]

        # 过滤出有媒体库权限的用户
        users_with_access = []
        for user in all_users:
            try:
                # 检查用户是否有访问当前服务器的权限
                user_server = user.server(self.plex_server_name)
                if (
                    user_server
                    and hasattr(user_server, "numLibraries")
                    and user_server.numLibraries > 0
                ):
                    users_with_access.append(user)
            except Exception as e:
                # 如果用户没有访问此服务器的权限,会抛出异常,跳过该用户
                logger.info(
                    f"用户 {user.username if hasattr(user, 'username') else user.email} 没有访问服务器的权限: {str(e)}"
                )
                continue

        self.users = users_with_access
        # 管理员账户始终添加
        self.users.append(self.my_plex_account)
        return self.users

    @property
    def users_by_email(self):
        users_by_email = {}
        for user in self.get_users():
            users_by_email[user.email] = (user.id, user)
        return users_by_email

    @property
    def users_by_id(self):
        users_by_id = {}
        for user in self.get_users():
            users_by_id[user.id] = (user.username, user)
        return users_by_id

    @property
    def users_info(self):
        users_info = {}
        for user in self.get_users():
            users_info[user.username] = user
        return users_info

    def get_user_id_by_email(self, email: str) -> int:
        """get user's id by email"""
        _user = self.users_by_email.get(email, None)
        if not _user:
            return 0
        return _user[0]

    def get_username_by_user_id(self, user_id):
        _user = self.users_by_id.get(user_id, None)
        if not _user:
            return ""
        return _user[0]

    def get_user_id_by_username(self, username: str) -> int:
        """
        通过用户名获取用户 ID

        Args:
            username: Plex 用户名

        Returns:
            int: 用户 ID，如果未找到则返回 0
        """
        for user in self.get_users():
            if hasattr(user, "username") and user.username == username:
                return user.id
            elif hasattr(user, "title") and user.title == username:
                return user.id
        return 0

    @classmethod
    def get_user_avatar_by_username(cls, username: str) -> str:
        """get user's avatar by username"""
        if not cls.cache.exists():
            plex = cls()
            user_avatars = plex.update_all_user_avatars()
        else:
            with cls.cache_lock:
                with open(cls.cache, "rb") as f:
                    user_avatars = pickle.load(f)
        return user_avatars.get(username, "")

    def update_all_user_avatars(self):
        user_avatars = {}
        for username, user in self.users_info.items():
            user_avatars[username] = user.thumb
        with self.cache_lock:
            with open(self.cache, "wb") as f:
                pickle.dump(user_avatars, f)
        return user_avatars

    def get_user_shared_libs_by_id(self, user_id) -> list:
        """get shared libraries with specified user by id"""
        if self.get_username_by_user_id(user_id) == settings.PLEX_ADMIN_USER:
            return self.get_libraries()
        data = (
            self.my_plex_account.user(user_id)
            .server(self.plex_server_name)
            ._server.query(
                self.my_plex_account.FRIENDSERVERS.format(
                    machineId=self.plex_server.machineIdentifier,
                    serverId=self.my_plex_account.user(user_id)
                    .server(self.plex_server_name)
                    .id,
                )
            )
        )
        return [
            section.title
            for section in self.plex_server.findItems(
                data, Section, rtag="SharedServer", **{"shared": 1}
            )
        ]

    def verify_all_libraries(self, user_id) -> bool:
        """Verify if specified user has permission with all libraries"""
        if self.get_username_by_user_id(user_id) == settings.PLEX_ADMIN_EMAIL:
            return True
        return (
            True
            if self.my_plex_account.user(user_id)
            .server(self.plex_server_name)
            .numLibraries
            == 6
            else False
        )

    def update_user_shared_libs(self, user_id, libs: list):
        """update shared libraries with specified user by id"""
        logger.info(f"Updating shared libraries for user {user_id}: {libs}")
        self.my_plex_account.updateFriend(
            self.my_plex_account.user(user_id), self.plex_server, sections=libs
        )

    def invite_friend(self, user, libs=None):
        try:
            if libs is None:
                libs = list(
                    set(self.get_libraries()).difference(set(settings.NSFW_LIBS))
                )
            self.my_plex_account.inviteFriend(user, self.plex_server, sections=libs)
        except Exception as e:
            logging.error(e)
            return False
        else:
            return True

    def add_shared_libs_for_all_users(self, add_sections: Union[str, list]):
        """更新所有用户的资料库权限"""

        if isinstance(add_sections, str):
            add_sections = [add_sections]

        if not self.users_by_email:
            self.get_users()

        for email, user_info in self.users_by_email.items():
            if (not email) or email == settings.PLEX_ADMIN_EMAIL:
                continue
            else:
                try:
                    cur_libs = self.get_user_shared_libs_by_id(user_info[0])
                    cur_libs.extend(add_sections)
                    new_libs = list(set(cur_libs))
                    self.update_user_shared_libs(user_info[0], libs=new_libs)
                except Exception:
                    logging.error(
                        f"Failed to update libraries({', '.join(new_libs)}) for {user_info[1].username}"
                    )
                    continue

    def add_shared_libs_for_user(self, email: str, add_sections: Union[str, list]):
        """更新指定用户的资料库权限"""

        if isinstance(add_sections, str):
            add_sections = [add_sections]

        user_info = self.users_by_email.get(email)
        if not user_info:
            logger.error(f"无法找到 Plex 用户 {email}")
            return

        try:
            cur_libs = self.get_user_shared_libs_by_id(user_info[0])
            cur_libs.extend(add_sections)
            new_libs = list(set(cur_libs))
            logger.info(
                f"为 Plex 用户 {user_info[1].username} 更新资料库权限: {', '.join(new_libs)}"
            )
            self.update_user_shared_libs(user_info[0], libs=new_libs)
        except Exception:
            logger.error(
                f"无法为 Plex 用户 {user_info[1].username} 更新资料库权限({', '.join(new_libs)})"
            )

    def _authenticate_user_by_username(
        self, username: str, password: str
    ) -> tuple[bool, Optional[int]]:
        """
        验证 Plex 用户名和密码
        返回 (是否验证成功, 用户ID) 的元组
        """
        try:
            # 导入MyPlexAccount用于认证
            from plexapi.myplex import MyPlexAccount

            # 尝试用提供的用户名和密码创建MyPlexAccount
            try:
                # 先尝试用用户名作为邮箱
                if "@" in username:
                    MyPlexAccount(username=username, password=password)
                    user_email = username
                else:
                    # 如果不是邮箱格式，尝试根据用户名找到对应的邮箱
                    user_email = None
                    for user in self.get_users():
                        if hasattr(user, "username") and user.username == username:
                            user_email = user.email
                            break

                    if not user_email:
                        logger.warning(f"无法找到Plex用户名 {username} 对应的邮箱")
                        return False, None

                    MyPlexAccount(username=user_email, password=password)

                # 验证用户是否在当前Plex服务器的用户列表中
                user_id = self.get_user_id_by_email(user_email)
                if user_id == 0:
                    logger.warning(f"Plex用户 {username} 不在当前服务器的用户列表中")
                    return False, None

                logger.info(f"Plex用户 {username} 认证成功")
                return True, user_id

            except Exception as auth_error:
                logger.warning(f"Plex用户 {username} 认证失败: {str(auth_error)}")
                return False, None

        except Exception as e:
            logger.error(f"Plex用户 {username} 认证时发生错误: {str(e)}")
            return False, None

    def _authenticate_user_by_token(self, token: str) -> tuple[bool, Optional[int]]:
        """
        使用 API Token 验证 Plex 用户
        返回 (是否验证成功, 用户ID) 的元组
        """
        headers = {
            "X-Plex-Token": token,
            "Accept": "application/json",
        }
        try:
            response = requests.get(
                f"{settings.PLEX_BASE_URL.strip('/')}/Authenticate/ValidateToken?X-Plex-Token={token}",
                headers=headers,
            )
            response.raise_for_status()  # 确保请求成功
            if response.status_code == 200:
                data = response.json()
                username = data.get("username")
                userinfo = self.users_info.get(username)
                if userinfo:
                    user_id = userinfo.id
                    logger.info(f"Plex 用户 {username} 通过 Token 认证成功")
                    return True, user_id
                else:
                    logger.warning(f"Plex 用户 {username} 不在当前服务器的用户列表中")
                    return False, None
        except Exception as e:
            logger.error(f"使用 Token 验证 Plex 用户时发生错误: {str(e)}")
            return False, None

    def authenticate_user(
        self, username: str = None, password: str = None, token: str = None
    ) -> tuple[bool, Optional[int]]:
        """
        验证 Plex 用户
        如果提供了用户名和密码，则使用它们进行验证
        如果提供了 Token，则使用 Token 进行验证
        返回 (是否验证成功, 用户ID) 的元组
        """
        if token:
            return self._authenticate_user_by_token(token)
        elif username and password:
            return self._authenticate_user_by_username(username, password)
        else:
            logger.error("必须提供用户名和密码或 API Token 进行验证")
            return False, None

    def get_user_last_viewed_at(self, user_id: int = None, username: str = None) -> int:
        """
        获取用户最后观看时间

        Args:
            user_id: Plex 用户 ID
            username: Plex 用户名 (如果未提供 user_id)

        Returns:
            int: Unix 时间戳，表示最后观看时间；如果没有观看记录则返回 0
        """
        try:
            # 如果提供了用户名，先获取用户ID
            if username and not user_id:
                user_id = self.get_user_id_by_username(username)

            if not user_id:
                logger.warning(f"无法找到用户: {username or user_id}")
                return 0

            # 获取用户的观看历史
            # 管理员账户和普通用户需要不同的处理方式
            if user_id == self.my_plex_account.id:
                # 对于管理员账户，不传入 accountID 参数
                history = self.plex_server.history(maxresults=1, mindate=None)
            else:
                # 对于普通用户，使用 accountID 参数
                history = self.plex_server.history(
                    maxresults=1, accountID=user_id, mindate=None
                )

            if history:
                # 获取最近一次观看记录的时间
                last_item = history[0]
                if hasattr(last_item, "viewedAt") and last_item.viewedAt:
                    # viewedAt 是 datetime 对象，需要转换为 Unix 时间戳
                    return int(last_item.viewedAt.timestamp())

            logger.info(f"用户 {self.get_username_by_user_id(user_id)} 没有观看记录")
            return 0

        except Exception as e:
            logger.error(f"获取用户最后观看时间时发生错误: {str(e)}")
            return 0

    def get_all_users_last_viewed_at(self) -> dict[int, int]:
        """
        批量获取所有用户的最后观看时间

        Returns:
            dict[int, int]: 字典，键为用户ID，值为最后观看时间的 Unix 时间戳
        """
        result = {}

        try:
            for user in self.get_users():
                user_id = user.id
                last_viewed = self.get_user_last_viewed_at(user_id=user_id)
                result[user_id] = last_viewed

            logger.info(f"成功获取 {len(result)} 个用户的最后观看时间")
            return result

        except Exception as e:
            logger.error(f"批量获取用户最后观看时间时发生错误: {str(e)}")
            return result
