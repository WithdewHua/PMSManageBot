import json
import time

from sqlalchemy import delete, func, select, update

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.badges.models import Badge
from app.domains.gift_pack.models import GiftPack, GiftPackUserState

from . import (
    _GIFT_PACK_PRIVILEGED_CODES_LOCK,
    gift_pack_rewards_require_binding,
)


class _GiftPackRepositoryPart2:
    @staticmethod
    def _persist_privileged_invite_codes(codes: list[str]) -> None:
        """Persist privileged invitation codes before the claim transaction commits.

        The configuration file is not transactional, so callers intentionally invoke
        this only after all database writes for the reward batch have succeeded.  A
        write failure is raised to abort the surrounding database transaction.
        """
        if not codes:
            return
        with _GIFT_PACK_PRIVILEGED_CODES_LOCK:
            original_codes = list(settings.PRIVILEGED_CODES)
            new_codes = original_codes.copy()
            for code in codes:
                if code not in new_codes:
                    new_codes.append(code)
            settings.PRIVILEGED_CODES[:] = new_codes
            try:
                settings.save_config_to_env_file(
                    {"PRIVILEGED_CODES": ",".join(new_codes)},
                    raise_on_error=True,
                )
            except Exception:
                settings.PRIVILEGED_CODES[:] = original_codes
                raise

    @staticmethod
    def _gift_pack_lifecycle(pack: GiftPack, now: int) -> str:
        """礼包相对当前时间的生命周期状态"""
        if now < int(pack.start_at):
            return "upcoming"
        if now > int(pack.end_at):
            return "ended"
        if pack.task_end_at is not None and int(pack.task_end_at) < now:
            return "claim_only"
        return "active"

    @staticmethod
    def _gift_pack_remaining(pack: GiftPack) -> int | None:
        """剩余份数；不限量时返回 None"""
        if pack.total_quantity is None:
            return None
        return max(0, int(pack.total_quantity) - int(pack.claimed_count))

    @staticmethod
    def _gift_pack_conditions_with_binding(
        requirements: list[dict], rewards: list[dict]
    ) -> list[dict]:
        result = list(requirements or [])
        if gift_pack_rewards_require_binding(rewards) and not any(
            item["type"] == "bound" for item in result
        ):
            result.append({"type": "bound", "service": "any"})
        return result

    @staticmethod
    def _gift_pack_audience_size(audience: list[dict]) -> int | None:
        include = [
            set(item["tg_ids"])
            for item in audience
            if item["type"] == "user_list" and item["mode"] == "include"
        ]
        if not include:
            return None
        members = set.intersection(*include)
        for item in audience:
            if item["type"] == "user_list" and item["mode"] == "exclude":
                members.difference_update(item["tg_ids"])
        return len(members)

    @staticmethod
    def _validate_gift_pack_references(
        session,
        audience: list[dict],
        requirements: list[dict],
        pack_id: int | None = None,
    ) -> None:
        def leaves(items):
            for item in items:
                if item["type"] == "any_of":
                    yield from item["items"]
                else:
                    yield item

        for item in leaves(audience + requirements):
            kind = item["type"]
            if kind == "badge" and session.get(Badge, item["badge_id"]) is None:
                raise ValueError(f"引用的勋章不存在: {item['badge_id']}")
            if kind == "claimed_pack":
                if pack_id is not None and item["pack_id"] == pack_id:
                    raise ValueError("礼包不能引用自身作为已领取条件")
                if session.get(GiftPack, item["pack_id"]) is None:
                    raise ValueError(f"引用的礼包不存在: {item['pack_id']}")

    def create_gift_pack(
        self,
        title: str,
        rewards: list[dict],
        start_at: int,
        end_at: int,
        description: str | None = None,
        eligibility: dict | None = None,
        total_quantity: int | None = None,
        max_prompt_count: int = 3,
        is_enabled: bool = True,
        created_by: int | None = None,
        audience: list[dict] | None = None,
        requirements: list[dict] | None = None,
        task_end_at: int | None = None,
        max_task_prompt_count: int = 2,
        notify_audience_on_start: bool = False,
    ) -> int:
        """Create a pack, normalizing legacy eligibility and binding requirements."""
        if not rewards:
            raise ValueError("礼包至少需要一项奖励")
        if end_at <= start_at:
            raise ValueError("结束时间必须晚于开始时间")
        if task_end_at is not None and not start_at < task_end_at <= end_at:
            raise ValueError("任务截止时间必须晚于开始时间且不晚于结束时间")
        if total_quantity is not None and total_quantity <= 0:
            raise ValueError("限量份数必须大于 0")
        audience = list(audience or [])
        if requirements is None and eligibility:
            requirements = self._legacy_gift_pack_requirements(eligibility)
        requirements = self._gift_pack_conditions_with_binding(
            requirements or [], rewards
        )
        if notify_audience_on_start and not any(
            item["type"] == "user_list" and item["mode"] == "include"
            for item in audience
        ):
            raise ValueError("开启开始通知要求受众顶层包含 include 指定名单")
        with get_session() as session:
            self._validate_gift_pack_references(session, audience, requirements)
            now = int(time.time())
            pack = GiftPack(
                title=title,
                description=description,
                rewards=json.dumps(rewards, ensure_ascii=False),
                audience=json.dumps(audience, ensure_ascii=False) if audience else None,
                requirements=json.dumps(requirements, ensure_ascii=False)
                if requirements
                else None,
                eligibility=None,
                total_quantity=total_quantity,
                claimed_count=0,
                start_at=int(start_at),
                end_at=int(end_at),
                task_end_at=task_end_at,
                max_prompt_count=int(max_prompt_count),
                max_task_prompt_count=int(max_task_prompt_count),
                notify_audience_on_start=int(bool(notify_audience_on_start)),
                is_enabled=int(bool(is_enabled)),
                expiry_notified=0,
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
            session.add(pack)
            session.flush()
            return int(pack.id)

    @staticmethod
    def _legacy_gift_pack_requirements(legacy: dict) -> list[dict]:
        result = []
        if legacy.get("min_credits") is not None:
            result.append({"type": "credits", "min": legacy["min_credits"]})
        if legacy.get("require_premium"):
            result.append({"type": "premium", "state": "active"})
        if legacy.get("require_binding"):
            result.append({"type": "bound", "service": legacy["require_binding"]})
        return result

    def update_gift_pack(self, pack_id: int, **fields) -> bool:
        """Merge partial update, enforce post-start monotonicity and references."""
        allowed = {
            "title",
            "description",
            "rewards",
            "audience",
            "requirements",
            "total_quantity",
            "start_at",
            "end_at",
            "task_end_at",
            "max_prompt_count",
            "max_task_prompt_count",
            "notify_audience_on_start",
            "is_enabled",
            "eligibility",
        }
        nullable = {
            "description",
            "audience",
            "requirements",
            "total_quantity",
            "task_end_at",
        }
        fields = {
            key: val
            for key, val in fields.items()
            if key in allowed and (val is not None or key in nullable)
        }
        with get_session() as session:
            pack = session.execute(
                select(GiftPack).where(GiftPack.id == pack_id).with_for_update()
            ).scalar_one_or_none()
            if pack is None:
                raise ValueError("礼包不存在")
            old_audience, old_requirements = self._resolve_gift_pack_conditions(pack)
            old = {
                "start_at": int(pack.start_at),
                "end_at": int(pack.end_at),
                "task_end_at": pack.task_end_at,
                "total_quantity": pack.total_quantity,
                "rewards": json.loads(pack.rewards),
                "audience": old_audience,
                "requirements": old_requirements,
            }
            if "eligibility" in fields and "requirements" not in fields:
                fields["requirements"] = self._legacy_gift_pack_requirements(
                    fields["eligibility"] or {}
                )
            new = {**old, **{k: v for k, v in fields.items() if k in old}}
            if not new["rewards"]:
                raise ValueError("礼包至少需要一项奖励")
            if new["end_at"] <= new["start_at"]:
                raise ValueError("结束时间必须晚于开始时间")
            if new["task_end_at"] is not None and not (
                new["start_at"] < new["task_end_at"] <= new["end_at"]
            ):
                raise ValueError("任务截止时间必须晚于开始时间且不晚于结束时间")
            if new["total_quantity"] is not None and (
                new["total_quantity"] <= 0 or new["total_quantity"] < pack.claimed_count
            ):
                raise ValueError("限量份数不能小于已领取份数且必须大于 0")
            new["audience"] = list(new["audience"] or [])
            new["requirements"] = self._gift_pack_conditions_with_binding(
                new["requirements"] or [], new["rewards"]
            )
            notify = fields.get(
                "notify_audience_on_start", pack.notify_audience_on_start
            )
            if notify and not any(
                item["type"] == "user_list" and item["mode"] == "include"
                for item in new["audience"]
            ):
                raise ValueError("开启开始通知要求受众顶层包含 include 指定名单")
            if int(time.time()) >= int(pack.start_at):
                self._validate_post_start_edit(old, new)
            self._validate_gift_pack_references(
                session, new["audience"], new["requirements"], pack_id
            )
            for key, value in fields.items():
                if key not in old and key != "eligibility":
                    setattr(
                        pack,
                        key,
                        int(bool(value))
                        if key in ("is_enabled", "notify_audience_on_start")
                        else value,
                    )
            for key, value in new.items():
                if key in ("audience", "requirements"):
                    value = json.dumps(value, ensure_ascii=False) if value else None
                elif key == "rewards":
                    value = json.dumps(value, ensure_ascii=False)
                setattr(pack, key, value)
            pack.eligibility = None
            pack.updated_at = int(time.time())
            return True

    def set_gift_pack_enabled(self, pack_id: int, is_enabled: bool) -> bool:
        """启用 / 停用礼包"""
        try:
            with get_session() as session:
                result = session.execute(
                    update(GiftPack)
                    .where(GiftPack.id == pack_id)
                    .values(
                        is_enabled=1 if is_enabled else 0, updated_at=int(time.time())
                    )
                )
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"更新礼包启用状态失败 (pack_id={pack_id}): {e}")
            return False

    def delete_gift_pack(self, pack_id: int) -> bool:
        """删除礼包；已有领取记录时拒绝删除，只能停用"""
        with get_session() as session:
            pack = (
                session.execute(select(GiftPack).where(GiftPack.id == pack_id))
                .scalars()
                .one_or_none()
            )
            if not pack:
                raise ValueError("礼包不存在")

            claimed = session.execute(
                select(func.count(GiftPackUserState.id)).where(
                    GiftPackUserState.pack_id == pack_id,
                    GiftPackUserState.claimed_at.isnot(None),
                )
            ).scalar_one()
            if int(claimed) > 0 or int(pack.claimed_count) > 0:
                raise ValueError("该礼包已有用户领取，只能停用不能删除")

            references = self._gift_pack_referencing_packs(session, pack_id)
            if references:
                names = "、".join(f"#{pid} {title}" for pid, title in references)
                raise ValueError(
                    f"该礼包被其他礼包的已领取条件引用：{names}；请先移除引用"
                )

            # 仅被提醒过、从未领取的状态行随礼包一并清理
            session.execute(
                delete(GiftPackUserState).where(GiftPackUserState.pack_id == pack_id)
            )
            session.delete(pack)
            return True

    def _gift_pack_admin_payload(self, session, pack: GiftPack, now: int) -> dict:
        audience, requirements = self._resolve_gift_pack_conditions(pack)
        size = self._gift_pack_audience_size(audience)
        prompted = session.execute(
            select(func.count(GiftPackUserState.id)).where(
                GiftPackUserState.pack_id == pack.id,
                GiftPackUserState.task_prompt_count > 0,
            )
        ).scalar_one()
        claimed_users = session.execute(
            select(func.count(GiftPackUserState.id)).where(
                GiftPackUserState.pack_id == pack.id,
                GiftPackUserState.claimed_at.is_not(None),
            )
        ).scalar_one()
        dependents = self._gift_pack_referencing_packs(session, pack.id)
        return {
            "id": int(pack.id),
            "title": pack.title,
            "description": pack.description,
            "rewards": json.loads(pack.rewards),
            "audience": audience or None,
            "requirements": requirements or None,
            "audience_summary": self._gift_pack_condition_summary(audience),
            "requirements_summary": self._gift_pack_condition_summary(requirements),
            "audience_size": size,
            "claim_rate": round(int(claimed_users) / size * 100, 2) if size else None,
            "task_prompted_users": int(prompted),
            "total_quantity": pack.total_quantity,
            "claimed_count": int(pack.claimed_count),
            "remaining": self._gift_pack_remaining(pack),
            "start_at": int(pack.start_at),
            "end_at": int(pack.end_at),
            "task_end_at": pack.task_end_at,
            "max_prompt_count": int(pack.max_prompt_count),
            "max_task_prompt_count": int(pack.max_task_prompt_count),
            "notify_audience_on_start": bool(pack.notify_audience_on_start),
            "is_enabled": bool(pack.is_enabled),
            "lifecycle": self._gift_pack_lifecycle(pack, now),
            "can_delete": int(pack.claimed_count) == 0
            and int(claimed_users) == 0
            and not dependents,
            "created_by": pack.created_by,
            "created_at": int(pack.created_at),
            "updated_at": int(pack.updated_at),
        }

    def get_gift_pack_by_id(self, pack_id: int) -> dict | None:
        try:
            with get_session() as session:
                pack = session.get(GiftPack, pack_id)
                return (
                    self._gift_pack_admin_payload(session, pack, int(time.time()))
                    if pack
                    else None
                )
        except Exception as e:
            logger.error(f"获取礼包失败 (pack_id={pack_id}): {e}")
            return None

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
                from app.domains.premium.service import sync_media_permission

                sync_media_permission(self, tg_id, service)
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
