"""Audit Emby playback limits and unauthorized full-library access.

Default is read-only. --apply requires a reviewed --input plan. Never changes
local entitlements, download permissions, protected accounts or unknown users.
Run with python -m scripts.reconcile_emby_template_permissions.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from app.core.config import settings
from app.domains.identity import rules as identity_rules
from app.domains.identity import service as identity_service
from app.domains.media_access import service as media_access_service

PLAYBACK = (
    "EnableAudioPlaybackTranscoding",
    "EnableVideoPlaybackTranscoding",
    "EnablePlaybackRemuxing",
)
SCOPE = ("EnableAllFolders", "EnabledFolders", "ExcludedSubFolders")


def request(method: str, path: str, **kwargs: Any) -> requests.Response:
    response = requests.request(
        method,
        settings.EMBY_BASE_URL.rstrip("/") + path,
        headers={"accept": "application/json", "X-Emby-Token": settings.EMBY_API_TOKEN},
        timeout=30,
        **kwargs,
    )
    response.raise_for_status()
    return response


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.touch(mode=0o600, exist_ok=True)
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.chmod(0o600)
    temporary.replace(path)


def read_user(user_id: str, name: str) -> dict:
    user = request("GET", f"/Users/{user_id}").json()
    if user.get("Id") != user_id or user.get("Name") != name:
        raise ValueError("Emby identity mismatch")
    if not isinstance(user.get("Policy"), dict):
        raise TypeError("missing policy")
    return user


def entitlement(user: dict) -> dict:
    name = user["Name"]
    policy = user["Policy"]
    if (
        name.casefold()
        in {settings.EMBY_USER_TEMPLATE.casefold(), settings.EMBY_ADMIN_USER.casefold()}
        or policy.get("IsAdministrator") is not False
    ):
        raise ValueError("protected_admin_or_template")
    account = identity_service.find_emby_by_username(name)
    if account is None or account.emby_id != user["Id"]:
        raise ValueError("missing_or_mismatched_database_identity")
    if account.tg_id in settings.TG_ADMIN_CHAT_ID:
        raise ValueError("protected_telegram_admin")
    if account.is_premium not in (0, 1) or account.emby_is_unlock not in (0, 1):
        raise ValueError("invalid_entitlement_flags")
    return {
        "premium": identity_rules.premium_active(
            account, datetime.now(settings.TZ), invalid_expiry=None
        ),
        "full_unlock": account.emby_is_unlock == 1,
    }


def context() -> tuple[list[dict], dict]:
    users = request("GET", "/Users").json()
    templates = [u for u in users if u.get("Name") == settings.EMBY_USER_TEMPLATE]
    if len(templates) != 1:
        raise ValueError("no unique template")
    template = read_user(templates[0]["Id"], templates[0]["Name"])
    policy = template["Policy"]
    if (
        policy.get("IsAdministrator") is not False
        or policy.get("EnableAllFolders") is not False
    ):
        raise ValueError("unsafe template")
    if any(policy.get(key) is not False for key in PLAYBACK):
        raise ValueError("template playback policy changed; review required")
    if (
        type(policy.get("SimultaneousStreamLimit")) is not int
        or policy["SimultaneousStreamLimit"] <= 0
    ):
        raise ValueError("template must have a positive stream limit")
    libraries = request("GET", "/Library/SelectableMediaFolders").json()
    restricted_names = media_access_service.get_nsfw_libs()
    restricted = [lib for lib in libraries if lib["Name"] in restricted_names]
    if not restricted_names or {lib["Name"] for lib in restricted} != set(
        restricted_names
    ):
        raise ValueError("restricted library catalog incomplete")
    restricted_ids = sorted(lib["Guid"] for lib in restricted)
    folders = policy.get("EnabledFolders")
    if (
        not isinstance(folders, list)
        or not folders
        or not set(folders) <= {lib["Guid"] for lib in libraries}
    ):
        raise ValueError("invalid template library scope")
    if set(folders) & set(restricted_ids):
        raise ValueError("template includes restricted libraries")
    exclusions = sorted(
        f"{lib['Guid']}_{sub['Id']}" for lib in restricted for sub in lib["SubFolders"]
    )
    return users, {
        "template_id": template["Id"],
        "template_policy": policy,
        "restricted_ids": restricted_ids,
        "restricted_subfolders": exclusions,
    }


def changes(policy: dict, access: dict, ctx: dict) -> dict:
    template = ctx["template_policy"]
    patch = {}
    for key in PLAYBACK:
        if type(policy.get(key)) is not bool:
            raise ValueError(f"unknown policy field {key}")
        if policy[key] is True:
            patch[key] = False
    limit = policy.get("SimultaneousStreamLimit")
    if type(limit) is not int or limit < 0:
        raise ValueError("unknown stream limit")
    if limit == 0 or limit > template["SimultaneousStreamLimit"]:
        patch["SimultaneousStreamLimit"] = template["SimultaneousStreamLimit"]
    if type(policy.get("EnableAllFolders")) is not bool:
        raise ValueError("unknown library scope")
    if not all(isinstance(policy.get(key), list) for key in SCOPE[1:]):
        raise ValueError("unknown library restrictions")
    if not access["premium"] and not access["full_unlock"]:
        if policy["EnableAllFolders"]:
            patch["EnableAllFolders"] = False
            patch["EnabledFolders"] = deepcopy(template["EnabledFolders"])
        elif set(policy["EnabledFolders"]) & set(ctx["restricted_ids"]):
            patch["EnabledFolders"] = [
                value
                for value in policy["EnabledFolders"]
                if value not in ctx["restricted_ids"]
            ]
        if "EnabledFolders" in patch:
            patch["ExcludedSubFolders"] = sorted(
                set(policy["ExcludedSubFolders"])
                | set(template["ExcludedSubFolders"])
                | set(ctx["restricted_subfolders"])
            )
    return {key: value for key, value in patch.items() if policy[key] != value}


def audit() -> dict:
    users, ctx = context()
    report = {
        "service": "emby_template_permissions",
        "generated_at": datetime.now(settings.TZ).isoformat(),
        "context": ctx,
        "scanned": len(users),
        "items": [],
        "skipped": [],
        "matched": 0,
    }
    for user in users:
        try:
            access = entitlement(user)
            patch = changes(user["Policy"], access, ctx)
            if not patch:
                report["matched"] += 1
                continue
            report["items"].append(
                {
                    "id": user["Id"],
                    "name": user["Name"],
                    "access": access,
                    "before": user["Policy"],
                    "changes": patch,
                }
            )
        except Exception as error:
            report["skipped"].append({"name": user["Name"], "reason": str(error)})
    return report


def write_verified(user_id: str, name: str, policy: dict) -> dict:
    error = None
    try:
        request("POST", f"/Users/{user_id}/Policy", json=policy)
    except Exception as exc:
        error = exc
    actual = read_user(user_id, name)
    if actual["Policy"] != policy:
        raise RuntimeError("complete policy readback mismatch") from error
    return actual


def apply(plan: dict, output: Path) -> int:
    _, ctx = context()
    if plan.get("service") != "emby_template_permissions" or plan.get("context") != ctx:
        raise ValueError("template/catalog changed or invalid plan; re-audit")
    items = plan["items"]
    if len({item["id"] for item in items}) != len(items):
        raise ValueError("duplicate users in plan")
    report = {
        "service": plan["service"],
        "started_at": datetime.now(settings.TZ).isoformat(),
        "results": [],
    }
    save(output, report)
    for item in items:
        result = {"id": item["id"], "name": item["name"], "status": "pending"}
        report["results"].append(result)
        try:
            user = read_user(item["id"], item["name"])
            access = entitlement(user)
            patch = changes(user["Policy"], access, ctx)
            if not patch:
                result["status"] = "already_satisfied"
            elif (
                user["Policy"] != item["before"]
                or patch != item["changes"]
                or access != item["access"]
            ):
                result["status"] = "skipped_state_changed"
            else:
                result.update(before=user["Policy"], changes=patch, access=access)
                save(
                    output, report
                )  # Persist the exact rollback snapshot before writing.
                desired = {**user["Policy"], **patch}
                after = write_verified(item["id"], item["name"], desired)
                fresh_access = entitlement(after)
                if any(key in patch for key in SCOPE) and (
                    fresh_access["premium"] or fresh_access["full_unlock"]
                ):
                    # A concurrent grant must not lose the original library access.
                    desired.update({key: user["Policy"][key] for key in SCOPE})
                    after = write_verified(item["id"], item["name"], desired)
                    result["restored_scope_for_concurrent_grant"] = True
                result.update(status="verified", after=after["Policy"])
        except Exception as error:
            result.update(status="failed", error=f"{type(error).__name__}: {error}")
            save(output, report)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return 1  # Stop rather than spreading an unexpected server failure.
        save(output, report)
        print(
            json.dumps(
                {"name": result["name"], "status": result["status"]}, ensure_ascii=False
            ),
            flush=True,
        )
    print(json.dumps(dict(Counter(row["status"] for row in report["results"]))))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.apply:
        if args.input is None or args.input.resolve() == args.output.resolve():
            parser.error("apply requires a reviewed input and a separate output")
        return apply(json.loads(args.input.read_text()), args.output)
    report = audit()
    save(args.output, report)
    print(
        json.dumps(
            {
                "scanned": report["scanned"],
                "matched": report["matched"],
                "planned": len(report["items"]),
                "skipped": report["skipped"],
                "field_counts": dict(
                    Counter(key for item in report["items"] for key in item["changes"])
                ),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
