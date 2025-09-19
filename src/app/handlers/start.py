import textwrap

from app.config import settings
from app.utils.utils import send_message
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    body_text = """
    欢迎来到 FunMedia 小助手

    公共命令：
    /info - 查看个人信息
    /exchange - 生成邀请码，消耗 {} 积分
    /credits\_rank - 查看积分榜
    /donation\_rank - 查看捐赠榜
    /play\_duration\_rank - 查看观看时长榜
    /device\_rank - 查看设备榜
    /register\_status - 查看 Plex/Emby 是否可注册

    Overseerr 命令:
    /create\_overseerr - 创建 Overseerr 账户，格式为 `/create_overseerr 邮箱 密码` (注意空格)
 
    管理员命令：
    /set\_donation - 设置捐赠金额
    /update\_database - 更新数据库
    /set\_register - 设置可注册状态
    """.format(settings.INVITATION_CREDITS)
    await send_message(
        chat_id=update.effective_chat.id,
        text=textwrap.dedent(body_text),
        parse_mode="markdown",
        context=context,
    )


start_handler = CommandHandler("start", start)

__all__ = ["start_handler"]
