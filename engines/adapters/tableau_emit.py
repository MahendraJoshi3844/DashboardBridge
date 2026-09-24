"""Write a `.twb` from the canonical model (`P6b.1`).

Entirely new: nothing here shares code with the reader, and nothing in the
reader knows this exists.

## The trap this exists to avoid

The mirror of the parser's costliest one. Tableau does not put plain field names
on a shelf — it writes ``[federated.x].[sum:Sales:qk]`` — so a generator that
writes ``[Sales]`` produces a workbook that opens and binds every visual to
nothing. `_shelf` writes the encoding `decode_shelf_ref` reads, and a test
decodes everything this writes to check the two still agree.

## What it will not do

A **DAX** expression goes through `engines/tableau_calc` (`P6b.2`), which either
produces a Tableau calculation or refuses with a sentence. A refusal is never
written into a `formula` attribute: a workbook that opens and then fails on
every row is worse than a field that is plainly missing, because only one of the
two is visible. It is written *beside* the field as a comment instead, since
absent and silently absent are not the same thing.

A **Tableau** expression, by contrast, is written back verbatim: the canonical
model already holds the source text, and rewriting it would be a translation
nobody asked for.

## What has never happened

No Tableau Desktop has opened one of these. The phase's acceptance criterion is
unmet and cannot be met here.

The round trip that exists proves less than it appears to, and the difference is
worth stating: the reader accepts a bare `[Sales]` on a shelf, because older
workbooks write them, so a round trip passes whether or not `_shelf` produces
the encoding Desktop needs. A lenient reader cannot validate a strict writer.
The shelf encoding is therefore asserted directly by a test, and the round trip
is kept for what it does establish - that tables, columns, calculations and
worksheets survive the journey.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from dashboardbridge_contracts import (
    CanonicalModel,
    Column,
    ConversionFlag,
    Dashboard,
    Relationship,
    Table,
    Visual,
)
from dashboardbridge_contracts.enums import (
    Aggregation,
    BindingRole,
    ConversionMethod,
    ConversionStatus,
    DataType,
    Grain,
    Severity,
    Stage,
)

#: What this writer declares itself to be. Tableau refuses a workbook with no
#: version, and reads an older one forwards rather than a newer one backwards -
#: so this is deliberately not the latest.
WORKBOOK_VERSION = "18.1"

#: The canonical model's types, in Tableau's words.
_DATATYPES = {
    DataType.STRING: "string",
    DataType.INTEGER: "integer",
    DataType.DECIMAL: "real",
    DataType.BOOLEAN: "boolean",
    DataType.DATE: "date",
    DataType.DATETIME: "datetime",
    DataType.UNKNOWN: "string",
}

#: The canonical aggregations, in the prefix Tableau puts on a shelf token.
_AGGREGATIONS = {
    Aggregation.SUM: "sum",
    Aggregation.AVERAGE: "avg",
    Aggregation.MIN: "min",
    Aggregation.MAX: "max",
    Aggregation.COUNT: "cnt",
    Aggregation.COUNT_DISTINCT: "cntd",
    Aggregation.MEDIAN: "median",
    Aggregation.ATTRIBUTE: "attr",
}

#: Which shelf a role goes on. Rows carry the values and columns the categories,
#: which is the inverse of the mapping the Tableau reader applies.
_ROWS = {BindingRole.VALUE}
_COLUMNS = {BindingRole.CATEGORY}


@dataclass(frozen=True)
class TwbEmission:
    """The written workbook, and everything about it a person has to know.

    `flags` is the only place some of this is recorded. A parameter, a visual
    filter or a dashboard layout that is not written leaves nothing behind in
    the file, and a refusal that *is* written there is a comment nobody using
    the web application will open the file to read.
    """

    path: Path
    flags: list[ConversionFlag]


class _Notes:
    """What the writer did not carry, collected as it writes.

    A refusal that also goes into the file as a comment is built here first and
    the comment is written from the returned text, so the comment and the flag
    are the same sentence by construction rather than by care.
    """

    _SEVERITY = {
        ConversionStatus.CONVERTED: Severity.INFO,
        ConversionStatus.PARTIAL: Severity.WARNING,
        ConversionStatus.UNSUPPORTED: Severity.MANUAL,
    }

    def __init__(self) -> None:
        self.flags: list[ConversionFlag] = []

    def add(
        self, item: str, stage: Stage, status: ConversionStatus, reason: str
    ) -> str:
        text = _comment_text(reason)
        self.flags.append(
            ConversionFlag(
                item=item,
                stage=stage,
                method=(
                    ConversionMethod.DETERMINISTIC
                    if status is ConversionStatus.CONVERTED
                    else ConversionMethod.MANUAL
                ),
                status=status,
                severity=self._SEVERITY[status],
                reason=text,
                ref=item,
            )
        )
        return text


def write_twb(model: CanonicalModel, out_dir: str | Path) -> Path:
    """Write one `.twb`. Returns its path. See `emit_twb` for what it left out."""
    return emit_twb(model, out_dir).path


def emit_twb(model: CanonicalModel, out_dir: str | Path) -> TwbEmission:
    """Write one `.twb`, and report everything it did not carry across.

    Deterministic: the same model produces the same bytes and the same flags,
    because a person may diff two runs and a file that differs for no reason
    cannot be reviewed.
    """
    notes = _Notes()
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    name = _safe_stem(model.name or "workbook")
    path = root / f"{name}.twb"

    lines: list[str] = [
        "<?xml version='1.0' encoding='utf-8' ?>",
        f"<workbook version={quoteattr(WORKBOOK_VERSION)}>",
        "  <datasources>",
    ]
    sources = _sources(model, notes)
    for source in sources:
        lines.extend(_datasource(source, notes))
    lines.append("  </datasources>")

    lines.append("  <worksheets>")
    for visual in sorted(model.visuals or [], key=lambda visual: visual.name):
        lines.extend(_worksheet(visual, sources, notes))
    lines.append("  </worksheets>")

    by_id = {visual.id: visual for visual in model.visuals or []}
    lines.append("  <dashboards>")
    for dashboard in sorted(model.dashboards or [], key=lambda item: item.name):
        lines.extend(_dashboard(dashboard, by_id, notes))
    lines.append("  </dashboards>")
    lines.append("</workbook>")

    for parameter in sorted(model.parameters or [], key=lambda item: item.name):
        notes.add(
            parameter.caption or parameter.name,
            Stage.GENERATE,
            ConversionStatus.UNSUPPORTED,
            "This parameter was not written: the Tableau writer does not "
            "produce parameters yet. Recreate it in Tableau and point anything "
            "that used it at the new parameter.",
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return TwbEmission(
        path=path,
        flags=sorted(
            notes.flags,
            key=lambda flag: (flag.item, flag.stage.value, flag.reason),
        ),
    )


def _dashboard(
    dashboard: Dashboard, visuals: dict[str, Visual], notes: _Notes
) -> list[str]:
    """A dashboard as the list of worksheets it holds, and nothing more.

    A zone names a *worksheet*, and worksheets are named after visuals. A Power
    BI visual id (`v1`, or a hex string) is not a worksheet name, so writing the
    id produced a dashboard pointing at nothing - found in `golden/retail.twb`.
    For a Tableau source the id and the name are the same, so its output is
    unchanged.
    """
    lines = [
        f"    <dashboard name={quoteattr(dashboard.name)}>",
        "      <zones>",
    ]
    missing: list[str] = []
    for visual_id in dashboard.visual_ids:
        visual = visuals.get(visual_id)
        if visual is None:
            missing.append(visual_id)
            continue
        lines.append(f"        <zone name={quoteattr(visual.name)} />")
    lines.extend(["      </zones>", "    </dashboard>"])

    notes.add(
        dashboard.name,
        Stage.GENERATE,
        ConversionStatus.PARTIAL,
        "Only the sheets this dashboard holds are carried; its layout, sizes "
        "and positions are not. Arrange the sheets on the dashboard in Tableau.",
    )
    if missing:
        notes.add(
            dashboard.name,
            Stage.GENERATE,
            ConversionStatus.PARTIAL,
            f"It refers to {', '.join(missing)}, which is not a visual in this "
            "model, so no zone was written for it.",
        )
    return lines


# --- data sources ---------------------------------------------------------------
#
# `P6b.5`. A canonical table used to become a `<datasource>` of its own, and
# Tableau binds one worksheet to one data source - so a visual reading two
# related tables produced a worksheet naming two sources, which is a workbook
# Tableau cannot bind. Related tables now share one source.
#
# The shape is copied from a workbook Tableau itself wrote
# (`testing_content/Superstore.twb`, which relates Orders, People and Returns):
# a `<relation type='collection'>` listing the tables, a `<cols>` map from one
# flat field namespace onto `[Table].[Column]`, and an `<object-graph>` as the
# last child of the data source carrying the relationships. Nothing here is
# inferred from documentation.


@dataclass(frozen=True)
class _Source:
    """One emitted `<datasource>`, and the tables that share it.

    `keys` is the flat namespace those tables live in: Tableau addresses a field
    of a related group by one name, not by table, so two tables using the same
    column name cannot both keep it. Superstore shows the rule - `Region` stays
    `[Region]` for Orders and becomes `[Region (People)]` for People - and it is
    load-bearing in three places: the `<cols>` map, the `<column>` declarations,
    and the relationship expression, which is written in flat names.
    """

    id: str
    caption: str
    tables: tuple[Table, ...]
    keys: dict[tuple[str, str], str]
    relationships: tuple[Relationship, ...] = ()

    def key(self, table: str, column: str) -> str | None:
        return self.keys.get((table, column))

    def holds(self, table: str) -> bool:
        return any(candidate.name == table for candidate in self.tables)


def _display(column: Column) -> str:
    return column.caption or column.name


def _flat_keys(tables: tuple[Table, ...]) -> dict[tuple[str, str], str]:
    """The one namespace these tables share, in Tableau's disambiguation.

    First table to use a name keeps it; a later one is suffixed with its own
    table name, which is what Tableau writes. The numeric tail is for the case
    Tableau's rule does not settle - two tables of the same name cannot occur
    here, but a column already literally called `Region (People)` can.
    """
    keys: dict[tuple[str, str], str] = {}
    taken: set[str] = set()
    for table in tables:
        for column in table.columns or []:
            name = _display(column)
            candidate = name
            if candidate in taken:
                candidate = f"{name} ({table.name})"
            suffix = 2
            while candidate in taken:
                candidate = f"{name} ({table.name} {suffix})"
                suffix += 1
            taken.add(candidate)
            keys[(table.name, name)] = candidate
    return keys


def _components(model: CanonicalModel) -> list[tuple[Table, ...]]:
    """Tables grouped by whether the model says they are related.

    Union-find over the relationships, which is deliberately the weakest thing
    that could work: relatedness is read from the source model and never
    inferred from matching column names. A shared name is not a relationship,
    and a converter that treats it as one has invented a join.
    """
    tables = sorted(model.all_tables(), key=lambda table: table.name)
    parent = {table.name: table.name for table in tables}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for relationship in model.relationships or []:
        left, right = relationship.from_table, relationship.to_table
        if left in parent and right in parent:
            parent[find(left)] = find(right)

    grouped: dict[str, list[Table]] = {}
    for table in tables:
        grouped.setdefault(find(table.name), []).append(table)
    return sorted(
        (tuple(group) for group in grouped.values()),
        key=lambda group: group[0].name,
    )


def _sources(model: CanonicalModel, notes: _Notes) -> list[_Source]:
    sources: list[_Source] = []
    for group in _components(model):
        names = {table.name for table in group}
        stem = "_".join(_safe_stem(table.name).lower() for table in group)
        keys = _flat_keys(group)
        for (table_name, column_name), flat in sorted(keys.items()):
            if flat != column_name:
                notes.add(
                    f"{table_name}.{column_name}",
                    Stage.GENERATE,
                    ConversionStatus.CONVERTED,
                    f"Renamed to {flat} in Tableau: related tables share one "
                    f"list of field names there, and another table already "
                    f"uses {column_name}.",
                )
        sources.append(
            _Source(
                id=f"federated.{stem}",
                caption=" + ".join(table.name for table in group),
                tables=group,
                keys=keys,
                relationships=tuple(
                    relationship
                    for relationship in model.relationships or []
                    if relationship.from_table in names
                    and relationship.to_table in names
                ),
            )
        )
    return sources


def _object_id(table: Table) -> str:
    """Tableau writes `Orders_<32 hex>`; the shape is copied, the value derived.

    Tableau's own value is a random GUID, and this project's output has to be
    byte-identical across runs, so it is a digest of the table name instead.
    """
    digest = hashlib.sha1(table.name.encode("utf-8")).hexdigest()[:32]
    return f"{table.name}_{digest.upper()}"


def _relation(table: Table) -> str:
    return (
        f"<relation name={quoteattr(table.name)} "
        f"table={quoteattr('[' + table.name + ']')} type='table' />"
    )


def _datasource(source: _Source, notes: _Notes) -> list[str]:
    lines = [
        f"    <datasource caption={quoteattr(source.caption)} "
        f"inline='true' name={quoteattr(source.id)} "
        f"version={quoteattr(WORKBOOK_VERSION)}>",
        "      <connection class='federated'>",
    ]
    if len(source.tables) == 1:
        lines.append(f"        {_relation(source.tables[0])}")
    else:
        lines.append("        <relation type='collection'>")
        for table in source.tables:
            lines.append(f"          {_relation(table)}")
        lines.append("        </relation>")
        lines.append("        <cols>")
        for (table_name, column_name), flat in sorted(source.keys.items()):
            lines.append(
                f"          <map key={quoteattr('[' + flat + ']')} "
                f"value={quoteattr(f'[{table_name}].[{column_name}]')} />"
            )
        lines.append("        </cols>")
    lines.append("      </connection>")

    for table in source.tables:
        for column in table.columns or []:
            lines.extend(_column(column, table, source, notes))

    lines.extend(_object_graph(source, notes))
    lines.append("    </datasource>")
    return lines


def _object_graph(source: _Source, notes: _Notes) -> list[str]:
    """The relationships, in the form Tableau writes them.

    Omitted for a lone table: Tableau's own single-table data sources have no
    object graph, and adding one would change output that was already right.
    """
    if len(source.tables) == 1:
        return []
    lines = ["      <object-graph>", "        <objects>"]
    for table in source.tables:
        lines.extend(
            [
                f"          <object caption={quoteattr(table.name)} "
                f"id={quoteattr(_object_id(table))}>",
                "            <properties context=''>",
                f"              {_relation(table)}",
                "            </properties>",
                "          </object>",
            ]
        )
    lines.append("        </objects>")
    lines.append("        <relationships>")
    by_name = {table.name: table for table in source.tables}
    for relationship in source.relationships:
        left = source.key(relationship.from_table, relationship.from_column)
        right = source.key(relationship.to_table, relationship.to_column)
        if left is None or right is None:
            # The model relates two tables on a column one of them does not
            # have. Writing the relationship anyway is a data source Tableau
            # cannot resolve; dropping it quietly loses the only statement the
            # source made about how these tables meet.
            missing = relationship.from_column if left is None else relationship.to_column
            reason = notes.add(
                f"{relationship.from_table}.{relationship.from_column} -> "
                f"{relationship.to_table}.{relationship.to_column}",
                Stage.GENERATE,
                ConversionStatus.UNSUPPORTED,
                f"{relationship.from_table} and {relationship.to_table} are "
                f"related on {missing}, which is not a column of either "
                "table in this model, so the relationship was not written",
            )
            lines.append(f"          <!-- not carried: {reason} -->")
            continue
        lines.extend(
            [
                "          <relationship>",
                "            <expression op='='>",
                f"              <expression op={quoteattr('[' + left + ']')} />",
                f"              <expression op={quoteattr('[' + right + ']')} />",
                "            </expression>",
                "            <first-end-point object-id="
                f"{quoteattr(_object_id(by_name[relationship.from_table]))} />",
                "            <second-end-point object-id="
                f"{quoteattr(_object_id(by_name[relationship.to_table]))} />",
                "          </relationship>",
            ]
        )
    lines.append("        </relationships>")
    lines.append("      </object-graph>")
    return lines


def _column(
    column: Column, table: Table, source: _Source, notes: _Notes | None = None
) -> list[str]:
    notes = notes if notes is not None else _Notes()
    name = _display(column)
    key = source.key(table.name, name) or name
    datatype, role = _role(column)
    if column.grain is Grain.AGGREGATE and column.datatype is DataType.UNKNOWN:
        notes.add(
            f"{table.name}.{name}",
            Stage.GENERATE,
            ConversionStatus.CONVERTED,
            "Written as a real number: Power BI records no data type for a "
            "measure and Tableau requires one. Change it in Tableau if the "
            "measure is not numeric.",
        )
    attributes = (
        f"caption={quoteattr(name)} datatype={quoteattr(datatype)} "
        f"name={quoteattr('[' + key + ']')} role={quoteattr(role)} "
        f"type={quoteattr('quantitative' if role == 'measure' else 'nominal')}"
    )

    formula, refusal = _tableau_formula(column, table)
    if formula is not None:
        formula = _in_flat_names(formula, table, source)
    if formula is None:
        if refusal is None:
            return [f"      <column {attributes} />"]
        reason = notes.add(
            f"{table.name}.{name}",
            Stage.TRANSLATE,
            ConversionStatus.UNSUPPORTED,
            refusal,
        )
        return [
            f"      <column {attributes} />",
            f"      <!-- not carried: {reason} -->",
        ]
    return [
        f"      <column {attributes}>",
        f"        <calculation class='tableau' formula={quoteattr(formula)} />",
        "      </column>",
    ]


#: A bracketed field reference in a Tableau formula. Tableau has no escape for
#: `]` inside one, so a name containing a bracket cannot be referenced at all -
#: which is why the character class is simply "not a bracket".
_FIELD_REFERENCE = re.compile(r"\[([^\[\]]+)\]")


def _in_flat_names(formula: str, table: Table, source: _Source) -> str:
    """Rewrite a formula's field references into the shared flat namespace.

    Only reached when tables were merged, and necessary exactly then. A formula
    on `Store` saying `[Store Key]` means *this table's* `Store Key`; once
    `Sales` is in the same data source and holds the plain name, `[Store Key]`
    means the other table's column. Left alone, the workbook opens and the
    number is quietly wrong, which is the most expensive kind of failure this
    project has.

    A reference this table does not have is left untouched. Every producer of
    these formulas refuses a cross-table reference already (`ADR-005`: a Tableau
    calculation has no table qualifier), so such a token is either a function
    argument that only looks like a field or something no rewriting here can
    make correct.
    """
    if len(source.tables) == 1:
        return formula

    def replace(match: re.Match[str]) -> str:
        flat = source.key(table.name, match.group(1))
        return f"[{flat}]" if flat else match.group(0)

    return _FIELD_REFERENCE.sub(replace, formula)


def _role(column: Column) -> tuple[str, str]:
    """The Tableau datatype and role for a column. Grain first, datatype after.

    **Grain is recorded; role was being guessed.** An aggregate written as a
    nominal string dimension contradicts the formula beside it - Tableau would
    offer `SUM([Revenue])` as a discrete field to slice by, which is not a thing
    it can be. `Column.grain` is the one fact the model states about this, so it
    decides, and the datatype heuristic is only consulted when it says nothing.

    **One assumption is made here and is named rather than hidden.** TMDL gives
    a measure no dataType - Power BI infers it from the expression - so an
    aggregate arrives with `UNKNOWN`, and Tableau requires a datatype. Writing
    `string` is as much a claim as writing `real`, and a worse one, because it
    contradicts the measure role on the same column. So `real` is written. It is
    unverified against Tableau Desktop, like everything else in this direction.

    For a row-level column, numeric becomes a measure and everything else a
    dimension: that is Tableau's own default when it connects to a table, and
    matching the target tool's behaviour is not a guess about the source.
    """
    datatype = _DATATYPES.get(column.datatype, "string")
    if column.grain is Grain.AGGREGATE:
        if column.datatype is DataType.UNKNOWN:
            datatype = "real"
        return datatype, "measure"
    return datatype, "measure" if datatype in {"real", "integer"} else "dimension"


def _tableau_formula(column: Column, table: Table) -> tuple[str | None, str | None]:
    """The Tableau formula for a calculated field, and why there is not one.

    A **Tableau** expression is written back verbatim: the canonical model
    already holds the source text, and rewriting it would be a translation
    nobody asked for.

    A **DAX** expression goes through `P6b.2`, which either produces a Tableau
    calculation or refuses with a sentence. A refusal is not written into a
    `formula` attribute under any circumstances - that would produce a workbook
    which opens and then fails on every row, and a field that is plainly missing
    is the more honest failure. It is written next to the field as a comment
    instead, because absent and *silently* absent are not the same thing.
    """
    expression = column.expression
    if expression is None:
        return None, None
    if expression.source_language == "tableau_calc":
        return expression.source_text, None
    if expression.source_language != "dax":
        return None, (
            f"the expression is written in {expression.source_language}, which "
            "nothing here can read"
        )

    from engines.tableau_calc import translate_dax  # noqa: PLC0415

    result = translate_dax(expression.source_text, table=table.name)
    if result.formula is None:
        return None, result.reason
    return result.formula, None


def _comment_text(reason: str) -> str:
    """A reason, safe to put inside an XML comment.

    A comment cannot contain a double hyphen and cannot end with one, and a
    sentence written for a person very well may - so the writer handles it here
    rather than every reason being written to remember.
    """
    cleaned = " ".join(reason.split()).replace("--", "-")
    return cleaned.rstrip("-").strip()


# --- worksheets ----------------------------------------------------------------


def _worksheet(visual: Visual, sources: list[_Source], notes: _Notes) -> list[str]:
    placed = [
        binding
        for binding in visual.bindings or []
        if binding.role in _ROWS | _COLUMNS and binding.resolvable and binding.field
    ]
    owners = {
        source.id
        for binding in placed
        if (source := _owner(binding, sources)) is not None
    }

    refusal: str | None = None
    if len(owners) > 1:
        # `P6b.5`. Tableau binds a worksheet to one data source, so there is no
        # correct form for this - and the two forms that would produce a file
        # both add a claim the model never made: a join imposes inner or outer
        # semantics, a blend invents a linking field. Refusing is the same
        # choice the Power BI direction makes for a visual it cannot bind.
        # Named by data source rather than by `field.table`, which a binding
        # read from a Tableau shelf may not carry at all - and the sources are
        # what the sentence is actually about.
        spanned = sorted(
            source.caption for source in sources if source.id in owners
        )
        refusal = (
            f"this worksheet reads {' and '.join(spanned)}, which are not "
            "related in the source model, and Tableau binds one worksheet to "
            "one data source. Relate the tables and convert again, or rebuild "
            "the worksheet by hand"
        )
        refusal = notes.add(
            visual.name, Stage.GENERATE, ConversionStatus.UNSUPPORTED, refusal
        )
        placed = []
    else:
        _report_unplaced(visual, sources, notes)

    if visual.filters:
        notes.add(
            visual.name,
            Stage.GENERATE,
            ConversionStatus.PARTIAL,
            f"Its filters on {_field_list(visual.filters)} were not written. "
            "Add them to the worksheet's Filters shelf in Tableau.",
        )
    if visual.visual_type not in _MARKS:
        notes.add(
            visual.name,
            Stage.GENERATE,
            ConversionStatus.PARTIAL,
            f"No Tableau mark is mapped for the {visual.visual_type} visual, so "
            "the worksheet uses Tableau's Automatic mark. Choose the mark in "
            "Tableau.",
        )

    rows = [
        _shelf(binding, sources) for binding in placed if binding.role in _ROWS
    ]
    columns = [
        _shelf(binding, sources) for binding in placed if binding.role in _COLUMNS
    ]
    return [
        f"    <worksheet name={quoteattr(visual.name)}>",
        *([f"      <!-- not carried: {refusal} -->"] if refusal else []),
        "      <table>",
        "        <view />",
        f"        <rows>{escape(' + '.join(filter(None, rows)))}</rows>",
        f"        <cols>{escape(' + '.join(filter(None, columns)))}</cols>",
        "        <panes>",
        "          <pane>",
        f"            <mark class={quoteattr(_mark(visual.visual_type))} />",
        "          </pane>",
        "        </panes>",
        "      </table>",
        "    </worksheet>",
    ]


def _report_unplaced(visual: Visual, sources: list[_Source], notes: _Notes) -> None:
    """Every field on the visual that did not reach a shelf, named once.

    The writer places row and column fields only. A field in any other well, a
    binding the reader could not resolve, and a field whose table is in no data
    source used to vanish from the worksheet with nothing said.
    """
    unplaced: list[str] = []
    for binding in visual.bindings or []:
        label = binding.field.column if binding.field else (binding.raw or "a field")
        if binding.role not in _ROWS | _COLUMNS:
            unplaced.append(f"{label} ({binding.role.value})")
        elif not binding.resolvable or binding.field is None:
            unplaced.append(f"{label} (could not be resolved)")
        elif _owner(binding, sources) is None:
            unplaced.append(f"{label} (its table is not in this workbook)")
    if unplaced:
        notes.add(
            visual.name,
            Stage.GENERATE,
            ConversionStatus.PARTIAL,
            f"Not placed on the worksheet: {', '.join(unplaced)}. Only row and "
            "column fields are written; add the rest in Tableau.",
        )


def _field_list(bindings) -> str:
    names = sorted(
        {binding.field.column if binding.field else binding.raw for binding in bindings}
    )
    return ", ".join(name for name in names if name) or "fields"


def _owner(binding, sources: list[_Source]) -> _Source | None:
    """The data source a binding's field lives in.

    Falls back to searching by column name for a field whose table the model
    does not name, which is the same leniency the single-source writer had:
    a binding that cannot be placed is dropped rather than qualified with a
    guessed source.
    """
    field = binding.field
    for source in sources:
        if source.holds(field.table) and source.key(field.table, field.column):
            return source
    for source in sources:
        if any(_has(table, field.column) for table in source.tables):
            return source
    return None


def _shelf(binding, sources: list[_Source]) -> str:
    """`[datasource].[prefix:Field:kind]` — the encoding Tableau actually uses.

    `none` is the prefix for an unaggregated field, and `qk`/`nk` distinguish a
    quantitative from a nominal one. Writing a plain `[Field]` here is the
    single most expensive mistake available in this direction: the workbook
    opens, and every visual is bound to nothing.
    """
    field = binding.field
    owner = _owner(binding, sources)
    if owner is None:
        return ""
    # The flat key, not the column name: in a source holding related tables the
    # two differ exactly where two tables share a name, and the shelf must say
    # what `<cols>` says.
    key = owner.key(field.table, field.column) or next(
        (
            owner.key(table.name, field.column)
            for table in owner.tables
            if _has(table, field.column)
        ),
        field.column,
    )

    prefix = _AGGREGATIONS.get(binding.aggregation) if binding.aggregation else None
    if prefix is None:
        prefix = (
            binding.date_part.value
            if binding.date_part
            else ("sum" if binding.role is BindingRole.VALUE else "none")
        )
    kind = "qk" if binding.role is BindingRole.VALUE else "nk"
    return f"[{owner.id}].[{prefix}:{key}:{kind}]"


def _has(table: Table, column_name: str) -> bool:
    return any(
        (column.caption or column.name) == column_name for column in table.columns or []
    )


#: Canonical visual types, in Tableau's mark classes. Anything unrecognised
#: becomes `Automatic`, which is what Tableau itself writes when it has not been
#: told - an honest "no opinion" rather than a guessed shape.
_MARKS = {
    "bar": "Bar",
    "clusteredBarChart": "Bar",
    "columnChart": "Bar",
    "line": "Line",
    "lineChart": "Line",
    "area": "Area",
    "areaChart": "Area",
    "scatter": "Circle",
    "scatterChart": "Circle",
    "pie": "Pie",
    "pieChart": "Pie",
    "table": "Automatic",
    "tableEx": "Automatic",
}


def _mark(visual_type: str) -> str:
    return _MARKS.get(visual_type, "Automatic")


def _safe_stem(name: str) -> str:
    """A file and identifier stem from a name that came out of someone's file.

    Never used to build a path outside `out_dir`, and never trusted to be one:
    the same rule `emit/paths.py` follows on the other side.
    """
    cleaned = "".join(
        character if character.isalnum() or character in " -_" else "_"
        for character in name
    ).strip()
    return cleaned or "workbook"
