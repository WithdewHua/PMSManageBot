from functools import wraps

from app.log import logger
from app.webapp.auth import verify_telegram_data
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware

security = HTTPBearer()


class TelegramAuthMiddleware(BaseHTTPMiddleware):
    """Telegram WebApp 认证中间件"""

    async def dispatch(self, request: Request, call_next):
        # 获取Telegram initData
        init_data = request.headers.get("X-Telegram-Init-Data")
        logger.debug(f"{init_data=}")

        if not init_data:
            # 如果请求不包含 initData，可能是公开API或静态资源请求，正常放行
            return await call_next(request)

        # 解析并验证 initData
        try:
            # 解析 url 编码的 query string 格式的 initData
            import urllib.parse

            data_dict = dict(urllib.parse.parse_qsl(init_data))

            # 在开发环境中，允许模拟认证数据
            is_mock_data = data_dict.get("hash") == "mock_hash_for_development"

            if is_mock_data:
                logger.info("使用开发环境模拟认证数据")
                # 创建模拟的用户数据
                request.state.telegram_data = data_dict
            else:
                # 验证数据
                if not verify_telegram_data(data_dict):
                    logger.warning(f"无效的 Telegram initData: {init_data[:100]}...")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="无效的 Telegram 认证数据",
                    )

                # 将验证过的用户数据添加到请求状态
                request.state.telegram_data = data_dict

            # 继续处理请求
            return await call_next(request)
        except Exception as e:
            logger.error(f"处理 Telegram initData 时出错: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无法处理 Telegram 认证数据",
            )


def require_telegram_auth(func):
    """要求 Telegram 认证的装饰器，可用于保护 API 端点"""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 从参数中提取request对象
        request = None
        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break

        if request is None:
            # 如果在args中没找到，尝试从kwargs中查找
            request = kwargs.get("request")

        if request is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="无法获取请求对象"
            )

        if not hasattr(request.state, "telegram_data"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="需要 Telegram 认证"
            )
        return await func(*args, **kwargs)

    return wrapper
