"""礼包领域提升的「生产形态」本地彩排（sanitized production-shaped rehearsal）。

用法::

    python -m scripts.refactor.rehearse_gift_pack \
        --url postgresql+psycopg2://localuser:localpw@127.0.0.1:55443/rehearsal

只对一次性本地容器里的**生产库副本**运行（项目规则：隔离容器、假凭据、通知处理器
置为 no-op）。脚本从不写生产主机，也不触达任何外部系统。副本要先升到代码的
head 版本（``alembic upgrade head``）：生产可能落后于待发布的迁移。

彩排步骤：

1. 选一个同时绑定 Plex 与 Emby 且有积分余额的真实用户；必要时在副本里一次性重置
   与本次奖励相关的解锁列 / 永久会员标记（见报告的 ``replica_only_adjustments``）。
2. 新建一个包含 ``rules.GIFT_PACK_REWARD_TYPES`` 全部奖励类型的限量礼包，并通过公开
   入口 ``gift_pack.service.claim_gift_pack`` 领取。
3. 逐项核对并打印 JSON 报告：服务返回的发放快照、落库的
   ``GiftPackUserState.reward_snapshot``、``GiftPack.claimed_count``、积分与争霸赛
   余额、邀请码行、四个解锁列、Premium 到期时间、免费大转盘机会行。
4. 核对提交后的副作用调用参数：积分缓存失效键、下载权限同步与 Premium 权限同步的
   ``(tg_id, service)``、通知派发列表（no-op 记录）、特权码没有落盘（pre-commit 例外
   在副本上必须被拦截）。
5. 断言过程中没有任何 ERROR 级日志或异常堆栈（``logged_errors`` 为空）。

失败时仍打印同一份 JSON（``ok=false``）并以非零码退出，方便测试脚本解析。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 每轮领取用的奖励配置：覆盖 ``rules.GIFT_PACK_REWARD_TYPES`` 的全部类型，字段取自
#: 各类型的必填项。``invite_codes`` 故意用普通码——特权码要写 data/.env（文档化的
#: pre-commit 例外），彩排在副本上不该改写本地配置；该路径由单元测试覆盖。
REWARD_SPECS: list[dict] = [
    {"type": "credits", "amount": 88.5},
    {"type": "premium_days", "days": 7},
    {"type": "wheel_free_spins", "count": 3, "expiry_days": 30},
    {"type": "tournament_wallet", "amount": 12.25},
    {"type": "invite_codes", "count": 2, "privileged": False},
    {"type": "line_schedule_unlock"},
    {"type": "download_unlock"},
]

#: 媒体奖励会作用于所有已绑定的服务；彩排用户两端都绑定。
BOUND_SERVICES: tuple[str, ...] = ("plex", "emby")

#: 「有足够积分」的门槛，只用于挑选更有代表性的用户，不是领取的前置条件。
MIN_CREDITS = 100.0

#: 彩排礼包是限量礼包：领取一次即领完，顺带验证 sold_out 通知恰好派发一次。
PACK_TOTAL_QUANTITY = 1


class _LogCapture(logging.Handler):
    """收集 WARNING 及以上日志，用于断言「没有异常被记录」。"""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.errors: list[dict] = []
        self.warnings: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "function": record.funcName,
            "has_exc_info": bool(record.exc_info),
        }
        if record.levelno >= logging.ERROR or record.exc_info:
            self.errors.append(entry)
        else:
            self.warnings.append(entry)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="礼包领域提升的生产形态本地彩排")
    parser.add_argument("--url", required=True, help="一次性副本库的 PostgreSQL URL")
    parser.add_argument(
        "--repo",
        default=str(REPO_ROOT),
        help="仓库根目录（解析 data/.env 与日志目录，默认脚本所在仓库）",
    )
    parser.add_argument(
        "--rounds", type=int, default=1, help="彩排轮数：每轮新建一个礼包并领取一次"
    )
    args = parser.parse_args(argv)
    if args.rounds < 1:
        parser.error("--rounds 必须为正整数")
    return args


def _needed_adjustments(row: dict) -> list[str]:
    """该用户在副本当前状态下需要的一次性调整（越少越有代表性）。"""
    needed: list[str] = []
    if row["plex_line_unlocked"] or row["plex_sync_unlocked"]:
        needed.append("plex_unlock_columns")
    if row["emby_line_unlocked"] or row["emby_download_unlocked"]:
        needed.append("emby_unlock_columns")
    if row["plex_premium"] and not row["plex_expiry"]:
        needed.append("plex_lifetime_premium")
    if row["emby_premium"] and not row["emby_expiry"]:
        needed.append("emby_lifetime_premium")
    return needed


def _seed_rehearsal_user(db_module, statistics_model, plex_model, emby_model) -> dict:
    """副本里没有同时绑定两端的用户时原地造一个（只影响一次性副本）。"""
    from sqlalchemy import func, select

    with db_module.get_session() as session:
        max_tg_id = int(
            session.execute(select(func.max(statistics_model.tg_id))).scalar_one() or 0
        )
        tg_id = max(max_tg_id, 9_000_000_000) + 1
        plex_username = f"rehearsal_plex_{tg_id}"
        emby_username = f"rehearsal_emby_{tg_id}"
        session.add(statistics_model(tg_id=tg_id, credits=1000.0))
        session.add(
            plex_model(
                tg_id=tg_id,
                plex_username=plex_username,
                plex_email=f"{plex_username}@rehearsal.invalid",
            )
        )
        session.add(
            emby_model(
                emby_username=emby_username,
                emby_id=f"rehearsal-emby-{tg_id}",
                tg_id=tg_id,
            )
        )
        session.flush()
    return {
        "tg_id": tg_id,
        "credits": 1000.0,
        "wallet": 0.0,
        "plex_username": plex_username,
        "plex_premium": 0,
        "plex_expiry": None,
        "plex_line_unlocked": 0,
        "plex_sync_unlocked": 0,
        "emby_username": emby_username,
        "emby_premium": 0,
        "emby_expiry": None,
        "emby_line_unlocked": 0,
        "emby_download_unlocked": 0,
        "seeded": True,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report: dict = {
        "repo": str(Path(args.repo).resolve()),
        "rounds": [],
        "checks": {},
    }
    failures: list[str] = []
    calls: dict[str, list[dict]] = {
        "download_unlock": [],
        "premium_permission": [],
        "cache_invalidation": [],
        "privileged_codes": [],
    }
    notifications: list[dict] = []
    capture = _LogCapture()

    def record(target: dict, name: str, ok: bool, detail: object = "") -> None:
        target[name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            failures.append(f"{name}: {detail}")

    # ---- 外部副作用全部替换为 no-op 或记录器 ----

    def _record_cache_invalidation(keys) -> None:
        calls["cache_invalidation"].append({"keys": [str(key) for key in keys]})

    def _record_download_unlock(tg_id: int, service: str) -> None:
        calls["download_unlock"].append({"tg_id": int(tg_id), "service": str(service)})

    def _record_premium_sync(tg_id: int, services=None) -> None:
        calls["premium_permission"].append(
            {"tg_id": int(tg_id), "services": [str(item) for item in (services or ())]}
        )

    def _record_privileged_codes(codes) -> None:
        calls["privileged_codes"].append({"codes": [str(code) for code in codes]})

    def _record_notification(coro) -> None:
        """替代 ``notifications._notify_detached``：只记录，绝不执行也不联网。"""
        frame = getattr(coro, "cr_frame", None)
        arguments = dict(frame.f_locals) if frame is not None else {}
        notifications.append(
            {
                "function": getattr(
                    getattr(coro, "cr_code", None), "co_name", "unknown"
                ),
                "args": {
                    key: value for key, value in arguments.items() if key != "self"
                },
            }
        )
        coro.close()

    async def _noop_send(*_args, **_kwargs) -> bool:
        return True

    try:
        if not args.url.startswith("postgresql"):
            raise ValueError("rehearsal requires the PostgreSQL rehearsal copy")
        repo_root = Path(args.repo)
        if not repo_root.is_dir():
            raise ValueError(f"--repo 不是目录: {repo_root}")
        os.chdir(repo_root)
        os.environ["DATABASE_URL"] = args.url
        os.environ["DATABASE_TYPE"] = "postgresql"

        from app.core.config import settings

        # data/.env 的值会被 Settings 直接写回 os.environ 与实例（见
        # Settings._load_from_env_file），所以必须在导入 app.core.db 之前把连接串
        # 钉死，否则彩排可能连上开发库甚至别的库。
        report["settings_url_overridden"] = settings.DATABASE_URL != args.url
        settings.DATABASE_URL = args.url
        settings.DATABASE_TYPE = "postgresql"

        # 注意：以上赋值语句把两个 import 块隔开，导入顺序不可被整理器合并。
        from sqlalchemy import func, select, text

        import app.core.db as db_module
        from app.core import telegram as telegram_module
        from app.domains.credits import repository as credits_repository
        from app.domains.credits import service as credits_service
        from app.domains.gift_pack import notifications as gift_pack_notifications
        from app.domains.gift_pack import repository as gift_pack_repository
        from app.domains.gift_pack import rules as gift_pack_rules
        from app.domains.gift_pack import service as gift_pack_service
        from app.domains.gift_pack.models import GiftPack, GiftPackUserState
        from app.domains.identity.models import EmbyUser, PlexUser, Statistics
        from app.domains.invitation import repository as invitation_repository
        from app.domains.invitation.models import Invitation
        from app.domains.luckywheel.models import LuckywheelFreeSpin
        from app.domains.premium import service as premium_service
        from app.model_registry import metadata as _metadata  # noqa: F401 - 注册模型

        logging.getLogger().addHandler(capture)
        telegram_module.send_message_by_url = _noop_send
        telegram_module.notify_admins_by_url = _noop_send
        gift_pack_notifications.notify_admins_by_url = _noop_send
        gift_pack_notifications.get_user_name_from_tg_id = (
            lambda tg_id, *_args, **_kwargs: f"rehearsal-{tg_id}"
        )
        gift_pack_notifications._notify_detached = _record_notification
        credits_repository.invalidate_user_credits = _record_cache_invalidation
        credits_service.invalidate_cache_keys = _record_cache_invalidation
        if hasattr(invitation_repository, "persist_privileged_codes_tx"):
            invitation_repository.persist_privileged_codes_tx = _record_privileged_codes
        premium_service.apply_download_unlock_to_media = _record_download_unlock
        premium_service.sync_premium_media_access = _record_premium_sync

        # ---- 1. 选一个同时绑定 Plex 与 Emby 的真实用户 ----
        candidates_sql = (
            select(
                Statistics.tg_id.label("tg_id"),
                Statistics.credits.label("credits"),
                Statistics.tournament_wallet_credits.label("wallet"),
                PlexUser.plex_username.label("plex_username"),
                PlexUser.is_premium.label("plex_premium"),
                PlexUser.premium_expiry_time.label("plex_expiry"),
                PlexUser.line_schedule_unlocked.label("plex_line_unlocked"),
                PlexUser.sync_unlocked.label("plex_sync_unlocked"),
                EmbyUser.emby_username.label("emby_username"),
                EmbyUser.is_premium.label("emby_premium"),
                EmbyUser.premium_expiry_time.label("emby_expiry"),
                EmbyUser.line_schedule_unlocked.label("emby_line_unlocked"),
                EmbyUser.download_unlocked.label("emby_download_unlocked"),
            )
            .join(PlexUser, PlexUser.tg_id == Statistics.tg_id)
            .join(EmbyUser, EmbyUser.tg_id == Statistics.tg_id)
            .order_by(Statistics.credits.desc())
            .limit(50)
        )
        with db_module.get_session() as session:
            candidates = [dict(row._mapping) for row in session.execute(candidates_sql)]
        candidates.sort(
            key=lambda row: (
                len(_needed_adjustments(row)),
                0 if float(row["credits"]) >= MIN_CREDITS else 1,
                -float(row["credits"]),
            )
        )

        seeded = not candidates
        user = (
            candidates[0]
            if candidates
            else _seed_rehearsal_user(db_module, Statistics, PlexUser, EmbyUser)
        )
        tg_id = int(user["tg_id"])
        report["rehearsal_user"] = {
            "tg_id": tg_id,
            "credits": float(user["credits"]),
            "bound_services": list(BOUND_SERVICES),
            "candidates": len(candidates),
            "seeded_in_replica": seeded,
        }
        record(
            report["checks"],
            "rehearsal_user_bound_to_both_services",
            True,
            {"tg_id": tg_id, "candidates": len(candidates), "seeded": seeded},
        )

        # ---- 2. 副本内一次性调整，让每类奖励都真的生效 ----
        adjustments = _needed_adjustments(user)
        if adjustments:
            with db_module.get_session() as session:
                if "plex_unlock_columns" in adjustments:
                    session.execute(
                        text(
                            "UPDATE plex_user SET line_schedule_unlocked = 0,"
                            " line_schedule_unlock_time = NULL, sync_unlocked = 0,"
                            " sync_unlock_time = NULL WHERE tg_id = :tg_id"
                        ),
                        {"tg_id": tg_id},
                    )
                if "emby_unlock_columns" in adjustments:
                    session.execute(
                        text(
                            "UPDATE emby_user SET line_schedule_unlocked = 0,"
                            " line_schedule_unlock_time = NULL, download_unlocked = 0,"
                            " download_unlock_time = NULL WHERE tg_id = :tg_id"
                        ),
                        {"tg_id": tg_id},
                    )
                if "plex_lifetime_premium" in adjustments:
                    session.execute(
                        text(
                            "UPDATE plex_user SET is_premium = 0,"
                            " premium_expiry_time = NULL WHERE tg_id = :tg_id"
                        ),
                        {"tg_id": tg_id},
                    )
                if "emby_lifetime_premium" in adjustments:
                    session.execute(
                        text(
                            "UPDATE emby_user SET is_premium = 0,"
                            " premium_expiry_time = NULL WHERE tg_id = :tg_id"
                        ),
                        {"tg_id": tg_id},
                    )
        report["replica_only_adjustments"] = adjustments

        # ---- 3. 每轮：建包 → 领取 → 逐项核对 ----
        # 期望条目数由领域登记表的 requires_binding 推导：作用于绑定服务的奖励每个
        # 服务一条，其余奖励一条。
        expected_counts = {
            reward["type"]: (
                len(BOUND_SERVICES)
                if gift_pack_rules.GIFT_PACK_REWARD_TYPES[reward["type"]][
                    "requires_binding"
                ]
                else 1
            )
            for reward in REWARD_SPECS
        }
        invite_codes_spec = next(
            reward for reward in REWARD_SPECS if reward["type"] == "invite_codes"
        )
        expected_cache_keys = sorted(
            key
            for key in (
                f"plex:{user['plex_username'].lower()}"
                if user.get("plex_username")
                else None,
                f"emby:{user['emby_username'].lower()}"
                if user.get("emby_username")
                else None,
            )
            if key
        )

        for index in range(int(args.rounds)):
            round_checks: dict = {}
            start_ms = int(time.time() * 1000)
            now = int(time.time())
            for recorded in calls.values():
                recorded.clear()
            notifications.clear()

            with db_module.get_session() as session:
                credits_before, wallet_before = session.execute(
                    select(
                        Statistics.credits, Statistics.tournament_wallet_credits
                    ).where(Statistics.tg_id == tg_id)
                ).one()
            credits_before = float(credits_before)
            wallet_before = float(wallet_before)

            pack_id = gift_pack_repository.create_gift_pack(
                title=f"[REHEARSAL] 全奖励礼包 #{index + 1}",
                description="production-shaped rehearsal pack",
                rewards=REWARD_SPECS,
                start_at=now - 600,
                end_at=now + 6 * 3600,
                total_quantity=PACK_TOTAL_QUANTITY,
                is_enabled=True,
            )
            result = gift_pack_service.claim_gift_pack(pack_id, tg_id)
            snapshot = list(result["results"])
            record(
                round_checks,
                "claim_succeeded",
                result.get("success") is True and result.get("pack_id") == pack_id,
                {
                    "success": result.get("success"),
                    "pack_id": result.get("pack_id"),
                    "expected_pack_id": pack_id,
                },
            )

            actual_counts: dict[str, int] = {}
            for item in snapshot:
                kind = str(item.get("type"))
                actual_counts[kind] = actual_counts.get(kind, 0) + 1
            record(
                round_checks,
                "reward_types_reported",
                actual_counts == expected_counts,
                {"expected": expected_counts, "actual": actual_counts},
            )
            record(
                round_checks,
                "reward_types_cover_domain_registry",
                set(actual_counts) == set(gift_pack_rules.GIFT_PACK_REWARD_TYPES),
                {
                    "domain_types": sorted(gift_pack_rules.GIFT_PACK_REWARD_TYPES),
                    "reported": sorted(actual_counts),
                },
            )
            # 生产副本里用户可能本来就解锁过线路/下载、或是永久会员，因此
            # skipped 只记录、不判失败；要求的是每一项都发放成功。
            record(
                round_checks,
                "all_rewards_succeeded",
                all(item.get("success") is True for item in snapshot),
                [item for item in snapshot if item.get("success") is not True],
            )
            record(
                round_checks,
                "no_download_sync_failures",
                result.get("download_sync_failed") == [],
                result.get("download_sync_failed"),
            )

            credits_entry = next(
                item for item in snapshot if item.get("type") == "credits"
            )
            wallet_entry = next(
                item for item in snapshot if item.get("type") == "tournament_wallet"
            )
            invite_codes = [
                code
                for item in snapshot
                if item.get("type") == "invite_codes"
                for code in item.get("codes", [])
            ]
            premium_entries = {
                str(item.get("service")): item
                for item in snapshot
                if item.get("type") == "premium_days"
            }

            # ---- 数据库侧核对 ----
            with db_module.get_session() as session:
                state = session.execute(
                    select(GiftPackUserState).where(
                        GiftPackUserState.pack_id == pack_id,
                        GiftPackUserState.tg_id == tg_id,
                    )
                ).scalar_one_or_none()
                persisted_snapshot = (
                    json.loads(state.reward_snapshot)
                    if state is not None and state.reward_snapshot
                    else None
                )
                claimed_at = (
                    int(state.claimed_at)
                    if state is not None and state.claimed_at
                    else None
                )
                claimed_count, total_quantity = session.execute(
                    select(GiftPack.claimed_count, GiftPack.total_quantity).where(
                        GiftPack.id == pack_id
                    )
                ).one()
                credits_after, wallet_after = session.execute(
                    select(
                        Statistics.credits, Statistics.tournament_wallet_credits
                    ).where(Statistics.tg_id == tg_id)
                ).one()
                plex_flags = dict(
                    session.execute(
                        select(
                            PlexUser.line_schedule_unlocked,
                            PlexUser.line_schedule_unlock_time,
                            PlexUser.sync_unlocked,
                            PlexUser.sync_unlock_time,
                            PlexUser.is_premium,
                            PlexUser.premium_expiry_time,
                        ).where(PlexUser.tg_id == tg_id)
                    )
                    .one()
                    ._mapping
                )
                emby_flags = dict(
                    session.execute(
                        select(
                            EmbyUser.line_schedule_unlocked,
                            EmbyUser.line_schedule_unlock_time,
                            EmbyUser.download_unlocked,
                            EmbyUser.download_unlock_time,
                            EmbyUser.is_premium,
                            EmbyUser.premium_expiry_time,
                        ).where(EmbyUser.tg_id == tg_id)
                    )
                    .one()
                    ._mapping
                )
                codes_in_db = set(
                    session.execute(
                        select(Invitation.code).where(
                            Invitation.owner == tg_id,
                            Invitation.code.in_(invite_codes),
                        )
                    ).scalars()
                )
                freespins = int(
                    session.execute(
                        select(func.count())
                        .select_from(LuckywheelFreeSpin)
                        .where(
                            LuckywheelFreeSpin.tg_id == tg_id,
                            LuckywheelFreeSpin.source == "gift_pack",
                            LuckywheelFreeSpin.granted_at_ms >= start_ms,
                        )
                    ).scalar_one()
                )

            serialised_snapshot = json.loads(json.dumps(snapshot, default=str))
            record(
                round_checks,
                "user_state_claimed",
                claimed_at is not None,
                claimed_at,
            )
            record(
                round_checks,
                "reward_snapshot_persisted",
                persisted_snapshot == serialised_snapshot,
                {
                    "persisted_entries": len(persisted_snapshot or []),
                    "service_entries": len(serialised_snapshot),
                    "match": persisted_snapshot == serialised_snapshot,
                },
            )
            record(
                round_checks,
                "claimed_count_incremented",
                int(claimed_count) == 1 and int(total_quantity) == PACK_TOTAL_QUANTITY,
                {
                    "claimed_count": int(claimed_count),
                    "total_quantity": int(total_quantity),
                },
            )
            record(
                round_checks,
                "pack_sold_out",
                result.get("sold_out") is True and result.get("remaining") == 0,
                {
                    "sold_out": result.get("sold_out"),
                    "remaining": result.get("remaining"),
                },
            )

            expected_credits = round(credits_before + float(credits_entry["amount"]), 2)
            record(
                round_checks,
                "credits_granted",
                round(float(credits_after), 2) == expected_credits
                and round(float(credits_entry["balance_after"]), 2) == expected_credits,
                {
                    "before": credits_before,
                    "after": round(float(credits_after), 2),
                    "expected": expected_credits,
                    "snapshot_balance_after": credits_entry["balance_after"],
                },
            )
            expected_wallet = round(wallet_before + float(wallet_entry["amount"]), 2)
            record(
                round_checks,
                "tournament_wallet_granted",
                round(float(wallet_after), 2) == expected_wallet
                and round(float(wallet_entry["balance_after"]), 2) == expected_wallet,
                {
                    "before": wallet_before,
                    "after": round(float(wallet_after), 2),
                    "expected": expected_wallet,
                    "snapshot_balance_after": wallet_entry["balance_after"],
                },
            )
            record(
                round_checks,
                "invite_codes_persisted",
                len(invite_codes) == int(invite_codes_spec["count"])
                and set(invite_codes) == codes_in_db,
                {
                    "snapshot": sorted(invite_codes),
                    "rows_in_db": sorted(codes_in_db),
                },
            )

            flags_ok = (
                int(plex_flags["line_schedule_unlocked"]) == 1
                and plex_flags["line_schedule_unlock_time"] is not None
                and int(plex_flags["sync_unlocked"]) == 1
                and plex_flags["sync_unlock_time"] is not None
                and int(emby_flags["line_schedule_unlocked"]) == 1
                and emby_flags["line_schedule_unlock_time"] is not None
                and int(emby_flags["download_unlocked"]) == 1
                and emby_flags["download_unlock_time"] is not None
            )
            record(
                round_checks,
                "media_flags_unlocked",
                flags_ok,
                {"plex": plex_flags, "emby": emby_flags},
            )

            expected_expiry = {
                service: premium_entries.get(service, {}).get("new_expiry")
                for service in BOUND_SERVICES
            }
            premium_ok = (
                all(expected_expiry.values())
                and int(plex_flags["is_premium"]) == 1
                and int(emby_flags["is_premium"]) == 1
                and plex_flags["premium_expiry_time"] == expected_expiry["plex"]
                and emby_flags["premium_expiry_time"] == expected_expiry["emby"]
            )
            record(
                round_checks,
                "premium_extended",
                premium_ok,
                {
                    "plex": plex_flags["premium_expiry_time"],
                    "emby": emby_flags["premium_expiry_time"],
                    "expected": expected_expiry,
                },
            )

            wheel_entry = next(
                item for item in snapshot if item.get("type") == "wheel_free_spins"
            )
            record(
                round_checks,
                "wheel_free_spins_granted",
                freespins == int(wheel_entry["count"]),
                {"rows_in_db": freespins, "snapshot_count": wheel_entry["count"]},
            )

            # ---- 提交后的副作用调用参数 ----
            recorded_keys = sorted(
                {key for call in calls["cache_invalidation"] for key in call["keys"]}
            )
            record(
                round_checks,
                "credit_cache_invalidation_recorded",
                recorded_keys == expected_cache_keys,
                {"recorded": recorded_keys, "expected": expected_cache_keys},
            )

            # 记录顺序就是同步顺序（plex → emby，与领域里的固定顺序一致）。
            # 副本里若已经永久解锁过，则该服务记为 skipped、不会触发同步。
            download_calls = list(calls["download_unlock"])
            skipped_download = {
                item.get("service")
                for item in snapshot
                if item.get("type") == "download_unlock"
                and item.get("skipped") == "already_unlocked"
            }
            expected_download = [
                {"tg_id": tg_id, "service": service}
                for service in BOUND_SERVICES
                if service not in skipped_download
            ]
            record(
                round_checks,
                "download_unlock_sync_called",
                download_calls == expected_download,
                {"recorded": download_calls, "expected": expected_download},
            )

            premium_calls = list(calls["premium_permission"])
            expected_premium = [
                {"tg_id": tg_id, "services": [service]} for service in BOUND_SERVICES
            ]
            record(
                round_checks,
                "premium_permission_sync_called",
                premium_calls == expected_premium,
                {"recorded": premium_calls, "expected": expected_premium},
            )
            record(
                round_checks,
                "privileged_codes_not_written",
                calls["privileged_codes"] == [],
                calls["privileged_codes"],
            )
            expected_notifications = [
                {
                    "function": "notify_gift_pack_sold_out",
                    "args": {
                        "pack_id": pack_id,
                        "title": result["title"],
                        "total_quantity": PACK_TOTAL_QUANTITY,
                    },
                }
            ]
            record(
                round_checks,
                "notifications_dispatched",
                notifications == expected_notifications,
                {"recorded": notifications, "expected": expected_notifications},
            )

            report["rounds"].append(
                {
                    "round": index + 1,
                    "pack_id": pack_id,
                    "title": result["title"],
                    "tg_id": tg_id,
                    "credits_before": credits_before,
                    "credits_after": round(float(credits_after), 2),
                    "wallet_before": wallet_before,
                    "wallet_after": round(float(wallet_after), 2),
                    "claimed_count": int(claimed_count),
                    "total_quantity": int(total_quantity),
                    "sold_out": bool(result.get("sold_out")),
                    "claimed_at": claimed_at,
                    "reward_snapshot_service": serialised_snapshot,
                    "reward_snapshot_persisted": persisted_snapshot,
                    "invite_codes_in_db": sorted(codes_in_db),
                    "media_flags": {"plex": plex_flags, "emby": emby_flags},
                    "media_sync_calls": {
                        "download_unlock": download_calls,
                        "premium_permission": premium_calls,
                    },
                    "cache_invalidation_keys": recorded_keys,
                    "notifications": notifications,
                    "checks": round_checks,
                }
            )
    except Exception as error:
        failures.append(f"unhandled {type(error).__name__}: {error}")
        report["error"] = {
            "type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        }
    finally:
        logging.getLogger().removeHandler(capture)

    record(report["checks"], "no_error_logs", not capture.errors, capture.errors)
    report["logged_errors"] = capture.errors
    report["logged_warnings"] = capture.warnings
    report["ok"] = not failures
    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
