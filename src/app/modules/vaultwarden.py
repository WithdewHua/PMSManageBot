#!/usr/bin/env python3

import requests
from app.config import settings
from app.log import logger


class Vaultwarden:
    """Vaultwarden 管理类"""

    def __init__(
        self,
        base_url: str = settings.VAULTWARDEN_BASE_URL,
        admin_token: str = settings.VAULTWARDEN_ADMIN_TOKEN,
    ):
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.session = requests.Session()
        self._authenticated = False

    def _authenticate(self) -> bool:
        """
        通过 admin token 获取认证 cookie

        Returns:
            bool: 认证是否成功
        """
        try:
            url = f"{self.base_url}/admin"

            # 使用 x-www-form-urlencoded 格式发送 token
            data = {"token": self.admin_token}
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
            }

            logger.debug("正在进行 Vaultwarden 管理员认证...")
            response = self.session.post(url, data=data, headers=headers, timeout=10)

            if response.status_code == 200:
                # 从 cookie 中获取认证信息
                cookies = self.session.cookies.get_dict()

                # 检查是否有必要的 cookie
                if cookies:
                    logger.info("Vaultwarden 管理员认证成功")
                    self._authenticated = True
                    return True
                else:
                    logger.error("认证响应中未找到 cookie")
                    return False
            else:
                logger.error(
                    f"Vaultwarden 管理员认证失败: {response.status_code} - {response.text}"
                )
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Vaultwarden 认证时发生网络错误: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Vaultwarden 认证时发生未知错误: {str(e)}")
            return False

    def invite_user(self, email: str) -> bool:
        """
        发送用户邀请

        Args:
            email: 用户邮箱地址

        Returns:
            bool: 邀请是否成功
        """
        try:
            # 如果未认证，先进行认证
            if not self._authenticated:
                if not self._authenticate():
                    logger.error("无法认证 Vaultwarden 管理员")
                    return False

            url = f"{self.base_url}/admin/invite"

            # 使用 JSON 格式发送邮箱
            payload = {"email": email}
            headers = {
                "Content-Type": "application/json",
            }

            logger.info(f"正在向 {email} 发送 Vaultwarden 邀请...")
            response = self.session.post(url, json=payload, headers=headers, timeout=10)

            if response.status_code == 200:
                logger.info(f"成功向 {email} 发送 Vaultwarden 邀请")
                return True
            else:
                logger.error(
                    f"发送 Vaultwarden 邀请失败: {response.status_code} - {response.text}"
                )
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"发送 Vaultwarden 邀请时发生网络错误: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"发送 Vaultwarden 邀请时发生未知错误: {str(e)}")
            return False
