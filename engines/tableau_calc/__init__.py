"""DAX -> a Tableau calculation (`P6b.2`). Translate fully, or refuse and say why.

This is what lets `engines/adapters/tableau_emit.py` write a `<calculation>` for
an expression that came from Power BI. Until it existed, such a field was left
out of the workbook entirely, because pasting DAX into a `formula` attribute
produces a workbook that opens and then fails on every row.

## Not the forward translator with the arrows reversed

Three differences decide most of what this refuses, and none of them has a
counterpart in `t2pbi/core/dax/translator.py`:

* **A Tableau calculation has no table qualifier.** The writer gives each
  canonical table its own `<datasource>`, so `Orders[Sales]` becomes `[Sales]`
  when `Orders` is the table being written — and has no spelling at all when it
  is not. A cross-table reference is refused rather than stripped: stripping it
  produces a field that resolves to the wrong column, or to none.
* **Arity is not preserved by a name.** `IF(a, b)` is legal DAX and there is no
  two-argument `IIF`; `LEFT(text)` is legal DAX and there is no one-argument
  Tableau `LEFT`. Every rule states the arities it is correct for.
* **`--` is a comment in DAX and arithmetic in Tableau.** Carried across
  unchanged it goes on being read — as a double negation, which is valid,
  silent, and wrong. It is the one thing here that is rewritten rather than
  copied or refused.

## The unrecognised-token net

Anything in the code that is not a mapped call, a reference, a number, an
operator or one of a small set of keywords refuses the expression. That is
deliberately blunt: the alternative is emitting an identifier Tableau does not
know, and a formula that fails to compile is only found by the person who opens
the workbook.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from engines.dax import Segment, qualifier_of, segments
from engines.tableau_calc.rules import refusal_rules, rule_for_function

__all__ = ["TranslationResult", "translate_dax"]

#: Bare words Tableau understands without parentheses. Everything else standing
#: alone in the code is unrecognised, and unrecognised is refused.
_BARE_WORDS = frozenset({"AND", "OR", "NOT", "IN", "TRUE", "FALSE", "NULL"})

_WORD = re.compile(r"[^\W\d][\w.]*|\d[\w.]*")
_NUMBER = re.compile(r"\d+(\.\d+)?([eE][+-]?\d+)?")


@dataclass(frozen=True)
class TranslationResult:
    """A Tableau formula, or nothing and the sentence explaining it.

    Exactly one of `formula` and `reason` is ever set. A refusal with no reason
    is an unexplained rejection, which is the one thing worse than a refusal.
    """

    formula: str | None
    reason: str | None = None
    #: Every rule-pack mapping this translation applied, sorted so two runs of
    #: one expression cite the same thing in the same order.
    rule_ids: tuple[str, ...] = ()


def translate_dax(expression: str, *, table: str) -> TranslationResult:
    """Translate `expression`, written in `table`, into a Tableau calculation.

    `table` is the canonical table the calculated column belongs to — the one
    the writer turns into a `<datasource>`. A reference to any other table is
    refused, because the generated workbook has no way to reach it.
    """
    text = expression or ""
    if not text.strip():
        return _refuse("Empty expression: there is nothing to translate.")

    parts = segments(text)

    refusal = _refused_construct(parts)
    if refusal is not None:
        return refusal

    literal = _unsupported_literal(parts)
    if literal is not None:
        return literal

    # Before anything is counted or rewritten. A symbol DAX means something by
    # and Tableau does not - a table constructor's braces, say - would otherwise
    # be counted as punctuation first, and the expression refused with a true
    # sentence about the wrong thing.
    operator = _unsupported_operator(parts)
    if operator is not None:
        return operator

    pieces: list[str] = []
    applied: set[str] = set()
    consumed: set[int] = _qualifier_positions(parts)
    mask = _mask(text)

    for position, segment in enumerate(parts):
        if position in consumed:
            continue
        if segment.kind == "code":
            rendered = _code(segment, parts, position, consumed, mask, applied)
            if isinstance(rendered, TranslationResult):
                return rendered
            pieces.append(rendered)
        elif segment.kind == "bracketed":
            name = _reference(segment, parts, position, table)
            if isinstance(name, TranslationResult):
                return name
            pieces.append(name)
        elif segment.kind == "comment":
            pieces.append(_comment(segment.text))
        else:
            pieces.append(segment.text)

    formula = "".join(pieces)
    residual = _residual_qualifier(formula)
    if residual is not None:
        return residual
    return TranslationResult(formula, None, tuple(sorted(applied)))


def _refuse(reason: str) -> TranslationResult:
    return TranslationResult(None, reason, ())


# --- what disqualifies the whole expression ------------------------------------


def _refused_construct(parts: tuple[Segment, ...]) -> TranslationResult | None:
    """A marker in the *code*, never in a name, a literal or a comment.

    `Orders[Filter Cost]` is a column, not a `FILTER`. The forward translator
    masks bracketed names before scanning for the same reason; here the segments
    do it, because a word cannot span two of them.
    """
    code = " ".join(part.text for part in parts if part.kind == "code").upper()
    for rule in refusal_rules():
        if re.search(rf"\b{re.escape(rule.marker)}\b", code):
            return _refuse(f"{rule.marker}: {rule.reason}")
    return None


def _unsupported_literal(parts: tuple[Segment, ...]) -> TranslationResult | None:
    """Escapes this does not carry across, refused rather than guessed at."""
    for part in parts:
        if part.kind == "string" and '""' in part.text[1:-1]:
            return _refuse(
                'The text contains an escaped quote. DAX escapes " by doubling '
                "it, and copying the doubling into Tableau would end the "
                "literal early - turning the rest of someone's text into code."
            )
        if part.kind == "bracketed" and "]]" in part.text:
            return _refuse(
                "The field name contains a ] , which DAX escapes by doubling. "
                "Tableau's escaping for the same character inside a name is not "
                "established here, so the name is not rewritten into a form "
                "that may not mean what it says."
            )
    return None


# --- references ----------------------------------------------------------------


def _qualifier_positions(parts: tuple[Segment, ...]) -> set[int]:
    """Quoted table names that belong to the reference after them.

    A quoted segment followed by a bracketed one is the table of that reference
    and is dropped with it. One that is not is a stray name, left in place so
    the unrecognised-token net can refuse it.
    """
    return {
        position - 1
        for position in range(len(parts))
        if (qualifier := qualifier_of(parts, position)) is not None and qualifier.quoted
    }


def _reference(
    segment: Segment, parts: tuple[Segment, ...], position: int, table: str
) -> str | TranslationResult:
    name = segment.text[1:-1]
    qualifier = qualifier_of(parts, position)
    if qualifier is None:
        return f"[{name}]"
    if qualifier.name.casefold() != table.casefold():
        return _refuse(
            f"References {qualifier.name}[{name}], a column in another table. "
            "Each table becomes its own Tableau data source, and a calculation "
            "cannot reach across one - the field would resolve to nothing. "
            "Joining the two in the data source is the equivalent, and that is "
            "a change to the model rather than to the formula."
        )
    return f"[{name}]"


# --- code ----------------------------------------------------------------------


def _mask(text: str) -> str:
    """The expression with everything that is not code made inert.

    Same length as the input, so an index into one is an index into the other.
    Parentheses and commas then appear only where they are punctuation, which is
    what makes counting a call's arguments possible at all.
    """
    out: list[str] = []
    for segment in segments(text):
        if segment.kind == "code":
            out.append(segment.text)
        elif segment.kind == "comment":
            out.append(" " * (segment.end - segment.start))
        else:
            out.append("x" * (segment.end - segment.start))
    return "".join(out)


def _code(
    segment: Segment,
    parts: tuple[Segment, ...],
    position: int,
    consumed: set[int],
    mask: str,
    applied: set[str],
) -> str | TranslationResult:
    """One run of code, with its calls renamed and its qualifier removed."""
    following = qualifier_of(parts, position + 1) if position + 1 < len(parts) else None
    # An unquoted qualifier is the tail of *this* segment, and goes with the
    # reference that follows. Everything from where it starts is dropped, the
    # whitespace between the two included.
    cut = (
        following.start - segment.start
        if following is not None and not following.quoted
        else len(segment.text)
    )

    pieces: list[str] = []
    last = 0
    for match in _WORD.finditer(segment.text):
        if match.start() >= cut:
            break
        word = match.group(0)

        if segment.text[match.end() : match.end() + 1] == "(":
            rule = rule_for_function(word)
            if rule is None:
                return _refuse(
                    f"No rule maps the DAX function {word.upper()} to a Tableau "
                    "one. Approximating it would produce a formula that looks "
                    "converted and is not."
                )
            count = _argument_count(mask, segment.start + match.end())
            if count is None:
                return _refuse(
                    f"{word.upper()}( is never closed, so the expression cannot "
                    "be read."
                )
            if not rule.accepts(count):
                return _refuse(
                    f"{word.upper()} is called with {count} argument(s), and "
                    f"{rule.target_function} accepts "
                    f"{rule.min_args}..{rule.max_args}. "
                    + (
                        rule.note
                        or "Supplying the difference would invent a value nobody "
                        "wrote."
                    )
                )
            applied.add(rule.rule_id)
            pieces.append(segment.text[last : match.start()])
            pieces.append(rule.target_function)
            last = match.end()
            continue

        if _NUMBER.fullmatch(word) or word.upper() in _BARE_WORDS:
            continue

        return _refuse(
            f"{word!r} is not something this can translate: it is not a mapped "
            "function, a field reference, a number or an operator. Emitting it "
            "unchanged would produce a formula Tableau cannot compile."
        )

    pieces.append(segment.text[last:cut])
    return _operators("".join(pieces))


#: DAX spellings that Tableau writes differently. `==` differs from `=` only in
#: how it treats blank, and Tableau has one equality operator.
_OPERATOR_REWRITES = (
    (re.compile(r"\s*&&\s*"), " AND "),
    (re.compile(r"\s*\|\|\s*"), " OR "),
    (re.compile(r"=="), "="),
)
#: Punctuation Tableau reads the same way DAX does. Anything else in the code -
#: after the rewrites above - is refused rather than passed through.
_ALLOWED_PUNCTUATION = frozenset("+-*/%^=<>!(),.:;")


def _unsupported_operator(parts: tuple[Segment, ...]) -> TranslationResult | None:
    """Symbols in the code that Tableau has no reading for.

    `&` is the one that must not be rewritten rather than the one that cannot
    be. It concatenates in DAX and coerces both sides to text; Tableau's `+`
    concatenates strings *and adds numbers*, so the same expression over two
    numeric fields would quietly return a sum where the source returned a
    string. Same characters, different answer, no error anywhere.
    """
    for part in parts:
        if part.kind != "code":
            continue
        rest = part.text.replace("&&", "").replace("||", "")
        if "&" in rest:
            return _refuse(
                "Uses & to join text. Tableau's + concatenates strings but adds "
                "numbers, so the same expression over two numeric fields would "
                "return a sum where this returns text - a different answer with "
                "no error. STR() around each side is the equivalent, and "
                "choosing where to put it is a judgement rather than a mapping."
            )
        stray = [
            character
            for character in rest
            if not (character.isalnum() or character.isspace() or character == "_")
            and character not in _ALLOWED_PUNCTUATION
        ]
        if stray:
            return _refuse(
                f"Uses {stray[0]!r}, which is not an operator this can carry "
                "into a Tableau calculation."
            )
    return None


def _operators(code: str) -> str:
    """The operators DAX and Tableau spell differently, respelled.

    Everything reaching here has already been checked by
    `_unsupported_operator`, so this only rewrites.
    """
    for pattern, replacement in _OPERATOR_REWRITES:
        code = pattern.sub(replacement, code)
    return code


def _argument_count(mask: str, open_paren: int) -> int | None:
    """How many arguments the call whose `(` is at `open_paren` was given.

    `None` when the call is never closed. Counted on the mask, so a comma inside
    a string or a field name is not an argument separator.
    """
    depth = 1
    commas = 0
    index = open_paren + 1
    while index < len(mask):
        char = mask[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                body = mask[open_paren + 1 : index]
                return commas + 1 if body.strip() else 0
        elif char == "," and depth == 1:
            commas += 1
        index += 1
    return None


def _comment(text: str) -> str:
    """A DAX comment, spelled the way Tableau spells one.

    `--` is the only rewrite in this module that is not optional: Tableau has no
    two-dash comment, so the same characters are read there as a double negation
    - valid, silent, and wrong.
    """
    return "//" + text[2:] if text.startswith("--") else text


# --- the backstop ---------------------------------------------------------------


def _residual_qualifier(formula: str) -> TranslationResult | None:
    """Nothing emitted may still carry a table qualifier.

    The mirror of the forward translator's residual-keyword net, and it exists
    for the same reason: a qualifier that survives is a field Tableau cannot
    bind, and the failure is only visible to whoever opens the workbook.
    """
    parts = segments(formula)
    for position, part in enumerate(parts):
        if qualifier_of(parts, position) is not None:
            return _refuse(
                f"Internal check: {part.text} is still qualified by a table "
                "after translation, which Tableau cannot resolve. Refusing "
                "rather than writing a field bound to nothing."
            )
    return None
