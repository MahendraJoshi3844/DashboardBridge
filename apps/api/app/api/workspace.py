"""The workspace: the produced Power BI project, read and edited after conversion.

Versions are the project's target artifacts in the order they were stored. v0
is what the converter wrote; every save adds one, and the download endpoint
already serves the newest, so a person downloads what they last saved.

Only Power BI output has a workspace today. A `.twb` is one XML file with no
DAX or Power Query in it, and editing it here is a separate piece of work.
"""

from __future__ import annotations

import hashlib
import logging
from uuid import UUID, uuid4

from dashboardbridge_contracts import (
    Conversion,
    PublishRequest,
    ReportExplorer,
    ReportPage,
    ReportVisual,
    WorkspaceCommit,
    WorkspaceHeld,
    WorkspaceModel,
    WorkspaceVersion,
)
from dashboardbridge_contracts.enums import (
    ArtifactKind,
    ConversionStatus,
    ErrorCategory,
    Platform,
    Stage,
)
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.projects import load_project
from app.core.db import get_session
from app.core.errors import ApiException
from app.core.headers import header_safe_filename
from app.db.models import Artifact as ArtifactRow
from app.db.models import JobKind as DbJobKind
from app.db.queries import latest_job
from app.services import workspace as ws
from app.services.artifact_store import ArtifactStore, get_artifact_store

logger = logging.getLogger(__name__)
router = APIRouter(tags=["workspace"])

#: Files a person may open as text. Everything a PBIP holds that is not binary.
_TEXT = (".tmdl", ".json", ".pbir", ".pbism", ".pbip", ".txt", ".md", ".platform")


def _versions(session: Session, project_id: UUID) -> list[ArtifactRow]:
    rows = session.scalars(
        select(ArtifactRow)
        .where(
            ArtifactRow.project_id == project_id,
            ArtifactRow.kind == ArtifactKind.TARGET.value,
        )
        .order_by(ArtifactRow.created_at.asc())
    ).all()
    if not rows:
        raise ApiException(
            ErrorCategory.CONVERSION_ERROR,
            "There is nothing to open yet. Convert the workbook first.",
            detail=f"no target artifact for project {project_id}",
            status_code=409,
        )
    return list(rows)


def _power_bi_only(session: Session, project_id: UUID):
    project = load_project(session, project_id)
    if Platform(project.target_platform) is not Platform.POWERBI:
        raise ApiException(
            ErrorCategory.UNSUPPORTED_ARTIFACT,
            "The workspace opens Power BI projects. This migration produces a "
            "Tableau workbook, which you can download from the job.",
            detail=f"workspace requested for target {project.target_platform}",
            status_code=409,
        )
    return project


def _held(session: Session, project_id: UUID) -> list[WorkspaceHeld]:
    """Calculations the converter refused, with the source a person rewrites."""
    job = latest_job(session, project_id, DbJobKind.CONVERSION)
    if job is None or job.result is None:
        return []
    conversion = Conversion.model_validate(job.result)
    sources = {}
    if conversion.model is not None:
        for table in conversion.model.all_tables():
            for column in table.columns:
                if column.expression is not None:
                    sources[f"{table.name}.{column.display_name}"] = (
                        table.name,
                        column.display_name,
                        column.expression.source_text,
                    )
    held: list[WorkspaceHeld] = []
    for flag in conversion.flags:
        if flag.stage is not Stage.TRANSLATE or flag.status not in {
            ConversionStatus.AI_REQUIRED,
            ConversionStatus.UNSUPPORTED,
        }:
            continue
        table, name, source = sources.get(flag.item, ("", flag.item, ""))
        if not table and "." in flag.item:
            table, name = flag.item.split(".", 1)
        held.append(
            WorkspaceHeld(item=flag.item, table=table, name=name, source=source, reason=flag.reason)
        )
    return sorted(held, key=lambda entry: entry.item)


def _model(
    session: Session, project, rows: list[ArtifactRow], store: ArtifactStore
) -> WorkspaceModel:
    files = ws.unzip(store.read(rows[-1].storage_key))
    tables = ws.read_tables(files)
    # Once a person has written a held calculation as a measure, it is no
    # longer waiting for them. The conversion report still records the refusal.
    written = {
        (table.name, measure.name) for table in tables for measure in table.measures
    }
    return WorkspaceModel(
        project_id=project.project_id,
        name=project.name,
        version=len(rows) - 1,
        versions=[
            WorkspaceVersion(
                version=index,
                artifact_id=row.artifact_id,
                created_at=row.created_at,
                note=row.note or ("Converted" if index == 0 else ""),
            )
            for index, row in enumerate(rows)
        ],
        tables=tables,
        files=ws.file_list(files),
        held=[
            held
            for held in _held(session, project.project_id)
            if (held.table, held.name) not in written
        ],
    )


@router.get("/projects/{project_id}/workspace", response_model=WorkspaceModel)
def get_workspace(
    project_id: UUID,
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> WorkspaceModel:
    project = _power_bi_only(session, project_id)
    return _model(session, project, _versions(session, project_id), store)


@router.get("/projects/{project_id}/workspace/file", response_class=PlainTextResponse)
def get_workspace_file(
    project_id: UUID,
    path: str = Query(min_length=1, max_length=512),
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> PlainTextResponse:
    """One file of the newest version, as text. The path is looked up, never joined."""
    _power_bi_only(session, project_id)
    files = ws.unzip(store.read(_versions(session, project_id)[-1].storage_key))
    if path not in files or not path.endswith(_TEXT):
        raise ApiException(
            ErrorCategory.NOT_FOUND,
            "That file is not part of this project.",
            detail=f"no text member {path!r}",
            status_code=404,
        )
    return PlainTextResponse(files[path].decode("utf-8", errors="replace"))


@router.post(
    "/projects/{project_id}/workspace/versions",
    response_model=WorkspaceModel,
    status_code=status.HTTP_201_CREATED,
)
def save_version(
    project_id: UUID,
    commit: WorkspaceCommit,
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> WorkspaceModel:
    """Apply edits to the newest version and store the result as the next one."""
    project = _power_bi_only(session, project_id)
    rows = _versions(session, project_id)
    if commit.base_version != len(rows) - 1:
        raise ApiException(
            ErrorCategory.VALIDATION_ERROR,
            f"These changes were made to v{commit.base_version}, and v{len(rows) - 1} "
            "has been saved since. Reload the workspace and make them again.",
            detail=f"stale base_version {commit.base_version}",
            status_code=409,
        )
    try:
        files = ws.apply_edits(ws.unzip(store.read(rows[-1].storage_key)), commit.edits)
    except ws.EditRefused as exc:
        raise ApiException(
            ErrorCategory.VALIDATION_ERROR,
            str(exc),
            detail=f"EditRefused: {exc}",
            status_code=400,
        ) from exc

    payload = ws.rezip(files)
    key = store.new_key(suffix=".zip")
    with store.stage() as staged:
        staged.write(payload)
        staged.commit(key)
    count = len(commit.edits)
    session.add(
        ArtifactRow(
            artifact_id=uuid4(),
            project_id=project_id,
            kind=ArtifactKind.TARGET.value,
            filename=rows[-1].filename,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            storage_key=key,
            detected_platform=Platform.POWERBI.value,
            note=(commit.note.strip() or f"{count} edit{'s' if count != 1 else ''}")[:500],
        )
    )
    session.commit()
    logger.info(
        "workspace version saved",
        extra={"project_id": str(project_id), "operation": "workspace.save"},
    )
    return _model(session, project, _versions(session, project_id), store)


def _visual_notes(session: Session, project_id: UUID) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Worksheet name to its Tableau mark, and to the reasons flags give about it.

    A visual's flags are named after its worksheet - `Sheet` or `Sheet: Field` -
    which is also the name of the page it was written on.
    """
    job = latest_job(session, project_id, DbJobKind.CONVERSION)
    if job is None or job.result is None:
        return {}, {}
    conversion = Conversion.model_validate(job.result)
    marks = {
        visual.name: visual.visual_type
        for visual in (conversion.model.visuals if conversion.model else [])
    }
    notes: dict[str, list[str]] = {}
    for flag in conversion.flags:
        if flag.status is ConversionStatus.CONVERTED:
            continue
        for sheet in marks:
            if flag.item == sheet or flag.item.startswith(f"{sheet}: "):
                notes.setdefault(sheet, []).append(flag.reason)
    return marks, notes


@router.get("/projects/{project_id}/workspace/report", response_model=ReportExplorer)
def get_report_explorer(
    project_id: UUID,
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> ReportExplorer:
    """Every page and visual of the newest version, with its Tableau source."""
    _power_bi_only(session, project_id)
    rows = _versions(session, project_id)
    marks, notes = _visual_notes(session, project_id)
    pages = ws.read_report(ws.unzip(store.read(rows[-1].storage_key)))
    return ReportExplorer(
        version=len(rows) - 1,
        pages=[
            ReportPage(
                id=page.id,
                name=page.name,
                width=page.width,
                height=page.height,
                notes=[] if page.visuals else notes.get(page.name, []),
                visuals=[
                    ReportVisual(
                        id=visual.id,
                        page_id=page.id,
                        visual_type=visual.visual_type,
                        source_name=page.name if page.name in marks else "",
                        source_mark=marks.get(page.name, ""),
                        fields=list(visual.fields),
                        status="partial" if notes.get(page.name) else "converted",
                        notes=notes.get(page.name, []),
                    )
                    for visual in page.visuals
                ],
            )
            for page in pages
        ],
    )


@router.post("/projects/{project_id}/workspace/publish")
def publish_selection(
    project_id: UUID,
    body: PublishRequest,
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> Response:
    """The newest version as a .pbip archive carrying only the chosen visuals.

    An id that names no visual is refused rather than skipped: a person who
    ticked something expects it in the file, and a silently shorter report is
    the kind of loss this product exists to prevent.
    """
    _power_bi_only(session, project_id)
    rows = _versions(session, project_id)
    files = ws.unzip(store.read(rows[-1].storage_key))
    known = {visual.id for page in ws.read_report(files) for visual in page.visuals}
    unknown = sorted(set(body.visual_ids) - known)
    if unknown:
        raise ApiException(
            ErrorCategory.VALIDATION_ERROR,
            "Some of the chosen visuals are not in this version of the report. "
            "Reload the Report Explorer and choose again.",
            detail=f"unknown visual ids {unknown}",
            status_code=400,
        )
    payload = ws.rezip(ws.filter_report(files, set(body.visual_ids)))
    logger.info(
        "workspace published",
        extra={"project_id": str(project_id), "operation": "workspace.publish"},
    )
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "content-disposition": f'attachment; filename="{header_safe_filename(rows[-1].filename)}"'
        },
    )
