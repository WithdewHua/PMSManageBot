"""礼包 repository：开始私信的认领、过期扫描与标记（由 part_1–part_3 与门面机械拆分）。"""

import json
import time

from sqlalchemy import select, update

from app.core.db import get_session
from app.core.log import logger
from app.domains.gift_pack import rules
from app.domains.gift_pack.models import GiftPack, GiftPackUserState


class _GiftPackRepositoryNotices:
    def claim_gift_pack_start_dm_candidates(self, limit: int = 200) -> list[dict]:
        """Reserve active named-pack DMs before returning them to the sender."""
        if limit <= 0:
            return []
        now = int(time.time())
        result = []
        with get_session() as session:
            packs = (
                session.execute(
                    select(GiftPack)
                    .where(
                        GiftPack.is_enabled == 1,
                        GiftPack.notify_audience_on_start == 1,
                        GiftPack.start_at <= now,
                        GiftPack.end_at >= now,
                    )
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            for pack in packs:
                if rules._gift_pack_lifecycle(pack, now) != "active":
                    continue
                audience, requirements = rules._resolve_gift_pack_conditions(pack)
                includes = [
                    set(item["tg_ids"])
                    for item in audience
                    if item["type"] == "user_list" and item["mode"] == "include"
                ]
                if not includes:
                    continue
                for tg_id in sorted(set.intersection(*includes)):
                    if len(result) >= limit:
                        return result
                    state = session.execute(
                        select(GiftPackUserState)
                        .where(
                            GiftPackUserState.pack_id == pack.id,
                            GiftPackUserState.tg_id == tg_id,
                        )
                        .with_for_update()
                    ).scalar_one_or_none()
                    if state is not None and (
                        state.claimed_at is not None
                        or state.start_dm_sent_at is not None
                    ):
                        continue
                    ctx = self._load_gift_pack_user_context(session, tg_id)
                    ref = rules._gift_pack_phase_ref(pack, now)
                    metrics = self._gift_pack_metrics(
                        session, tg_id, audience, pack, ref
                    )
                    if not ctx["has_stats"] or not rules._evaluate_gift_pack_audience(
                        audience, ctx, pack, ref, None, metrics=metrics
                    ):
                        continue
                    if state is None:
                        state = GiftPackUserState(pack_id=pack.id, tg_id=tg_id)
                        session.add(state)
                    state.start_dm_sent_at = now
                    result.append(
                        {
                            "pack_id": int(pack.id),
                            "tg_id": int(tg_id),
                            "title": pack.title,
                            "rewards": json.loads(pack.rewards),
                            "requirements_summary": rules._gift_pack_condition_summary(
                                requirements
                            ),
                            "end_at": int(pack.end_at),
                        }
                    )
        return result

    def get_expired_unnotified_gift_packs(self) -> list[dict]:
        """扫描已过期且尚未发送汇总通知的礼包

        配合 mark_gift_pack_expiry_notified() 使用。用周期扫描而非 date job：
        end_at 是管理员可编辑的，date job 每次改期都要重排、漏排就永久丢通知。
        """
        try:
            now = int(time.time())
            with get_session() as session:
                packs = (
                    session.execute(
                        select(GiftPack).where(
                            GiftPack.end_at < now,
                            GiftPack.expiry_notified == 0,
                        )
                    )
                    .scalars()
                    .all()
                )
                return [
                    {
                        "id": int(pack.id),
                        "title": pack.title,
                        "total_quantity": pack.total_quantity,
                        "claimed_count": int(pack.claimed_count),
                        "end_at": int(pack.end_at),
                    }
                    for pack in packs
                ]
        except Exception as e:
            logger.error(f"扫描过期礼包失败: {e}")
            return []

    def mark_gift_pack_expiry_notified(self, pack_id: int) -> bool:
        """标记某礼包的过期汇总通知已发送"""
        try:
            with get_session() as session:
                result = session.execute(
                    update(GiftPack)
                    .where(GiftPack.id == pack_id, GiftPack.expiry_notified == 0)
                    .values(expiry_notified=1)
                )
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"标记礼包过期通知失败 (pack_id={pack_id}): {e}")
            return False
