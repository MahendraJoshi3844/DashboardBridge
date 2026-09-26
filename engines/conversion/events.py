"""The conversion recording, owned by the DashboardBridge shell.

Every engine seam (Tableau, MicroStrategy, Qlik) reports what crossed and
what was held in this shape. It started as `t2pbi.events`; the shell keeps
its own copy so it does not need the Tableau engine installed to record.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

# Which side of the seam an item ends on. "crossed" reached Power BI; "held"
# stopped at the seam for a human. There is no third outcome by design: an item
# we neither converted nor reported would be exactly the silent drop this
# product exists to prevent.
CROSSED = "crossed"
HELD = "held"
_OUTCOMES = frozenset({CROSSED, HELD})


@dataclass(frozen=True)
class ConversionEvent:
    """One item the pipeline handled, and what became of it."""

    seq: int
    elapsed_ms: int
    stage: str  # Extract | Parse | Map | Translate | Generate | Report
    kind: str  # table | column | calc | visual | parameter | relationship
    name: str
    outcome: str  # crossed | held
    detail: str = ""  # "measure", "clusteredBarChart", or why it was held
    ref: str = ""  # IR reference, e.g. "Orders.Profit Ratio", for drill-down
    # The proof panel puts these side by side. Carried on the event so opening a
    # drill-down costs no round-trip; empty for anything that is not a calc.
    source: str = ""  # the original Tableau expression
    result: str = ""  # the emitted DAX, empty when the item was held

    def __post_init__(self) -> None:
        if self.outcome not in _OUTCOMES:
            raise ValueError(
                f"outcome must be one of {sorted(_OUTCOMES)}, got {self.outcome!r}"
            )


@dataclass
class Timeline:
    """A complete recorded run: every event, plus how long it really took."""

    events: list[ConversionEvent] = field(default_factory=list)
    duration_ms: int = 0

    def crossed(self) -> list[ConversionEvent]:
        return [e for e in self.events if e.outcome == CROSSED]

    def held(self) -> list[ConversionEvent]:
        return [e for e in self.events if e.outcome == HELD]

    def to_dict(self) -> dict:
        """JSON-serializable form. This is the payload the UI bridge receives."""
        return {
            "durationMs": self.duration_ms,
            "events": [asdict(e) for e in self.events],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Timeline:
        return cls(
            events=[ConversionEvent(**e) for e in data.get("events", [])],
            duration_ms=data.get("durationMs", 0),
        )


class EventSink:
    """Collects events during a run. Created and owned by `pipeline.run`."""

    def __init__(self) -> None:
        self._events: list[ConversionEvent] = []
        self._started = time.perf_counter()

    def _elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._started) * 1000)

    def emit(
        self,
        stage: str,
        kind: str,
        name: str,
        outcome: str,
        detail: str = "",
        ref: str = "",
        source: str = "",
        result: str = "",
    ) -> None:
        self._events.append(
            ConversionEvent(
                seq=len(self._events),
                elapsed_ms=self._elapsed_ms(),
                stage=stage,
                kind=kind,
                name=name,
                outcome=outcome,
                detail=detail,
                ref=ref,
                source=source,
                result=result,
            )
        )

    def timeline(self) -> Timeline:
        return Timeline(events=list(self._events), duration_ms=self._elapsed_ms())


class _NullSink(EventSink):
    """Default sink for callers that do not want a recording (CLI, most tests)."""

    def emit(self, *args, **kwargs) -> None:  # noqa: D102
        return

    def timeline(self) -> Timeline:
        return Timeline()


NULL_SINK = _NullSink()
