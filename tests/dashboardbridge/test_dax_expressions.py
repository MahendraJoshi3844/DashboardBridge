"""Reading a DAX expression (`P6a.2`).

Not an evaluator and not a full grammar. It answers the questions everything
downstream actually asks — *what does this expression reference, and what does it
call* — and answers them correctly on the inputs where a regular expression
quietly gets it wrong.

Three of those were real, found by probing the reference regexes the validator
had been using:

* `Orders[Sales]` matched *nothing* as a qualified reference, because the
  pattern required a quoted table name. Power BI quotes a table name only when
  it has to, so the common form was invisible - and then matched as a *bare*
  reference, turning a column into a measure.
* A bracket inside a string literal counted as a reference. `"see Fake[Column]"`
  produced a reference to `Column`.
* A reference inside a comment counted too, so a line removed by a developer
  went on being a dependency.

Each of those produces a *plausible* wrong answer: a dangling-reference check
reporting something that is not there, or missing something that is.
"""

from __future__ import annotations

import pytest

from engines.dax import parse, references_in, segments, visible


def _refs(expression: str) -> list[tuple[str, str]]:
    return [(ref.table, ref.name) for ref in references_in(expression)]


# --- the forms a reference takes ---------------------------------------------


def test_an_unquoted_table_reference_is_read():
    """`Orders[Sales]`. Power BI quotes a table name only when it must, so this
    is the form most real expressions use - and the one the old pattern missed
    entirely."""
    assert _refs("SUM(Orders[Sales])") == [("Orders", "Sales")]


def test_a_quoted_table_reference_is_read():
    assert _refs("SUM('Sales Commission'[Base Salary])") == [
        ("Sales Commission", "Base Salary")
    ]


def test_a_bare_reference_is_a_measure_not_a_column():
    """`[Total]` with no table is a measure reference. The distinction is the
    whole reason to tell them apart: a measure lives on the model, a column on
    a table, and binding one where the other belongs fails at open time."""
    assert _refs("[Total Revenue] * 2") == [("", "Total Revenue")]


def test_a_column_and_a_measure_in_one_expression_stay_apart():
    assert _refs("DIVIDE([Total Revenue], SUM(Orders[Units]))") == [
        ("", "Total Revenue"),
        ("Orders", "Units"),
    ]


def test_a_space_between_a_table_and_its_column_is_not_part_of_the_name():
    """`Orders [Sales]` is a qualified reference in DAX, and the table is
    `Orders`, not `Orders `.

    A caller matching the table against the one it is translating for compares
    strings, so a trailing space turns a reference to the owning table into an
    apparent cross-table one - refused for a reason that is not true.
    """
    assert _refs("SUM(Orders [Sales])") == [("Orders", "Sales")]


def test_a_keyword_before_a_bracket_is_not_a_table_name():
    """`AND [B]` is a keyword and a measure, not a table called `AND`.

    Adjacency is what makes a qualifier unambiguous: `Orders[Sales]` can only be
    a table and a column, while a *spaced* word before a bracket may be either,
    and a reader that cannot tell has to prefer the reading that does not invent
    a table. Getting this wrong refuses a convertible expression for a table
    that was never referenced.
    """
    assert _refs("IF([A] > 0 AND [B] < 1, 1, 0)") == [("", "A"), ("", "B")]
    assert _refs("[A] OR [B]") == [("", "A"), ("", "B")]


def test_an_escaped_bracket_inside_a_name_does_not_end_it():
    """DAX escapes `]` inside a bracketed name by doubling it."""
    assert _refs("Orders[Value ]] with bracket]") == [("Orders", "Value ] with bracket")]


def test_an_escaped_quote_inside_a_table_name_does_not_end_it():
    assert _refs("'O''Brien Sales'[Revenue]") == [("O'Brien Sales", "Revenue")]


# --- what is not a reference --------------------------------------------------


def test_a_bracket_inside_a_string_literal_is_not_a_reference():
    """The defect this module exists for.

    A label like `"see Fake[Column] for detail"` is text a person wrote. Reading
    it as a dependency invents a reference to a column that does not exist, and
    a dangling-reference check then reports a fault in a correct expression.
    """
    assert _refs('CONCATENATE("see Fake[Column]", Orders[Sales])') == [
        ("Orders", "Sales")
    ]


def test_a_doubled_quote_inside_a_string_does_not_end_it():
    """DAX escapes `"` inside a string by doubling it. Ending the literal early
    puts the rest of the string back into scope as code."""
    assert _refs('IF(x, "say ""Fake[Column]"" loudly", Orders[Sales])') == [
        ("Orders", "Sales")
    ]


@pytest.mark.parametrize(
    "expression",
    [
        "SUM(Orders[Sales]) // Orders[Ghost] was removed",
        "SUM(Orders[Sales]) -- Orders[Ghost] was removed",
        "SUM(Orders[Sales]) /* uses Orders[Ghost] */",
        "/* Orders[Ghost] */ SUM(Orders[Sales])",
    ],
)
def test_a_reference_in_a_comment_is_not_a_dependency(expression):
    """A line someone commented out is not a line that runs."""
    assert _refs(expression) == [("Orders", "Sales")]


def test_an_unterminated_block_comment_does_not_swallow_the_expression():
    """Malformed input is common and must not produce a confident empty answer.

    Returning "no references" for an expression full of them is the failure that
    looks like success.
    """
    parsed = parse("SUM(Orders[Sales]) /* never closed")
    assert ("Orders", "Sales") in [(r.table, r.name) for r in parsed.references]


# --- calls --------------------------------------------------------------------


def test_the_functions_it_calls_are_listed_once_each_in_order():
    parsed = parse("DIVIDE(SUM(Orders[Sales]), SUM(Orders[Units]))")
    assert parsed.calls == ("DIVIDE", "SUM")


def test_a_function_name_inside_a_string_is_not_a_call():
    parsed = parse('CONCATENATE("SUM(", Orders[Sales])')
    assert parsed.calls == ("CONCATENATE",)


def test_a_bracketed_name_that_looks_like_a_call_is_not_one():
    """A column may legitimately be called `Count(x)`."""
    parsed = parse("Orders[Count(x)]")
    assert parsed.calls == ()
    assert _refs("Orders[Count(x)]") == [("Orders", "Count(x)")]


# --- shape --------------------------------------------------------------------


def test_the_same_reference_twice_is_reported_once():
    assert _refs("Orders[Sales] + Orders[Sales]") == [("Orders", "Sales")]


def test_parsing_is_deterministic():
    expression = "DIVIDE(SUM(Orders[Sales]), [Total Revenue])"
    assert parse(expression) == parse(expression)


def test_an_empty_expression_says_so_rather_than_guessing():
    parsed = parse("")
    assert parsed.references == ()
    assert parsed.calls == ()


# --- the visible text ----------------------------------------------------------
#
# `visible` blanks comments and string contents so that something else can
# search the *code* of an expression without matching text a person wrote inside
# it. `P6b.2` is the first caller: it rewrites references and function names, and
# it must not rewrite either inside a comment or a literal.


def test_a_comment_marker_inside_a_bracketed_name_does_not_start_a_comment():
    """`Orders[a//b]` is a column whose name contains two slashes.

    Treating them as a comment blanks the rest of the line, so everything after
    a legitimately-named column becomes invisible - and a rewriter working on
    the visible text then leaves that code untouched while believing it handled
    the whole expression.
    """
    expression = "Orders[a//b] + Orders[Sales]"
    assert visible(expression) == expression


def test_a_comment_marker_inside_a_quoted_table_name_does_not_start_a_comment():
    expression = "'Orders // Archive'[Sales] + Orders[Units]"
    assert visible(expression) == expression


def test_a_quote_inside_a_bracketed_name_does_not_open_a_literal():
    """A column called `Sales "net"` is legal. Reading its quote as the start of
    a string literal blanks real code until the next quote."""
    expression = 'Orders[Sales "net"] + Orders[Units]'
    assert visible(expression) == expression


def test_a_comment_is_blanked_but_the_length_is_unchanged():
    """Offsets into the visible text must be offsets into the original."""
    expression = "SUM(Orders[Sales]) // Orders[Ghost]"
    seen = visible(expression)
    assert len(seen) == len(expression)
    assert "Ghost" not in seen
    assert seen.startswith("SUM(Orders[Sales])")


def test_the_contents_of_a_string_literal_are_blanked():
    seen = visible('CONCATENATE("Fake[Column]", Orders[Sales])')
    assert "Fake" not in seen
    assert "Orders[Sales]" in seen


# --- segments -----------------------------------------------------------------
#
# `visible` answers "which characters are code"; it cannot answer "where does
# this comment start", and a rewriter needs the second. Both are the same walk,
# so there is one walk and `visible` is built from it.


def _kinds(expression: str) -> list[tuple[str, str]]:
    return [(segment.kind, segment.text) for segment in segments(expression)]


def test_segments_cover_the_whole_expression_in_order():
    """Contiguous and gapless: a caller splices replacements into the original by
    offset, so a missing character is a corrupted expression."""
    expression = 'IF(Orders[Sales] > 0, "yes", \'Old Orders\'[Sales]) // done'
    parts = segments(expression)
    assert "".join(part.text for part in parts) == expression
    assert parts[0].start == 0
    assert parts[-1].end == len(expression)
    for before, after in zip(parts, parts[1:]):
        assert before.end == after.start


def test_a_bracketed_name_is_its_own_segment():
    assert ("bracketed", "[Sales]") in _kinds("SUM(Orders[Sales])")


def test_a_quoted_table_name_is_its_own_segment():
    assert ("quoted", "'Sales Commission'") in _kinds("'Sales Commission'[Base]")


def test_a_line_comment_is_a_segment_in_both_of_its_spellings():
    assert ("comment", "// gone") in _kinds("SUM(Orders[Sales]) // gone")
    assert ("comment", "-- gone") in _kinds("SUM(Orders[Sales]) -- gone")


def test_a_string_literal_is_a_segment_including_its_quotes():
    assert ("string", '"Fake[Column]"') in _kinds('CONCATENATE("Fake[Column]", x)')


def test_an_unterminated_block_comment_is_one_segment_to_the_end():
    parts = segments("SUM(Orders[Sales]) /* never closed")
    assert parts[-1].kind == "comment"
    assert parts[-1].end == len("SUM(Orders[Sales]) /* never closed")


def test_an_empty_expression_has_no_segments():
    assert segments("") == ()
