"""The canonical BI model — the seam every platform crosses.

See docs/dashboardbridge/04-canonical-model.md. Data only: no conversion logic
lives here, because both adapters and both directions depend on these shapes.

A field belongs here only if it means the same thing in at least two platforms
without translation. Anything else belongs in an adapter.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    Aggregation,
    BindingRole,
    ConversionMethod,
    ConversionStatus,
    DataType,
    DatePart,
    Grain,
    Platform,
    Severity,
    Stage,
)


class CanonicalBase(BaseModel):
    """Frozen so a model cannot be mutated after a stage has read it.

    `extra="forbid"` is deliberate: an adapter smuggling platform detail through
    an undeclared field is how a neutral model quietly stops being neutral.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldRef(CanonicalBase):
    """A reference to a column, resolved or not."""

    table: str | None = None
    column: str
    resolved: bool = True


class Expression(CanonicalBase):
    source_language: str = Field(description="e.g. tableau_calc, dax")
    source_text: str = Field(
        description="Verbatim source. Untrusted: never interpolated into a "
        "prompt as instruction, only as delimited USER DATA."
    )
    references: list[FieldRef] = Field(default_factory=list)


class Translation(CanonicalBase):
    target_language: str
    target_text: str
    method: ConversionMethod
    rule_ids: list[str] = Field(
        default_factory=list,
        description="Every rule-pack mapping that produced this translation, "
        "sorted. Plural because one expression can fire several; empty when no "
        "mapping fired, which is a fact about the translation and not a gap - "
        "a control-flow rewrite is the translator's own work.",
    )
    proposal_id: str | None = Field(
        default=None,
        description="Set when a human accepted an AI proposal. Never set by the "
        "model itself.",
    )


class Column(CanonicalBase):
    id: str = Field(description="Deterministic: '<table>.<name>'. Never random.")
    name: str
    caption: str | None = Field(
        default=None,
        description="Display name. Often differs from name; collapsing them "
        "loses data and produces references to names that do not exist.",
    )
    datatype: DataType = DataType.UNKNOWN
    role: str = "dimension"
    grain: Grain | None = Field(
        default=None,
        description="None means the grain could not be determined; the object "
        "is refused rather than guessed.",
    )
    expression: Expression | None = None
    translation: Translation | None = None

    @property
    def display_name(self) -> str:
        return self.caption or self.name

    @property
    def is_calculated(self) -> bool:
        return self.expression is not None


class Table(CanonicalBase):
    id: str
    name: str
    columns: list[Column] = Field(default_factory=list)


class DataSource(CanonicalBase):
    id: str
    name: str
    connection: str = "unknown"
    is_extract: bool = False
    source_id: str = Field(
        default="",
        description="The platform's own datasource id. Visual bindings are "
        "scoped by it, so a field name present in two sources binds correctly.",
    )
    tables: list[Table] = Field(default_factory=list)


class Relationship(CanonicalBase):
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    kind: str = "many_to_one"


class Parameter(CanonicalBase):
    id: str
    name: str
    caption: str
    datatype: DataType = DataType.STRING
    default_value: str = ""
    kind: str = "range"
    min_value: str | None = None
    max_value: str | None = None
    step: str | None = None
    members: list[str] = Field(default_factory=list)


class VisualBinding(CanonicalBase):
    """One field placed in one well. Replaces Tableau-shaped shelf encodings."""

    role: BindingRole
    field: FieldRef | None = None
    aggregation: Aggregation | None = None
    date_part: DatePart | None = None
    resolvable: bool = Field(
        default=True,
        description="False for constructs naming no real column. Binding one to "
        "a guess is how every visual ends up pointing at a column that does "
        "not exist.",
    )
    raw: str = Field(default="", description="The original token, for the report.")


class Visual(CanonicalBase):
    id: str
    name: str
    visual_type: str = "unknown"
    bindings: list[VisualBinding] = Field(default_factory=list)
    filters: list[VisualBinding] = Field(default_factory=list)


class Dashboard(CanonicalBase):
    id: str
    name: str
    visual_ids: list[str] = Field(default_factory=list)


class ConversionFlag(CanonicalBase):
    """Anything that did not convert cleanly. Nothing is ever dropped silently."""

    item: str
    stage: Stage
    method: ConversionMethod = ConversionMethod.DETERMINISTIC
    status: ConversionStatus = ConversionStatus.CONVERTED
    severity: Severity = Severity.INFO
    reason: str = ""
    ref: str = ""


class CanonicalModel(CanonicalBase):
    source_platform: Platform
    source_version: str = ""
    name: str = ""
    datasources: list[DataSource] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    visuals: list[Visual] = Field(default_factory=list)
    dashboards: list[Dashboard] = Field(default_factory=list)
    flags: list[ConversionFlag] = Field(default_factory=list)

    def all_tables(self) -> list[Table]:
        return [t for ds in self.datasources for t in ds.tables]

    def all_columns(self) -> list[Column]:
        return [c for t in self.all_tables() for c in t.columns]
