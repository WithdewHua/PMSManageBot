"""The dangling Telegram ID audit remains read-only and registration-driven."""

from __future__ import annotations

import pytest
from sqlalchemy import event, select

from app.core.db import Base, get_session
from app.domains.donation.models import DonationRegistrations
from app.domains.gift_pack.models import GiftPack
from app.domains.identity.models import Statistics
from app.domains.invitation.models import Invitation
from app.domains.watch_rewards.models import WatchRewardSettlement
from scripts.check_dangling_tg_ids import collect_dangling_tg_ids, main


def test_dangling_audit_finds_numeric_and_encoded_ids(session_env):
    """Ensure audit finds numeric user/admin/inviter columns and encoded invitation/gift fields,

    while correctly ignoring null/nonpositive sentinels, handling nested invalid audience data,
    and detecting legitimate numeric string IDs in JSON audience.
    """
    valid_user = 10001
    dangling_user = 991234
    dangling_admin = 991235
    dangling_inviter = 991236
    dangling_gift_str = 991237
    dangling_gift_int = 991238

    with get_session() as session:
        # 1. Existing valid user in statistics
        session.add(Statistics(tg_id=valid_user, donation=0, credits=100))

        # 2. Donation registrations with dangling user and admin
        session.add(
            DonationRegistrations(
                id=1,
                user_id=dangling_user,
                payment_method="other",
                amount=1,
                status="pending",
                created_at="2026-09-01",
            )
        )
        session.add(
            DonationRegistrations(
                id=2,
                user_id=valid_user,
                processed_by=dangling_admin,
                payment_method="other",
                amount=1,
                status="approved",
                created_at="2026-09-01",
            )
        )

        # 3. Watch reward settlements covering tg_id, inviter_tg_id, and sentinels
        session.add(
            WatchRewardSettlement(
                id=1,
                service="plex",
                account_key="acc_dangling",
                settlement_date="2026-09-01",
                tg_id=dangling_user,
                credits_delta=10.0,
                premium_charge=0.0,
                inviter_tg_id=dangling_inviter,
                inviter_bonus=5.0,
                created_at=1000000,
            )
        )
        session.add(
            WatchRewardSettlement(
                id=2,
                service="plex",
                account_key="acc_sentinels",
                settlement_date="2026-09-02",
                tg_id=None,  # Null sentinel ignored
                credits_delta=0.0,
                premium_charge=0.0,
                inviter_tg_id=0,  # Zero sentinel ignored
                inviter_bonus=0.0,
                created_at=1000000,
            )
        )
        session.add(
            WatchRewardSettlement(
                id=3,
                service="plex",
                account_key="acc_negative",
                settlement_date="2026-09-03",
                tg_id=-1,  # Negative sentinel ignored
                credits_delta=0.0,
                premium_charge=0.0,
                inviter_tg_id=-99,  # Negative sentinel ignored
                inviter_bonus=0.0,
                created_at=1000000,
            )
        )

        # 4. Invitation records: owner, credits_by_<id>, sentinels, emails, invalid strings
        session.add(
            Invitation(
                code="dang-inv-1",
                owner=dangling_user,
                used_by=f"credits_by_{dangling_user}",
            )
        )
        session.add(
            Invitation(
                code="valid-inv-2",
                owner=valid_user,
                used_by=f"credits_by_{valid_user}",
            )
        )
        session.add(
            Invitation(
                code="sentinel-inv-3",
                owner=valid_user,
                used_by="credits_by_0",  # Zero sentinel ignored
            )
        )
        session.add(
            Invitation(
                code="email-inv-4",
                owner=valid_user,
                used_by="plex_user@example.com",
                service="plex",
            )
        )
        session.add(
            Invitation(
                code="invalid-inv-5",
                owner=valid_user,
                used_by="credits_by_not_a_number",  # Non-integer handled safely
            )
        )

        # 5. Gift pack audience: legitimate string and int IDs, sentinels, malformed JSON
        session.add(
            GiftPack(
                id=1,
                title="pack-mixed-audience",
                description=None,
                rewards="[]",
                audience=(
                    f'[{{"type":"user_list","mode":"include","tg_ids":['
                    f'{dangling_gift_int}, "{dangling_gift_str}", {valid_user}, '
                    f'0, -1, null, "not_a_number", {{}}]}}]'
                ),
                requirements=None,
                task_end_at=None,
                total_quantity=None,
                claimed_count=0,
                start_at=1,
                end_at=2,
                max_prompt_count=1,
                max_task_prompt_count=0,
                notify_audience_on_start=0,
                is_enabled=1,
                expiry_notified=0,
                created_by=None,
                created_at=1,
                updated_at=1,
            )
        )
        session.add(
            GiftPack(
                id=2,
                title="pack-malformed-json",
                description=None,
                rewards="[]",
                audience="{malformed_json_syntax: [[[",  # Handled without crashing
                requirements=None,
                task_end_at=None,
                total_quantity=None,
                claimed_count=0,
                start_at=1,
                end_at=2,
                max_prompt_count=1,
                max_task_prompt_count=0,
                notify_audience_on_start=0,
                is_enabled=1,
                expiry_notified=0,
                created_by=None,
                created_at=1,
                updated_at=1,
            )
        )
        session.add(
            GiftPack(
                id=3,
                title="pack-null-audience",
                description=None,
                rewards="[]",
                audience=None,
                requirements=None,
                task_end_at=None,
                total_quantity=None,
                claimed_count=0,
                start_at=1,
                end_at=2,
                max_prompt_count=1,
                max_task_prompt_count=0,
                notify_audience_on_start=0,
                is_enabled=1,
                expiry_notified=0,
                created_by=None,
                created_at=1,
                updated_at=1,
            )
        )

    # Execute audit with engine passed directly (database_url optional)
    report = collect_dangling_tg_ids(engine=session_env)

    # Assert expected detections
    assert report["donation_registrations.user_id"] == [dangling_user]
    assert report["donation_registrations.processed_by"] == [dangling_admin]
    assert report["watch_reward_settlement.tg_id"] == [dangling_user]
    assert report["watch_reward_settlement.inviter_tg_id"] == [dangling_inviter]
    assert report["invitation.owner"] == [dangling_user]
    assert report["invitation.used_by:credits_by_"] == [dangling_user]
    assert report["gift_pack.audience:user_list.tg_ids"] == [
        dangling_gift_str,
        dangling_gift_int,
    ]

    # Assert sentinels and valid IDs are excluded everywhere
    all_reported = {tg_id for ids in report.values() for tg_id in ids}
    assert valid_user not in all_reported
    assert 0 not in all_reported
    assert -1 not in all_reported
    assert -99 not in all_reported


def test_dangling_audit_is_strictly_read_only(session_env):
    """Ensure audit issues only read-only statements and leaves table contents unchanged."""
    executed_sql: list[str] = []

    def before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        stmt = statement.strip().upper()
        executed_sql.append(stmt)

    event.listen(session_env, "before_cursor_execute", before_cursor_execute)

    # Take full database fingerprint before audit
    fingerprint_before: dict[str, list[tuple]] = {}
    with session_env.connect() as conn:
        for table in Base.metadata.tables.values():
            rows = conn.execute(select(table)).fetchall()
            fingerprint_before[table.name] = sorted(rows)

    try:
        collect_dangling_tg_ids(engine=session_env)
    finally:
        event.remove(session_env, "before_cursor_execute", before_cursor_execute)

    # 1. Assert only read operations were executed
    allowed_prefixes = ("SELECT", "PRAGMA", "SET", "ROLLBACK", "COMMIT")
    disallowed_prefixes = (
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE",
        "REPLACE",
    )

    for stmt in executed_sql:
        assert any(stmt.startswith(prefix) for prefix in allowed_prefixes), (
            f"Unexpected non-read SQL statement executed: {stmt}"
        )
        assert not any(stmt.startswith(prefix) for prefix in disallowed_prefixes), (
            f"Mutating SQL statement detected: {stmt}"
        )

    # 2. Assert full database fingerprint unchanged
    fingerprint_after: dict[str, list[tuple]] = {}
    with session_env.connect() as conn:
        for table in Base.metadata.tables.values():
            rows = conn.execute(select(table)).fetchall()
            fingerprint_after[table.name] = sorted(rows)

    assert fingerprint_before == fingerprint_after


def test_collect_dangling_tg_ids_requires_url_or_engine():
    with pytest.raises(
        ValueError, match="Either database_url or engine must be provided"
    ):
        collect_dangling_tg_ids(None, engine=None)


def test_cli_help_does_not_load_secrets(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert "--database-url" in captured.out
