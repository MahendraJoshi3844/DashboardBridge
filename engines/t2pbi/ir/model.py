"""Intermediate Representation (IR) for t2pbi.

Technology-neutral data model that decouples reading Tableau from writing Power BI.
Every pipeline stage reads/writes only these dataclasses. See
docs/specs/modules/ir.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    """Severity of a conversion flag. MANUAL means a human must finish the item."""

    INFO = "info"
    WARNING = "warning"
    MANUAL = "manual"


@dataclass
class ConversionFlag:
    """One record of anything that did not convert cleanly. Feeds the report.

    Nothing is ever dropped silently; if we cannot convert it, we flag it.
    """

    item: str
    severity: Severity
    reason: str
    stage: str = ""


#: Where an expression evaluates (ADR-002). Defined here because the model
#: owns its own vocabulary: `core.dax.grain` decides which one applies, and a
#: stage that reads the model should not be where the model's words live.
#:
#: Neither name is a target's. Power BI writes an aggregate-grain expression
#: as a measure and a row-grain one as a calculated column; Tableau writes
#: them differently again. Naming the field after either answer would decide
#: the question in the source model.
ROW = "row"
AGGREGATE = "aggregate"

#: What a field is doing in a visual. The canonical model's `BindingRole`
#: spelled out here for the same reason `ROW`/`AGGREGATE` are: the model owns
#: its vocabulary, and these are the words every target understands.
CATEGORY = "category"
VALUE = "value"
SERIES = "series"
DETAIL = "detail"
TOOLTIP = "tooltip"
FILTER = "filter"


@dataclass
class Column:
    name: str
    datatype: str  # tableau datatype, e.g. "integer", "real", "string", "date"
    role: str  # "dimension" | "measure"
    caption: str | None = None
    formula: str | None = None  # original Tableau calc expression, if calculated
    dax: str | None = None  # translated DAX (None if unsupported)
    # Rule-pack ids that produced `dax`, sorted. Plural because one formula can
    # fire several mappings, and empty because many translations are the
    # translator's own control-flow work rather than a function mapping.
    dax_rule_ids: list[str] = field(default_factory=list)
    # Set when `dax` came from a model's draft that a person accepted, never
    # from a rule. The adapter turns it into `Translation.proposal_id`, which is
    # how the audit trail separates AI contribution from deterministic work.
    dax_proposal_id: str = ""
    # Where a calculated field's expression evaluates: ROW or AGGREGATE
     # (core.dax.grain). Named for the question rather than for one target's
     # answer to it - "measure" and "calculated column" are Power BI's words for
     # what a row-grain or aggregate-grain expression becomes there, and a
     # platform-neutral model that speaks them has already picked a side
     # (ADR-002).
    grain: str = "row"

    @property
    def is_calculated(self) -> bool:
        return self.formula is not None

    @property
    def is_aggregate(self) -> bool:
        """Evaluates over a set of rows rather than within one.

        What that becomes is the target's business: Power BI writes it as a
        measure, Tableau as an aggregate calculation.
        """
        return self.is_calculated and self.grain == AGGREGATE

    @property
    def display_name(self) -> str:
        return self.caption or self.name


@dataclass
class Parameter:
    """A Tableau parameter -> Power BI what-if parameter.

    `name` is the raw Tableau identifier (e.g. "Parameter 1"); `caption` is the
    user-facing label (e.g. "New Business Growth"). Calc references may use either.
    """

    name: str
    caption: str
    datatype: str  # tableau datatype: integer | real | string
    default_value: str  # raw default (numeric literal or quoted string)
    kind: str = "range"  # "range" | "list"
    min_value: str | None = None
    max_value: str | None = None
    step: str | None = None
    members: list[str] = field(default_factory=list)  # for list params

    @property
    def display_name(self) -> str:
        return self.caption or self.name


@dataclass
class Relationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    kind: str = "many_to_one"  # many_to_one | one_to_one | many_to_many
    #: `source_id` of the datasource this relationship was read from.
    #: Endpoints are table names, and two datasources may use the same one,
    #: so a name alone cannot say which table an endpoint meant. Renaming a
    #: colliding table needs this to tell its own relationships apart from
    #: the ones that kept the name.
    datasource_id: str = ""


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)


@dataclass
class DataSource:
    name: str
    connection: str  # short description of the connection, e.g. "extract", "sqlserver"
    #: Where the data actually is: a file path, or `server/database`. `None`
    #: when the workbook does not say.
    #:
    #: The converted model carries schema and no rows - deliberately, because a
    #: converter that read a full extract would be a much worse tool - so this
    #: is the one thing the user needs in order to make the model useful. It
    #: was being read and thrown away: every Tableau file source is a
    #: `federated` shell around a `<named-connection>`, and only the shell was
    #: kept.
    source_location: str | None = None
    tables: list[Table] = field(default_factory=list)
    is_extract: bool = False
    # Raw Tableau datasource id (e.g. "federated.10nnk8d..."). Worksheet shelves
    # qualify fields by this id, so it is what scopes a field back to its source.
    source_id: str = ""


@dataclass(frozen=True)
class VisualBinding:
    """One field placed in one well (ADR-002). Replaces `ShelfRef`/`Encoding`.

    `role` says what the field is *doing* in the visual rather than which
    Tableau shelf it was dragged to. Rows and columns are Tableau's geometry;
    every target has categories and values, so the model carries those and the
    reader of it never has to know about shelves.

    Tableau encodes shelf fields as ``<prefix>:<Field>:<role-kind>``; `field` is
    the decoded column name. `resolvable` is False for tokens that name no real
    column (Measure Names, Multiple Values, nested table calcs, join keys) —
    those must be flagged, never bound to a guessed column.
    """

    raw: str
    field: str
    role: str = VALUE
    datasource: str | None = None
    aggregation: str | None = None
    date_part: str | None = None
    resolvable: bool = True

    # --- filters only -------------------------------------------------------
    #
    # What the filter *does*, not just which field it is on. Only the field was
    # kept before, and that is why every filter looked alike: "Category, all
    # values" and "Category, two values" arrived as the same object, so the
    # report told the user to recreate both. On Superstore that was 65 of 83
    # filters reported as manual work that restrict nothing.
    #
    # `restricts` is the question everything downstream actually asks. A filter
    # shelf entry with every member selected changes no data, and reporting it
    # as work to redo is over-claiming - which erodes trust exactly as fast as
    # under-claiming, because a person who checks six no-op items stops reading
    # before the ones that matter.
    #: True when this filter removes something. False for Tableau's "all".
    restricts: bool = False
    #: The members this filter names, sorted. Empty when the filter selects
    #: everything - the values *are* the filter, and "recreate this" without
    #: them is a puzzle rather than an instruction.
    members: tuple[str, ...] = ()
    #: True when `members` are the values *removed* rather than the values kept.
    #:
    #: Tableau writes "everything but these" as an `except` groupfilter wrapping
    #: the whole level plus the members to drop. Reading only the member leaves
    #: turns that into "only these" - the exact opposite - and the report then
    #: states the opposite of the truth about the user's data. Superstore has
    #: one: *every city except the blanks*, reported as *only the blanks*.
    excludes: bool = False
    #: Bounds for a range filter, as written. Strings, because Tableau writes
    #: dates, integers and reals here and re-typing them would be a decision
    #: this layer has no reason to make.
    minimum: str | None = None
    maximum: str | None = None


@dataclass
class Worksheet:
    name: str
    visual_type: str  # normalized: bar|line|area|table|scatter|pie|kpi|unknown
    #: Every field placed on the visual, each carrying its role. One list rather
    #: than a field per shelf: `Encoding` had six, four of which nothing ever
    #: filled in, and a shelf Tableau adds tomorrow needed a new attribute here
    #: before it could even be reported.
    bindings: list[VisualBinding] = field(default_factory=list)
    filters: list[VisualBinding] = field(default_factory=list)

    def placed(self, role: str) -> list[VisualBinding]:
        return [binding for binding in self.bindings if binding.role == role]


@dataclass
class Dashboard:
    name: str
    sheet_names: list[str] = field(default_factory=list)


@dataclass
class Workbook:
    version: str = ""
    datasources: list[DataSource] = field(default_factory=list)
    worksheets: list[Worksheet] = field(default_factory=list)
    dashboards: list[Dashboard] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    flags: list[ConversionFlag] = field(default_factory=list)

    def add_flag(
        self, item: str, severity: Severity, reason: str, stage: str = ""
    ) -> None:
        self.flags.append(ConversionFlag(item, severity, reason, stage))

    def all_tables(self) -> list[Table]:
        return [t for ds in self.datasources for t in ds.tables]
