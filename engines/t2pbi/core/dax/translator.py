"""Tableau calc -> DAX. Translate only if fully supported; else return None + reason.

We NEVER emit guessed or half-converted DAX. The residual-keyword safety net at the
end is the backstop for the project's #1 trust rule: a measure that still contains
Tableau control-flow keywords (THEN/ELSE/CASE/WHEN/END) is invalid DAX and must be
flagged for manual work, never written. See docs/specs/modules/dax.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from engines.t2pbi.core.dax.functions import ALLOWED_DAX_FUNCS, SUPPORTED_FUNCS, UNSUPPORTED_MARKERS
from engines.t2pbi.core.dax.refs import REF_RE
from engines.t2pbi.core.dax.rules import rule_for_function

# Optional [Datasource]. qualifier then the [Field] itself. One pass so that the
# column part of an already-emitted 'Table'[Col] is never re-matched.
_FIELD_RE = re.compile(r"\[([^\[\]]+)\]")
_FUNC_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
# Tableau conditional keyword. The negative lookahead skips DAX-style IF( that we
# emit ourselves, so a converted block is not re-detected as a new conditional.
_COND_START_RE = re.compile(r"\b(IF|CASE)\b(?!\()", re.IGNORECASE)
_END_RE = re.compile(r"\bEND\b", re.IGNORECASE)
# Tableau control-flow keywords that must NOT survive into emitted DAX.
_RESIDUAL_KW_RE = re.compile(r"\b(THEN|ELSEIF|ELSE|WHEN|CASE|END)\b", re.IGNORECASE)
# One DATEDIFF argument: bare text, or a call whose own parentheses close again.
# The previous `([^,)]+)\)` stopped at the first `)`, so `TODAY()` was cut after
# `TODAY(` and `DATEDIFF('Orders'[Order Date], TODAY(, DAY))` - malformed DAX -
# was emitted with no flag. `([^,]+)` had the same blind spot for a comma inside
# a nested call. Balanced nesting is not a regular language, so one level is all
# this can express; `_DATEDIFF_LEFTOVER_RE` refuses what it fails to match rather
# than let a half-converted call through.
_DATEDIFF_ARG = r"(?:[^,()]|\([^()]*\))+"
_DATEDIFF_RE = re.compile(
    rf"\bDATEDIFF\s*\(\s*['\"](\w+)['\"]\s*,({_DATEDIFF_ARG}),({_DATEDIFF_ARG})\)",
    re.IGNORECASE,
)
#: A DATEDIFF still in Tableau form - quoted date-part first - after conversion
#: ran. It means the pattern above did not match, so the quoted literal would be
#: emitted as DAX's first argument, which is not valid DAX.
_DATEDIFF_LEFTOVER_RE = re.compile(
    r"\bDATEDIFF\s*\(\s*['\"]\w+['\"]\s*,", re.IGNORECASE
)

_DATEPART = {
    "year": "YEAR",
    "quarter": "QUARTER",
    "month": "MONTH",
    "week": "WEEK",
    "day": "DAY",
    "hour": "HOUR",
    "minute": "MINUTE",
    "second": "SECOND",
}


class _Unconvertible(Exception):
    """Raised internally when a construct cannot be safely converted."""


@dataclass
class TranslationContext:
    """What the translator needs to resolve references correctly.

    Without context the translator still works (used by unit tests with a single
    table); the pipeline passes a populated context so parameter, measure, and
    cross-table references resolve to valid DAX.
    """

    # lower-cased field/caption -> owning table name (columns only)
    field_to_table: dict[str, str] = field(default_factory=dict)
    # table name -> set of lower-cased column names it owns (for local priority)
    columns_by_table: dict[str, set[str]] = field(default_factory=dict)
    # lower-cased column alias -> the name that column is actually emitted under.
    # A calc may reference a column by its raw Tableau name while TMDL names the
    # column by its caption; without this the DAX points at a name that isn't there.
    column_display: dict[str, str] = field(default_factory=dict)
    # lower-cased measure alias (raw name OR caption) -> emitted display name.
    # Refs may use either alias; the emitted measure is named by its display name.
    measures: dict[str, str] = field(default_factory=dict)
    # lower-cased param name OR caption -> what-if value measure name
    param_value_measures: dict[str, str] = field(default_factory=dict)


@dataclass
class TranslationResult:
    dax: str | None
    reason: str | None = None
    #: Every rule-pack mapping this translation applied, sorted so two runs of
    #: one formula cite the same thing in the same order. Empty is a fact and
    #: not a gap: a control-flow rewrite is the translator's own work, and no
    #: function mapping fired for it.
    rule_ids: tuple[str, ...] = ()


def translate_formula(
    formula: str, table_name: str, ctx: TranslationContext | None = None
) -> TranslationResult:
    if formula is None or not formula.strip():
        return TranslationResult(None, "Empty formula.")
    ctx = ctx or TranslationContext()
    expr = _normalize_string_literals(formula.strip())

    # 1) Hard stops: any unsupported construct disqualifies the whole formula.
    #    Scan with literals and [field names] blanked, so a column called
    #    [Fixed Cost] is not mistaken for a FIXED level-of-detail expression.
    upper = _mask(expr, brackets=True).upper()
    for marker in UNSUPPORTED_MARKERS:
        if marker in upper:
            return TranslationResult(
                None, f"Uses unsupported Tableau construct: {marker.rstrip('(')}"
            )

    if expr.count("[") != expr.count("]"):
        return TranslationResult(None, "Could not parse: unbalanced brackets.")

    try:
        # 2) Conditionals: IF/ELSEIF/THEN/ELSE/END and CASE/WHEN -> IF()/SWITCH().
        expr = _convert_conditionals(expr)

        # 3) DATEDIFF('unit', a, b) -> DATEDIFF(a, b, UNIT) (arg reorder).
        expr = _convert_datediff(expr)

        # 4) Null helpers / safe divide.
        expr = re.sub(r"\bZN\s*\(", "COALESCE_ZN(", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\bIFNULL\s*\(", "COALESCE(", expr, flags=re.IGNORECASE)

        # 5) Validate + map every function-like token, recording which rules
        #    did the mapping so the translation can cite them.
        expr, applied = _map_functions(expr)
        expr = _expand_zn(expr)

        # 6) Resolve references (params -> value measures, calcs -> measures,
        #    columns -> 'Table'[Column], qualified cross-table refs).
        expr = _resolve_references(expr, table_name, ctx)
    except _Unconvertible as exc:
        return TranslationResult(None, str(exc))

    # 7) Safety net: no Tableau control-flow keyword may survive.
    if _RESIDUAL_KW_RE.search(_mask(expr)):
        return TranslationResult(
            None, "Could not fully convert control-flow (CASE/IF) to valid DAX."
        )

    return TranslationResult(expr.strip(), None, tuple(sorted(applied)))


def _normalize_string_literals(expr: str) -> str:
    """Rewrite Tableau 'single-quoted' literals as DAX "double-quoted" ones.

    DAX reads 'West' as a reference to a table named West, so a surviving single
    -quoted literal produces DAX that will not validate. Tableau escapes an inner
    quote by doubling it ('O''Fallon'), and DAX escapes with "" the same way.
    """
    out: list[str] = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch == '"':  # already a DAX literal - copy through verbatim
            j = i + 1
            while j < len(expr):
                if expr[j] == '"' and expr[j + 1 : j + 2] == '"':
                    j += 2
                    continue
                if expr[j] == '"':
                    break
                j += 1
            out.append(expr[i : j + 1])
            i = j + 1
            continue
        if ch == "'":
            j = i + 1
            body: list[str] = []
            while j < len(expr):
                if expr[j] == "'" and expr[j + 1 : j + 2] == "'":
                    body.append("'")
                    j += 2
                    continue
                if expr[j] == "'":
                    break
                body.append(expr[j])
                j += 1
            out.append('"' + "".join(body).replace('"', '""') + '"')
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _mask(expr: str, brackets: bool = False) -> str:
    """Same-length copy with string literals (and optionally [field names]) blanked.

    Keeping the length identical means every offset found in the mask indexes the
    original string, so we can detect keywords while ignoring text that merely
    looks like one inside a literal or a field name.
    """
    out = list(expr)
    i = 0
    while i < len(expr):
        if expr[i] == '"':
            j = i + 1
            while j < len(expr):
                if expr[j] == '"' and expr[j + 1 : j + 2] == '"':
                    j += 2
                    continue
                if expr[j] == '"':
                    break
                j += 1
            for k in range(i + 1, min(j, len(expr))):
                out[k] = "x"
            i = j + 1
            continue
        if brackets and expr[i] == "[":
            j = expr.find("]", i + 1)
            if j == -1:
                break
            for k in range(i + 1, j):
                out[k] = "x"
            i = j + 1
            continue
        i += 1
    return "".join(out)


def _split_on_keyword(
    text: str, keyword: str, maxsplit: int = 0
) -> list[str]:
    """Split on a bare keyword, ignoring occurrences inside string literals."""
    masked = _mask(text)
    pattern = re.compile(rf"\b{keyword}\b", re.IGNORECASE)
    parts: list[str] = []
    last = 0
    for count, m in enumerate(pattern.finditer(masked)):
        if maxsplit and count >= maxsplit:
            break
        parts.append(text[last : m.start()])
        last = m.end()
    parts.append(text[last:])
    return parts


def _convert_conditionals(expr: str) -> str:
    """Repeatedly collapse the innermost IF/CASE...END block into IF()/SWITCH()."""
    guard = 0
    while True:
        # Detect on a literal-masked copy so that a keyword inside a string (e.g.
        # CONTAINS([Name], "END")) never terminates a block. Offsets still index
        # the real expression because masking preserves length.
        masked = _mask(expr)
        starts = list(_COND_START_RE.finditer(masked))
        if not starts:
            return expr
        guard += 1
        if guard > 200:
            raise _Unconvertible("Conditional nesting too deep to convert safely.")
        start = starts[-1]  # rightmost start == innermost block
        m_end = _END_RE.search(masked, start.end())
        if not m_end:
            raise _Unconvertible("Conditional (IF/CASE) without matching END.")
        block = expr[start.start() : m_end.end()]
        converted = _convert_one_block(block)
        expr = expr[: start.start()] + converted + expr[m_end.end() :]


def _convert_one_block(block: str) -> str:
    """Convert a single-level IF/CASE...END block (no nested IF/CASE inside)."""
    kind = _COND_START_RE.match(block).group(1).upper()
    # Strip the leading IF/CASE keyword and the trailing END that bound the block.
    inner = block[len(kind) :]
    inner = inner[: _mask(inner).upper().rindex("END")].strip()

    if kind == "CASE":
        segs = _split_on_keyword(inner, "WHEN")
        subject = segs[0].strip()
        args = [subject]
        else_val = None
        for seg in segs[1:]:
            when_then = _split_on_keyword(seg, "THEN", maxsplit=1)
            if len(when_then) != 2:
                raise _Unconvertible("Malformed CASE/WHEN/THEN.")
            value = when_then[0].strip()
            rest = _split_on_keyword(when_then[1], "ELSE", maxsplit=1)
            args.extend([value, rest[0].strip()])
            if len(rest) > 1:
                else_val = rest[1].strip()
        if else_val is not None:
            args.append(else_val)
        return "SWITCH(" + ", ".join(args) + ")"

    # IF [ELSEIF...]* [ELSE] END
    branches = _split_on_keyword(inner, "ELSEIF")
    conds: list[str] = []
    results: list[str] = []
    else_val = None
    for branch in branches:
        ct = _split_on_keyword(branch, "THEN", maxsplit=1)
        if len(ct) != 2:
            raise _Unconvertible("Malformed IF/THEN.")
        cond = ct[0].strip()
        rest = _split_on_keyword(ct[1], "ELSE", maxsplit=1)
        conds.append(cond)
        results.append(rest[0].strip())
        if len(rest) > 1:
            else_val = rest[1].strip()

    if len(conds) == 1:
        if else_val is not None:
            return f"IF({conds[0]}, {results[0]}, {else_val})"
        return f"IF({conds[0]}, {results[0]})"

    # ELSEIF chain -> SWITCH(TRUE(), cond, result, ...).
    args = ["TRUE()"]
    for cond, result in zip(conds, results):
        args.extend([cond, result])
    if else_val is not None:
        args.append(else_val)
    return "SWITCH(" + ", ".join(args) + ")"


def _convert_datediff(expr: str) -> str:
    def repl(m: re.Match) -> str:
        unit = _DATEPART.get(m.group(1).lower())
        if unit is None:
            raise _Unconvertible(f"Unsupported DATEDIFF unit: {m.group(1)}")
        return f"DATEDIFF({m.group(2).strip()}, {m.group(3).strip()}, {unit})"

    converted = _DATEDIFF_RE.sub(repl, expr)
    if _DATEDIFF_LEFTOVER_RE.search(converted):
        raise _Unconvertible(
            "DATEDIFF arguments are nested too deeply to convert safely."
        )
    return converted


def _map_functions(expr: str) -> tuple[str, set[str]]:
    # Validate against a copy with [field names] blanked, so "(" inside a name like
    # [Base (Variable)] is never mistaken for a function call.
    masked = _FIELD_RE.sub(lambda m: "[" + "x" * len(m.group(1)) + "]", expr)
    for match in _FUNC_RE.finditer(masked):
        fn_up = match.group(1).upper()
        if fn_up in ALLOWED_DAX_FUNCS or fn_up in SUPPORTED_FUNCS:
            continue
        raise _Unconvertible(f"Unsupported function: {match.group(1)}")

    # Rewrite on the real string, skipping anything inside [brackets], so field
    # names are never mangled by the function-name mapping.
    return _map_outside_brackets(expr)


def _map_outside_brackets(expr: str) -> tuple[str, set[str]]:
    """Apply SUPPORTED_FUNCS name mapping only to function calls not inside [ ].

    Returns the rewritten expression and the ids of the rules that rewrote it.
    A rule is cited only when it actually fired: a name already spelled the same
    in both languages (`SUM` -> `SUM`) still fires its rule, because the rule is
    what says the two are equivalent, but a token no rule matched cites nothing.
    """
    applied: set[str] = set()
    out: list[str] = []
    i = 0
    depth = 0  # bracket depth
    while i < len(expr):
        ch = expr[i]
        if ch == "[":
            depth += 1
            out.append(ch)
            i += 1
            continue
        if ch == "]":
            depth = max(0, depth - 1)
            out.append(ch)
            i += 1
            continue
        if depth == 0:
            m = _FUNC_RE.match(expr, i)
            if m:
                fn_up = m.group(1).upper()
                repl = SUPPORTED_FUNCS.get(fn_up, m.group(1))
                rule = rule_for_function(fn_up)
                if rule is not None:
                    applied.add(rule.rule_id)
                out.append(repl + "(")
                i = m.end()
                continue
        out.append(ch)
        i += 1
    return "".join(out), applied


def _resolve_references(expr: str, table_name: str, ctx: TranslationContext) -> str:
    """Qualify field refs into valid DAX based on what each name actually is."""

    local_cols = ctx.columns_by_table.get(table_name, set())

    def resolve_field(raw: str) -> str:
        key = raw.lower()
        # Parameter -> its what-if value measure (referenced unqualified).
        if key in ctx.param_value_measures:
            return f"[{ctx.param_value_measures[key]}]"
        # The calc's own table first. A measure index is global, because a DAX
        # measure reference is unqualified - so consulting it first let a
        # measure in *another* table shadow this table's own column of the same
        # name, and `sum([Sales])` in Orders came out pointing at Targets. A
        # name written inside a Tableau calculation means the field in scope
        # where it was written, and that scope is this table.
        if key in local_cols:
            return f"'{table_name}'[{ctx.column_display.get(key, raw)}]"
        # Calculated field (measure) -> unqualified ref by its emitted display
        # name. A measure of this table lands here too: measures are not in
        # `local_cols`, because they are not columns of anything.
        if key in ctx.measures:
            return f"[{ctx.measures[key]}]"
        # Column in some other table -> 'OwningTable'[Column].
        owner = ctx.field_to_table.get(key, table_name)
        return f"'{owner}'[{ctx.column_display.get(key, raw)}]"

    # Match against a literal-masked copy so bracket text inside a string (e.g.
    # "[Sales] total") is left alone, then splice replacements into the original.
    masked = _mask(expr)
    out: list[str] = []
    last = 0
    for m in REF_RE.finditer(masked):
        out.append(expr[last : m.start()])
        out.append(resolve_field(expr[m.start(1) : m.end(1)]))
        last = m.end()
    out.append(expr[last:])
    return "".join(out)


def _expand_zn(expr: str) -> str:
    """Turn COALESCE_ZN(<arg>) into COALESCE(<arg>, 0) with balanced parens."""
    out = expr
    while "COALESCE_ZN(" in out:
        start = out.index("COALESCE_ZN(")
        open_paren = start + len("COALESCE_ZN")
        depth = 0
        i = open_paren
        while i < len(out):
            if out[i] == "(":
                depth += 1
            elif out[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            return out  # unbalanced; leave as-is (caught upstream)
        inner = out[open_paren + 1 : i]
        out = out[:start] + f"COALESCE({inner}, 0)" + out[i + 1 :]
    return out
