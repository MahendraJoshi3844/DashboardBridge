"""Analysis: a stored artifact becomes a canonical model plus the numbers the
metadata dashboard shows.

Everything here is derived from the adapter's output. Nothing is estimated, and
nothing is displayed that was not counted — the complexity score travels with
the formula that produced it, because a score whose derivation a reader cannot
follow is decoration.
"""

from __future__ import annotations

from dashboardbridge_contracts import (
    CanonicalModel,
    Compatibility,
    Complexity,
    ConversionFlag,
    Inventory,
)
from dashboardbridge_contracts.enums import ConversionStatus

# What makes a migration expensive, relative to a plain column.
#
# A calculated field must be read, classified for grain, translated, and often
# reviewed by a person; a column is copied. The ratios are judgement, but they
# are *stated* judgement, and they are published with every score so a reader
# can disagree with them specifically rather than distrust the number.
_WEIGHTS: dict[str, float] = {
    "calculations": 5.0,
    "visuals": 3.0,
    "parameters": 2.0,
    "relationships": 2.0,
    "dashboards": 2.0,
    "tables": 1.0,
    "columns": 0.5,
}
_MAX_WEIGHT = max(_WEIGHTS.values())

FORMULA = (
    "score = Σ(count × weight) / (total objects × 5); "
    "weights: calculation 5, visual 3, parameter 2, relationship 2, "
    "dashboard 2, table 1, column 0.5. "
    "1.0 would mean the workbook is nothing but calculated fields."
)


def inventory_of(model: CanonicalModel) -> Inventory:
    """Count what is actually in the model. No estimates."""
    columns = model.all_columns()
    return Inventory(
        datasources=len(model.datasources),
        tables=len(model.all_tables()),
        columns=len(columns),
        calculations=sum(1 for column in columns if column.is_calculated),
        visuals=len(model.visuals),
        parameters=len(model.parameters),
        relationships=len(model.relationships),
        dashboards=len(model.dashboards),
    )


def complexity_of(inventory: Inventory) -> Complexity:
    """How much of this workbook is made of the expensive things?

    Self-normalising, so it does not reward or punish sheer size: a thousand
    plain columns is a big migration but not a hard one, and the score says so.
    """
    counts = inventory.model_dump()
    total = sum(counts.get(kind, 0) for kind in _WEIGHTS)
    if total == 0:
        return Complexity(score=0.0, band="low", formula=FORMULA)

    effort = sum(counts.get(kind, 0) * weight for kind, weight in _WEIGHTS.items())
    score = min(1.0, effort / (total * _MAX_WEIGHT))
    return Complexity(score=round(score, 4), band=_band(score), formula=FORMULA)


def _band(score: float) -> str:
    if score < 0.33:
        return "low"
    if score < 0.66:
        return "moderate"
    return "high"


def compatibility_of(
    inventory: Inventory, flags: list[ConversionFlag]
) -> Compatibility:
    """What became of each object, on the status axis (ADR-004).

    `total` is the number of objects considered, so the parts always sum to the
    whole and a reader can check the arithmetic. An object with no flag
    converted cleanly.
    """
    considered = (
        inventory.columns
        + inventory.visuals
        + inventory.parameters
        + inventory.relationships
        + inventory.tables
    )
    tally = {status: 0 for status in ConversionStatus}
    for flag in flags:
        tally[flag.status] += 1

    flagged = sum(count for status, count in tally.items() if status is not ConversionStatus.CONVERTED)
    return Compatibility(
        converted=max(considered - flagged, 0),
        partial=tally[ConversionStatus.PARTIAL],
        ai_required=tally[ConversionStatus.AI_REQUIRED],
        unsupported=tally[ConversionStatus.UNSUPPORTED],
        failed=tally[ConversionStatus.FAILED],
        total=max(considered, flagged),
    )
