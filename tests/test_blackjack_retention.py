"""留存三机制的结算核心测试：连败救济 + 打满送免费大转盘机会。

手牌均为合成插入（牌面由用例指定，结果确定），经公开路径
`blackjack_stand` / `blackjack_surrender` / `sweep_timed_out_blackjack_hands`
结算，验证钩子在真实结算链路上的行为，而非单独测钩子函数。

合成手牌未走过发牌扣注，故判负手的积分变动只有救济本身——恰好把
「救济不抽水、救济是唯一增量」这两个断言面隔离干净。
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import event

from app.core.kv import SystemConfig
from app.databases import db
from app.domains.blackjack.models import BlackjackTournamentEntry
from app.domains.blackjack.repository import DEFAULT_BLACKJACK_CONFIG
from app.domains.luckywheel.models import WheelStats
from tests.conftest import (
    add_cash_hand,
    add_entry,
    add_tournament,
    add_user,
    get_stats,
    next_id,
)


# SQLite 上 BIGINT 主键不会自增（见 conftest 注释），而 register 与游标写入
# 是**生产代码**插入、无法在测试里显式给 id。挂 before_insert 钩子在
# flush 前补 id——只影响测试进程，不改生产代码
@event.listens_for(BlackjackTournamentEntry, "before_insert")
def _assign_entry_id(mapper, connection, target):
    if target.id is None:
        target.id = next_id()


@event.listens_for(SystemConfig, "before_insert")
def _assign_system_config_id(mapper, connection, target):
    if target.id is None:
        target.id = next_id()


@event.listens_for(WheelStats, "before_insert")
def _assign_wheel_stats_id(mapper, connection, target):
    if target.id is None:
        target.id = next_id()


LOSS = '["KH", "5C", "9H"]'  # 24 点爆牌，庄家不补牌
WIN_P, WIN_D = '["QH", "JH"]', '["KH", "9H"]'  # 20 vs 19，庄家停牌
PUSH_P, PUSH_D = '["QH", "9H"]', '["KH", "9H"]'  # 19 vs 19
EXPIRED_MS = lambda: int(time.time() * 1000) - 20 * 60 * 1000


def lose_once(orm, tg_id: int, *, bet: int = 15, doubled: int = 0) -> dict:
    hand_id = add_cash_hand(orm, tg_id, bet_credits=bet, doubled=doubled)
    return orm.blackjack_stand(tg_id, hand_id)


def patch_cfg(monkeypatch, orm, **overrides) -> None:
    """把 21 点配置固定为「默认值 + 用例覆盖」，屏蔽落库配置的干扰。"""
    merged = {**DEFAULT_BLACKJACK_CONFIG, **overrides}
    monkeypatch.setattr(orm, "get_blackjack_config_dict", lambda: dict(merged))


def freespins_count(orm, tg_id: int) -> int:
    from app.core.db import get_session
    from app.domains.luckywheel.models import LuckywheelFreeSpin

    with get_session() as session:
        return int(
            session.query(LuckywheelFreeSpin)
            .filter(LuckywheelFreeSpin.tg_id == int(tg_id))
            .count()
        )


# ---------------------------------------------------------------- 连败救济


def test_relief_triggers_on_eighth_consecutive_loss(orm, monkeypatch):
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)

    for _ in range(7):
        result = lose_once(orm, 1)
        assert result["relief_credits"] == 0.0

    result = lose_once(orm, 1)
    assert result["relief_credits"] == 15.0
    # 救济落手牌行，与赔付分列
    assert result["hand"]["relief_credits"] == 15.0
    # 判负手不产生赔付，救济是唯一积分增量：100 + 15
    assert get_stats(1)["credits"] == 115.0
    # 触发后计数归零
    assert get_stats(1)["blackjack_lose_streak"] == 0


def test_relief_requires_fresh_streak_after_payment(orm, monkeypatch):
    """第 8 手救济后计数归零：8~15 手是新的 7 连败，第 16 手才再次救济。"""
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)

    for _ in range(16):
        result = lose_once(orm, 1)
    # 第 8 手与第 16 手各救济一次
    assert result["relief_credits"] == 15.0

    from app.core.db import get_session
    from app.domains.blackjack.models import BlackjackHand

    with get_session() as session:
        reliefs = [
            float(h.relief_credits)
            for h in session.query(BlackjackHand)
            .filter(BlackjackHand.tg_id == 1, BlackjackHand.relief_credits > 0)
            .all()
        ]
    assert reliefs == [15.0, 15.0]
    assert get_stats(1)["credits"] == 130.0


def test_push_and_surrender_do_not_break_streak(orm, monkeypatch):
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)

    for _ in range(5):
        lose_once(orm, 1)
    # 平局：计数不变
    hand = add_cash_hand(orm, 1, player_cards=PUSH_P, dealer_cards=PUSH_D)
    orm.blackjack_stand(1, hand)
    assert get_stats(1)["blackjack_lose_streak"] == 5

    # 投降：计数不变（投降走独立结算路径，钩子以 outcome='surrender' 中立处理）
    hand = add_cash_hand(
        orm, 1, player_cards='["KH", "6C"]', dealer_cards='["KD", "9H"]'
    )
    result = orm.blackjack_surrender(1, hand)
    assert result["settled"] is True
    assert get_stats(1)["blackjack_lose_streak"] == 5

    # 再负 3 手：累计第 8 个判负触发救济
    for _ in range(3):
        result = lose_once(orm, 1)
    assert result["relief_credits"] == 15.0


def test_win_resets_streak(orm, monkeypatch):
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)

    for _ in range(6):
        lose_once(orm, 1)
    hand = add_cash_hand(orm, 1, player_cards=WIN_P, dealer_cards=WIN_D)
    orm.blackjack_stand(1, hand)
    assert get_stats(1)["blackjack_lose_streak"] == 0

    for _ in range(2):
        result = lose_once(orm, 1)
    assert result["relief_credits"] == 0.0
    assert get_stats(1)["blackjack_lose_streak"] == 2


def test_natural_blackjack_resets_streak(orm, monkeypatch):
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)

    for _ in range(7):
        lose_once(orm, 1)
    hand = add_cash_hand(
        orm, 1, player_cards='["AS", "KH"]', dealer_cards='["KD", "5C"]'
    )
    result = orm.blackjack_stand(1, hand)
    assert result["outcome"] == "blackjack"
    assert get_stats(1)["blackjack_lose_streak"] == 0


def test_doubled_loss_relief_uses_base_bet(orm, monkeypatch):
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)

    for _ in range(7):
        lose_once(orm, 1)
    # 加倍判负：投注总额 30，救济按基础注额 15
    result = lose_once(orm, 1, doubled=1)
    assert result["relief_credits"] == 15.0


def test_timeout_loss_counts_toward_streak(orm, monkeypatch):
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)

    for _ in range(7):
        lose_once(orm, 1)
    # 超时兜底路径：手牌超时（快照时限 15 分钟），按停牌结算
    hand_id = add_cash_hand(orm, 1, created_at_ms=EXPIRED_MS())
    swept = orm.sweep_timed_out_blackjack_hands(tg_id=1)
    assert swept == 1

    from app.core.db import get_session
    from app.domains.blackjack.models import BlackjackHand

    with get_session() as session:
        hand = session.get(BlackjackHand, hand_id)
        assert hand.outcome == "bust"
        assert float(hand.relief_credits or 0) == 15.0


def test_tournament_hand_not_counted(orm, monkeypatch):
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)
    t = add_tournament(orm, total_hands=2)
    add_entry(orm, t["id"], 1, chips=1000, registered_at_ms=1)

    # 赛内手牌（爆牌牌面）超时后经 dispatch 路由到锦标赛适配层结算
    add_cash_hand(orm, 1, tournament_id=int(t["id"]), created_at_ms=EXPIRED_MS())

    stats_before = get_stats(1)
    streak_before = int(stats_before["blackjack_lose_streak"])
    hands_before = int(stats_before["blackjack_hands_since_freespin"])

    orm.sweep_timed_out_blackjack_hands(tg_id=1)

    stats_after = get_stats(1)
    assert stats_after["blackjack_lose_streak"] == streak_before
    assert stats_after["blackjack_hands_since_freespin"] == hands_before


def test_relief_disabled_by_config(orm, monkeypatch):
    """停用只门控发放：计数继续维护（判负 +1 / 判胜归零），不发救济。"""
    patch_cfg(monkeypatch, orm, relief_enabled=False)
    add_user(orm, 1, credits=100.0)

    for _ in range(9):
        result = lose_once(orm, 1)
    assert result["relief_credits"] == 0.0
    # 计数未被门控冻结：9 连败如实累计
    assert get_stats(1)["blackjack_lose_streak"] == 9

    # 停用期间胜局同样归零
    hand = add_cash_hand(orm, 1, player_cards=WIN_P, dealer_cards=WIN_D)
    orm.blackjack_stand(1, hand)
    assert get_stats(1)["blackjack_lose_streak"] == 0


def test_relief_reenable_after_threshold_crossed_during_disabled(orm, monkeypatch):
    """停用期间跨过阈值：计数如实反映真实连败，重启用后按真实计数支付。"""
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)

    for _ in range(7):
        lose_once(orm, 1)
    # 停用期间第 8 负：计数到 8 但不支付
    patch_cfg(monkeypatch, orm, relief_enabled=False)
    result = lose_once(orm, 1)
    assert result["relief_credits"] == 0.0
    assert get_stats(1)["blackjack_lose_streak"] == 8

    # 重启用：下一负（真实连败第 9 手）按阈值支付
    patch_cfg(monkeypatch, orm)
    result = lose_once(orm, 1)
    assert result["relief_credits"] == 15.0
    assert get_stats(1)["blackjack_lose_streak"] == 0


# ------------------------------------------------------ 打满送免费大转盘机会


def test_freespin_granted_at_hand_threshold(orm, monkeypatch):
    patch_cfg(monkeypatch, orm, freespins_hand_threshold=20)
    add_user(orm, 1, credits=100.0)

    for _ in range(19):
        result = lose_once(orm, 1)
        assert result["freespins"] == []

    result = lose_once(orm, 1)
    assert len(result["freespins"]) == 1
    assert get_stats(1)["blackjack_hands_since_freespin"] == 0
    assert freespins_count(orm, 1) == 1

    from app.core.db import get_session
    from app.domains.luckywheel.models import LuckywheelFreeSpin

    with get_session() as session:
        spin = (
            session.query(LuckywheelFreeSpin)
            .filter(LuckywheelFreeSpin.tg_id == 1)
            .one()
        )
        assert spin.source == "blackjack"
        assert spin.used_at_ms is None
        # 有效期 7 个自然日
        delta_ms = int(spin.expires_at_ms) - int(spin.granted_at_ms)
        assert delta_ms == 7 * 86400 * 1000


def test_all_settled_outcomes_count(orm, monkeypatch):
    """平局、投降、超时、判负、判胜都计入免费机会的手数。"""
    patch_cfg(monkeypatch, orm, freespins_hand_threshold=5)
    add_user(orm, 1, credits=100.0)

    lose_once(orm, 1)
    lose_once(orm, 1)
    hand = add_cash_hand(orm, 1, player_cards=PUSH_P, dealer_cards=PUSH_D)
    orm.blackjack_stand(1, hand)
    hand = add_cash_hand(
        orm, 1, player_cards='["KH", "6C"]', dealer_cards='["KD", "9H"]'
    )
    orm.blackjack_surrender(1, hand)
    add_cash_hand(orm, 1, created_at_ms=EXPIRED_MS())  # 第 5 手：超时结算
    orm.sweep_timed_out_blackjack_hands(tg_id=1)

    assert freespins_count(orm, 1) == 1
    assert get_stats(1)["blackjack_hands_since_freespin"] == 0

    # 第 6 手：新的计数周期
    hand = add_cash_hand(orm, 1, player_cards=WIN_P, dealer_cards=WIN_D)
    result = orm.blackjack_stand(1, hand)
    assert result["freespins"] == []
    assert get_stats(1)["blackjack_hands_since_freespin"] == 1


def test_freespin_weekly_cap_blocks_new_grants(orm, monkeypatch):
    patch_cfg(monkeypatch, orm, freespins_hand_threshold=2, freespins_weekly_cap=3)
    add_user(orm, 1, credits=100.0)

    for _ in range(6):  # 6 手 / 阈值 2 = 3 次机会，恰好触顶
        lose_once(orm, 1)
    assert freespins_count(orm, 1) == 3
    assert get_stats(1)["blackjack_hands_since_freespin"] == 0

    # 触顶后手数继续累计、不再发放
    for _ in range(3):
        result = lose_once(orm, 1)
        assert result["freespins"] == []
    assert freespins_count(orm, 1) == 3
    assert get_stats(1)["blackjack_hands_since_freespin"] == 3


def test_threshold_lowering_converts_backlog(orm, monkeypatch):
    """管理员调低阈值后，存量手数应连续转换直至配额用尽。"""
    patch_cfg(monkeypatch, orm, freespins_hand_threshold=20)
    add_user(orm, 1, credits=100.0)

    for _ in range(11):  # 未达 20，不转换，存量 11
        lose_once(orm, 1)
    assert get_stats(1)["blackjack_hands_since_freespin"] == 11

    patch_cfg(monkeypatch, orm, freespins_hand_threshold=5)
    result = lose_once(orm, 1)  # 12 ≥ 5×2，单手连发两张
    assert len(result["freespins"]) == 2
    assert get_stats(1)["blackjack_hands_since_freespin"] == 2


def test_freespin_cap_zero_pauses_grants_not_progress(orm, monkeypatch):
    """weekly_cap=0 只暂停发放，进度继续累计；恢复后按存量进度转换。"""
    add_user(orm, 1, credits=100.0)
    patch_cfg(monkeypatch, orm, freespins_hand_threshold=5, freespins_weekly_cap=0)
    for _ in range(5):
        result = lose_once(orm, 1)
    assert result["freespins"] == []
    assert freespins_count(orm, 1) == 0
    assert get_stats(1)["blackjack_hands_since_freespin"] == 5  # 进度未冻结

    # 恢复配额：下一手使进度 6 ≥ 5，立即转换
    patch_cfg(monkeypatch, orm, freespins_hand_threshold=5, freespins_weekly_cap=3)
    result = lose_once(orm, 1)
    assert len(result["freespins"]) == 1
    assert get_stats(1)["blackjack_hands_since_freespin"] == 1


def test_freespin_disabled_by_config(orm, monkeypatch):
    patch_cfg(monkeypatch, orm, freespins_enabled=False)
    add_user(orm, 1, credits=100.0)

    for _ in range(25):
        result = lose_once(orm, 1)
    assert result["freespins"] == []
    assert freespins_count(orm, 1) == 0


# ------------------------------------------------------ 争霸赛余额与周返还


def _register(orm, tg_id: int, tournament_id: int) -> dict:
    return orm.register_blackjack_tournament(tg_id, tournament_id)


def _registering_tournament(orm, **kwargs) -> dict:
    """建一场处于报名中、截止时间在未来的赛事。"""
    from tests.conftest import _now_ms

    kwargs.setdefault("status", orm.TOURNAMENT_REGISTERING)
    kwargs.setdefault("register_deadline_ms", _now_ms() + 2 * 3600 * 1000)
    kwargs.setdefault("entrant_count", 0)
    return add_tournament(orm, **kwargs)


def _set_wallet(tg_id: int, wallet: float) -> None:
    from app.core.db import get_session
    from app.domains.identity.models import Statistics

    with get_session() as session:
        stats = session.get(Statistics, int(tg_id))
        stats.tournament_wallet_credits = float(wallet)
    _ = Statistics


def test_register_full_wallet_payment(orm, monkeypatch):
    patch_cfg(monkeypatch, orm, enabled=True)
    add_user(orm, 1, credits=100.0)
    _set_wallet(1, 50.0)
    t = _registering_tournament(orm)

    result = _register(orm, 1, t["id"])

    stats = get_stats(1)
    assert stats["credits"] == 100.0  # 积分分文未动
    assert stats["tournament_wallet_credits"] == 20.0
    assert result["entry"]["wallet_paid_credits"] == 30.0
    assert result["entry"]["credits_paid_credits"] == 0.0


def test_register_mixed_payment(orm, monkeypatch):
    patch_cfg(monkeypatch, orm, enabled=True)
    add_user(orm, 1, credits=100.0)
    _set_wallet(1, 10.0)
    t = _registering_tournament(orm)

    result = _register(orm, 1, t["id"])

    stats = get_stats(1)
    assert stats["credits"] == 80.0
    assert stats["tournament_wallet_credits"] == 0.0
    assert result["entry"]["wallet_paid_credits"] == 10.0
    assert result["entry"]["credits_paid_credits"] == 20.0
    # 余额随报名结果返回，路由层不再二次读库
    assert result["current_credits"] == 80.0
    assert result["tournament_wallet_credits"] == 0.0


def test_register_rejects_when_combined_insufficient(orm, monkeypatch):
    patch_cfg(monkeypatch, orm, enabled=True)
    add_user(orm, 1, credits=15.0)
    _set_wallet(1, 10.0)
    t = _registering_tournament(orm)

    with pytest.raises(ValueError, match="insufficient credits"):
        _register(orm, 1, t["id"])

    stats = get_stats(1)
    assert stats["credits"] == 15.0
    assert stats["tournament_wallet_credits"] == 10.0


def test_register_zero_credits_full_wallet(orm, monkeypatch):
    patch_cfg(monkeypatch, orm, enabled=True)
    add_user(orm, 1, credits=0.0)
    _set_wallet(1, 40.0)
    t = _registering_tournament(orm)

    result = _register(orm, 1, t["id"])

    assert result["entry"]["wallet_paid_credits"] == 30.0
    assert get_stats(1)["credits"] == 0.0


def test_cancel_refunds_by_payment_source(orm, monkeypatch):
    patch_cfg(monkeypatch, orm, enabled=True)
    add_user(orm, 1, credits=100.0)
    _set_wallet(1, 10.0)
    t = _registering_tournament(orm)
    _register(orm, 1, t["id"])

    result = orm.cancel_blackjack_tournament(t["id"])

    assert result["cancelled"] is True
    refund = result["refunds"][0]
    assert refund["wallet_credits"] == 10.0
    assert refund["paid_credits"] == 20.0
    stats = get_stats(1)
    assert stats["credits"] == 100.0
    assert stats["tournament_wallet_credits"] == 10.0


def test_cancel_legacy_entry_refunds_full_credits(orm, monkeypatch):
    """迁移前创建的报名（拆分两列为 0）按全额积分退款。"""
    patch_cfg(monkeypatch, orm, enabled=True)
    add_user(orm, 1, credits=0.0)
    t = _registering_tournament(orm)

    # 手工插入无拆分的存量报名（模拟迁移前数据）
    from app.core.db import get_session

    with get_session() as session:
        session.add(
            BlackjackTournamentEntry(
                id=next_id(),
                tournament_id=int(t["id"]),
                tg_id=1,
                chips=1000,
                hands_played=0,
                status=orm.ENTRY_PLAYING,
                wallet_paid_credits=0.0,
                credits_paid_credits=0.0,
                registered_at_ms=1,
            )
        )

    result = orm.cancel_blackjack_tournament(t["id"])

    assert result["cancelled"] is True
    refund = result["refunds"][0]
    assert refund["wallet_credits"] == 0.0
    assert refund["paid_credits"] == 30.0
    stats = get_stats(1)
    assert stats["credits"] == 30.0
    assert stats["tournament_wallet_credits"] == 0.0


# ------------------------------------------------------ 周结算


def _prev_week_bounds(orm) -> tuple:
    """上一完整自然周的 [start_s, end_s)（秒），按 settings.TZ 周一口径。"""
    now_week_ms = orm._blackjack_week_start_ms()
    week_ms = 7 * 86400 * 1000
    prev_start_ms = now_week_ms - week_ms
    return prev_start_ms // 1000, now_week_ms // 1000


def _rewind_cashback_cursor(orm, week_start_ms: int) -> None:
    from app.core.db import get_session
    from app.core.kv import SystemConfig
    from app.databases.db import DatabaseORM

    with get_session() as session:
        row = (
            session.query(SystemConfig)
            .filter(
                SystemConfig.config_type == "blackjack",
                SystemConfig.config_key == DatabaseORM.CASHBACK_CURSOR_KEY,
            )
            .one_or_none()
        )
        assert row is not None
        row.config_value = str(int(week_start_ms))


def _add_settled_hand(
    tg_id: int, *, net: float, settled_at_s: int, bet: int = 15
) -> None:
    """直接插入一手已结算的现金局手牌，凑出指定净变动（聚合测试用）。"""
    from app.core.db import get_session
    from app.domains.blackjack.models import BlackjackHand
    from app.domains.blackjack.rules import STATUS_SETTLED

    with get_session() as session:
        session.add(
            BlackjackHand(
                id=next_id(),
                tg_id=int(tg_id),
                tournament_id=None,
                status=STATUS_SETTLED,
                bet_credits=int(bet),
                doubled=0,
                deck_seed="00" * 16,
                next_card_index=4,
                player_cards=LOSS,
                dealer_cards='["KD", "5C"]',
                outcome="lose",
                payout_credits=round(net + bet, 2),
                rake_credits=0.0,
                settled_at=int(settled_at_s),
                created_at_ms=int(settled_at_s) * 1000,
            )
        )


def test_cashback_first_run_only_anchors(orm, monkeypatch):
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)
    start_s, _ = _prev_week_bounds(orm)
    _add_settled_hand(1, net=-60.0, settled_at_s=start_s + 100)

    result = orm.settle_blackjack_weekly_cashback()

    assert result["anchored"] is True
    assert result["settled_weeks"] == []
    assert get_stats(1)["tournament_wallet_credits"] == 0.0


def test_cashback_settles_net_losers(orm, monkeypatch):
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)
    start_s, _ = _prev_week_bounds(orm)
    _add_settled_hand(1, net=-60.0, settled_at_s=start_s + 100)

    # 首跑锚定后把游标拨回两周前，使上一完整周可结算
    orm.settle_blackjack_weekly_cashback()
    _rewind_cashback_cursor(orm, (start_s - 7 * 86400) * 1000)

    result = orm.settle_blackjack_weekly_cashback()

    assert result["anchored"] is False
    weeks = result["settled_weeks"]
    assert len(weeks) == 1
    users = weeks[0]["users"]
    assert len(users) == 1
    assert users[0]["net_change"] == -60.0
    assert users[0]["cashback"] == 9.0  # 15%
    assert get_stats(1)["tournament_wallet_credits"] == 9.0
    assert get_stats(1)["credits"] == 100.0  # 返还不进积分


def test_cashback_rerun_is_idempotent(orm, monkeypatch):
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)
    start_s, _ = _prev_week_bounds(orm)
    _add_settled_hand(1, net=-60.0, settled_at_s=start_s + 100)

    orm.settle_blackjack_weekly_cashback()
    _rewind_cashback_cursor(orm, (start_s - 7 * 86400) * 1000)

    orm.settle_blackjack_weekly_cashback()
    result = orm.settle_blackjack_weekly_cashback()  # 重跑：游标已推进，无事可做

    assert (
        all(not w["users"] for w in result["settled_weeks"])
        or result["settled_weeks"] == []
    )
    assert get_stats(1)["tournament_wallet_credits"] == 9.0  # 只入账一次


def test_cashback_skips_net_winners_and_small_amounts(orm, monkeypatch):
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)  # 净赢者
    add_user(orm, 2, credits=100.0)  # 低于门槛
    start_s, _ = _prev_week_bounds(orm)
    _add_settled_hand(1, net=40.0, settled_at_s=start_s + 100)
    _add_settled_hand(2, net=-5.0, settled_at_s=start_s + 200)

    orm.settle_blackjack_weekly_cashback()
    _rewind_cashback_cursor(orm, (start_s - 7 * 86400) * 1000)
    result = orm.settle_blackjack_weekly_cashback()

    users = result["settled_weeks"][0]["users"]
    assert users == []  # 净赢者不发；-5×15%=0.75 < 1 门槛也不发
    assert get_stats(1)["tournament_wallet_credits"] == 0.0
    assert get_stats(2)["tournament_wallet_credits"] == 0.0


def test_cashback_jackpot_makes_net_winner(orm, monkeypatch):
    """手牌净亏但彩池派彩把周净变动拉正时不返还。"""
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)
    start_s, _ = _prev_week_bounds(orm)
    # 一手净亏 80 + 奖池派彩 200 → 周净变动 +120
    _add_settled_hand(1, net=-80.0, settled_at_s=start_s + 100)
    from app.core.db import get_session
    from app.domains.blackjack.models import BlackjackHand

    with get_session() as session:
        session.query(BlackjackHand).filter(
            BlackjackHand.tg_id == 1, BlackjackHand.jackpot_won.is_(None)
        ).update({"jackpot_won": 200.0})

    orm.settle_blackjack_weekly_cashback()
    _rewind_cashback_cursor(orm, (start_s - 7 * 86400) * 1000)
    result = orm.settle_blackjack_weekly_cashback()

    assert result["settled_weeks"][0]["users"] == []
    assert get_stats(1)["tournament_wallet_credits"] == 0.0


def test_cashback_catches_up_missed_weeks(orm, monkeypatch):
    """停机跨周：一次运行把两个错过的完整周都补上。"""
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)
    now_week_ms = orm._blackjack_week_start_ms()
    week_ms = 7 * 86400 * 1000
    w1_start_s = (now_week_ms - 2 * week_ms) // 1000
    w2_start_s = (now_week_ms - 1 * week_ms) // 1000
    _add_settled_hand(1, net=-40.0, settled_at_s=w1_start_s + 100)
    _add_settled_hand(1, net=-20.0, settled_at_s=w2_start_s + 100)

    orm.settle_blackjack_weekly_cashback()  # 锚定
    _rewind_cashback_cursor(orm, now_week_ms - 3 * week_ms)

    result = orm.settle_blackjack_weekly_cashback()

    assert len(result["settled_weeks"]) == 2
    # 两周各 6 与 3 的返还
    assert get_stats(1)["tournament_wallet_credits"] == 9.0


def test_cashback_disabled(orm, monkeypatch):
    patch_cfg(monkeypatch, orm, cashback_enabled=False)
    add_user(orm, 1, credits=100.0)
    start_s, _ = _prev_week_bounds(orm)
    _add_settled_hand(1, net=-60.0, settled_at_s=start_s + 100)

    result = orm.settle_blackjack_weekly_cashback()

    assert result["enabled"] is False
    assert get_stats(1)["tournament_wallet_credits"] == 0.0


# ------------------------------------------------------ 免费机会的消耗


def _add_free_spin(
    tg_id: int,
    *,
    expires_in_ms: int = 7 * 86400 * 1000,
    source: str = "blackjack",
    granted_at_ms: int | None = None,
) -> int:
    """插入一张免费机会。expires_in_ms 为负时构造「已过期」的行（回溯
    发放时间以满足 expires > granted 的 CHECK 约束）。"""
    from app.core.db import get_session
    from app.domains.luckywheel.models import LuckywheelFreeSpin

    now_ms = int(time.time() * 1000)
    expires_at = now_ms + int(expires_in_ms)
    granted = now_ms if expires_in_ms > 0 else expires_at - 7 * 86400 * 1000
    if granted_at_ms is not None:
        granted = int(granted_at_ms)
    with get_session() as session:
        row = LuckywheelFreeSpin(
            tg_id=int(tg_id),
            source=source,
            granted_at_ms=granted,
            expires_at_ms=expires_at,
        )
        session.add(row)
        session.flush()
        return int(row.id)


def test_consume_freespin_claims_oldest_expiry(orm):
    add_user(orm, 1, credits=100.0)
    later = _add_free_spin(1, expires_in_ms=7 * 86400 * 1000)
    sooner = _add_free_spin(1, expires_in_ms=1 * 86400 * 1000)

    claimed = db.consume_blackjack_freespin(1)

    assert claimed is not None
    assert claimed["id"] == sooner  # 先消耗最早到期的
    assert claimed["expires_at_ms"] > 0

    claimed2 = db.consume_blackjack_freespin(1)
    assert claimed2["id"] == later

    assert db.consume_blackjack_freespin(1) is None  # 用尽


def test_consume_freespin_skips_expired(orm):
    add_user(orm, 1, credits=100.0)
    _add_free_spin(1, expires_in_ms=-1000)  # 已过期

    assert db.consume_blackjack_freespin(1) is None


def test_release_freespin_restores_availability(orm):
    add_user(orm, 1, credits=100.0)
    spin_id = _add_free_spin(1)

    claimed = db.consume_blackjack_freespin(1)
    assert claimed["id"] == spin_id

    # 补偿路径：只回退本方写入的时戳
    assert (
        db.release_blackjack_freespin(spin_id, claimed_at_ms=claimed["claimed_at_ms"])
        is True
    )
    assert db.consume_blackjack_freespin(1) is not None  # 机会回来了


async def test_free_spin_execute_skips_cost(orm, monkeypatch):
    """免费机会走 execute_single_spin：不扣参与费、记录来源。"""
    from app.domains.luckywheel.router import (
        LuckyWheelConfig,
        LuckyWheelItem,
        execute_single_spin,
    )

    add_user(orm, 1, credits=25.0)  # 低于普通门槛 30
    _add_free_spin(1)

    claimed = db.consume_blackjack_freespin(1)
    assert claimed is not None

    config = LuckyWheelConfig(
        items=[LuckyWheelItem(name="谢谢参与", probability=100.0)],
        cost_credits=10,
        min_credits_required=30,
    )
    result, final_credits, _ = await execute_single_spin(
        config=config,
        user_id=1,
        current_credits=25.0,
        cost_credits=0.0,
        source="blackjack_free",
    )

    assert result.used_free_spin is True
    assert final_credits == 25.0  # 参与费分文未扣
    assert result.current_credits == 25.0

    from app.core.db import get_session
    from app.domains.luckywheel.models import WheelStats

    with get_session() as session:
        record = session.query(WheelStats).filter(WheelStats.tg_id == 1).one()
        assert record.cost_credits == 0.0
        assert record.source == "blackjack_free"


async def test_free_spin_negative_prize_truncates_at_zero(orm, monkeypatch):
    """0 余额玩家的免费盘：负分奖品截断为 0，不会出现负积分。"""
    from app.domains.luckywheel.router import (
        LuckyWheelConfig,
        LuckyWheelItem,
        execute_single_spin,
    )

    add_user(orm, 1, credits=0.0)
    _add_free_spin(1)
    claimed = db.consume_blackjack_freespin(1)
    assert claimed is not None

    config = LuckyWheelConfig(
        items=[LuckyWheelItem(name="积分 -50", probability=100.0)],
        cost_credits=10,
        min_credits_required=30,
    )
    result, final_credits, _ = await execute_single_spin(
        config=config,
        user_id=1,
        current_credits=0.0,
        cost_credits=0.0,
        source="blackjack_free",
    )

    assert final_credits == 0.0
    assert result.credits_change == 0.0  # 截断后实际变化为 0


def test_freespin_summary_reports_state(orm):
    add_user(orm, 1, credits=100.0)
    summary = db.get_blackjack_freespin_summary(1)
    assert summary["available"] == 0

    _add_free_spin(1)
    _add_free_spin(1)
    summary = db.get_blackjack_freespin_summary(1)
    assert summary["available"] == 2
    assert len(summary["expires_at_ms_list"]) == 2
    assert summary["hands_since_freespin"] == 0
    assert summary["hand_threshold"] == 20  # 默认配置


# ------------------------------------------------------ review 修复的回归


def test_cashback_launch_anchor_settles_first_full_week_after_deploy(orm, monkeypatch):
    """周中部署：锚点取部署周（=上一完整周），部署周不结算；下一周任务
    结算的是「启用后的第一个完整自然周」而非再下一周。"""
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)
    now_week_ms = orm._blackjack_week_start_ms()
    week_ms = 7 * 86400 * 1000
    deploy_week_s = (now_week_ms - week_ms) // 1000  # 部署周 = 上一完整周
    first_full_week_s = now_week_ms // 1000  # 启用后的第一个完整自然周
    # 部署周内部署日之前的亏损 + 第一个完整周的亏损
    _add_settled_hand(1, net=-100.0, settled_at_s=deploy_week_s + 3600)
    _add_settled_hand(1, net=-60.0, settled_at_s=first_full_week_s + 3600)

    # 首跑：锚定，不结算
    result = orm.settle_blackjack_weekly_cashback()
    assert result["anchored"] is True
    assert get_stats(1)["tournament_wallet_credits"] == 0.0

    # 模拟下一周的周一任务
    monkeypatch.setattr(
        orm, "_blackjack_week_start_ms", lambda **kw: now_week_ms + week_ms
    )
    result = orm.settle_blackjack_weekly_cashback()

    weeks = result["settled_weeks"]
    assert len(weeks) == 1
    assert weeks[0]["week_start_ms"] == now_week_ms  # 第一个完整周
    assert len(weeks[0]["users"]) == 1
    # 只有第一个完整周的 -60 参与结算；部署周的 -100 不参与
    assert weeks[0]["users"][0]["net_change"] == -60.0
    assert get_stats(1)["tournament_wallet_credits"] == 9.0


def test_cashback_disabled_period_not_backsettled(orm, monkeypatch):
    """停用期间游标照常推进：重启用后不回溯补结停用期的周（防爆发式
    补结算与私信倾泻）。"""
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)
    now_week_ms = orm._blackjack_week_start_ms()
    week_ms = 7 * 86400 * 1000
    # 两周前的亏损（处于将来的停用期内）
    old_s = (now_week_ms - 2 * week_ms) // 1000
    _add_settled_hand(1, net=-100.0, settled_at_s=old_s + 3600)

    # 锚定后把游标拨回三周前（模拟停用期任务长期未跑）
    orm.settle_blackjack_weekly_cashback()
    _rewind_cashback_cursor(orm, now_week_ms - 3 * week_ms)

    # 停用状态下运行：游标推进，不结算
    patch_cfg(monkeypatch, orm, cashback_enabled=False)
    result = orm.settle_blackjack_weekly_cashback()
    assert result["enabled"] is False
    assert get_stats(1)["tournament_wallet_credits"] == 0.0

    # 重启用：不回溯停用期
    patch_cfg(monkeypatch, orm)
    result = orm.settle_blackjack_weekly_cashback()
    assert result["enabled"] is True
    assert all(not w["users"] for w in result["settled_weeks"])
    assert get_stats(1)["tournament_wallet_credits"] == 0.0


def test_hand_response_forwards_relief_credits(orm, monkeypatch):
    """from_hand 必须转发 relief_credits——前端牌桌读的是手牌层，
    该层缺失会让救济提示永不显示。"""
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)
    for _ in range(8):
        result = lose_once(orm, 1)
    assert result["relief_credits"] == 15.0

    from app.domains.blackjack.schemas import BlackjackHandResponse

    resp = BlackjackHandResponse.from_hand(result["hand"])
    assert resp.relief_credits == 15.0


# ------------------------------------------- review 第二轮修复的回归


def test_user_and_admin_stats_include_relief(orm, monkeypatch):
    """救济计入净变动：用户统计卡与管理端聚合的口径与周结算一致。"""
    patch_cfg(monkeypatch, orm)
    add_user(orm, 1, credits=100.0)
    for _ in range(8):
        lose_once(orm, 1)

    # 8 手：7 手净 -15，救济手净 0（赔付 0 − 注 15 + 救济 15）
    user_stats = db.get_user_blackjack_stats(1)
    assert user_stats["net_credits"] == -105.0

    admin_stats = db.get_blackjack_admin_stats()
    # wagered 120、payout 0、jackpot 0、relief 15 → net = 15 − 120
    assert admin_stats["net_credits"] == -105.0


async def test_admin_notification_failure_does_not_break_spin(orm, monkeypatch):
    """邀请码的管理员通知抛异常不得影响抽奖结果——否则免费机会路径会
    触发补偿释放，变成「奖品与机会双收」（review 第二轮 #1）。"""
    from app.domains.luckywheel import router as lw

    add_user(orm, 1, credits=25.0)
    _add_free_spin(1)
    claimed = db.consume_blackjack_freespin(1)
    assert claimed is not None

    config = lw.LuckyWheelConfig(
        items=[lw.LuckyWheelItem(name="邀请码", probability=100.0)],
        cost_credits=10,
        min_credits_required=30,
    )

    async def _boom(**kwargs):
        raise ValueError("chat_id malformed")

    monkeypatch.setattr(lw, "send_message_by_url", _boom)
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "TG_ADMIN_CHAT_ID", [12345], raising=False)

    # 通知失败被吞掉，抽奖正常返回
    result, final_credits, _ = await lw.execute_single_spin(
        config=config,
        user_id=1,
        current_credits=25.0,
        cost_credits=0.0,
        source="blackjack_free",
    )
    assert result.item.name == "邀请码"
    assert final_credits == 25.0  # 邀请码奖品不改变积分


def test_wallet_route_precedes_parameterized_routes():
    """GET /wallet 必须先于 /{tournament_id} 注册——FastAPI 按注册顺序匹配，
    否则 "wallet" 会被当作 int 赛事 ID 解析而 422（线上实测回归）。"""
    from starlette.routing import Match

    from app.domains.blackjack.router.tournament import router

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/blackjack/tournament/wallet",
    }
    for route in router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            # 第一个全量匹配的必须是字面量路由，而非 /{tournament_id}
            assert route.name == "get_wallet", (
                f"/wallet 撞上了先注册的路由 {route.path!r}，"
                f"把字面量路由移到参数化路由之前"
            )
            return
    raise AssertionError("没有路由匹配 /blackjack/tournament/wallet")


# ------------------------------------------------ 免费机会来源解耦（礼包来源）


def test_weekly_cap_ignores_gift_pack_freespins(orm, monkeypatch):
    """本周已持有 5 张礼包来源的机会，打满阈值仍获得 21 点来源的机会。"""
    patch_cfg(monkeypatch, orm, freespins_hand_threshold=2, freespins_weekly_cap=5)
    add_user(orm, 1, credits=100.0)
    for _ in range(5):
        _add_free_spin(1, source="gift_pack")

    lose_once(orm, 1)
    result = lose_once(orm, 1)

    assert len(result["freespins"]) == 1
    assert freespins_count(orm, 1) == 6


def test_notify_cursor_returns_only_blackjack_and_skips_gift_rows(orm):
    """礼包行与 21 点行交错插入：只返回 21 点行，游标越过礼包行。"""
    add_user(orm, 1, credits=100.0)
    old_ms = int(time.time() * 1000) - 5 * 60 * 1000  # 早于 60 秒安全边界

    # 首次运行只初始化游标
    assert db.claim_unnotified_blackjack_freespins() == []

    bj1 = _add_free_spin(1, granted_at_ms=old_ms)
    gp1 = _add_free_spin(1, source="gift_pack", granted_at_ms=old_ms)
    bj2 = _add_free_spin(1, granted_at_ms=old_ms)
    gp2 = _add_free_spin(1, source="gift_pack", granted_at_ms=old_ms)

    claimed = db.claim_unnotified_blackjack_freespins()
    assert [c["id"] for c in claimed] == [bj1, bj2]

    # 游标推进到扫描范围内的最大 id（含礼包行），不会重复返回
    from app.core.db import get_session

    with get_session() as session:
        _, cursor = db._read_retention_cursor(session, db.FREESPIN_NOTIFY_CURSOR_KEY)
    assert cursor == max(bj1, gp1, bj2, gp2)
    assert db.claim_unnotified_blackjack_freespins() == []

    # 游标后只有礼包行时也会越过，其后的 21 点行照常返回
    gp3 = _add_free_spin(1, source="gift_pack", granted_at_ms=old_ms)
    assert db.claim_unnotified_blackjack_freespins() == []
    bj3 = _add_free_spin(1, granted_at_ms=old_ms)
    assert [c["id"] for c in db.claim_unnotified_blackjack_freespins()] == [bj3]
    assert bj3 > gp3


def test_consume_returns_source_and_orders_by_expiry_across_sources(orm):
    """不区分来源、最早到期优先；返回值带来源。"""
    add_user(orm, 1, credits=100.0)
    gift_later = _add_free_spin(1, source="gift_pack", expires_in_ms=3 * 86400 * 1000)
    bj_sooner = _add_free_spin(1, expires_in_ms=1 * 86400 * 1000)

    first = db.consume_blackjack_freespin(1)
    assert first["id"] == bj_sooner
    assert first["source"] == "blackjack"

    second = db.consume_blackjack_freespin(1)
    assert second["id"] == gift_later
    assert second["source"] == "gift_pack"


@pytest.mark.parametrize(
    "spin_source, wheel_source",
    [("blackjack", "blackjack_free"), ("gift_pack", "gift_pack_free")],
)
async def test_spin_records_free_spin_source(orm, spin_source, wheel_source):
    """单次转盘按消耗到的机会来源映射参与记录的 source。"""
    from app.domains.luckywheel import router as lw

    add_user(orm, 1, credits=0.0)
    _add_free_spin(1, source=spin_source)
    claimed = db.consume_blackjack_freespin(1)

    config = lw.LuckyWheelConfig(
        items=[lw.LuckyWheelItem(name="谢谢参与", probability=100.0)],
        cost_credits=10,
        min_credits_required=30,
    )
    result, _, _ = await lw.execute_single_spin(
        config=config,
        user_id=1,
        current_credits=0.0,
        cost_credits=0.0,
        source=lw.wheel_source_for_free_spin(claimed["source"]),
    )

    assert result.used_free_spin is True
    assert result.free_spin_source == spin_source

    from app.core.db import get_session

    with get_session() as session:
        record = session.query(WheelStats).filter(WheelStats.tg_id == 1).one()
        assert record.source == wheel_source


async def test_paid_spin_has_no_free_spin_source(orm):
    from app.domains.luckywheel import router as lw

    add_user(orm, 1, credits=100.0)
    config = lw.LuckyWheelConfig(
        items=[lw.LuckyWheelItem(name="谢谢参与", probability=100.0)],
        cost_credits=10,
        min_credits_required=30,
    )
    result, _, _ = await lw.execute_single_spin(
        config=config, user_id=1, current_credits=100.0
    )
    assert result.used_free_spin is False
    assert result.free_spin_source is None


def _load_audit_script(monkeypatch):
    import importlib.util
    from pathlib import Path

    from app.core.config import settings as app_settings

    # 脚本导入时会读取真实 .env，测试里屏蔽掉
    monkeypatch.setattr(type(app_settings), "load_config_from_file", lambda self: None)
    path = Path(__file__).parents[1] / "scripts" / "blackjack_retention_audit.py"
    spec = importlib.util.spec_from_file_location("_bj_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_script_ignores_gift_pack_freespins(orm, monkeypatch, capsys):
    """构造礼包来源的发放与使用后，对账与周报结果与不含这些数据时一致。"""
    audit = _load_audit_script(monkeypatch)
    add_user(orm, 1, credits=100.0)
    _add_free_spin(1)

    def run() -> str:
        capsys.readouterr()
        audit.audit_counters()
        audit.weekly_report(1)
        return capsys.readouterr().out

    baseline = run()

    _add_free_spin(1, source="gift_pack")
    _add_free_spin(1, source="gift_pack")
    db.add_wheel_spin_record(1, "积分 +50", 50.0, 0.0, source="gift_pack_free")

    assert run() == baseline
    assert "已发放 1 张" in baseline
    assert "免费机会：发放 1 张，已用 0 张" in baseline
