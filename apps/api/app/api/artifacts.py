"""Artifact upload — the boundary where hostile bytes enter the system.

Everything in `09-security-spec.md` that applies at upload time applies *here*,
in this order, and the order is the control:

```
1  project lookup          an artifact with nowhere to belong is not stored
2  filename sanitisation   display text; never a path, never a key
3  extension allow-list    cheap, and refuses `.pbix` by name (ADR-005)
4  declared size           refused before a byte of the body is read
5  streamed size + sha256  bounded per chunk, into staging, never the store
6  archive limits          the zip's own directory; nothing is extracted
7  detection               extension + magic bytes; `None` means refuse
8  platform agreement      a contradiction is a 400, never a coercion
9  commit                  only now does the artifact store contain anything
```

Step 4 is enforced by `SizeLimitedRoute` rather than inside the handler,
because by the time a handler runs, the framework has already parsed the body —
a size check there is a measurement, not a limit. The route wraps the ASGI
receive channel so the cap applies to the bytes as they arrive.

Step 7 is deliberately shallow. Detection must be *cheap and safe* on untrusted
input, and parsing is neither; the adapter's `parse()` is expensive, sandboxed,
and somebody else's module (02-architecture § Extensibility).
"""

from __future__ import annotations

from typing import Any, Callable, Iterator
from uuid import UUID

from dashboardbridge_contracts import Artifact as ArtifactContract
from dashboardbridge_contracts.enums import ArtifactKind, Platform
from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.api.projects import load_project
from app.core.config import settings
from app.services import malware_scan
from app.core.db import get_session
from app.db.models import Artifact as ArtifactRow
from app.db.models import ArtifactKind as ArtifactKindRow
from app.services import upload_validation as uv
from app.services.artifact_store import ArtifactStore, get_artifact_store


class SizeLimitedRoute(APIRoute):
    """A route whose request body is bounded before the framework buffers it.

    FastAPI parses a multipart body *before* the handler is called, so a limit
    checked in the handler is a limit checked after the resource has already
    been consumed. Wrapping `receive` moves the check to where the bytes
    actually arrive: the declared length is refused outright, and the stream is
    cut off the moment it exceeds the cap even if the declaration lied.
    """

    def get_route_handler(self) -> Callable[[Request], Any]:
        inner = super().get_route_handler()

        async def limited(request: Request) -> Response:
            cap = uv.max_upload_bytes()
            uv.check_declared_size(request.headers.get("content-length"), cap)
            request._receive = _bounded_receive(  # noqa: SLF001 - the ASGI seam
                request.receive, cap + uv.MULTIPART_OVERHEAD_BYTES
            )
            return await inner(request)

        return limited


def _bounded_receive(receive: Callable[[], Any], cap: int) -> Callable[[], Any]:
    seen = 0

    async def wrapped() -> Any:
        nonlocal seen
        message = await receive()
        if message.get("type") == "http.request":
            seen += len(message.get("body", b""))
            if seen > cap:
                raise uv.oversize_body(seen, cap)
        return message

    return wrapped


router = APIRouter(tags=["artifacts"], route_class=SizeLimitedRoute)


def _chunks(upload: UploadFile) -> Iterator[bytes]:
    upload.file.seek(0)
    return iter(lambda: upload.file.read(uv.READ_CHUNK_BYTES), b"")


@router.post(
    "/projects/{project_id}/artifacts",
    response_model=ArtifactContract,
    status_code=201,
)
def upload_artifact(
    project_id: UUID,
    file: UploadFile = File(
        ...,
        description=(
            "A Tableau .twb/.twbx workbook, a zipped Power BI project, or a "
            "MicroStrategy .mstr package / zipped metadata export."
        ),
    ),
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> ArtifactContract:
    project = load_project(session, project_id)

    display_name = uv.sanitize_filename(file.filename)
    extension = uv.validated_extension(display_name)

    with store.stage() as staged:
        # Into staging, never the store: a file that fails a check below was
        # never an artifact, so there is nothing to roll back.
        result = uv.stream_with_limits(
            _chunks(file), sink=staged.write, limit_bytes=uv.max_upload_bytes()
        )

        report = (
            # Every archive we accept, not just `.twbx`. A zipped Power BI
            # project needs the same bomb limits and the same member list -
            # and detection cannot tell a project from a holiday album
            # without one.
            uv.inspect_zip_archive(staged.path)
            if extension in uv.ARCHIVE_EXTENSIONS
            else None
        )

        detected = uv.detect_platform(
            extension, head=result.head, zip_report=report
        )
        if detected is None:
            raise uv.refuse_undetectable(display_name, Platform(project.source_platform))
        if detected is not project.source_platform:
            raise uv.refuse_platform_mismatch(detected, project.source_platform)

        # Last, and still in staging (`P7.5`). A scanner that runs after the
        # commit is a scanner that reports on a file the system already holds.
        verdict = malware_scan.scan(staged.path)
        refusal = malware_scan.refuse_reason(
            verdict, require_scan=settings().require_malware_scan
        )
        if refusal is not None:
            raise uv.refuse_malware(refusal, verdict.scanner)

        storage_key = store.new_key(suffix=extension)
        staged.commit(storage_key)

    row = ArtifactRow(
        project_id=project.project_id,
        kind=ArtifactKindRow.SOURCE,
        filename=display_name,
        size_bytes=result.size_bytes,
        sha256=result.sha256,
        storage_key=storage_key,
        detected_platform=detected,
    )
    try:
        session.add(row)
        session.flush()
    except Exception:
        # A stored object with no row is unreachable and unaccountable. If the
        # row will not persist, the bytes do not stay either.
        store.delete(storage_key)
        raise

    return ArtifactContract(
        artifact_id=row.artifact_id,
        kind=ArtifactKind.SOURCE,
        filename=row.filename,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        detected_platform=detected,
    )
