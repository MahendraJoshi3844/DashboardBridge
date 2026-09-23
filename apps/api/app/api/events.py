"""The conversion event stream. Recorded work, replayed — never re-enacted.

The engine records one event per item it handled, in the order it handled them
(`t2pbi.events`). This endpoint carries that recording across the boundary and
adds nothing to it. In particular it does not smooth the progression: a
percentage here is `completed / total` of real items, and if there is no real
count there is no percentage.

Ids are positions in the recording, which is what makes resumption stateless.
`Last-Event-ID` — which a browser's `EventSource` resends by itself after a
dropped connection — becomes the predicate `id > n` over the same fixed list,
so a client that reconnects sees exactly what it missed and nothing twice.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from uuid import UUID

from dashboardbridge_contracts.enums import ErrorCategory
from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.queries import latest_job as _latest
from app.api.projects import load_project
from app.core.db import get_session
from app.core.errors import ApiException
from app.db.models import JobKind as DbJobKind

router = APIRouter(tags=["events"])

ITEM = "conversion.item"
PROGRESS = "conversion.progress"
COMPLETED = "conversion.completed"


def _frames(timeline: dict) -> list[tuple[int, str, dict]]:
    """The whole stream as `(id, event, data)`, fixed and re-derivable.

    Built in full on every request rather than from a cursor, because the ids a
    resuming client sends must mean the same thing on the second request as on
    the first. Deriving them from position in the recording guarantees that;
    handing out a counter would not survive a restart.
    """
    events = timeline.get("events", [])
    total = len(events)
    frames: list[tuple[int, str, dict]] = []
    for completed, event in enumerate(events, start=1):
        frames.append(
            (
                len(frames) + 1,
                ITEM,
                {
                    "name": event.get("name", ""),
                    "outcome": event.get("outcome", ""),
                    "stage": event.get("stage", ""),
                    "kind": event.get("kind", ""),
                    "detail": event.get("detail", ""),
                    "ref": event.get("ref", ""),
                    # Carried so a drill-down costs no round-trip; empty for
                    # anything that is not a calculation, and empty on `result`
                    # for anything that was held.
                    "source": event.get("source", ""),
                    "result": event.get("result", ""),
                    "elapsed_ms": event.get("elapsed_ms", 0),
                },
            )
        )
        frames.append((len(frames) + 1, PROGRESS, {"completed": completed, "total": total}))
    frames.append(
        (
            len(frames) + 1,
            COMPLETED,
            {"total": total, "duration_ms": timeline.get("durationMs", 0)},
        )
    )
    return frames


def _sse(frames: list[tuple[int, str, dict]]) -> Iterator[str]:
    for event_id, name, data in frames:
        yield (
            f"id: {event_id}\n"
            f"event: {name}\n"
            f"data: {json.dumps(data, ensure_ascii=True)}\n\n"
        )


@router.get("/projects/{project_id}/events")
def stream_events(
    project_id: UUID,
    session: Session = Depends(get_session),
    last_event_id: str | None = Header(default=None, alias="last-event-id"),
) -> StreamingResponse:
    """Replay a finished conversion's recording.

    404 when there is no recording. A project that has not been converted has
    nothing to stream, and an empty stream would read as a run that did nothing
    rather than a run that never happened.
    """
    load_project(session, project_id)
    job = _latest(session, project_id, DbJobKind.CONVERSION)
    if job is None or job.timeline is None:
        raise ApiException(
            ErrorCategory.NOT_FOUND,
            "This project has not been converted yet, so there is nothing to "
            "show.",
            detail=f"no conversion timeline for project {project_id}",
            status_code=404,
        )

    frames = _frames(job.timeline)
    after = _after(last_event_id)
    if after is not None:
        frames = [frame for frame in frames if frame[0] > after]

    return StreamingResponse(
        _sse(frames),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-store",
            # Proxies that buffer a response defeat the point of a stream.
            "x-accel-buffering": "no",
        },
    )


def _after(last_event_id: str | None) -> int | None:
    """A malformed id resumes from the beginning rather than failing.

    The header is set by the browser, not by our code, and refusing the request
    would leave a client that somehow sent a bad one unable to reconnect at all.
    Replaying from the start is the safe direction: it repeats events, and the
    ids let the client discard what it already has.
    """
    if last_event_id is None:
        return None
    try:
        return int(last_event_id.strip())
    except ValueError:
        return None
