#!/user/bin/env python3

import logging

from plexapi.server import PlexServer
from plexapi.myplex import Section
from settings import PLEX_BASE_URL, PLEX_API_TOKEN, NSFW_LIBS


class Plex:
    """class Plex"""

    def __init__(self, base_url: str=PLEX_BASE_URL, token: str=PLEX_API_TOKEN):
        self.plex_server = PlexServer(baseurl=base_url, token=token)
        self.my_plex_account = self.plex_server.myPlexAccount()
        self.plex_server_name = self.plex_server.friendlyName
        self.get_users()

    def get_libraries(self) -> list:
        return [section.title for section in self.plex_server.library.sections()]

    def get_users(self):
        users = [user for user in self.my_plex_account.users()]
        users.append(self.my_plex_account)
        self.users_by_id = {}
        self.users_by_email = {}
        for user in users:
            self.users_by_id.update({user.id: (user.username, user)})
            self.users_by_email.update({user.email: (user.id, user)})

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

    def get_user_shared_libs_by_id(self, user_id) -> list:
        """get shared libraries with specified user by id"""
        if self.get_username_by_user_id(user_id) == "GGBond":
            return self.get_libraries()
        data = self.my_plex_account.user(user_id).server(self.plex_server_name)._server.query(self.my_plex_account.FRIENDSERVERS.format(machineId=self.plex_server.machineIdentifier, serverId=self.my_plex_account.user(user_id).server(self.plex_server_name).id))
        return [section.title for section in self.plex_server.findItems(data, Section, rtag="SharedServer", **{"shared": 1})]
        
    def verify_all_libraries(self, user_id) -> bool:
        """Verify if specified user has permission with all libraries"""
        if self.get_username_by_user_id(user_id) == "GGBond":
            return True
        return True  if self.my_plex_account.user(user_id).server(self.plex_server_name).numLibraries == 6 else False
        
    def update_user_shared_libs(self, user_id, libs: list):
        """update shared libraries with specified user by id"""
        self.my_plex_account.updateFriend(self.my_plex_account.user(user_id), self.plex_server, sections=libs)

    def invite_friend(self, user, libs=None):
        if libs is None:
            libs = list(set(self.get_libraries()).difference(set(NSFW_LIBS)))
        self.my_plex_account.inviteFriend(user, self.plex_server, sections=libs)

    def add_shared_libs_for_all_users(self, add_sections=[]):
        """更新所有用户的资料库权限"""

        for email, user_info in self.users_by_email.items():
            if (not email) or email == "i@10101.io":
                continue
            else:
                try:
                    cur_libs = self.get_user_shared_libs_by_id(user_info[0])
                    cur_libs.extend(add_sections)
                    new_libs = list(set(cur_libs))
                    self.update_user_shared_libs(user_info[0], libs=new_libs)
                except:
                    logging.error(f"Failed to update libraries({', '.join(new_libs)}) for {user_info[1].username}")
                    continue


