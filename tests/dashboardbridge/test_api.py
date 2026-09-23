"""The API gateway. Thin, typed, and honest about failure."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_health_reports_the_active_privacy_mode():
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["privacy_mode"] in {"standard", "local_only", "enterprise_private"}


def test_ai_is_absent_when_no_provider_is_configured():
    """Absent, not degraded: the UI must not offer what will fail."""
    assert client.get("/api/v1/health").json()["ai_available"] is False


def test_the_safe_privacy_mode_is_the_default():
    """Nothing configured must not mean 'allowed to call out'."""
    assert client.get("/api/v1/health").json()["privacy_mode"] == "local_only"


def test_every_response_carries_a_request_id():
    assert client.get("/api/v1/health").headers.get("x-request-id")


def test_a_supplied_request_id_is_preserved_for_tracing():
    response = client.get("/api/v1/health", headers={"x-request-id": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


def test_an_unhandled_error_returns_both_messages_never_a_bare_500():
    @app.get("/api/v1/_boom")
    async def boom():  # pragma: no cover - exercised via the client
        raise RuntimeError("engine exploded")

    body = client.get("/api/v1/_boom").json()
    assert body["category"] == "SYSTEM_ERROR"
    assert "went wrong" in body["message"]
    assert "RuntimeError" in body["detail"], "engineers need the real cause"
    assert "RuntimeError" not in body["message"], "people must not see a traceback"


def test_the_openapi_schema_is_generated_from_the_contracts():
    schemas = client.get("/api/openapi.json").json()["components"]["schemas"]
    assert "HealthResponse" in schemas


def test_a_failure_response_is_readable_by_the_browser():
    """CORS headers must survive a 500.

    Starlette applies an app-level exception handler outside CORSMiddleware, so
    the careful two-message error arrives with no CORS headers and the browser
    reports an opaque network failure. The user is then told "we cannot reach
    the service" - the least useful sentence available - in exactly the case
    where the real message matters most.
    """
    @app.get("/api/v1/_cors_probe")
    async def probe():  # pragma: no cover - exercised via the client
        raise RuntimeError("engine exploded")

    origin = {"origin": "http://localhost:3000"}
    healthy = client.get("/api/v1/health", headers=origin)
    failed = client.get("/api/v1/_cors_probe", headers=origin)

    assert healthy.headers.get("access-control-allow-origin")
    assert failed.headers.get("access-control-allow-origin"), (
        "a 500 lost its CORS headers; the browser cannot read the error body"
    )
    assert failed.json()["category"] == "SYSTEM_ERROR"


def test_the_produced_filename_is_readable_by_the_browser():
    """Without exposing content-disposition the client must invent a filename."""
    exposed = client.get(
        "/api/v1/health", headers={"origin": "http://localhost:3000"}
    ).headers.get("access-control-expose-headers", "")
    assert "content-disposition" in exposed.lower()
