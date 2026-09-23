"""Validation: what the product is allowed to claim about a conversion.

This module is only arithmetic and vocabulary. Every judgement about the
conversion is made in `checks`, against the artifact re-read by `target`; here
those judgements are counted, weighted and named. Keeping the scoring separate
from the rules is what makes the score auditable: a reader can check the
arithmetic without reading a single rule, and a rule can be argued with without
touching the score.

Three decisions are load-bearing, and none of them is a preference.

**A category with no applicable checks is excluded, not scored 1.0.** Scoring an
absent check as a pass is how validation becomes theatre — a workbook with no
visuals would otherwise earn a fifth of its score for having nothing to get
wrong (08-validation-engine, *Scoring*).

**A category weighted 0.0 is not run at all.** Weight zero says "do not judge
this", so producing rules for it — and letting one of them block the verdict —
would be judging it anyway. The consequence is that `weights` selects as well as
weights, which is stated here because it is not obvious from the name.

**VERIFIED requires every applicable check to have passed.** Neither the spec
nor the ADRs fix a threshold, and any number below 1.0 would be one I invented:
"verified at 0.9" means nine in ten of the things we checked were true, which is
not what the word promises a reader. Everything measured but imperfect is
`partially_verified`, which is less flattering and is the point (§63).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from dashboardbridge_contracts import (
    CanonicalModel,
    CategoryScore,
    ConversionFlag,
    Validation,
    ValidationRuleResult,
)
from dashboardbridge_contracts.enums import JobStatus, Verdict

from engines.validation.checks import (
    BLOCKING,
    SEMANTIC,
    STRUCTURAL,
    VISUAL,
    Check,
    RuleStatus,
    semantic_checks,
    structural_checks,
    visual_checks,
)
from engines.validation.target import TargetProject

__all__ = ["RuleStatus", "TargetProject", "Validation", "validate", "DEFAULT_WEIGHTS"]

#: Structural failure means the model does not open; a visual difference is
#: cosmetic and repairable. The weights say so (08-validation-engine).
DEFAULT_WEIGHTS: Mapping[str, float] = {STRUCTURAL: 0.4, SEMANTIC: 0.4, VISUAL: 0.2}

#: Fixed, so two runs of the same conversion diff to nothing.
_ORDER = (STRUCTURAL, SEMANTIC, VISUAL)


def validate(
    *,
    validation_id: UUID,
    model: CanonicalModel,
    target: TargetProject,
    flags: Sequence[ConversionFlag] = (),
    replica: TargetProject | None = None,
    weights: Mapping[str, float] | None = None,
) -> Validation:
    """Judge a conversion against the project it actually wrote to disk.

    `replica` is a second conversion of the same source. Without one the
    determinism rule reports NOT_APPLICABLE rather than passing, because an
    unrun check is not a satisfied one.
    """
    weighting = {**DEFAULT_WEIGHTS, **(weights or {})}
    checks = _run(model, flags, target, replica, weighting)

    categories = {
        name: score
        for name in _ORDER
        if (score := _score(checks.get(name, ()))) is not None
    }
    measured = {name: weighting[name] for name in categories}
    total = sum(measured.values())
    score = (
        round(
            sum(categories[name].score * weight for name, weight in measured.items())
            / total,
            4,
        )
        if total
        else None
    )

    ordered = [check for name in _ORDER for check in checks.get(name, ())]
    return Validation(
        validation_id=validation_id,
        status=JobStatus.COMPLETED,
        verdict=_verdict(ordered, categories, score),
        score=score,
        formula=_formula(categories, measured, total, score),
        categories=categories,
        rules=[
            ValidationRuleResult(
                rule_id=check.rule_id, status=check.status.value, note=check.note
            )
            for check in ordered
        ],
    )


def _run(
    model: CanonicalModel,
    flags: Sequence[ConversionFlag],
    target: TargetProject,
    replica: TargetProject | None,
    weighting: Mapping[str, float],
) -> dict[str, list[Check]]:
    """Only the categories that will be scored. See the module docstring."""
    checks: dict[str, list[Check]] = {}
    if weighting.get(STRUCTURAL, 0.0) > 0.0:
        checks[STRUCTURAL], _ = structural_checks(model, flags, target, replica)
    if weighting.get(SEMANTIC, 0.0) > 0.0:
        checks[SEMANTIC] = semantic_checks(model, target)
    if weighting.get(VISUAL, 0.0) > 0.0:
        checks[VISUAL] = visual_checks(model, target)
    return checks


def _score(checks: Sequence[Check]) -> CategoryScore | None:
    """`passed / applicable`, or nothing at all.

    NOT_APPLICABLE leaves the denominator; WARNING and FAIL stay in it and are
    not passes. A category whose checks were all inapplicable has measured
    nothing, and returns None so it is excluded rather than scored.
    """
    applicable = [c for c in checks if c.status is not RuleStatus.NOT_APPLICABLE]
    if not applicable:
        return None
    passed = sum(1 for c in applicable if c.status is RuleStatus.PASS)
    return CategoryScore(
        score=round(passed / len(applicable), 4),
        checks=len(applicable),
        passed=passed,
    )


def _verdict(
    checks: Sequence[Check],
    categories: Mapping[str, CategoryScore],
    score: float | None,
) -> Verdict:
    """FAILED outranks everything: a blocking rule that failed means the target
    is not a usable Power BI project, or the report of it is untrue. Neither is
    improved by a good score elsewhere."""
    if any(c.status is RuleStatus.FAIL and c.rule_id in BLOCKING for c in checks):
        return Verdict.FAILED
    if not categories or score is None:
        return Verdict.UNVERIFIED
    return Verdict.VERIFIED if score == 1.0 else Verdict.PARTIALLY_VERIFIED


def _formula(
    categories: Mapping[str, CategoryScore],
    measured: Mapping[str, float],
    total: float,
    score: float | None,
) -> str:
    """The derivation, published beside the score.

    A score whose derivation a reader cannot follow is decoration. Only measured
    categories appear, so the formula also shows what was *not* judged by its
    absence.
    """
    if not categories:
        return (
            "No category had an applicable check, so no score was computed. "
            "passed/applicable is undefined over an empty set."
        )
    terms = " + ".join(
        f"{measured[name]} × {name} {categories[name].passed}/"
        f"{categories[name].checks}"
        for name in categories
    )
    return (
        f"score = ({terms}) / {round(total, 4)} = {score}, "
        "where each term is that category's passed/applicable checks. "
        "Categories with no applicable check are excluded from both sides."
    )
