"""Deterministic conversion: a Tableau artifact becomes a Power BI project.

Runs the engine's pipeline and maps its result into the canonical contracts
(ADR-009). Nothing here decides what converts — the pipeline does — so this
module's only job is to report what happened without smoothing any of it away.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dashboardbridge_contracts import CanonicalModel, Compatibility, ConversionFlag
from dashboardbridge_contracts.enums import (
    ConversionMethod,
    ConversionStatus,
    Severity,
    Stage,
)
from engines.t2pbi.events import EventSink, Timeline
from engines.t2pbi.ir import Severity as IRSeverity
from engines.t2pbi.pipeline import run as run_pipeline

# The engine reports how loudly to speak; the contracts also need what became of
# each object and how (ADR-004). Shared with the read adapter so both directions
# describe the same outcome the same way.
_METHOD = {
    IRSeverity.INFO: ConversionMethod.DETERMINISTIC,
    IRSeverity.WARNING: ConversionMethod.DETERMINISTIC,
    IRSeverity.MANUAL: ConversionMethod.MANUAL,
}


def _status(severity: IRSeverity, stage: str) -> ConversionStatus:
    """What became of an object — and what "needs AI" is allowed to mean.

    Severity alone cannot answer this. Mapping every MANUAL flag to
    AI_REQUIRED said 51 items needed a model on a workbook where a model could
    attempt six: the other 45 were worksheet filters, dashboard layouts and
    unbindable field wells, all of which need a person to rebuild them and
    none of which a model can draft.

    Only a refused *expression* is something a model could attempt, and those
    come from the translate stage. Everything else that needs a human is
    UNSUPPORTED, which is the truth and is also less flattering.
    """
    if severity is IRSeverity.INFO:
        return ConversionStatus.CONVERTED
    if severity is IRSeverity.WARNING:
        return ConversionStatus.PARTIAL
    return (
        ConversionStatus.AI_REQUIRED
        if stage == "translate"
        else ConversionStatus.UNSUPPORTED
    )


_STAGE = {
    "extract": Stage.EXTRACT,
    "parse": Stage.PARSE,
    "visual_map": Stage.MAP,
    "translate": Stage.TRANSLATE,
    "emit": Stage.GENERATE,
}


@dataclass
class ConversionOutcome:
    """What the conversion produced, in contract terms."""

    project_dir: Path
    model: CanonicalModel
    flags: list[ConversionFlag]
    compatibility: Compatibility
    timeline: Timeline
    stats: dict[str, int]


def convert_tableau_to_powerbi(
    artifact: bytes,
    out_dir: Path,
    name: str,
    accepted: dict[str, tuple[str, str]] | None = None,
) -> ConversionOutcome:
    """Convert, with no AI anywhere in the path.

    The artifact is written to a temporary file because the engine's extractor
    reads a path — a `.twbx` is a zip, and reading one member of it needs a
    seekable file rather than a stream.

    That file is named by us, never by `name`. `name` is the project's name and
    the project's name came from a person or from an uploaded file, so building
    a path out of it means an attacker chooses a path: separators walk out of
    the staging directory, and on Windows a character as ordinary as `<` makes
    the write fail outright. The name still reaches the emitter, which quotes it
    for TMDL rather than opening it.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    sink = EventSink()

    with tempfile.TemporaryDirectory(prefix="dbb-convert-") as staging:
        source = Path(staging) / "source.twb"
        source.write_bytes(artifact)
        result = run_pipeline(
            source,
            out_dir,
            name,
            sink=sink,
            # `{item: (expression, proposal id)}`. The id travels with the
            # expression so the produced model can say a person accepted a
            # model's draft rather than a rule producing it (§62).
            accepted=accepted or {},
        )

    flags = [
        ConversionFlag(
            item=flag.item,
            stage=_STAGE.get(flag.stage, Stage.GENERATE),
            method=_METHOD[flag.severity],
            status=_status(flag.severity, flag.stage),
            severity=Severity(flag.severity.value),
            reason=flag.reason,
            ref=flag.item,
        )
        for flag in result.workbook.flags
    ]
    # Normalised *after* the pipeline, so every column that translated carries
    # its DAX. The same mapping the read path uses, so both directions describe
    # the same object the same way.
    from engines.adapters.tableau import TableauAdapter  # noqa: PLC0415

    flags.extend(_ai_assisted_flags(accepted or {}))

    return ConversionOutcome(
        project_dir=out_dir,
        model=TableauAdapter().normalize(result.workbook),
        flags=flags,
        compatibility=_compatibility(result.stats, flags),
        timeline=result.timeline,
        stats=result.stats,
    )


def _compatibility(stats: dict[str, int], flags: list[ConversionFlag]) -> Compatibility:
    """Counts whose parts sum to the whole, so a reader can check the arithmetic.

    `converted` is derived by subtraction rather than counted independently:
    an object with no flag converted cleanly, and deriving it means the total
    cannot drift away from the flags that explain it.
    """
    considered = sum(
        stats.get(kind, 0)
        for kind in (
            "tables",
            "columns",
            "worksheets",
            "parameters",
            "relationships",
            # Dashboards and filters are flagged one by one, so they belong in
            # the denominator. Leaving them out does not flatter the result, it
            # ruins it: on a workbook with more filters than columns the
            # flagged count exceeds everything counted, every cleanly converted
            # object is subtracted away, and the screen reports nothing
            # converted for a run that converted plenty.
            "dashboards",
            "filters",
            # Every field placed on a visual. Reported one by one since
            # `P2.2`, so counted one by one here for the same reason
            # dashboards and filters are.
            "bindings",
        )
    )
    tally = {status: 0 for status in ConversionStatus}
    for flag in flags:
        tally[flag.status] += 1

    flagged = sum(
        count
        for status, count in tally.items()
        if status is not ConversionStatus.CONVERTED
    )
    return Compatibility(
        converted=max(considered - flagged, 0),
        partial=tally[ConversionStatus.PARTIAL],
        ai_required=tally[ConversionStatus.AI_REQUIRED],
        unsupported=tally[ConversionStatus.UNSUPPORTED],
        failed=tally[ConversionStatus.FAILED],
        total=max(considered, flagged),
    )


def zip_project(project_dir: Path, destination: Path) -> Path:
    """A PBIP is a folder, so it is delivered as an archive.

    Written with a fixed member order and no compression timestamps of our own,
    because two conversions of the same workbook must produce the same contents.
    """
    archive = shutil.make_archive(
        str(destination.with_suffix("")), "zip", root_dir=project_dir
    )
    return Path(archive)


def _ai_assisted_flags(
    accepted: dict[str, tuple[str, str]],
) -> list[ConversionFlag]:
    """One flag per accepted draft, so it appears in the report as itself.

    Status `converted`, because it did convert. Method `ai_assisted`, because a
    model drafted it. Severity `info`, because there is nothing left to do -
    a person already did the deciding, which is the whole point of ADR-007.
    """
    return [
        ConversionFlag(
            item=item,
            stage=Stage.TRANSLATE,
            method=ConversionMethod.AI_ASSISTED,
            status=ConversionStatus.CONVERTED,
            severity=Severity.INFO,
            reason=(
                "Drafted by a model and accepted by a person before it was "
                f"written (proposal {proposal_id})."
            ),
            ref=item,
        )
        for item, (_, proposal_id) in sorted(accepted.items())
    ]
