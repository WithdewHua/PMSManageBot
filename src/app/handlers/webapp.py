from app.config import settings
from app.log import logger
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update, WebAppInfo
from telegram.ext import CommandHandler, ContextTypes


async def webapp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """启动 WebApp"""
    chat_id = update.effective_chat.id

    # 检查是否启用了 WebApp
    if not settings.WEBAPP_ENABLE:
        await context.bot.send_message(
            chat_id=chat_id, text="WebApp 功能当前未启用，请联系管理员启用此功能。"
        )
        logger.warning(f"用户 {chat_id} 请求 WebApp，但功能已被禁用")
        return

    # 创建带有 WebApp 按钮的键盘
    webapp_button = KeyboardButton(
        text="打开 FunMedia 助手", web_app=WebAppInfo(url=f"{settings.WEBAPP_URL}")
    )

    reply_markup = ReplyKeyboardMarkup(
        [[webapp_button]], resize_keyboard=True, one_time_keyboard=False
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text="点击下方按钮打开 FunMedia 助手 WebApp，查看您的个人信息和排行榜。",
        reply_markup=reply_markup,
    )


webapp_handler = CommandHandler("webapp", webapp)

__all__ = ["webapp_handler"]
