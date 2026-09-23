"""Pipeline orchestration. THE ONLY module that knows the stage order.

Extract -> Parse -> Translate(DAX) -> Generate(PBIP) -> Report.
See docs/specs/modules/pipeline.md.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# Stage labels shown by the desktop pipeline tracer (this module owns stage order).
STAGES: tuple[str, ...] = ("Extract", "Parse", "Map", "Translate", "Generate", "Report")

from engines.t2pbi.core.dax import translate_formula
from engines.t2pbi.core.dax.grain import classify_calc
from engines.t2pbi.core.graph import build as build_graph
from engines.t2pbi.core.dax.translator import TranslationContext
from engines.t2pbi.core.emit import write_pbip
from engines.t2pbi.core.emit.params import value_measure_name
from engines.t2pbi.core.extract import extract
from engines.t2pbi.core.mapping import map_visuals
from engines.t2pbi.core.parse import parse_workbook
from engines.t2pbi.events import CROSSED, HELD, EventSink, Timeline
from engines.t2pbi.ir import Severity, Workbook
from engines.t2pbi.report import compute_stats, write_report


@dataclass
class ConvertResult:
    pbip_path: Path
    report_path: Path
    stats: dict[str, int]
    workbook: Workbook
    timeline: Timeline = field(default_factory=Timeline)


def _param_aliases(wb: Workbook) -> set[str]:
    aliases: set[str] = set()
    for p in wb.parameters:
        aliases.add(p.name.lower())
        aliases.add(p.caption.lower())
    return aliases


def _classify_calculations(wb: Workbook) -> None:
    """Decide measure vs calculated column for every calc, before translating.

    A calc's grain depends on the grain of the calcs it references, so this
    iterates to a fixpoint. Calcs whose grain is ambiguous keep grain "row" and
    are refused during translation.
    """
    params = _param_aliases(wb)
    calcs = [c for t in wb.all_tables() for c in t.columns if c.is_calculated]

    grains: dict[str, str] = {}
    for _ in range(len(calcs) + 1):
        changed = False
        for col in calcs:
            verdict = classify_calc(col.formula or "", grains, params)
            if verdict.grain is None:
                continue
            for alias in (col.name.lower(), col.display_name.lower()):
                if grains.get(alias) != verdict.grain:
                    grains[alias] = verdict.grain
                    changed = True
            col.grain = verdict.grain
        if not changed:
            break


def _build_context(wb: Workbook) -> TranslationContext:
    """Index columns, measures, and parameters so references resolve to valid DAX."""
    field_to_table: dict[str, str] = {}
    columns_by_table: dict[str, set[str]] = {}
    column_display: dict[str, str] = {}
    measures: dict[str, str] = {}
    for table in wb.all_tables():
        local = columns_by_table.setdefault(table.name, set())
        for col in table.columns:
            if col.is_aggregate:
                measures[col.display_name.lower()] = col.display_name
                measures[col.name.lower()] = col.display_name
            else:
                # Physical columns and calculated columns both live in a table, so
                # both resolve to 'Table'[Column] rather than a bare measure ref.
                for key in (col.name.lower(), col.display_name.lower()):
                    field_to_table.setdefault(key, table.name)
                    column_display.setdefault(key, col.display_name)
                    local.add(key)

    param_value_measures: dict[str, str] = {}
    for p in wb.parameters:
        vm = value_measure_name(p)
        param_value_measures[p.name.lower()] = vm
        param_value_measures[p.caption.lower()] = vm

    # Parameters take precedence over any same-named column when resolving refs.
    for key in param_value_measures:
        field_to_table.pop(key, None)
        measures.pop(key, None)

    return TranslationContext(
        field_to_table=field_to_table,
        columns_by_table=columns_by_table,
        column_display=column_display,
        measures=measures,
        param_value_measures=param_value_measures,
    )


def _translate_calculations(
    wb: Workbook, accepted: dict[str, tuple[str, str]] | None = None
) -> None:
    """Stage 4: fill col.dax for supported calcs; flag the rest MANUAL. No guesses.

    Runs in dependency order over the graph (`P3.2`), so a calculation is only
    attempted once everything it reads has been decided. That makes refusal
    propagation a fact the loop already knows rather than a text search over the
    DAX afterwards - which is what used to refuse `sum([Profit])/sum([Sales])`
    because an unrelated table held a refused calculation called `Sales`.
    """
    _classify_calculations(wb)
    ctx = _build_context(wb)
    params = _param_aliases(wb)
    graph, scope = build_graph(wb)
    calcs = {
        f"{table.name}.{col.display_name}": (table, col)
        for table in wb.all_tables()
        for col in table.columns
        if col.is_calculated
    }

    def refuse(key: str, reason: str) -> None:
        wb.add_flag(
            item=key,
            severity=Severity.MANUAL,
            reason=f"Calculated field not auto-converted: {reason}",
            stage="translate",
        )

    ordered, cycled = graph.order()
    refused: set[str] = set()
    # Expressions a person accepted from a model (`P4.6`). Applied here rather
    # than written over the output afterwards, so everything downstream - the
    # dependency order, the refusal propagation, the dangling-reference
    # backstop - sees the same model a deterministic run would have seen.
    accepted = accepted or {}

    for key in cycled:
        # Each member needs another member translated first, so there is no
        # order in which any of them can be attempted. Saying so is better than
        # picking one arbitrarily and emitting DAX that references itself.
        refuse(
            key,
            "it refers to itself through a chain of calculations "
            f"({', '.join(sorted(graph.edges[key]))}), so there is no order in "
            "which it can be built.",
        )
        refused.add(key)

    for key in ordered:
        table, col = calcs[key]

        override = accepted.get(key)
        if override:
            dax, proposal_id = override
            # A person read this and accepted it. It is not re-derived and not
            # re-checked against the grain rules: those describe what the
            # converter is willing to write by itself, and this is not that.
            col.dax = dax
            col.dax_rule_ids = []
            col.dax_proposal_id = proposal_id
            continue

        blocking = sorted(graph.edges[key] & refused)
        if blocking:
            refuse(
                key,
                f"depends on {', '.join(_short(name) for name in blocking)}, "
                "which could not be converted.",
            )
            refused.add(key)
            continue

        # Refuse before translating when the grain itself is ambiguous:
        # emitting an aggregation the author never wrote would be a guess.
        verdict = classify_calc(
            col.formula or "", _grains_from(table.name, scope, calcs), params
        )
        if verdict.grain is None:
            refuse(key, verdict.reason or "the grain could not be determined.")
            refused.add(key)
            continue

        result = translate_formula(col.formula or "", table.name, ctx)
        if result.dax is not None:
            col.dax = result.dax
            col.dax_rule_ids = list(result.rule_ids)
        else:
            refuse(key, result.reason or "it could not be converted.")
            refused.add(key)

    _refuse_dangling_references(wb)


def _short(key: str) -> str:
    """`"Table.Name"` -> `"Name"`. The reason names the field, not its address."""
    _, _, name = key.rpartition(".")
    return name or key


def _grains_from(table_name: str, scope, calcs: dict) -> dict[str, str]:
    """Calculation grains **as seen from one table**.

    A global name->grain map is what made grain classification report "cannot
    aggregate 'Sales': it converts to a measure" about a physical column that
    merely shares a name with a calculation somewhere else. A name only carries
    a calculation's grain here if it resolves, from this table, to that
    calculation.
    """
    grains: dict[str, str] = {}
    for key, (table, col) in calcs.items():
        for alias in (col.name.lower(), col.display_name.lower()):
            if not alias or alias in grains:
                continue
            target = scope.resolve(alias, table_name)
            if target is not None and target.is_calculated and target.key == key:
                grains[alias] = col.grain
    return grains


#: An unqualified DAX measure reference. A column is always written
#: `'Table'[Name]`, so the closing quote before the bracket is what tells the
#: two apart - and telling them apart is the whole point: `[Sales]` inside
#: `'Orders'[Sales]` is a column of Orders, not a measure that happens to share
#: the name with a refused calculation in some other table.
_MEASURE_REF_RE = re.compile(r"(?<!')\[([^\[\]]+)\]")


def _refuse_dangling_references(wb: Workbook) -> None:
    """Backstop: drop any calc whose DAX *names a measure* that was not emitted.

    The dependency graph is the authority on what depends on what, and
    `_translate_calculations` has already refused everything downstream of a
    refusal. This exists for the case where the translator emits a reference the
    graph did not predict: a measure pointing at a field that was never written
    is broken DAX that fails only when someone opens the model, which is exactly
    the surprise this product exists to prevent.

    Iterates because refusing one calc can orphan another.
    """
    calcs = [
        (table, col)
        for table in wb.all_tables()
        for col in table.columns
        if col.is_calculated
    ]

    def measures_named(dax: str) -> set[str]:
        return {match.group(1) for match in _MEASURE_REF_RE.finditer(dax)}

    while True:
        missing = {c.display_name for _, c in calcs if c.dax is None}
        if not missing:
            return
        orphaned = [
            (t, c, broken)
            for t, c in calcs
            if c.dax is not None
            and (broken := sorted(missing & measures_named(c.dax)))
        ]
        if not orphaned:
            return
        for table, col, broken in orphaned:
            col.dax = None
            wb.add_flag(
                item=f"{table.name}.{col.display_name}",
                severity=Severity.MANUAL,
                reason=(
                    "Calculated field not auto-converted: depends on "
                    f"{', '.join(broken)}, which could not be converted."
                ),
                stage="translate",
            )


def _record_parse(wb: Workbook, sink: EventSink) -> None:
    """Account for everything Parse found. Derived from the IR, so no stage
    needs to know the sink exists and nothing is double-counted."""
    for ds in wb.datasources:
        for table in ds.tables:
            sink.emit("Parse", "table", table.name, CROSSED, ds.name, table.name)
            for col in table.columns:
                if col.is_calculated:
                    continue  # accounted for in Translate, where its fate is known
                sink.emit(
                    "Parse", "column", col.display_name, CROSSED,
                    col.datatype, f"{table.name}.{col.display_name}",
                )
    for param in wb.parameters:
        sink.emit(
            "Parse", "parameter", param.display_name, CROSSED, param.kind,
            param.display_name,
        )
    for rel in wb.relationships:
        sink.emit(
            "Parse", "relationship", f"{rel.from_table} - {rel.to_table}", CROSSED,
            rel.kind, rel.from_table,
        )


def _record_translation(wb: Workbook, sink: EventSink) -> None:
    """Account for every calculated field, crossed or held, with its reason."""
    held_reasons = {
        f.item: f.reason.replace("Calculated field not auto-converted: ", "")
        for f in wb.flags
        if f.stage == "translate"
    }
    for table in wb.all_tables():
        for col in table.columns:
            if not col.is_calculated:
                continue
            ref = f"{table.name}.{col.display_name}"
            if col.dax:
                sink.emit(
                    "Translate", "calc", col.display_name, CROSSED, col.grain, ref,
                    source=col.formula or "", result=col.dax,
                )
            else:
                sink.emit(
                    "Translate", "calc", col.display_name, HELD,
                    held_reasons.get(ref, "Could not be converted safely."), ref,
                    source=col.formula or "",
                )


def _record_mapping(wb: Workbook, visuals, sink: EventSink) -> None:
    """Account for every worksheet, and for each field well we could not bind.

    Held items are emitted next to the worksheet they came from rather than in a
    block at the end, so the recording reflects the order the work happened in.
    """
    held_by_sheet: dict[str, list] = {}
    for flag in wb.flags:
        if flag.stage != "visual_map" or flag.severity != Severity.MANUAL:
            continue
        sheet = flag.item.split(":", 1)[0].strip()
        held_by_sheet.setdefault(sheet, []).append(flag)

    def emit_held(flag) -> None:
        # flag.item reads "Sheet: field, field"; the short field part is the
        # readable name, and the full item stays as the drill-down reference.
        _, _, field = flag.item.partition(":")
        sink.emit(
            "Map", "visual", (field.strip() or flag.item), HELD, flag.reason, flag.item
        )

    seen: set[str] = set()
    for visual in visuals:
        sink.emit(
            "Map", "visual", visual.name, CROSSED, visual.visual_type, visual.name
        )
        seen.add(visual.name)
        for flag in held_by_sheet.get(visual.name, ()):
            emit_held(flag)

    # Anything whose sheet we never emitted (e.g. dashboards) still gets reported.
    for sheet, flags in held_by_sheet.items():
        if sheet in seen:
            continue
        for flag in flags:
            emit_held(flag)


def run(
    input_path: str | Path,
    out_dir: str | Path,
    project_name: str | None = None,
    progress_cb: Callable[[str, int], None] | None = None,
    sink: EventSink | None = None,
    accepted: dict[str, tuple[str, str]] | None = None,
) -> ConvertResult:
    input_path = Path(input_path)
    out_dir = Path(out_dir)
    name = project_name or input_path.stem
    sink = sink if sink is not None else EventSink()

    def stage(index: int, label: str) -> None:
        if progress_cb is not None:
            # Report stage start as a percentage across the fixed stage list.
            progress_cb(label, round(index / len(STAGES) * 100))

    # 1. Extract
    stage(0, "Extract")
    extracted = extract(input_path)
    # 2. Parse
    stage(1, "Parse")
    wb = parse_workbook(extracted.twb_bytes)
    _record_parse(wb, sink)
    # 3. Map worksheets to Power BI visuals
    stage(2, "Map")
    visuals = map_visuals(wb)
    _record_mapping(wb, visuals, sink)
    # 4. Translate calculations
    stage(3, "Translate")
    _translate_calculations(wb, accepted)
    _record_translation(wb, sink)
    # 5. Generate PBIP
    stage(4, "Generate")
    pbip_path = write_pbip(wb, out_dir, name, visuals)
    # 6. Report
    stage(5, "Report")
    report_path = write_report(wb, out_dir)
    if progress_cb is not None:
        progress_cb("Done", 100)

    return ConvertResult(
        pbip_path=pbip_path,
        report_path=report_path,
        stats=compute_stats(wb),
        workbook=wb,
        timeline=sink.timeline(),
    )
