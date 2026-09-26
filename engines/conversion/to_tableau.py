"""Deterministic conversion: a Power BI project becomes a Tableau workbook.

The mirror of `run.convert_tableau_to_powerbi`, and deliberately not a copy of
it. That direction has an engine with its own pipeline and statistics; this one
is two adapters - read PBIP, write `.twb` - with the canonical model between
them, which is what the model was for.

## How the counts are made

Per object, never by subtraction. Every table, column, relationship, parameter,
visual and dashboard in the model is one object; an object with no flag
converted, and an object with flags is counted as its worst one. The parts
therefore sum to the whole by construction, and an object named by three flags
is still one object - which is the question a person reading "14 of 17" is
asking.

The forward direction derives `converted` by subtracting flags from a total,
and on a workbook where one object carries several flags that undercounts. It
is left alone here; changing it would move every Tableau number a customer has
already seen.

## What this does not do

No model is consulted (spec `SPEC-powerbi-to-tableau-web.md`, Q3), so
`ai_required` is always zero: a refused DAX expression is `unsupported`, and the
reason says what a person has to write.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from dashboardbridge_contracts import CanonicalModel, ConversionFlag
from dashboardbridge_contracts.enums import ConversionStatus

from engines.adapters.powerbi import PowerBIAdapter
from engines.adapters.tableau_emit import emit_twb
from engines.conversion.outcome import ConversionOutcome, compatibility_by_object
from t2pbi.events import CROSSED, HELD, EventSink


class NoSemanticModel(ValueError):
    """The archive holds a report and no model for its visuals to read.

    Converting it would produce worksheets bound to nothing, so it is refused
    with a sentence rather than converted into something that looks finished.
    """


#: Worst last. A flag of any of these, on an object, is what it is counted as.
_RANK = (
    ConversionStatus.CONVERTED,
    ConversionStatus.PARTIAL,
    ConversionStatus.AI_REQUIRED,
    ConversionStatus.UNSUPPORTED,
    ConversionStatus.FAILED,
)


def objects_of(model: CanonicalModel) -> list[tuple[str, str, str]]:
    """Every object the counts are over, as `(kind, name, ref)`, in a fixed order.

    `ref` is the key the writer's flags use, so a flag finds its object without
    any matching on names that two objects may share.
    """
    found: list[tuple[str, str, str]] = []
    for table in sorted(model.all_tables(), key=lambda item: item.name):
        found.append(("table", table.name, f"table:{table.name}"))
        for column in table.columns:
            kind = "calc" if column.is_calculated else "column"
            ref = f"{table.name}.{column.display_name}"
            found.append((kind, column.display_name, ref))
    for rel in model.relationships:
        name = f"{rel.from_table}.{rel.from_column} -> {rel.to_table}.{rel.to_column}"
        found.append(("relationship", name, f"relationship:{name}"))
    for parameter in sorted(model.parameters, key=lambda item: item.name):
        name = parameter.caption or parameter.name
        found.append(("parameter", name, f"parameter:{name}"))
    for visual in sorted(model.visuals, key=lambda item: item.name):
        found.append(("visual", visual.name, f"visual:{visual.name}"))
    for dashboard in sorted(model.dashboards, key=lambda item: item.name):
        found.append(("dashboard", dashboard.name, f"dashboard:{dashboard.name}"))
    return found


def _worst(flags: list[ConversionFlag]) -> dict[str, ConversionStatus]:
    worst: dict[str, ConversionStatus] = {}
    for flag in flags:
        current = worst.get(flag.ref, ConversionStatus.CONVERTED)
        worst[flag.ref] = max(current, flag.status, key=_RANK.index)
    return worst


def convert_powerbi_to_tableau(
    artifact: bytes, out_dir: Path, name: str
) -> ConversionOutcome:
    """Read a zipped PBIP, write a `.twb` into `out_dir`, report everything.

    `name` becomes the workbook's name and file stem. It came from a person or
    an uploaded file, so it only ever reaches the writer, which makes a safe
    stem of it - never a path built here.
    """
    sink = EventSink()
    adapter = PowerBIAdapter()
    model = adapter.normalize(adapter.parse(artifact)).model_copy(update={"name": name})
    if not model.all_tables():
        raise NoSemanticModel(
            "This project has a report but no semantic model, so there is "
            "nothing for its visuals to read. Zip the whole project folder, "
            "including the .SemanticModel folder, and upload that."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    emission = emit_twb(model, out_dir)
    flags = sorted(
        [*model.flags, *emission.flags],
        key=lambda flag: (flag.ref, flag.stage.value, flag.reason),
    )

    worst = _worst(flags)
    objects = objects_of(model)
    columns = {
        f"{table.name}.{column.display_name}": column
        for table in model.all_tables()
        for column in table.columns
    }
    formulas = _written_formulas(emission.path)
    for kind, object_name, ref in objects:
        status = worst.get(ref, ConversionStatus.CONVERTED)
        held = status in {ConversionStatus.UNSUPPORTED, ConversionStatus.FAILED}
        column = columns.get(ref)
        source = column.expression.source_text if column and column.expression else ""
        sink.emit(
            stage="Translate" if kind == "calc" else "Generate",
            kind=kind,
            name=object_name,
            outcome=HELD if held else CROSSED,
            detail=_reason(flags, ref) if held else status.value,
            ref=ref,
            source=source,
            result="" if held or not source else formulas.get(ref, ""),
        )

    return ConversionOutcome(
        project_dir=out_dir,
        model=model,
        flags=flags,
        compatibility=compatibility_by_object([ref for _, _, ref in objects], worst),
        timeline=sink.timeline(),
        stats=dict(sorted(Counter(kind for kind, _, _ in objects).items())),
    )


def _reason(flags: list[ConversionFlag], ref: str) -> str:
    return next((flag.reason for flag in flags if flag.ref == ref), "")


def _written_formulas(path: Path) -> dict[str, str]:
    """`Table.Column` to the formula actually written, read back off the file.

    Read from the output rather than recomputed, so the side-by-side view shows
    what is in the workbook a person downloads - including the rewrite into the
    flat names related tables share - and not what a second call would produce.
    """
    from lxml import etree  # noqa: PLC0415

    formulas: dict[str, str] = {}
    root = etree.parse(str(path)).getroot()
    for datasource in root.iterfind("./datasources/datasource"):
        maps = {
            node.get("key"): node.get("value")
            for node in datasource.iterfind("./connection/cols/map")
        }
        single = datasource.find("./connection/relation[@type='table']")
        for column in datasource.iterfind("./column"):
            calculation = column.find("./calculation")
            if calculation is None:
                continue
            key = column.get("name")
            if key in maps:
                table, field = maps[key].split("].[", 1)
                ref = f"{table.lstrip('[')}.{field.rstrip(']')}"
            else:
                table = single.get("name") if single is not None else ""
                ref = f"{table}.{column.get('caption')}"
            formulas[ref] = calculation.get("formula", "")
    return formulas
