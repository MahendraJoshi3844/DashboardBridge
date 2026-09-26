"""Validation: what the product is allowed to claim about a conversion.

These tests exist to protect one rule (08-validation-engine, AGENTS.md §2):

    the system never reports success it did not verify.

So most of them are written the wrong way round on purpose. They do not check
that the validator says nice things; they check that it *refuses* to say them —
that an unmeasured category is absent rather than 1.0, that an undecidable
equivalence is a WARNING rather than a PASS, and that a numerical figure is
never produced at all (ADR-003).

The format-shaped fixtures are produced by the real emitter and then damaged,
rather than hand-written. A hand-written TMDL file tests the author's idea of
TMDL; only real output tests the format (AGENTS.md, "fixtures must be real").
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from uuid import UUID

import pytest
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
    BindingRole,
    ConversionMethod,
    ConversionStatus,
    Grain,
    Severity,
    Stage,
    Verdict,
)

pytest.importorskip("t2pbi", reason="optional engine not installed on this deployment")

from engines.conversion.run import convert_tableau_to_powerbi
from engines.validation import RuleStatus, TargetProject, validate

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PREFIX = "/api/v1"

#: Fixed so a repeated run is byte-identical. A uuid4() default would make the
#: engine non-deterministic by construction.
VID = UUID("00000000-0000-4000-8000-000000000001")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def by_id(result, rule_id: str) -> list:
    return [r for r in result.rules if r.rule_id == rule_id]


def one(result, rule_id: str):
    matches = by_id(result, rule_id)
    assert len(matches) == 1, f"expected exactly one {rule_id}, got {len(matches)}"
    return matches[0]


@pytest.fixture(scope="module")
def emitted() -> tuple[CanonicalModel, list[ConversionFlag], TargetProject]:
    """A real conversion of a real workbook, and the project it wrote to disk."""
    with tempfile.TemporaryDirectory(prefix="dbb-validation-") as tmp:
        outcome = convert_tableau_to_powerbi(
            (FIXTURES / "sample.twb").read_bytes(), Path(tmp) / "p", "Sample"
        )
        target = TargetProject.from_dir(outcome.project_dir)
    return outcome.model, outcome.flags, target


def tiny_model(**overrides) -> CanonicalModel:
    """A one-table model with no visuals, so a category can be left unmeasured."""
    defaults = dict(
        source_platform=Platform.TABLEAU,
        name="Tiny",
        datasources=[
            DataSource(
                id="ds",
                name="ds",
                tables=[
                    Table(
                        id="Orders",
                        name="Orders",
                        columns=[
                            Column(
                                id="Orders.Sales",
                                name="Sales",
                                grain=Grain.ROW,
                            )
                        ],
                    )
                ],
            )
        ],
    )
    defaults.update(overrides)
    return CanonicalModel(**defaults)


def calc(name: str, source: str, dax: str | None, table: str = "Orders") -> Column:
    return Column(
        id=f"{table}.{name}",
        name=name,
        caption=name,
        grain=Grain.AGGREGATE,
        expression=Expression(source_language="tableau_calc", source_text=source),
        translation=(
            Translation(
                target_language="dax",
                target_text=dax,
                method=ConversionMethod.DETERMINISTIC,
            )
            if dax is not None
            else None
        ),
    )


def model_with(columns: list[Column], **overrides) -> CanonicalModel:
    return tiny_model(
        datasources=[
            DataSource(
                id="ds",
                name="ds",
                tables=[Table(id="Orders", name="Orders", columns=columns)],
            )
        ],
        **overrides,
    )


def tiny_target(
    tables: dict[str, str] | None = None, *, pages: dict[str, dict] | None = None
) -> TargetProject:
    """A minimal but structurally valid PBIP, in the shape the emitter writes."""
    tables = tables or {
        "Orders": "table 'Orders'\n\n\tcolumn 'Sales'\n\t\tdataType: double\n"
        "\t\tsourceColumn: Sales\n\n\tpartition 'Orders' = m\n\t\tmode: import\n"
        "\t\tsource = let Source = #table(type table [], {}) in Source\n"
    }
    refs = "".join(f"ref table '{name}'\n" for name in tables)
    files = {
        "Tiny.pbip": json.dumps({"version": "1.0"}),
        "Tiny.SemanticModel/definition/model.tmdl": (
            "model Model\n\tculture: en-US\n\n" + refs
        ),
        "Tiny.Report/definition.pbir": json.dumps({"version": "4.0"}),
        "Tiny.Report/definition/pages/pages.json": json.dumps(
            {"pageOrder": sorted(pages or {}), "activePageName": ""}
        ),
    }
    for name, text in tables.items():
        files[f"Tiny.SemanticModel/definition/tables/{name}.tmdl"] = text
    for page_id, page in (pages or {}).items():
        files[f"Tiny.Report/definition/pages/{page_id}/page.json"] = json.dumps(page)
        files[
            f"Tiny.Report/definition/pages/{page_id}/visuals/v/visual.json"
        ] = json.dumps(page.pop("_visual", {"visual": {"visualType": "tableEx"}}))
    return TargetProject(files={k: v.encode("utf-8") for k, v in files.items()})


def run(model, target, *, flags=(), replica=None):
    return validate(
        validation_id=VID,
        model=model,
        flags=list(flags),
        target=target,
        replica=replica,
    )


# ---------------------------------------------------------------------------
# ADR-003 — numerical validation does not ship
# ---------------------------------------------------------------------------


def test_numerical_equivalence_is_always_reported_as_not_measured(emitted):
    model, flags, target = emitted
    result = run(model, target, flags=flags)
    assert result.numerical.measured is False
    assert result.numerical.reason.strip(), "an absence with no reason is a gap"


def test_no_numerical_figure_is_produced_anywhere_in_the_result(emitted):
    """Not merely 'numerical is false' — no number attributable to it exists.

    The failure this guards against is a numerical score leaking in under
    another name, which is how an unmeasured figure ends up on a slide.
    """
    model, flags, target = emitted
    result = run(model, target, flags=flags)
    assert "numerical" not in result.categories
    payload = result.model_dump(mode="json")
    assert set(payload["numerical"]) == {"measured", "reason"}
    for rule in result.rules:
        assert "numerical" not in rule.rule_id.lower()


def test_the_measured_categories_are_exactly_the_three_of_adr_003(emitted):
    model, flags, target = emitted
    result = run(model, target, flags=flags)
    assert set(result.categories) <= {"structural", "semantic", "visual"}


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def test_a_category_with_no_applicable_checks_is_excluded_not_scored_one():
    """Scoring an absent check as a pass is how validation becomes theatre."""
    model = tiny_model()  # no visuals at all
    result = run(model, tiny_target())
    assert "visual" not in result.categories
    assert "visual" not in result.formula


def test_an_excluded_category_does_not_enter_the_denominator():
    """A model with no visuals must not be scored as though visual were 1.0,
    and must not be scored as though visual were 0.0 either."""
    model = tiny_model()
    result = run(model, tiny_target())
    weighted = sum(
        result.categories[name].score * weight
        for name, weight in (("structural", 0.4), ("semantic", 0.4), ("visual", 0.2))
        if name in result.categories
    )
    total = sum(
        weight
        for name, weight in (("structural", 0.4), ("semantic", 0.4), ("visual", 0.2))
        if name in result.categories
    )
    assert result.score == pytest.approx(round(weighted / total, 4))


def test_nothing_measurable_at_all_is_unverified_with_no_score():
    """No score is an honest answer. 1.0 is not."""
    result = validate(
        validation_id=VID,
        model=tiny_model(),
        flags=[],
        target=TargetProject(files={}),
        replica=None,
        weights={"structural": 0.0, "semantic": 0.4, "visual": 0.2},
    )
    assert "structural" not in result.categories or result.score is not None
    empty = validate(
        validation_id=VID,
        model=CanonicalModel(source_platform=Platform.TABLEAU),
        flags=[],
        target=TargetProject(files={}),
        weights={"structural": 0.0},
    )
    assert empty.categories == {}
    assert empty.score is None
    assert empty.verdict is Verdict.UNVERIFIED


def test_the_formula_is_published_next_to_the_score(emitted):
    """A score whose derivation a reader cannot follow is decoration."""
    model, flags, target = emitted
    result = run(model, target, flags=flags)
    assert "passed" in result.formula
    assert "0.4" in result.formula and "0.2" in result.formula
    for name, category in result.categories.items():
        assert f"{name} {category.passed}/{category.checks}" in result.formula


def test_a_category_score_is_passed_over_applicable(emitted):
    model, flags, target = emitted
    result = run(model, target, flags=flags)
    for category in result.categories.values():
        assert category.checks > 0
        assert category.score == pytest.approx(
            round(category.passed / category.checks, 4)
        )


def test_warnings_and_not_applicable_never_count_as_passes():
    model = model_with(
        [
            Column(id="Orders.Sales", name="Sales", grain=Grain.ROW),
            calc("Ratio", "sum([Sales])/sum([Sales])", "SUM('Orders'[Sales])/SUM('Orders'[Sales])"),
            calc("Held", "INDEX()", None),
        ]
    )
    result = run(
        model,
        tiny_target(),
        flags=[
            ConversionFlag(
                item="Orders.Held",
                stage=Stage.TRANSLATE,
                status=ConversionStatus.AI_REQUIRED,
                severity=Severity.MANUAL,
                reason="unsupported construct",
                ref="Orders.Held",
            )
        ],
    )
    statuses = [r.status for r in by_id(result, "CALCULATION_SEMANTIC_MATCH")]
    assert RuleStatus.WARNING.value in statuses
    assert RuleStatus.NOT_APPLICABLE.value in statuses
    semantic = result.categories["semantic"]
    # One WARNING, one NOT_APPLICABLE: the warning is applicable and unpassed,
    # the not-applicable is not counted at all.
    assert semantic.passed == 0
    assert semantic.checks == 1


def test_the_verdict_vocabulary_never_says_success(emitted):
    model, flags, target = emitted
    result = run(model, target, flags=flags)
    assert result.verdict in set(Verdict)
    assert "success" not in result.verdict.value


def test_determinism_the_same_inputs_score_identically(emitted):
    model, flags, target = emitted
    first = run(model, target, flags=flags)
    second = run(model, target, flags=flags)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_rule_order_is_stable_so_two_runs_diff_to_nothing(emitted):
    model, flags, target = emitted
    first = [(r.rule_id, r.status, r.note) for r in run(model, target, flags=flags).rules]
    second = [(r.rule_id, r.status, r.note) for r in run(model, target, flags=flags).rules]
    assert first == second


# ---------------------------------------------------------------------------
# semantic — expression equivalence, honestly
# ---------------------------------------------------------------------------


def test_an_undecidable_equivalence_is_a_warning_not_a_pass():
    """`/` diverges on division by zero: Tableau yields null, DAX does not.

    Overstating this is the most tempting failure available to this engine.
    """
    model = model_with(
        [
            Column(id="Orders.Profit", name="Profit", grain=Grain.ROW),
            Column(id="Orders.Sales", name="Sales", grain=Grain.ROW),
            calc(
                "Profit Ratio",
                "sum([Profit])/sum([Sales])",
                "SUM('Orders'[Profit])/SUM('Orders'[Sales])",
            ),
        ]
    )
    target = tiny_target(
        tables={
            "Orders": "table 'Orders'\n\n\tcolumn 'Profit'\n\t\tdataType: double\n"
            "\t\tsourceColumn: Profit\n\n\tcolumn 'Sales'\n\t\tdataType: double\n"
            "\t\tsourceColumn: Sales\n\n"
            "\tmeasure 'Profit Ratio' = SUM('Orders'[Profit])/SUM('Orders'[Sales])\n\n"
            "\tpartition 'Orders' = m\n\t\tmode: import\n\t\tsource = let Source = "
            "#table(type table [], {}) in Source\n"
        }
    )
    result = run(model, target)
    rule = one(result, "CALCULATION_SEMANTIC_MATCH")
    assert rule.status == RuleStatus.WARNING.value
    assert "not executed" in rule.note


def test_the_warning_names_the_construct_that_made_it_undecidable():
    model = model_with(
        [
            Column(id="Orders.Sales", name="Sales", grain=Grain.ROW),
            calc(
                "Band",
                'IF [Sales] > 100 THEN "High" ELSE "Low" END',
                'IF(\'Orders\'[Sales] > 100, "High", "Low")',
            ),
        ]
    )
    rule = one(run(model, tiny_target()), "CALCULATION_SEMANTIC_MATCH")
    assert rule.status == RuleStatus.WARNING.value
    assert "branch" in rule.note.lower()


def test_an_identical_aggregation_is_decidably_equivalent_and_passes():
    model = model_with(
        [
            Column(id="Orders.Sales", name="Sales", grain=Grain.ROW),
            calc("Total Sales", "SUM([Sales])", "SUM('Orders'[Sales])"),
        ]
    )
    rule = one(run(model, tiny_target()), "CALCULATION_SEMANTIC_MATCH")
    assert rule.status == RuleStatus.PASS.value


def test_a_literal_that_survived_unchanged_passes():
    model = model_with(
        [
            Column(id="Orders.Sales", name="Sales", grain=Grain.ROW),
            calc("Label", '"Total Sales:"', '"Total Sales:"'),
        ]
    )
    rule = one(run(model, tiny_target()), "CALCULATION_SEMANTIC_MATCH")
    assert rule.status == RuleStatus.PASS.value


def test_a_calculation_that_was_refused_is_not_applicable_not_failed():
    """The refusal is already counted by count parity and refusal integrity.

    Counting it a third time as a semantic failure would penalise honesty.
    """
    model = model_with(
        [
            Column(id="Orders.Sales", name="Sales", grain=Grain.ROW),
            calc("Rank", "INDEX()", None),
        ]
    )
    flags = [
        ConversionFlag(
            item="Orders.Rank",
            stage=Stage.TRANSLATE,
            status=ConversionStatus.AI_REQUIRED,
            severity=Severity.MANUAL,
            reason="Uses unsupported Tableau construct: INDEX",
            ref="Orders.Rank",
        )
    ]
    rule = one(run(model, tiny_target(), flags=flags), "CALCULATION_SEMANTIC_MATCH")
    assert rule.status == RuleStatus.NOT_APPLICABLE.value


def test_a_source_filter_that_was_not_carried_over_is_a_failure():
    model = tiny_model(
        visuals=[
            Visual(
                id="Sheet",
                name="Sheet",
                visual_type="bar",
                filters=[
                    VisualBinding(
                        role=BindingRole.FILTER,
                        field=FieldRef(column="Region"),
                        raw="Region",
                    )
                ],
            )
        ]
    )
    rule = one(run(model, tiny_target()), "FILTER_MAPPED")
    assert rule.status == RuleStatus.FAIL.value
    assert "Region" in rule.note


def test_a_parameter_becomes_a_what_if_table_or_the_check_fails():
    model = tiny_model(
        parameters=[
            Parameter(id="Growth", name="Growth", caption="Growth"),
            Parameter(id="Missing", name="Missing", caption="Missing"),
        ]
    )
    target = tiny_target(
        tables={
            "Orders": "table 'Orders'\n\n\tpartition 'Orders' = m\n\t\tmode: import\n",
            "Growth": "table 'Growth'\n\n\tcolumn 'Growth'\n\t\tdataType: double\n"
            "\t\tsourceColumn: Value\n\n\tpartition 'Growth' = calculated\n"
            "\t\tmode: import\n\t\tsource = {0}\n\n"
            "\tmeasure 'Growth Value' = SELECTEDVALUE('Growth'[Growth], 0)\n",
        }
    )
    statuses = {r.note.split(":")[0]: r.status for r in by_id(target and run(model, target), "PARAMETER_MAPPED")}
    assert statuses["Growth"] == RuleStatus.PASS.value
    assert statuses["Missing"] == RuleStatus.FAIL.value


# ---------------------------------------------------------------------------
# structural — count parity, format validity, dangling references
# ---------------------------------------------------------------------------


def test_a_dangling_reference_is_caught_and_is_blocking():
    """An emitted expression naming something never emitted breaks model load."""
    model = model_with(
        [
            Column(id="Orders.Sales", name="Sales", grain=Grain.ROW),
            calc("Ghost", "SUM([Nope])", "SUM('Orders'[Nope])"),
        ]
    )
    target = tiny_target(
        tables={
            "Orders": "table 'Orders'\n\n\tcolumn 'Sales'\n\t\tdataType: double\n"
            "\t\tsourceColumn: Sales\n\n"
            "\tmeasure 'Ghost' = SUM('Orders'[Nope])\n\n"
            "\tpartition 'Orders' = m\n\t\tmode: import\n"
        }
    )
    result = run(model, target)
    rule = one(result, "EXPRESSION_REFERENCES_RESOLVE")
    assert rule.status == RuleStatus.FAIL.value
    assert "Orders'[Nope]" in rule.note or "Orders[Nope]" in rule.note
    assert result.verdict is Verdict.FAILED


def test_a_resolvable_reference_is_not_reported_as_dangling(emitted):
    model, flags, target = emitted
    rule = one(run(model, target, flags=flags), "EXPRESSION_REFERENCES_RESOLVE")
    assert rule.status == RuleStatus.PASS.value, rule.note


def test_a_missing_partition_fails_format_validity(emitted):
    """Power BI rejects the entire model, so this is not a cosmetic defect."""
    model, flags, target = emitted
    damaged = {}
    removed = False
    for path, data in target.files.items():
        text = data.decode("utf-8")
        if not removed and "/tables/" in path and "\tpartition " in text:
            text = "\n".join(
                line for line in text.splitlines() if not line.startswith("\tpartition ")
            )
            removed = True
        damaged[path] = text.encode("utf-8")
    assert removed, "the fixture must really contain a partition to remove"

    result = run(model, TargetProject(files=damaged), flags=flags)
    rule = one(result, "SEMANTIC_MODEL_TABLE_PARTITIONS")
    assert rule.status == RuleStatus.FAIL.value
    assert result.verdict is Verdict.FAILED


def test_the_real_emitter_output_carries_a_partition_on_every_table(emitted):
    model, flags, target = emitted
    rule = one(run(model, target, flags=flags), "SEMANTIC_MODEL_TABLE_PARTITIONS")
    assert rule.status == RuleStatus.PASS.value, rule.note


def test_a_missing_pbip_manifest_fails_format_validity(emitted):
    model, flags, target = emitted
    stripped = {p: d for p, d in target.files.items() if not p.endswith(".pbip")}
    result = run(model, TargetProject(files=stripped), flags=flags)
    assert one(result, "PBIP_MANIFEST_PRESENT").status == RuleStatus.FAIL.value


def test_a_missing_report_definition_fails_format_validity(emitted):
    model, flags, target = emitted
    stripped = {
        p: d for p, d in target.files.items() if not p.endswith("definition.pbir")
    }
    result = run(model, TargetProject(files=stripped), flags=flags)
    assert one(result, "REPORT_DEFINITION_PRESENT").status == RuleStatus.FAIL.value


def test_count_parity_states_both_numbers(emitted):
    model, flags, target = emitted
    rule = one(run(model, target, flags=flags), "TABLE_COUNT_MATCH")
    assert "source" in rule.note and "target" in rule.note


def test_a_shortfall_every_bit_of_which_is_flagged_is_a_warning_not_a_pass():
    model = model_with(
        [
            Column(id="Orders.Sales", name="Sales", grain=Grain.ROW),
            calc("Rank", "INDEX()", None),
        ]
    )
    flags = [
        ConversionFlag(
            item="Orders.Rank",
            stage=Stage.TRANSLATE,
            status=ConversionStatus.AI_REQUIRED,
            severity=Severity.MANUAL,
            reason="Uses unsupported Tableau construct: INDEX",
            ref="Orders.Rank",
        )
    ]
    result = run(model, tiny_target(), flags=flags)
    assert one(result, "CALCULATION_COUNT_MATCH").status == RuleStatus.WARNING.value


def test_an_unexplained_shortfall_is_a_failure_not_a_warning():
    model = model_with(
        [
            Column(id="Orders.Sales", name="Sales", grain=Grain.ROW),
            calc("Rank", "INDEX()", None),
        ]
    )
    result = run(model, tiny_target(), flags=[])
    assert one(result, "CALCULATION_COUNT_MATCH").status == RuleStatus.FAIL.value


# ---------------------------------------------------------------------------
# refusal integrity — the silent drop this product exists to prevent
# ---------------------------------------------------------------------------


def test_refusal_integrity_catches_an_object_neither_converted_nor_reported():
    model = model_with(
        [
            Column(id="Orders.Sales", name="Sales", grain=Grain.ROW),
            calc("Rank", "INDEX()", None),
        ]
    )
    result = run(model, tiny_target(), flags=[])
    rule = one(result, "REFUSAL_INTEGRITY")
    assert rule.status == RuleStatus.FAIL.value
    assert "Orders.Rank" in rule.note
    assert result.verdict is Verdict.FAILED


def test_refusal_integrity_passes_when_every_gap_is_flagged():
    model = model_with(
        [
            Column(id="Orders.Sales", name="Sales", grain=Grain.ROW),
            calc("Rank", "INDEX()", None),
        ]
    )
    flags = [
        ConversionFlag(
            item="Orders.Rank",
            stage=Stage.TRANSLATE,
            status=ConversionStatus.AI_REQUIRED,
            severity=Severity.MANUAL,
            reason="Uses unsupported Tableau construct: INDEX",
            ref="Orders.Rank",
        )
    ]
    result = run(model, tiny_target(), flags=flags)
    assert one(result, "REFUSAL_INTEGRITY").status == RuleStatus.PASS.value


def test_a_dropped_dashboard_must_be_flagged_to_pass_refusal_integrity():
    model = tiny_model(dashboards=[Dashboard(id="Overview", name="Overview")])
    unflagged = run(model, tiny_target(), flags=[])
    assert one(unflagged, "REFUSAL_INTEGRITY").status == RuleStatus.FAIL.value
    flagged = run(
        model,
        tiny_target(),
        flags=[
            ConversionFlag(
                item="Overview",
                stage=Stage.MAP,
                status=ConversionStatus.UNSUPPORTED,
                severity=Severity.MANUAL,
                reason="Dashboard layout is not carried over",
                ref="Overview",
            )
        ],
    )
    assert one(flagged, "REFUSAL_INTEGRITY").status == RuleStatus.PASS.value


def test_the_real_conversion_reports_every_one_of_its_own_gaps(emitted):
    """The engine's refusals must survive the mapping into the contracts."""
    model, flags, target = emitted
    rule = one(run(model, target, flags=flags), "REFUSAL_INTEGRITY")
    assert rule.status == RuleStatus.PASS.value, rule.note


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_without_a_second_conversion_determinism_is_not_applicable_not_passed(emitted):
    """Treating an absent check as a pass is refused explicitly."""
    model, flags, target = emitted
    rule = one(run(model, target, flags=flags), "OUTPUT_DETERMINISTIC")
    assert rule.status == RuleStatus.NOT_APPLICABLE.value


def test_two_identical_conversions_pass_determinism(emitted):
    model, flags, target = emitted
    rule = one(
        run(model, target, flags=flags, replica=target), "OUTPUT_DETERMINISTIC"
    )
    assert rule.status == RuleStatus.PASS.value


def test_a_differing_second_conversion_fails_determinism_and_blocks(emitted):
    model, flags, target = emitted
    files = dict(target.files)
    victim = sorted(p for p in files if p.endswith(".tmdl"))[0]
    files[victim] = files[victim] + b"\n// drifted\n"
    result = run(model, target, flags=flags, replica=TargetProject(files=files))
    rule = one(result, "OUTPUT_DETERMINISTIC")
    assert rule.status == RuleStatus.FAIL.value
    assert victim in rule.note
    assert result.verdict is Verdict.FAILED


def test_the_real_engine_converts_the_same_workbook_the_same_way_twice():
    """The check the doc actually asks for: convert twice, diff."""
    data = (FIXTURES / "sample.twb").read_bytes()
    with tempfile.TemporaryDirectory(prefix="dbb-twice-") as tmp:
        first = convert_tableau_to_powerbi(data, Path(tmp) / "a", "Sample")
        second = convert_tableau_to_powerbi(data, Path(tmp) / "b", "Sample")
        a = TargetProject.from_dir(first.project_dir)
        b = TargetProject.from_dir(second.project_dir)
    assert a.digests() == b.digests()


# ---------------------------------------------------------------------------
# visual
# ---------------------------------------------------------------------------


def test_a_visual_whose_bindings_bound_nothing_is_not_a_pass():
    """Zero applicable bindings is not 'all bindings satisfied'."""
    model = tiny_model(
        visuals=[
            Visual(
                id="Sheet",
                name="Sheet",
                visual_type="bar",
                bindings=[
                    VisualBinding(
                        role=BindingRole.CATEGORY,
                        resolvable=False,
                        raw="fVal:sum:Sales:qk",
                    )
                ],
            )
        ]
    )
    target = tiny_target(
        pages={
            "p1": {
                "displayName": "Sheet",
                "_visual": {
                    "visual": {
                        "visualType": "clusteredBarChart",
                        "query": {"queryState": {}},
                    }
                },
            }
        }
    )
    rule = one(run(model, target), "VISUAL_BINDINGS_BOUND")
    assert rule.status == RuleStatus.FAIL.value


def test_a_visual_missing_from_the_target_fails_all_three_visual_checks():
    model = tiny_model(
        visuals=[Visual(id="Sheet", name="Sheet", visual_type="bar")]
    )
    result = run(model, tiny_target())
    for rule_id in (
        "VISUAL_TYPE_PRESENT",
        "VISUAL_BINDINGS_BOUND",
        "VISUAL_TITLE_CARRIED",
    ):
        assert one(result, rule_id).status == RuleStatus.FAIL.value


def test_an_unrecognised_source_mark_type_is_a_warning_not_a_pass():
    """The emitted type is a substitute, not the source's type."""
    model = tiny_model(
        visuals=[Visual(id="Sheet", name="Sheet", visual_type="unknown")]
    )
    target = tiny_target(
        pages={
            "p1": {
                "displayName": "Sheet",
                "_visual": {
                    "visual": {"visualType": "tableEx", "query": {"queryState": {}}}
                },
            }
        }
    )
    rule = one(run(model, target), "VISUAL_TYPE_PRESENT")
    assert rule.status == RuleStatus.WARNING.value


def test_the_real_report_carries_every_worksheet_name_as_a_page(emitted):
    model, flags, target = emitted
    result = run(model, target, flags=flags)
    titles = by_id(result, "VISUAL_TITLE_CARRIED")
    assert titles and all(r.status == RuleStatus.PASS.value for r in titles)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _project(client) -> str:
    return client.post(
        f"{PREFIX}/projects",
        json={
            "source_platform": "tableau",
            "target_platform": "powerbi",
            "name": "Validation test",
        },
    ).json()["project_id"]


def _converted(client) -> str:
    project_id = _project(client)
    client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={
            "file": (
                "sample.twb",
                (FIXTURES / "sample.twb").read_bytes(),
                "application/octet-stream",
            )
        },
    )
    client.post(f"{PREFIX}/projects/{project_id}/analysis")
    started = client.post(
        f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False}
    )
    assert started.status_code == 202, started.text
    return project_id


def test_validating_before_conversion_is_refused_in_the_users_terms(api):
    project_id = _project(api.client)
    response = api.client.post(f"{PREFIX}/projects/{project_id}/validation")
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["category"] == "VALIDATION_ERROR"
    assert "Traceback" not in body["message"]
    assert "409" not in body["message"]


def test_reading_a_validation_that_was_never_run_is_a_typed_404(api):
    project_id = _converted(api.client)
    response = api.client.get(f"{PREFIX}/projects/{project_id}/validation")
    assert response.status_code == 404
    assert response.json()["category"] == "NOT_FOUND"


def test_validation_returns_a_job_naming_its_kind(api):
    project_id = _converted(api.client)
    response = api.client.post(f"{PREFIX}/projects/{project_id}/validation")
    assert response.status_code == 202, response.text
    assert response.json()["kind"] == "validation"


def test_the_validation_result_is_readable_afterwards_and_states_its_denominators(api):
    project_id = _converted(api.client)
    api.client.post(f"{PREFIX}/projects/{project_id}/validation")
    body = api.client.get(f"{PREFIX}/projects/{project_id}/validation").json()

    assert body["numerical"] == {
        "measured": False,
        "reason": body["numerical"]["reason"],
    }
    assert body["numerical"]["measured"] is False
    assert body["verdict"] in {
        "verified",
        "partially_verified",
        "unverified",
        "failed",
    }
    assert body["formula"]
    for category in body["categories"].values():
        assert category["checks"] > 0


def test_the_api_runs_the_determinism_check_for_real(api):
    """The endpoint reconverts and diffs, so OUTPUT_DETERMINISTIC is decided."""
    project_id = _converted(api.client)
    api.client.post(f"{PREFIX}/projects/{project_id}/validation")
    body = api.client.get(f"{PREFIX}/projects/{project_id}/validation").json()
    rule = [r for r in body["rules"] if r["rule_id"] == "OUTPUT_DETERMINISTIC"][0]
    assert rule["status"] == "PASS"


def test_validating_twice_gives_the_same_answer(api):
    project_id = _converted(api.client)
    api.client.post(f"{PREFIX}/projects/{project_id}/validation")
    first = api.client.get(f"{PREFIX}/projects/{project_id}/validation").json()
    api.client.post(f"{PREFIX}/projects/{project_id}/validation")
    second = api.client.get(f"{PREFIX}/projects/{project_id}/validation").json()
    for body in (first, second):
        body.pop("validation_id")
    assert first == second


def test_the_api_never_returns_a_numerical_score(api):
    project_id = _converted(api.client)
    api.client.post(f"{PREFIX}/projects/{project_id}/validation")
    raw = api.client.get(f"{PREFIX}/projects/{project_id}/validation").text
    body = json.loads(raw)
    assert set(body["numerical"]) == {"measured", "reason"}
    assert "numerical" not in body["categories"]


# ---------------------------------------------------------------------------
# A workbook whose tables reuse each other's field names
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def clashing() -> tuple[CanonicalModel, list[ConversionFlag], TargetProject]:
    """`clashes.twb` converted, and the project it wrote to disk."""
    with tempfile.TemporaryDirectory(prefix="dbb-clashes-") as tmp:
        outcome = convert_tableau_to_powerbi(
            (FIXTURES / "clashes.twb").read_bytes(), Path(tmp) / "p", "Clashes"
        )
        target = TargetProject.from_dir(outcome.project_dir)
    return outcome.model, outcome.flags, target


def test_a_workbook_full_of_name_clashes_produces_a_usable_project(clashing):
    """The checks are the second opinion on `P3.2`'s scoping.

    They re-read the produced PBIP with their own parser, so a resolver that
    emitted a reference to the wrong table's field shows up here as a dangling
    reference rather than as a plausible number in a report.
    """
    model, flags, target = clashing
    result = run(model, target, flags=flags)

    assert result.verdict is not Verdict.FAILED
    failures = [rule for rule in result.rules if rule.status == RuleStatus.FAIL.value]
    assert failures == [], [f"{r.rule_id}: {r.note}" for r in failures]


def test_the_clashing_workbook_binds_every_reference_it_emits(clashing):
    model, flags, target = clashing
    result = run(model, target, flags=flags)

    for rule_id in (
        "EXPRESSION_REFERENCES_RESOLVE",
        "VISUAL_BINDING_REFERENCES_RESOLVE",
        "SEMANTIC_MODEL_TABLE_REFS_RESOLVE",
    ):
        found = by_id(result, rule_id)
        # A rule id that no longer exists makes this test assert nothing at all,
        # silently. It was written once with a name that was never a rule.
        assert found, f"{rule_id} is not a rule this validator runs"
        for rule in found:
            assert rule.status != RuleStatus.FAIL.value, f"{rule_id}: {rule.note}"


# ---------------------------------------------------------------------------
# reference resolution reads DAX, rather than pattern-matching it
# ---------------------------------------------------------------------------


def _model_with_expression(expression: str) -> TargetProject:
    """A target whose one measure contains `expression`."""
    return tiny_target(
        {
            "Orders": (
                "table 'Orders'\n\n"
                "\tcolumn 'Sales'\n\t\tdataType: double\n\t\tsourceColumn: Sales\n\n"
                f"\tmeasure 'Labelled' = {expression}\n\n"
                "\tpartition 'Orders' = m\n\t\tmode: import\n"
                "\t\tsource = let Source = #table(type table [], {}) in Source\n"
            )
        }
    )


def test_a_bracket_inside_a_string_literal_is_not_a_dangling_reference():
    """The false failure this check used to produce.

    A label a person typed - `"see [Ghost] for detail"` - is text, not a
    dependency. Reporting it makes a correct model fail its own validation, and
    the report then names a column that was never meant to exist.
    """
    target = _model_with_expression('CONCATENATE("see [Ghost] for detail", \'Orders\'[Sales])')

    result = run(tiny_model(), target)

    rule = one(result, "EXPRESSION_REFERENCES_RESOLVE")
    assert rule.status != RuleStatus.FAIL.value, rule.note


def test_a_reference_in_a_comment_is_not_a_dangling_reference():
    """A line a developer commented out is not a line that runs."""
    target = _model_with_expression("SUM('Orders'[Sales]) // was [Ghost]")

    result = run(tiny_model(), target)

    rule = one(result, "EXPRESSION_REFERENCES_RESOLVE")
    assert rule.status != RuleStatus.FAIL.value, rule.note


def test_an_unquoted_table_reference_is_checked_as_a_column():
    """`Orders[Ghost]` is a column that does not exist, not a measure.

    The old pattern required a quoted table, so it saw no qualified reference
    here at all - and then matched `[Ghost]` as a bare measure reference. The
    check still failed, but for the wrong reason and with the wrong message,
    which is what a person reads.
    """
    target = _model_with_expression("SUM(Orders[Ghost])")

    result = run(tiny_model(), target)

    rule = one(result, "EXPRESSION_REFERENCES_RESOLVE")
    assert rule.status == RuleStatus.FAIL.value
    assert "Orders[Ghost]" in rule.note


def test_a_real_reference_is_still_resolved():
    target = _model_with_expression("SUM(Orders[Sales])")

    result = run(tiny_model(), target)

    assert one(result, "EXPRESSION_REFERENCES_RESOLVE").status == RuleStatus.PASS.value
