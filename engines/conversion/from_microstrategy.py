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

## How the engine's tiers become contract statuses

| mstr2pbi | status | severity |
|---|---|---|
| exact | converted | info |
| assumed (converted on a stated assumption) | partial | warning |
| manual / unsupported | unsupported | manual |
| info (advice) | converted | info |

`ai_required` is never used: no model is consulted on this path, and "a model
could draft this" is not a claim this module can make.

## Counts

Per object, as the other directions count: every measure, table, relationship,
page and every object the engine reported on is one object, counted once as its
worst finding.
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from dashboardbridge_contracts import (
    CanonicalModel,
    ConversionFlag,
)
from dashboardbridge_contracts.canonical import (
    Column,
    Dashboard,
    DataSource,
    Expression,
    Relationship,
    Table,
    Translation,
    Visual,
)
from dashboardbridge_contracts.enums import (
    ConversionMethod,
    ConversionStatus,
    DataType,
    Platform,
    Severity,
    Stage,
)
from mstr2pbi.catalog.loader import BUNDLE_KEYS
from mstr2pbi.findings import Fidelity, Finding
from mstr2pbi.pipeline import Options
from mstr2pbi.pipeline import run as run_mstr2pbi

from engines.conversion.run import ConversionOutcome, compatibility_by_object
from engines.t2pbi.events import CROSSED, HELD, EventSink


class UnreadableMicroStrategy(ValueError):
    """The archive holds nothing the reader recognises as MicroStrategy metadata.

    Converting it would produce an empty project that looks finished, so it is
    refused, naming what was inside so the reader can be extended for it.
    """


#: Member names that make a zip an export bundle rather than a `.mstr` package.
BUNDLE_MEMBERS = frozenset(f"{key}.json" for key in BUNDLE_KEYS)

_STATUS = {
    Fidelity.EXACT: (ConversionStatus.CONVERTED, Severity.INFO, ConversionMethod.DETERMINISTIC),
    Fidelity.INFO: (ConversionStatus.CONVERTED, Severity.INFO, ConversionMethod.DETERMINISTIC),
    Fidelity.ASSUMED: (ConversionStatus.PARTIAL, Severity.WARNING, ConversionMethod.DETERMINISTIC),
    Fidelity.MANUAL: (ConversionStatus.UNSUPPORTED, Severity.MANUAL, ConversionMethod.MANUAL),
    Fidelity.UNSUPPORTED: (ConversionStatus.UNSUPPORTED, Severity.MANUAL, ConversionMethod.MANUAL),
}

_STAGE = {
    "acquire": Stage.EXTRACT,
    "assess": Stage.PARSE,
    "model": Stage.MAP,
    "translate": Stage.TRANSLATE,
    "layout": Stage.MAP,
    "emit": Stage.GENERATE,
    "validate": Stage.VALIDATE,
    "report": Stage.REPORT,
}

_TYPES = {
    "string": DataType.STRING,
    "integer": DataType.INTEGER,
    "decimal": DataType.DECIMAL,
    "double": DataType.DECIMAL,
    "date": DataType.DATE,
    "datetime": DataType.DATETIME,
    "boolean": DataType.BOOLEAN,
}

#: The order statuses are ranked in; worst last.
_RANK = (
    ConversionStatus.CONVERTED,
    ConversionStatus.PARTIAL,
    ConversionStatus.AI_REQUIRED,
    ConversionStatus.UNSUPPORTED,
    ConversionStatus.FAILED,
)


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


def _ref(finding: Finding) -> str:
    return f"{finding.object_type}:{finding.object_name}"


def _flag(finding: Finding) -> ConversionFlag:
    status, severity, method = _STATUS[finding.fidelity]
    reason = finding.message
    if finding.action:
        reason = f"{reason} What to do: {finding.action}"
    return ConversionFlag(
        item=f"{finding.object_type}: {finding.object_name}",
        stage=_STAGE.get(finding.stage, Stage.MAP),
        method=method,
        status=status,
        severity=severity,
        reason=reason,
        ref=_ref(finding),
    )


def _canonical(run, name: str) -> CanonicalModel:
    """The produced model, in contract terms, for the screens that read one."""
    sem = run.model
    tables: list[Table] = []
    for table in sorted(sem.tables, key=lambda t: t.name.lower()):
        columns = [
            Column(
                id=f"{table.name}.{column.name}",
                name=column.name,
                datatype=_TYPES.get(column.data_type, DataType.UNKNOWN),
                role="dimension",
                expression=(
                    Expression(source_language="dax", source_text=column.expression)
                    if column.expression
                    else None
                ),
            )
            for column in table.columns
        ]
        columns += [
            Column(
                id=f"{table.name}.{measure.name}",
                name=measure.name,
                datatype=DataType.DECIMAL,
                role="measure",
                expression=Expression(
                    source_language="microstrategy_metric", source_text=measure.source
                ),
                translation=Translation(
                    target_language="dax",
                    target_text=measure.dax,
                    method=ConversionMethod.DETERMINISTIC,
                ),
            )
            for measure in sorted(table.measures, key=lambda m: m.name.lower())
        ]
        tables.append(Table(id=f"table:{table.name}", name=table.name, columns=columns))

    visuals: list[Visual] = []
    dashboards: list[Dashboard] = []
    for page in run.plan.pages:
        ids = []
        for index, visual in enumerate(page.visuals):
            visual_id = f"visual:{page.name}:{index}"
            ids.append(visual_id)
            visuals.append(
                Visual(id=visual_id, name=f"{page.name} / {visual.name}", visual_type=visual.visual_type)
            )
        dashboards.append(Dashboard(id=f"page:{page.name}", name=page.name, visual_ids=ids))

    connection = ", ".join(sorted({ds.db_type for ds in run.catalog.datasources})) or "unknown"
    return CanonicalModel(
        source_platform=Platform.MICROSTRATEGY,
        name=name,
        datasources=[
            DataSource(
                id=f"project:{run.catalog.project}",
                name=run.catalog.project,
                connection=connection,
                tables=tables,
            )
        ],
        relationships=[
            Relationship(
                from_table=r.from_table,
                from_column=r.from_column,
                to_table=r.to_table,
                to_column=r.to_column,
                # Inactive paths are reported as flags; the kind stays the contract's.
                kind="many_to_one",
            )
            for r in sem.relationships
        ],
        visuals=visuals,
        dashboards=dashboards,
    )


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

    findings = run.log.sorted()
    flags = sorted((_flag(f) for f in findings), key=lambda f: (f.ref, f.stage.value, f.reason))

    worst: dict[str, ConversionStatus] = {}
    for flag in flags:
        current = worst.get(flag.ref, ConversionStatus.CONVERTED)
        worst[flag.ref] = max(current, flag.status, key=_RANK.index)

    objects: list[str] = []
    for table in run.model.tables:
        objects.append(f"table:{table.name}")
        objects.extend(f"metric:{m.name}" for m in table.measures)
    objects.extend(f"relationship:{r.from_table} -> {r.to_table}" for r in run.model.relationships)
    objects.extend(f"page:{p.name}" for p in run.plan.pages)

    sink = EventSink()
    measures = {m.name: m for m in run.model.all_measures()}
    recorded: set[str] = set()
    for finding in findings:
        # One event per metric, from the finding that decided it (a metric can
        # also carry a format or threshold finding).
        if finding.object_type != "metric" or finding.stage != "translate" or not finding.source:
            continue
        if finding.object_name in recorded:
            continue
        recorded.add(finding.object_name)
        measure = measures.get(finding.object_name)
        held = measure is None
        sink.emit(
            stage="Translate",
            kind="metric",
            name=finding.object_name,
            outcome=HELD if held else CROSSED,
            detail=finding.message if held else finding.fidelity.value,
            ref=_ref(finding),
            source=finding.source,
            result="" if held else measure.dax,
        )
    for table in sorted(run.model.tables, key=lambda t: t.name.lower()):
        sink.emit(stage="Generate", kind="table", name=table.name, outcome=CROSSED,
                  detail=f"{len(table.columns)} columns", ref=f"table:{table.name}")
    for page in run.plan.pages:
        sink.emit(stage="Generate", kind="page", name=page.name, outcome=CROSSED,
                  detail=f"{len(page.visuals)} visuals", ref=f"page:{page.name}")

    kinds = Counter(ref.split(":", 1)[0] for ref in set(objects) | set(worst))
    return ConversionOutcome(
        project_dir=out_dir,
        model=_canonical(run, name),
        flags=flags,
        compatibility=compatibility_by_object(objects, worst),
        timeline=sink.timeline(),
        stats=dict(sorted(kinds.items())),
    )
