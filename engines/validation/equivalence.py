"""Is this DAX equivalent to that Tableau calculation? Usually: undecidable.

08-validation-engine, *Semantic equivalence, honestly*:

> Overstating this is the most tempting failure available to this engine,
> because PASS makes the score look better and nobody notices until production.

So the decidable core here is small on purpose. An expression is declared
equivalent only when, after normalisation, it is a **token-for-token image** of
the source built exclusively from:

* column and measure references,
* numeric and string literals,
* the aggregations in `TOTAL_EQUIVALENCE` — pairs whose two implementations
  agree over their *entire* domain, including the empty input,
* grouping punctuation.

Everything else is `undecided`, and the note names the specific construct that
made it so. Three constructs come up constantly and are worth stating, because
each is a real behavioural difference a reviewer needs to know about rather
than pedantry:

* **Division.** Tableau's `/` yields null when the divisor is zero. DAX's `/`
  yields Infinity or NaN. `SUM([Profit])/SUM([Sales])` is the canonical
  migration surprise, and `DIVIDE()` is the usual repair.
* **Arithmetic with a missing value.** Tableau propagates null through `+`,
  `-` and `*`. DAX coerces `BLANK()` to zero, so `null + 1` is null in one and
  `1` in the other.
* **Text comparison.** `=` on strings is case-sensitive in Tableau and
  case-insensitive in DAX.

None of these can be decided without executing the expression against data,
which ADR-003 says we do not do. So they are reported, not scored as passes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

#: Tableau -> DAX pairs whose behaviour is identical over the whole domain,
#: including the empty input (both yield "no value"). Deliberately short: a pair
#: belongs here only when no input distinguishes the two implementations.
TOTAL_EQUIVALENCE: dict[str, str] = {
    "SUM": "SUM",
    "MIN": "MIN",
    "MAX": "MAX",
    "AVG": "AVERAGE",
    "AVERAGE": "AVERAGE",
    "COUNT": "COUNT",
    "COUNTD": "DISTINCTCOUNT",
    "MEDIAN": "MEDIAN",
}

_CONTROL_FLOW = frozenset(
    {"IF", "IIF", "THEN", "ELSE", "ELSEIF", "END", "CASE", "WHEN", "SWITCH"}
)
_COMPARISON = frozenset({"=", "==", "<>", "!=", ">", "<", ">=", "<="})
_ARITHMETIC = frozenset({"+", "-", "*", "%", "^"})
_GROUPING = frozenset({"(", ")", ","})

_NUMBER = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_OPERATORS = ("<>", "!=", ">=", "<=", "==", "=", ">", "<", "+", "-", "*", "/", "%", "^")


class Verdict(str, Enum):
    EQUIVALENT = "equivalent"
    UNDECIDED = "undecided"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str

    @property
    def equivalent(self) -> bool:
        return self.verdict is Verdict.EQUIVALENT


Token = tuple[str, str]  # (kind, value); kinds: field num str func word op punct


class LexError(Exception):
    """The text could not be tokenised, so nothing about it can be decided."""


# ---------------------------------------------------------------------------
# lexing
# ---------------------------------------------------------------------------


def _strip_comments(text: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", without_block)


def lex_tableau(text: str) -> list[Token]:
    """Tokenise a Tableau calculation.

    `[Datasource].[Field]` keeps only the field: the target qualifies with a
    Power BI table name that the source does not contain, so comparing
    qualifiers would reject every correct translation.
    """
    source = _strip_comments(text)
    tokens: list[Token] = []
    i, n = 0, len(source)
    while i < n:
        char = source[i]
        if char.isspace():
            i += 1
        elif char == "[":
            end = source.find("]", i)
            if end < 0:
                raise LexError("unterminated field reference")
            name = source[i + 1 : end]
            i = end + 1
            # `[ds].[Field]` -> keep the last part only.
            while i < n and source[i] == "." and i + 1 < n and source[i + 1] == "[":
                end = source.find("]", i + 1)
                if end < 0:
                    raise LexError("unterminated field reference")
                name = source[i + 2 : end]
                i = end + 1
            tokens.append(("field", name.casefold()))
        elif char in "\"'":
            end = source.find(char, i + 1)
            if end < 0:
                raise LexError("unterminated string literal")
            tokens.append(("str", source[i + 1 : end]))
            i = end + 1
        elif char.isdigit() or (char == "." and i + 1 < n and source[i + 1].isdigit()):
            match = _NUMBER.match(source, i)
            if match is None:
                raise LexError("malformed number")
            tokens.append(("num", _number(match.group(0))))
            i = match.end()
        elif (match := _IDENTIFIER.match(source, i)) is not None:
            word = match.group(0).upper()
            i = match.end()
            j = i
            while j < n and source[j].isspace():
                j += 1
            kind = "func" if j < n and source[j] == "(" else "word"
            tokens.append((kind, word))
        elif source.startswith(_OPERATORS, i):
            operator = next(op for op in _OPERATORS if source.startswith(op, i))
            tokens.append(("op", operator))
            i += len(operator)
        elif char in "(),":
            tokens.append(("punct", char))
            i += 1
        else:
            tokens.append(("op", char))
            i += 1
    return tokens


def lex_dax(text: str) -> list[Token]:
    """Tokenise emitted DAX.

    Single quotes are a table qualifier in DAX, never a string, so `'Orders'`
    is read as a qualifier and dropped: only the column name is compared.
    """
    source = _strip_comments(text)
    tokens: list[Token] = []
    i, n = 0, len(source)
    while i < n:
        char = source[i]
        if char.isspace():
            i += 1
        elif char == "'":
            i0 = i
            end = source.find("'", i + 1)
            if end < 0:
                raise LexError("unterminated table qualifier")
            i = end + 1
            if i < n and source[i] == "[":
                close = source.find("]", i)
                if close < 0:
                    raise LexError("unterminated column reference")
                tokens.append(("field", source[i + 1 : close].casefold()))
                i = close + 1
            else:
                # A bare `'Table'` reference, e.g. inside CALCULATE. Not part of
                # the decidable core, but it must not vanish silently.
                tokens.append(("word", source[i0 + 1 : end].upper()))
        elif char == "[":
            end = source.find("]", i)
            if end < 0:
                raise LexError("unterminated measure reference")
            tokens.append(("field", source[i + 1 : end].casefold()))
            i = end + 1
        elif char == '"':
            end = source.find('"', i + 1)
            if end < 0:
                raise LexError("unterminated string literal")
            tokens.append(("str", source[i + 1 : end]))
            i = end + 1
        elif char.isdigit() or (char == "." and i + 1 < n and source[i + 1].isdigit()):
            match = _NUMBER.match(source, i)
            if match is None:
                raise LexError("malformed number")
            tokens.append(("num", _number(match.group(0))))
            i = match.end()
        elif (match := _IDENTIFIER.match(source, i)) is not None:
            word = match.group(0).upper()
            i = match.end()
            j = i
            while j < n and source[j].isspace():
                j += 1
            kind = "func" if j < n and source[j] == "(" else "word"
            tokens.append((kind, word))
        elif source.startswith(_OPERATORS, i):
            operator = next(op for op in _OPERATORS if source.startswith(op, i))
            tokens.append(("op", operator))
            i += len(operator)
        elif char in "(),":
            tokens.append(("punct", char))
            i += 1
        else:
            tokens.append(("op", char))
            i += 1
    return tokens


def _number(raw: str) -> str:
    try:
        value = float(raw)
    except ValueError:  # pragma: no cover - guarded by the regex
        return raw
    return repr(int(value)) if value.is_integer() else repr(value)


# ---------------------------------------------------------------------------
# the decision
# ---------------------------------------------------------------------------


def _in_decidable_core(tokens: list[Token], mapping: bool) -> bool:
    for kind, value in tokens:
        if kind in {"field", "num", "str"}:
            continue
        if kind == "punct" and value in _GROUPING:
            continue
        if kind == "func" and (
            value in TOTAL_EQUIVALENCE if mapping else value in set(TOTAL_EQUIVALENCE.values())
        ):
            continue
        return False
    return True


def _normalise_source(tokens: list[Token]) -> list[Token]:
    return [
        ("func", TOTAL_EQUIVALENCE[value]) if kind == "func" else (kind, value)
        for kind, value in tokens
    ]


def _undecidable_reason(source: list[Token], target: list[Token]) -> str:
    words = {value for kind, value in source + target if kind in {"word", "func"}}
    operators = {value for kind, value in source + target if kind == "op"}

    if words & _CONTROL_FLOW:
        return (
            "the calculation branches (IF/CASE) and was re-expressed by rule; "
            "branch selection and the comparisons inside it were not executed"
        )
    if "/" in operators:
        return (
            "division is not decidable offline: Tableau yields null when the "
            "divisor is zero and DAX yields Infinity or NaN, so the two agree "
            "only on data neither engine was run against"
        )
    if operators & _COMPARISON:
        return (
            "comparison is not decidable offline: text comparison is "
            "case-sensitive in Tableau and case-insensitive in DAX"
        )
    if operators & _ARITHMETIC:
        return (
            "arithmetic is not decidable offline: Tableau propagates null "
            "through an operator, DAX treats a blank operand as zero"
        )
    unknown = sorted(
        value
        for kind, value in source
        if kind == "func" and value not in TOTAL_EQUIVALENCE
    )
    if unknown:
        return (
            f"uses {', '.join(unknown)}, mapped to DAX by rule; the two "
            "implementations were not compared by execution"
        )
    return (
        "the target is not a token-for-token image of the source under the "
        "known-equivalent mappings, so equivalence could not be decided"
    )


def decide_equivalence(source_text: str, target_text: str) -> Decision:
    """Decide, or refuse to decide, whether the two expressions agree.

    There is no third answer that means "probably". A caller turning
    `UNDECIDED` into a pass would defeat the entire engine.
    """
    try:
        source = lex_tableau(source_text)
        target = lex_dax(target_text)
    except LexError as exc:
        return Decision(
            Verdict.UNDECIDED,
            f"the expression could not be read for comparison ({exc})",
        )

    if not source or not target:
        return Decision(
            Verdict.UNDECIDED, "one side of the comparison is empty"
        )

    if (
        _in_decidable_core(source, mapping=True)
        and _in_decidable_core(target, mapping=False)
        and _normalise_source(source) == target
    ):
        if len(source) == 1 and source[0][0] in {"str", "num"}:
            return Decision(Verdict.EQUIVALENT, "both sides are the same literal")
        if len(source) == 1 and source[0][0] == "field":
            return Decision(
                Verdict.EQUIVALENT,
                "the calculation is a reference to one column and the target "
                "references a column of the same name",
            )
        return Decision(
            Verdict.EQUIVALENT,
            "token-for-token identical under aggregations whose Tableau and "
            "DAX implementations agree over their whole domain",
        )

    return Decision(Verdict.UNDECIDED, _undecidable_reason(source, target))
