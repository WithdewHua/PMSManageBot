import threading

import aiohttp

from app.core.log import logger


# Global session manager to avoid SSL connection issues
class HTTPSessionManager:
    """Manages global HTTP session to avoid connection pool issues"""

    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        self._connector: aiohttp.TCPConnector | None = None

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session"""
        if self._session is None or self._session.closed:
            await self._create_session()
        return self._session

    async def _create_session(self):
        """Create new HTTP session with optimized settings"""
        # Close existing resources if any
        await self.close()

        self._connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=30,
            enable_cleanup_closed=True,
            keepalive_timeout=30,  # 使用 keepalive 而不是 force_close
            ssl=None,
        )

        timeout = aiohttp.ClientTimeout(total=10, connect=5)

        self._session = aiohttp.ClientSession(
            connector=self._connector,
            connector_owner=True,
            trust_env=True,
            timeout=timeout,
        )

    async def close(self):
        """Close session and connector safely"""
        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except Exception as e:
                logger.debug(f"Error closing session: {e}")

        if self._connector:
            try:
                await self._connector.close()
            except Exception as e:
                logger.debug(f"Error closing connector: {e}")

        self._session = None
        self._connector = None


# thread local session
_thread_local_session_manager = threading.local()


async def get_thread_safe_session() -> aiohttp.ClientSession:
    if not hasattr(_thread_local_session_manager, "session_manager"):
        _thread_local_session_manager.session_manager = HTTPSessionManager()
    return await _thread_local_session_manager.session_manager.get_session()


async def cleanup_http_resources():
    """Clean up HTTP resources on application shutdown"""
    if hasattr(_thread_local_session_manager, "session_manager"):
        await _thread_local_session_manager.session_manager.close()
