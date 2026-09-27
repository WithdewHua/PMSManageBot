"""礼包 repository：奖励发放（由 part_1–part_3 与门面机械拆分）。"""

import time
from typing import ClassVar
from uuid import uuid4

from sqlalchemy import select

from app.core.config import settings
from app.domains.blackjack import repository as blackjack_repository
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.invitation.models import Invitation
from app.domains.luckywheel import repository as luckywheel_repository

from . import (
    _GIFT_PACK_PRIVILEGED_CODES_LOCK,
)


class _GiftPackRepositoryRewards:
    def _grant_gift_pack_rewards(
        self, session, tg_id: int, rewards: list[dict], context: dict
    ) -> tuple[list[dict], list[str], list[str], list[str]]:
        """在调用方的事务内发放全部奖励项

        任一项失败即抛出异常，由调用方回滚整个事务。所有分支都复用调用方的
        session；媒体服务器同步提交后执行，特权码配置由领取方在最后一次
        数据库 flush 后、事务提交前写入。

        :return: (发放快照,
                  待事务提交后同步 Premium 媒体服务器权限的服务列表,
                  待事务提交后同步下载权限到媒体服务器的服务列表,
                  待事务提交前写入配置的特权邀请码列表)
        """
        # 延迟导入：app.premium 依赖本模块，模块级导入会形成循环
        from app.domains.premium.service import update_premium_status

        snapshot: list[dict] = []
        pending_permission_sync: list[str] = []
        pending_download_sync: list[str] = []
        pending_privileged_codes: list[str] = []

        for reward in rewards:
            reward_type = reward.get("type")
            label = self._gift_pack_reward_label(reward)

            if reward_type == "credits":
                amount = float(reward.get("amount") or 0)
                self._lock_gift_pack_stats(session, tg_id)
                mutation = credits_repository.add_tx(
                    session, CreditAccount.tg(int(tg_id)), amount
                )
                credits_service.register_cache_invalidation(session, mutation)
                snapshot.append(
                    {
                        "type": "credits",
                        "label": label,
                        "success": True,
                        "amount": amount,
                        "balance_after": mutation.after,
                    }
                )

            elif reward_type == "premium_days":
                days = int(reward.get("days") or 0)
                services = context["bound_services"]
                if not services:
                    # 正常情况下已被 require_binding 资格拦住，这里是最后一道防线
                    raise ValueError("请先绑定媒体账号后再领取")
                for service in services:
                    # 传入 session 复用外层事务，使 Premium 写入与领取记录同生共死
                    new_expiry = update_premium_status(
                        self, tg_id, service, days, session=session
                    )
                    if new_expiry is None:
                        # 永久会员：跳过延长，但不阻断领取
                        snapshot.append(
                            {
                                "type": "premium_days",
                                "label": label,
                                "success": True,
                                "days": days,
                                "service": service,
                                "skipped": "lifetime",
                                "message": f"{service.capitalize()} 为永久会员，Premium 天数未生效",
                            }
                        )
                    else:
                        snapshot.append(
                            {
                                "type": "premium_days",
                                "label": label,
                                "success": True,
                                "days": days,
                                "service": service,
                                "new_expiry": new_expiry.isoformat(),
                            }
                        )
                        pending_permission_sync.append(service)

            elif reward_type == "wheel_free_spins":
                snapshot.append(
                    self._grant_wheel_free_spins_tx(session, tg_id, reward, label)
                )

            elif reward_type == "tournament_wallet":
                snapshot.append(
                    self._grant_tournament_wallet_tx(session, tg_id, reward, label)
                )

            elif reward_type in ("line_schedule_unlock", "download_unlock"):
                services = context["bound_services"]
                if not services:
                    # 正常情况下已被 require_binding 资格拦住，这里是最后一道防线
                    raise ValueError("请先绑定媒体账号后再领取")
                feature = (
                    "line_schedule"
                    if reward_type == "line_schedule_unlock"
                    else "download"
                )
                for service in services:
                    item = self._grant_feature_unlock_tx(
                        session, tg_id, service, feature
                    )
                    item["type"] = reward_type
                    item["label"] = label
                    snapshot.append(item)
                    if feature == "download" and not item.get("skipped"):
                        pending_download_sync.append(service)

            elif reward_type == "invite_codes":
                snapshot.append(
                    self._grant_invite_codes_tx(
                        session, tg_id, reward, label, pending_privileged_codes
                    )
                )

            else:
                raise ValueError(f"不支持的奖励类型: {reward_type}")

        return (
            snapshot,
            pending_permission_sync,
            pending_download_sync,
            pending_privileged_codes,
        )

    @staticmethod
    def _grant_wheel_free_spins_tx(
        session, tg_id: int, reward: dict, label: str
    ) -> dict:
        """发放礼包来源的免费大转盘机会（source='gift_pack'）

        与 21 点来源写入同一张表：消耗、概览、到期提醒、角标无需改动；
        周上限、获得通知与对账按 source == 'blackjack' 过滤，不受影响。
        """
        count = int(reward.get("count") or 0)
        expiry_days = int(reward.get("expiry_days") or 0)
        if count <= 0 or expiry_days <= 0:
            raise ValueError("免费机会的次数与有效天数必须为正")
        now_ms = int(time.time() * 1000)
        expires_at_ms = now_ms + expiry_days * 86400 * 1000
        luckywheel_repository.grant_free_spins_tx(
            session,
            tg_id,
            count,
            source="gift_pack",
            granted_at_ms=now_ms,
            expires_at_ms=expires_at_ms,
            cost_credits=0,
            wheel_stats_source="gift_pack_free",
        )
        return {
            "type": "wheel_free_spins",
            "label": label,
            "success": True,
            "count": count,
            "days": expiry_days,
            "expires_at": expires_at_ms // 1000,
        }

    def _grant_tournament_wallet_tx(
        self, session, tg_id: int, reward: dict, label: str
    ) -> dict:
        """把数额计入争霸赛余额（不计入积分）

        争霸赛余额列属于 blackjack 领域，写入统一走它的 `*_tx`（行锁 + SQL 增量 +
        两位小数舍入），礼包这边只负责校验数额与拼响应。
        """
        amount = round(float(reward.get("amount") or 0), 2)
        if amount <= 0:
            raise ValueError("争霸赛余额数量必须为正")
        balance_after = blackjack_repository.credit_tournament_wallet_tx(
            session, tg_id, amount
        )
        return {
            "type": "tournament_wallet",
            "label": label,
            "success": True,
            "amount": amount,
            "balance_after": balance_after,
        }

    # 功能解锁的永久标记列：(模型, 标记列, 解锁时间列)
    _GIFT_PACK_UNLOCK_COLUMNS: ClassVar[dict] = {
        ("line_schedule", "plex"): (
            PlexUser,
            "line_schedule_unlocked",
            "line_schedule_unlock_time",
        ),
        ("line_schedule", "emby"): (
            EmbyUser,
            "line_schedule_unlocked",
            "line_schedule_unlock_time",
        ),
        ("download", "plex"): (PlexUser, "sync_unlocked", "sync_unlock_time"),
        ("download", "emby"): (EmbyUser, "download_unlocked", "download_unlock_time"),
    }

    def _grant_feature_unlock_tx(
        self, session, tg_id: int, service: str, feature: str
    ) -> dict:
        """在调用方事务内为一个服务永久解锁线路调度 / 下载权限（只写数据库）

        「已拥有」直接读永久解锁标记列，而不是调 check_download_unlock：
        后者把 Premium 也算作已解锁，按它判断会让 Premium 用户永远拿不到
        永久解锁。已永久解锁的服务记为 skipped，不阻断领取。
        """
        key = (feature, service)
        if key not in self._GIFT_PACK_UNLOCK_COLUMNS:
            raise ValueError(f"不支持的解锁类型: {feature}/{service}")
        model, flag_col, time_col = self._GIFT_PACK_UNLOCK_COLUMNS[key]
        feature_name = "线路调度" if feature == "line_schedule" else "下载权限"
        service_name = service.capitalize()

        user = (
            session.execute(select(model).where(model.tg_id == tg_id).with_for_update())
            .scalars()
            .one_or_none()
        )
        if user is None:
            raise ValueError(f"未找到绑定的 {service_name} 账号")

        if int(getattr(user, flag_col) or 0) == 1:
            return {
                "success": True,
                "service": service,
                "skipped": "already_unlocked",
                "message": f"{service_name} 已解锁{feature_name}，本次未变更",
            }

        setattr(user, flag_col, 1)
        setattr(user, time_col, int(time.time()))
        return {
            "success": True,
            "service": service,
            "message": f"{service_name} 已永久解锁{feature_name}",
        }

    @staticmethod
    def _grant_invite_codes_tx(
        session,
        tg_id: int,
        reward: dict,
        label: str,
        pending_privileged_codes: list[str],
    ) -> dict:
        """在调用方事务内为用户生成邀请码（Invitation 行）

        与领取同生共死：事务回滚时不会留下可用的邀请码。
        uuid4().hex 与既有码同为 32 位十六进制，不会重复。
        """
        count = int(reward.get("count") or 0)
        if count <= 0:
            raise ValueError("邀请码数量必须为正")
        privileged = bool(reward.get("privileged"))
        codes = [uuid4().hex for _ in range(count)]
        for code in codes:
            session.add(Invitation(code=code, owner=tg_id, is_used=0))
        if privileged:
            pending_privileged_codes.extend(codes)
        session.flush()
        return {
            "type": "invite_codes",
            "label": label,
            "success": True,
            "count": count,
            "privileged": privileged,
            "codes": codes,
        }

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
