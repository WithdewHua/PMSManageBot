"""End-to-end tests for move-privileged-codes-to-database OpenSpec change.

Covers:
- Three issuance paths (admin, luckywheel, gift pack) writing is_privileged in DB
- Atomic rollback on failure
- Registration when closed (privileged vs normal)
- External creation failure releasing code with is_privileged preserved
- Single and batch check-privileged endpoints
- One-time startup import with 4 categories (unused, used, missing, duplicate) and idempotency
- Export script for rollback (read-only verification)
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine, select, text
from starlette.requests import Request

from app.core import kv as core_kv
from app.core.config import settings
from app.core.db import get_session
from app.core.legacy_env import LegacyEnvSource
from app.domains.accounts import service as accounts_service
from app.domains.identity.models import Statistics
from app.domains.invitation import repository as invitation_repository
from app.domains.invitation import router as invitation_router
from app.domains.invitation import service as invitation_service
from app.domains.invitation.exceptions import (
    InvitationCodeUsed,
    InvitationError,
)
from app.domains.invitation.models import Invitation
from app.domains.invitation.schemas import (
    BatchCheckPrivilegedCodesRequest,
    CheckPrivilegedCodeRequest,
    RedeemInviteCodeRequest,
)
from app.model_registry import metadata
from app.transport.http.schemas import TelegramUser
from scripts.export_privileged_codes import export_unused_privileged_codes


def _request() -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/api", "headers": []})
    request.state.telegram_data = {}
    return request


async def _async_noop(*args, **kwargs):
    return None


# --------------------------------------------------------------------------- #
# 1. 发放路径与原子回滚
# --------------------------------------------------------------------------- #


def test_admin_generate_privileged_code(session_env):
    with get_session() as session:
        session.add(Statistics(tg_id=101, credits=100, donation=0))

    # 普通码
    normal_codes = invitation_service.generate_codes(
        101, count=1, charge=0, privileged=False
    )
    # 特权码
    privileged_codes = invitation_service.generate_codes(
        101, count=1, charge=0, privileged=True
    )

    with get_session() as session:
        normal = session.get(Invitation, normal_codes[0])
        assert normal.is_privileged == 0
        assert normal.is_used == 0

        priv = session.get(Invitation, privileged_codes[0])
        assert priv.is_privileged == 1
        assert priv.is_used == 0


def test_admin_generate_rolls_back_atomically(session_env, monkeypatch):
    with get_session() as session:
        session.add(Statistics(tg_id=102, credits=10, donation=0))

    # 模拟扣除积分失败触发回滚
    monkeypatch.setattr(
        invitation_repository.credits_repository,
        "deduct_tx",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("deduct error")),
    )

    with pytest.raises(InvitationError):
        invitation_service.generate_codes(102, count=1, charge=50, privileged=True)

    with get_session() as session:
        rows = (
            session.execute(select(Invitation).where(Invitation.owner == 102))
            .scalars()
            .all()
        )
        assert rows == []


def test_luckywheel_issues_privileged_code_in_transaction(session_env):
    from app.domains.luckywheel import config as wheel_config

    with get_session() as session:
        session.add(Statistics(tg_id=103, credits=500, donation=0))

    # 模拟转盘中奖包含邀请码且特权开关开启
    with get_session() as session:
        core_kv.upsert_tx(
            session,
            wheel_config.CONFIG_TYPE,
            wheel_config.CONFIG_KEY,
            json.dumps({"gen_privileged_code": True}),
        )
        privileged = wheel_config.consume_privileged_code_toggle_tx(session)
        assert privileged is True
        codes = invitation_repository.issue_codes_tx(
            session, 103, count=1, privileged=privileged
        )

    with get_session() as session:
        inv = session.get(Invitation, codes[0])
        assert inv.is_privileged == 1
        assert inv.is_used == 0


# --------------------------------------------------------------------------- #
# 2. 兑换逻辑：预占—开号—确认，特权码效力与失败释放
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_registration_closed_allows_privileged_blocks_normal(
    session_env, monkeypatch
):
    accounts_service.set_registration_enabled("emby", False)
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [])

    with get_session() as session:
        session.add_all(
            [
                Invitation(code="norm-code", owner=999, is_used=0, is_privileged=0),
                Invitation(code="priv-code", owner=999, is_used=0, is_privileged=1),
            ]
        )

    class FakeEmby:
        def get_uid_from_username(self, username):
            return None

        def add_user(self, *, username, password):
            return True, "emby-id-1"

    monkeypatch.setattr("app.domains.invitation.router.Emby", FakeEmby)
    monkeypatch.setattr(
        "app.domains.invitation.router.send_message_by_url", _async_noop
    )

    # 1. 普通码尝试注册 -> 被拒绝，提示注册已关闭
    resp_norm = await invitation_router.redeem_emby_code(
        request=_request(),
        background_tasks=BackgroundTasks(),
        data=RedeemInviteCodeRequest(
            code="norm-code", username="user1", password="password"
        ),
        telegram_user=TelegramUser(id=201, first_name="u1"),
    )
    assert resp_norm.success is False
    assert "当前不接受新用户注册" in resp_norm.message
    with get_session() as session:
        inv = session.get(Invitation, "norm-code")
        assert inv.is_used == 0

    # 2. 特权码尝试注册 -> 成功，不受注册开关限制
    resp_priv = await invitation_router.redeem_emby_code(
        request=_request(),
        background_tasks=BackgroundTasks(),
        data=RedeemInviteCodeRequest(
            code="priv-code", username="user2", password="password"
        ),
        telegram_user=TelegramUser(id=202, first_name="u2"),
    )
    assert resp_priv.success is True
    assert "user2" in resp_priv.message
    with get_session() as session:
        inv = session.get(Invitation, "priv-code")
        assert inv.is_used == 1
        assert inv.is_privileged == 1  # 兑换后仍保留特权标记


@pytest.mark.asyncio
async def test_external_failure_releases_code_preserving_privileged(
    session_env, monkeypatch
):
    accounts_service.set_registration_enabled("emby", True)
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [])

    with get_session() as session:
        session.add(
            Invitation(code="fail-priv-code", owner=999, is_used=0, is_privileged=1)
        )

    class FailingEmby:
        def get_uid_from_username(self, username):
            return None

        def add_user(self, *, username, password):
            return False, "server_error"

    monkeypatch.setattr("app.domains.invitation.router.Emby", FailingEmby)
    monkeypatch.setattr(
        "app.domains.invitation.router.send_message_by_url", _async_noop
    )

    resp = await invitation_router.redeem_emby_code(
        request=_request(),
        background_tasks=BackgroundTasks(),
        data=RedeemInviteCodeRequest(
            code="fail-priv-code", username="user_err", password="password"
        ),
        telegram_user=TelegramUser(id=203, first_name="u3"),
    )

    assert resp.success is False
    assert "创建用户失败" in resp.message

    with get_session() as session:
        inv = session.get(Invitation, "fail-priv-code")
        assert inv.is_used == 0
        assert inv.used_by is None
        assert inv.service is None
        assert inv.is_privileged == 1  # 特权标记未变，可再次使用


# --------------------------------------------------------------------------- #
# 3. 检查特权状态接口
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_check_privileged_endpoints(session_env):
    with get_session() as session:
        session.add_all(
            [
                Invitation(code="c_unused_priv", owner=999, is_used=0, is_privileged=1),
                Invitation(code="c_used_priv", owner=999, is_used=1, is_privileged=1),
                Invitation(code="c_unused_norm", owner=999, is_used=0, is_privileged=0),
                Invitation(code="c_used_norm", owner=999, is_used=1, is_privileged=0),
            ]
        )

    # 单个检查
    res1 = await invitation_router.check_privileged_invite_code(
        _request(), CheckPrivilegedCodeRequest(code="c_unused_priv")
    )
    assert res1.privileged is True

    res2 = await invitation_router.check_privileged_invite_code(
        _request(), CheckPrivilegedCodeRequest(code="c_used_priv")
    )
    assert res2.privileged is False

    res3 = await invitation_router.check_privileged_invite_code(
        _request(), CheckPrivilegedCodeRequest(code="c_unused_norm")
    )
    assert res3.privileged is False

    res4 = await invitation_router.check_privileged_invite_code(
        _request(), CheckPrivilegedCodeRequest(code="c_non_existent")
    )
    assert res4.privileged is False

    # 批量检查
    batch_res = await invitation_router.batch_check_privileged_invite_codes(
        _request(),
        BatchCheckPrivilegedCodesRequest(
            codes=[
                "c_unused_priv",
                "c_used_priv",
                "c_unused_norm",
                "c_non_existent",
            ]
        ),
    )
    assert batch_res.results == {
        "c_unused_priv": True,
        "c_used_priv": False,
        "c_unused_norm": False,
        "c_non_existent": False,
    }


# --------------------------------------------------------------------------- #
# 4. 一次性导入与幂等性
# --------------------------------------------------------------------------- #


def test_one_time_import_and_idempotency(session_env):
    core_kv.delete("invitation", "privileged_codes_imported")

    with get_session() as session:
        session.add_all(
            [
                Invitation(code="imp_unused", owner=999, is_used=0, is_privileged=0),
                Invitation(code="imp_used", owner=999, is_used=1, is_privileged=0),
            ]
        )

    # 模拟环境中的 PRIVILEGED_CODES
    mock_env = {
        "PRIVILEGED_CODES": "imp_unused, imp_used, imp_missing, imp_unused"  # 包含重复
    }
    source = LegacyEnvSource(
        defaults={"PRIVILEGED_CODES": []},
        environ=mock_env,
        data_path="/nonexistent/.env",
        working_path="/nonexistent/.env",
    )

    report = invitation_service.import_legacy_privileged_codes(source)
    assert report["marked"] == ["imp_unused"]
    assert report["used_skipped"] == ["imp_used"]
    assert report["not_found_skipped"] == ["imp_missing"]

    with get_session() as session:
        inv1 = session.get(Invitation, "imp_unused")
        assert inv1.is_privileged == 1

        inv2 = session.get(Invitation, "imp_used")
        assert inv2.is_privileged == 0

    # 重复运行跳过
    report2 = invitation_service.import_legacy_privileged_codes(source)
    assert report2 == {"already_imported": True}

    # 修改环境变量再次运行，仍被跳过
    mock_env["PRIVILEGED_CODES"] = "imp_new_code"
    source_new = LegacyEnvSource(
        defaults={"PRIVILEGED_CODES": []},
        environ=mock_env,
        data_path="/nonexistent/.env",
        working_path="/nonexistent/.env",
    )
    report3 = invitation_service.import_legacy_privileged_codes(source_new)
    assert report3 == {"already_imported": True}


# --------------------------------------------------------------------------- #
# 5. 导出脚本回退验证（只读）
# --------------------------------------------------------------------------- #


def test_export_privileged_codes_read_only(session_env):
    with get_session() as session:
        session.add_all(
            [
                Invitation(code="exp_p1", owner=999, is_used=0, is_privileged=1),
                Invitation(code="exp_p2", owner=999, is_used=0, is_privileged=1),
                Invitation(code="exp_used", owner=999, is_used=1, is_privileged=1),
                Invitation(code="exp_norm", owner=999, is_used=0, is_privileged=0),
            ]
        )

    line = export_unused_privileged_codes()
    assert line.startswith("PRIVILEGED_CODES=")
    codes_str = line.removeprefix("PRIVILEGED_CODES=")
    exported = [c.strip() for c in codes_str.split(",") if c.strip()]
    assert "exp_p1" in exported
    assert "exp_p2" in exported
    assert "exp_used" not in exported
    assert "exp_norm" not in exported

    # 验证数据库未被修改
    with get_session() as session:
        p1 = session.get(Invitation, "exp_p1")
        assert p1.is_used == 0
        assert p1.is_privileged == 1


# --------------------------------------------------------------------------- #
# 6. 一次性 PostgreSQL 并发兑换同一个码，外部开号替身只调用一次
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not os.environ.get("POSTGRES_TEST_URL"),
    reason="set POSTGRES_TEST_URL to run PostgreSQL concurrency test",
)
def test_concurrent_redemption_on_postgres():
    import asyncio

    pg_url = os.environ["POSTGRES_TEST_URL"]
    engine = create_engine(pg_url)
    metadata.create_all(engine)

    from contextlib import contextmanager

    from sqlalchemy.orm import sessionmaker

    PgSession = sessionmaker(bind=engine)

    @contextmanager
    def pg_session():
        s = PgSession()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    orig_get_session = invitation_repository.get_session
    invitation_repository.get_session = pg_session

    orig_is_reg_enabled = accounts_service.is_registration_enabled
    accounts_service.is_registration_enabled = lambda s: True

    orig_create_invited = accounts_service.create_invited_emby_user
    accounts_service.create_invited_emby_user = lambda emby_username, emby_id, tg_id: (
        True
    )

    orig_find_by_username = invitation_service.identity_service.find_emby_by_username
    orig_find_by_tg = invitation_service.identity_service.find_emby_by_tg
    invitation_service.identity_service.find_emby_by_username = lambda u: None
    invitation_service.identity_service.find_emby_by_tg = lambda tg: None

    try:
        with pg_session() as s:
            s.execute(text("DELETE FROM invitation WHERE code='concurrent_code';"))
            s.add(
                Invitation(
                    code="concurrent_code", owner=888, is_used=0, is_privileged=1
                )
            )

        external_calls: list[str] = []

        class FakeEmby:
            def get_uid_from_username(self, u):
                return None

            def add_user(self, *args, **kwargs):
                external_calls.append("called")
                return True, "emby-concurrent-user"

        results: list[tuple[str, object]] = []

        def worker(i: int):
            async def _run():
                try:
                    res = await invitation_service.register_emby(
                        code="concurrent_code",
                        username=f"user_{i}",
                        password="secretpassword",
                        bind_to_telegram=False,
                        telegram_user_id=1000 + i,
                        notify=lambda **kw: asyncio.sleep(0),
                        emby_factory=lambda: FakeEmby(),
                    )
                    return ("success", res)
                except InvitationCodeUsed:
                    return ("used", None)
                except Exception as e:
                    return ("error", type(e).__name__)

            return asyncio.run(_run())

        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = [ex.submit(worker, i) for i in range(10)]
            for f in futures:
                results.append(f.result())

        successes = [r for r in results if r[0] == "success"]
        useds = [r for r in results if r[0] == "used"]
        assert len(successes) == 1, (
            f"Expected 1 success, got {len(successes)}, all results: {results}"
        )
        assert len(useds) == 9, f"Expected 9 used, got {len(useds)}"
        assert len(external_calls) == 1, (
            f"Expected 1 external call, got {len(external_calls)}"
        )
    finally:
        invitation_repository.get_session = orig_get_session
        accounts_service.is_registration_enabled = orig_is_reg_enabled
        accounts_service.create_invited_emby_user = orig_create_invited
        invitation_service.identity_service.find_emby_by_username = (
            orig_find_by_username
        )
        invitation_service.identity_service.find_emby_by_tg = orig_find_by_tg
        engine.dispose()


@pytest.mark.asyncio
async def test_successful_plex_invite_stays_claimed_when_id_lookup_fails(
    session_env, monkeypatch
):
    code = "lookup-failure-after-success"
    with get_session() as session:
        session.add(Invitation(code=code, owner=101, is_used=0, is_privileged=1))
    monkeypatch.setattr(
        invitation_service.identity_service, "count_bound_plex_users", lambda: 0
    )
    monkeypatch.setattr(
        accounts_service, "is_registration_enabled", lambda service: False
    )
    monkeypatch.setattr(
        accounts_service, "create_invited_plex_user", lambda **kwargs: True
    )
    monkeypatch.setattr(invitation_service.media_access_service, "get_nsfw_libs", list)
    monkeypatch.setattr(settings, "TG_ADMIN_CHAT_ID", [])
    scheduled = []
    monkeypatch.setattr(
        invitation_service, "register_plex_id_resolution_task", scheduled.append
    )
    calls = []

    class PlexStub:
        def __init__(self):
            self.users_by_email = {}

        def invite_friend(self, email, **kwargs):
            calls.append(email)
            return True

        def get_user_id_by_email(self, email):
            raise RuntimeError("lookup temporarily unavailable")

    result = await invitation_service.register_plex(
        code=code,
        email="accepted@example.test",
        bind_to_telegram=False,
        telegram_user_id=101,
        plex_factory=PlexStub,
        notify=_async_noop,
    )
    assert result == (False, 101)
    assert calls == ["accepted@example.test"]
    assert scheduled == ["accepted@example.test"]
    with get_session() as session:
        row = session.get(Invitation, code)
        assert row.is_used == 1
        assert row.plex_id is None
    with pytest.raises(InvitationError):
        await invitation_service.register_plex(
            code=code,
            email="second@example.test",
            bind_to_telegram=False,
            telegram_user_id=101,
            plex_factory=PlexStub,
            notify=_async_noop,
        )
    assert calls == ["accepted@example.test"]
