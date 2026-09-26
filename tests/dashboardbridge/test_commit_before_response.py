"""Writes are committed before the response is sent.

FastAPI runs a yield-dependency's teardown - where `get_session` commits - only
after the response has gone out. A client that follows up at once then races the
commit: signing in and immediately asking `/auth/me` returned 401 about one time
in two in a real browser, and the Migrate dialog creates a project and uploads to
it back to back.

`TestClient` cannot show the race (it returns only when the whole request, teardown
included, is finished), so these tests call the endpoints the way FastAPI does but
keep the request's session open, and look from a *second* connection - where the
next request would look.
"""

from __future__ import annotations

from dashboardbridge_contracts import LoginRequest
from dashboardbridge_contracts.api import CreateProjectRequest
from dashboardbridge_contracts.enums import Platform
from fastapi import Response
from sqlalchemy import func, select
from starlette.requests import Request

from app.api.accounts import login
from app.api.projects import create_project
from app.db.models import Project, Session

from tests.dashboardbridge.conftest import FIXTURE_EMAIL, FIXTURE_PASSWORD


def _request() -> Request:
    return Request({"type": "http", "scheme": "http", "method": "POST", "path": "/",
                    "headers": [], "query_string": b"", "server": ("test", 80)})


def _count(factory, model) -> int:
    with factory() as other:
        return other.scalar(select(func.count()).select_from(model))


def test_a_new_sign_in_is_visible_to_the_next_request(api):
    factory = api.session_factory
    before = _count(factory, Session)
    held = factory()  # the request's own session, still open - as while the response goes out
    try:
        login(LoginRequest(email=FIXTURE_EMAIL, password=FIXTURE_PASSWORD), _request(), Response(), session=held)
        assert _count(factory, Session) == before + 1
    finally:
        held.close()


def test_a_new_project_is_visible_to_the_next_request(api):
    factory = api.session_factory
    before = _count(factory, Project)
    held = factory()
    try:
        create_project(CreateProjectRequest(source_platform=Platform.QLIK, target_platform=Platform.POWERBI,
                                            name="Race"), session=held)
        assert _count(factory, Project) == before + 1
    finally:
        held.close()
