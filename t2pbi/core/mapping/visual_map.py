"""Map Tableau worksheets to Power BI visuals (type + field wells).

See docs/specs/modules/visual.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from t2pbi.ir import CATEGORY, Severity, VALUE, VisualBinding, Workbook

# Normalized Tableau visual_type -> Power BI visualType.
_VISUAL_TYPE_MAP = {
    "bar": "clusteredBarChart",
    "line": "lineChart",
    "area": "areaChart",
    "pie": "pieChart",
    "scatter": "scatterChart",
    "table": "tableEx",
    "kpi": "card",
    "unknown": "tableEx",
}


@dataclass
class FieldRef:
    table: str
    column: str


#: Tableau's marker for "the blank value" in a member list. It is an encoding,
#: not data: printing it in a report shows a consultant the source tool's
#: internals, and quoting it into Power BI would filter for the seven-character
#: string "%null%" instead of for blanks.
NULL_MEMBER = "%null%"


@dataclass
class PBIFilter:
    """One Tableau filter that survives the crossing intact.

    Only filters that can be written *exactly* get here. A filter this converter
    cannot type - a date member list, a range over an aggregate, a member of a
    calculated field that did not translate - is not approximated; it keeps its
    `MANUAL` flag and the person doing the migration is told what it was.

    `values` are Tableau's member strings, still encoded (`NULL_MEMBER`
    included). Turning them into Power BI literals is the emitter's job, because
    the encoding is Power BI's (`'text'`, `123L`, `null`) and format knowledge
    lives in `core/emit`.
    """

    field: FieldRef
    values: tuple[str, ...]
    #: True when `values` are removed rather than kept - Tableau's `except`.
    excludes: bool = False


@dataclass
class PBIVisual:
    name: str  # source worksheet name
    visual_type: str  # Power BI visualType
    category: list[FieldRef] = field(default_factory=list)
    values: list[FieldRef] = field(default_factory=list)
    legend: list[FieldRef] = field(default_factory=list)
    #: The worksheet's filters that could be carried across, in shelf order.
    filters: list[PBIFilter] = field(default_factory=list)

    def unwritable_because(self) -> str | None:
        """Why this cannot be written as a visual, or `None` if it can.

        Asked here rather than in the emitter so that the flag and the file
        cannot disagree: the stage that reports "a visual was generated" and the
        stage that writes it read the same answer. They disagreed before -
        five of Superstore's worksheets were reported as generated visuals and
        written as containers with no field on them at all.

        Two reasons, and both are refusals rather than failures:

        * **Nothing bound.** Every field on the worksheet is a Tableau construct
          with no column behind it - `Measure Names`, `Multiple Values` - so
          there is no projection to put in any well. Each of those is already
          its own `MANUAL` flag; writing an empty container on top of them adds
          a claim, not information.
        * **A scatter with no X.** Power BI's scatter needs X and Y. This
          converter fills `Category` and `Y`, never `X`, so it cannot produce
          one - and choosing which measure belongs on X is the guess it refuses
          to make everywhere else.
        """
        if not (self.category or self.values or self.legend):
            return (
                "No field on this worksheet could be bound to a Power BI field "
                "well, so no visual was written. The page is here and empty; "
                "the fields are listed above with what stopped each one."
            )
        if self.visual_type == "scatterChart":
            return (
                "A Power BI scatter needs an X and a Y measure, and this "
                "worksheet gives one measure and a category. Choosing which "
                "measure goes on X would be a guess, so no visual was written."
            )
        return None


def _field_index(wb: Workbook) -> dict[tuple[str | None, str], str]:
    """Map (datasource id, field name) -> owning table name.

    Every field is also indexed under a ``None`` datasource so shelves that carry
    no qualifier still resolve. Scoping by datasource is what keeps a field name
    that exists in two sources (e.g. 'Sales') from binding to the wrong table.
    """
    index: dict[tuple[str | None, str], str] = {}
    for ds in wb.datasources:
        for table in ds.tables:
            for col in table.columns:
                for key in (col.name, col.caption):
                    if not key:
                        continue
                    index[(ds.source_id, key)] = index.get(
                        (ds.source_id, key), table.name
                    )
                    index.setdefault((None, key), table.name)
    return index


def _column_index(wb: Workbook):
    """Map (datasource id, field name) -> the `Column` itself.

    `_field_index` answers "which table", which is all a projection needs. A
    filter needs more: its members have to be encoded as Power BI literals, and
    the encoding depends on the column's type. Without the column there is no
    honest way to write `'East'` rather than `East`, `123L` or `null`.
    """
    index = {}
    for ds in wb.datasources:
        for table in ds.tables:
            for col in table.columns:
                for key in (col.name, col.caption):
                    if key:
                        index.setdefault((ds.source_id, key), col)
                        index.setdefault((None, key), col)
    return index


def _carry_over(filter_, tables, columns) -> PBIFilter | None:
    """The filter as a Power BI filter, or `None` if it cannot be written exactly.

    Deliberately narrow. Every "no" here is a filter the migration report still
    reports as manual work, with its values named - which is a worse outcome for
    the user than converting it and a far better one than converting it wrong.

    * **Member lists only.** A range filter in Tableau is nearly always over an
      aggregate (`sum:Profit`), and Power BI cannot filter an aggregate that has
      no measure behind it. This converter does not invent the measure.
    * **Text columns only.** Power BI literals are typed - `'East'`, `123L`,
      `datetime'2016-01-01T00:00:00'` - and Tableau writes a date member as
      `#2016-01-01#` with no timezone and no statement of whether it is a date
      or a datetime. Re-typing that is a guess.
    * **Columns that will exist.** A filter naming a column the emitted model
      does not have is not a degraded report; it is one that will not resolve.
      So a calculated field whose DAX was refused is refused here too, and an
      aggregate-grain calc is excluded because it becomes a measure.
    """
    if not (filter_.restricts and filter_.members and filter_.resolvable):
        return None
    table = tables.get((filter_.datasource, filter_.field)) or tables.get(
        (None, filter_.field)
    )
    column = columns.get((filter_.datasource, filter_.field)) or columns.get(
        (None, filter_.field)
    )
    if table is None or column is None:
        return None
    if column.datatype != "string":
        return None
    if column.is_calculated and (not column.dax or column.is_aggregate):
        return None
    return PBIFilter(
        field=FieldRef(table=table, column=filter_.field),
        values=filter_.members,
        excludes=filter_.excludes,
    )


def map_visuals(wb: Workbook) -> list[PBIVisual]:
    index = _field_index(wb)
    columns = _column_index(wb)
    visuals: list[PBIVisual] = []

    def resolve(sheet: str, refs: list[VisualBinding]) -> list[FieldRef]:
        """Bind shelf refs to real columns. A ref we cannot bind is flagged, not guessed."""
        bound: list[FieldRef] = []
        for ref in refs:
            if not ref.resolvable:
                wb.add_flag(
                    item=f"{sheet}: {ref.field}",
                    severity=Severity.MANUAL,
                    reason=(
                        f"Shelf field '{ref.field}' is a Tableau construct with no "
                        "direct column equivalent; add this field well by hand."
                    ),
                    stage="visual_map",
                )
                continue
            # Prefer the datasource the shelf named; fall back to a global match.
            table = index.get((ref.datasource, ref.field)) or index.get(
                (None, ref.field)
            )
            if table is None:
                wb.add_flag(
                    item=f"{sheet}: {ref.field}",
                    severity=Severity.MANUAL,
                    reason=(
                        f"Shelf field '{ref.field}' matches no column in the model; "
                        "left unbound rather than pointed at a guessed table."
                    ),
                    stage="visual_map",
                )
                continue
            bound.append(FieldRef(table=table, column=ref.field))
        return bound

    for ws in wb.worksheets:
        vtype = _VISUAL_TYPE_MAP.get(ws.visual_type, "tableEx")
        visual = PBIVisual(
            name=ws.name,
            visual_type=vtype,
            category=resolve(ws.name, ws.placed(CATEGORY)),
            values=resolve(ws.name, ws.placed(VALUE)),
            # Deliberately empty. Colour is now *read* (`P2.2`) and reported
            # below; binding it to a legend well is a mapping decision that
            # needs its own evidence, and a well filled on a guess is the
            # visual this project refuses to emit.
            legend=[],
        )
        visuals.append(visual)
        for binding in ws.bindings:
            if binding.role in (CATEGORY, VALUE):
                continue
            wb.add_flag(
                item=f"{ws.name}: {binding.field}",
                severity=Severity.MANUAL,
                reason=(
                    f"Placed on the {binding.role} of this worksheet, which has "
                    "no Power BI field well this converter will bind on its own. "
                    "Add it by hand once you have decided where it belongs."
                ),
                stage="visual_map",
            )
        # "Visual generated as X" said a chart existed. For a worksheet nothing
        # bound to, that was false, and Power BI refused to render the report it
        # appeared in. The two outcomes now say which one happened.
        unwritable = visual.unwritable_because()
        wb.add_flag(
            item=ws.name,
            severity=Severity.MANUAL if unwritable else Severity.INFO,
            reason=(
                unwritable
                or f"Visual generated as '{vtype}' — verify layout in Power BI Desktop."
            ),
            stage="visual_map",
        )
        # One flag per filter, not one flag listing them all. A field name can
        # contain both a comma and a colon - "Tooltip (Country/Region,State
        # /Province)" on a sheet called "Tooltip: Profit Ratio by City" - so a
        # joined item cannot be decomposed back into the objects it names, and
        # anything downstream that has to ask "was this particular filter
        # reported?" has to guess. Nothing is silently dropped is a promise
        # about each object, so each object gets its own flag.
        for filter_ in ws.filters:
            carried = _carry_over(filter_, index, columns)
            if carried is not None:
                visual.filters.append(carried)
            wb.add_flag(
                item=f"{ws.name}: {filter_.field}",
                severity=(
                    Severity.MANUAL
                    if filter_.restricts and carried is None
                    else Severity.INFO
                ),
                reason=_filter_reason(filter_, carried is not None),
                stage="visual_map",
            )

    _flag_dashboards(wb)
    return visuals


def _readable(members: tuple[str, ...]) -> str:
    """The member list as a person would read it.

    `%null%` is Tableau's encoding of the blank value, not a value anyone typed.
    Printed as-is it looks like data and is not - the same failure `_member_value`
    fixes for shelf references.
    """
    shown = ", ".join(
        "(blank)" if m == NULL_MEMBER else m for m in members[:6]
    )
    if len(members) > 6:
        shown += f" and {len(members) - 6} more"
    return shown


def _filter_reason(filter_, carried: bool = False) -> str:
    """What to say about one filter, sized to what it actually does.

    Every filter used to get the same sentence and the same `MANUAL` weight:
    "recreate it as a Power BI visual, page, or report-level filter". On
    Superstore that was 83 items of work, of which about 18 restrict anything -
    the rest are filter shelf entries with every value selected.

    Over-claiming the work left is the same failure as over-claiming the work
    done, and it costs more than it looks: a person who checks six items, finds
    all six are nothing, stops reading - and the ones that change what the
    report shows are further down the list they abandoned.

    So a filter that removes nothing is still reported, because nothing is ever
    silently dropped, but as a note rather than a task. And a filter that does
    restrict now carries its values, because "recreate this filter" without them
    sends someone back to Tableau to find out what it was.
    """
    if not filter_.restricts:
        return (
            "This worksheet had a filter on this field with every value "
            "selected, so it removed nothing. The converted report does not "
            "have the filter shelf entry; no data is missing because of it."
        )

    if filter_.members:
        # The direction is the filter. "Keeps only (blank)" and "keeps
        # everything except (blank)" describe different data, and Tableau's
        # `except` was being read - and reported - as the first of those.
        what = (
            f"keeps every value except: {_readable(filter_.members)}"
            if filter_.excludes
            else f"keeps only: {_readable(filter_.members)}"
        )
        if carried:
            return (
                f"This worksheet filter {what}. It was carried over as a Power "
                "BI page filter - open the Filters pane to see it."
            )
        return (
            f"This worksheet filter {what}. It is not carried over - recreate "
            "it as a Power BI visual, page, or report-level filter."
        )

    if filter_.minimum is not None or filter_.maximum is not None:
        low = filter_.minimum if filter_.minimum is not None else "no lower bound"
        high = filter_.maximum if filter_.maximum is not None else "no upper bound"
        return (
            f"This worksheet filter keeps a range: {low} to {high}. It is not "
            "carried over - recreate it as a Power BI visual, page, or "
            "report-level filter."
        )

    return (
        "This worksheet filter restricts the data and its shape is one this "
        "converter does not read, so what it keeps is not stated here. It is "
        "not carried over - open the worksheet in Tableau to see the filter, "
        "and recreate it in Power BI."
    )


def _flag_dashboards(wb: Workbook) -> None:
    """Tableau dashboards compose sheets on a canvas; v1 emits one page per sheet.

    The composition itself is real work that did not convert, so it is reported
    rather than quietly discarded.
    """
    for dashboard in wb.dashboards:
        sheets = ", ".join(dashboard.sheet_names) or "no recognised sheets"
        wb.add_flag(
            item=dashboard.name,
            severity=Severity.MANUAL,
            reason=(
                f"Dashboard layout is not carried over; its sheets ({sheets}) were "
                "generated as separate pages. Recompose them on one page."
            ),
            stage="visual_map",
        )
