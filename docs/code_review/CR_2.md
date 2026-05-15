# Code Review — Phase 2

**Scope:** Config, DB, Alembic, Clock, real system/status  
**Files reviewed:** `config.py`, `db.py`, `clock.py`, `models/`, `main.py`, `alembic/env.py`, migration `1e697fab1bb8`, all new tests, `Dockerfile.backend`, `docker-compose.yml`  
**Result:** 3 bugs / correctness issues, 5 design notes, 4 test notes

---

## Bugs / Correctness

### 1. `check_source` and `email_sink` accept any string — `config.py:12–13`

```python
check_source: str = "real"
email_sink: str = "smtp"
```

Both fields are plain `str`. Setting `CHECK_SOURCE=fake` at runtime silently passes validation and will produce a broken runtime later when the app tries to construct a checker or sink. They should be constrained at the config layer:

```python
from typing import Literal

check_source: Literal["real", "simulated"] = "real"
email_sink: Literal["smtp", "log"] = "smtp"
```

Pydantic-settings will raise a `ValidationError` on startup with a clear message if an invalid value is set, rather than failing silently at the point of use.

### 2. Empty `database_url` silently produces a broken engine — `db.py:8`

```python
engine = create_async_engine(settings.database_url, echo=False)
```

`settings.database_url` defaults to `""`. SQLAlchemy accepts the empty string at construction time and only raises when a connection is first attempted — so a missing `DATABASE_URL` env var produces an opaque error deep in asyncpg rather than a clear startup failure. The lifespan's `check_db_connection()` partially mitigates this (it fails fast on startup), but unit-test modules that import `db.py` without setting `DATABASE_URL` will get a junk engine object created silently.

Preferred fix: make `database_url` required (no default). Pydantic-settings raises `ValidationError` at `Settings()` construction time with a clear field name:

```python
database_url: str  # no default; startup fails immediately if unset
```

Unit tests that import `heartbeat.db` will then need `DATABASE_URL` set — a small fix enforced by the environment, not by catching a buried asyncpg error.

### 3. `nullable=False` in `Mapped[str]` columns is redundant — `models/user.py:13–14`

```python
email: Mapped[str] = mapped_column(String, nullable=False)
name:  Mapped[str] = mapped_column(String, nullable=False)
```

In SQLAlchemy 2.0, `Mapped[str]` (not `Mapped[str | None]`) already implies `nullable=False` at the ORM level. The explicit kwarg is harmless but misleading — it implies the column would be nullable without it, which is false. All future model columns should omit `nullable=False` unless overriding a `Mapped[str | None]` field for some reason. Remove both kwargs to stay consistent with the SQLAlchemy 2.0 idiomatic style the codebase adopts everywhere else.

---

## Design Notes

### 4. Multi-level `.env` search is fragile — `config.py:5–8`

```python
env_file=(".env", "../.env", "../../.env", "../../../.env"),
```

If a `.env` file exists at an unintended parent level (e.g., the user's home directory has one), pydantic-settings will silently load it and merge its values. The intent — "find the repo-root `.env` regardless of CWD" — is better served by computing the path explicitly in one place:

```python
# Resolve once, relative to this file's location
_ROOT = Path(__file__).parent.parent.parent.parent  # backend/src/heartbeat -> repo root
```

```python
env_file=str(_ROOT / ".env"),
```

This is deterministic and doesn't search arbitrary parent directories.

### 5. Lifespan missing return type annotation — `main.py:10`

```python
async def lifespan(app: FastAPI):
```

Should be:

```python
from collections.abc import AsyncIterator

async def lifespan(app: FastAPI) -> AsyncIterator[None]:
```

The missing annotation is inconsistent with the rest of the codebase (all other functions are fully typed) and will produce a mypy warning once type-checking is added.

### 6. `system_status` returns `dict` instead of a typed response model — `main.py:20`

```python
async def system_status() -> dict:
```

A plain `dict` return type means FastAPI cannot generate a schema for this endpoint in the OpenAPI docs, and callers have no contract to check against. A small inline Pydantic model or `TypedDict` would be better:

```python
class SystemStatus(BaseModel):
    check_source: str
    email_sink: str
    smtp_from: str | None
    n: int
    m: int
```

This is consistent with how every other route in the plan will be typed, so deferring it creates an inconsistency that has to be cleaned up later.

### 7. `noqa` comments in `alembic/env.py` signal avoidable import order — `env.py:21–22`

```python
from heartbeat.models.base import Base  # noqa: E402
from heartbeat.models import user  # noqa: E402, F401
```

These are placed after `fileConfig(...)` because the alembic boilerplate does it that way, but there's no actual requirement. The `Base` and model imports can be moved to the top of the file without any change in behavior. That removes both `noqa` suppressions and keeps the import block clean.

The `from heartbeat.models import user` side-effect import is also non-obvious. Prefer:

```python
from heartbeat.models.user import User  # registers User with Base.metadata
```

This makes the intent (register the model) explicit through a named import.

### 8. `docker-compose.yml` — exposing port 5432 on the host

```yaml
ports:
  - "5432:5432"
```

This was added to enable host-side test access to the DB. It is correct for local dev but should be documented: any developer who runs the stack while their own Postgres is already listening on 5432 will get a port conflict. A comment in the compose file or a note in the README would prevent confusion.

---

## Test Notes

### 9. `test_system_status_reflects_env` is a non-assertion — `test_system_status.py:29–33`

```python
assert data["check_source"] in ("real", "simulated")
assert data["email_sink"] in ("smtp", "log")
```

This checks that the field is one of the two valid values — it would pass even if the endpoint returned a hardcoded string. The intent is to verify the endpoint reads from `Settings`, but that property isn't being tested. A better test sets a specific env var value before the request and asserts that exact value is returned, using `monkeypatch` or module-level env setup similar to what the conftest already does.

### 10. `test_db_url` fixture is unused outside `conftest.py` — `conftest.py:25–27`

```python
@pytest.fixture(scope="session")
def test_db_url() -> str:
    return _TEST_DB_URL
```

This fixture exists but is only used internally by `db_engine`. No test file queries it. Either remove it or, if it's intended for future use by integration tests that need to open their own connections, leave it with a comment explaining why.

### 11. No negative-path coverage for the lifespan DB ping — `main.py:11`

```python
await check_db_connection()
```

There's no test asserting the app refuses to start (raises / returns 503) when the database is unreachable. The current test suite only covers the happy path. A unit test that patches `check_db_connection` to raise and asserts the lifespan propagates the error would protect against regressions where someone accidentally swallows the exception.

### 12. `test_users_created_at_is_set` duplicates work from `test_users_seed_row_exists`

Both tests open a fresh session (triggering a new DB connection each time because of `NullPool`). The `created_at` check could just be an additional assertion in the first test, saving one round-trip and reducing test surface area. Splitting it made sense as a "one assertion per test" discipline, but given both tests share identical setup cost and context, keeping them together is the pragmatic choice here.

---

## What Is Good

- `FakeClock` is clean and minimal. The `set`/`advance` API covers exactly what test code needs.
- The `NullPool` fix in `conftest.py` is the right call. Using a connection pool across event loops with asyncpg is a common source of hard-to-debug failures.
- Alembic env.py creates a fresh `Settings()` instance rather than re-using the module-level singleton — this is what makes the test URL override via `os.environ` work correctly.
- The `asyncio.run(reset_schema())` approach in the session-scoped sync fixture is the correct pattern for running async setup code from a synchronous pytest fixture without fighting pytest-asyncio's event loop management.
- Migration is explicit and complete: schema + data in one revision, `downgrade` correctly drops the table.
