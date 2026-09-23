"""Database engine and session factory.

`DATABASE_URL` comes from the environment and is never hard-coded (§53). With
nothing configured the default is a local SQLite file, so `pytest`, the desktop
shell and a first `git clone` all work with no database server running.
Postgres is the deployed target, not a prerequisite for a test.

Nothing here imports FastAPI-specific machinery beyond the dependency helper, so
the same session factory is usable from a worker, the CLI or a test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

# apps/api/app/core/db.py → repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SQLITE_PATH = REPO_ROOT / ".data" / "dashboardbridge.db"


def database_url() -> str:
    """The configured database, or a local SQLite file if none is configured.

    The fallback is deliberate: an unconfigured checkout must still run. A
    deployment sets `DATABASE_URL` to Postgres.
    """
    configured = os.getenv("DATABASE_URL")
    if configured:
        return configured
    return f"sqlite+pysqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"


def redacted_database_url(url: str | None = None) -> str:
    """The URL with its password removed, for logs and error detail.

    Connection strings are never logged (09-security-spec § Logging), and a
    password that reaches a log has already leaked.
    """
    return make_url(url or database_url()).render_as_string(hide_password=True)


def create_app_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Build an engine for `url`.

    SQLite needs two accommodations and both are correctness, not taste:
    `check_same_thread=False` because the API serves requests on a thread pool,
    and `PRAGMA foreign_keys=ON` because SQLite otherwise ignores foreign keys
    entirely — which would let a test pass on constraints Postgres enforces.
    """
    resolved = url or database_url()
    parsed = make_url(resolved)
    kwargs: dict[str, object] = {"echo": echo, "future": True}

    if parsed.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    else:
        kwargs["pool_pre_ping"] = True

    engine = create_engine(resolved, **kwargs)

    if parsed.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


@lru_cache
def engine() -> Engine:
    """The process-wide engine. Cached so pooling actually pools."""
    return create_app_engine()


@lru_cache
def session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """A transaction that commits on success and rolls back on any exception.

    A failed stage never leaves half-written state behind (02-architecture
    § Failure model).
    """
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency. One session per request, closed with the request."""
    with session_scope() as session:
        yield session
