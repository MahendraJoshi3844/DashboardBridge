"""Errors that carry two messages, always both (§46).

```json
{"category": "...", "message": "for a person", "detail": "for an engineer"}
```

The split is not cosmetic. A person reading *"Opening and ending tag mismatch:
worksheet line 4412"* learns nothing they can act on; an engineer reading *"We
could not read the workbook"* learns nothing they can debug. Collapsing the two
loses one audience whichever way it is collapsed, so neither substitutes for the
other and neither is optional.

The human half is held to a rule the spec states plainly: it *never* contains a
stack trace, a filesystem path, or an HTTP status code. That rule is enforced
here rather than trusted to the discipline of every future call site —
`ApiException` inspects its own message and, if a leak got in, keeps it for the
engineer and substitutes a safe sentence for the person. A control that depends
on nobody ever making a mistake is not a control.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from dashboardbridge_contracts import ApiError
from dashboardbridge_contracts.enums import ErrorCategory
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import logging as log

#: Patterns that must never reach a person. A drive letter or POSIX system path
#: tells an attacker about the host and tells a user nothing; a traceback is an
#: implementation detail; a bare status code is protocol, not language.
#: The size lookahead keeps a legitimate "500 MB" limit from tripping the
#: HTTP-500 pattern.
_LEAKY = (
    re.compile(r"[A-Za-z]:[\\/]"),
    re.compile(r"(?<!\w)/(?:home|usr|var|tmp|etc|Users)/"),
    re.compile(r"Traceback|File \"|line \d+, in "),
    re.compile(r"\b(?:400|401|403|404|409|413|422|500|502|503)\b(?!\s*(?:MB|GB|KB|bytes))"),
)

_SUBSTITUTE = (
    "Something went wrong and the operation was not completed. Nothing was "
    "changed. Open the technical details, or send them to your administrator."
)


def is_human_safe(message: str) -> bool:
    """True when `message` is fit for a person to read (§46)."""
    return not any(pattern.search(message) for pattern in _LEAKY)


class ApiException(Exception):
    """A failure with a category, a status, and both messages.

    Raised by services as well as routes: a service that can only return `None`
    forces its caller to invent a reason, and an invented reason is a guess.
    """

    def __init__(
        self,
        category: ErrorCategory,
        message: str,
        *,
        detail: str = "",
        status_code: int = 400,
        project_id: UUID | None = None,
    ) -> None:
        safe = is_human_safe(message)
        # A leak is kept — for the engineer — not deleted. Losing the text
        # would hide the very mistake this check exists to catch.
        self.message = message if safe else _SUBSTITUTE
        self.detail = detail if safe else f"{detail} :: unsafe message: {message}".strip()
        self.category = category
        self.status_code = status_code
        self.project_id = project_id
        super().__init__(f"{category.value}: {self.detail or self.message}")

    def to_api_error(self) -> ApiError:
        return ApiError(
            category=self.category,
            message=self.message,
            detail=self.detail or self.message,
            request_id=log.request_id.get(),
            project_id=self.project_id,
        )

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content=self.to_api_error().model_dump(mode="json"),
        )


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------


async def api_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiException)
    return exc.to_response()


#: The model validator in `CreateProjectRequest` raises this exact text. Matching
#: on it is stringly-typed and unlovely, but the alternative is either a second
#: source of truth for the rule or letting a documented `400 UNSUPPORTED_ARTIFACT`
#: reach the client as a 422 list of pydantic `loc` tuples.
_PLATFORMS_MUST_DIFFER = "source_platform and target_platform must differ"


def _summarise(errors: list[dict[str, Any]]) -> str:
    parts = []
    for error in errors:
        where = ".".join(str(piece) for piece in error.get("loc", ()))
        parts.append(f"{where}: {error.get('msg', '')}".strip(": "))
    return "; ".join(parts) or "request validation failed"


async def request_validation_handler(_: Request, exc: Exception) -> JSONResponse:
    """FastAPI's 422 body is a list of pydantic errors. That is a dump, not an
    error message, and it is the wrong shape for a client that has been told
    every failure looks like `ApiError`."""
    assert isinstance(exc, RequestValidationError)
    errors = list(exc.errors())
    detail = _summarise(errors)

    if _PLATFORMS_MUST_DIFFER in detail:
        return ApiException(
            ErrorCategory.UNSUPPORTED_ARTIFACT,
            "A migration needs two different platforms: choose a source and a "
            "target that are not the same.",
            detail=detail,
            status_code=400,
        ).to_response()

    return ApiException(
        ErrorCategory.SYSTEM_ERROR,
        "That request was not in a form we could accept. Check the fields and "
        "try again.",
        detail=detail,
        status_code=422,
    ).to_response()


async def http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """Starlette's own errors, in the shape the client was promised.

    This also recovers a swallowed refusal. FastAPI wraps *any* exception raised
    while parsing a request body into `HTTPException(400, "There was an error
    parsing the body")`, which would turn a deliberate "this upload is over the
    limit" into a generic parse failure and lose both the category and the
    reason. The original is still on `__cause__`, so it is used when it is ours.
    """
    assert isinstance(exc, StarletteHTTPException)
    cause = exc.__cause__
    if isinstance(cause, ApiException):
        return cause.to_response()

    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return ApiException(
        ErrorCategory.SYSTEM_ERROR,
        "That request could not be completed.",
        detail=detail,
        status_code=exc.status_code,
    ).to_response()


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiException, api_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
