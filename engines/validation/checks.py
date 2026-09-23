"""The rules. Each one answers a question that can be answered offline.

Granularity is not uniform, and that is deliberate. Structural rules are
properties of the model *as a whole* — one answer per property — because eleven
"this table has a partition" passes would swamp the seven count-parity rules and
make the structural score a function of how many tables the workbook happened to
have. Semantic and visual rules are per object, because "one of 27 calculations
is verifiable" and "27 of 27 are" must not collapse to the same number.

Every rule states its denominator in the note, since `ValidationRuleResult`
carries no count fields (see the report accompanying this phase). "94%" is
meaningless; "132 of 143, 8 requiring review, 3 unsupported" is a fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from dashboardbridge_contracts import CanonicalModel, ConversionFlag, Visual, VisualBinding

from engines.validation.equivalence import decide_equivalence
from engines.dax import references_in
from engines.validation.target import TargetProject

STRUCTURAL = "structural"
SEMANTIC = "semantic"
VISUAL = "visual"


class RuleStatus(str, Enum):
    """`WARNING` never counts as a pass; `NOT_APPLICABLE` is never counted at all."""

    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class Check:
    category: str
    rule_id: str
    status: RuleStatus
    note: str


#: A FAIL here means the target is not a usable Power BI project or the report
#: of it is untrue, so the verdict is `failed` regardless of the arithmetic. A
#: model without partitions does not open; an object neither converted nor
#: reported is the silent drop the product exists to prevent.
BLOCKING = frozenset(
    {
        "PBIP_MANIFEST_PRESENT",
        "REPORT_DEFINITION_PRESENT",
        "SEMANTIC_MODEL_DEFINITION_PRESENT",
        "SEMANTIC_MODEL_TABLE_PARTITIONS",
        "SEMANTIC_MODEL_TABLE_REFS_RESOLVE",
        "EXPRESSION_REFERENCES_RESOLVE",
        "VISUAL_BINDING_REFERENCES_RESOLVE",
        "REFUSAL_INTEGRITY",
        "OUTPUT_DETERMINISTIC",
    }
)

_LAST_BRACKET = re.compile(r"\[([^\[\]]*)\]\s*$")


# ---------------------------------------------------------------------------
# naming — how a source object is identified to a flag
# ---------------------------------------------------------------------------


def binding_label(binding: VisualBinding) -> str:
    """The name a shelf operand is known by, resolvable or not.

    An unresolvable operand keeps no field, only its raw Tableau token, and the
    engine's refusal names the decoded tail of that token. Reading the tail here
    is what lets the refusal and the gap be recognised as the same thing.
    """
    if binding.field is not None:
        return binding.field.column
    match = _LAST_BRACKET.search(binding.raw or "")
    return match.group(1) if match else (binding.raw or "")


def flag_subjects(flags: Iterable[ConversionFlag]) -> set[str]:
    """Everything the conversion said something about, case-folded.

    Engine refusals are sometimes aggregated — `"ProductView: Category, Region"`
    is one flag about three filters — so an aggregated item is expanded into the
    individual subjects it names. Without that, three reported gaps would look
    like two silent drops.
    """
    subjects: set[str] = set()
    for flag in flags:
        for value in (flag.item, flag.ref):
            if not value:
                continue
            subjects.add(value.casefold())
            if ": " in value:
                owner, listed = value.split(": ", 1)
                subjects.add(owner.casefold())
                for part in listed.split(", "):
                    subjects.add(f"{owner}: {part}".casefold())
    return subjects


def _accounted(subject: str, subjects: set[str]) -> bool:
    return subject.casefold() in subjects


def _listed(names: Sequence[str], limit: int = 8) -> str:
    shown = ", ".join(names[:limit])
    return shown + (f", and {len(names) - limit} more" if len(names) > limit else "")


# ---------------------------------------------------------------------------
# count parity
# ---------------------------------------------------------------------------


def _count_check(
    rule_id: str,
    kind: str,
    source_count: int,
    target_count: int,
    missing: Sequence[str],
    subjects: set[str],
    extra_note: str = "",
) -> Check:
    tail = f" {extra_note}" if extra_note else ""
    head = f"{kind}: source {source_count}, target {target_count}."
    if target_count > source_count:
        return Check(
            STRUCTURAL,
            rule_id,
            RuleStatus.FAIL,
            f"{head} The target contains {target_count - source_count} more "
            f"than the source did, which no conversion rule accounts for.{tail}",
        )
    if not missing and source_count == target_count:
        return Check(STRUCTURAL, rule_id, RuleStatus.PASS, f"{head}{tail}")
    unreported = [name for name in missing if not _accounted(name, subjects)]
    if unreported:
        return Check(
            STRUCTURAL,
            rule_id,
            RuleStatus.FAIL,
            f"{head} {len(unreported)} of {len(missing)} that did not cross are "
            f"reported nowhere: {_listed(unreported)}.{tail}",
        )
    return Check(
        STRUCTURAL,
        rule_id,
        RuleStatus.WARNING,
        f"{head} {len(missing)} did not cross and every one is reported as a "
        f"conversion flag: {_listed(list(missing))}.{tail}",
    )


# ---------------------------------------------------------------------------
# structural
# ---------------------------------------------------------------------------


def structural_checks(
    model: CanonicalModel,
    flags: Sequence[ConversionFlag],
    target: TargetProject,
    replica: TargetProject | None,
) -> tuple[list[Check], list[str]]:
    """Count parity, format validity, dangling references, determinism.

    Returns the checks and the list of source objects that did not reach the
    target, which refusal integrity then holds the conversion accountable for.
    """
    subjects = flag_subjects(flags)
    semantic_model = target.semantic_model()
    report = target.report()

    parameter_names = {
        name.casefold()
        for parameter in model.parameters
        for name in (parameter.id, parameter.caption, parameter.name)
        if name
    }
    data_tables = [
        table
        for table in semantic_model.tables
        if table.name.casefold() not in parameter_names
    ]
    target_table_names = {t.name.casefold() for t in semantic_model.tables}

    checks: list[Check] = []
    missing: list[str] = []

    # -- tables --------------------------------------------------------------
    source_tables = model.all_tables()
    missing_tables = [
        t.name for t in source_tables if t.name.casefold() not in target_table_names
    ]
    missing += missing_tables
    checks.append(
        _count_check(
            "TABLE_COUNT_MATCH",
            "tables",
            len(source_tables),
            len(data_tables),
            missing_tables,
            subjects,
        )
    )

    # -- columns -------------------------------------------------------------
    emitted_columns = {
        (table.name.casefold(), column.casefold())
        for table in semantic_model.tables
        for column in table.columns
    }
    source_columns = [
        (table, column)
        for table in source_tables
        for column in table.columns
        if not column.is_calculated
    ]
    missing_columns = [
        f"{table.name}.{column.display_name}"
        for table, column in source_columns
        if (table.name.casefold(), column.display_name.casefold()) not in emitted_columns
    ]
    missing += missing_columns
    checks.append(
        _count_check(
            "COLUMN_COUNT_MATCH",
            "columns",
            len(source_columns),
            sum(len(t.columns) for t in data_tables),
            missing_columns,
            subjects,
        )
    )

    # -- calculations --------------------------------------------------------
    emitted_expressions = {
        (table.name.casefold(), name.casefold())
        for table in semantic_model.tables
        for name, _ in list(table.calculated_columns) + list(table.measures)
    }
    source_calculations = [
        (table, column)
        for table in source_tables
        for column in table.columns
        if column.is_calculated
    ]
    missing_calculations = [
        f"{table.name}.{column.display_name}"
        for table, column in source_calculations
        if (table.name.casefold(), column.display_name.casefold())
        not in emitted_expressions
    ]
    missing += missing_calculations
    checks.append(
        _count_check(
            "CALCULATION_COUNT_MATCH",
            "calculations",
            len(source_calculations),
            sum(
                len(t.calculated_columns) + len(t.measures) for t in data_tables
            ),
            missing_calculations,
            subjects,
        )
    )

    # -- relationships -------------------------------------------------------
    emitted_pairs = {
        (r.from_table.casefold(), r.to_table.casefold())
        for r in semantic_model.relationships
    }
    missing_relationships = [
        f"{r.from_table}.{r.from_column} -> {r.to_table}.{r.to_column}"
        for r in model.relationships
        if (r.from_table.casefold(), r.to_table.casefold()) not in emitted_pairs
    ]
    missing += missing_relationships
    checks.append(
        _count_check(
            "RELATIONSHIP_COUNT_MATCH",
            "relationships",
            len(model.relationships),
            len(semantic_model.relationships),
            missing_relationships,
            subjects,
        )
    )

    # -- parameters ----------------------------------------------------------
    missing_parameters = [
        parameter.id
        for parameter in model.parameters
        if not {
            name.casefold()
            for name in (parameter.id, parameter.caption, parameter.name)
            if name
        }
        & target_table_names
    ]
    missing += missing_parameters
    checks.append(
        _count_check(
            "PARAMETER_COUNT_MATCH",
            "parameters",
            len(model.parameters),
            len(semantic_model.tables) - len(data_tables),
            missing_parameters,
            subjects,
        )
    )

    # -- visuals -------------------------------------------------------------
    page_titles = {page.display_name.casefold() for page in report.pages}
    missing_visuals = [
        visual.name
        for visual in model.visuals
        if visual.name.casefold() not in page_titles
    ]
    missing += missing_visuals
    checks.append(
        _count_check(
            "VISUAL_COUNT_MATCH",
            "visuals",
            len(model.visuals),
            sum(len(page.visuals) for page in report.pages),
            missing_visuals,
            subjects,
        )
    )

    # -- dashboards ----------------------------------------------------------
    # A PBIR report definition has no dashboard object at all, so this can only
    # ever be a shortfall. It is measured anyway: a gap that is never counted
    # is a gap nobody sees.
    missing_dashboards = [dashboard.name for dashboard in model.dashboards]
    missing += missing_dashboards
    checks.append(
        _count_check(
            "DASHBOARD_COUNT_MATCH",
            "dashboards",
            len(model.dashboards),
            0,
            missing_dashboards,
            subjects,
            extra_note=(
                "A PBIR report definition has no dashboard object; each "
                "dashboard's sheets are generated as separate pages."
            ),
        )
    )

    # -- bindings and filters that did not cross ------------------------------
    # A shelf may name a column by its internal Tableau name while the model
    # carries its caption, and the emitter writes the caption. Both names are
    # the same column, so a binding is looked for under either; treating them
    # as two objects would report a column that crossed cleanly as lost.
    display_of = {
        alias.casefold(): column.display_name.casefold()
        for table in model.all_tables()
        for column in table.columns
        for alias in (column.name, column.caption, column.display_name)
        if alias
    }
    for visual in model.visuals:
        page = report.page_titled(visual.name)
        bound = {
            binding.column.casefold()
            for target_visual in (page.visuals if page else ())
            for binding in target_visual.bindings
        }
        for binding in visual.bindings:
            label = binding_label(binding)
            folded = label.casefold()
            if not ({folded, display_of.get(folded, folded)} & bound):
                missing.append(f"{visual.name}: {label}")
        for binding in visual.filters:
            missing.append(f"{visual.name}: {binding_label(binding)}")

    # -- format validity -----------------------------------------------------
    checks.append(
        _presence(
            "PBIP_MANIFEST_PRESENT",
            target.pbip_manifest_present(),
            "a .pbip manifest",
        )
    )
    checks.append(
        _presence(
            "REPORT_DEFINITION_PRESENT",
            report.definition_present,
            "definition.pbir",
        )
    )
    checks.append(
        _presence(
            "SEMANTIC_MODEL_DEFINITION_PRESENT",
            semantic_model.present,
            "definition/model.tmdl",
        )
    )
    checks.append(_partitions(semantic_model))
    checks.append(_table_refs(semantic_model))
    checks.append(_page_index(report))

    # -- dangling references -------------------------------------------------
    checks.append(_expression_references(semantic_model))
    checks.append(_binding_references(semantic_model, report))

    # -- refusal integrity ---------------------------------------------------
    checks.append(_refusal_integrity(missing, subjects))

    # -- determinism ---------------------------------------------------------
    checks.append(_determinism(target, replica))

    return checks, missing


def _presence(rule_id: str, present: bool, what: str) -> Check:
    return Check(
        STRUCTURAL,
        rule_id,
        RuleStatus.PASS if present else RuleStatus.FAIL,
        f"{what} is present." if present else f"{what} is missing from the target.",
    )


def _partitions(semantic_model) -> Check:
    tables = semantic_model.tables
    if not tables:
        return Check(
            STRUCTURAL,
            "SEMANTIC_MODEL_TABLE_PARTITIONS",
            RuleStatus.FAIL,
            "The semantic model contains no tables, so there is nothing to load.",
        )
    without = sorted(t.name for t in tables if not t.has_partition)
    if without:
        return Check(
            STRUCTURAL,
            "SEMANTIC_MODEL_TABLE_PARTITIONS",
            RuleStatus.FAIL,
            f"{len(tables) - len(without)} of {len(tables)} tables carry a "
            f"partition. Power BI rejects a model whose table has none: "
            f"{_listed(without)}.",
        )
    return Check(
        STRUCTURAL,
        "SEMANTIC_MODEL_TABLE_PARTITIONS",
        RuleStatus.PASS,
        f"{len(tables)} of {len(tables)} tables carry a partition.",
    )


def _table_refs(semantic_model) -> Check:
    declared = {t.name for t in semantic_model.tables}
    referenced = set(semantic_model.referenced_tables)
    unreferenced = sorted(declared - referenced)
    dangling = sorted(referenced - declared)
    if dangling or unreferenced:
        parts = []
        if dangling:
            parts.append(f"model.tmdl references {_listed(dangling)}, which no file defines")
        if unreferenced:
            parts.append(f"{_listed(unreferenced)} is defined but never referenced")
        return Check(
            STRUCTURAL,
            "SEMANTIC_MODEL_TABLE_REFS_RESOLVE",
            RuleStatus.FAIL,
            "; ".join(parts) + ".",
        )
    return Check(
        STRUCTURAL,
        "SEMANTIC_MODEL_TABLE_REFS_RESOLVE",
        RuleStatus.PASS,
        f"{len(declared)} of {len(declared)} table files are referenced by model.tmdl.",
    )


def _page_index(report) -> Check:
    if not report.pages:
        return Check(
            STRUCTURAL,
            "REPORT_PAGE_INDEX_COMPLETE",
            RuleStatus.FAIL,
            "The report definition contains no pages.",
        )
    ids = {page.page_id for page in report.pages}
    order = set(report.page_order)
    if ids != order:
        return Check(
            STRUCTURAL,
            "REPORT_PAGE_INDEX_COMPLETE",
            RuleStatus.FAIL,
            f"pages.json orders {len(order)} pages but {len(ids)} exist; "
            f"unindexed: {_listed(sorted(ids - order))}.",
        )
    return Check(
        STRUCTURAL,
        "REPORT_PAGE_INDEX_COMPLETE",
        RuleStatus.PASS,
        f"{len(ids)} of {len(ids)} pages appear in pages.json.",
    )


def _expression_references(semantic_model) -> Check:
    """Does any emitted expression name something never emitted?"""
    columns = {
        (table.name.casefold(), name.casefold())
        for table in semantic_model.tables
        for name in table.names()
    }
    measures = {
        name.casefold()
        for table in semantic_model.tables
        for name, _ in table.measures
    }
    checked = 0
    dangling: list[str] = []
    for table in semantic_model.tables:
        for name, expression in list(table.calculated_columns) + list(table.measures):
            checked += 1
            # Read, not pattern-matched (`P6a.2`). Deciding whether a `[` opens
            # a reference means knowing whether you are inside a string or a
            # comment, which is state a regular expression does not carry - and
            # the patterns this replaced reported a label like
            # `"see [Ghost]"` as a dependency, failing a correct model.
            for reference in references_in(expression):
                if reference.table:
                    if (
                        reference.table.casefold(),
                        reference.name.casefold(),
                    ) not in columns:
                        dangling.append(
                            f"{table.name}.{name} -> "
                            f"{reference.table}[{reference.name}]"
                        )
                elif reference.name.casefold() not in measures:
                    dangling.append(f"{table.name}.{name} -> [{reference.name}]")
    if not checked:
        return Check(
            STRUCTURAL,
            "EXPRESSION_REFERENCES_RESOLVE",
            RuleStatus.NOT_APPLICABLE,
            "The target contains no emitted expressions to resolve.",
        )
    if dangling:
        return Check(
            STRUCTURAL,
            "EXPRESSION_REFERENCES_RESOLVE",
            RuleStatus.FAIL,
            f"{len(dangling)} reference(s) in {checked} emitted expression(s) "
            f"name something never emitted: {_listed(sorted(dangling))}.",
        )
    return Check(
        STRUCTURAL,
        "EXPRESSION_REFERENCES_RESOLVE",
        RuleStatus.PASS,
        f"{checked} of {checked} emitted expressions reference only emitted objects.",
    )


def _binding_references(semantic_model, report) -> Check:
    columns = {
        (table.name.casefold(), name.casefold())
        for table in semantic_model.tables
        for name in table.names()
    }
    checked = 0
    dangling: list[str] = []
    for page in report.pages:
        for visual in page.visuals:
            for binding in visual.bindings:
                checked += 1
                if (binding.table.casefold(), binding.column.casefold()) not in columns:
                    dangling.append(
                        f"{page.display_name}: '{binding.table}'[{binding.column}]"
                    )
    if not checked:
        return Check(
            STRUCTURAL,
            "VISUAL_BINDING_REFERENCES_RESOLVE",
            RuleStatus.NOT_APPLICABLE,
            "The report contains no field bindings to resolve.",
        )
    if dangling:
        return Check(
            STRUCTURAL,
            "VISUAL_BINDING_REFERENCES_RESOLVE",
            RuleStatus.FAIL,
            f"{len(dangling)} of {checked} field bindings point at a column the "
            f"model does not define: {_listed(sorted(dangling))}.",
        )
    return Check(
        STRUCTURAL,
        "VISUAL_BINDING_REFERENCES_RESOLVE",
        RuleStatus.PASS,
        f"{checked} of {checked} field bindings resolve to an emitted column.",
    )


def _refusal_integrity(missing: Sequence[str], subjects: set[str]) -> Check:
    if not missing:
        return Check(
            STRUCTURAL,
            "REFUSAL_INTEGRITY",
            RuleStatus.PASS,
            "Every source object reached the target; there is nothing to refuse.",
        )
    unreported = sorted({name for name in missing if not _accounted(name, subjects)})
    total = len(set(missing))
    if unreported:
        return Check(
            STRUCTURAL,
            "REFUSAL_INTEGRITY",
            RuleStatus.FAIL,
            f"{total - len(unreported)} of {total} objects that did not cross "
            f"are reported as conversion flags. {len(unreported)} were neither "
            f"converted nor reported: {_listed(unreported)}.",
        )
    return Check(
        STRUCTURAL,
        "REFUSAL_INTEGRITY",
        RuleStatus.PASS,
        f"{total} of {total} objects that did not cross are reported as "
        f"conversion flags.",
    )


def _determinism(target: TargetProject, replica: TargetProject | None) -> Check:
    if replica is None:
        return Check(
            STRUCTURAL,
            "OUTPUT_DETERMINISTIC",
            RuleStatus.NOT_APPLICABLE,
            "No second conversion was supplied, so reproducibility was not "
            "checked. An unchecked property is not a passing one.",
        )
    first, second = target.digests(), replica.digests()
    differing = sorted(
        set(first) ^ set(second)
        | {path for path in set(first) & set(second) if first[path] != second[path]}
    )
    if differing:
        return Check(
            STRUCTURAL,
            "OUTPUT_DETERMINISTIC",
            RuleStatus.FAIL,
            f"{len(differing)} of {len(set(first) | set(second))} files differ "
            f"between two conversions of the same workbook: {_listed(differing)}.",
        )
    return Check(
        STRUCTURAL,
        "OUTPUT_DETERMINISTIC",
        RuleStatus.PASS,
        f"{len(first)} of {len(first)} files are byte-identical across two "
        f"conversions of the same workbook.",
    )


# ---------------------------------------------------------------------------
# semantic
# ---------------------------------------------------------------------------


def semantic_checks(model: CanonicalModel, target: TargetProject) -> list[Check]:
    semantic_model = target.semantic_model()
    checks: list[Check] = []

    for table in model.all_tables():
        for column in table.columns:
            if not column.is_calculated:
                continue
            checks.append(_expression_equivalence(table.name, column))

    for parameter in model.parameters:
        checks.append(_parameter_mapping(parameter, semantic_model))

    for visual in model.visuals:
        for binding in visual.filters:
            checks.append(_filter_mapping(visual, binding))

    return checks


def _expression_equivalence(table_name: str, column) -> Check:
    subject = f"{table_name}.{column.display_name}"
    if column.translation is None:
        return Check(
            SEMANTIC,
            "CALCULATION_SEMANTIC_MATCH",
            RuleStatus.NOT_APPLICABLE,
            f"{subject}: not translated, so there is no target expression to "
            f"compare. The gap is counted by CALCULATION_COUNT_MATCH and "
            f"REFUSAL_INTEGRITY, not a third time here.",
        )
    source = column.expression.source_text if column.expression else ""
    decision = decide_equivalence(source, column.translation.target_text)
    if decision.equivalent:
        return Check(
            SEMANTIC,
            "CALCULATION_SEMANTIC_MATCH",
            RuleStatus.PASS,
            f"{subject}: {decision.reason}. source={_inline(source)} "
            f"target={_inline(column.translation.target_text)}",
        )
    return Check(
        SEMANTIC,
        "CALCULATION_SEMANTIC_MATCH",
        RuleStatus.WARNING,
        f"{subject}: translated by rule, but its runtime behaviour was not "
        f"executed, so equivalence is undecided — {decision.reason}. "
        f"source={_inline(source)} target={_inline(column.translation.target_text)}",
    )


def _inline(text: str) -> str:
    return " ".join((text or "").split())


def _parameter_mapping(parameter, semantic_model) -> Check:
    names = [n for n in (parameter.id, parameter.caption, parameter.name) if n]
    for name in names:
        table = next(
            (t for t in semantic_model.tables if t.name.casefold() == name.casefold()),
            None,
        )
        if table is None:
            continue
        if not table.measures:
            return Check(
                SEMANTIC,
                "PARAMETER_MAPPED",
                RuleStatus.FAIL,
                f"{parameter.id}: a table exists but carries no measure, so "
                f"nothing reads the selected value.",
            )
        return Check(
            SEMANTIC,
            "PARAMETER_MAPPED",
            RuleStatus.PASS,
            f"{parameter.id}: mapped to table '{table.name}' with a value "
            f"measure '{table.measures[0][0]}'.",
        )
    return Check(
        SEMANTIC,
        "PARAMETER_MAPPED",
        RuleStatus.FAIL,
        f"{parameter.id}: no table of this name exists in the semantic model.",
    )


def _filter_mapping(visual: Visual, binding: VisualBinding) -> Check:
    label = binding_label(binding)
    return Check(
        SEMANTIC,
        "FILTER_MAPPED",
        RuleStatus.FAIL,
        f"{visual.name}: filter on '{label}' is not carried into the report "
        f"definition; recreate it as a Power BI visual, page or report-level "
        f"filter.",
    )


# ---------------------------------------------------------------------------
# visual
# ---------------------------------------------------------------------------


def visual_checks(model: CanonicalModel, target: TargetProject) -> list[Check]:
    """Type, bindings and title, per source visual.

    A visual is matched to its page by title, which is the only human-meaningful
    link between the two formats — the page id is a hash the emitter chose, and
    validating against it would be validating the emitter against itself. The
    consequence is that the three results are correlated: a visual that lost its
    title fails all three. That is stated rather than hidden.
    """
    report = target.report()
    checks: list[Check] = []
    for visual in model.visuals:
        page = report.page_titled(visual.name)
        checks.append(_visual_type(visual, page))
        checks.append(_visual_bindings(visual, page))
        checks.append(_visual_title(visual, page))
    return checks


def _missing(visual: Visual, rule_id: str) -> Check:
    return Check(
        VISUAL,
        rule_id,
        RuleStatus.FAIL,
        f"{visual.name}: no page in the report definition carries this name, "
        f"so the visual is absent from the target.",
    )


def _visual_type(visual: Visual, page) -> Check:
    if page is None or not page.visuals:
        return _missing(visual, "VISUAL_TYPE_PRESENT")
    emitted = page.visuals[0].visual_type
    if not emitted:
        return Check(
            VISUAL,
            "VISUAL_TYPE_PRESENT",
            RuleStatus.FAIL,
            f"{visual.name}: the emitted visual declares no visualType.",
        )
    if visual.visual_type in {"", "unknown"}:
        return Check(
            VISUAL,
            "VISUAL_TYPE_PRESENT",
            RuleStatus.WARNING,
            f"{visual.name}: the source mark type was not recognised, so "
            f"'{emitted}' is a substitute rather than the source's own type.",
        )
    return Check(
        VISUAL,
        "VISUAL_TYPE_PRESENT",
        RuleStatus.PASS,
        f"{visual.name}: source '{visual.visual_type}' emitted as '{emitted}'.",
    )


def _visual_bindings(visual: Visual, page) -> Check:
    if page is None or not page.visuals:
        return _missing(visual, "VISUAL_BINDINGS_BOUND")
    bound = {
        binding.column.casefold()
        for target_visual in page.visuals
        for binding in target_visual.bindings
    }
    if not visual.bindings:
        return Check(
            VISUAL,
            "VISUAL_BINDINGS_BOUND",
            RuleStatus.NOT_APPLICABLE,
            f"{visual.name}: the source visual places no field on a shelf.",
        )
    unbound = sorted(
        binding_label(binding)
        for binding in visual.bindings
        if binding_label(binding).casefold() not in bound
    )
    if unbound:
        return Check(
            VISUAL,
            "VISUAL_BINDINGS_BOUND",
            RuleStatus.FAIL,
            f"{visual.name}: {len(visual.bindings) - len(unbound)} of "
            f"{len(visual.bindings)} shelf fields are bound in the target; "
            f"unbound: {_listed(unbound)}.",
        )
    return Check(
        VISUAL,
        "VISUAL_BINDINGS_BOUND",
        RuleStatus.PASS,
        f"{visual.name}: {len(visual.bindings)} of {len(visual.bindings)} shelf "
        f"fields are bound in the target.",
    )


def _visual_title(visual: Visual, page) -> Check:
    if page is None:
        return _missing(visual, "VISUAL_TITLE_CARRIED")
    return Check(
        VISUAL,
        "VISUAL_TITLE_CARRIED",
        RuleStatus.PASS,
        f"{visual.name}: carried as the page's displayName.",
    )
