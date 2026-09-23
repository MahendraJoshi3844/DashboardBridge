"""Analysis endpoints. Thin: load the artifact, run the adapter, store the result.

All the intelligence is in `engines/adapters`, which never imports FastAPI so it
stays callable from a CLI, the desktop shell, or a test with no server running.
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from dashboardbridge_contracts import Analysis, Job
from dashboardbridge_contracts.enums import ErrorCategory, JobKind, JobStatus, Platform
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.projects import load_project
from app.core.db import get_session
from app.core.errors import ApiException
from app.db.models import Artifact as ArtifactRow
from app.db.models import Job as JobRow
from app.db.models import JobKind as DbJobKind
from app.db.models import JobStatus as DbJobStatus
from app.services import analysis as analysis_service
from app.services.artifact_store import ArtifactStore, StorageKeyError, get_artifact_store
from engines.adapters.tableau import UnreadableArtifact

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analysis"])


def _fail(session: Session, job: JobRow, category: ErrorCategory) -> None:
    job.transition_to(DbJobStatus.FAILED)
    job.error_category = category.value
    session.commit()

# One adapter per readable platform. Adding Qlik means adding a row here, not
# touching anything else in this module.
_ADAPTERS = {}


def _adapter_for(platform: Platform):
    if not _ADAPTERS:
        from engines.adapters.powerbi import PowerBIAdapter  # noqa: PLC0415
        from engines.adapters.tableau import TableauAdapter  # noqa: PLC0415

        _ADAPTERS[Platform.TABLEAU] = TableauAdapter
        # Reading Power BI is not converting from it: `P6a` reads a PBIP into
        # the canonical model, and `P6b` - writing Tableau - does not exist, so
        # the conversion endpoint still refuses this platform.
        _ADAPTERS[Platform.POWERBI] = PowerBIAdapter
    factory = _ADAPTERS.get(platform)
    if factory is None:
        raise ApiException(
            ErrorCategory.UNSUPPORTED_ARTIFACT,
            f"Reading {platform.value} files is not supported yet.",
            detail=f"no reading adapter registered for {platform.value}",
        )
    return factory()


def _source_artifact(session: Session, project_id: UUID) -> ArtifactRow:
    row = session.scalars(
        select(ArtifactRow)
        .where(ArtifactRow.project_id == project_id)
        .order_by(ArtifactRow.created_at.desc())
    ).first()
    if row is None:
        raise ApiException(
            ErrorCategory.UPLOAD_ERROR,
            "Upload a workbook before running the analysis.",
            detail=f"no source artifact for project {project_id}",
        )
    return row


@router.post(
    "/projects/{project_id}/analysis",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_analysis(
    project_id: UUID,
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> Job:
    """Parse the uploaded artifact into the canonical model.

    Runs inline: analysis of a real 1.1 MB workbook takes about 25 ms, and a
    queue would add latency and a failure mode for no benefit at this size. The
    response is still a Job so the contract does not change when a larger
    artifact makes a worker worthwhile.
    """
    project = load_project(session, project_id)
    artifact = _source_artifact(session, project_id)

    job = JobRow(job_id=uuid4(), project_id=project_id, kind=DbJobKind.ANALYSIS)
    session.add(job)
    # transition_to stamps started_at/finished_at, so the audit trail cannot
    # drift from the status it describes.
    job.transition_to(DbJobStatus.RUNNING)
    session.flush()

    try:
        data = store.read(artifact.storage_key)
    except (StorageKeyError, OSError) as exc:
        # Our storage failed. Do not dress this up as a bad workbook.
        _fail(session, job, ErrorCategory.SYSTEM_ERROR)
        logger.exception("artifact unreadable", extra={"project_id": str(project_id)})
        raise ApiException(
            ErrorCategory.SYSTEM_ERROR,
            "We could not retrieve the uploaded file. The analysis did not run.",
            detail=f"{type(exc).__name__}: {exc}",
            project_id=project_id,
        ) from exc

    adapter = _adapter_for(Platform(project.source_platform))
    try:
        model = adapter.normalize(adapter.parse(data))
    except UnreadableArtifact as exc:
        # Distinct from a parse crash: the file was well-formed but empty of
        # anything we recognise. Say that, rather than reporting zeros.
        _fail(session, job, ErrorCategory.UNSUPPORTED_ARTIFACT)
        raise ApiException(
            ErrorCategory.UNSUPPORTED_ARTIFACT,
            "That file is shaped like a Tableau workbook but contains no data "
            "sources or worksheets. Re-save it from Tableau Desktop and try "
            "again.",
            detail=f"UnreadableArtifact: {exc}",
            project_id=project_id,
        ) from exc
    except Exception as exc:
        # Only the parse itself is attributed to the artifact, and only because
        # a malformed workbook is by far the likeliest cause of a failure here.
        _fail(session, job, ErrorCategory.PARSER_ERROR)
        logger.exception("analysis failed", extra={"project_id": str(project_id)})
        raise ApiException(
            ErrorCategory.PARSER_ERROR,
            "We could not read that workbook. It may be corrupted, or it may "
            "use a feature this version does not understand yet.",
            detail=f"{type(exc).__name__}: {exc}",
            project_id=project_id,
        ) from exc

    inventory = analysis_service.inventory_of(model)
    job.result = Analysis(
        analysis_id=job.job_id,
        status=JobStatus.COMPLETED,
        model=model,
        inventory=inventory,
        complexity=analysis_service.complexity_of(inventory),
        compatibility=analysis_service.compatibility_of(inventory, model.flags),
        flags=model.flags,
    ).model_dump(mode="json")
    job.transition_to(DbJobStatus.COMPLETED)
    session.commit()

    logger.info(
        "analysis completed",
        extra={
            "project_id": str(project_id),
            "job_id": str(job.job_id),
            "operation": "analysis",
        },
    )
    return Job(job_id=job.job_id, kind=JobKind.ANALYSIS, status=JobStatus.COMPLETED)


@router.get("/projects/{project_id}/analysis", response_model=Analysis)
def get_analysis(
    project_id: UUID, session: Session = Depends(get_session)
) -> Analysis:
    load_project(session, project_id)
    row = session.scalars(
        select(JobRow)
        .where(JobRow.project_id == project_id, JobRow.kind == DbJobKind.ANALYSIS)
        .order_by(JobRow.created_at.desc())
    ).first()
    if row is None or row.result is None:
        raise ApiException(
            ErrorCategory.NOT_FOUND,
            "This project has not been analysed yet.",
            detail=f"no completed analysis job for project {project_id}",
            status_code=404,
        )
    return Analysis.model_validate(row.result)
