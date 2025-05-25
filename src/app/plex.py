#!/user/bin/env python3

import logging
from typing import Union

import filelock
from app.config import settings
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
        self.users_info = {}
        self.users_by_id = {}
        self.users_by_email = {}

    def get_libraries(self) -> list:
        return [section.title for section in self.plex_server.library.sections()]

    def get_users(self):
        self.users = [user for user in self.my_plex_account.users()]
        self.users.append(self.my_plex_account)
        for user in self.users:
            self.users_by_id.update({user.id: (user.username, user)})
            self.users_by_email.update({user.email: (user.id, user)})
            self.users_info.update({user.username: user})

    def get_user_id_by_email(self, email: str) -> int:
        """get user's id by email"""
        if not self.users_by_email:
            self.get_users()

        _user = self.users_by_email.get(email, None)
        if not _user:
            return 0
        return _user[0]

    def get_username_by_user_id(self, user_id):
        if not self.users_by_id:
            self.get_users()
        _user = self.users_by_id.get(user_id, None)
        if not _user:
            return ""
        return _user[0]

    def get_user_avatar_by_username(self, username: str) -> str:
        """get user's avatar by username"""
        if not self.users_info:
            self.get_users()
        user = self.users_info.get(username, None)
        if not user:
            return ""
        return user.thumb

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
