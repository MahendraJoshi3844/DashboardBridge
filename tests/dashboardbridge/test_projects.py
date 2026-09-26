"""Projects over the API.

A project is the only thing that gives an artifact somewhere to belong, so the
interesting claims here are not "a row was written" but:

1. A project round-trips: what came back from `POST` is what `GET` returns.
2. A contract violation surfaces as an `ApiError` with **both** messages, never
   as FastAPI's raw 422 dump, and the human half never contains a stack trace,
   a filesystem path or an HTTP status code (§46).
3. Two identical platforms are refused as `UNSUPPORTED_ARTIFACT` (05-api-spec
   § Projects), not coerced into something plausible.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.db import create_app_engine, get_session
from app.db.models import Base
from app.main import app

PREFIX = "/api/v1"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


# The `api` fixture lives in `conftest.py`. It was copied into this file and
# into `test_artifacts.py`, and the copies drifted: when every data route
# started requiring a session (`P7.1`), only the shared one signed in, so this
# module 401'd against a fixture that looked identical to the one that worked.


def create(api, **overrides) -> dict:
    payload = {
        "source_platform": "tableau",
        "target_platform": "powerbi",
        "name": "Sales migration",
    }
    payload.update(overrides)
    return api.client.post(f"{PREFIX}/projects", json=payload)


# ---------------------------------------------------------------------------
# the human half of an error (§46)
# ---------------------------------------------------------------------------

#: A drive letter, a POSIX path, a traceback marker, or a bare HTTP code. Each
#: of these has leaked out of a "user-friendly" message at some point in the
#: life of every product; none of them helps the person reading it.
_LEAKS = (
    re.compile(r"[A-Za-z]:[\\/]"),
    re.compile(r"(?<!\w)/(?:home|usr|var|tmp|Users)/"),
    re.compile(r"Traceback"),
    # A bare status code. The lookahead keeps a legitimate "500 MB" size limit
    # from being mistaken for an HTTP 500.
    re.compile(r"\b(?:400|401|403|404|409|413|422|500)\b(?!\s*(?:MB|GB|KB|bytes))"),
)


def assert_error_shape(body: dict) -> None:
    assert body["category"], "every error carries a category"
    assert body["message"], "a message for a person is never optional"
    assert body["detail"], "a detail for an engineer is never optional"
    for leak in _LEAKS:
        assert not leak.search(body["message"]), (
            f"human message leaked {leak.pattern!r}: {body['message']!r}"
        )


# ---------------------------------------------------------------------------
# round trip
# ---------------------------------------------------------------------------


def test_a_project_round_trips(api):
    created = create(api)
    assert created.status_code == 201, created.text
    body = created.json()

    assert body["name"] == "Sales migration"
    assert body["source_platform"] == "tableau"
    assert body["target_platform"] == "powerbi"
    assert body["project_id"]
    assert body["created_at"]

    fetched = api.client.get(f"{PREFIX}/projects/{body['project_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_listing_returns_what_was_created(api):
    ids = {create(api, name=f"Migration {n}").json()["project_id"] for n in range(3)}
    listed = api.client.get(f"{PREFIX}/projects")
    assert listed.status_code == 200
    assert {p["project_id"] for p in listed.json()} == ids


def test_listing_is_paginated_deterministically(api):
    for n in range(5):
        create(api, name=f"Migration {n}")

    first = api.client.get(f"{PREFIX}/projects", params={"limit": 2})
    assert len(first.json()) == 2
    cursor = first.headers.get("x-next-cursor")
    assert cursor, "a truncated page must say how to continue"

    second = api.client.get(f"{PREFIX}/projects", params={"limit": 2, "cursor": cursor})
    assert len(second.json()) == 2
    assert {p["project_id"] for p in first.json()}.isdisjoint(
        {p["project_id"] for p in second.json()}
    )

    # Same request, same answer: pagination is not allowed to shuffle.
    again = api.client.get(f"{PREFIX}/projects", params={"limit": 2})
    assert again.json() == first.json()


# ---------------------------------------------------------------------------
# contract violations are errors, not dumps
# ---------------------------------------------------------------------------


def test_matching_platforms_are_refused_as_unsupported(api):
    response = create(api, target_platform="tableau")
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["category"] == "UNSUPPORTED_ARTIFACT"
    assert_error_shape(body)
    assert "differ" in body["message"] or "different" in body["message"]


def test_an_unknown_platform_is_a_typed_error_not_a_raw_422_dump(api):
    response = create(api, source_platform="looker")  # a platform with no reader
    body = response.json()
    assert set(body) >= {"category", "message", "detail", "request_id"}
    assert "detail" in body and isinstance(body["detail"], str)
    assert_error_shape(body)
    # FastAPI's own shape is {"detail": [ {...loc...} ]} — a list, not a string.
    assert not isinstance(body["detail"], list)


def test_an_empty_name_is_refused_with_both_messages(api):
    response = create(api, name="")
    assert response.status_code in (400, 422)
    assert_error_shape(response.json())


def test_an_unknown_project_is_reported_not_crashed(api):
    response = api.client.get(f"{PREFIX}/projects/11111111-1111-4111-8111-111111111111")
    assert response.status_code == 404
    assert_error_shape(response.json())


def test_a_malformed_project_id_is_a_typed_error(api):
    response = api.client.get(f"{PREFIX}/projects/not-a-uuid")
    assert_error_shape(response.json())


def test_every_error_carries_the_request_id_for_tracing(api):
    response = api.client.post(
        f"{PREFIX}/projects",
        json={
            "source_platform": "tableau",
            "target_platform": "tableau",
            "name": "x",
        },
        headers={"x-request-id": "trace-me"},
    )
    assert response.json()["request_id"] == "trace-me"


def test_projects_appear_in_the_generated_openapi_schema(api):
    schemas = api.client.get("/api/openapi.json").json()["components"]["schemas"]
    assert "Project" in schemas
    assert "CreateProjectRequest" in schemas
