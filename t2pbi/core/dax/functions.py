"""The tables the DAX translator reads, built from the rule pack (`P3.1`).

The mappings used to be Python literals here. They are now YAML in `rules/`, so
they can be reviewed, diffed and versioned (06-conversion-engine.md, "Rule
engine"), and so a translation can cite the rule that produced it.

These names stay because they are the translator's vocabulary and every caller
already speaks it; what changed is where the values come from. Grow coverage by
adding a rule to `rules/functions.yaml`, not by editing this file.

See docs/specs/modules/dax.md.
"""

from __future__ import annotations

from t2pbi.core.dax.rules import function_rules, refusal_rules

# Tableau function name -> DAX function name (same-arity, direct substitution).
SUPPORTED_FUNCS: dict[str, str] = {
    rule.source_function: rule.target_function for rule in function_rules()
}

# DAX function names the translator may legitimately emit (so validation passes
# on tokens it produced itself, e.g. control-flow rewrites and null helpers).
#
# Not in the pack: these are not mappings from anything. They are what the
# translator writes on its own when rewriting control flow, and a rule pack
# describing them would be describing the translator, not the source language.
ALLOWED_DAX_FUNCS: frozenset[str] = frozenset(
    {"IF", "SWITCH", "TRUE", "COALESCE", "COALESCE_ZN", "DATEDIFF"}
)

# Substrings whose presence immediately disqualifies a formula (v1 cannot convert).
UNSUPPORTED_MARKERS: tuple[str, ...] = tuple(
    rule.marker for rule in refusal_rules()
)

#: Why each marker is refused, in the words a person reads. Keyed by marker so
#: the translator can answer "why" without carrying the sentence itself.
REFUSAL_REASONS: dict[str, str] = {
    rule.marker: rule.reason for rule in refusal_rules()
}
