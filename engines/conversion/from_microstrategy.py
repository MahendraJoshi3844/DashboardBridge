"""Deterministic conversion: a MicroStrategy export becomes a Power BI project.

The converter is `mstr2pbi`, a separate engine in its own repository
(MicroStrategy-to-Power-BI), installed as a dependency. It is built around
MicroStrategy's semantic layer - attributes, facts, level metrics, the object
graph of a whole project - which is why it is not a mode of `t2pbi`. This module
is the seam: run that engine, then describe what it did in contract terms.

## Rule 1, and why the engine is asked to hold back

`mstr2pbi` on its own keeps an untranslatable metric as a `BLANK()` measure, so
a developer has a named slot to fill. That is a placeholder, and AGENTS.md rule 1
forbids placeholders here. So it runs with `placeholders=False`: a metric it
cannot translate - and every measure built on one - is not written, and is
reported as unsupported with the reason and the Power BI construct to use.

The tiers, counts and recording are described in `engine_outcome.py`, shared
with the Qlik seam.
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from dashboardbridge_contracts.enums import Platform
from mstr2pbi.catalog.loader import BUNDLE_KEYS
from mstr2pbi.pipeline import Options
from mstr2pbi.pipeline import run as run_mstr2pbi

from engines.conversion.engine_outcome import canonical_model, outcome_from_engine
from engines.conversion.run import ConversionOutcome


class UnreadableMicroStrategy(ValueError):
    """The archive holds nothing the reader recognises as MicroStrategy metadata.

    Converting it would produce an empty project that looks finished, so it is
    refused, naming what was inside so the reader can be extended for it.
    """


#: Member names that make a zip an export bundle rather than a `.mstr` package.
BUNDLE_MEMBERS = frozenset(f"{key}.json" for key in BUNDLE_KEYS)


def _suffix_for(data: bytes) -> str:
    """`.zip` for an export bundle, `.mstr` for anything else zipped.

    The engine reads both; which reader runs depends on the name, and the member
    list is what decides it - not the name the file was uploaded with.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = {Path(name).name.lower() for name in archive.namelist()}
    except zipfile.BadZipFile as exc:
        raise UnreadableMicroStrategy(
            "That file is not a MicroStrategy package: it is not an archive. Export the "
            "dossier again from MicroStrategy Workstation (.mstr), or upload the metadata "
            "export bundle as a .zip."
        ) from exc
    return ".zip" if names & BUNDLE_MEMBERS else ".mstr"


def convert_microstrategy_to_powerbi(artifact: bytes, out_dir: Path, name: str) -> ConversionOutcome:
    """Read a `.mstr` package or zipped export bundle, write a PBIP, report everything.

    `name` becomes the project's name. It came from a person or an uploaded file,
    so it only ever reaches the engine, which makes a safe path component of it.
    """
    suffix = _suffix_for(artifact)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dbb-mstr-") as scratch:
        source = Path(scratch) / f"source{suffix}"
        source.write_bytes(artifact)
        from mstr2pbi.catalog.loader import load_catalog  # noqa: PLC0415

        catalog = load_catalog(source)
        counts = catalog.counts()
        readable = sum(counts[k] for k in ("attributes", "metrics", "dossiers", "reports", "documents", "tables"))
        if readable == 0:
            unknown = "; ".join(catalog.unrecognized) or "nothing"
            raise UnreadableMicroStrategy(
                "No MicroStrategy objects were found in that file (no attributes, metrics, "
                f"reports or dossiers). Found: {unknown}."
            )
        run = run_mstr2pbi(source, out_dir, Options(project_name=name, placeholders=False))

    canonical = canonical_model(
        platform=Platform.MICROSTRATEGY,
        name=name,
        model=run.model,
        pages=run.plan.pages,
        source_language="microstrategy_metric",
        datasource_id=f"project:{run.catalog.project}",
        datasource_name=run.catalog.project,
        connection=", ".join(sorted({ds.db_type for ds in run.catalog.datasources})) or "unknown",
    )
    return outcome_from_engine(
        project_dir=out_dir,
        findings=run.log.sorted(),
        model=run.model,
        pages=run.plan.pages,
        canonical=canonical,
        measure_ref=lambda m: f"metric:{m.name}",
        measure_kinds={"metric"},
    )
