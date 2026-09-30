"""礼包 repository：用户列表、开屏提醒与领取（由 part_1–part_3 与门面机械拆分）。"""

import json
import time

from sqlalchemy import select

from app.core.db import get_session
from app.core.log import logger
from app.domains.gift_pack import rules
from app.domains.gift_pack.exceptions import ConditionsNotMet, gift_pack_error
from app.domains.gift_pack.models import GiftPack, GiftPackUserState


class _GiftPackRepositoryClaims:
    def get_gift_packs_for_user(self, tg_id: int) -> list[dict]:
        """Read-only listing; claimed packs remain visible even after audience changes."""
        try:
            with get_session() as session:
                now = int(time.time())
                claimed_ids = set(
                    session.execute(
                        select(GiftPackUserState.pack_id).where(
                            GiftPackUserState.tg_id == tg_id,
                            GiftPackUserState.claimed_at.is_not(None),
                        )
                    ).scalars()
                )
                condition = GiftPack.is_enabled == 1
                if claimed_ids:
                    condition = condition | GiftPack.id.in_(claimed_ids)
                packs = (
                    session.execute(select(GiftPack).where(condition)).scalars().all()
                )
                if not packs:
                    return []
                states = {
                    state.pack_id: state
                    for state in session.execute(
                        select(GiftPackUserState).where(
                            GiftPackUserState.tg_id == tg_id,
                            GiftPackUserState.pack_id.in_([p.id for p in packs]),
                        )
                    ).scalars()
                }
                ctx = self._load_gift_pack_user_context(session, tg_id)
                result = []
                for pack in packs:
                    state = states.get(pack.id)
                    claimed = state is not None and state.claimed_at is not None
                    audience, requirements = rules._resolve_gift_pack_conditions(pack)
                    lifecycle = rules._gift_pack_lifecycle(pack, now)
                    ref = rules._gift_pack_phase_ref(pack, now)
                    metrics = self._gift_pack_metrics(
                        session, tg_id, audience, pack, ref
                    )
                    if not claimed and not rules._evaluate_gift_pack_audience(
                        audience, ctx, pack, ref, state, metrics=metrics
                    ):
                        continue
                    remaining = rules._gift_pack_remaining(pack)
                    self._gift_pack_metrics(
                        session, tg_id, requirements, pack, ref, metrics=metrics
                    )
                    met, progress = rules._evaluate_conditions(
                        requirements, ctx, pack, ref, metrics=metrics
                    )
                    status = rules.gift_pack_status(
                        claimed=claimed,
                        is_enabled=bool(pack.is_enabled),
                        lifecycle=lifecycle,
                        remaining=remaining,
                        requirements_met=met,
                    )
                    result.append(
                        {
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
                                    "label": rules._gift_pack_reward_label(r),
                                }
                                for r in json.loads(pack.rewards)
                            ],
                            "start_at": int(pack.start_at),
                            "end_at": int(pack.end_at),
                            "task_end_at": pack.task_end_at,
                            "total_quantity": pack.total_quantity,
                            "claimed_count": int(pack.claimed_count),
                            "remaining": remaining,
                            "lifecycle": lifecycle,
                            "status": status,
                            "requirements": progress,
                            "task_closed": lifecycle == "claim_only",
                            "claimed_at": int(state.claimed_at) if claimed else None,
                            "reward_snapshot": json.loads(state.reward_snapshot)
                            if state is not None and state.reward_snapshot
                            else None,
                        }
                    )
                result.sort(key=rules.gift_pack_sort_key)
                return result
        except Exception as e:
            logger.error(f"获取用户礼包列表失败 (tg_id={tg_id}): {e}")
            return []

    def claim_gift_pack(self, pack_id: int, tg_id: int) -> dict:
        """领取礼包

        单事务内完成：锁 pack 行 → 校验启用/窗口/余量/资格/未领取 →
        发放全部奖励 → claimed_count += 1 → upsert user_state。
        任一步失败整体回滚，不扣余量、不记领取、不发奖励。
        UniqueConstraint(pack_id, tg_id) 是并发重复提交的最后一道防线。

        媒体服务器权限同步是不可回滚的外部副作用，放到事务提交之后执行。
        """
        now = int(time.time())
        with get_session() as session:
            pack = (
                session.execute(
                    select(GiftPack).where(GiftPack.id == pack_id).with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if not pack:
                raise gift_pack_error("礼包不存在")
            # Audience is checked before exposing status, window, or inventory.
            state = session.execute(
                select(GiftPackUserState)
                .where(
                    GiftPackUserState.pack_id == pack_id,
                    GiftPackUserState.tg_id == tg_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            context = self._load_gift_pack_user_context(session, tg_id)
            audience, requirements = rules._resolve_gift_pack_conditions(pack)
            ref = rules._gift_pack_phase_ref(pack, now)
            metrics = self._gift_pack_metrics(session, tg_id, audience, pack, ref)
            if not rules._evaluate_gift_pack_audience(
                audience, context, pack, ref, state, metrics=metrics
            ):
                # 受众不符时不暴露礼包状态、时间窗与余量
                raise gift_pack_error("礼包不存在")
            if not pack.is_enabled:
                raise gift_pack_error("礼包已停用")
            if now < int(pack.start_at):
                raise gift_pack_error("礼包尚未开始")
            if now > int(pack.end_at):
                raise gift_pack_error("礼包已结束")

            total_quantity = pack.total_quantity
            if total_quantity is not None and int(pack.claimed_count) >= int(
                total_quantity
            ):
                raise gift_pack_error("礼包已被领完")

            if state is not None and state.claimed_at is not None:
                raise gift_pack_error("你已领取过该礼包")
            if not context["has_stats"]:
                raise gift_pack_error("用户积分信息不存在")
            self._gift_pack_metrics(
                session, tg_id, requirements, pack, ref, metrics=metrics
            )
            eligible, progress = rules._evaluate_conditions(
                requirements, context, pack, ref, metrics=metrics
            )
            if not eligible:
                # Include both the human-readable progress and its structure in the
                # business error; the claim route currently exposes only detail text.
                raise ConditionsNotMet(progress)

            rewards = json.loads(pack.rewards)
            # 固定加锁顺序：先 statistics，再 plex_user / emby_user
            self._prelock_gift_pack_reward_rows_tx(session, tg_id, rewards)
            (
                snapshot,
                pending_permission_sync,
                pending_download_sync,
                _pending_privileged_codes,
            ) = self._grant_gift_pack_rewards(session, tg_id, rewards, context)

            pack.claimed_count = int(pack.claimed_count) + 1
            snapshot_json = json.dumps(snapshot, ensure_ascii=False)
            if state is not None:
                state.claimed_at = now
                state.reward_snapshot = snapshot_json
            else:
                session.add(
                    GiftPackUserState(
                        pack_id=pack_id,
                        tg_id=tg_id,
                        claimed_at=now,
                        reward_snapshot=snapshot_json,
                        prompt_count=0,
                    )
                )

            claimed_count = int(pack.claimed_count)
            remaining = rules._gift_pack_remaining(pack)
            pack_title = pack.title

        result = {
            "success": True,
            "pack_id": int(pack_id),
            "title": pack_title,
            "results": snapshot,
            "claimed_count": claimed_count,
            "remaining": remaining,
            "total_quantity": total_quantity,
            "sold_out": total_quantity is not None
            and claimed_count >= int(total_quantity),
            "download_sync_failed": [],
        }
        # 媒体权限同步属于提交后的副作用，由 service 执行（design D7）
        return result, pending_permission_sync, pending_download_sync

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
                today = rules._gift_pack_local_date(now)
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
                    remaining = rules._gift_pack_remaining(pack)
                    if remaining is not None and remaining <= 0:
                        continue
                    _, requirements = rules._resolve_gift_pack_conditions(pack)
                    ref = rules._gift_pack_phase_ref(pack, now)
                    metrics = self._gift_pack_metrics(
                        session, tg_id, requirements, pack, ref
                    )
                    met, progress = rules._evaluate_conditions(
                        requirements, ctx, pack, ref, metrics=metrics
                    )
                    if met:
                        count_field, time_field = "prompt_count", "last_prompted_at"
                        maximum, destination = int(pack.max_prompt_count), claimable
                    else:
                        if rules._gift_pack_lifecycle(pack, now) != "active":
                            continue
                        count_field, time_field = (
                            "task_prompt_count",
                            "last_task_prompted_at",
                        )
                        maximum, destination = int(pack.max_task_prompt_count), tasks
                    last = getattr(state, time_field)
                    if not rules.reminder_allowed(
                        count=int(getattr(state, count_field) or 0),
                        maximum=maximum,
                        last_prompt_date=(
                            rules._gift_pack_local_date(last)
                            if last is not None
                            else None
                        ),
                        today=today,
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
                                "label": rules._gift_pack_reward_label(r),
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
