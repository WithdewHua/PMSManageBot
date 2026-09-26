import json
import time

from sqlalchemy import func, select, update

from app.core.db import get_session
from app.core.log import logger
from app.domains.gift_pack.models import GiftPack, GiftPackUserState
from app.domains.identity.models import EmbyUser, PlexUser, Statistics

from . import (
    GIFT_PACK_REWARD_TYPES,
)


class _GiftPackRepositoryPart3:
    def prompt_check_gift_packs(self, tg_id: int) -> dict:
        """POST reminder check: lock audience, then throttle each reminder class separately."""
        empty = {"packs": [], "task_packs": []}
        try:
            with get_session() as session:
                now = int(time.time())
                packs = (
                    session.execute(
                        select(GiftPack).where(
                            GiftPack.is_enabled == 1,
                            GiftPack.start_at <= now,
                            GiftPack.end_at >= now,
                        )
                    )
                    .scalars()
                    .all()
                )
                # The no-active-pack path must not query the user or write state.
                if not packs:
                    return empty
                ctx = self._load_gift_pack_user_context(session, tg_id)
                if not ctx["has_stats"]:
                    return empty
                states = {
                    state.pack_id: state
                    for state in session.execute(
                        select(GiftPackUserState).where(
                            GiftPackUserState.tg_id == tg_id,
                            GiftPackUserState.pack_id.in_([p.id for p in packs]),
                        )
                    ).scalars()
                }
                today = self._gift_pack_local_date(now)
                claimable, tasks = [], []
                for pack in packs:
                    state = states.get(pack.id)
                    if state is not None and state.claimed_at is not None:
                        continue
                    # Lock even when sold out or both reminder quotas are exhausted.
                    if not self._lock_gift_pack_audience(
                        session, pack, tg_id, ctx, now, state
                    ):
                        continue
                    if state is None:
                        # _lock_gift_pack_audience inserted this row; autoflush
                        # before selecting it in the same session.
                        session.flush()
                        state = session.execute(
                            select(GiftPackUserState).where(
                                GiftPackUserState.pack_id == pack.id,
                                GiftPackUserState.tg_id == tg_id,
                            )
                        ).scalar_one()
                        states[pack.id] = state
                    remaining = self._gift_pack_remaining(pack)
                    if remaining is not None and remaining <= 0:
                        continue
                    _, requirements = self._resolve_gift_pack_conditions(pack)
                    met, progress = self._evaluate_conditions(
                        requirements, ctx, pack, self._gift_pack_phase_ref(pack, now)
                    )
                    if met:
                        count_field, time_field = "prompt_count", "last_prompted_at"
                        maximum, destination = int(pack.max_prompt_count), claimable
                    else:
                        if self._gift_pack_lifecycle(pack, now) != "active":
                            continue
                        count_field, time_field = (
                            "task_prompt_count",
                            "last_task_prompted_at",
                        )
                        maximum, destination = int(pack.max_task_prompt_count), tasks
                    last = getattr(state, time_field)
                    if int(getattr(state, count_field) or 0) >= maximum or (
                        last is not None and self._gift_pack_local_date(last) == today
                    ):
                        continue
                    setattr(
                        state, count_field, int(getattr(state, count_field) or 0) + 1
                    )
                    setattr(state, time_field, now)
                    rewards = json.loads(pack.rewards)
                    item = {
                        "id": int(pack.id),
                        "title": pack.title,
                        "description": pack.description,
                        "rewards": [
                            {
                                **{
                                    key: r.get(key)
                                    for key in (
                                        "type",
                                        "amount",
                                        "days",
                                        "count",
                                        "expiry_days",
                                        "privileged",
                                    )
                                },
                                "label": self._gift_pack_reward_label(r),
                            }
                            for r in rewards
                        ],
                        "end_at": int(pack.end_at),
                        "total_quantity": pack.total_quantity,
                        "remaining": remaining,
                    }
                    if not met:
                        item["requirements"] = progress
                    destination.append(item)
                return {"packs": claimable, "task_packs": tasks}
        except Exception as e:
            logger.error(f"礼包提醒判定失败 (tg_id={tg_id}): {e}")
            return empty

    def get_gift_packs_admin(
        self, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict], int]:
        """Admin list with condition summaries and audience conversion rates."""
        try:
            with get_session() as session:
                now = int(time.time())
                total = session.execute(select(func.count(GiftPack.id))).scalar_one()
                packs = (
                    session.execute(
                        select(GiftPack)
                        .order_by(GiftPack.created_at.desc())
                        .offset(max(0, (page - 1) * page_size))
                        .limit(page_size)
                    )
                    .scalars()
                    .all()
                )
                return [
                    self._gift_pack_admin_payload(session, p, now) for p in packs
                ], int(total)
        except Exception as e:
            logger.error(f"获取礼包管理列表失败: {e}")
            return [], 0

    def get_gift_pack_stats(self, pack_id: int) -> dict | None:
        """单个礼包的领取统计：领取人数、被提醒人数、各类奖励发放总量"""
        try:
            with get_session() as session:
                pack = (
                    session.execute(select(GiftPack).where(GiftPack.id == pack_id))
                    .scalars()
                    .one_or_none()
                )
                if not pack:
                    return None

                claimed_users = session.execute(
                    select(func.count(GiftPackUserState.id)).where(
                        GiftPackUserState.pack_id == pack_id,
                        GiftPackUserState.claimed_at.isnot(None),
                    )
                ).scalar_one()
                prompted_users = session.execute(
                    select(func.count(GiftPackUserState.id)).where(
                        GiftPackUserState.pack_id == pack_id,
                        GiftPackUserState.prompt_count > 0,
                    )
                ).scalar_one()

                task_prompted_users = session.execute(
                    select(func.count(GiftPackUserState.id)).where(
                        GiftPackUserState.pack_id == pack_id,
                        GiftPackUserState.task_prompt_count > 0,
                    )
                ).scalar_one()
                audience, _ = self._resolve_gift_pack_conditions(pack)
                audience_size = self._gift_pack_audience_size(audience)

                # reward_snapshot 是 JSON 文本，聚合只能在 Python 侧做
                snapshots = [
                    row
                    for (row,) in session.execute(
                        select(GiftPackUserState.reward_snapshot).where(
                            GiftPackUserState.pack_id == pack_id,
                            GiftPackUserState.reward_snapshot.isnot(None),
                        )
                    ).all()
                ]
                aggregates: dict[str, dict] = {}
                for raw in snapshots:
                    try:
                        items = json.loads(raw)
                        for item in items:
                            reward_type = item.get("type")
                            meta = GIFT_PACK_REWARD_TYPES.get(reward_type)
                            if meta is None:
                                continue
                            entry = aggregates.setdefault(
                                reward_type,
                                {
                                    "type": reward_type,
                                    "label": meta["stat_label"],
                                    "total": 0,
                                    "grants": 0,
                                    "skipped": 0,
                                },
                            )
                            if item.get("skipped"):
                                entry["skipped"] += 1
                                continue
                            field = meta["stat_field"]
                            entry["total"] += (
                                float(item.get(field) or 0) if field else 1
                            )
                            entry["grants"] += 1
                    except (ValueError, TypeError) as e:
                        logger.warning(f"解析礼包发放快照失败 (pack_id={pack_id}): {e}")

                reward_totals = []
                for reward_type, meta in GIFT_PACK_REWARD_TYPES.items():
                    entry = aggregates.get(reward_type)
                    if entry is None:
                        continue
                    entry["total"] = round(entry["total"], 2)
                    if meta["skipped_label"]:
                        entry["skipped_label"] = meta["skipped_label"]
                    if reward_type == "premium_days":
                        entry["skipped_lifetime"] = entry["skipped"]
                    reward_totals.append(entry)

                return {
                    "pack_id": int(pack.id),
                    "title": pack.title,
                    "claimed_users": int(claimed_users),
                    "prompted_users": int(prompted_users),
                    "task_prompted_users": int(task_prompted_users),
                    "audience_size": audience_size,
                    "claim_rate": round(int(claimed_users) / audience_size * 100, 2)
                    if audience_size
                    else None,
                    "total_quantity": pack.total_quantity,
                    "remaining": self._gift_pack_remaining(pack),
                    "reward_totals": reward_totals,
                }
        except Exception as e:
            logger.error(f"获取礼包统计失败 (pack_id={pack_id}): {e}")
            return None

    def resolve_gift_pack_users(self, text: str) -> dict:
        """Resolve mixed Telegram IDs and media usernames; never guess ambiguity."""
        import re

        from app.core.telegram import load_tg_user_info_cache

        tokens = list(dict.fromkeys(t for t in re.split(r"[\s,，]+", text) if t))
        resolved, unresolved = [], []
        with get_session() as session:
            tg_cache = load_tg_user_info_cache()
            for token in tokens:
                matches: dict[int, tuple[str, str]] = {}
                if token.isdecimal():
                    tg_id = int(token)
                    if session.get(Statistics, tg_id) is not None:
                        matches[tg_id] = ("tg_id", str(tg_id))
                if not matches:
                    for tg_id, username, email in session.execute(
                        select(
                            PlexUser.tg_id, PlexUser.plex_username, PlexUser.plex_email
                        ).where(
                            (func.lower(PlexUser.plex_username) == token.lower())
                            | (func.lower(PlexUser.plex_email) == token.lower())
                        )
                    ):
                        if tg_id is not None:
                            matches[int(tg_id)] = ("plex", username or email or token)
                    for tg_id, username in session.execute(
                        select(EmbyUser.tg_id, EmbyUser.emby_username).where(
                            func.lower(EmbyUser.emby_username) == token.lower()
                        )
                    ):
                        if tg_id is not None:
                            matches[int(tg_id)] = ("emby", username)
                if token.startswith("@") and not matches:
                    for tg_id, data in tg_cache.items():
                        if str(data.get("username") or "").lower() == token[1:].lower():
                            matches[int(tg_id)] = (
                                "telegram_cache",
                                data.get("first_name") or token,
                            )
                if len(matches) == 1:
                    tg_id, (by, name) = next(iter(matches.items()))
                    resolved.append(
                        {
                            "token": token,
                            "tg_id": tg_id,
                            "matched_by": by,
                            "display_name": name,
                        }
                    )
                else:
                    unresolved.append(
                        {
                            "token": token,
                            "reason": "匹配到多个 Telegram 用户"
                            if matches
                            else "未找到对应的 Telegram 用户",
                        }
                    )
        return {"resolved": resolved, "unresolved": unresolved}

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
                if self._gift_pack_lifecycle(pack, now) != "active":
                    continue
                audience, requirements = self._resolve_gift_pack_conditions(pack)
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
                    if not ctx["has_stats"] or not self._evaluate_gift_pack_audience(
                        audience, ctx, pack, self._gift_pack_phase_ref(pack, now), None
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
                            "requirements_summary": self._gift_pack_condition_summary(
                                requirements
                            ),
                            "end_at": int(pack.end_at),
                        }
                    )
        return result

    def get_gift_pack_claim_records(
        self, pack_id: int, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict], int]:
        """某礼包的领取记录（按领取时间倒序分页）"""
        try:
            with get_session() as session:
                total = session.execute(
                    select(func.count(GiftPackUserState.id)).where(
                        GiftPackUserState.pack_id == pack_id,
                        GiftPackUserState.claimed_at.isnot(None),
                    )
                ).scalar_one()
                rows = (
                    session.execute(
                        select(GiftPackUserState)
                        .where(
                            GiftPackUserState.pack_id == pack_id,
                            GiftPackUserState.claimed_at.isnot(None),
                        )
                        .order_by(GiftPackUserState.claimed_at.desc())
                        .offset(max(0, (page - 1) * page_size))
                        .limit(page_size)
                    )
                    .scalars()
                    .all()
                )
                records = [
                    {
                        "tg_id": int(row.tg_id),
                        "claimed_at": int(row.claimed_at),
                        "reward_snapshot": json.loads(row.reward_snapshot)
                        if row.reward_snapshot
                        else None,
                    }
                    for row in rows
                ]
                return records, int(total)
        except Exception as e:
            logger.error(f"获取礼包领取记录失败 (pack_id={pack_id}): {e}")
            return [], 0

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
