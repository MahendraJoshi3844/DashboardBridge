"""What every engine seam returns, owned by the shell.

Tableau, MicroStrategy and Qlik seams all describe their result as a
`ConversionOutcome`; the API stores and serves it without knowing which engine
produced it. Lives here, not in the Tableau seam, so the shell works with any
combination of engines installed.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from dashboardbridge_contracts import CanonicalModel, Compatibility, ConversionFlag
from dashboardbridge_contracts.enums import ConversionStatus

from engines.conversion.events import Timeline


@dataclass
class ConversionOutcome:
    """What the conversion produced, in contract terms."""

    project_dir: Path
    model: CanonicalModel
    flags: list[ConversionFlag]
    compatibility: Compatibility
    timeline: Timeline
    stats: dict[str, int]


def compatibility_by_object(
    refs: list[str], worst: dict[str, ConversionStatus]
) -> Compatibility:
    """Counts over objects, each counted once as its worst flag says.

    The parts sum to the whole by construction: every object lands in exactly
    one bucket, and one with no flag converted. A flag naming no object in
    `refs` is not silently lost either - it is counted as an object of its own,
    because "every flagged object is in the total" is the promise the headline
    makes.
    """
    everything = sorted(set(refs) | set(worst))
    tally = {status: 0 for status in ConversionStatus}
    for ref in everything:
        tally[worst.get(ref, ConversionStatus.CONVERTED)] += 1
    return Compatibility(
        converted=tally[ConversionStatus.CONVERTED],
        partial=tally[ConversionStatus.PARTIAL],
        ai_required=tally[ConversionStatus.AI_REQUIRED],
        unsupported=tally[ConversionStatus.UNSUPPORTED],
        failed=tally[ConversionStatus.FAILED],
        total=len(everything),
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
