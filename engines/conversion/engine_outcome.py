"""Describe what an external PBIP engine did, in contract terms.

`mstr2pbi` and `qlik2pbi` are separate engines with the same shape of result: a
planned semantic model, a report plan (pages of visuals) and a log of findings,
each with a fidelity tier. This module turns that result into what every
DashboardBridge screen reads - flags, per-object counts, a recording, and a
canonical model - so each engine's seam only has to say what is specific to it.

## How the engines' tiers become contract statuses

| engine tier | status | severity |
|---|---|---|
| exact | converted | info |
| assumed (converted on a stated assumption) | partial | warning |
| manual / unsupported | unsupported | manual |
| info (advice) | converted | info |

`ai_required` is never used: no model is consulted on these paths.

## Counts

Per object: every table, measure, relationship and page, plus every object the
engine reported on, counted once as its worst finding.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

from dashboardbridge_contracts import CanonicalModel, ConversionFlag
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

from engines.conversion.run import ConversionOutcome, compatibility_by_object
from engines.t2pbi.events import CROSSED, HELD, EventSink

_STATUS = {
    "exact": (ConversionStatus.CONVERTED, Severity.INFO, ConversionMethod.DETERMINISTIC),
    "info": (ConversionStatus.CONVERTED, Severity.INFO, ConversionMethod.DETERMINISTIC),
    "assumed": (ConversionStatus.PARTIAL, Severity.WARNING, ConversionMethod.DETERMINISTIC),
    "manual": (ConversionStatus.UNSUPPORTED, Severity.MANUAL, ConversionMethod.MANUAL),
    "unsupported": (ConversionStatus.UNSUPPORTED, Severity.MANUAL, ConversionMethod.MANUAL),
}

#: Engine stage names (both engines) -> contract stages.
_STAGE = {
    "acquire": Stage.EXTRACT,
    "read": Stage.EXTRACT,
    "assess": Stage.PARSE,
    "script": Stage.TRANSLATE,
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

#: Worst last.
_RANK = (
    ConversionStatus.CONVERTED,
    ConversionStatus.PARTIAL,
    ConversionStatus.AI_REQUIRED,
    ConversionStatus.UNSUPPORTED,
    ConversionStatus.FAILED,
)


def finding_ref(finding: Any) -> str:
    return f"{finding.object_type}:{finding.object_name}"


def to_flag(finding: Any) -> ConversionFlag:
    status, severity, method = _STATUS[finding.fidelity.value]
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
        ref=finding_ref(finding),
    )


def canonical_model(
    *,
    platform: Platform,
    name: str,
    model: Any,
    pages: Iterable[Any],
    source_language: str,
    datasource_id: str,
    datasource_name: str,
    connection: str,
) -> CanonicalModel:
    """The produced model, in contract terms, for the screens that read one."""
    tables: list[Table] = []
    for table in sorted(model.tables, key=lambda t: t.name.lower()):
        columns = [
            Column(
                id=f"{table.name}.{column.name}",
                name=column.name,
                datatype=_TYPES.get(column.data_type, DataType.UNKNOWN),
                role="dimension",
                expression=(Expression(source_language="dax", source_text=column.expression)
                            if column.expression else None),
            )
            for column in table.columns
        ]
        columns += [
            Column(
                id=f"{table.name}.{measure.name}",
                name=measure.name,
                datatype=DataType.DECIMAL,
                role="measure",
                expression=Expression(source_language=source_language, source_text=measure.source),
                translation=Translation(target_language="dax", target_text=measure.dax,
                                        method=ConversionMethod.DETERMINISTIC),
            )
            for measure in sorted(table.measures, key=lambda m: m.name.lower())
        ]
        tables.append(Table(id=f"table:{table.name}", name=table.name, columns=columns))

    visuals: list[Visual] = []
    dashboards: list[Dashboard] = []
    for page in pages:
        ids = []
        for index, visual in enumerate(page.visuals):
            visual_id = f"visual:{page.name}:{index}"
            ids.append(visual_id)
            visuals.append(Visual(id=visual_id, name=f"{page.name} / {visual.name}", visual_type=visual.visual_type))
        dashboards.append(Dashboard(id=f"page:{page.name}", name=page.name, visual_ids=ids))

    return CanonicalModel(
        source_platform=platform,
        name=name,
        datasources=[DataSource(id=datasource_id, name=datasource_name, connection=connection, tables=tables)],
        relationships=[
            # Inactive and many-to-many paths are reported as flags; the kind stays the contract's.
            Relationship(from_table=r.from_table, from_column=r.from_column, to_table=r.to_table,
                         to_column=r.to_column, kind="many_to_one")
            for r in model.relationships
        ],
        visuals=visuals,
        dashboards=dashboards,
    )


def outcome_from_engine(
    *,
    project_dir: Path,
    findings: list[Any],
    model: Any,
    pages: list[Any],
    canonical: CanonicalModel,
    measure_ref: Callable[[Any], str],
    measure_kinds: set[str],
) -> ConversionOutcome:
    flags = sorted((to_flag(f) for f in findings), key=lambda f: (f.ref, f.stage.value, f.reason))
    worst: dict[str, ConversionStatus] = {}
    for flag in flags:
        current = worst.get(flag.ref, ConversionStatus.CONVERTED)
        worst[flag.ref] = max(current, flag.status, key=_RANK.index)

    objects: list[str] = []
    for table in model.tables:
        objects.append(f"table:{table.name}")
        objects.extend(measure_ref(m) for m in table.measures)
    objects.extend(f"relationship:{r.from_table} -> {r.to_table}" for r in model.relationships)
    objects.extend(f"page:{p.name}" for p in pages)

    sink = EventSink()
    measures = {m.name: m for m in model.all_measures()}
    recorded: set[str] = set()
    for finding in findings:
        # One event per measure, from the finding that decided it.
        if finding.object_type not in measure_kinds or finding.stage != "translate" or not finding.source:
            continue
        if finding.object_name in recorded:
            continue
        recorded.add(finding.object_name)
        measure = measures.get(finding.object_name)
        held = measure is None
        sink.emit(
            stage="Translate",
            kind=finding.object_type,
            name=finding.object_name,
            outcome=HELD if held else CROSSED,
            detail=finding.message if held else finding.fidelity.value,
            ref=finding_ref(finding),
            source=finding.source,
            result="" if held else measure.dax,
        )
    for table in sorted(model.tables, key=lambda t: t.name.lower()):
        sink.emit(stage="Generate", kind="table", name=table.name, outcome=CROSSED,
                  detail=f"{len(table.columns)} columns", ref=f"table:{table.name}")
    for page in pages:
        sink.emit(stage="Generate", kind="page", name=page.name, outcome=CROSSED,
                  detail=f"{len(page.visuals)} visuals", ref=f"page:{page.name}")

    kinds = Counter(ref.split(":", 1)[0] for ref in set(objects) | set(worst))
    return ConversionOutcome(
        project_dir=project_dir,
        model=canonical,
        flags=flags,
        compatibility=compatibility_by_object(objects, worst),
        timeline=sink.timeline(),
        stats=dict(sorted(kinds.items())),
    )
