import textwrap

from app.config import settings
from app.utils import send_message
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


    Plex 命令:
    /redeem\_plex - 兑换邀请码，格式为 `/redeem_plex 邮箱 邀请码` (注意空格)
    /bind\_plex - 绑定 Plex 用户，格式为 `/bind_plex 邮箱` (注意空格)
    /unlock\_nsfw\_plex - 解锁 NSFW 相关库权限, 消耗 {} 积分
    /lock\_nsfw\_plex - 关闭 NSFW 权限, 积分返还规则：一天内返还 90%, 7 天内 70%, 一月内 50%，超出一个月 0
    
    Emby 命令:
    /redeem\_emby - 兑换邀请码，格式为 `/redeem_emby 用户名 邀请码` (注意空格)
    /bind\_emby - 绑定 Emby 用户，格式为 `/bind_emby 用户名` (注意空格)
    /unlock\_nsfw\_emby - 解锁 NSFW 相关库权限, 消耗 {} 积分
    /lock\_nsfw\_emby - 关闭 NSFW 权限, 积分返还规则：一天内返还 90%, 7 天内 70%, 一月内 50%，超出一个月 0
    /bind\_emby\_line - 绑定 Emby 线路，格式为: 1. `/bind_emby_line 线路` (注意空格) 2. `/bind_emby_line emby_id 线路` (注意空格)
    /unbind\_emby\_line - 解绑 Emby 线路，格式为: 1. `/unbind_emby_line` 2. `/unbind_emby_line emby_id`

    Overseerr 命令:
    /create\_overseerr - 创建 Overseerr 账户，格式为 `/create_overseerr 邮箱 密码` (注意空格)
 
    管理员命令：
    /set\_donation - 设置捐赠金额
    /update\_database - 更新数据库
    /set\_register - 设置可注册状态
    """.format(
        settings.INVITATION_CREDITS, settings.UNLOCK_CREDITS, settings.UNLOCK_CREDITS
    )
    await send_message(
        chat_id=update.effective_chat.id,
        text=textwrap.dedent(body_text),
        parse_mode="markdown",
        context=context,
    )


start_handler = CommandHandler("start", start)

__all__ = ["start_handler"]
