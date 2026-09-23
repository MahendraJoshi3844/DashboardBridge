"""Reading DAX (`P6a.2`). Not an evaluator, and deliberately not a grammar.

Everything downstream asks one of two questions of an expression — *what does it
reference* and *what does it call* — and both have to be answered correctly on
the inputs where a regular expression quietly gets it wrong. A full DAX grammar
would answer more questions than anything here asks, and would be a second
source of truth for a language we do not own.

## Why a scanner rather than a pattern

The regexes this replaces produced plausible wrong answers, which is the only
kind that matters:

* `Orders[Sales]` matched nothing as a qualified reference, because the pattern
  required a *quoted* table name. Power BI quotes a name only when it must, so
  the common form was invisible — and then matched as a **bare** reference,
  turning a column into a measure.
* A bracket inside a string literal counted as a reference: `"see Fake[Column]"`
  produced a dependency on a column nobody wrote.
* A reference inside a comment counted, so a line a developer removed went on
  being a dependency.

None of those is fixable by a better pattern, because deciding whether a `[` is
a reference requires knowing whether you are inside a string, and that is state.
So this walks the text once, carrying that state.

## What it does not do

No precedence, no types, no evaluation, no validation of syntax. A malformed
expression yields whatever it could read rather than an exception: the callers
are a validator and a reader, and both need a partial answer more than they need
a stack trace. An unterminated block comment does not swallow the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "ParsedExpression",
    "Qualifier",
    "Reference",
    "Segment",
    "parse",
    "qualifier_of",
    "references_in",
    "segments",
    "visible",
]


@dataclass(frozen=True)
class Reference:
    """One field an expression names.

    `table` is empty for a measure reference. That distinction is the point of
    reading these at all: a measure lives on the model and a column on a table,
    and binding one where the other belongs fails when someone opens the report.
    """

    table: str
    name: str
    raw: str


@dataclass(frozen=True)
class ParsedExpression:
    text: str
    references: tuple[Reference, ...]
    #: Function names, upper-cased, first-seen order. Never one inside a string.
    calls: tuple[str, ...]


#: A trailing word in a run of code, optionally spaced off the bracket that
#: follows it: the table of an unquoted `Orders[Sales]`, and of the `Orders
#: [Sales]` that DAX also accepts. The space is not part of the name.
_TRAILING_WORD = re.compile(r"([^\W][\w.]*)(\s*)$")

#: Words that are the language, not a table. Only consulted when a space
#: separates the word from the bracket: `AND [B]` is a keyword and a measure,
#: while `AND[B]` can only be a table called AND. Adjacency is unambiguous and
#: is left to speak for itself; a spaced keyword is not, and reading one as a
#: table invents a reference to something nobody wrote - which then reads as a
#: dangling reference in a correct expression, or as a cross-table one in an
#: expression that never left its table.
_NOT_A_TABLE = frozenset(
    {
        "AND",
        "ASC",
        "BLANK",
        "BY",
        "COLUMN",
        "DEFINE",
        "DESC",
        "EVALUATE",
        "FALSE",
        "IN",
        "MEASURE",
        "NOT",
        "OR",
        "ORDER",
        "RETURN",
        "TABLE",
        "TRUE",
        "VAR",
    }
)
#: A word applied to an argument list. No space is allowed before the bracket,
#: because `SUM (x)` is not how DAX is written and reading it as a call would
#: make any spaced word before any bracket a function.
_CALL = re.compile(r"([^\W][\w.]*)\(")


def parse(expression: str) -> ParsedExpression:
    """Read an expression once, carrying the state a pattern cannot.

    The walk is `segments`: one pass decides what every character belongs to,
    and this reads meaning off the pieces. Two walks would be two answers to
    "is this a comment", and they would drift.
    """
    text = expression or ""
    references: list[Reference] = []
    calls: list[str] = []
    seen_refs: set[tuple[str, str]] = set()
    seen_calls: set[str] = set()

    parts = segments(text)
    for position, segment in enumerate(parts):
        if segment.kind == "code":
            for match in _CALL.finditer(segment.text):
                name = match.group(1).upper()
                if name and name not in seen_calls:
                    seen_calls.add(name)
                    calls.append(name)
            continue

        if segment.kind != "bracketed":
            continue

        qualifier = qualifier_of(parts, position)
        table = qualifier.name if qualifier else ""
        start = qualifier.start if qualifier else segment.start
        name = segment.text[1:-1].replace("]]", "]")
        _add(references, seen_refs, table, name, text[start : segment.end])

    return ParsedExpression(text=text, references=tuple(references), calls=tuple(calls))


@dataclass(frozen=True)
class Qualifier:
    """The table naming the reference that follows it, and where it is written.

    `quoted` says which of the two spellings it is, because a caller removing a
    qualifier removes a whole segment in one case and the tail of one in the
    other.
    """

    name: str
    start: int
    quoted: bool


def qualifier_of(parts: tuple[Segment, ...], position: int) -> Qualifier | None:
    """The table qualifying the bracketed segment at `position`, if any.

    `None` for a bare `[Total]`, which is a measure reference. One rule in one
    place: `parse` reads references with it and the DAX-to-Tableau translator
    removes qualifiers with it, and two copies of it would eventually disagree
    about what counts as a table.
    """
    if position <= 0 or parts[position].kind != "bracketed":
        return None
    before = parts[position - 1]
    if before.kind == "quoted":
        return Qualifier(before.text[1:-1].replace("''", "'"), before.start, True)
    if before.kind != "code":
        return None
    word = _TRAILING_WORD.search(before.text)
    if not word:
        return None
    if word.group(2) and word.group(1).upper() in _NOT_A_TABLE:
        return None
    return Qualifier(word.group(1), before.start + word.start(1), False)


def references_in(expression: str) -> tuple[Reference, ...]:
    return parse(expression).references


@dataclass(frozen=True)
class Segment:
    """One stretch of an expression, and what kind of thing it is.

    `kind` is one of `code`, `comment`, `string`, `bracketed` (a `[Name]`) or
    `quoted` (a `'Table Name'`). Segments cover the whole expression, in order,
    with no gaps: a caller that splices a replacement in by offset would corrupt
    the expression if a character belonged to nothing.
    """

    kind: str
    start: int
    end: int
    text: str


def segments(expression: str) -> tuple[Segment, ...]:
    """Split an expression into code, comments, literals and names.

    `visible` answers *which characters are code*; this answers *where each
    piece begins*, which is what anything rewriting an expression needs — the
    DAX-to-Tableau translator replaces a reference in place, and a span it got
    wrong is a formula that is quietly no longer the one someone wrote.
    """
    text = expression or ""
    found: list[Segment] = []
    length = len(text)
    index = 0
    code_at = 0

    def close_code(upto: int) -> None:
        if upto > code_at:
            found.append(Segment("code", code_at, upto, text[code_at:upto]))

    while index < length:
        char = text[index]
        if text.startswith(("//", "--"), index):
            kind, end = "comment", _line_end(text, index)
        elif text.startswith("/*", index):
            closed = text.find("*/", index + 2)
            kind, end = "comment", (length if closed == -1 else closed + 2)
        elif char == '"':
            kind, end = "string", _string_end(text, index)
        elif char == "[":
            kind, end = "bracketed", _bracketed(text, index)[1]
        elif char == "'":
            kind, end = "quoted", _quoted_name(text, index)[1]
        else:
            index += 1
            continue

        close_code(index)
        found.append(Segment(kind, index, end, text[index:end]))
        index = end
        code_at = end

    close_code(length)
    return tuple(found)


def visible(expression: str) -> str:
    """The expression with comments and string contents blanked.

    Useful to anything that wants to search the *code* of an expression without
    matching text a person wrote inside it. Same length as the input, so an
    offset into one is an offset into the other — which is what lets `P6b.2`
    find a reference here and splice its replacement into the original.

    **A name is not text.** `Orders[a//b]` is a column whose name contains two
    slashes, and `Orders[Sales "net"]` one whose name contains a quote. Reading
    either as the start of a comment or a literal blanks the *code* that follows
    it, and a caller working on the result then leaves that code untouched while
    believing it handled the whole expression. So bracketed and quoted names are
    stepped over here exactly as `parse` steps over them.
    """
    pieces: list[str] = []
    for segment in segments(expression):
        if segment.kind == "comment":
            pieces.append(" " * (segment.end - segment.start))
        elif segment.kind == "string":
            # Keep the quotes so the result is still recognisably a literal.
            body = segment.end - segment.start - 2
            pieces.append(
                segment.text
                if body < 0
                else segment.text[0] + " " * body + segment.text[-1]
            )
        else:
            pieces.append(segment.text)
    return "".join(pieces)


# --- the small readers --------------------------------------------------------


def _add(
    references: list[Reference],
    seen: set[tuple[str, str]],
    table: str,
    name: str,
    raw: str,
) -> None:
    key = (table, name)
    if key in seen:
        return
    seen.add(key)
    references.append(Reference(table=table, name=name, raw=raw))


def _line_end(text: str, index: int) -> int:
    end = text.find("\n", index)
    return len(text) if end == -1 else end


def _string_end(text: str, index: int) -> int:
    """Past the closing quote. `""` inside a literal is an escaped quote."""
    index += 1
    length = len(text)
    while index < length:
        if text[index] == '"':
            if index + 1 < length and text[index + 1] == '"':
                index += 2
                continue
            return index + 1
        index += 1
    return length


def _bracketed(text: str, index: int) -> tuple[str, int]:
    """The name inside `[...]`, and the index past it. `]]` is an escaped `]`."""
    index += 1
    length = len(text)
    collected: list[str] = []
    while index < length:
        if text[index] == "]":
            if index + 1 < length and text[index + 1] == "]":
                collected.append("]")
                index += 2
                continue
            return "".join(collected), index + 1
        collected.append(text[index])
        index += 1
    return "".join(collected), length


def _quoted_name(text: str, index: int) -> tuple[str, int]:
    """The name inside `'...'`, and the index past it. `''` is an escaped `'`."""
    index += 1
    length = len(text)
    collected: list[str] = []
    while index < length:
        if text[index] == "'":
            if index + 1 < length and text[index + 1] == "'":
                collected.append("'")
                index += 2
                continue
            return "".join(collected), index + 1
        collected.append(text[index])
        index += 1
    return "".join(collected), length
