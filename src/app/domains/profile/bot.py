from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.databases import db
from app.utils.utils import send_message


# 查看个人信息
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update._effective_chat.id
    _plex_info = db.get_plex_info_by_tg_id(chat_id)
    _emby_info = db.get_emby_info_by_tg_id(chat_id)
    _stats_info = db.get_stats_by_tg_id(chat_id)
    _codes = db.get_invitation_code_by_owner(chat_id)
    if _plex_info is None and _emby_info is None:
        await send_message(
            chat_id=chat_id,
            text="错误：Plex/Emby 均未绑定，请先绑定任一",
            context=context,
        )
        return
    _credits, _donation = _stats_info[2], _stats_info[1]
    _codes = "" if not _codes else "\n".join(_codes)
    body_text = f"""
{"=" * 44}
<strong>可用积分: </strong>{_credits:.2f}
<strong>捐赠金额: </strong>{_donation}
<strong>可用邀请码：</strong>
{_codes}
{"=" * 44}

"""
    if _plex_info:
        body_text += f"""
{"=" * 20} Plex {"=" * 20}
<strong>Plex 用户名：</strong>{_plex_info[4]}
<strong>总观看时长：</strong>{_plex_info[7]:.2f}h
<strong>当前权限：</strong>{"全部" if _plex_info[5] == 1 else "部分"}

"""
    if _emby_info:
        body_text += f"""
{"=" * 20} Emby {"=" * 20}
<strong>Emby 用户名: </strong>{_emby_info[0]}
<strong>总观看时长：</strong>{_emby_info[5]:.2f}h
<strong>当前权限：</strong>{"全部" if _emby_info[3] == 1 else "部分"}
<strong>当前线路：</strong>{_emby_info[7]}
"""
    await send_message(
        chat_id=chat_id, text=body_text, parse_mode="HTML", context=context
    )


info_handler = CommandHandler("info", info)
