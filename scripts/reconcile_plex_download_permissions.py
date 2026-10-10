"""Read-only Plex download audit; apply only an explicit reviewed JSON plan.

Database entitlements are authoritative. Never copy live permissions into the
permanent-unlock columns. Revocations reuse list_expired_download_holders.
Run with ``python -m scripts.reconcile_plex_download_permissions``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.domains.identity import rules as identity_rules
from app.domains.identity import service as identity_service
from app.domains.identity.types import PlexAccount
from app.integrations.plex import Plex
from scripts import list_expired_download_holders as expired_holders


def expected_permission(account: PlexAccount, now: datetime) -> tuple[bool | None, str]:
    """None means insufficient evidence to revoke a manually managed grant."""
    if account.is_premium not in (0, 1) or account.sync_unlocked not in (0, 1):
        raise ValueError("invalid persisted permission flags")
    premium = identity_rules.premium_active(account, now, invalid_expiry=None)
    if account.sync_unlocked == 1 and account.sync_unlock_time is None:
        raise ValueError("permanent unlock flag has no unlock timestamp")
    if premium:
        return True, "active_premium"
    if account.sync_unlocked == 1:
        return True, "permanent_download_unlock"
    if (
        account.is_premium == 1
        or account.premium_expiry_time
        or account.premium_status_updated_at is not None
    ):
        return False, "inactive_premium_without_permanent_unlock"
    return None, "no_premium_history_or_permanent_unlock"


def protected(account: PlexAccount, owner_id: float | None) -> bool:
    return (
        account.plex_id == owner_id
        or (account.plex_email or "").casefold() == settings.PLEX_ADMIN_EMAIL.casefold()
        or (account.plex_username or "").casefold()
        == settings.PLEX_ADMIN_USER.casefold()
        or (account.tg_id is not None and account.tg_id in settings.TG_ADMIN_CHAT_ID)
    )


def read_state(
    client: Plex,
    user_id: int,
    expected_email: str,
    *,
    users: dict[int, Any] | None = None,
) -> dict[str, Any]:
    """Query the exact current server share, not the cached allowSync field."""
    user = (
        users.get(user_id)
        if users is not None
        else next((u for u in client.my_plex_account.users() if u.id == user_id), None)
    )
    if user is None:
        raise ValueError("Plex user not present in current sharing list")
    if (user.email or "").casefold() != expected_email.casefold():
        raise ValueError("database and Plex email identities do not match")
    shares = [
        s
        for s in user.servers
        if s.machineIdentifier == client.plex_server.machineIdentifier
    ]
    if len(shares) != 1:
        raise ValueError("no unique share for the current server")
    url = (
        f"{settings.PLEX_TV_BASE_URL.rstrip('/')}/api/v2/shared_servers/{shares[0].id}"
    )
    permissions, libraries, all_libraries = client._read_sharing_state(url, user_id)
    return {
        "allowSync": permissions["allowSync"] == "1",
        "settings": permissions,
        "library_ids": sorted(libraries),
        "allLibraries": all_libraries,
    }


def audit(client: Plex) -> dict[str, Any]:
    report: dict[str, Any] = {
        "service": "plex",
        "generated_at": datetime.now(settings.TZ).isoformat(),
        "scanned": 0,
        "matched": 0,
        "items": [],
        "skipped": [],
    }
    users = {user.id: user for user in client.my_plex_account.users()}
    for user_id in sorted(identity_service.list_plex_ids()):
        report["scanned"] += 1
        try:
            account = identity_service.find_plex_by_id(user_id)
            if account is None or not account.plex_email:
                raise ValueError("missing database account or email")
            if protected(account, client.my_plex_account.id):
                report["skipped"].append(
                    {"plex_id": user_id, "reason": "protected_admin"}
                )
                continue
            expected, reason = expected_permission(account, datetime.now(settings.TZ))
            if expected is None:
                report["skipped"].append({"plex_id": user_id, "reason": reason})
                continue
            state = read_state(client, user_id, account.plex_email, users=users)
            if state["allowSync"] == expected:
                report["matched"] += 1
                continue
            report["items"].append(
                {
                    "plex_id": user_id,
                    "tg_id": account.tg_id,
                    "username": account.plex_username,
                    "target": account.plex_email,
                    "expected": expected,
                    "reason": reason,
                    "before": state,
                }
            )
        except Exception as error:
            report["skipped"].append(
                {"plex_id": user_id, "reason": f"{type(error).__name__}: {error}"}
            )
    return report


def apply_item(client: Plex, item: dict[str, Any]) -> dict[str, Any]:
    """Recheck entitlements before and after a post-commit permission change."""
    user_id = int(item["plex_id"])
    account = identity_service.find_plex_by_id(user_id)
    if (
        account is None
        or not account.plex_email
        or protected(account, client.my_plex_account.id)
    ):
        raise ValueError("account missing or protected")
    if (account.plex_email or "").casefold() != str(item["target"]).casefold():
        raise ValueError("account identity changed since audit")
    desired, reason = expected_permission(account, datetime.now(settings.TZ))
    if desired is None or desired is not item["expected"]:
        return {"plex_id": user_id, "status": "skipped_entitlement_changed"}
    before = read_state(client, user_id, account.plex_email)
    if before["allowSync"] != desired:
        if desired:
            if not client.update_sync_for_user(account.plex_email, allow_sync=True):
                raise RuntimeError("Plex download enable failed")
        else:
            # Reuse the established explicit-holder revocation entry point.
            expired_holders.revoke_download_holder(
                {"service": "plex", "target": account.plex_email}
            )
    fresh_account = identity_service.find_plex_by_id(user_id)
    if fresh_account is None or fresh_account.plex_email != account.plex_email:
        raise ValueError("account identity changed during repair")
    fresh_desired, _ = expected_permission(fresh_account, datetime.now(settings.TZ))
    if fresh_desired is None:
        raise ValueError("entitlement became indeterminate during repair")
    if fresh_desired != desired and not client.update_sync_for_user(
        account.plex_email, allow_sync=fresh_desired
    ):
        raise RuntimeError("concurrent entitlement change repair failed")
    after = read_state(client, user_id, account.plex_email)
    if after["allowSync"] != fresh_desired:
        raise RuntimeError("fresh readback does not match current entitlement")
    for name in ("library_ids", "allLibraries"):
        if before[name] != after[name]:
            raise RuntimeError("media library scope changed during repair")
    if {k: v for k, v in before["settings"].items() if k != "allowSync"} != {
        k: v for k, v in after["settings"].items() if k != "allowSync"
    }:
        raise RuntimeError("other sharing restrictions changed during repair")
    return {"plex_id": user_id, "status": "verified", "reason": reason, "after": after}


def save_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--input", type=Path, help="Reviewed audit JSON; required for apply"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.apply and args.input is None:
        parser.error("--apply requires --input")
    client = Plex()
    if not args.apply:
        report = audit(client)
        save_report(args.output, report)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "scanned": report["scanned"],
                    "matched": report["matched"],
                    "planned": len(report["items"]),
                    "categories": dict(
                        Counter(item["reason"] for item in report["items"])
                    ),
                    "skipped": len(report["skipped"]),
                },
                ensure_ascii=False,
            )
        )
        return 0
    plan = json.loads(args.input.read_text(encoding="utf-8"))
    if plan.get("service") != "plex" or not isinstance(plan.get("items"), list):
        raise ValueError("invalid Plex audit plan")
    results: dict[str, Any] = {"service": "plex", "results": []}
    save_report(args.output, results)
    for item in plan["items"]:
        try:
            result = apply_item(client, item)
        except Exception as error:
            result = {
                "plex_id": item.get("plex_id"),
                "status": "failed",
                "error": f"{type(error).__name__}: {error}",
            }
        results["results"].append(result)
        save_report(args.output, results)
        print(
            json.dumps(
                {k: v for k, v in result.items() if k != "after"}, ensure_ascii=False
            ),
            flush=True,
        )
    counts = Counter(row["status"] for row in results["results"])
    print(
        json.dumps(
            {"output": str(args.output), "counts": dict(counts)}, ensure_ascii=False
        )
    )
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
