#!/usr/bin/env python3
"""Production-shaped read-model rehearsal comparison script (Task 5.1).

Compares read-model domains (rankings, reports, profile) between baseline
(commit 761b0a5) and current checkout on a disposable PostgreSQL copy.

Strict isolation & safety constraints:
- Outbound socket guard: ONLY designated local PostgreSQL port is permitted.
- URL validation: Host must be localhost/127.0.0.1, port must match allowed_port,
  and database name must start with 'pms_test_remaining_compare_'.
- Immutable read-only transactions: Enforced at PostgreSQL engine level via
  'default_transaction_read_only=on'.
- Table state invariance: Full-table fingerprints (count + checksum) across all tables
  are verified before and after the rehearsal run.
- Zero production Telegram IDs: Representative users and profile caches are dynamically
  derived from read-only queries with synthetic names and generic sentinels.
- Identically frozen clock: Timestamp and datetime boundaries match across old and new.
- Serialization parity: Results are encoded via FastAPI jsonable_encoder before diffing.
- Subprocess isolation: Executed in work_dir with dummy config; never loads source_dir/data/.env.
- Failure policy: Returns non-zero exit code if any semantic difference is detected.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

DEFAULT_BASELINE_DIR = "/tmp/pms-remaining-baseline-761b0a5"
DEFAULT_WORK_DIR = "/tmp/pms-remaining-rehearsal"
DEFAULT_PG_URL = "postgresql+psycopg2://postgres:local-rehearsal-only@127.0.0.1:32768/pms_test_remaining_compare_proto"
DEFAULT_ALLOWED_PORT = 32768

SENTINEL_ADMIN_TG_ID = 100000001
SENTINEL_ADMIN_TG_ID_2 = 100000002
SENTINEL_UNBOUND_TG_ID = 999999999


def install_socket_guard(
    allowed_port: int,
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost"),
) -> Callable:
    """Install an outbound socket guard allowing only specific host/port."""
    orig_connect = socket.socket.connect

    def guarded_connect(self, address):
        host, port = address[0], address[1]
        if host in allowed_hosts and port == allowed_port:
            return orig_connect(self, address)
        raise RuntimeError(
            f"OUTBOUND NETWORK BLOCKED by socket guard: {address} (allowed port: {allowed_port})"
        )

    socket.socket.connect = guarded_connect
    return orig_connect


def validate_rehearsal_database_url(
    url: str, allowed_port: int = DEFAULT_ALLOWED_PORT
) -> str:
    """Validate database safety constraints and enforce read-only transaction mode."""
    parsed = make_url(url)
    if parsed.host not in ("127.0.0.1", "localhost"):
        raise ValueError(
            f"Safety violation: rehearsal database host must be localhost/127.0.0.1, got '{parsed.host}'"
        )
    actual_port = parsed.port or 5432
    if actual_port != allowed_port:
        raise ValueError(
            f"Safety violation: rehearsal database port must be {allowed_port}, got {actual_port}"
        )
    if not (
        parsed.database and parsed.database.startswith("pms_test_remaining_compare_")
    ):
        raise ValueError(
            f"Safety violation: rehearsal database name must start with 'pms_test_remaining_compare_', got '{parsed.database}'"
        )

    if parsed.get_backend_name() != "postgresql" or set(parsed.query) - {"options"}:
        raise ValueError("Safety violation: unsupported driver or connection overrides")
    # libpq query parameters can otherwise override the validated host/database;
    # never preserve options that could turn read-only mode back off.
    return parsed.set(
        query={"options": "-c default_transaction_read_only=on"}
    ).render_as_string(hide_password=False)


def compute_database_fingerprints(pg_url: str) -> dict[str, tuple[int, int]]:
    """Compute (row_count, row_checksum) for every table in the public schema."""
    engine = create_engine(pg_url)
    fingerprints = {}
    with engine.connect() as conn:
        tables = (
            conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                    "ORDER BY table_name"
                )
            )
            .scalars()
            .all()
        )
        for tbl in tables:
            query = text(
                f"SELECT count(*), coalesce(sum(('x' || substr(md5(t::text), 1, 8))::bit(32)::bigint), 0) "
                f'FROM "{tbl}" t'
            )
            row = conn.execute(query).one()
            fingerprints[tbl] = (int(row[0]), int(row[1]))
    engine.dispose()
    return fingerprints


def find_representative_users(pg_url: str) -> dict[str, int]:
    """Derive representative user IDs from read-only local database queries."""
    engine = create_engine(pg_url)
    with engine.connect() as conn:
        both_rows = (
            conn.execute(
                text(
                    "SELECT s.tg_id FROM statistics s "
                    "JOIN plex_user p ON p.tg_id = s.tg_id "
                    "JOIN emby_user e ON e.tg_id = s.tg_id "
                    "WHERE s.tg_id IS NOT NULL AND s.tg_id > 0 "
                    "ORDER BY s.tg_id LIMIT 2"
                )
            )
            .scalars()
            .all()
        )
        if len(both_rows) < 2:
            raise RuntimeError(
                "Database insufficient: need at least 2 users with both Plex and Emby bound"
            )

        plex_only = (
            conn.execute(
                text(
                    "SELECT p.tg_id FROM plex_user p "
                    "LEFT JOIN emby_user e ON e.tg_id = p.tg_id "
                    "WHERE p.tg_id IS NOT NULL AND p.tg_id > 0 AND e.tg_id IS NULL "
                    "ORDER BY p.tg_id LIMIT 1"
                )
            )
            .scalars()
            .first()
        )
        if not plex_only:
            raise RuntimeError(
                "Database insufficient: need at least 1 user with only Plex bound"
            )

        emby_only = (
            conn.execute(
                text(
                    "SELECT e.tg_id FROM emby_user e "
                    "LEFT JOIN plex_user p ON p.tg_id = e.tg_id "
                    "WHERE e.tg_id IS NOT NULL AND e.tg_id > 0 AND p.tg_id IS NULL "
                    "ORDER BY e.tg_id LIMIT 1"
                )
            )
            .scalars()
            .first()
        )
        if not emby_only:
            raise RuntimeError(
                "Database insufficient: need at least 1 user with only Emby bound"
            )

        neither = (
            conn.execute(
                text(
                    "SELECT s.tg_id FROM statistics s "
                    "LEFT JOIN plex_user p ON p.tg_id = s.tg_id "
                    "LEFT JOIN emby_user e ON e.tg_id = s.tg_id "
                    "WHERE s.tg_id IS NOT NULL AND s.tg_id > 0 AND p.tg_id IS NULL AND e.tg_id IS NULL "
                    "ORDER BY s.tg_id LIMIT 1"
                )
            )
            .scalars()
            .first()
        )
        if not neither:
            raise RuntimeError(
                "Database insufficient: need at least 1 user with neither Plex nor Emby bound"
            )

    engine.dispose()
    return {
        "user_both_1": int(both_rows[0]),
        "user_both_2": int(both_rows[1]),
        "user_only_plex": int(plex_only),
        "user_only_emby": int(emby_only),
        "user_neither": int(neither),
        "user_admin": SENTINEL_ADMIN_TG_ID,
        "user_unbound": SENTINEL_UNBOUND_TG_ID,
    }


def build_fake_profile_cache(pg_url: str, sentinel_ids: list[int]) -> dict[str, dict]:
    """Build a deterministic synthetic Telegram profile cache covering all DB users."""
    engine = create_engine(pg_url)
    with engine.connect() as conn:
        all_ids = set(
            conn.execute(
                text(
                    "SELECT tg_id FROM statistics WHERE tg_id IS NOT NULL AND tg_id > 0"
                )
            )
            .scalars()
            .all()
        )
    engine.dispose()
    all_ids.update(sentinel_ids)
    return {
        str(uid): {
            "id": int(uid),
            "first_name": f"User_{uid}",
            "username": f"user_{uid}",
            "photo_url": f"https://fake-tg/avatar_{uid}.jpg",
        }
        for uid in all_ids
    }


WORKER_CODE = """# Rehearsal worker process
import asyncio
import datetime
import json
import socket
import sys
import time
from unittest.mock import AsyncMock, MagicMock
from fastapi import BackgroundTasks, HTTPException
from fastapi.encoders import jsonable_encoder
from starlette.requests import Request

# 1. Outbound socket guard: only allow local PostgreSQL port (argv[2])
ALLOWED_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 32768
_orig_connect = socket.socket.connect

def guarded_connect(self, address):
    host, port = address[0], address[1]
    if host in ("127.0.0.1", "localhost") and port == ALLOWED_PORT:
        return _orig_connect(self, address)
    raise RuntimeError(f"OUTBOUND NETWORK BLOCKED by socket guard: {address} (allowed port: {ALLOWED_PORT})")

socket.socket.connect = guarded_connect

# 2. Identically freeze the clock across old/new
FIXED_TS = 1790769600.0  # 2026-09-30 12:00:00 UTC

class FrozenDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        base = datetime.datetime(2026, 9, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)
        if tz is None:
            return base.replace(tzinfo=None)
        return base.astimezone(tz)

    @classmethod
    def utcnow(cls):
        return datetime.datetime(2026, 9, 30, 12, 0, 0)

class FrozenDate(datetime.date):
    @classmethod
    def today(cls):
        return datetime.date(2026, 9, 30)

datetime.datetime = FrozenDatetime
datetime.date = FrozenDate
time.time = lambda: FIXED_TS
_orig_localtime = time.localtime
time.localtime = lambda s=None: _orig_localtime(FIXED_TS if s is None else s)

# 3. Load representative users and synthetic profile cache from work_dir
with open("representative_users.json", "r", encoding="utf-8") as f:
    REP_USERS = json.load(f)

with open("profile_cache.json", "r", encoding="utf-8") as f:
    RAW_CACHE = json.load(f)

class DynamicProfileDict(dict):
    def __missing__(self, key):
        uid = int(key)
        val = {
            "id": uid,
            "first_name": f"User_{uid}",
            "username": f"user_{uid}",
            "photo_url": f"https://fake-tg/avatar_{uid}.jpg",
        }
        self[key] = val
        return val

    def get(self, key, default=None):
        if key in self:
            return self[key]
        try:
            return self.__missing__(key)
        except Exception:
            return default

DYNAMIC_CACHE = DynamicProfileDict({int(k): v for k, v in RAW_CACHE.items()})

import app.integrations.telegram.profiles as tg_profiles
try:
    import app.integrations.telegram.profile_cache as tg_cache
except ImportError:
    tg_cache = None

tg_profiles.load_tg_user_info_cache = lambda: DYNAMIC_CACHE
tg_profiles.get_user_name_from_tg_id = lambda tg_id, token=None: DYNAMIC_CACHE.get(int(tg_id), {}).get("first_name", str(tg_id))
tg_profiles.get_user_avatar_from_tg_id = lambda tg_id, token=None: DYNAMIC_CACHE.get(int(tg_id), {}).get("photo_url", "")
tg_profiles.get_user_info_from_tg_id = lambda tg_id, token=None: DYNAMIC_CACHE.get(int(tg_id), {})
if tg_cache:
    tg_cache.load_tg_user_info_cache = lambda: DYNAMIC_CACHE

from app.integrations.plex import Plex
Plex.get_user_avatar_by_username = lambda username: f"https://fake-plex/avatar/{username}.jpg"
Plex.get_current_playing_users = lambda: 12
Plex.get_all_users = lambda: []

from app.integrations.emby import Emby
Emby.get_user_avatar_by_username = lambda self_or_user, username=None, from_emby=False: (
    f"https://fake-emby/avatar/{username or self_or_user}.jpg"
)
Emby.get_current_playing_users = lambda self=None: 18
Emby.get_all_users = lambda self=None: []
Emby.get_emby_current_playing_user_num = lambda self=None: 18
Emby.get_devices_per_user = lambda self=None: [
    {"user_name": "emby_alice", "devices": ["d1", "d2", "d3"], "clients": ["c1", "c2"], "ip": ["1.1.1.1"]},
    {"user_name": "emby_bob", "devices": ["d4", "d5"], "clients": ["c3"], "ip": ["2.2.2.2"]},
]
Emby.get_user_info_from_username = lambda self, username: {"date_created": "2024-01-01T00:00:00Z", "Id": f"fake_{username}"}
Emby.get_report = lambda self, types, days, limit, end_date: (True, f"Fake Emby {types} report (days={days})")
Emby.get_user_report = lambda self, days, limit, end_date: (True, f"Fake Emby user report (days={days})")

from app.integrations.tautulli import Tautulli
Tautulli.get_plex_current_playing_user_num = lambda self=None: 12
Tautulli.get_libraries = lambda self=None: [
    {"section_id": "1", "section_name": "Movies", "section_type": "movie", "count": "1500"},
    {"section_id": "2", "section_name": "TV Shows", "section_type": "show", "count": "300", "parent_count": "500", "child_count": "3000"},
]
Tautulli.get_home_stats = lambda self, days, stat, top: [
    {
        "stat_id": "top_users",
        "rows": [
            {"friendly_name": "user_alpha", "total_duration": 36000, "total_plays": 20},
            {"friendly_name": "user_beta", "total_duration": 18000, "total_plays": 15},
        ],
    },
    {
        "stat_id": "top_movies",
        "rows": [
            {"title": "Movie One", "year": "2024", "total_duration": 7200, "total_plays": 10},
            {"title": "Movie Two", "year": "2023", "total_duration": 3600, "total_plays": 5},
        ],
    },
    {
        "stat_id": "top_tv",
        "rows": [
            {"title": "Show One", "year": "2022", "total_duration": 14400, "total_plays": 12},
            {"title": "Show Two", "year": "2021", "total_duration": 7200, "total_plays": 8},
        ],
    },
]

import app.integrations.telegram.messaging as tg_msg
last_sent_messages = []

async def fake_send_message(chat_id, text, parse_mode=None, context=None):
    last_sent_messages.append({"type": "send_message", "chat_id": chat_id, "text": text, "parse_mode": parse_mode})

async def fake_send_message_by_url(chat_id, text, parse_mode=None):
    last_sent_messages.append({"type": "send_message_by_url", "chat_id": chat_id, "text": text, "parse_mode": parse_mode})

tg_msg.send_message = fake_send_message
tg_msg.send_message_by_url = fake_send_message_by_url

# Configure admin list with sentinel admin IDs
from app.core.config import settings
settings.TG_ADMIN_CHAT_ID = [REP_USERS["user_admin"], 100000002]

from app.transport.http.schemas import TelegramUser
from app.domains.rankings import router as rankings_router
from app.domains.rankings import bot as rankings_bot
from app.domains.reports import router as reports_router
from app.domains.reports import admin_router as reports_admin_router
from app.domains.reports import bot as reports_bot
from app.domains.reports import jobs as reports_jobs
from app.domains.profile import router as profile_router
from app.domains.profile import bot as profile_bot
from app.domains.profile import service as profile_service

def make_request(user: TelegramUser) -> Request:
    req = Request({"type": "http", "method": "GET", "path": "/api", "headers": []})
    req.state.telegram_data = {
        "user": json.dumps({"id": user.id, "first_name": user.first_name, "username": user.username})
    }
    return req

def make_bot_context():
    context = MagicMock()
    async def mock_bot_send(chat_id, text, parse_mode=None):
        last_sent_messages.append({"type": "context_bot_send", "chat_id": chat_id, "text": text, "parse_mode": parse_mode})
    context.bot.send_message = mock_bot_send
    return context

async def run_collector() -> dict:
    outputs = {}
    default_uid = REP_USERS["user_both_1"]
    admin_uid = REP_USERS["user_admin"]

    default_user = TelegramUser(id=default_uid, first_name=f"User_{default_uid}", username=f"user_{default_uid}")
    admin_user = TelegramUser(id=admin_uid, first_name="SentinelAdmin", username="sentinel_admin")
    req = make_request(default_user)

    # 1. Rankings Endpoints
    outputs["rankings_badge"] = await rankings_router.get_badge_rankings(request=req, user=default_user)
    outputs["rankings_credits"] = await rankings_router.get_credits_rankings(request=req, user=default_user)
    outputs["rankings_donation"] = await rankings_router.get_donation_rankings(request=req, user=default_user)
    outputs["rankings_watched_time_plex"] = await rankings_router.get_plex_watched_time_rankings(request=req, user=default_user)
    outputs["rankings_watched_time_emby"] = await rankings_router.get_emby_watched_time_rankings(request=req, user=default_user)
    outputs["rankings_invitation"] = await rankings_router.get_invitation_rankings(request=req, user=default_user)
    outputs["rankings_game_wheel"] = await rankings_router.get_wheel_game_rankings(request=req, user=default_user)
    outputs["rankings_game_treasure"] = await rankings_router.get_treasure_game_rankings(request=req, user=default_user)
    outputs["rankings_game_prediction"] = await rankings_router.get_prediction_game_rankings(request=req, user=default_user)
    outputs["rankings_game_blackjack"] = await rankings_router.get_blackjack_game_rankings(request=req, user=default_user)
    outputs["rankings_traffic_plex_default"] = await rankings_router.get_plex_traffic_rankings(request=req, user=default_user, start_date=None, end_date=None)
    outputs["rankings_traffic_plex_dated"] = await rankings_router.get_plex_traffic_rankings(request=req, user=default_user, start_date="2026-09-01", end_date="2026-09-30")
    outputs["rankings_traffic_emby_default"] = await rankings_router.get_emby_traffic_rankings(request=req, user=default_user, start_date=None, end_date=None)
    outputs["rankings_traffic_emby_dated"] = await rankings_router.get_emby_traffic_rankings(request=req, user=default_user, start_date="2026-09-01", end_date="2026-09-30")

    # 1b. Rankings validation error case
    try:
        await rankings_router.get_plex_traffic_rankings(request=req, user=default_user, start_date="bad-date", end_date="bad-date")
        outputs["rankings_traffic_invalid_date"] = {"status": 200}
    except HTTPException as e:
        outputs["rankings_traffic_invalid_date"] = {"status": e.status_code, "detail": e.detail}

    # 2. Rankings Bot Commands
    for cmd_name, handler, cid in [
        ("bot_credits_rank", rankings_bot.credits_rank, default_user.id),
        ("bot_donation_rank", rankings_bot.donation_rank, default_user.id),
        ("bot_watched_time_rank", rankings_bot.watched_time_rank, default_user.id),
        ("bot_device_rank_admin", rankings_bot.device_rank, admin_user.id),
        ("bot_device_rank_non_admin", rankings_bot.device_rank, default_user.id),
        ("bot_rank_24h", rankings_bot.rank_24h, default_user.id),
    ]:
        last_sent_messages.clear()
        up = MagicMock()
        up._effective_chat.id = cid
        up.effective_chat.id = cid
        ctx = make_bot_context()
        await handler(up, ctx)
        outputs[cmd_name] = list(last_sent_messages)

    # 3. Reports Endpoints
    outputs["reports_system_stats"] = await reports_router.get_system_stats(request=req, user=default_user)
    outputs["reports_system_status"] = await reports_router.get_system_status()
    outputs["reports_traffic_overview"] = await reports_router.get_traffic_overview(request=req, user=default_user)
    admin_req = make_request(admin_user)
    outputs["reports_admin_settings_admin"] = await reports_admin_router.get_admin_settings(request=admin_req, user=admin_user)

    try:
        await reports_admin_router.get_admin_settings(request=req, user=default_user)
        outputs["reports_admin_settings_forbidden"] = {"status": 200}
    except HTTPException as e:
        outputs["reports_admin_settings_forbidden"] = {"status": e.status_code, "detail": e.detail}

    # 4. Reports Bot & Job
    last_sent_messages.clear()
    up = MagicMock()
    up.effective_chat.id = default_user.id
    ctx = make_bot_context()
    await reports_bot.get_server_status(up, ctx)
    outputs["bot_server_status"] = list(last_sent_messages)

    last_sent_messages.clear()
    weekly_text = await reports_jobs.send_weekly_report(channel_id="-100987654321")
    outputs["reports_weekly_report"] = {"return_text": weekly_text, "messages": list(last_sent_messages)}

    # 5. Profile Endpoints & Bot Command across representative user states
    for state_name, uid in REP_USERS.items():
        u = TelegramUser(id=uid, first_name=f"User_{uid}", username=f"user_{uid}")
        u_req = make_request(u)
        bg = BackgroundTasks()
        try:
            profile_res = await profile_router.get_user_info(request=u_req, background_tasks=bg, user=u)
            if hasattr(profile_res, "model_dump"):
                outputs[f"profile_info_{state_name}"] = profile_res.model_dump()
            elif hasattr(profile_res, "dict"):
                outputs[f"profile_info_{state_name}"] = profile_res.dict()
            else:
                outputs[f"profile_info_{state_name}"] = profile_res
        except Exception as e:
            outputs[f"profile_info_{state_name}"] = {"error": str(e), "type": type(e).__name__}

        last_sent_messages.clear()
        b_up = MagicMock()
        b_up._effective_chat.id = uid
        b_up.effective_chat.id = uid
        b_ctx = make_bot_context()
        await profile_bot.info(b_up, b_ctx)
        outputs[f"bot_info_{state_name}"] = list(last_sent_messages)

    # Profile all users
    outputs["profile_all_users"] = await profile_router.get_all_users(request=req, user=default_user)

    # Profile scheduled job
    refreshed_users = []
    tg_profiles.refresh_tg_user_info = AsyncMock(side_effect=lambda users, token=None: refreshed_users.extend(users))
    await profile_service.refresh_tg_user_info(tg_id=default_uid)
    outputs["profile_refresh_tg_user_info"] = refreshed_users

    # Apply FastAPI jsonable_encoder before serialization
    return jsonable_encoder(outputs)

if __name__ == "__main__":
    out_file = sys.argv[1]
    data = asyncio.run(run_collector())
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
"""


def run_collection(
    source_dir: str,
    pg_url: str,
    output_path: str,
    work_dir: str,
    allowed_port: int,
) -> None:
    data_dir = os.path.join(work_dir, "data_dummy")
    os.makedirs(data_dir, exist_ok=True)
    logs_dir = os.path.join(data_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    dummy_env_file = os.path.join(data_dir, ".env")
    with open(dummy_env_file, "w", encoding="utf-8") as f:
        f.write(
            f"TG_API_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11\n"
            f"TG_ADMIN_CHAT_ID={SENTINEL_ADMIN_TG_ID},{SENTINEL_ADMIN_TG_ID_2}\n"
            f"TG_CHANNEL_ID=-100987654321\n"
            f"DATABASE_URL={pg_url}\n"
            f"DATABASE_TYPE=postgres\n"
            f"WEBAPP_DEV_MOCK_AUTH=false\n"
        )

    worker_file = os.path.join(work_dir, "_runner_worker.py")
    with open(worker_file, "w", encoding="utf-8") as f:
        f.write(WORKER_CODE)

    clean_env = {
        "PATH": os.environ.get("PATH", "/bin:/usr/bin:/usr/local/bin"),
        "HOME": work_dir,
        "PYTHONPATH": os.path.join(source_dir, "src"),
        "DATABASE_URL": pg_url,
        "DATABASE_TYPE": "postgres",
        "DATA_DIR": data_dir,
        "TZ": "UTC",
    }

    cmd = [
        sys.executable,
        worker_file,
        output_path,
        str(allowed_port),
    ]

    res = subprocess.run(
        cmd,
        env=clean_env,
        capture_output=True,
        text=True,
        cwd=work_dir,
        check=False,
    )
    if res.returncode != 0:
        print(
            f"Error running worker for {source_dir}:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )
        sys.exit(1)


def compare_results(baseline_json: str, current_json: str) -> dict:
    with open(baseline_json, "r", encoding="utf-8") as f:
        base = json.load(f)
    with open(current_json, "r", encoding="utf-8") as f:
        curr = json.load(f)

    all_keys = sorted(set(base.keys()) | set(curr.keys()))
    matches = []
    diffs = {}

    for k in all_keys:
        b_val = base.get(k)
        c_val = curr.get(k)
        if b_val == c_val:
            matches.append(k)
        else:
            diffs[k] = {"baseline": b_val, "current": c_val}

    return {
        "total": len(all_keys),
        "match_count": len(matches),
        "diff_count": len(diffs),
        "matches": matches,
        "diffs": diffs,
    }


def main():
    parser = argparse.ArgumentParser(description="Read-model rehearsal comparison")
    parser.add_argument(
        "--baseline-dir",
        default=DEFAULT_BASELINE_DIR,
        help="Path to baseline git checkout",
    )
    parser.add_argument(
        "--current-dir",
        default=str(Path(__file__).resolve().parents[2]),
        help="Path to current git checkout",
    )
    parser.add_argument(
        "--work-dir",
        default=DEFAULT_WORK_DIR,
        help="Working directory for rehearsal artifacts",
    )
    parser.add_argument(
        "--pg-url",
        default=DEFAULT_PG_URL,
        help="Disposable PostgreSQL connection string",
    )
    parser.add_argument(
        "--allowed-port",
        type=int,
        default=DEFAULT_ALLOWED_PORT,
        help="Allowed PostgreSQL port for socket guard",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional output path for comparison report JSON",
    )

    args = parser.parse_args()
    os.makedirs(args.work_dir, exist_ok=True)

    print("0. Validating rehearsal database URL and enforcing read-only mode...")
    safe_pg_url = validate_rehearsal_database_url(
        args.pg_url, allowed_port=args.allowed_port
    )

    print("   Computing pre-rehearsal database fingerprints...")
    pre_fingerprints = compute_database_fingerprints(safe_pg_url)
    print(f"   Indexed {len(pre_fingerprints)} tables.")

    print("   Deriving representative user fixtures and synthetic profiles...")
    rep_users = find_representative_users(safe_pg_url)
    rep_users_file = os.path.join(args.work_dir, "representative_users.json")
    with open(rep_users_file, "w", encoding="utf-8") as f:
        json.dump(rep_users, f, indent=2)

    fake_cache = build_fake_profile_cache(
        safe_pg_url,
        [rep_users["user_admin"], SENTINEL_ADMIN_TG_ID_2, rep_users["user_unbound"]],
    )
    cache_file = os.path.join(args.work_dir, "profile_cache.json")
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(fake_cache, f, indent=2)

    base_out = os.path.join(args.work_dir, "rehearsal_baseline_hardened.json")
    curr_out = os.path.join(args.work_dir, "rehearsal_current_hardened.json")

    print(f"1. Running baseline rehearsal on {args.baseline_dir}...")
    run_collection(
        args.baseline_dir, safe_pg_url, base_out, args.work_dir, args.allowed_port
    )

    print(f"2. Running current checkout rehearsal on {args.current_dir}...")
    run_collection(
        args.current_dir, safe_pg_url, curr_out, args.work_dir, args.allowed_port
    )

    print("3. Validating post-rehearsal database fingerprints...")
    post_fingerprints = compute_database_fingerprints(safe_pg_url)
    if pre_fingerprints != post_fingerprints:
        changed_tables = [
            t
            for t in pre_fingerprints
            if pre_fingerprints[t] != post_fingerprints.get(t)
        ]
        raise RuntimeError(
            f"DATABASE MUTATION DETECTED! Rehearsal violated read-only guarantee in tables: {changed_tables}"
        )
    print(
        "   Post-rehearsal fingerprints 100% identical: zero database writes occurred."
    )

    print("4. Comparing baseline and current results...")
    report = compare_results(base_out, curr_out)

    print("\n================ REHEARSAL SUMMARY ================")
    print(f"Total test cases executed: {report['total']}")
    print(f"Exact matches:             {report['match_count']}/{report['total']}")
    print(f"Differences:               {report['diff_count']}/{report['total']}")
    print("===================================================\n")

    if report["diff_count"] > 0:
        print("Diff items:")
        for k, v in report["diffs"].items():
            print(f"\n[-] {k}:")
            b_sample = str(v["baseline"])[:140]
            c_sample = str(v["current"])[:140]
            print(f"    Baseline: {b_sample}...")
            print(f"    Current:  {c_sample}...")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nFull comparison report written to {args.json_out}")

    if report["diff_count"] > 0:
        print("\nRehearsal failed: semantic parity differences exist.")
        sys.exit(1)
    else:
        print(
            "\nRehearsal succeeded: 100% exact parity achieved across all test cases."
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
