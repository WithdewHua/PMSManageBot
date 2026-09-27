"""礼包后台任务：过期汇总扫描的行为。

领取与开始私信的路径见 test_gift_pack_audience.py；本文件只覆盖
`scan_expired_gift_packs` 的发送内容、置位与失败重试语义。
"""

from __future__ import annotations

import json
import time

from sqlalchemy import event

from app.core.db import get_session
from app.domains.gift_pack import jobs as gift_pack_jobs
from app.domains.gift_pack.models import GiftPack, GiftPackUserState
from tests.conftest import add_user, next_id


def _assign_bigint_id(mapper, connection, target) -> None:
    if target.id is None:
        target.id = next_id()


for _model in (GiftPack, GiftPackUserState):
    event.listen(_model, "before_insert", _assign_bigint_id)


def _pack_with_claim(orm, *, total_quantity: int | None = None) -> int:
    """建一个可领取的礼包、领取一次，再把结束时间挪到过去。"""
    now = int(time.time())
    pack_id = orm.create_gift_pack(
        "过期礼包",
        [{"type": "credits", "amount": 5}],
        now - 3600,
        now + 3600,
        total_quantity=total_quantity,
    )
    add_user(orm, 1)
    orm.claim_gift_pack(pack_id, 1)
    with get_session() as session:
        pack = session.get(GiftPack, pack_id)
        assert pack is not None
        pack.end_at = now - 60
    return pack_id


def _expiry_notified(pack_id: int) -> int:
    with get_session() as session:
        pack = session.get(GiftPack, pack_id)
        assert pack is not None
        return int(pack.expiry_notified or 0)


async def test_scan_sends_summary_once_and_marks_expiry(orm, monkeypatch):
    add_user(orm, 2)
    pack_id = _pack_with_claim(orm, total_quantity=5)

    messages: list[tuple[str, dict]] = []

    async def _notify(text, **kwargs):
        messages.append((text, kwargs))

    monkeypatch.setattr(gift_pack_jobs, "db", orm)
    monkeypatch.setattr(gift_pack_jobs, "notify_admins_by_url", _notify)

    await gift_pack_jobs.scan_expired_gift_packs()

    assert len(messages) == 1
    text, kwargs = messages[0]
    assert "礼包已结束 · 领取汇总" in text
    assert "过期礼包" in text
    assert "1 / 5 份" in text
    assert "积分" in text
    assert kwargs == {"parse_mode": "HTML"}
    assert _expiry_notified(pack_id) == 1

    # 已置位：第二轮不再发送
    await gift_pack_jobs.scan_expired_gift_packs()
    assert len(messages) == 1


async def test_scan_leaves_pack_unnotified_when_sending_fails(orm, monkeypatch):
    pack_id = _pack_with_claim(orm)

    async def _boom(*args, **kwargs):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(gift_pack_jobs, "db", orm)
    monkeypatch.setattr(gift_pack_jobs, "notify_admins_by_url", _boom)

    await gift_pack_jobs.scan_expired_gift_packs()

    # 通知失败不置位，下一轮重试
    assert _expiry_notified(pack_id) == 0


async def test_scan_reports_unlimited_quantity_wording(orm, monkeypatch):
    _pack_with_claim(orm)

    messages: list[str] = []

    async def _notify(text, **kwargs):
        messages.append(text)

    monkeypatch.setattr(gift_pack_jobs, "db", orm)
    monkeypatch.setattr(gift_pack_jobs, "notify_admins_by_url", _notify)

    await gift_pack_jobs.scan_expired_gift_packs()

    assert len(messages) == 1
    assert "1 人（不限量）" in messages[0]
    assert json.dumps(messages[0], ensure_ascii=False)  # 可序列化，便于日志排查
