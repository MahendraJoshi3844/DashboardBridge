"""Conversion endpoints. Thin: run the engine, record what it reported, serve it.

Nothing here decides what converts. The engine does, and this module's job is to
carry its answer across the boundary without smoothing any of it away.
"""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from dashboardbridge_contracts import Conversion, ConversionRequest, Job
from dashboardbridge_contracts.enums import (
    ArtifactKind,
    ErrorCategory,
    JobKind,
    JobStatus,
    Platform,
)
from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.projects import load_project
from app.core.licensing import status as license_status
from app.api.proposals import accepted_proposals
from app.core.db import get_session
from app.core.directions import require_direction
from app.core.errors import ApiException
from app.core.headers import header_safe_filename
from app.db.models import Artifact as ArtifactRow
from app.db.queries import latest_job
from app.db.models import Job as JobRow
from app.db.models import JobKind as DbJobKind
from app.db.models import JobStatus as DbJobStatus
from app.services.artifact_store import ArtifactStore, get_artifact_store
from engines.conversion.run import convert_tableau_to_powerbi, zip_project

logger = logging.getLogger(__name__)
router = APIRouter(tags=["conversion"])


#: Moved to `app.db.queries` when `proposals` needed it and this module needed
#: something back from `proposals`. Four routes had been importing it from here,
#: which worked only while nothing this module imports imported it too.
_latest = latest_job


#: What the stored target is served as, by its file name.
_MEDIA_TYPES = {".zip": "application/zip", ".twb": "application/xml"}


def _produce(
    direction: tuple[Platform, Platform],
    data: bytes,
    out: Path,
    name: str,
    session: Session,
    project_id: UUID,
):
    """Run the engine for this direction. Returns the outcome, bytes and file name.

    A PBIP is a folder, so it is delivered zipped. A `.twb` is one file, and
    zipping it would hand a person an archive they have to open to find the
    thing they asked for.
    """
    if direction == (Platform.POWERBI, Platform.TABLEAU):
        from engines.conversion.to_tableau import convert_powerbi_to_tableau  # noqa: PLC0415

        outcome = convert_powerbi_to_tableau(data, out / "project", name)
        workbook = next(outcome.project_dir.glob("*.twb"))
        return outcome, workbook.read_bytes(), f"{name}.twb"

    if direction == (Platform.MICROSTRATEGY, Platform.POWERBI):
        from engines.conversion.from_microstrategy import (  # noqa: PLC0415
            convert_microstrategy_to_powerbi,
        )

        # The archive also carries the engine's migration report and the
        # data-parity DAX queries beside the project: they are how a person
        # checks what the conversion claims.
        outcome = convert_microstrategy_to_powerbi(data, out / "project", name)
        archive = zip_project(outcome.project_dir, out / "produced")
        return outcome, archive.read_bytes(), f"{name}.pbip.zip"

    if direction == (Platform.QLIK, Platform.POWERBI):
        from engines.conversion.from_qlik import convert_qlik_to_powerbi  # noqa: PLC0415

        # Carries the migration report and parity queries beside the project too.
        outcome = convert_qlik_to_powerbi(data, out / "project", name)
        archive = zip_project(outcome.project_dir, out / "produced")
        return outcome, archive.read_bytes(), f"{name}.pbip.zip"

    outcome = convert_tableau_to_powerbi(
        data,
        out / "project",
        name,
        # Only what a person accepted. A pending proposal is a draft nobody has
        # read, and a rejected one is a draft someone turned down; using either
        # here would be the auto-apply path ADR-007 rejects, arrived at from the
        # conversion endpoint.
        accepted=accepted_proposals(session, project_id),
    )
    archive = zip_project(outcome.project_dir, out / "produced")
    return outcome, archive.read_bytes(), f"{name}.pbip.zip"


def _source(session: Session, project_id: UUID) -> ArtifactRow:
    row = session.scalars(
        select(ArtifactRow)
        .where(
            ArtifactRow.project_id == project_id,
            ArtifactRow.kind == ArtifactKind.SOURCE.value,
        )
        .order_by(ArtifactRow.created_at.desc())
    ).first()
    if row is None:
        raise ApiException(
            ErrorCategory.UPLOAD_ERROR,
            "Upload a workbook before converting.",
            detail=f"no source artifact for project {project_id}",
        )
    return row


@router.post(
    "/projects/{project_id}/conversion",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_conversion(
    project_id: UUID,
    request: ConversionRequest,
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> Job:
    """Convert deterministically. No AI is reachable from this path today.

    Runs inline for the same reason analysis does: a real workbook converts in
    well under a second, and a queue would add a failure mode for no benefit.
    The response is a Job so the contract survives that changing.
    """
    # The licence gate, before anything is read or written (`P7.1`).
    #
    # Converting is what a licence buys, so this is where an expired one stops.
    # Reading is untouched on purpose: past projects, reports and flags stay
    # available after expiry, because no *new* work is the commercial lever and
    # losing old work would just be a threat.
    #
    # 402 Payment Required is the one status code that says this exactly - not
    # 401 (nobody is being asked to identify themselves) and not 403 (the
    # request is permitted, the subscription has lapsed).
    licence = license_status()
    if not licence.may_convert:
        raise ApiException(
            ErrorCategory.VALIDATION_ERROR,
            licence.message or "This deployment is not licensed to convert.",
            detail="licence check failed at the conversion endpoint",
            status_code=402,
        )

    project = load_project(session, project_id)
    direction = (Platform(project.source_platform), Platform(project.target_platform))
    # Installed and licensed now - not only when the project began.
    require_direction(*direction)
    if _latest(session, project_id, DbJobKind.ANALYSIS) is None:
        raise ApiException(
            ErrorCategory.CONVERSION_ERROR,
            "Analyse the workbook before converting it, so you can see what "
            "will and will not come across.",
            detail=f"no analysis job for project {project_id}",
        )
    if request.ai_enabled:
        # The contract already rejects ai_enabled without a provider. Reaching
        # here means a provider was named, and none is wired yet: saying so is
        # better than silently converting without the assistance that was asked
        # for and reporting success.
        raise ApiException(
            ErrorCategory.AI_ERROR,
            "AI assistance is not available yet. You can convert without it — "
            "anything needing a model will be listed for you instead.",
            detail=f"ai_enabled with provider={request.provider.value}, no router",
        )

    artifact = _source(session, project_id)
    job = JobRow(job_id=uuid4(), project_id=project_id, kind=DbJobKind.CONVERSION)
    session.add(job)
    job.transition_to(DbJobStatus.RUNNING)
    session.flush()

    try:
        data = store.read(artifact.storage_key)
        with tempfile.TemporaryDirectory(prefix="dbb-out-") as out:
            outcome, payload, filename = _produce(
                direction,
                data,
                Path(out),
                project.name or "project",
                session,
                project_id,
            )
            # Same staged write the upload path uses, so nothing enters the
            # store until it is complete.
            storage_key = store.new_key(suffix=Path(filename).suffix)
            with store.stage() as staged:
                staged.write(payload)
                staged.commit(storage_key)
    except Exception as exc:
        job.transition_to(DbJobStatus.FAILED)
        job.error_category = ErrorCategory.CONVERSION_ERROR.value
        session.commit()
        logger.exception("conversion failed", extra={"project_id": str(project_id)})
        raise ApiException(
            ErrorCategory.CONVERSION_ERROR,
            "The conversion did not finish. Nothing was produced, and the "
            "workbook you uploaded is unchanged.",
            detail=f"{type(exc).__name__}: {exc}",
            project_id=project_id,
        ) from exc

    produced = ArtifactRow(
        artifact_id=uuid4(),
        project_id=project_id,
        kind=ArtifactKind.TARGET.value,
        filename=filename,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        storage_key=storage_key,
        detected_platform=direction[1].value,
    )
    session.add(produced)

    job.result = Conversion(
        conversion_id=job.job_id,
        status=JobStatus.COMPLETED,
        compatibility=outcome.compatibility,
        model=outcome.model,
        artifact_id=produced.artifact_id,
        flags=outcome.flags,
    ).model_dump(mode="json")
    # The engine's own recording, kept so the event stream can replay this run
    # rather than re-enact it (05-api-spec, "Real stages from the job's event
    # stream").
    job.timeline = outcome.timeline.to_dict()
    job.transition_to(DbJobStatus.COMPLETED)
    session.commit()

    logger.info(
        "conversion completed",
        extra={
            "project_id": str(project_id),
            "job_id": str(job.job_id),
            "operation": "conversion",
        },
    )
    return Job(job_id=job.job_id, kind=JobKind.CONVERSION, status=JobStatus.COMPLETED)


@router.get("/projects/{project_id}/conversion", response_model=Conversion)
def get_conversion(
    project_id: UUID, session: Session = Depends(get_session)
) -> Conversion:
    load_project(session, project_id)
    row = _latest(session, project_id, DbJobKind.CONVERSION)
    if row is None or row.result is None:
        raise ApiException(
            ErrorCategory.NOT_FOUND,
            "This project has not been converted yet.",
            detail=f"no completed conversion job for project {project_id}",
            status_code=404,
        )
    return Conversion.model_validate(row.result)


@router.get("/projects/{project_id}/artifact")
def download_artifact(
    project_id: UUID,
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> Response:
    """What the conversion produced: a zipped PBIP, or a `.twb`.

    Refuses while the conversion is unfinished: a partial artifact must never be
    served as if it were done.
    """
    load_project(session, project_id)
    produced = session.scalars(
        select(ArtifactRow)
        .where(
            ArtifactRow.project_id == project_id,
            ArtifactRow.kind == ArtifactKind.TARGET.value,
        )
        .order_by(ArtifactRow.created_at.desc())
    ).first()
    if produced is None:
        raise ApiException(
            ErrorCategory.CONVERSION_ERROR,
            "There is nothing to download yet. Convert the workbook first.",
            detail=f"no target artifact for project {project_id}",
            status_code=409,
        )
    return Response(
        content=store.read(produced.storage_key),
        media_type=_MEDIA_TYPES.get(
            Path(produced.filename).suffix.lower(), "application/octet-stream"
        ),
        headers={
            "content-disposition": f'attachment; filename="{header_safe_filename(produced.filename)}"'
        },
    )
