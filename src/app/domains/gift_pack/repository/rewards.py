"""礼包 repository：奖励发放（由 part_1–part_3 与门面机械拆分）。"""

import time

from app.domains.blackjack import repository as blackjack_repository
from app.domains.credits import repository as credits_repository
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.gift_pack import rules
from app.domains.gift_pack.exceptions import gift_pack_error
from app.domains.invitation import repository as invitation_repository
from app.domains.lines import repository as lines_repository
from app.domains.luckywheel import repository as luckywheel_repository
from app.domains.media_access import repository as media_access_repository
from app.domains.premium import repository as premium_repository


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

        snapshot: list[dict] = []
        pending_permission_sync: list[str] = []
        pending_download_sync: list[str] = []
        pending_privileged_codes: list[str] = []

        for reward in rewards:
            reward_type = reward.get("type")
            label = rules._gift_pack_reward_label(reward)

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
                    raise gift_pack_error("请先绑定媒体账号后再领取")
                for service in services:
                    # 复用外层事务（行锁在 premium 的 *_tx 里），Premium 写入与
                    # 领取记录同生共死；媒体权限同步由提交后的 service 负责。
                    new_expiry = premium_repository.grant_premium_days_tx(
                        session, tg_id, service, days
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
                    raise gift_pack_error("请先绑定媒体账号后再领取")
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
                raise gift_pack_error(f"不支持的奖励类型: {reward_type}")

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
            raise gift_pack_error("免费机会的次数与有效天数必须为正")
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
            raise gift_pack_error("争霸赛余额数量必须为正")
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

    # 解锁的永久标记列属于 lines / media_access：这里只负责拼接用户可见文案，
    # 写列交给对应领域的 `*_tx`（行锁 + 调用方事务）。
    def _grant_feature_unlock_tx(
        self, session, tg_id: int, service: str, feature: str
    ) -> dict:
        if feature == "line_schedule":
            result = lines_repository.unlock_line_schedule_tx(session, tg_id, service)
            feature_name = "线路调度"
        elif feature == "download":
            result = media_access_repository.unlock_download_tx(session, tg_id, service)
            feature_name = "下载权限"
        else:
            raise gift_pack_error(f"不支持的解锁类型: {feature}/{service}")
        service_name = service.capitalize()
        if result.get("skipped"):
            return {
                "success": True,
                "service": service,
                "skipped": "already_unlocked",
                "message": f"{service_name} 已解锁{feature_name}，本次未变更",
            }
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
        """生成邀请码（Invitation 行）并登记特权码

        行写入与领取同生共死；特权码只是先记账，真正写配置发生在最后一次
        数据库 flush 之后、事务提交之前（`persist_privileged_codes_tx`）。
        """
        count = int(reward.get("count") or 0)
        if count <= 0:
            raise gift_pack_error("邀请码数量必须为正")
        privileged = bool(reward.get("privileged"))
        codes = invitation_repository.issue_codes_tx(
            session, tg_id, count, privileged=privileged
        )
        if privileged:
            pending_privileged_codes.extend(codes)
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
        """把特权码写入配置（pre-commit 例外，最后交给 invitation 领域）

        配置文件不是事务性的，所以只在一批奖励的数据库写入全部成功之后调用；
        写失败会把异常抛出去，让整个领取事务回滚。
        """
        invitation_repository.persist_privileged_codes_tx(codes)
