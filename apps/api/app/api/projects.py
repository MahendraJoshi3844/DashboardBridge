"""Projects — the thing an artifact, a job and a report all belong to.

Thin by design (02-architecture): validate, authorise, delegate. There is no
conversion knowledge in this module and there never will be.

Two decisions worth stating, because both look like fussiness until the day they
are not:

* **Pagination is by cursor, not offset.** Offsets shift when a row is inserted,
  so page 2 silently skips a project. The cursor is the `(created_at,
  project_id)` of the last row returned, which is stable whatever else arrives.
* **The ordering is total.** `created_at` alone is not unique — three projects
  created in the same millisecond are ordered arbitrarily, and an arbitrary
  order is not a deterministic one (02-architecture § Determinism).
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
from uuid import UUID

from dashboardbridge_contracts import Project as ProjectContract
from dashboardbridge_contracts.api import CreateProjectRequest
from dashboardbridge_contracts.enums import ErrorCategory
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.directions import require_direction
from app.core.errors import ApiException
from app.db.models import Project as ProjectRow

router = APIRouter(tags=["projects"])

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

#: The header a truncated page uses to say how to continue. The contracts
#: package has no pagination envelope, and inventing one here would put a second
#: source of truth beside `packages/contracts` (see the report).
NEXT_CURSOR_HEADER = "x-next-cursor"


def to_contract(row: ProjectRow) -> ProjectContract:
    return ProjectContract(
        project_id=row.project_id,
        name=row.name,
        source_platform=row.source_platform,
        target_platform=row.target_platform,
        created_at=_as_utc(row.created_at),
    )


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back a naive datetime; Postgres hands back an aware one.

    Serialising the same row differently depending on which database is
    underneath would make `POST` and a later `GET` disagree about the same
    project, so the boundary settles it in one place: everything is UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# cursor
# ---------------------------------------------------------------------------


def _encode_cursor(row: ProjectRow) -> str:
    raw = f"{_as_utc(row.created_at).isoformat()}|{row.project_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created_at, _, project_id = (
            base64.urlsafe_b64decode(padded.encode()).decode().partition("|")
        )
        return datetime.fromisoformat(created_at), UUID(project_id)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ApiException(
            ErrorCategory.SYSTEM_ERROR,
            "That page of results could not be loaded. Start from the "
            "beginning of the list.",
            detail=f"undecodable cursor {cursor!r}: {type(exc).__name__}: {exc}",
            status_code=400,
        ) from exc


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@router.post("/projects", response_model=ProjectContract, status_code=201)
def create_project(
    body: CreateProjectRequest,
    session: Session = Depends(get_session),
) -> ProjectContract:
    """`201` → `Project`.

    The "source and target must differ" rule lives in the contract, so it is
    enforced identically for the API, the desktop shell and the generated
    TypeScript client. What this layer owes it is a decent error: see
    `app.core.errors.request_validation_handler`, which turns that rule into the
    documented `400 UNSUPPORTED_ARTIFACT` instead of a pydantic dump.
    """
    # Refused here, before anything is stored: a project in a direction this
    # deployment cannot run would only fail later, after an upload.
    require_direction(body.source_platform, body.target_platform)
    row = ProjectRow(
        name=body.name,
        source_platform=body.source_platform,
        target_platform=body.target_platform,
    )
    session.add(row)
    session.flush()
    # Commit before answering. The request's session scope only closes after
    # the response is sent (FastAPI runs yield-dependency teardown late), so a
    # client that follows up at once - /auth/me right after signing in, an
    # upload right after creating the project - could otherwise not see this.
    session.commit()
    return to_contract(row)


@router.get("/projects", response_model=list[ProjectContract])
def list_projects(
    response: Response,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None),
    session: Session = Depends(get_session),
) -> list[ProjectContract]:
    statement = select(ProjectRow).order_by(
        ProjectRow.created_at.asc(), ProjectRow.project_id.asc()
    )

    if cursor:
        created_at, project_id = _decode_cursor(cursor)
        statement = statement.where(
            or_(
                ProjectRow.created_at > created_at,
                and_(
                    ProjectRow.created_at == created_at,
                    ProjectRow.project_id > project_id,
                ),
            )
        )

    # One extra row answers "is there a next page?" without a second COUNT that
    # can disagree with the page it describes.
    rows = list(session.scalars(statement.limit(limit + 1)))
    page, has_more = rows[:limit], len(rows) > limit
    if has_more:
        response.headers[NEXT_CURSOR_HEADER] = _encode_cursor(page[-1])
    return [to_contract(row) for row in page]


@router.get("/projects/{project_id}", response_model=ProjectContract)
def get_project(
    project_id: UUID,
    session: Session = Depends(get_session),
) -> ProjectContract:
    return to_contract(load_project(session, project_id))


# ---------------------------------------------------------------------------
# shared
# ---------------------------------------------------------------------------


def load_project(session: Session, project_id: UUID) -> ProjectRow:
    """The project, or a typed 404.

    Shared with the artifact routes: *"every read is authorised against the
    project; object ids are never sufficient authority"* (09-security-spec
    § Transport and tenancy). Authentication arrives in a later phase; the
    single lookup point it will hang off exists now, so there is one place to
    change rather than one per route.
    """
    row = session.get(ProjectRow, project_id)
    if row is None:
        raise ApiException(
            ErrorCategory.NOT_FOUND,
            "That project could not be found. It may have been deleted. "
            "Start a new migration.",
            detail=f"no project row with project_id={project_id}",
            status_code=404,
            project_id=project_id,
        )
    return row
