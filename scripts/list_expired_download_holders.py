"""List and, explicitly, revoke stale permanent download permissions.

The default mode is read-only.  ``--apply`` requires a JSON input file produced
by the read-only scan (or supplied by a maintainer) and only processes those
listed rows; it never performs a broad reconciliation against the database.

This is deliberately separate from ``sync_download_permissions.py``.  That
script is a one-way server-to-database synchronizer and must not be used as an
accounting or revocation reconciliation job.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.db import get_session
from app.domains.identity.models import EmbyUser, PlexUser
from app.integrations.emby import Emby
from app.integrations.plex import Plex


def _expired(expiry: str | None, now: datetime) -> bool:
    if not expiry:
        return True
    try:
        parsed = datetime.fromisoformat(str(expiry)).astimezone(settings.TZ)
    except ValueError:
        parsed = datetime.fromtimestamp(float(expiry), tz=settings.TZ)
    return parsed <= now


def list_expired_download_holders() -> list[dict[str, Any]]:
    """Return stale permanent download holders without writing or calling APIs."""
    now = datetime.now(settings.TZ)
    holders: list[dict[str, Any]] = []
    with get_session() as session:
        for row in session.execute(
            select(PlexUser).where(PlexUser.sync_unlocked == 1)
        ).scalars():
            if _expired(row.premium_expiry_time, now):
                holders.append(
                    {
                        "service": "plex",
                        "tg_id": row.tg_id,
                        "target": row.plex_email,
                        "username": row.plex_username,
                    }
                )
        for row in session.execute(
            select(EmbyUser).where(EmbyUser.download_unlocked == 1)
        ).scalars():
            if _expired(row.premium_expiry_time, now):
                holders.append(
                    {
                        "service": "emby",
                        "tg_id": row.tg_id,
                        "target": row.emby_id,
                        "username": row.emby_username,
                    }
                )
    return holders


def revoke_download_holder(holder: dict[str, Any]) -> None:
    """Revoke one explicitly supplied holder on its media server."""
    service = str(holder.get("service"))
    target = holder.get("target")
    if not target:
        raise ValueError("名单项缺少 target")
    if service == "plex":
        if not Plex().update_sync_for_user(str(target), allow_sync=False):
            raise RuntimeError(f"Plex 权限撤销失败: {target}")
    elif service == "emby":
        result = Emby().update_download_permission_for_user(
            str(target), allow_download=False
        )
        if isinstance(result, tuple) and not result[0]:
            raise RuntimeError(f"Emby 权限撤销失败: {target}: {result[1]}")
        if result is False:
            raise RuntimeError(f"Emby 权限撤销失败: {target}")
    else:
        raise ValueError(f"不支持的服务类型: {service}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="执行输入名单中的媒体服务器权限撤销（不会扫描并批量应用）",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="--apply 使用的 JSON 名单；默认扫描模式会把结果写到标准输出",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.apply:
        print(json.dumps(list_expired_download_holders(), ensure_ascii=False, indent=2))
        return 0
    if args.input is None:
        raise SystemExit("--apply 必须同时指定 --input")
    holders = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(holders, list):
        raise SystemExit("名单必须是 JSON 数组")
    for holder in holders:
        revoke_download_holder(dict(holder))
    print(f"已处理 {len(holders)} 个名单项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
