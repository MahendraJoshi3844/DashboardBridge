"""Shared fixtures for the DashboardBridge API tests.

Each test gets a throwaway SQLite file and its own artifact store, so nothing
leaks between tests and no server or Postgres is required to run the suite.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.db import create_app_engine, get_session
from app.services.artifact_store import LocalFilesystemStore, get_artifact_store
from app.db.models import Base
from app.main import app

PREFIX = "/api/v1"

#: The account every API test acts as. A real login rather than a stubbed
#: `current_user`: overriding the dependency would mean the suite never
#: exercises the cookie, the digest lookup or the expiry checks, and the test
#: asserting a route is *not* public would be asserting against a stub.
FIXTURE_EMAIL = "fixture@dashboardbridge.test"
FIXTURE_PASSWORD = "fixture password long enough"


def sign_in(client, factory) -> None:
    """Create the deployment's first administrator and sign the client in.

    Shared because it was not, once: `test_projects.py` and `test_artifacts.py`
    each carried their own copy of the `api` fixture, and when every data route
    started requiring a session (`P7.1`) only the `conftest` copy signed in.
    Both modules 401'd against a fixture that looked identical to the one that
    worked.
    """
    from app.core.accounts import create_user

    with factory() as bootstrap:
        create_user(
            bootstrap,
            email=FIXTURE_EMAIL,
            display_name="Fixture",
            password=FIXTURE_PASSWORD,
            is_admin=True,
            enforce_seats=False,
        )
        bootstrap.commit()

    response = client.post(
        f"{PREFIX}/auth/login",
        json={"email": FIXTURE_EMAIL, "password": FIXTURE_PASSWORD},
    )
    assert response.status_code == 200, response.text



@contextmanager
def _deployment(tmp_path: Path, monkeypatch, *, signed_in: bool):
    """One throwaway deployment. Two fixtures, one implementation.

    Copies of this were what drifted last time - `test_projects.py` and
    `test_artifacts.py` each had one, and only the `conftest` copy learned to
    sign in when every data route started requiring a session.
    """
    monkeypatch.setenv("ARTIFACT_STORAGE_DIR", str(tmp_path / "artifacts"))

    engine = create_app_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'api.db').as_posix()}"
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def _session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # The limiter is process-global and the suite fires hundreds of requests,
    # so a neighbouring test must not be able to cause a 429 here. A test
    # that wants a limit sets one deliberately.
    app.state.rate_limiter.configure(per_minute_write=0, per_minute_read=0)

    store = LocalFilesystemStore(tmp_path / "artifacts")
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_artifact_store] = lambda: store

    with TestClient(app, raise_server_exceptions=False) as client:
        if signed_in:
            sign_in(client, factory)
        # `session_factory` so an account test can put a user straight into
        # the database - creating the first administrator is an operator's
        # job on the machine, and there is deliberately no route for it.
        yield SimpleNamespace(
            client=client,
            storage=tmp_path / "artifacts",
            session_factory=factory,
        )
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    """A client signed in as an administrator. What almost every test wants."""
    with _deployment(tmp_path, monkeypatch, signed_in=True) as deployment:
        yield deployment


@pytest.fixture
def empty_api(tmp_path: Path, monkeypatch):
    """A deployment with **no accounts at all** and nobody signed in.

    For the tests that are about accounts themselves: they create exactly the
    people they mean to, and a pre-made administrator would silently occupy a
    seat and change every count they assert on.
    """
    with _deployment(tmp_path, monkeypatch, signed_in=False) as deployment:
        yield deployment


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Configuration is read once and cached, so a test that changes it leaks.

    `settings()` is `lru_cache`d, which is right for a process and wrong for a
    suite: a test that sets `AI_PROVIDER` and clears the cache to be seen leaves
    the *next* test looking at a provider it never configured. `monkeypatch`
    restores the environment but knows nothing about the cache.

    Found the way these things are: one test passing alone and failing in the
    full run.
    """
    from app.core.config import settings

    settings.cache_clear()
    yield
    settings.cache_clear()


@pytest.fixture(autouse=True, scope="session")
def _licensed():
    """Every test runs under a valid licence, because the product requires one.

    The licence gate is real: without this the whole suite would 402 at the
    conversion endpoint, which is the gate working rather than a problem to
    route around. So the suite installs a licence and exercises the licensed
    path; `test_license_enforcement.py` owns the expired, missing and forged
    paths deliberately.

    A keypair per session, generated here. Nothing is committed: a private key
    in the repository would let any customer mint themselves a perpetual
    licence, and `tests/test_licensing.py` fails if one ever appears.
    """
    from datetime import date, timedelta

    from engines.licensing import generate_keypair, issue
    from app.core import licensing

    private, public = generate_keypair()
    token = issue(
        private_key=private,
        customer="Test Suite",
        issued=date.today() - timedelta(days=1),
        expires=date.today() + timedelta(days=3650),
        features=("convert", "ai"),
        seats=99,
    )
    original_key = licensing.VENDOR_PUBLIC_KEY
    licensing.VENDOR_PUBLIC_KEY = public
    os.environ["LICENSE_KEY"] = token
    licensing.status.cache_clear()
    yield
    licensing.VENDOR_PUBLIC_KEY = original_key
    os.environ.pop("LICENSE_KEY", None)
    licensing.status.cache_clear()
