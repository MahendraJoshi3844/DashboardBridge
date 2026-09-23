"""Decide whether a Tableau calc becomes a DAX measure or a calculated column.

Tableau has no measure/column distinction: aggregation is chosen at the shelf, at
query time. Power BI must commit at definition time. That mismatch is the single
biggest source of invalid generated DAX, so this module answers one question —
what grain does this expression evaluate at? — and refuses when the answer is
genuinely ambiguous rather than guessing an aggregation the author never wrote.

Rules (a reference is a column, a parameter, or another calc):
  * every column reference sits inside an aggregation  -> measure
  * no aggregation anywhere, only column references    -> calculated column
  * an aggregation wraps a measure                     -> refuse
  * a row-level column sits beside a measure/parameter -> refuse (which
    aggregation the author intended is unknowable from the formula alone)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from engines.t2pbi.core.dax.refs import REF_RE

# Tableau aggregation functions. A reference inside one of these evaluates at the
# aggregate grain; anything else evaluates row by row.
_AGGREGATIONS = frozenset(
    {
        "SUM", "AVG", "MIN", "MAX", "COUNT", "COUNTD", "MEDIAN",
        "STDEV", "STDEVP", "VAR", "VARP", "ATTR",
    }
)

_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")

#: The model's own words, imported rather than restated: two spellings of
#: one vocabulary is one that drifts.
from engines.t2pbi.ir.model import AGGREGATE, ROW  # noqa: E402


@dataclass
class GrainVerdict:
    """`grain` is None when it cannot be determined without guessing."""

    grain: str | None
    reason: str | None = None


def _aggregated_spans(expr: str) -> list[tuple[int, int]]:
    """Character spans covered by an aggregation call's parentheses."""
    spans: list[tuple[int, int]] = []
    for match in _CALL_RE.finditer(expr):
        if match.group(1).upper() not in _AGGREGATIONS:
            continue
        if _inside_brackets(expr, match.start()):
            continue  # a field name like [Sum of Things], not a call
        depth = 0
        for i in range(match.end() - 1, len(expr)):
            if expr[i] == "(":
                depth += 1
            elif expr[i] == ")":
                depth -= 1
                if depth == 0:
                    spans.append((match.start(), i))
                    break
    return spans


def _inside_brackets(expr: str, pos: int) -> bool:
    return expr.count("[", 0, pos) > expr.count("]", 0, pos)


def classify_calc(
    formula: str, calc_grains: dict[str, str], param_aliases: set[str]
) -> GrainVerdict:
    """Classify one Tableau calc given what its referenced names already are.

    `calc_grains` maps a lower-cased calc alias to AGGREGATE or ROW; a reference
    to a parameter behaves like a measure (it reads a slicer selection).
    """
    spans = _aggregated_spans(formula)

    def is_aggregated(pos: int) -> bool:
        return any(start <= pos <= end for start, end in spans)

    saw_bare_column = False
    saw_aggregated_column = False
    saw_bare_measure = False

    for match in REF_RE.finditer(formula):
        name = match.group(1).lower()
        aggregated = is_aggregated(match.start())
        referenced_grain = calc_grains.get(name)
        is_aggregate_like = name in param_aliases or referenced_grain == AGGREGATE

        if is_aggregate_like:
            if aggregated:
                return GrainVerdict(
                    None,
                    f"Cannot aggregate '{match.group(1)}': it converts to a measure, "
                    "and DAX aggregations take a column.",
                )
            saw_bare_measure = True
        elif aggregated:
            saw_aggregated_column = True
        else:
            saw_bare_column = True

    if saw_bare_column and (saw_bare_measure or saw_aggregated_column):
        return GrainVerdict(
            None,
            "Mixes a row-level column with an aggregate or parameter; the intended "
            "aggregation is not stated in the formula.",
        )
    if saw_bare_column:
        return GrainVerdict(ROW)
    # Only aggregated columns, measures/parameters, or pure constants remain.
    return GrainVerdict(AGGREGATE)
