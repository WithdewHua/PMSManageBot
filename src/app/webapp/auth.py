import hashlib
import hmac
import json

from app.config import settings
from app.webapp.schemas import TelegramUser
from fastapi import HTTPException, Request, status


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
            detail=f"获取用户数据失败: {str(e)}",
        )
