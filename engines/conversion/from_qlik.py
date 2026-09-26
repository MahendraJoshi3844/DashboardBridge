"""Deterministic conversion: a Qlik app becomes a Power BI project.

The converter is `qlik2pbi` (repository Qlik-To-PowerBI), installed as a
dependency. It is built around what is specific to Qlik: the load script *is* the
data model (it is executed symbolically into Power Query), tables associate by
field name (resolved into a star schema with evidence-based cardinality), and
calculations are set analysis (translated to DAX with the chart's context).

Accepted uploads: a zipped `qlik app unbuild` folder, or a `.qvs` load script on
its own (the data model only). `.qvf`/`.qvw` binaries are refused at upload with
the export route.

Rule 1 (AGENTS.md): the engine runs with `placeholders=False`, so an expression it
cannot translate - and everything built on it - is not written, and a visual that
would show it loses that field, with a finding each time. A load-script table
whose query cannot be converted exactly keeps its columns with an empty query and
an unsupported flag: the model opens, and nothing loads rows Qlik would not.

The tiers, counts and recording are described in `engine_outcome.py`, shared
with the MicroStrategy seam.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from dashboardbridge_contracts.enums import Platform
from qlik2pbi.pipeline import Options
from qlik2pbi.pipeline import run as run_qlik2pbi

from engines.conversion.engine_outcome import canonical_model, outcome_from_engine
from engines.conversion.run import ConversionOutcome

_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


class UnreadableQlik(ValueError):
    """Nothing in the upload is a Qlik load script or app object.

    Converting it would produce an empty project that looks finished, so it is
    refused, naming what was found so the reader can be extended for it.
    """


def convert_qlik_to_powerbi(artifact: bytes, out_dir: Path, name: str) -> ConversionOutcome:
    """Read a zipped unbuild folder or a `.qvs` script, write a PBIP, report everything.

    `name` becomes the project's name; it only ever reaches the engine, which
    makes a safe path component of it.
    """
    suffix = ".zip" if artifact.startswith(_ZIP_SIGNATURES) else ".qvs"
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dbb-qlik-") as scratch:
        source = Path(scratch) / f"source{suffix}"
        source.write_bytes(artifact)
        from qlik2pbi.app.loader import load_app  # noqa: PLC0415

        app = load_app(source)
        if not app.script.strip() and not app.sheets and not app.measures:
            unknown = "; ".join(app.unrecognized) or "nothing"
            raise UnreadableQlik(
                "No Qlik load script, sheets or master items were found in that file. Upload the folder "
                "written by `qlik app unbuild` (zipped), or the app's load script as a .qvs. "
                f"Found: {unknown}."
            )
        run = run_qlik2pbi(source, out_dir, Options(project_name=name, placeholders=False))

    canonical = canonical_model(
        platform=Platform.QLIK,
        name=name,
        model=run.model,
        pages=run.plan.pages,
        source_language="qlik_expression",
        datasource_id=f"app:{run.app.name}",
        datasource_name=run.app.name,
        connection=", ".join(sorted({c.kind or c.name for c in run.app.connections})) or "unknown",
    )
    return outcome_from_engine(
        project_dir=out_dir,
        findings=run.log.sorted(),
        model=run.model,
        pages=run.plan.pages,
        canonical=canonical,
        measure_ref=lambda m: f"{'master measure' if m.origin == 'master' else 'chart expression'}:{m.name}",
        measure_kinds={"master measure", "chart expression"},
    )
