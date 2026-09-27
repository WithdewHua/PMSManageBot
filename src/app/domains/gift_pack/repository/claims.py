"""礼包 repository：用户列表、开屏提醒与领取（由 part_1–part_3 与门面机械拆分）。"""

import json
import time

from sqlalchemy import select

from app.core.db import get_session
from app.core.log import logger
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
                    audience, requirements = self._resolve_gift_pack_conditions(pack)
                    lifecycle = self._gift_pack_lifecycle(pack, now)
                    ref = self._gift_pack_phase_ref(pack, now)
                    if not claimed and not self._evaluate_gift_pack_audience(
                        audience, ctx, pack, ref, state
                    ):
                        continue
                    remaining = self._gift_pack_remaining(pack)
                    met, progress = self._evaluate_conditions(
                        requirements, ctx, pack, ref
                    )
                    if claimed:
                        status = "claimed"
                    elif not pack.is_enabled:
                        status = "disabled"
                    elif lifecycle == "upcoming":
                        status = "upcoming"
                    elif lifecycle == "ended":
                        status = "ended"
                    elif remaining is not None and remaining <= 0:
                        status = "sold_out"
                    else:
                        status = "claimable" if met else "in_progress"
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
                                    "label": self._gift_pack_reward_label(r),
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
                order = {"active": 0, "claim_only": 0, "upcoming": 1, "ended": 2}
                result.sort(key=lambda x: (order.get(x["lifecycle"], 3), x["end_at"]))
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
                raise ValueError("礼包不存在")
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
            audience, requirements = self._resolve_gift_pack_conditions(pack)
            ref = self._gift_pack_phase_ref(pack, now)
            if not self._evaluate_gift_pack_audience(
                audience, context, pack, ref, state
            ):
                raise ValueError("礼包不存在")
            if not pack.is_enabled:
                raise ValueError("礼包已停用")
            if now < int(pack.start_at):
                raise ValueError("礼包尚未开始")
            if now > int(pack.end_at):
                raise ValueError("礼包已结束")

            total_quantity = pack.total_quantity
            if total_quantity is not None and int(pack.claimed_count) >= int(
                total_quantity
            ):
                raise ValueError("礼包已被领完")

            if state is not None and state.claimed_at is not None:
                raise ValueError("你已领取过该礼包")
            if not context["has_stats"]:
                raise ValueError("用户积分信息不存在")
            eligible, progress = self._evaluate_conditions(
                requirements, context, pack, ref
            )
            if not eligible:
                # Include both the human-readable progress and its structure in the
                # business error; the claim route currently exposes only detail text.
                raise ValueError(
                    f"不满足领取条件；当前进度：{json.dumps(progress, ensure_ascii=False)}"
                )

            rewards = json.loads(pack.rewards)
            (
                snapshot,
                pending_permission_sync,
                pending_download_sync,
                pending_privileged_codes,
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

            # 所有数据库行已写入且 flush 成功后，才在提交前写特权码配置；
            # 写入失败抛异常，get_session 回滚积分、邀请码及领取记录。
            if pending_privileged_codes:
                session.flush()
                self._persist_privileged_invite_codes(pending_privileged_codes)

            claimed_count = int(pack.claimed_count)
            remaining = self._gift_pack_remaining(pack)
            pack_title = pack.title

        # 事务已提交：把下载权限解锁同步到媒体服务器。失败不回滚领取——数据库
        # 已记为解锁、是权威状态；在响应条目中说明，并由调用方通知管理员人工处理。
        # 已持久化的发放快照记录的是数据库状态，不受这里的说明影响
        download_sync_failed: list[dict] = []
        for service in pending_download_sync:
            try:
                from app.domains.premium.service import apply_download_unlock_to_media

                apply_download_unlock_to_media(tg_id, service)
            except Exception as e:
                logger.error(
                    f"礼包下载权限解锁同步 {service} 失败 (pack_id={pack_id}, tg_id={tg_id}): {e}"
                )
                download_sync_failed.append({"service": service, "error": str(e)})
                for item in snapshot:
                    if (
                        item.get("type") == "download_unlock"
                        and item.get("service") == service
                    ):
                        item["message"] = (
                            f"{service.capitalize()} 已解锁下载权限，但同步到媒体服务器"
                            "未完成，管理员将尽快人工处理"
                        )

        # 事务已提交：同步媒体服务器权限（best-effort，失败只告警不影响领取结果）
        for service in pending_permission_sync:
            try:
                from app.domains.premium import service as premium_service

                premium_service.sync_premium_media_access(tg_id, (service,))
            except Exception as e:
                logger.warning(
                    f"礼包领取后同步 {service} 权限失败 (pack_id={pack_id}, tg_id={tg_id}): {e}"
                )

        return {
            "success": True,
            "pack_id": int(pack_id),
            "title": pack_title,
            "results": snapshot,
            "claimed_count": claimed_count,
            "remaining": remaining,
            "total_quantity": total_quantity,
            "sold_out": total_quantity is not None
            and claimed_count >= int(total_quantity),
            "download_sync_failed": download_sync_failed,
        }

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
