"""The conversion report endpoint.

Thin, like every other route here. It gathers contracts that have already
crossed this boundary — the project, the conversion, the validation if there is
one — and hands them to a renderer. Nothing in the report is computed here,
because a report that derived its own figures could disagree with the endpoints
it claims to summarise.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from dashboardbridge_contracts import (
    AuditEntry,
    Conversion,
    ConversionReport,
    Project,
    Validation,
)
from dashboardbridge_contracts.enums import ErrorCategory, Outcome, Stage, Verdict
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.queries import latest_job as _latest
from app.api.projects import load_project
from app.core.db import get_session
from app.core.errors import ApiException
from app.db.models import JobKind as DbJobKind
from app.services.report import render_html

router = APIRouter(tags=["report"])


#: The engine names its stages in its own words - and in its own case: events
#: say "Parse" while flags say "parse". Keys here are folded before lookup, so
#: a capital is not the difference between a stage and the fallback.
_STAGE = {
    "extract": Stage.EXTRACT,
    "parse": Stage.PARSE,
    "visual_map": Stage.MAP,
    "map": Stage.MAP,
    "translate": Stage.TRANSLATE,
    "emit": Stage.GENERATE,
    "generate": Stage.GENERATE,
    "report": Stage.REPORT,
}


def _stage(name: str) -> Stage:
    """A stage the contract does not know is a defect between the two, not a
    row to relabel. It still renders - a report is not the place to raise - but
    it lands on `report`, the stage that describes the run rather than one that
    claims work was done there."""
    return _STAGE.get(name.strip().casefold(), Stage.REPORT)


def _audit(timeline: dict | None) -> list[AuditEntry]:
    """The engine's recording, as the contract sees it.

    `elapsed_ms` is deliberately dropped: it belongs to a run in progress, and
    a record of a finished one has to be identical on every read and on every
    re-run, or it cannot be diffed or attached to a ticket.
    """
    if not timeline:
        return []
    return [
        AuditEntry(
            seq=event.get("seq", index),
            stage=_stage(event.get("stage", "")),
            kind=event.get("kind", ""),
            name=event.get("name", ""),
            outcome=Outcome(event.get("outcome", Outcome.HELD.value)),
            detail=event.get("detail", ""),
            ref=event.get("ref", ""),
            source=event.get("source", ""),
            result=event.get("result", ""),
        )
        for index, event in enumerate(timeline.get("events", []))
    ]


def _report(session: Session, project_id: UUID) -> ConversionReport:
    project = load_project(session, project_id)
    job = _latest(session, project_id, DbJobKind.CONVERSION)
    if job is None or job.result is None:
        raise ApiException(
            ErrorCategory.CONVERSION_ERROR,
            "There is nothing to report yet. Convert the workbook first, and "
            "the report will describe what happened to every object in it.",
            detail=f"no completed conversion for project {project_id}",
            status_code=409,
        )

    conversion = Conversion.model_validate(job.result)
    validation_job = _latest(session, project_id, DbJobKind.VALIDATION)
    validation = (
        Validation.model_validate(validation_job.result)
        if validation_job is not None and validation_job.result is not None
        else None
    )
    return ConversionReport(
        project=Project(
            project_id=project.project_id,
            name=project.name,
            source_platform=project.source_platform,
            target_platform=project.target_platform,
            created_at=project.created_at,
        ),
        # Read off the validation, never recomputed. With no validation the
        # answer is `unverified`: files exist and nothing has been checked.
        verdict=validation.verdict if validation is not None else Verdict.UNVERIFIED,
        compatibility=conversion.compatibility,
        flags=conversion.flags,
        validation=validation,
        audit=_audit(job.timeline),
    )


@router.get("/projects/{project_id}/report")
def get_report(
    project_id: UUID,
    format: Literal["json", "html"] = Query(
        default="json",
        description="PDF and CSV are later (05-api-spec).",
    ),
    session: Session = Depends(get_session),
):
    """The report, in the one of two formats that were asked for.

    An unrecognised format is refused rather than served as the default. This
    document is a deliverable, and quietly handing back JSON to something that
    asked for a PDF is how an empty attachment reaches a stakeholder.
    """
    report = _report(session, project_id)
    if format == "html":
        return HTMLResponse(render_html(report))
    return report
