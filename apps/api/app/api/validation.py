"""Validation endpoints. The product's licence to make a claim.

Everything here is arranged around one rule: nothing is reported as verified
that was not checked against the artifact we actually delivered. So the target
under test is the **stored zip**, re-read by the validator's own parser, not the
in-memory project the emitter still has open. Validating the emitter's
intentions would prove only that the emitter is self-consistent.

The determinism rule is the reason this endpoint converts a second time. A
replica is the only way to answer "does this workbook convert the same way
twice", and answering it from a cache would be assuming the thing under test.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from dashboardbridge_contracts import (
    Conversion,
    Job,
    Validation,
    ValidationRuleResult,
)
from dashboardbridge_contracts.enums import (
    ArtifactKind,
    ErrorCategory,
    JobKind,
    JobStatus,
    Platform,
    Verdict,
)
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.conversion import _source
from app.db.queries import latest_job as _latest
from app.api.projects import load_project
from app.core.db import get_session
from app.core.errors import ApiException
from app.db.models import Artifact as ArtifactRow
from app.db.models import Job as JobRow
from app.db.models import JobKind as DbJobKind
from app.db.models import JobStatus as DbJobStatus
from app.services.artifact_store import ArtifactStore, get_artifact_store
from engines.conversion.run import convert_tableau_to_powerbi
from engines.validation import TargetProject, validate

logger = logging.getLogger(__name__)
router = APIRouter(tags=["validation"])


def _delivered(session: Session, project_id: UUID) -> ArtifactRow:
    return session.scalars(
        select(ArtifactRow)
        .where(
            ArtifactRow.project_id == project_id,
            ArtifactRow.kind == ArtifactKind.TARGET.value,
        )
        .order_by(ArtifactRow.created_at.desc())
    ).first()


@router.post(
    "/projects/{project_id}/validation",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_validation(
    project_id: UUID,
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> Job:
    """Validate the delivered project against the model it came from.

    Runs inline, like analysis and conversion, because the work is a second
    conversion plus a file diff — well under a second on a real workbook.
    """
    project = load_project(session, project_id)
    conversion_job = _latest(session, project_id, DbJobKind.CONVERSION)
    produced = _delivered(session, project_id)
    if conversion_job is None or conversion_job.result is None or produced is None:
        raise ApiException(
            ErrorCategory.VALIDATION_ERROR,
            "There is nothing to validate yet. Convert the workbook first, and "
            "then we can check what was produced against what you uploaded.",
            detail=f"no completed conversion for project {project_id}",
            status_code=409,
        )

    # The source model and its flags are the conversion's own report of what it
    # did. Validation holds that report to account against the artifact; it does
    # not recompute it, because a rederived report would agree with itself.
    conversion = Conversion.model_validate(conversion_job.result)
    job = JobRow(job_id=uuid4(), project_id=project_id, kind=DbJobKind.VALIDATION)
    session.add(job)
    job.transition_to(DbJobStatus.RUNNING)
    session.flush()

    if Platform(project.target_platform) is Platform.TABLEAU:
        job.result = _unverified_tableau(job.job_id).model_dump(mode="json")
        job.transition_to(DbJobStatus.COMPLETED)
        session.commit()
        return Job(
            job_id=job.job_id, kind=JobKind.VALIDATION, status=JobStatus.COMPLETED
        )

    try:
        target = TargetProject.from_zip(store.read(produced.storage_key))
        replica = _reconvert(store, session, project_id, project.name or "project")
        result = validate(
            validation_id=job.job_id,
            model=conversion.model,
            flags=conversion.flags,
            target=target,
            replica=replica,
        )
    except Exception as exc:
        job.transition_to(DbJobStatus.FAILED)
        job.error_category = ErrorCategory.VALIDATION_ERROR.value
        session.commit()
        logger.exception("validation failed", extra={"project_id": str(project_id)})
        raise ApiException(
            ErrorCategory.VALIDATION_ERROR,
            "The validation did not finish, so we cannot tell you whether the "
            "conversion is sound. The converted project is unchanged.",
            detail=f"{type(exc).__name__}: {exc}",
            project_id=project_id,
        ) from exc

    job.result = result.model_dump(mode="json")
    job.transition_to(DbJobStatus.COMPLETED)
    session.commit()

    logger.info(
        "validation completed",
        extra={
            "project_id": str(project_id),
            "job_id": str(job.job_id),
            "operation": "validation",
            "verdict": result.verdict.value,
        },
    )
    return Job(job_id=job.job_id, kind=JobKind.VALIDATION, status=JobStatus.COMPLETED)


#: Why a Tableau workbook is never more than unverified today. Shown to people.
TABLEAU_READBACK_NOTE = (
    "No check reads a produced Tableau workbook back yet, so nothing about "
    "this one has been verified against the Power BI project it came from. "
    "The flags above are the writer's own account of what it left out."
)


def _unverified_tableau(validation_id: UUID) -> Validation:
    """A completed validation that ran nothing, and says so.

    Every check in `engines/validation` reads TMDL and PBIR. Running them against
    a `.twb` would measure nothing, and reporting a category with no checks as
    scored would be a claim - so the verdict is `unverified`, no category or
    score is given, and one rule states why (spec FR8). A read-back check is its
    own spec.
    """
    return Validation(
        validation_id=validation_id,
        status=JobStatus.COMPLETED,
        verdict=Verdict.UNVERIFIED,
        rules=[
            ValidationRuleResult(
                rule_id="TABLEAU_READBACK",
                status="NOT_APPLICABLE",
                note=TABLEAU_READBACK_NOTE,
            )
        ],
    )


def _reconvert(
    store: ArtifactStore, session: Session, project_id: UUID, name: str
) -> TargetProject | None:
    """A second conversion of the same upload, for the determinism rule.

    Returns None when the source is gone or the platform has no conversion
    path, so the rule reports NOT_APPLICABLE. An unrun check must not be
    reported as a satisfied one, and the alternative — inventing a replica —
    would make the check pass by construction.
    """
    project = load_project(session, project_id)
    source = Platform(project.source_platform)
    if source is Platform.MICROSTRATEGY:
        from engines.conversion.from_microstrategy import (  # noqa: PLC0415
            convert_microstrategy_to_powerbi,
        )

        data = store.read(_source(session, project_id).storage_key)
        with tempfile.TemporaryDirectory(prefix="dbb-replica-") as tmp:
            outcome = convert_microstrategy_to_powerbi(data, Path(tmp) / "replica", name)
            return TargetProject.from_dir(outcome.project_dir)
    if source is not Platform.TABLEAU:
        return None
    data = store.read(_source(session, project_id).storage_key)
    with tempfile.TemporaryDirectory(prefix="dbb-replica-") as tmp:
        outcome = convert_tableau_to_powerbi(data, Path(tmp) / "replica", name)
        return TargetProject.from_dir(outcome.project_dir)


@router.get("/projects/{project_id}/validation", response_model=Validation)
def get_validation(
    project_id: UUID, session: Session = Depends(get_session)
) -> Validation:
    load_project(session, project_id)
    row = _latest(session, project_id, DbJobKind.VALIDATION)
    if row is None or row.result is None:
        raise ApiException(
            ErrorCategory.NOT_FOUND,
            "This conversion has not been validated yet.",
            detail=f"no completed validation job for project {project_id}",
            status_code=404,
        )
    return Validation.model_validate(row.result)
