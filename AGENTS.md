# AGENTS.md — PMSManageBot Coding Guidelines

## Project Overview

PMSManageBot is a Telegram bot + FastAPI web backend + Vue 3 frontend (Telegram MiniApp).
It manages Plex/Emby media server users, credits, premium subscriptions, and activities.

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.x, python-telegram-bot, APScheduler, Pydantic v2
- **Frontend:** Vue 3, Vuetify 3, Vue Router 4, axios (JavaScript, no TypeScript)
- **Database:** SQLAlchemy ORM with Alembic migrations (SQLite/PostgreSQL)
- **Package managers:** `uv` (Python), `npm` (frontend)

---

## Build & Run Commands

### Python Backend

```bash
# Install dependencies
uv pip install ".[postgres]"

# Run the application
python3 -m app.main

# Apply database migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "description"
```

### Frontend (`webapp-frontend/`)

```bash
# Dev server (port 8080 by default)
npm run serve

# Production build (also updates service worker version)
npm run build
```

### Docker

```bash
# Build and start all services
docker compose up --build

# Start detached
docker compose up -d
```

---

## Lint & Format Commands

### Python — Ruff (linter + formatter)

```bash
# Lint
ruff check src/

# Auto-fix linting issues
ruff check --fix src/

# Sort imports only
ruff check --select I --fix src/

# Format code
ruff format src/

# Check import boundaries against the live src/ tree (after installing test extras)
PYTHONPATH=src .venv/bin/lint-imports --no-cache

# Run all pre-commit hooks (lint + sort + format + architecture)
pre-commit run --all-files
```

Ruff uses default rules plus the `[tool.ruff.lint]` ignores in `pyproject.toml` (`BLE001`, `B008`).
Pre-commit hooks are defined in `.pre-commit-config.yaml` (ruff, plus local import-linter and architecture-test hooks).

### JavaScript/Vue — ESLint

```bash
# Lint frontend (run from webapp-frontend/)
npm run lint
```

Config: `webapp-frontend/.eslintrc.js` — extends `plugin:vue/vue3-essential` + `eslint:recommended`.
Notable disabled rules: `vue/multi-word-component-names`, `vue/valid-v-slot`.

---

## Tests

```bash
# Install test extras (pytest)
uv pip install ".[test]"

# Run all tests
.venv/bin/python -m pytest tests/

# Run architecture checks
.venv/bin/python -m pytest tests/architecture

# Run a single test file or function
.venv/bin/python -m pytest tests/test_blackjack_tournament_settle.py
.venv/bin/python -m pytest tests/test_blackjack_tournament_settle.py::test_function_name

# Run with verbose output
.venv/bin/python -m pytest -v tests/
```

---

## Code Style Guidelines

### Python

#### Imports

- Use **absolute imports** within `app.*`; for cross-layer or cross-domain calls import the target module, not individual functions:
  ```python
  from app.domains.credits import service as credits_service
  from app.core.config import settings
  ```
  Existing imports retain their old paths only until the corresponding B-stage relocation; don't introduce new dependencies on those paths.
- Order: stdlib → third-party → local (enforced by ruff `I` ruleset).
- Avoid wildcard imports. Bot handlers are explicitly registered in the target `app.bot.app`.

#### Naming Conventions

| Category | Style | Example |
|---|---|---|
| Variables & functions | `snake_case` | `plex_id`, `get_plex_info_by_tg_id()` |
| Classes | `PascalCase` | `DatabaseORM`, `TelegramAuthMiddleware` |
| Constants / env vars | `SCREAMING_SNAKE_CASE` | `TG_API_TOKEN`, `PLEX_BASE_URL` |
| Module filenames | `snake_case` | `db_func.py`, `custom_line.py` |
| ORM table/column names | `snake_case` | `plex_user`, `auction_bids` |
| Private methods | Single underscore prefix | `_load_from_env_file()`, `_get_cache_key()` |

#### Type Annotations

- Always annotate public function signatures with parameter types and return types.
- Use `Mapped[T]` / `mapped_column()` for SQLAlchemy 2.x ORM models:
  ```python
  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  credits: Mapped[float] = mapped_column(Float, default=0, nullable=False)
  ```
- Use Pydantic v2 `BaseModel` for all FastAPI request/response schemas with full annotations:
  ```python
  class TelegramUser(BaseModel):
      id: int
      first_name: str
      username: Optional[str] = None
  ```
- For newer code, prefer Python 3.10+ built-in generics (`list[str]`, `tuple[bool, str]`)
  over `typing.List`, `typing.Tuple`. `Optional[T]` from `typing` is still acceptable.
- Explicit `-> None` return type on handlers and void functions.

#### Error Handling

1. **Legacy DB operations** — existing complete-transaction methods wrap in `try/except Exception as e`, log with `logger.error`, and return `False`/`None`. Keep this behavior when mechanically moving them. `*_tx(session, …)` helpers must **not** swallow exceptions; let them propagate so the outer transaction rolls back:
   ```python
   def some_db_operation(self, ...) -> bool:
       try:
           with get_session() as session:
               ...
               return True
       except Exception as e:
           logger.error(f"Error doing X: {e}")
           return False
   ```

2. **Session management** — use the `get_session()` context manager (currently `app.databases.session`, moving to `app.core.db`) **only inside a domain repository**. It handles commit/rollback/close automatically. Cross-domain operations in one transaction must call the target domain's `*_tx(session, …)` helper, not open a second session.

3. **FastAPI routes** — raise `HTTPException` with appropriate status codes. Detail messages
   follow the existing Chinese-language convention:
   ```python
   raise HTTPException(
       status_code=status.HTTP_401_UNAUTHORIZED,
       detail="无效的 Telegram 认证数据",
   )
   ```

4. **Business logic violations** — keep raising `ValueError` until the shared `DomainError` base is introduced by the first `promote-*` change that needs it; after that, new domain code uses a domain-specific `DomainError` subclass (in that domain's `exceptions.py`) with structured code and payload. Preserve existing `ValueError` handling when mechanically relocating legacy code; conversion belongs to the relevant `promote-*` change.

5. **Critical operations** — include `traceback.print_exc()` alongside `logger.error` when
   a full stack trace is needed for debugging.

6. **Non-critical background tasks** — swallow exceptions after logging; do not crash the scheduler.

#### Logging

Use the project logger exclusively — never `print()` in backend code (scripts are exempt):

```python
from app.core.log import logger  # legacy code retains app.log until its relocation

logger.info("Message")
logger.error(f"Error doing X: {e}")
logger.warning("Warning message")
```

#### Async

- All database operations use **synchronous** SQLAlchemy sessions. Do not convert them to async.
- FastAPI route handlers and APScheduler callbacks may be `async def`.
- Telegram bot handlers must be `async def`.

---

### JavaScript / Vue (Frontend)

#### Naming Conventions

| Category | Style | Example |
|---|---|---|
| Variables & functions | `camelCase` | `apiClient`, `parseInitData()` |
| API export functions | `camelCase` | `getUserInfo`, `bindPlexAccount` |
| Vue component filenames | `PascalCase` | `UserInfo.vue`, `BindAccountDialog.vue` |
| Route names | `kebab-case` | `'user-info'`, `'activities'` |

#### Imports & Exports

- Use **relative imports** within the frontend (`../views/`, `../main`).
- Named exports for API functions in `src/api/index.js`.
- Default exports for Vue components, the router instance, and the app instance.
- All HTTP calls must go through the shared `apiClient` axios instance (configured in `main.js`).

#### Error Handling (Frontend)

- API errors are caught by the axios response interceptor in `main.js` (logs via `console.error`).
- Display user-facing errors with Vuetify snackbar/alert components — do not use `alert()`.

---

## Architecture Patterns

The domain inventory, ownership of wide-table columns, existing exceptions and manual operations are in [docs/architecture.md](docs/architecture.md).

- **Invocation direction:** entry points (`router`, `admin_router`, `jobs`, `bot`) → `service` → `repository` → `models`; pure computation belongs in `rules`. Dependencies across domains flow from higher to lower tiers (T5 → T0); same-tier dependencies must not cycle. T4 domains coordinate multi-domain operations; do not create a separate application layer.
- **Database boundary:** only domain `repository.py` (or a same-named repository package) contains business SQLAlchemy queries and transaction management. Routers, services, and jobs do not call `get_session()` or query ORM models. A cross-domain transaction calls the target domain's `*_tx(session, …)` helper; a separate session would break atomicity and may deadlock.
- **Side effects:** network API calls, notifications and background scheduling happen in services after commit, not inside repository transactions. Lower tiers notify higher tiers with post-commit domain events, never direct upward imports. The privileged-code `.env` write lives in the owning `invitation` domain (`invitation.repository.persist_privileged_codes_tx`) and remains a documented pre-commit exception until its database migration.
- **Credits:** change user balances only through locked delta increment/decrement operations in the credits domain, not by writing absolute balances. Do not add user state columns to `Statistics`, `PlexUser` or `EmbyUser`; put new per-user state in the owning domain's table keyed by `tg_id`.
- **Imports:** across domains and architectural layers import modules rather than individual functions. Cross-domain calls use only the target `service` or `*_tx` repository helper; do not import foreign models, routers, jobs or notifications. The one shared vocabulary is pure value types: a `<domain>/types.py` module may be imported by any layer of any domain, and it must stay dependency-free (no domain models, services, repositories, `app.core.db` or SQLAlchemy) — enforced by the “Domain types are pure value modules” import-linter contract. T5 read-model repositories alone may read other domains' tables for aggregation and must never write them.
- **Singletons:** keep existing Scheduler and settings instances; do not re-instantiate them. Telegram auth continues to validate HMAC `initData`, and guarded routes use `require_telegram_auth`.

### Where new code goes

| New work | Location |
|---|---|
| HTTP endpoint / Telegram command / scheduled entry | Owning domain's `router.py` or `admin_router.py` / `bot.py` / `jobs.py`; composition only in `api/`, `bot/app.py` or `schedule.py` |
| Business workflow, especially coordination of multiple domains | Owning domain's `service.py`; multi-domain strategy in a T4 domain, **not** a new application layer |
| SQLAlchemy query, write or transactional helper | Owning domain's `repository.py` / `repository/`; model in `models.py` |
| Pure calculations / validation / error types | `rules.py` / `exceptions.py` in that domain |
| External API client / common infrastructure | `integrations/` / `core/` respectively |
| Runtime business setting / infrastructure secret | Business settings use domain `config.py` backed by `SystemConfig`; infrastructure secrets and deployment settings remain read-only in `data/.env` via `core.config` |

**Transition (B-stage mechanical move):** Existing `db.xxx()` calls remain intact. The `app.databases.db` singleton temporarily composes domain repository mixins; the facade file itself gets no new methods. A new database operation goes in its owning domain's repository mixin and may be called as `db.xxx()` from that same domain, but do not add new cross-domain `db.xxx()` calls. Move old code without altering behavior or broadly replacing existing calls; later `promote-*` changes introduce services and remove the facade. Do not add compatibility import modules for moved code. Modules exceeding 1,000 lines become same-named packages split by subtopic.

A function with no codebase callers is **not necessarily dead**. Before removing one, check the manual operations list in [docs/architecture.md](docs/architecture.md) and confirm with the maintainer; `db.rebind_user_tg_id(...)` is a known manual entry point.

---

## Environment & Configuration

- Copy `.env.example` to `data/.env` and fill in values before running locally.
- `Settings` (`pydantic-settings` `BaseSettings`; currently `app/core/config.py`) loads infrastructure settings from system env → `data/.env` → defaults. Runtime business settings are typed `DomainConfig` declarations persisted in `SystemConfig`; legacy business keys in `.env` are read only for first-run seeding.
- Never hardcode secrets or service URLs — always read from `settings.*`.
- Key variables: `TG_API_TOKEN`, `PLEX_BASE_URL`, `EMBY_BASE_URL`, `DATABASE_URL`,
  `REDIS_HOST`, `WEBAPP_URL`, `SESSION_SECRET_KEY`.

---

## Database Migrations

- Always create a migration when changing SQLAlchemy models in a domain `models.py` (legacy models remain in `app/models/models.py` until B1):
  ```bash
  alembic revision --autogenerate -m "add column foo to plex_user"
  alembic upgrade head
  ```
- Review autogenerated migrations before applying — Alembic may miss certain changes
  (e.g., column type changes, check constraints).
- One-off data migrations go in `scripts/` as standalone Python scripts, not in Alembic.
