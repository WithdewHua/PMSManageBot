import redis
from app.config import settings


class Redis:
    def __init__(
        self,
        db: int = 0,
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=True,
    ):
        self._pool = redis.ConnectionPool(
            host=host, port=port, decode_responses=decode_responses
        )
        self.client = redis.Redis(db=db, connection_pool=self._pool)

    def get_connection(self):
        return self.client

    def get_pool(self):
        return self._pool
