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

from dashboardbridge_contracts import Conversion, ConversionRequest, Job, ProjectFile, ProjectFiles
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
from app.api.accounts import current_user
from app.core.directions import require_direction
from app.db.models import User
from app.core.errors import ApiException
from app.core.headers import header_safe_filename
from app.db.models import Artifact as ArtifactRow
from app.db.queries import latest_job
from app.db.models import Job as JobRow
from app.db.models import JobKind as DbJobKind
from app.db.models import JobStatus as DbJobStatus
from app.services.artifact_store import ArtifactStore, get_artifact_store
from engines.conversion.outcome import zip_project

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
    source_name: str | None = None,
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

    from engines.conversion.run import convert_tableau_to_powerbi  # noqa: PLC0415 - Tableau engine, optional

    outcome = convert_tableau_to_powerbi(
        data,
        out / "project",
        name,
        # Only what a person accepted. A pending proposal is a draft nobody has
        # read, and a rejected one is a draft someone turned down; using either
        # here would be the auto-apply path ADR-007 rejects, arrived at from the
        # conversion endpoint.
        accepted=accepted_proposals(session, project_id),
        source_name=source_name,
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
    user: User = Depends(current_user),
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
    require_direction(*direction, user)
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
                source_name=artifact.filename,
            )
            # Same staged write the upload path uses, so nothing enters the
            # store until it is complete.
            storage_key = store.new_key(suffix=Path(filename).suffix)
            with store.stage() as staged:
                staged.write(payload)
                staged.commit(storage_key)
            extraction = None
            if outcome.extraction_dir is not None and outcome.extraction_dir.is_dir():
                extracted = zip_project(outcome.extraction_dir, Path(out) / "extracted").read_bytes()
                extraction_key = store.new_key(suffix=".zip")
                with store.stage() as staged:
                    staged.write(extracted)
                    staged.commit(extraction_key)
                extraction = (extracted, extraction_key)
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
    if extraction is not None:
        extracted, extraction_key = extraction
        session.add(
            ArtifactRow(
                artifact_id=uuid4(),
                project_id=project_id,
                kind=ArtifactKind.EXTRACTION.value,
                filename=f"{project.name or 'project'}.extracted.zip",
                size_bytes=len(extracted),
                sha256=hashlib.sha256(extracted).hexdigest(),
                storage_key=extraction_key,
                detected_platform=direction[0].value,
            )
        )

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


def _latest_artifact(session: Session, project_id: UUID, kind: ArtifactKind) -> ArtifactRow | None:
    return session.scalars(
        select(ArtifactRow)
        .where(ArtifactRow.project_id == project_id, ArtifactRow.kind == kind.value)
        .order_by(ArtifactRow.created_at.desc())
    ).first()


def _no_extraction(project) -> ApiException:
    if project.source_platform != Platform.TABLEAU.value or project.target_platform != Platform.POWERBI.value:
        message = (
            "Extracted files are produced for Tableau to Power BI migrations. This project's "
            "engine does not produce them; its converted project is still available to download."
        )
    else:
        message = "There are no extracted files yet. Convert the workbook first."
    return ApiException(
        ErrorCategory.NOT_FOUND,
        message,
        detail=f"no extraction artifact for project {project.project_id}",
        status_code=404,
    )


def _validation_of(archive: bytes) -> tuple[str | None, bytes | None]:
    """The validation status and report inside an extraction archive."""
    import io  # noqa: PLC0415
    import json  # noqa: PLC0415
    import zipfile  # noqa: PLC0415

    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        names = set(zipped.namelist())
        status = None
        if "validation.json" in names:
            status = json.loads(zipped.read("validation.json")).get("status")
        report = zipped.read("VALIDATION_REPORT.md") if "VALIDATION_REPORT.md" in names else None
    return status, report


@router.get("/projects/{project_id}/extraction")
def download_extraction(
    project_id: UUID,
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> Response:
    """The extracted files of the latest conversion: metadata, what each item
    became, the validation report and the project, as one archive."""
    project = load_project(session, project_id)
    row = _latest_artifact(session, project_id, ArtifactKind.EXTRACTION)
    if row is None:
        raise _no_extraction(project)
    return Response(
        content=store.read(row.storage_key),
        media_type="application/zip",
        headers={"content-disposition": f'attachment; filename="{header_safe_filename(row.filename)}"'},
    )


@router.get("/projects/{project_id}/validation-report")
def download_validation_report(
    project_id: UUID,
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> Response:
    """The validation report on its own, readable without unzipping anything."""
    project = load_project(session, project_id)
    row = _latest_artifact(session, project_id, ArtifactKind.EXTRACTION)
    report = _validation_of(store.read(row.storage_key))[1] if row is not None else None
    if report is None:
        raise _no_extraction(project)
    name = Path(row.filename).name.removesuffix(".extracted.zip")
    return Response(
        content=report,
        media_type="text/markdown; charset=utf-8",
        headers={"content-disposition": f'attachment; filename="{header_safe_filename(name + "-validation-report.md")}"'},
    )


@router.get("/projects/{project_id}/files", response_model=ProjectFiles)
def list_files(
    project_id: UUID,
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> ProjectFiles:
    """What the job's Files tab offers: only files that exist, and why not when not."""
    project = load_project(session, project_id)
    files: list[ProjectFile] = []
    validation = None
    extraction = _latest_artifact(session, project_id, ArtifactKind.EXTRACTION)
    if extraction is not None:
        files.append(ProjectFile(kind="extraction", label="Extracted Files (.zip)", filename=extraction.filename,
                                 size_bytes=extraction.size_bytes, href=f"/projects/{project_id}/extraction"))
        validation, report = _validation_of(store.read(extraction.storage_key))
        if report is not None:
            stem = Path(extraction.filename).name.removesuffix(".extracted.zip")
            files.append(ProjectFile(kind="validation_report", label="Validation report (.md)",
                                     filename=f"{stem}-validation-report.md", size_bytes=len(report),
                                     href=f"/projects/{project_id}/validation-report"))
    target = _latest_artifact(session, project_id, ArtifactKind.TARGET)
    if target is not None:
        label = "Tableau workbook (.twb)" if target.filename.endswith(".twb") else "Power BI project (.pbip.zip)"
        files.append(ProjectFile(kind="target", label=label, filename=target.filename,
                                 size_bytes=target.size_bytes, href=f"/projects/{project_id}/artifact"))
    note = None
    if extraction is None:
        note = _no_extraction(project).message if target is not None else \
            "Files appear here once the project has been converted."
    return ProjectFiles(files=files, extraction_available=extraction is not None, note=note,
                        validation=validation)
