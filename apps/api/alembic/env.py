"""Alembic environment.

The URL is resolved the same way the application resolves it — `DATABASE_URL`
from the environment, SQLite locally — so a migration can never run against a
different database from the one the app opens. It is never read from the ini
file, because a checked-in file is not a place for a credential (§53).
"""

from __future__ import annotations

import logging
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

API_ROOT = Path(__file__).resolve().parents[1]  # apps/api
REPO_ROOT = API_ROOT.parents[1]
CONTRACTS_SRC = REPO_ROOT / "packages" / "contracts" / "src"

for path in (API_ROOT, CONTRACTS_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core.db import create_app_engine, database_url  # noqa: E402
from app.db.models import Base  # noqa: E402

config = context.config

# Configure logging only if the host process has not already done so. Running a
# migration from inside a test or a running API must not tear down the JSON
# logging the app installed.
if config.config_file_name is not None and not logging.getLogger().handlers:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_app_engine(_url())
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                # SQLite cannot ALTER in place; batch mode makes later
                # migrations runnable on the local default as well as Postgres.
                render_as_batch=connection.dialect.name == "sqlite",
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
