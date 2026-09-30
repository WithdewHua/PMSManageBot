"""Rehearse move-privileged-codes-to-database against PostgreSQL production-shaped replica.

Usage:
    python -m scripts.refactor.rehearse_privileged_codes \
        --url postgresql+psycopg2://postgres:testpass@127.0.0.1:55499/pms_test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


PRODUCTION_CODES_SHAPE = [
    {
        "code": "49c23436b9203092b0ef494daf8c4523",
        "owner": 1986559911,
        "is_used": 0,
        "used_by": None,
    },
    {
        "code": "65c39f604d2c3e77a2237661ee6b6846",
        "owner": 234886189,
        "is_used": 0,
        "used_by": None,
    },
    {
        "code": "c26b372aa0193f19a715457d3b983f6d",
        "owner": 1986559911,
        "is_used": 0,
        "used_by": None,
    },
    {
        "code": "4d90bb4a037f3247b16b68f27aa96358",
        "owner": 739052768,
        "is_used": 1,
        "used_by": "credits_by_739052768",
    },
    {
        "code": "f91633eb4dd034a981bd6385c096ddeb",
        "owner": 234886189,
        "is_used": 0,
        "used_by": None,
    },
    {
        "code": "3b6820718bd537d0b4af13fce080c625",
        "owner": 447960583,
        "is_used": 1,
        "used_by": "7969521@gmail.com",
    },
]


def run_rehearsal_pg(
    pg_url: str,
    *,
    verbose: bool = True,
) -> dict[str, object]:
    """Execute isolated rehearsal on PostgreSQL."""
    temp_dir = Path(tempfile.mkdtemp(prefix="pms-rehearsal-pg-"))
    isolated_env = temp_dir / ".env"

    env_codes = [c["code"] for c in PRODUCTION_CODES_SHAPE]
    isolated_env.write_text(
        f"PRIVILEGED_CODES={','.join(env_codes)}\n",
        encoding="utf-8",
    )

    os.environ["DATA_DIR"] = str(temp_dir)
    os.environ["DATABASE_TYPE"] = "postgresql"
    os.environ["DATABASE_URL"] = pg_url
    os.environ["TG_ADMIN_CHAT_ID"] = ""
    os.environ["WEBAPP_DEV_MOCK_AUTH"] = "true"

    import fakeredis
    from sqlalchemy import create_engine, delete, text
    from sqlalchemy.orm import sessionmaker

    import app.core.cache as cache_module
    import app.core.db as db_module
    from app.core import kv as core_kv
    from app.core.legacy_env import LegacyEnvSource
    from app.domains.accounts import service as accounts_service
    from app.domains.identity.models import EmbyUser, Statistics
    from app.domains.invitation import service as invitation_service
    from app.domains.invitation.models import Invitation
    from app.model_registry import metadata

    fake_redis = fakeredis.FakeRedis()
    cache_module.redis_client = fake_redis
    import app.domains.identity.cache as identity_cache

    identity_cache.user_info_cache.put = lambda *a, **k: None

    engine = create_engine(
        pg_url,
        pool_size=10,
        max_overflow=10,
        pool_pre_ping=True,
    )
    metadata.create_all(engine)
    db_module.engine = engine
    db_module.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )

    # Clean previous rehearsal state for the test codes
    with db_module.get_session() as session:
        session.execute(
            delete(EmbyUser).where(EmbyUser.emby_username == "rehearsal_pg_user")
        )
        core_kv.delete_tx(session, "invitation", "privileged_codes_imported")
        unique_owners = {item["owner"] for item in PRODUCTION_CODES_SHAPE}
        for owner_id in unique_owners:
            if (
                session.execute(
                    text(f"SELECT tg_id FROM statistics WHERE tg_id={owner_id}")
                ).fetchone()
                is None
            ):
                session.add(Statistics(tg_id=owner_id, credits=100, donation=0))

        for item in PRODUCTION_CODES_SHAPE:
            session.execute(delete(Invitation).where(Invitation.code == item["code"]))

        # Seed the production-shaped invitations
        for item in PRODUCTION_CODES_SHAPE:
            session.add(
                Invitation(
                    code=item["code"],
                    owner=item["owner"],
                    is_used=item["is_used"],
                    used_by=item["used_by"],
                    is_privileged=0,
                )
            )

    env_source = LegacyEnvSource(
        defaults={"PRIVILEGED_CODES": []},
        environ={},
        data_path=str(isolated_env),
        working_path=str(isolated_env),
    )

    # 1. Execute one-time import
    import_summary = invitation_service.import_legacy_privileged_codes(env_source)

    # Check imported summary
    expected_marked = [
        "49c23436b9203092b0ef494daf8c4523",
        "65c39f604d2c3e77a2237661ee6b6846",
        "c26b372aa0193f19a715457d3b983f6d",
        "f91633eb4dd034a981bd6385c096ddeb",
    ]
    expected_used = [
        "4d90bb4a037f3247b16b68f27aa96358",
        "3b6820718bd537d0b4af13fce080c625",
    ]
    assert sorted(import_summary["marked"]) == sorted(expected_marked)
    assert sorted(import_summary["used_skipped"]) == sorted(expected_used)
    assert import_summary["not_found_skipped"] == []

    # 2. Pick a marked code and test registration with registration closed
    test_code = expected_marked[0]
    accounts_service.set_registration_enabled("emby", False)

    class FakeEmby:
        def get_uid_from_username(self, u):
            return None

        def add_user(self, *, username, password):
            return True, "emby-user-rehearsal"

    async def _do_register():
        return await invitation_service.register_emby(
            code=test_code,
            username="rehearsal_pg_user",
            password="secure_password_123",
            bind_to_telegram=False,
            telegram_user_id=888999,
            notify=lambda **kw: asyncio.sleep(0),
            emby_factory=lambda: FakeEmby(),
        )

    _telegram_bound, _owner, _password = asyncio.run(_do_register())

    # Verify invitation row after registration
    with db_module.get_session() as session:
        inv = session.get(Invitation, test_code)
        assert inv is not None
        assert inv.is_used == 1
        assert inv.is_privileged == 1
        assert inv.service == "emby"
        assert inv.emby_id == "emby-user-rehearsal"

    # Verify isolated .env was untouched
    env_content = isolated_env.read_text(encoding="utf-8")
    assert "PRIVILEGED_CODES=" in env_content

    # Verify marker in core_kv
    marker = core_kv.get("invitation", "privileged_codes_imported")
    assert marker is not None

    report = {
        "ok": True,
        "database": "postgresql",
        "import_summary": import_summary,
        "registration_verification": {
            "code": test_code,
            "registered": True,
            "retained_privileged": True,
            "service": "emby",
        },
        "env_untouched": True,
    }

    if verbose:
        print(json.dumps(report, indent=2, ensure_ascii=False))

    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)
    engine.dispose()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="postgresql+psycopg2://postgres:testpass@127.0.0.1:55499/pms_test",
        help="PostgreSQL URL for rehearsal",
    )
    args = parser.parse_args()

    report = run_rehearsal_pg(args.url, verbose=True)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
