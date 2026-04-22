import redis
from app.config import settings


class Redis:
    def __init__(
        self,
        db: int = 0,
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout: int = 5,
        socket_timeout: int = 30,
        retry_on_timeout: bool = True,
        health_check_interval: int = 30,
    ):
        self._pool = redis.ConnectionPool(
            db=db,
            host=host,
            port=port,
            password=password,
            decode_responses=decode_responses,
            socket_connect_timeout=socket_connect_timeout,
            socket_timeout=socket_timeout,
            retry_on_timeout=retry_on_timeout,
            health_check_interval=health_check_interval,
        )
        self.client = redis.Redis(connection_pool=self._pool)

    def get_connection(self):
        return self.client

    def get_pool(self):
        return self._pool
