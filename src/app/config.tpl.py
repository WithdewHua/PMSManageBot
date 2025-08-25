import os
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # debug
    DEBUG: bool = True
    # log
    LOG_LEVEL: str = "INFO"

    # data folder
    DATA_DIR: str = ""

    # plex
    PLEX_REGISTER: bool = False
    PLEX_BASE_URL: str = ""
    PLEX_API_TOKEN: str = ""
    PLEX_ADMIN_USER: str = ""
    PLEX_ADMIN_EMAIL: str = ""

    # Overseerr
    OVERSEERR_BASE_URL: str = ""
    OVERSEERR_API_TOKEN: str = ""

    # library
    NSFW_LIBS: list = ["NSFW", "NC17 Movies"]

    # credits
    UNLOCK_CREDITS: int = 100
    INVITATION_CREDITS: int = 288
    PREMIUM_DAILY_CREDITS: int = 15
    DONATION_MULTIPLIER: int = 5  # 捐赠积分倍数
    USER_TRAFFIC_LIMIT: int = (
        30 * 1024 * 1024 * 1024
    )  # 每日用户流量限额，单位为字节（30GB）
    PREMIUM_USER_TRAFFIC_LIMIT: int = (
        60 * 1024 * 1024 * 1024
    )  # 每日高级用户流量限额，单位为字节（60GB）
    CREDITS_COST_PER_10GB: int = 5  # 超出每日限额后，每 10GB 流量消耗的积分

    # 功能开放设置
    PREMIUM_UNLOCK_ENABLED: bool = False  # 是否开放 premium 解锁功能
    CREDITS_TRANSFER_ENABLED: bool = True  # 积分转移功能开关

    # TG
    TG_API_TOKEN: str = ""
    ADMIN_CHAT_ID: list = []
    TG_GROUP: str = ""
    TG_CHANNEL: str = ""  # 可选的通知频道链接，如果不设置将使用群组链接

    # WebApp
    ENABLE_WEBAPP: bool = True  # 是否启用 WebApp
    WEBAPP_URL: str = "https://yourdomain.com"  # WebApp 的公开 URL
    WEBAPP_PORT: int = 5000  # WebApp 服务器监听端口
    WEBAPP_HOST: str = "127.0.0.1"  # WebApp 服务器监听地址
    WEBAPP_STATIC_DIR: str = "../webapp-frontend/dist"  # WebApp 前端静态文件目录
    SESSION_SECRET_KEY: str = ""  # 用于会话加密的密钥

    # tautulli
    TAUTULLI_URL: str = ""
    TAUTULLI_APIKEY: str = ""
    TAUTULLI_PUBLIC_URL: str = "/"
    TAUTULLI_VERIFY_SSL: bool = False

    # emby
    EMBY_REGISTER: bool = True
    EMBY_BASE_URL: str = ""
    EMBY_API_TOKEN: str = ""
    EMBY_ADMIN_USER: str = ""
    EMBY_USER_TEMPLATE: str = ""

    # 后端线路
    STREAM_BACKEND: list[str] = []
    PREMIUM_STREAM_BACKEND: list[str] = []
    PREMIUM_FREE: bool = False

    # redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_LINE_TRAFFIC_STATS_HANDLE_SIZE: int = 1000  # Redis 流量统计单次处理条数

    # redeem code
    PRIVILEGED_CODES: list[str] = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.DATA_PATH.exists():
            self.DATA_PATH.mkdir(parents=True)
        # 启动时尝试从配置文件加载设置
        self.load_config_from_file()

    # 设置北京时间
    @property
    def TZ(self):
        return timezone(timedelta(hours=8))

    @property
    def DATA_PATH(self):
        if not self.DATA_DIR:
            return Path(__file__).parents[2] / "data"
        return Path(self.DATA_DIR)

    @property
    def TG_USER_INFO_CACHE_PATH(self):
        return self.DATA_PATH / "tg_user_info.cache"

    @property
    def TG_USER_PROFILE_CACHE_PATH(self):
        if self.WEBAPP_ENABLE and Path(self.WEBAPP_STATIC_DIR).exists():
            path = Path(self.WEBAPP_STATIC_DIR) / "pics"
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def ENV_FILE_PATH(self):
        """环境变量文件路径"""
        return self.DATA_PATH / ".env"

    def load_config_from_file(self):
        """从配置文件加载设置"""
        # 从 .env 文件加载
        if self.ENV_FILE_PATH.exists():
            self._load_from_env_file()

    def _load_from_env_file(self):
        """从 .env 文件加载环境变量"""
        try:
            with open(self.ENV_FILE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")

                        # 设置环境变量
                        os.environ[key] = value

                        # 如果是当前设置中存在的字段，直接更新
                        if hasattr(self, key):
                            # 处理不同类型的值
                            current_value = getattr(self, key)
                            if isinstance(current_value, bool):
                                setattr(
                                    self,
                                    key,
                                    value.lower() in ("true", "1", "yes", "on"),
                                )
                            elif isinstance(current_value, int):
                                setattr(self, key, int(value))
                            elif isinstance(current_value, list):
                                # 假设列表用逗号分隔
                                setattr(
                                    self,
                                    key,
                                    [
                                        item.strip()
                                        for item in value.split(",")
                                        if item.strip()
                                    ],
                                )
                            else:
                                setattr(self, key, value)
        except Exception as e:
            print(f"加载 .env 文件失败: {e}")

    def save_config_to_env_file(self, config_data: Dict[str, Any]):
        """保存配置到 .env 文件"""
        try:
            # 读取现有的 .env 文件内容
            existing_lines = []
            existing_keys = set()

            if self.ENV_FILE_PATH.exists():
                with open(self.ENV_FILE_PATH, "r", encoding="utf-8") as f:
                    for line in f:
                        line_stripped = line.strip()
                        if (
                            line_stripped
                            and not line_stripped.startswith("#")
                            and "=" in line_stripped
                        ):
                            key = line_stripped.split("=", 1)[0].strip()
                            existing_keys.add(key)
                        existing_lines.append(line.rstrip())

            # 更新或添加新的配置项
            for key, value in config_data.items():
                env_line = f"{key}={value}"

                if key in existing_keys:
                    # 更新现有项
                    for i, line in enumerate(existing_lines):
                        if line.strip().startswith(f"{key}="):
                            existing_lines[i] = env_line
                            break
                else:
                    # 添加新项
                    existing_lines.append(env_line)

            # 保存到文件
            with open(self.ENV_FILE_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(existing_lines))
                if existing_lines and not existing_lines[-1] == "":
                    f.write("\n")

            print(f"配置已保存到: {self.ENV_FILE_PATH}")
        except Exception as e:
            print(f"保存 .env 配置文件失败: {e}")

    def get_saveable_config(self) -> Dict[str, Any]:
        """
        获取可保存的配置项（排除敏感信息）
        可以根据需要自定义哪些配置项不应该被保存
        """
        # 定义不应该保存到文件的敏感配置项
        sensitive_keys = {
            "TG_API_TOKEN",
            "PLEX_API_TOKEN",
            "OVERSEERR_API_TOKEN",
            "EMBY_API_TOKEN",
            "TAUTULLI_APIKEY",
            "REDIS_PASSWORD",
            "WEBAPP_SESSION_SECRET_KEY",
        }

        config = {}
        for key in dir(self):
            if (
                not key.startswith("_")
                and key.isupper()
                and key not in sensitive_keys
                and not callable(getattr(self, key))
            ):
                value = getattr(self, key)
                # 只保存基本类型
                if isinstance(value, (str, int, bool, list)):
                    config[key] = value

        return config

    def save_current_config(self, include_sensitive: bool = False):
        """
        保存当前配置到 .env 文件

        Args:
            include_sensitive: 是否包含敏感信息（如 API 密钥等）
        """
        if include_sensitive:
            # 保存所有配置项
            config = {}
            for key in dir(self):
                if (
                    not key.startswith("_")
                    and key.isupper()
                    and not callable(getattr(self, key))
                ):
                    value = getattr(self, key)
                    if isinstance(value, (str, int, bool, list)):
                        config[key] = value
        else:
            # 只保存非敏感配置项
            config = self.get_saveable_config()

        self.save_config_to_env_file(config)

    class Config:
        case_sensitive = True
        # 支持从 .env 文件读取环境变量
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
