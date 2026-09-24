"""DashboardBridge AI — API gateway.

Thin by design: validate, authorise, delegate, stream. All conversion
intelligence lives in engines/, which never imports FastAPI so it stays callable
from a CLI, the desktop shell, or a test with no server running.
"""

from __future__ import annotations

import logging
import uuid

from dashboardbridge_contracts import ApiError
from dashboardbridge_contracts.enums import ErrorCategory
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.rate_limit import CostBasedLimiter
from app.api import (
    accounts,
    analysis,
    artifacts,
    conversion,
    events,
    health,
    license as license_api,
    projects,
    proposals,
    report,
    settings as settings_api,
    validation,
    workspace,
)
from app.core import logging as log
from app.core.config import settings
from app.core.errors import install_error_handlers

from app.api.accounts import current_user  # noqa: E402

logger = logging.getLogger(__name__)
API_PREFIX = "/api/v1"

@asynccontextmanager
async def _lifespan(_: FastAPI):
    """Create the first administrator, if the operator asked for one (`P7.1`).

    A deployment with no accounts is one nobody can sign into, and there is
    deliberately no route that makes the first admin - an endpoint that creates
    one when the table is empty creates one on any deployment whose database has
    not finished migrating. So it comes from the environment, at start-up, the
    same shape as installing a licence: set it where the process reads it and
    restart.

    Does nothing once any account exists. A failure here is fatal on purpose: a
    deployment that was told to create an administrator and did not is one the
    operator believes is ready and is not.
    """
    from app.core.accounts import bootstrap_admin
    from app.core.db import session_scope

    with session_scope() as session:
        created = bootstrap_admin(session)
    if created is not None:
        logger.info(
            "created the first administrator from the environment",
            extra={"email": created.email},
        )
    yield


app = FastAPI(
    lifespan=_lifespan,
    title="DashboardBridge AI",
    version=settings().version,
    description=(
        "Explainable BI migration. Deterministic engineering at its core, "
        "AI only where it adds value."
    ),
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

log.configure()



#: One limiter for the process, on `app.state` so a test can reach it and reset
#: it. It is process-global by nature, and the suite fires hundreds of requests.
app.state.rate_limiter = CostBasedLimiter(
    per_minute_write=settings().rate_limit_write_per_minute,
    per_minute_read=settings().rate_limit_read_per_minute,
)


@app.middleware("http")
async def enforce_rate_limit(request: Request, call_next):
    """Refuse before the work, not after it (`P7.6`).

    Inside `attach_request_id` so a refusal still carries a request id, and
    inside CORS so the browser can actually read the 429 rather than reporting
    an opaque network failure - the same reason the error handler lives there.
    """
    verdict = app.state.rate_limiter.check(
        request.method, request.client.host if request.client else "unknown"
    )
    if verdict.allowed:
        return await call_next(request)

    response = JSONResponse(
        status_code=429,
        content=ApiError(
            category=ErrorCategory.VALIDATION_ERROR,
            message=(
                "Too many requests in a short time. Nothing was changed. Try "
                f"again in about {verdict.retry_after_seconds} seconds."
            ),
            detail=(
                "Rate limited by client address. Reads and writes are counted "
                "separately; this is the write limit unless the request was a "
                "GET. The counter is per process."
            ),
            request_id=log.request_id.get(),
        ).model_dump(mode="json"),
    )
    response.headers["retry-after"] = str(verdict.retry_after_seconds)
    return response


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    """Traceability, and the last place an unhandled error can still be read.

    An `app.exception_handler(Exception)` runs *outside* CORSMiddleware, so its
    response carries no CORS headers: a browser reports an opaque network
    failure and the user is told "we cannot reach the service" instead of the
    real, carefully-worded message. Catching here — inside CORS — is what makes
    the §46 two-message error survive the one case it matters most in.
    """
    rid = request.headers.get("x-request-id") or str(uuid.uuid4())
    token = log.request_id.set(rid)
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.exception("unhandled error", extra={"request_id": rid})
        response = _system_error(exc, rid)
    finally:
        log.request_id.reset(token)
    response.headers["x-request-id"] = rid
    return response


def _system_error(exc: Exception, request_id: str) -> JSONResponse:
    """Two messages, always: one for a person, one for an engineer (§46)."""
    return JSONResponse(
        status_code=500,
        content=ApiError(
            category=ErrorCategory.SYSTEM_ERROR,
            message=(
                "Something went wrong on our side. The operation was not "
                "completed, and nothing was changed."
            ),
            detail=f"{type(exc).__name__}: {exc}",
            request_id=request_id,
        ).model_dump(mode="json"),
    )


# The web app is the only browser client; in local mode nothing is remote.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # A browser cannot read a response header unless it is exposed, so
    # pagination and tracing would be invisible to the web app without this.
    # content-disposition carries the produced filename; without exposing it the
    # browser cannot read the name the server chose and has to invent one.
    expose_headers=["x-request-id", "x-next-cursor", "content-disposition"],
)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Backstop for anything raised outside the middleware above."""
    return _system_error(exc, log.request_id.get())


# Every failure leaves through the same door, in the same shape (§46).
install_error_handlers(app)

#: Every route that touches a workbook, a project or a conversion. Signing in is
#: required for all of them, and the list is written out rather than derived
#: from a path prefix: a router added tomorrow is not silently public because
#: its URL happened not to match a pattern.
#:
#: Deliberately *not* here:
#:
#: * `health` - a load balancer and a starting web app both need it before
#:   anyone has signed in, and it says only whether the service is up.
#: * `license` - the licence banner has to be readable on the sign-in page. A
#:   deployment whose licence has lapsed must be able to say so to the person
#:   about to try signing in, rather than after.
#: * `accounts` - signing in cannot require being signed in. Its own routes
#:   depend on `current_user` individually where they need it.
_SIGNED_IN = [Depends(current_user)]

app.include_router(health.router, prefix=API_PREFIX)
app.include_router(accounts.router, prefix=API_PREFIX)
app.include_router(license_api.router, prefix=API_PREFIX)
app.include_router(projects.router, prefix=API_PREFIX, dependencies=_SIGNED_IN)
app.include_router(artifacts.router, prefix=API_PREFIX, dependencies=_SIGNED_IN)
app.include_router(analysis.router, prefix=API_PREFIX, dependencies=_SIGNED_IN)
app.include_router(conversion.router, prefix=API_PREFIX, dependencies=_SIGNED_IN)
app.include_router(validation.router, prefix=API_PREFIX, dependencies=_SIGNED_IN)
app.include_router(events.router, prefix=API_PREFIX, dependencies=_SIGNED_IN)
app.include_router(report.router, prefix=API_PREFIX, dependencies=_SIGNED_IN)
app.include_router(settings_api.router, prefix=API_PREFIX, dependencies=_SIGNED_IN)
app.include_router(proposals.router, prefix=API_PREFIX, dependencies=_SIGNED_IN)
app.include_router(workspace.router, prefix=API_PREFIX, dependencies=_SIGNED_IN)
