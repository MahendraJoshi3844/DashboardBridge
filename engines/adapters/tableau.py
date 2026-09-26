"""Tableau adapter: `.twb`/`.twbx` bytes -> canonical model.

Wraps the proven `t2pbi` engine (ADR-001) and maps its parse-time IR onto the
canonical contracts (ADR-008). The engine keeps its own working model; this
module is the seam where Tableau's vocabulary stops and the platform-neutral one
begins.

Nothing here parses XML. All the hard-won Tableau knowledge — encoded shelf
references, federation object graphs, grain classification — stays in the engine.
"""

from __future__ import annotations

from dashboardbridge_contracts import (
    CanonicalModel,
    Column,
    ConversionFlag,
    DataSource,
    Dashboard,
    Expression,
    FieldRef,
    Parameter,
    Platform,
    Table,
    Translation,
    Visual,
    VisualBinding,
)
from dashboardbridge_contracts.enums import (
    Aggregation,
    BindingRole,
    ConversionMethod,
    ConversionStatus,
    DataType,
    DatePart,
    Grain,
    Severity,
    Stage,
)
from t2pbi.core.parse import parse_workbook
from t2pbi.ir import Severity as IRSeverity
# Aliased: the IR and the contract now use the same name for the same
# concept, which is the point of `P2.2` - and is exactly why one of them
# has to be spelled differently here. The unaliased name is the contract's,
# because this module's job is to produce those.
from t2pbi.ir import VisualBinding as IRBinding
from t2pbi.ir import Workbook
from t2pbi.core.dax.grain import classify_calc
from t2pbi.pipeline import _classify_calculations, _param_aliases

# Tableau spellings -> canonical datatypes.
_DATATYPES = {
    "integer": DataType.INTEGER,
    "real": DataType.DECIMAL,
    "string": DataType.STRING,
    "boolean": DataType.BOOLEAN,
    "date": DataType.DATE,
    "datetime": DataType.DATETIME,
}

_AGGREGATIONS = {
    "sum": Aggregation.SUM,
    "avg": Aggregation.AVERAGE,
    "min": Aggregation.MIN,
    "max": Aggregation.MAX,
    "cnt": Aggregation.COUNT,
    "cntd": Aggregation.COUNT_DISTINCT,
    "median": Aggregation.MEDIAN,
    "attr": Aggregation.ATTRIBUTE,
}

_DATE_PARTS = {
    "yr": DatePart.YEAR,
    "tyr": DatePart.YEAR,
    "qr": DatePart.QUARTER,
    "tqr": DatePart.QUARTER,
    "mn": DatePart.MONTH,
    "tmn": DatePart.MONTH,
    "wk": DatePart.WEEK,
    "twk": DatePart.WEEK,
    "dy": DatePart.DAY,
    "tdy": DatePart.DAY,
    "hr": DatePart.HOUR,
    "mi": DatePart.MINUTE,
    "se": DatePart.SECOND,
}

# The engine's flag severity says how loudly to report; the canonical model also
# needs to say what became of the object and how (ADR-004). Severity alone cannot
# express "the AI was asked and the user declined".
_STATUS_BY_SEVERITY = {
    IRSeverity.INFO: ConversionStatus.CONVERTED,
    IRSeverity.WARNING: ConversionStatus.PARTIAL,
    IRSeverity.MANUAL: ConversionStatus.AI_REQUIRED,
}
_METHOD_BY_SEVERITY = {
    IRSeverity.INFO: ConversionMethod.DETERMINISTIC,
    IRSeverity.WARNING: ConversionMethod.DETERMINISTIC,
    IRSeverity.MANUAL: ConversionMethod.MANUAL,
}
_STAGES = {
    "extract": Stage.EXTRACT,
    "parse": Stage.PARSE,
    "visual_map": Stage.MAP,
    "translate": Stage.TRANSLATE,
    "emit": Stage.GENERATE,
}


class UnreadableArtifact(Exception):
    """The file was accepted as a workbook but yielded nothing.

    Reporting zeros for this is a silent drop wearing a number: the user is
    shown a confident "0 columns, 0 flags" and reads it as an empty workbook,
    when the truth is that we could not read the file at all. Refusing is the
    only honest answer.
    """


def _twb_from_package(data: bytes) -> bytes:
    """The `.twb` inside a `.twbx`, through the engine's capped extractor.

    The extractor reads a path, because the CLI and desktop hand it one, so the
    bytes go to a temporary file first. An archive with no workbook in it, or
    one that lies about its members, is refused as unreadable rather than
    parsed as whatever it happens to contain.
    """
    import tempfile  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    from t2pbi.core.extract import InvalidWorkbookError, extract  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="dbb-twbx-") as scratch:
        package = Path(scratch) / "source.twbx"
        package.write_bytes(data)
        try:
            return extract(package).twb_bytes
        except InvalidWorkbookError as exc:
            raise UnreadableArtifact(str(exc)) from exc


def _datatype(raw: str | None) -> DataType:
    return _DATATYPES.get((raw or "").lower(), DataType.UNKNOWN)


class TableauAdapter:
    """Reads Tableau. Cannot write it — see ADR-005."""

    platform = Platform.TABLEAU

    def __init__(self) -> None:
        self._grains: dict[str, Grain | None] = {}

    # ---- detect -----------------------------------------------------------

    def detect(self, data: bytes) -> bool:
        """Cheap header peek. Never parses: parsing untrusted input is what the
        sandbox and the size limits exist for."""
        if not data:
            return False
        if data[:2] == b"PK":  # a .twbx is a zip; the API validates its contents
            return False
        head = data[:4096].lstrip()
        return b"<workbook" in head[:2048]

    # ---- parse ------------------------------------------------------------

    def parse(self, data: bytes) -> Workbook:
        """Bytes -> the engine's IR. Grain is classified here because the
        canonical model records grain per column, and classification needs the
        whole workbook to reach a fixpoint.

        A `.twbx` is a zip, and the `.twb` inside it is what gets parsed. It is
        taken out by the engine's own extractor - the one the conversion uses -
        so the member cap and the lying-member check apply here too. Handing the
        zip itself to the XML parser under `recover=True` produced no document
        at all, and every packaged workbook failed analysis.
        """
        if data[:2] == b"PK":
            data = _twb_from_package(data)
        workbook = parse_workbook(data)
        _classify_calculations(workbook)
        return workbook

    # ---- normalize --------------------------------------------------------

    def normalize(self, parsed: Workbook) -> CanonicalModel:
        # A real workbook has at least one datasource or one worksheet. Nothing
        # at all means the document was well-formed XML that we did not
        # understand - not an empty workbook.
        if not parsed.datasources and not parsed.worksheets:
            raise UnreadableArtifact(
                "the document contains no datasources and no worksheets"
            )
        self._grains = self._classify(parsed)
        return CanonicalModel(
            source_platform=Platform.TABLEAU,
            source_version=parsed.version,
            datasources=[self._datasource(ds) for ds in parsed.datasources],
            relationships=[
                self._relationship(r) for r in parsed.relationships
            ],
            parameters=[self._parameter(p) for p in parsed.parameters],
            visuals=[self._visual(w) for w in parsed.worksheets],
            dashboards=[self._dashboard(d) for d in parsed.dashboards],
            flags=self._flags(parsed),
        )

    # ---- mapping ----------------------------------------------------------

    def _datasource(self, ds) -> DataSource:
        return DataSource(
            id=ds.name,
            name=ds.name,
            connection=ds.connection,
            is_extract=ds.is_extract,
            source_id=ds.source_id,
            tables=[self._table(t) for t in ds.tables],
        )

    def _table(self, table) -> Table:
        return Table(
            id=table.name,
            name=table.name,
            columns=[self._column(table.name, c) for c in table.columns],
        )

    def _column(self, table_name: str, column) -> Column:
        expression = None
        translation = None
        if column.is_calculated:
            expression = Expression(
                source_language="tableau_calc",
                source_text=column.formula or "",
            )
            if column.dax:
                # Present only after the engine has translated. On the read path
                # nothing is translated yet, so this stays null and the
                # comparison view renders an empty target - which is the honest
                # rendering of "not converted", not a gap to be filled in.
                translation = Translation(
                    target_language="dax",
                    target_text=column.dax,
                    # A person accepted a model's draft, or a rule produced it.
                    # Recording which is what lets the report answer §62.
                    method=(
                        ConversionMethod.AI_ASSISTED
                        if column.dax_proposal_id
                        else ConversionMethod.DETERMINISTIC
                    ),
                    rule_ids=list(column.dax_rule_ids),
                    proposal_id=column.dax_proposal_id or None,
                )
        return Column(
            id=f"{table_name}.{column.display_name}",
            name=column.name,
            caption=column.caption,
            datatype=_datatype(column.datatype),
            role=column.role,
            grain=self._grain(column, table_name),
            expression=expression,
            translation=translation,
        )

    # ---- write ------------------------------------------------------------

    def generate(self, model: CanonicalModel, out_dir: str) -> str:
        """Canonical model to a `.twb` on disk (`P6b.1`). Returns its path.

        Delegated rather than written here: reading and writing a platform are
        separate capabilities (ADR-005), and a module that did both would let a
        writer quietly reuse a reader's assumptions - which is how a generator
        ends up producing only what its own parser happens to accept.
        """
        from engines.adapters.tableau_emit import write_twb  # noqa: PLC0415

        return str(write_twb(model, out_dir))

    def _classify(self, parsed: Workbook) -> dict[str, Grain | None]:
        """Grain per calculated column, asked of the classifier directly.

        `Column.grain` cannot answer this: the engine leaves it at its default
        for a calc it refused, so a refused calc and a row-level one look
        identical. Reading the verdict keeps "undetermined" distinguishable
        from "row-level", which is the difference between refusing and guessing.
        """
        params = _param_aliases(parsed)
        known = {
            alias: column.grain
            for table in parsed.all_tables()
            for column in table.columns
            if column.is_calculated
            for alias in (column.name.lower(), column.display_name.lower())
        }
        grains: dict[str, Grain | None] = {}
        for table in parsed.all_tables():
            for column in table.columns:
                if not column.is_calculated:
                    continue
                verdict = classify_calc(column.formula or "", known, params)
                # The IR and the contract now use the same two words, so this
                # is a lookup rather than a translation (`P2.2`).
                grains[f"{table.name}.{column.display_name}"] = (
                    Grain(verdict.grain) if verdict.grain else None
                )
        return grains

    def _grain(self, column, table_name: str = "") -> Grain | None:
        """None means undetermined, and undetermined is refused, never guessed.

        A physical column is row-level by definition.
        """
        if not column.is_calculated:
            return Grain.ROW
        return self._grains.get(f"{table_name}.{column.display_name}")

    def _relationship(self, rel):
        from dashboardbridge_contracts import Relationship

        return Relationship(
            from_table=rel.from_table,
            from_column=rel.from_column,
            to_table=rel.to_table,
            to_column=rel.to_column,
            kind=rel.kind,
        )

    def _parameter(self, param) -> Parameter:
        return Parameter(
            id=param.display_name,
            name=param.name,
            caption=param.caption,
            datatype=_datatype(param.datatype),
            default_value=param.default_value,
            kind=param.kind,
            min_value=param.min_value,
            max_value=param.max_value,
            step=param.step,
            members=list(param.members),
        )

    def _binding(self, ref: IRBinding) -> VisualBinding:
        """An IR binding becomes the contract's binding.

        Since `P2.2` the two carry the same fields and the same role
        vocabulary, so this copies rather than translates; the role travels on
        the binding instead of being supplied by whichever shelf it came from.

        An unresolvable operand keeps its raw token and binds no field. Guessing
        a field here is the bug that once pointed every visual at a column named
        `sum:Sales:qk`, which existed nowhere.
        """
        role = BindingRole(ref.role)
        if not ref.resolvable:
            return VisualBinding(role=role, resolvable=False, raw=ref.raw)
        return VisualBinding(
            role=role,
            field=FieldRef(column=ref.field),
            aggregation=_AGGREGATIONS.get(ref.aggregation or ""),
            date_part=_DATE_PARTS.get(ref.date_part or ""),
            resolvable=True,
            raw=ref.raw,
        )

    def _visual(self, sheet) -> Visual:
        bindings = [self._binding(ref) for ref in sheet.bindings]
        return Visual(
            id=sheet.name,
            name=sheet.name,
            visual_type=sheet.visual_type,
            bindings=bindings,
            filters=[
                self._binding(ref) for ref in sheet.filters
            ],
        )

    def _dashboard(self, dashboard) -> Dashboard:
        return Dashboard(
            id=dashboard.name,
            name=dashboard.name,
            visual_ids=list(dashboard.sheet_names),
        )

    def _flags(self, parsed: Workbook) -> list[ConversionFlag]:
        """Engine flags carry severity; the canonical flag carries all three
        axes, so status and method are derived rather than lost."""
        flags = [
            ConversionFlag(
                item=flag.item,
                stage=_STAGES.get(flag.stage, Stage.PARSE),
                method=_METHOD_BY_SEVERITY[flag.severity],
                status=_STATUS_BY_SEVERITY[flag.severity],
                severity=Severity(flag.severity.value),
                reason=flag.reason,
                ref=flag.item,
            )
            for flag in parsed.flags
        ]
        flags.extend(self._undetermined_grain_flags(parsed))
        flags.extend(self._unbindable_flags(parsed))
        return flags

    def _unbindable_flags(self, parsed: Workbook) -> list[ConversionFlag]:
        """A shelf operand naming no real column cannot become a binding, and
        the canonical model owns saying so."""
        found: list[ConversionFlag] = []
        for sheet in parsed.worksheets:
            operands = list(sheet.bindings)
            for ref in operands:
                if ref.resolvable:
                    continue
                found.append(
                    ConversionFlag(
                        item=f"{sheet.name}: {ref.raw}",
                        stage=Stage.MAP,
                        method=ConversionMethod.MANUAL,
                        status=ConversionStatus.UNSUPPORTED,
                        severity=Severity.MANUAL,
                        reason=(
                            f"{ref.raw} is a Tableau construct with no column "
                            "equivalent; add this field well by hand."
                        ),
                        ref=sheet.name,
                    )
                )
        return found

    def _undetermined_grain_flags(
        self, parsed: Workbook
    ) -> list[ConversionFlag]:
        """A calc whose grain could not be determined is refused, and a refusal
        nobody can see is a silent drop."""
        found: list[ConversionFlag] = []
        for table in parsed.all_tables():
            for column in table.columns:
                if (
                    not column.is_calculated
                    or self._grain(column, table.name) is not None
                ):
                    continue
                ref = f"{table.name}.{column.display_name}"
                if any(f.item == ref for f in parsed.flags):
                    continue
                found.append(
                    ConversionFlag(
                        item=ref,
                        stage=Stage.TRANSLATE,
                        method=ConversionMethod.MANUAL,
                        status=ConversionStatus.AI_REQUIRED,
                        severity=Severity.MANUAL,
                        reason=(
                            "The intended aggregation is not stated in the "
                            "formula, so the grain could not be determined."
                        ),
                        ref=ref,
                    )
                )
        return found
