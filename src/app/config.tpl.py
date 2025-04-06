from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # debug
    DEBUG: bool = False
    # log
    LOG_LEVEL: str = "DEBUG"

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

    # TG
    TG_API_TOKEN: str = ""
    ADMIN_CHAT_ID: list = []
    TG_GROUP: str = ""

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

    # redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""

    def __init__(self, **kwargs):
        super().__init__(self, **kwargs)
        if not self.DATA_PATH.exists():
            self.DATA_PATH.mkdir(parents=True)

    @property
    def DATA_PATH(self):
        if not self.DATA_DIR:
            return Path(__file__).parents[2] / "data"
        return Path(self.DATA_DIR)

    class config:
        case_sensitive = True


settings = Settings()
