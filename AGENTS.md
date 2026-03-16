# AGENTS.md — PMSManageBot Coding Guidelines

## Project Overview

PMSManageBot is a Telegram bot + FastAPI web backend + Vue 3 frontend (Telegram MiniApp).
It manages Plex/Emby media server users, credits, premium subscriptions, and activities.

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.x, python-telegram-bot, APScheduler, Pydantic v2
- **Frontend:** Vue 3, Vuetify 3, Vue Router 4, axios (JavaScript, no TypeScript)
- **Database:** SQLAlchemy ORM with Alembic migrations (SQLite/PostgreSQL/MySQL)
- **Package managers:** `uv` (Python), `npm` (frontend)

---

## Build & Run Commands

### Python Backend

```bash
# Install dependencies
uv pip install ".[postgres,mysql]"

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

# Run all pre-commit hooks (lint + sort + format)
pre-commit run --all-files
```

Ruff runs with default settings — no `[tool.ruff]` block in `pyproject.toml`.
Pre-commit hooks are defined in `.pre-commit-config.yaml` (ruff v0.6.0).

### JavaScript/Vue — ESLint

```bash
# Lint frontend (run from webapp-frontend/)
npm run lint
```

Config: `webapp-frontend/.eslintrc.js` — extends `plugin:vue/vue3-essential` + `eslint:recommended`.
Notable disabled rules: `vue/multi-word-component-names`, `vue/valid-v-slot`.

---

## Tests

**There is currently no test suite.** The `tests/` directory exists but is empty.
No pytest configuration exists in `pyproject.toml`.

When tests are added, the expected commands will be:

```bash
# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_something.py

# Run a single test function
pytest tests/test_something.py::test_function_name

# Run with verbose output
pytest -v tests/
```

---

## Code Style Guidelines

### Python

#### Imports

- Use **absolute imports** with the `app.*` namespace exclusively:
  ```python
  from app.config import settings
  from app.databases.db import DatabaseORM
  from app.models.models import PlexUser
  from app.log import logger
  ```
- Order: stdlib → third-party → local (enforced by ruff `I` ruleset).
- Avoid wildcard imports (`from module import *`) except in `main.py` for handler registration.

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

1. **DB operations** — wrap in `try/except Exception as e`, log with `logger.error`, return `False`/`None`:
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

2. **Session management** — use `get_session()` context manager from `app.databases.session`;
   it handles commit/rollback/close automatically. Never manage sessions manually.

3. **FastAPI routes** — raise `HTTPException` with appropriate status codes. Detail messages
   follow the existing Chinese-language convention:
   ```python
   raise HTTPException(
       status_code=status.HTTP_401_UNAUTHORIZED,
       detail="无效的 Telegram 认证数据",
   )
   ```

4. **Business logic violations** — raise `ValueError` with a descriptive message; let the router catch it.

5. **Critical operations** — include `traceback.print_exc()` alongside `logger.error` when
   a full stack trace is needed for debugging.

6. **Non-critical background tasks** — swallow exceptions after logging; do not crash the scheduler.

#### Logging

Use the project logger exclusively — never `print()` in backend code (scripts are exempt):

```python
from app.log import logger

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

- **`DatabaseORM` singleton** (`app.databases.db`) — all DB operations live here. Import via
  `from app.databases import db`. Do not instantiate `DatabaseORM` elsewhere.
- **External services** in `app/modules/` — one class per service (Plex, Emby, Tautulli, etc.).
  Keep third-party API integrations isolated in this layer.
- **FastAPI routers** in `app/webapp/routers/` — thin handlers that delegate to `db.*` and
  module methods. Business logic belongs in `db.py` or modules, not in routers.
- **Scheduler tasks** in `app/databases/db_func.py` — background/scheduled functions that
  orchestrate DB and module calls.
- **Singletons** — `Scheduler` uses `SingletonMeta`; `Settings` is a module-level `settings`
  instance. Do not re-instantiate these.
- **Authentication** — `TelegramAuthMiddleware` validates Telegram HMAC `initData` globally.
  Use the `require_telegram_auth` decorator on individual routes that need extra enforcement.

---

## Environment & Configuration

- Copy `.env.example` to `data/.env` and fill in values before running locally.
- `Settings` (`pydantic-settings` `BaseSettings`) in `app/config.py` loads in priority order:
  system env → `data/.env` → defaults.
- Never hardcode secrets or service URLs — always read from `settings.*`.
- Key variables: `TG_API_TOKEN`, `PLEX_BASE_URL`, `EMBY_BASE_URL`, `DATABASE_URL`,
  `REDIS_HOST`, `WEBAPP_URL`, `SESSION_SECRET_KEY`.

---

## Database Migrations

- Always create a migration when changing SQLAlchemy models in `app/models/models.py`:
  ```bash
  alembic revision --autogenerate -m "add column foo to plex_user"
  alembic upgrade head
  ```
- Review autogenerated migrations before applying — Alembic may miss certain changes
  (e.g., column type changes, check constraints).
- One-off data migrations go in `scripts/` as standalone Python scripts, not in Alembic.
