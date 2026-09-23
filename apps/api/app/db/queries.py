"""Queries more than one route needs.

`latest_job` lived in `app.api.conversion` and was imported from there by every
route that needed it, which worked until `conversion` needed something back from
one of them - `proposals` - and the two modules could not both be imported
first.

A shared query does not belong to whichever endpoint happened to want it first.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Job as JobRow
from app.db.models import JobKind


def latest_job(session: Session, project_id: UUID, kind: JobKind) -> JobRow | None:
    """The most recent job of one kind for a project, or nothing.

    Ordered by `created_at` rather than by id, because a uuid has no order and
    "the latest" has to mean the latest in time.
    """
    return session.scalars(
        select(JobRow)
        .where(JobRow.project_id == project_id, JobRow.kind == kind)
        .order_by(JobRow.created_at.desc())
    ).first()
