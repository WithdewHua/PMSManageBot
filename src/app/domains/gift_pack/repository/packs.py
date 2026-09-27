"""礼包 repository：定义的增删改、引用校验、管理端列表、统计与领取记录（由 part_1–part_3 与门面机械拆分）。"""

import json
import time

from sqlalchemy import delete, func, select, update

from app.core.db import get_session
from app.core.log import logger
from app.domains.badges.models import Badge
from app.domains.gift_pack.models import GiftPack, GiftPackUserState
from app.domains.identity.models import EmbyUser, PlexUser, Statistics

from . import GIFT_PACK_REWARD_TYPES
from .conditions import _GiftPackRepositoryConditions


class _GiftPackRepositoryPacks:
    @staticmethod
    def _gift_pack_reward_label(reward: dict) -> str:
        """把一个奖励项渲染成人类可读的短语，如「100 积分」「7 天 Premium」"""
        reward_type = reward.get("type")
        meta = GIFT_PACK_REWARD_TYPES.get(reward_type)
        if meta is None:
            return str(reward_type)
        return meta["label"](reward)

    @staticmethod
    def _gift_pack_phase_ref(pack: GiftPack, now: int) -> int:
        """Freeze timestamped tasks at their deadline (or the pack's end)."""
        return min(int(now), int(pack.task_end_at or pack.end_at))

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

    @staticmethod
    def _validate_post_start_edit(old: dict, new: dict) -> None:
        def reject(field: str) -> None:
            raise ValueError(f"礼包开始后不能修改 {field}；可停用后新建礼包")

        for field in ("start_at", "rewards"):
            if old[field] != new[field]:
                reject(field if field == "start_at" else "奖励 rewards")

        def skeleton(items, field):
            def strip(item):
                item = dict(item)
                if field == "audience" and item["type"] == "user_list":
                    item.pop("tg_ids", None)
                if field == "requirements":
                    if item["type"] == "any_of":
                        item["items"] = [strip(child) for child in item["items"]]
                    elif (
                        item["type"]
                        in _GiftPackRepositoryConditions._GIFT_PACK_COUNT_METHODS
                        or item["type"] == "credits"
                    ):
                        item.pop("min", None)
                return item

            return [strip(item) for item in items]

        for field in ("audience", "requirements"):
            old_items, new_items = old[field], new[field]
            if skeleton(old_items, field) != skeleton(new_items, field):
                reject(field)
            if field == "requirements":

                def targets(items):
                    for item in items:
                        if item["type"] == "any_of":
                            yield from targets(item["items"])
                        else:
                            yield item.get("min")

                for before, after in zip(targets(old_items), targets(new_items)):
                    if before is not None and (after is None or after > before):
                        reject(field)
        if new["end_at"] < old["end_at"]:
            reject("end_at")
        old_deadline, new_deadline = old["task_end_at"], new["task_end_at"]
        if (old_deadline is None and new_deadline is not None) or (
            old_deadline is not None
            and new_deadline is not None
            and new_deadline < old_deadline
        ):
            reject("task_end_at")
        old_quantity, new_quantity = old["total_quantity"], new["total_quantity"]
        if (old_quantity is None and new_quantity is not None) or (
            old_quantity is not None
            and new_quantity is not None
            and new_quantity < old_quantity
        ):
            reject("total_quantity")

    @staticmethod
    def _gift_pack_referencing_packs(session, pack_id: int) -> list[tuple[int, str]]:
        """Check references semantically, including any_of, not via JSON substring."""
        references = []
        for pack in session.execute(
            select(GiftPack).where(GiftPack.id != pack_id)
        ).scalars():
            audience, requirements = (
                _GiftPackRepositoryConditions._resolve_gift_pack_conditions(pack)
            )

            def refers(items):
                return any(
                    any(
                        child["type"] == "claimed_pack" and child["pack_id"] == pack_id
                        for child in item["items"]
                    )
                    if item["type"] == "any_of"
                    else item["type"] == "claimed_pack" and item["pack_id"] == pack_id
                    for item in items
                )

            if refers(audience) or refers(requirements):
                references.append((int(pack.id), pack.title))
        return references
