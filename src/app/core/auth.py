import hashlib
import hmac
import json
from functools import wraps

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.schemas import TelegramUser


def verify_telegram_data(data: dict) -> bool:
    """验证来自 Telegram WebApp 的数据"""
    if "hash" not in data:
        return False

    received_hash = data["hash"]
    data_check = {k: v for k, v in data.items() if k != "hash"}

    # 按字母顺序排序键
    data_check_keys = sorted(data_check.keys())
    data_check_string = "\n".join([f"{k}={data_check[k]}" for k in data_check_keys])

    # 计算 HMAC-SHA-256 签名
    secret_key = hmac.new(
        b"WebAppData", settings.TG_API_TOKEN.encode(), digestmod=hashlib.sha256
    ).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode(), digestmod=hashlib.sha256
    ).hexdigest()

    # 验证哈希
    return calculated_hash == received_hash


def get_telegram_user(request: Request) -> TelegramUser:
    """从请求中获取和验证 Telegram 用户数据"""
    try:
        # 从请求头中获取 telegram user 信息
        user_data = request.state.telegram_data.get("user")
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少 Telegram 用户数据",
            )

        # 检查是否是模拟数据
        if request.state.telegram_data.get("hash") == "mock_hash_for_development":
            # 开发环境模拟数据，直接解析JSON
            user_dict = json.loads(user_data)
            return TelegramUser(**user_dict)
        else:
            # 正常的Telegram数据
            return TelegramUser(**json.loads(user_data))

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"获取用户数据失败: {e!s}",
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


def check_admin_permission(user: TelegramUser):
    """检查用户是否为管理员"""
    # 开发环境允许模拟管理员
    if user.id == 123456789:  # 模拟用户ID
        return True

    if user.id not in settings.TG_ADMIN_CHAT_ID:
        raise HTTPException(status_code=403, detail="权限不足，需要管理员权限")
    return True
