"""DAX -> a Tableau calculation (`P6b.2`).

The mirror of `P3.1`, and **not its reflection**. Translating the other way is
not the same job with the arrows turned round, and three differences decide most
of what this refuses:

* **A Tableau calculation has no table qualifier.** `engines/adapters/
  tableau_emit.py` writes each canonical table as its own `<datasource>`, so
  `Orders[Sales]` becomes `[Sales]` when `Orders` is the table being written and
  cannot become anything at all when it is not. A cross-table DAX reference has
  no Tableau spelling here, and inventing one produces a field bound to nothing.
* **Arity is not preserved by a name.** `IF(a, b)` is legal DAX and there is no
  two-argument `IIF`; `LEFT(text)` is legal DAX and there is no one-argument
  Tableau `LEFT`. A rule that maps only the name would emit a call that opens
  and then fails, so every rule carries the argument counts it is valid for.
* **`--` is a comment in DAX and arithmetic in Tableau.** Left alone, `x -- y`
  goes on being read - as a double negation, which is valid, silent, and wrong.

Everything else follows the rule the forward direction already follows: a
construct with no rule is refused with a sentence naming it, never approximated.
"""

from __future__ import annotations

import pytest

from engines.tableau_calc import translate_dax
from engines.tableau_calc.rules import RulePackError, function_rules, load_pack
from engines.tableau_calc.rules import refusal_rules


def _formula(expression: str, table: str = "Orders") -> str | None:
    return translate_dax(expression, table=table).formula


# --- what it translates -------------------------------------------------------


def test_a_function_is_renamed_by_the_rule_that_maps_it():
    result = translate_dax("AVERAGE(Orders[Sales])", table="Orders")
    assert result.formula == "AVG([Sales])"
    assert result.rule_ids == ("PBI_AVERAGE_TO_TABLEAU_AVG",)


def test_a_qualified_reference_loses_its_table():
    """Each canonical table is written as its own Tableau data source, so a
    calculation inside it names fields and never tables."""
    assert _formula("SUM(Orders[Sales])") == "SUM([Sales])"


def test_a_quoted_table_name_is_recognised_as_the_owning_table():
    assert _formula("SUM('Order Lines'[Sales])", table="Order Lines") == "SUM([Sales])"


def test_a_measure_reference_is_carried_across_unchanged():
    """`[Total Revenue]` is already how Tableau names a field."""
    assert _formula("[Total Revenue] * 2") == "[Total Revenue] * 2"


def test_a_three_argument_if_becomes_iif():
    result = translate_dax('IF(Orders[Sales] > 0, "up", "down")', table="Orders")
    assert result.formula == 'IIF([Sales] > 0, "up", "down")'


def test_a_dash_comment_becomes_a_tableau_comment():
    """The one rewrite that is not optional.

    Tableau has no `--` comment: the same two characters are a double negation
    there, so leaving the line alone changes the value of the expression instead
    of being ignored by it. Valid, silent, and wrong is the worst of the three.
    """
    assert _formula("SUM(Orders[Sales]) -- was Ghost") == "SUM([Sales]) // was Ghost"


def test_a_slash_comment_and_a_block_comment_are_left_alone():
    assert _formula("SUM(Orders[Sales]) // fine") == "SUM([Sales]) // fine"
    assert _formula("/* fine */ SUM(Orders[Sales])") == "/* fine */ SUM([Sales])"


def test_several_rules_are_all_cited_and_sorted():
    result = translate_dax(
        "AVERAGE(Orders[Sales]) + DISTINCTCOUNT(Orders[Id])", table="Orders"
    )
    assert result.rule_ids == (
        "PBI_AVERAGE_TO_TABLEAU_AVG",
        "PBI_DISTINCTCOUNT_TO_TABLEAU_COUNTD",
    )
    assert result.rule_ids == tuple(sorted(result.rule_ids))


# --- what it refuses ----------------------------------------------------------


def test_a_reference_to_another_table_is_refused_and_the_table_is_named():
    """The refusal this direction exists for.

    Tableau has no cross-data-source reference inside a calculation, and each
    table is written as its own data source. There is no spelling of this that
    resolves, so there is nothing to emit.
    """
    result = translate_dax("SUM(Customers[Sales])", table="Orders")
    assert result.formula is None
    assert "Customers" in result.reason


def test_a_function_with_no_rule_is_refused_by_name():
    result = translate_dax("DIVIDE(Orders[Sales], Orders[Units])", table="Orders")
    assert result.formula is None
    assert "DIVIDE" in result.reason


def test_a_construct_with_no_tableau_equivalent_is_refused_with_its_reason():
    result = translate_dax("CALCULATE(SUM(Orders[Sales]))", table="Orders")
    assert result.formula is None
    assert result.reason
    assert "CALCULATE" in result.reason


def test_a_variable_binding_is_refused():
    """`VAR`/`RETURN` has no Tableau form: a calculation is one expression."""
    result = translate_dax("VAR x = SUM(Orders[Sales]) RETURN x", table="Orders")
    assert result.formula is None


def test_a_two_argument_if_is_refused_because_tableau_has_no_such_form():
    """DAX lets the else branch be omitted; `IIF` does not.

    Emitting `IIF(a, b)` produces a calculation Tableau rejects, and inventing
    the third argument invents a value for every row that fails the test.
    """
    result = translate_dax("IF(Orders[Sales] > 0, 1)", table="Orders")
    assert result.formula is None
    assert "IF" in result.reason


def test_a_one_argument_left_is_refused_because_tableau_requires_the_length():
    result = translate_dax("LEFT(Orders[Name])", table="Orders")
    assert result.formula is None


def test_a_field_name_containing_a_bracket_is_refused():
    """DAX escapes `]` by doubling it inside the name. Tableau's escaping for
    the same character is not established here, so the name is not rewritten
    into a form that may not mean what it says."""
    result = translate_dax("SUM(Orders[Value ]] here])", table="Orders")
    assert result.formula is None


def test_a_string_literal_with_an_escaped_quote_is_refused():
    """DAX escapes `"` by doubling it. Carrying the doubling across unchanged
    would end the literal early in a language that does not read it that way,
    which turns the remainder of someone's text into code."""
    result = translate_dax('IF(Orders[A] = "say ""hi""", 1, 0)', table="Orders")
    assert result.formula is None


def test_an_empty_expression_is_refused_rather_than_translated_to_nothing():
    result = translate_dax("   ", table="Orders")
    assert result.formula is None
    assert result.reason


@pytest.mark.parametrize(
    "expression",
    [
        "CALCULATE(SUM(Orders[Sales]))",
        "DIVIDE(Orders[Sales], Orders[Units])",
        "SUM(Customers[Sales])",
        "",
    ],
)
def test_a_refusal_always_carries_a_reason_and_never_a_formula(expression):
    """An unexplained rejection is the one thing worse than a refusal."""
    result = translate_dax(expression, table="Orders")
    assert result.formula is None
    assert result.reason and result.reason.strip()
    assert result.rule_ids == ()


# --- what is not code ----------------------------------------------------------


def test_a_column_named_after_a_refused_construct_does_not_refuse():
    """`[Filter Cost]` is a column, not a `FILTER`.

    The forward translator masks bracketed names before scanning for markers for
    exactly this reason, and the mirror has to as well.
    """
    assert _formula("SUM(Orders[Filter Cost])") == "SUM([Filter Cost])"


def test_a_function_name_inside_a_string_is_not_translated():
    result = translate_dax('IF(Orders[A] = "AVERAGE(", 1, 0)', table="Orders")
    assert result.formula == 'IIF([A] = "AVERAGE(", 1, 0)'


def test_a_reference_in_a_comment_does_not_refuse_as_cross_table():
    """A line someone commented out is not a dependency, and must not be the
    reason a live expression is held back."""
    assert (
        _formula("SUM(Orders[Sales]) // was Customers[Sales]")
        == "SUM([Sales]) // was Customers[Sales]"
    )


# --- shape ---------------------------------------------------------------------


def test_nothing_it_emits_still_carries_a_table_qualifier():
    """The backstop, mirroring the forward translator's residual-keyword net.

    A qualifier that survives is a field Tableau cannot bind, and the failure is
    only visible once someone opens the workbook.
    """
    result = translate_dax(
        "IF(Orders[Sales] > AVERAGE(Orders[Sales]), UPPER(Orders[Name]), "
        "LOWER(Orders[Name]))",
        table="Orders",
    )
    assert result.formula
    assert "Orders[" not in result.formula


def test_translating_the_same_expression_twice_gives_the_same_answer():
    expression = "AVERAGE(Orders[Sales]) + SUM(Orders[Units])"
    assert translate_dax(expression, table="Orders") == translate_dax(
        expression, table="Orders"
    )


# --- the pack ------------------------------------------------------------------


def test_the_pack_loads_and_is_not_empty():
    assert function_rules()
    assert refusal_rules()


def test_every_rule_id_is_unique_across_both_files():
    ids = [rule.rule_id for rule in (*function_rules(), *refusal_rules())]
    assert len(ids) == len(set(ids))


def test_every_rule_id_names_its_direction():
    """`PBI_..._TO_TABLEAU_...`, the mirror of the forward pack's naming.

    Two packs whose ids look alike is how an audit trail cites a rule from the
    wrong direction and nobody notices.
    """
    for rule in function_rules():
        assert rule.rule_id.startswith("PBI_")
        assert "_TO_TABLEAU_" in rule.rule_id


def test_a_missing_pack_file_raises_rather_than_translating_with_half_a_pack(tmp_path):
    """A lost rule converts one formula fewer and reports it as needing a
    person, which is indistinguishable from a workbook that always did."""
    with pytest.raises(RulePackError):
        load_pack(tmp_path)


def test_a_rule_missing_a_field_raises(tmp_path):
    (tmp_path / "functions.yaml").write_text(
        "functions:\n  - rule_id: PBI_X_TO_TABLEAU_Y\n    version: 1\n    source: X\n",
        encoding="utf-8",
    )
    (tmp_path / "refusals.yaml").write_text("refusals: []\n", encoding="utf-8")
    with pytest.raises(RulePackError):
        load_pack(tmp_path)


def test_a_duplicate_rule_id_raises_because_shadowing_is_silent(tmp_path):
    (tmp_path / "functions.yaml").write_text(
        "functions:\n"
        "  - rule_id: PBI_X_TO_TABLEAU_Y\n    version: 1\n    source: X\n    target: Y\n"
        "  - rule_id: PBI_X_TO_TABLEAU_Y\n    version: 1\n    source: X\n    target: Z\n",
        encoding="utf-8",
    )
    (tmp_path / "refusals.yaml").write_text("refusals: []\n", encoding="utf-8")
    with pytest.raises(RulePackError):
        load_pack(tmp_path)


# --- operators and unrecognised tokens ------------------------------------------
#
# Found by breaking the translator to see which tests noticed: removing the
# unrecognised-token net failed nothing, which meant nothing was checking it.
# Writing the test that should have failed exposed the hole it was meant to
# cover - the net only ever looked at words, and DAX's operators are not words.


def test_a_bare_identifier_is_refused_rather_than_emitted_unchanged():
    """A DAX measure is `[Rate]`; a bare `Rate` is a table, a variable, or a
    mistake. Any of the three produces a formula Tableau cannot compile."""
    result = translate_dax("SUM(Orders[Sales]) * Rate", table="Orders")
    assert result.formula is None
    assert "Rate" in result.reason


def test_the_logical_keywords_tableau_shares_are_left_alone():
    assert (
        _formula("IF(Orders[A] > 0 AND Orders[B] < 1, TRUE, FALSE)")
        == "IIF([A] > 0 AND [B] < 1, TRUE, FALSE)"
    )


def test_the_dax_logical_operators_become_tableau_keywords():
    """`&&` and `||` are not operators in Tableau. Left alone they are not
    ignored - the calculation simply fails to compile, and only when someone
    opens the workbook."""
    assert (
        _formula("IF(Orders[A] > 0 && Orders[B] < 1, 1, 0)")
        == "IIF([A] > 0 AND [B] < 1, 1, 0)"
    )
    assert (
        _formula("IF(Orders[A] > 0 || Orders[B] < 1, 1, 0)")
        == "IIF([A] > 0 OR [B] < 1, 1, 0)"
    )


def test_strict_equality_becomes_ordinary_equality():
    """DAX `==` differs from `=` only in how it treats blank; Tableau has one
    equality operator, and it is the one `=` already means."""
    assert _formula("IF(Orders[A] == 1, 1, 0)") == "IIF([A] = 1, 1, 0)"


def test_string_concatenation_is_refused_rather_than_turned_into_addition():
    """The refusal that a rewrite would get wrong.

    DAX `&` concatenates and coerces both sides to text. Tableau's `+`
    concatenates strings *and adds numbers*, so the same expression over two
    numeric fields would silently return a sum where the source returned a
    string. Same characters, different answer, no error.
    """
    result = translate_dax('Orders[Code] & "-" & Orders[Name]', table="Orders")
    assert result.formula is None
    # The reason has to be the *trap*, not "unknown character": a stray-symbol
    # message would satisfy a test looking only for the "&" and would tell the
    # person reading the report nothing about why no rewrite is offered.
    assert "adds numbers" in result.reason


def test_a_symbol_with_no_tableau_meaning_is_refused():
    """A DAX table constructor is the realistic case: `{1, 2}` is a table, and
    Tableau has no braces at all. Passing the characters through produces a
    formula that fails to compile, which is found by whoever opens the workbook
    rather than by the report."""
    result = translate_dax("IF(Orders[A] IN {1, 2}, 1, 0)", table="Orders")
    assert result.formula is None
    assert "{" in result.reason


def test_the_residual_qualifier_net_catches_a_qualified_field():
    """Removing this net fails no other test, because nothing reaching it is
    currently wrong. It is tested directly so that a later change to reference
    handling cannot emit a qualified field with nothing objecting."""
    from engines.tableau_calc import _residual_qualifier

    assert _residual_qualifier("SUM([Sales])") is None
    caught = _residual_qualifier("SUM(Orders[Sales])")
    assert caught is not None
    assert caught.formula is None
    assert caught.reason
