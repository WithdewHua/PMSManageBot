"""21 点活动路由

只做参数校验、权限、异常翻译与超时任务编排；业务逻辑与事务在 `db.py` 的
`blackjack_*` 方法里，规则判定在 `blackjack_engine.py`。

响应一律经 `BlackjackHandResponse.from_hand()` 构造，庄家暗牌与随机种子的过滤
落在该构造入口，不在本模块逐处 if 判断（设计决策 10）。
"""

from app.core.config import settings
from app.core.telegram import get_user_name_from_tg_id

# router declaration belongs to the HTTP assembly(prefix="/blackjack", tags=["21点"])


def _get_group_chat_id() -> str | None:
    """群组播报的 chat_id；未配置 TG_GROUP_ID 则跳过播报。

    与夺宝奇兵、大预言家取同一个配置项，行为保持一致。
    """
    if getattr(settings, "TG_GROUP_ID", None):
        return str(settings.TG_GROUP_ID)
    return None


def _format_jackpot_win(win: dict, jackpot_balance: float) -> str:
    """把一条中奖记录渲染成群播报文案。

    刻意带上牌面：只报金额的话，奖池空虚期会出现「赢得 0.4 积分」这种毫无
    说服力的播报；牌面本身（同花天胡、三张 7）才是真正稀有的部分。稀有度不
    另注明触发频率——那是给管理员判断播报频次用的（见管理面板），播到群里
    只会让报喜的消息读着像说明书。

    余额由调用方查好传入——本函数会被逐条调用，在此处查库等于每条消息各开
    一次会话去读同一个值。
    """
    name = get_user_name_from_tg_id(win["tg_id"])
    cards = " ".join(win.get("player_cards") or [])
    amount = float(win.get("jackpot_won") or 0)

    if win.get("triple_seven"):
        headline = "🎰 <b>三张 7！幸运奖池被通吃</b>"
    else:
        headline = "🃏 <b>同花天胡！命中幸运奖池</b>"

    return (
        f"{headline}\n"
        f"玩家：<code>{name}</code>\n"
        f"牌面：{cards}\n"
        f"奖池派彩：<b>{amount:.2f}</b> 积分\n"
        f"当前奖池：{jackpot_balance:.2f} 积分\n"
        f"入口：WebApp 活动页 → 21 点"
    )


def _fmt_credits(amount: float) -> str:
    """积分金额的展示格式（两位小数，去尾零）。"""
    text = f"{float(amount):.2f}"
    return text.rstrip("0").rstrip(".") if "." in text else text
